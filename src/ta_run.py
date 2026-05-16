"""
Wrapper for TradingAgents analysis called by the Streamlit dashboard.

Emits newline-delimited JSON to stdout for structured results.
Emits log lines to stderr.

Usage:
    python ta_run.py --tickers AAPL,NVDA --date 2026-01-15 [options]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
from datetime import datetime as _dt
from pathlib import Path

# ── path setup: TradingAgents root must be importable ────────────────────────
_TA_ROOT = Path(__file__).parent.parent / "external" / "TradingAgents"
_REPORTS_DIR = _TA_ROOT.parent.parent / "reports"
if str(_TA_ROOT) not in sys.path:
    sys.path.insert(0, str(_TA_ROOT))

# Load TradingAgents .env (API keys for LLM providers) before importing
from dotenv import load_dotenv
load_dotenv(_TA_ROOT / ".env", override=False)
load_dotenv(_TA_ROOT / ".env.enterprise", override=False)

_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
_SEP = "═" * 56
_THIN = "─" * 56


def _emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        s = value.strip()
        return not s or s.lower() in ("none", "null", "{}", "[]", "n/a")
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


class _CallTracker:
    """Thread-safe LangChain callback handler — tracks LLM + tool calls."""

    from langchain_core.callbacks import BaseCallbackHandler

    class _Inner(BaseCallbackHandler):
        def __init__(self, tracker: "_CallTracker", logger: logging.Logger) -> None:
            super().__init__()
            self._tracker = tracker
            self._logger = logger
            self._local = threading.local()

        def on_chat_model_start(self, serialized, _messages, **kwargs) -> None:  # type: ignore[override]
            meta = kwargs.get("metadata") or {}
            node = meta.get("langgraph_node", "unknown")
            analyst = meta.get("analyst_type", "")
            # Extract model name from serialized info
            model = (
                (serialized or {}).get("kwargs", {}).get("model")
                or (serialized or {}).get("kwargs", {}).get("model_name")
                or (serialized or {}).get("name")
                or ((serialized or {}).get("id") or ["unknown"])[-1]
            )
            with self._tracker._lock:
                self._tracker.total += 1
                self._tracker.per_node[node] = self._tracker.per_node.get(node, 0) + 1
            if analyst:
                self._logger.info("[LLM] node=%-30s analyst=%-15s model=%s", node, analyst, model)
            else:
                self._logger.info("[LLM] node=%-30s model=%s", node, model)

        def on_llm_end(self, response, **kwargs) -> None:
            try:
                if not (hasattr(response, "generations") and response.generations):
                    return
                gen = response.generations[0]
                if not gen:
                    return
                g = gen[0]
                # Tool-call responses have empty text — not an error, skip
                msg = getattr(g, "message", None)
                if msg and getattr(msg, "tool_calls", None):
                    return
                text = getattr(g, "text", "") or ""
                if not text and msg:
                    content = getattr(msg, "content", "")
                    text = content if isinstance(content, str) else str(content)
                if _is_empty(text):
                    _meta = kwargs.get("metadata") or {}
                    node = _meta.get("langgraph_node", "unknown")
                    self._logger.warning(
                        "%s[WARNING] LLM returned empty response | node=%s%s",
                        _RED, node, _RESET,
                    )
            except Exception:
                pass

        def on_tool_start(self, serialized, input_str, **kwargs) -> None:
            tool_name = (serialized or {}).get("name", "unknown_tool")
            short_in = str(input_str)[:100].replace("\n", " ")
            if len(str(input_str)) > 100:
                short_in += "..."
            self._logger.info("[TOOL →] %-30s  %s", tool_name, short_in)
            with self._tracker._lock:
                self._tracker.tool_calls.append(tool_name)
                self._tracker.tool_call_count += 1

        def on_tool_end(self, output, **kwargs) -> None:
            tool_name = kwargs.get("name", "")
            if not tool_name:
                with self._tracker._lock:
                    tool_name = self._tracker.tool_calls[-1] if self._tracker.tool_calls else "unknown_tool"
            if _is_empty(output):
                self._logger.warning(
                    "%s[WARNING] Tool returned no data   | tool=%s%s",
                    _RED, tool_name, _RESET,
                )
            else:
                self._logger.info("[TOOL ←] %-30s  %d chars", tool_name, len(str(output)))

        def on_tool_error(self, error, **kwargs) -> None:
            tool_name = kwargs.get("name", "unknown_tool")
            self._logger.warning(
                "%s[WARNING] Tool error               | tool=%s | %s%s",
                _RED, tool_name, str(error)[:150], _RESET,
            )

    def __init__(self, logger: logging.Logger) -> None:
        self._lock = threading.Lock()
        self.total = 0
        self.per_node: dict[str, int] = {}
        self.tool_calls: list[str] = []
        self.tool_call_count = 0
        self._logger = logger

    def handler(self) -> "BaseCallbackHandler":
        return _CallTracker._Inner(self, self._logger)


def _save_report(final_state: dict, ticker: str, date: str, save_path: Path) -> Path:
    save_path.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []

    analysts_dir = save_path / "1_analysts"
    analyst_parts: list[tuple[str, str]] = []
    for field, fname, label in [
        ("market_report",       "market.md",       "Market Analyst"),
        ("sentiment_report",    "sentiment.md",    "Social Analyst"),
        ("news_report",         "news.md",         "News Analyst"),
        ("fundamentals_report", "fundamentals.md", "Fundamentals Analyst"),
    ]:
        text = final_state.get(field, "")
        if text:
            analysts_dir.mkdir(exist_ok=True)
            (analysts_dir / fname).write_text(text, encoding="utf-8")
            analyst_parts.append((label, text))
    if analyst_parts:
        body = "\n\n".join(f"### {n}\n{t}" for n, t in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{body}")

    if final_state.get("investment_plan"):
        research_dir = save_path / "2_research"
        research_dir.mkdir(exist_ok=True)
        (research_dir / "plan.md").write_text(final_state["investment_plan"], encoding="utf-8")
        sections.append(f"## II. Research Team Decision\n\n{final_state['investment_plan']}")

    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"], encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n{final_state['trader_investment_plan']}")

    if final_state.get("final_trade_decision"):
        decision_dir = save_path / "4_decision"
        decision_dir.mkdir(exist_ok=True)
        (decision_dir / "decision.md").write_text(final_state["final_trade_decision"], encoding="utf-8")
        sections.append(f"## IV. Final Decision\n\n{final_state['final_trade_decision']}")

    header = (
        f"# Trading Analysis Report: {ticker}\n\n"
        f"Date: {date}\nGenerated: {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    report_file = save_path / "complete_report.md"
    report_file.write_text(header + "\n\n".join(sections), encoding="utf-8")
    return report_file


def _summarise_report(report_text: str, llm, label: str, logger: logging.Logger) -> list[str]:
    if not report_text or not report_text.strip():
        return ["• (no report generated)"]
    prompt = (
        "Summarize the following analyst report in exactly 3 concise bullet points.\n"
        "Each bullet must be a single short sentence. "
        "Use '•' as the bullet character. "
        "Output only the 3 bullets — no preamble, no numbering, no extra text.\n\n"
        f"{report_text}"
    )
    logger.debug("Summarising %s ...", label)
    response = llm.invoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)
    bullets = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    bullets = [b if b.startswith("•") else f"• {b}" for b in bullets]
    if len(bullets) < 3:
        bullets += ["• (no additional data)"] * (3 - len(bullets))
    return bullets[:3]


_ANALYST_ORDER = ["market", "social", "news", "fundamentals"]
_ANALYST_REPORT_FIELDS = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}
_ALWAYS_REQUIRED_FIELDS = {
    "investment_plan": "Investment Plan",
    "trader_investment_plan": "Trader Plan",
    "final_trade_decision": "Final Decision",
}


def _run_ticker(
    ticker: str,
    date: str,
    selected_analysts: list[str],
    config: dict,
    logger: logging.Logger,
) -> dict:
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    tracker = _CallTracker(logger)
    graph = TradingAgentsGraph(
        selected_analysts,
        config=config,
        debug=False,
        callbacks=[tracker.handler()],
    )

    init_state = graph.propagator.create_initial_state(ticker, date)
    graph_args = graph.propagator.get_graph_args()

    final_state = asyncio.run(graph.graph.ainvoke(init_state, **graph_args))
    graph.curr_state = final_state
    graph.ticker = ticker
    graph._log_state(date, final_state)
    decision = graph.process_signal(final_state.get("final_trade_decision", ""))

    # Warn on missing/empty report sections
    for analyst_key, field in _ANALYST_REPORT_FIELDS.items():
        if analyst_key not in selected_analysts:
            continue
        if _is_empty(final_state.get(field)):
            logger.warning(
                "%s[WARNING] Empty report section: %s (field=%s)%s",
                _RED, analyst_key, field, _RESET,
            )

    for field, label in _ALWAYS_REQUIRED_FIELDS.items():
        if _is_empty(final_state.get(field)):
            logger.warning(
                "%s[WARNING] Missing output: %s%s", _RED, label, _RESET,
            )

    summaries: dict[str, str] = {}
    for field, label in [
        ("market_report", "Market Analysis"),
        ("sentiment_report", "Social Sentiment"),
        ("news_report", "News Analysis"),
        ("fundamentals_report", "Fundamentals"),
    ]:
        text = (final_state.get(field) or "").strip()
        if text:
            summaries[label] = text

    # ── Save report to disk ───────────────────────────────────────────────────
    _ts = _dt.now().strftime("%H%M%S")
    results_dir = _REPORTS_DIR / ticker / f"{date}_{_ts}"
    report_path: str | None = None
    try:
        report_file = _save_report(final_state, ticker, date, results_dir)
        report_path = str(report_file)
        logger.info("[REPORT] Saved → %s", report_file)
    except Exception as exc:
        logger.warning("[REPORT] Save failed: %s", exc)

    # ── Bullet summaries via quick-think LLM ─────────────────────────────────
    bullet_summaries: dict[str, list[str]] = {}
    try:
        from tradingagents.llm_clients.factory import create_llm_client
        _summary_llm = create_llm_client(
            config["llm_provider"],
            config["quick_think_llm"],
            config.get("backend_url"),
        ).get_llm()
        for field, label in [
            ("market_report",       "Market Analysis"),
            ("sentiment_report",    "Social Sentiment"),
            ("news_report",         "News Analysis"),
            ("fundamentals_report", "Fundamentals"),
            ("final_trade_decision", "Final Decision"),
        ]:
            text = (final_state.get(field) or "").strip()
            if text:
                bullet_summaries[label] = _summarise_report(text, _summary_llm, f"{ticker}/{label}", logger)
    except Exception as exc:
        logger.warning("[SUMMARY] Failed: %s", exc)

    # ── Save metadata.json ───────────────────────────────────────────────────
    if results_dir.exists():
        try:
            import json as _json_mod
            _metadata = {
                "ticker": ticker,
                "date": date,
                "decision": decision,
                "llm_calls": tracker.total,
                "generated_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "bullet_summaries": bullet_summaries,
            }
            (results_dir / "metadata.json").write_text(
                _json_mod.dumps(_metadata, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("[REPORT] metadata.json save failed: %s", exc)

    return {
        "type": "ticker_result",
        "ticker": ticker,
        "decision": decision,
        "summaries": summaries,
        "investment_plan": (final_state.get("investment_plan") or "").strip(),
        "trader_plan": (final_state.get("trader_investment_plan") or "").strip(),
        "final_decision": (final_state.get("final_trade_decision") or "").strip(),
        "llm_calls": tracker.total,
        "per_node": tracker.per_node,
        "tool_call_count": tracker.tool_call_count,
        "report_path": report_path,
        "bullet_summaries": bullet_summaries,
    }


def _print_summary(
    summary_rows: list[dict],
    total_llm_calls: int,
    total_per_node: dict[str, int],
    logger: logging.Logger,
) -> None:
    logger.info(_SEP)
    logger.info("%sANALYSIS COMPLETE%s", _BOLD, _RESET)
    logger.info(_SEP)
    logger.info("%-10s  %s", "TICKER", "DECISION")
    logger.info(_THIN)
    for row in summary_rows:
        d = row["decision"]
        color = _RED if d == "SELL" else (_GREEN if d == "BUY" else _YELLOW)
        logger.info("%-10s  %s%s%s", row["ticker"], color, d, _RESET)
    logger.info(_THIN)
    logger.info("Total LLM calls : %d", total_llm_calls)
    if total_per_node:
        logger.info("LLM calls by node:")
        for node, count in sorted(total_per_node.items(), key=lambda x: -x[1]):
            logger.info("  %-38s %3d", node, count)
    logger.info(_SEP)


def main() -> None:
    parser = argparse.ArgumentParser(description="TradingAgents CLI wrapper")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers")
    parser.add_argument("--date", required=True, help="Analysis date YYYY-MM-DD")
    parser.add_argument("--skip", default="", help="Comma-separated analysts to skip")
    parser.add_argument("--llm-provider", default="deepseek")
    parser.add_argument("--deep-model", default="deepseek-v4-pro")
    parser.add_argument("--quick-model", default="deepseek-v4-pro")
    parser.add_argument("--core-api", default="alpha_vantage")
    parser.add_argument("--technical-api", default="alpha_vantage")
    parser.add_argument("--fundamental-api", default="alpha_vantage")
    parser.add_argument("--news-api", default="google")
    parser.add_argument("--debate-rounds", type=int, default=1)
    parser.add_argument("--risk-rounds", type=int, default=1)
    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logger = logging.getLogger("ta_run")

    import news_cache
    news_cache.install()

    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = args.llm_provider
    config["deep_think_llm"] = args.deep_model
    config["quick_think_llm"] = args.quick_model
    config["data_vendors"] = {
        "core_stock_apis": args.core_api,
        "technical_indicators": args.technical_api,
        "fundamental_data": args.fundamental_api,
        "news_data": args.news_api,
    }
    config["max_debate_rounds"] = args.debate_rounds
    config["max_risk_discuss_rounds"] = args.risk_rounds

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    skip_set = {s.strip().lower() for s in args.skip.split(",") if s.strip()}
    selected_analysts = [a for a in _ANALYST_ORDER if a not in skip_set]

    if not tickers:
        logger.error("No tickers provided")
        sys.exit(1)
    if not selected_analysts:
        logger.error("All analysts skipped")
        sys.exit(1)

    # ── Configuration summary ─────────────────────────────────────────────────
    logger.info(_SEP)
    logger.info("[CONFIG] LLM provider  : %s", args.llm_provider)
    logger.info("[CONFIG] Deep model    : %s", args.deep_model)
    logger.info("[CONFIG] Quick model   : %s", args.quick_model)
    logger.info("[CONFIG] Data sources  : core=%-15s technical=%-15s", args.core_api, args.technical_api)
    logger.info("[CONFIG]                 fundamental=%-15s news=%s", args.fundamental_api, args.news_api)
    logger.info("[CONFIG] Analysts      : %s", ", ".join(selected_analysts))
    logger.info("[CONFIG] Debate rounds : %d  |  Risk rounds: %d", args.debate_rounds, args.risk_rounds)
    logger.info(_SEP)

    _emit({"type": "start", "tickers": tickers, "date": args.date, "analysts": selected_analysts})
    logger.info("Starting | tickers=%s  date=%s", tickers, args.date)

    total_llm_calls = 0
    total_per_node: dict[str, int] = {}
    summary_rows: list[dict] = []

    for ticker in tickers:
        logger.info(_THIN)
        logger.info("[%s] Starting analysis", ticker)
        _emit({"type": "ticker_start", "ticker": ticker})
        try:
            result = _run_ticker(ticker, args.date, selected_analysts, config, logger)
            _emit(result)
            total_llm_calls += result["llm_calls"]
            for node, cnt in result["per_node"].items():
                total_per_node[node] = total_per_node.get(node, 0) + cnt
            summary_rows.append({"ticker": ticker, "decision": result["decision"]})
            logger.info(
                "[%s] Done | decision=%s | LLM calls=%d | tool calls=%d",
                ticker,
                result["decision"],
                result["llm_calls"],
                result.get("tool_call_count", 0),
            )
            if result.get("report_path"):
                logger.info("[%s] Report → %s", ticker, result["report_path"])
            bullet_summaries = result.get("bullet_summaries") or {}
            if bullet_summaries:
                logger.info("[%s] ── Quick Summary ──────────────────────────────", ticker)
                for section, bullets in bullet_summaries.items():
                    logger.info("[%s]   %s", ticker, section)
                    for b in bullets:
                        logger.info("[%s]     %s", ticker, b)
        except Exception as exc:
            logger.error("[%s] Failed: %s", ticker, exc, exc_info=True)
            _emit({"type": "ticker_error", "ticker": ticker, "error": str(exc)})
            summary_rows.append({"ticker": ticker, "decision": "ERROR"})

    _emit({
        "type": "done",
        "total_llm_calls": total_llm_calls,
        "per_node": total_per_node,
        "summary": summary_rows,
    })

    _print_summary(summary_rows, total_llm_calls, total_per_node, logger)


if __name__ == "__main__":
    main()
