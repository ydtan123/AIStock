"""DeepEvaluationStep — step 4 of the pipeline."""
from __future__ import annotations

import datetime as dt
import logging
import traceback

from sqlalchemy import desc

from models import DeepEvaluationRow, FastEvaluationConclusion
from pipeline.backends.deep_evaluators import DEEP_EVALUATOR_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult, open_session


_NAMED_SLOTS = (
    "market_report",
    "bull_argument",
    "bear_argument",
    "research_manager_decision",
    "trader_plan",
)

_REPORT_SECTIONS: list[tuple[str, str]] = [
    ("market_report", "Market Analyst"),
    ("social_report", "Social / Sentiment Analyst"),
    ("news_report", "News Analyst"),
    ("fundamentals_report", "Fundamentals Analyst"),
    ("bull_argument", "Bull Researcher Debate"),
    ("bear_argument", "Bear Researcher Debate"),
    ("research_manager_decision", "Research Manager Decision"),
    ("trader_plan", "Trader Investment Plan"),
    ("risk_aggressive", "Risk Debate — Aggressive"),
    ("risk_conservative", "Risk Debate — Conservative"),
    ("risk_neutral", "Risk Debate — Neutral"),
    ("risk_manager_decision", "Risk Manager Final Decision"),
]


def _extract_key_point(text: str, max_chars: int = 200) -> str:
    """Extract the first meaningful sentence(s) from an agent's output."""
    t = text.strip()
    if len(t) <= max_chars:
        return t
    # Try breaking at sentence boundary within max_chars
    cut = t[:max_chars]
    for sep in (". ", ".\n", "! ", "?\n", "\n\n"):
        idx = cut.rfind(sep)
        if idx > 50:
            return t[:idx + 1] + "..."
    return cut.rsplit(" ", 1)[0] + "..."


def _get_summary_llm(cfg: dict | None):
    """Create a lightweight LLM for report summarisation.

    Reads ``summary_model`` / ``summary_provider`` from the deep_evaluation
    trading_agents config.  Defaults to ``deepseek-chat`` / ``deepseek`` so
    no thinking-mode overhead is incurred.  Returns ``None`` if config is
    missing or the LLM cannot be created — callers fall back to
    ``_extract_key_point``.
    """
    if cfg is None:
        return None
    ta_cfg = cfg.get("deep_evaluation", {}).get("trading_agents", {})
    provider = ta_cfg.get("summary_provider", "deepseek")
    model = ta_cfg.get("summary_model", "deepseek-chat")
    try:
        from tradingagents.llm_clients import create_llm_client
        client = create_llm_client(provider, model)
        return client.get_llm()
    except Exception:
        return None


def _summarise_report(
    report_text: str,
    llm,
    label: str,
    logger: logging.Logger | None = None,
) -> list[str]:
    """Call the summarisation LLM and return exactly 3 bullet-point strings.

    Mirrors ``_summarise_report`` in ``TradingAgents/cli/main.py``.
    Falls back to text truncation on any failure.
    """
    if not report_text or not report_text.strip():
        return ["• (no report generated)"]
    prompt = (
        "Summarize the following analyst report in exactly 3 concise bullet points.\n"
        "Each bullet must be a single short sentence. "
        "Use '•' as the bullet character. "
        "Output only the 3 bullets — no preamble, no numbering, no extra text.\n\n"
        f"{report_text}"
    )
    try:
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        if logger:
            logger.warning("Summarisation failed for %s: %s", label, exc)
        return [_extract_key_point(report_text)]
    bullets = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    bullets = [b if b.startswith("•") else f"• {b}" for b in bullets]
    if len(bullets) < 3:
        bullets += ["• (no additional data)"] * (3 - len(bullets))
    return bullets[:3]


# Per-section subfolder layout mirroring TradingAgents CLI's save_report_to_disk
_SECTION_LAYOUT: dict[str, tuple[str, str]] = {
    "market_report":              ("1_analysts", "market.md"),
    "social_report":              ("1_analysts", "social.md"),
    "news_report":                ("1_analysts", "news.md"),
    "fundamentals_report":        ("1_analysts", "fundamentals.md"),
    "bull_argument":              ("2_research", "bull_argument.md"),
    "bear_argument":              ("2_research", "bear_argument.md"),
    "research_manager_decision":  ("2_research", "manager_decision.md"),
    "trader_plan":                ("3_trading", "trader_plan.md"),
    "risk_aggressive":            ("4_risk", "aggressive.md"),
    "risk_conservative":          ("4_risk", "conservative.md"),
    "risk_neutral":               ("4_risk", "neutral.md"),
    "risk_manager_decision":      ("4_risk", "risk_manager_decision.md"),
}


def _write_report(evaluations, report_dir, backend_name, cfg=None):
    """Write per-ticker deep evaluation reports with organised subfolders.

    Creates per-ticker directory structure::

        <run_id>/<TICKER>/
        ├── 1_analysts/       market.md, social.md, news.md, fundamentals.md
        ├── 2_research/        bull_argument.md, bear_argument.md, manager_decision.md
        ├── 3_trading/         trader_plan.md
        ├── 4_risk/            aggressive.md, conservative.md, neutral.md,
        │                      risk_manager_decision.md
        ├── summary.md         ← 3-bullet per-section summary + decision + API stats
        └── complete_report.md ← full concatenated report

    Also writes legacy flat files (``deep_evaluation_<TICKER>.md``,
    ``deep_evaluation.md``) at *report_dir* for backward compatibility.
    """
    summary_llm = _get_summary_llm(cfg)
    logger = logging.getLogger(__name__)
    summary_call_count = 0

    _EMOJI = {"BUY": "\U0001f7e2", "SELL": "\U0001f534", "HOLD": "\U0001f7e1"}

    for ev in evaluations:
        ticker = ev.ticker
        decision = ev.final_decision or "N/A"
        emoji = _EMOJI.get(decision.upper(), "⚪")
        ticker_dir = report_dir / ticker / "deep_evaluation"

        # --- write per-section files into organised subfolders ---
        for slot_key, (subdir, filename) in _SECTION_LAYOUT.items():
            content = ev.agent_outputs.get(slot_key, "").strip()
            if not content:
                continue
            folder = ticker_dir / subdir
            folder.mkdir(parents=True, exist_ok=True)
            (folder / filename).write_text(content, encoding="utf-8")

        # --- LLM 3-bullet summary per section ---
        bullet_rows: list[tuple[str, str, str]] = []
        for slot_key, section_title in _REPORT_SECTIONS:
            content = ev.agent_outputs.get(slot_key, "").strip()
            if not content:
                continue
            if summary_llm:
                try:
                    bullets = _summarise_report(content, summary_llm, f"{ticker}/{slot_key}", logger)
                    summary_call_count += 1
                except Exception:
                    bullets = [_extract_key_point(content)]
            else:
                bullets = [_extract_key_point(content)]
            bullet_rows.append((section_title, "  \n".join(bullets), slot_key))

        # --- API call stats ---
        api_stats = ev.extra_outputs.get("api_call_stats", {})
        per_node: dict = api_stats.get("per_node", {})
        total_analysis_calls = api_stats.get("total_llm_calls", len(per_node))

        # --- summary.md ---
        summary_lines = [
            f"# Deep Evaluation: {ticker}",
            "",
            f"**Backend:** {backend_name}",
            f"**Date:** {ev.evaluation_date}",
            f"**Final Decision:** {emoji} {decision}",
            "",
            "---",
            "",
            "## 📊 Summary of Key Points",
            "",
            "| Analyst | Key Points |",
            "|---------|------------|",
        ]
        for title, points, _ in bullet_rows:
            safe = points.replace("|", "\\|").replace("\n", "  \n")
            summary_lines.append(f"| {title} | {safe} |")

        summary_lines.extend([
            "",
            "## 📈 LLM API Call Statistics",
            "",
            f"| Category | Count |",
            f"|----------|-------|",
            f"| Analysis-phase LLM calls (per agent) | {total_analysis_calls} |",
            f"| Summarisation LLM calls | {summary_call_count} |",
            f"| **Total** | **{total_analysis_calls + summary_call_count}** |",
            "",
        ])
        if per_node:
            summary_lines.append("### Analysis-phase breakdown by agent")
            summary_lines.append("")
            summary_lines.append("| Agent / Node | Calls |")
            summary_lines.append("|-------------|-------|")
            for node, count in sorted(per_node.items(), key=lambda x: -x[1]):
                summary_lines.append(f"| {node} | {count} |")
            summary_lines.append("")
        else:
            sections_with_content = sum(1 for _, _, _ in bullet_rows)
            summary_lines.extend([
                "_Note: Per-agent breakdown unavailable. "
                f"{sections_with_content} agent sections completed._",
                "",
            ])

        (ticker_dir / "summary.md").write_text(
            "\n".join(summary_lines), encoding="utf-8"
        )

        # --- complete_report.md (all sections concatenated) ---
        complete = [
            f"# {ticker} — Complete Analysis Report",
            "",
            f"**Backend:** {backend_name}",
            f"**Date:** {ev.evaluation_date}",
            f"**Final Decision:** {emoji} {decision}",
            "",
            "---",
            "",
        ]
        for slot_key, section_title in _REPORT_SECTIONS:
            content = ev.agent_outputs.get(slot_key, "").strip()
            if not content:
                continue
            complete.append(f"## {section_title}")
            complete.append("")
            complete.append(content)
            complete.append("")
            complete.append("---")
            complete.append("")
        (ticker_dir / "complete_report.md").write_text(
            "\n".join(complete), encoding="utf-8"
        )

        # --- legacy flat per-ticker report ---
        (report_dir / f"deep_evaluation_{ticker}.md").write_text(
            "\n".join(complete), encoding="utf-8"
        )

    # --- legacy combined all-ticker report ---
    combined = [
        f"# Deep Evaluation Report — {backend_name}",
        "",
        f"**Date:** {dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC",
        f"**Tickers evaluated:** {len(evaluations)}",
        "",
        "---",
        "",
    ]
    for ev in evaluations:
        decision = ev.final_decision or "N/A"
        emoji = _EMOJI.get(decision.upper(), "⚪")
        combined.append(f"## {ev.ticker} — {emoji} {decision}")
        combined.append("")
        for slot_key, section_title in _REPORT_SECTIONS:
            content = ev.agent_outputs.get(slot_key, "").strip()
            if not content:
                continue
            combined.append(f"### {section_title}")
            combined.append("")
            combined.append(content)
            combined.append("")
        combined.append("---")
        combined.append("")

    combined_path = report_dir / "deep_evaluation.md"
    combined_path.write_text("\n".join(combined), encoding="utf-8")
    return combined_path


class DeepEvaluationStep(PipelineStep):
    name = "deep_evaluation"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)
        backend_name = sub.get("backend", "trading_agents")
        top_n = int(sub.get("top_n", 3))

        try:
            evaluator_cls = DEEP_EVALUATOR_REGISTRY.get(backend_name)
        except KeyError as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=str(e),
            )

        # deep_evaluation.symbols overrides top_n when non-empty.
        # Accepts a list (from config.yaml) or comma-separated string (from web app).
        symbols_cfg = sub.get("symbols", None)
        if isinstance(symbols_cfg, str):
            symbols_override = [s.strip().upper() for s in symbols_cfg.split(",") if s.strip()]
        elif isinstance(symbols_cfg, list):
            symbols_override = [s.strip().upper() for s in symbols_cfg if s.strip()]
        else:
            symbols_override = []

        if symbols_override:
            tickers = symbols_override
            ctx.logger.info(
                "DeepEvaluationStep: symbols override — %d tickers: %s",
                len(tickers), tickers,
            )
        else:
            # Fall back to pipeline-level --symbols flag (CLI), then top_n from DB.
            pipeline_symbols = ctx.cfg.get("pipeline", {}).get("symbols", [])
            if pipeline_symbols:
                tickers = pipeline_symbols[:top_n]
                ctx.logger.info("DeepEvaluationStep: using --symbols (%d tickers)", len(tickers))
            else:
                with open_session(ctx) as session:
                    rows = (
                        session.query(FastEvaluationConclusion)
                        .filter(FastEvaluationConclusion.pipeline_run_id == ctx.run_id)
                        .order_by(desc(FastEvaluationConclusion.consensus_score))
                        .limit(top_n)
                        .all()
                    )
                    tickers = [r.ticker for r in rows]

        if not tickers:
            return StepResult(
                step_name=self.name,
                status="success",
                summary={"backend": backend_name, "note": "no upstream tickers"},
                payload={"backend": backend_name, "evaluations": []},
            )

        evaluator_cfg = sub.get(backend_name, {})
        try:
            evaluator = evaluator_cls(cfg=evaluator_cfg)
            evaluations = evaluator.evaluate(tickers, ctx)
        except Exception as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            )

        with open_session(ctx) as session:
            rows: list[DeepEvaluationRow] = []
            for ev in evaluations:
                slot_kwargs = {slot: ev.agent_outputs.get(slot) for slot in _NAMED_SLOTS}
                overflow = {k: v for k, v in ev.agent_outputs.items() if k not in _NAMED_SLOTS}
                merged_extras = {**overflow, **(ev.extra_outputs or {})}
                eval_date = (
                    dt.datetime.fromisoformat(ev.evaluation_date)
                    if "T" in ev.evaluation_date
                    else dt.datetime.strptime(ev.evaluation_date, "%Y-%m-%d")
                )
                rows.append(DeepEvaluationRow(
                    pipeline_run_id=ctx.run_id,
                    ticker=ev.ticker,
                    backend=backend_name,
                    evaluation_date=eval_date,
                    extra_outputs=merged_extras,
                    final_decision=ev.final_decision,
                    model_name=evaluator_cfg.get("model_name"),
                    **slot_kwargs,
                ))
            session.add_all(rows)
            session.commit()

        report_path = _write_report(evaluations, ctx.report_dir, backend_name, ctx.cfg)
        ctx.logger.info("Deep evaluation report saved → %s", report_path)

        ev_list = [
            {"ticker": ev.ticker, "final_decision": ev.final_decision}
            for ev in evaluations
        ]
        return StepResult(
            step_name=self.name,
            status="success",
            summary={
                "backend": backend_name,
                "tickers_evaluated": len(evaluations),
            },
            payload={"backend": backend_name, "evaluations": ev_list},
        )
