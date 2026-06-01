"""DeepEvaluator ABC + DeepEvaluation + TradingAgentsDeepEvaluator + registry."""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pipeline.backends.selectors import _Registry
from pipeline.base import RegisteredBackend, StepContext

logger = logging.getLogger(__name__)


@dataclass
class DeepEvaluation:
    ticker: str
    evaluation_date: str
    agent_outputs: dict[str, str]
    extra_outputs: dict[str, Any] = field(default_factory=dict)
    final_decision: str = ""


DEEP_EVALUATOR_REGISTRY = _Registry("deep_evaluator")


class DeepEvaluator(RegisteredBackend):
    name: str = ""

    @abstractmethod
    def evaluate(self, tickers: list[str], ctx: StepContext) -> list[DeepEvaluation]: ...


# --- Concrete backend: TradingAgentsDeepEvaluator ----------------------------

_FINAL_STATE_TO_SLOT = {
    "market_report": "market_report",
    "sentiment_report": "social_report",
    "news_report": "news_report",
    "fundamentals_report": "fundamentals_report",
    "bull_argument": "bull_argument",
    "bear_argument": "bear_argument",
    "investment_plan": "research_manager_decision",
    "trader_investment_plan": "trader_plan",
    "risk_debate_aggressive": "risk_aggressive",
    "risk_debate_conservative": "risk_conservative",
    "risk_debate_neutral": "risk_neutral",
    "final_trade_decision": "risk_manager_decision",
}


def _inject_api_keys(ctx_cfg: dict) -> None:
    common = ctx_cfg.get("common", {})
    av_key = (
        common.get("alpha_vantage_api_key")
        or ctx_cfg.get("data_update", {}).get("alpha_vantage", {}).get("api_key")
        or ctx_cfg.get("alpha_vantage", {}).get("api_key")
    )
    mapping = {
        "DEEPSEEK_API_KEY": common.get("deepseek_api_key"),
        "OPENAI_API_KEY": common.get("openai_api_key"),
        "ANTHROPIC_API_KEY": common.get("anthropic_api_key"),
        "GOOGLE_API_KEY": common.get("google_api_key"),
        "ALPHA_VANTAGE_API_KEY": av_key,
    }
    for env_var, value in mapping.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value


def _install_news_cache() -> None:
    """Indirection seam — tests monkeypatch this."""
    from news_cache import install
    install()


def _build_graph(**kwargs):
    """Indirection seam — tests monkeypatch this."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    return TradingAgentsGraph(**kwargs)


def _extract_decision(final_state: dict, fallback_decision: str | None) -> str:
    for key in ("final_trade_decision", "trader_investment_plan"):
        text = final_state.get(key, "") or ""
        upper = text.upper()
        for token in ("BUY", "SELL", "HOLD"):
            if token in upper:
                return token
    if fallback_decision:
        upper = fallback_decision.upper()
        for token in ("BUY", "SELL", "HOLD"):
            if token in upper:
                return token
    return ""


@DEEP_EVALUATOR_REGISTRY.register
class TradingAgentsDeepEvaluator(DeepEvaluator):
    name = "trading_agents"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def evaluate(
        self, tickers: list[str], ctx: StepContext
    ) -> list[DeepEvaluation]:
        if not tickers:
            ctx.logger.warning("TradingAgentsDeepEvaluator: empty tickers list")
            return []

        sub = self.cfg or ctx.cfg.get("deep_evaluation", {}).get("trading_agents", {})

        _inject_api_keys(ctx.cfg)

        if sub.get("use_news_cache", True):
            try:
                _install_news_cache()
            except Exception as e:
                ctx.logger.warning("news_cache install failed: %s", e)

        eval_date = sub.get("evaluation_date") or datetime.now().strftime("%Y-%m-%d")
        analysts = sub.get("selected_analysts") or [
            "market", "social", "news", "fundamentals"
        ]

        deep_model = sub.get("model_name", "deepseek-v4-pro")
        ta_cfg: dict[str, Any] = {
            "llm_provider": sub.get("model_provider", "deepseek"),
            "deep_think_llm": deep_model,
            "quick_think_llm": sub.get("quick_model") or deep_model,
            "data_cache_dir": sub.get("data_cache_dir", "data/tradingagents_cache"),
            "results_dir": sub.get("results_dir", "reports/tradingagents"),
            "max_debate_rounds": sub.get("max_debate_rounds", 1),
            "max_risk_discuss_rounds": sub.get("max_risk_discuss_rounds", 1),
            "checkpoint_enabled": sub.get("checkpoint_enabled", False),
        }
        ta_cfg = {k: v for k, v in ta_cfg.items() if v is not None}

        from tradingagents.graph.call_tracker import PerAgentCallTracker

        tracker = PerAgentCallTracker()

        graph = _build_graph(
            selected_analysts=analysts,
            debug=sub.get("debug", False),
            config=ta_cfg,
            callbacks=[tracker],
        )

        def _evaluate_one(tkr: str):
            """Evaluate a single ticker. Returns (ticker, result) or (ticker, None, error_str)."""
            try:
                result = graph.propagate(tkr, eval_date)
                return tkr, result, None
            except Exception as e:
                return tkr, None, str(e)

        out: list[DeepEvaluation] = []
        max_workers = min(len(tickers), 3)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_evaluate_one, t): t for t in tickers}
            for future in as_completed(futures):
                ticker, result, error = future.result(timeout=300)
                if error:
                    ctx.logger.exception("TradingAgents failed for %s: %s", ticker, error)
                    continue

                if isinstance(result, tuple) and len(result) == 2:
                    final_state, decision = result
                else:
                    final_state, decision = result, None
                final_state = final_state or {}

                agent_outputs: dict[str, str] = {}
                extras: dict[str, Any] = {}
                for src_key, value in final_state.items():
                    slot = _FINAL_STATE_TO_SLOT.get(src_key)
                    if slot:
                        agent_outputs[slot] = value if isinstance(value, str) else str(value)
                    elif src_key == "messages":
                        pass  # LangChain message objects are not JSON-serializable
                    elif isinstance(value, (str, int, float, bool)) or value is None:
                        extras[src_key] = value

                # Extract bull/bear from nested investment_debate_state
                invest_debate = final_state.get("investment_debate_state") or {}
                if isinstance(invest_debate, dict):
                    if invest_debate.get("bull_history"):
                        agent_outputs["bull_argument"] = invest_debate["bull_history"]
                    if invest_debate.get("bear_history"):
                        agent_outputs["bear_argument"] = invest_debate["bear_history"]

                # Extract risk analysts from nested risk_debate_state
                risk_debate = final_state.get("risk_debate_state") or {}
                if isinstance(risk_debate, dict):
                    if risk_debate.get("aggressive_history"):
                        agent_outputs.setdefault("risk_aggressive", risk_debate["aggressive_history"])
                    if risk_debate.get("conservative_history"):
                        agent_outputs.setdefault("risk_conservative", risk_debate["conservative_history"])
                    if risk_debate.get("neutral_history"):
                        agent_outputs.setdefault("risk_neutral", risk_debate["neutral_history"])
                    if risk_debate.get("judge_decision"):
                        agent_outputs.setdefault("risk_manager_decision", risk_debate["judge_decision"])

                out.append(
                    DeepEvaluation(
                        ticker=ticker,
                        evaluation_date=eval_date,
                        agent_outputs=agent_outputs,
                        extra_outputs=extras,
                        final_decision=_extract_decision(final_state, decision),
                    )
                )

        # Attach per-agent LLM call counts to each evaluation for reporting
        snap = tracker.snapshot()
        for ev in out:
            ev.extra_outputs["api_call_stats"] = snap

        return out
