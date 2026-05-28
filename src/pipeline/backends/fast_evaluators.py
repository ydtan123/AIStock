"""FastEvaluator ABC + AnalystOpinion + FastEvaluation + registry.

Concrete evaluator: AIHedgeFundFastEvaluator wrapping run_hedge_fund.
"""
from __future__ import annotations

import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from pipeline.backends.selectors import _Registry
from pipeline.base import StepContext

logger = logging.getLogger(__name__)


@dataclass
class AnalystOpinion:
    analyst_name: str
    opinion: str       # "bullish" | "bearish" | "neutral"
    confidence: float  # 0-100
    reasoning: str


@dataclass
class FastEvaluation:
    ticker: str
    start_date: str    # YYYY-MM-DD
    end_date: str      # YYYY-MM-DD
    opinions: list[AnalystOpinion]
    consensus_score: float  # [-1, +1]
    extras: dict = field(default_factory=dict)


FAST_EVALUATOR_REGISTRY = _Registry("fast_evaluator")


class FastEvaluator(ABC):
    name: str = ""

    def __init__(self):
        if not self.name:
            raise TypeError(
                f"{type(self).__name__} must define a non-empty `name` class attribute"
            )

    @abstractmethod
    def evaluate(self, tickers: list[str], ctx: StepContext) -> list[FastEvaluation]: ...


# --- Concrete backend: AIHedgeFundFastEvaluator ------------------------------
# sys.path hazard: external/ai-hedge-fund has its own src/main.py. We must
# pre-import AIStock's modules before inserting ai-hedge-fund's path so that
# `from src.main import run_hedge_fund` resolves to ai-hedge-fund's copy.

_AI_HEDGE_FUND_PATH = (
    Path(__file__).resolve().parents[3] / "external" / "ai-hedge-fund"
)


def _ensure_ai_hedge_fund_path() -> None:
    p = str(_AI_HEDGE_FUND_PATH)
    if p not in sys.path:
        sys.path.insert(0, p)


def _call_run_hedge_fund(**kwargs):
    """Indirection seam — tests monkeypatch this."""
    _ensure_ai_hedge_fund_path()
    from src.main import run_hedge_fund  # type: ignore[import-not-found]
    return run_hedge_fund(**kwargs)


def _inject_api_keys(ctx_cfg: dict) -> None:
    common = ctx_cfg.get("common", {})
    mapping = {
        "DEEPSEEK_API_KEY": common.get("deepseek_api_key"),
        "OPENAI_API_KEY": common.get("openai_api_key"),
        "ANTHROPIC_API_KEY": common.get("anthropic_api_key"),
        "GOOGLE_API_KEY": common.get("google_api_key"),
        "GROQ_API_KEY": common.get("groq_api_key"),
    }
    for env_var, value in mapping.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value


def _last_trading_date() -> str:
    """Return most recent weekday (Mon–Fri) as YYYY-MM-DD."""
    d = datetime.now().date()
    # weekday(): Mon=0 … Sun=6
    offset = max(0, d.weekday() - 4)  # Sat→1, Sun→2, weekdays→0
    d -= timedelta(days=offset)
    return d.strftime("%Y-%m-%d")


def _resolve_dates(start: str, end: str) -> tuple[str, str]:
    final_end = end or _last_trading_date()
    if start:
        final_start = start
    else:
        end_dt = datetime.strptime(final_end, "%Y-%m-%d")
        final_start = (end_dt - timedelta(days=90)).strftime("%Y-%m-%d")
    return final_start, final_end


_SIGN_BY_OPINION = {"bullish": 1, "bearish": -1, "neutral": 0}


def _compute_consensus(opinions: list[AnalystOpinion]) -> float:
    total_conf = sum(o.confidence for o in opinions if o.confidence > 0)
    if total_conf <= 0:
        return 0.0
    weighted = sum(
        _SIGN_BY_OPINION.get(o.opinion, 0) * o.confidence for o in opinions
    )
    return weighted / total_conf


@FAST_EVALUATOR_REGISTRY.register
class AIHedgeFundFastEvaluator(FastEvaluator):
    name = "ai_hedge_fund"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def evaluate(
        self, tickers: list[str], ctx: StepContext
    ) -> list[FastEvaluation]:
        if not tickers:
            ctx.logger.warning("AIHedgeFundFastEvaluator: empty tickers list")
            return []

        sub = self.cfg or ctx.cfg.get("fast_evaluation", {}).get("ai_hedge_fund", {})
        _inject_api_keys(ctx.cfg)

        start_date, end_date = _resolve_dates(
            sub.get("start_date", ""), sub.get("end_date", "")
        )
        portfolio = {
            "cash": float(sub.get("initial_cash", 100000.0)),
            "margin_requirement": float(sub.get("margin_requirement", 0.0)),
            "positions": {
                t: {"long": 0, "short": 0, "long_cost_basis": 0.0, "short_cost_basis": 0.0}
                for t in tickers
            },
            "realized_gains": {
                t: {"long": 0.0, "short": 0.0} for t in tickers
            },
        }
        result = _call_run_hedge_fund(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            portfolio=portfolio,
            show_reasoning=sub.get("show_reasoning", False),
            selected_analysts=sub.get("selected_analysts", []),
            model_name=sub.get("model_name", "deepseek-v4-pro"),
            model_provider=sub.get("model_provider", "DeepSeek"),
        )

        analyst_signals = (result or {}).get("analyst_signals", {})
        per_ticker_evals: list[FastEvaluation] = []
        for ticker in tickers:
            opinions: list[AnalystOpinion] = []
            for analyst_name, by_ticker in analyst_signals.items():
                sig = by_ticker.get(ticker) if isinstance(by_ticker, dict) else None
                if not sig:
                    continue
                opinion = str(sig.get("signal", "neutral")).lower()
                confidence = float(sig.get("confidence", 0.0))
                reasoning = str(sig.get("reasoning", ""))
                opinions.append(
                    AnalystOpinion(
                        analyst_name=analyst_name,
                        opinion=opinion,
                        confidence=confidence,
                        reasoning=reasoning,
                    )
                )
            per_ticker_evals.append(
                FastEvaluation(
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    opinions=opinions,
                    consensus_score=_compute_consensus(opinions),
                )
            )
        return per_ticker_evals
