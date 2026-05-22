"""Backend ABC + registry tests using fakes."""
import logging
from pathlib import Path

import pytest

from pipeline.backends.selectors import (
    SELECTOR_REGISTRY,
    ScoredTicker,
    StockSelector,
)
from pipeline.base import StepContext


def make_ctx(tmp_path, cfg=None):
    return StepContext(
        cfg=cfg or {},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )


def test_scored_ticker_construction():
    t = ScoredTicker(ticker="AAPL", ml_score=0.5, sector="Tech")
    assert t.ticker == "AAPL"
    assert t.sector == "Tech"


def test_stock_selector_is_abstract():
    with pytest.raises(TypeError):
        StockSelector()  # type: ignore[abstract]


def test_stock_selector_subclass_must_define_name(tmp_path):
    class NoName(StockSelector):
        def select(self, ctx):
            return []

    with pytest.raises(TypeError, match="name"):
        NoName()  # type: ignore[abstract]


def test_fake_selector_registers_and_runs(tmp_path):
    @SELECTOR_REGISTRY.register
    class FakeSelector(StockSelector):
        name = "fake_selector_test"

        def __init__(self, cfg=None):
            self.cfg = cfg or {}

        def select(self, ctx):
            return [ScoredTicker(ticker="X", ml_score=1.0, sector=None)]

    assert "fake_selector_test" in SELECTOR_REGISTRY
    cls = SELECTOR_REGISTRY.get("fake_selector_test")
    out = cls().select(make_ctx(tmp_path))
    assert out[0].ticker == "X"
    SELECTOR_REGISTRY.unregister("fake_selector_test")
    assert "fake_selector_test" not in SELECTOR_REGISTRY


def test_registry_get_unknown_raises():
    with pytest.raises(KeyError, match="unknown selector"):
        SELECTOR_REGISTRY.get("does_not_exist")


def test_finrl_stock_selector_uses_run_pipeline(monkeypatch, tmp_path):
    """FinrlStockSelector runs finrl_pipeline then reads selections from DB."""
    from pipeline.backends import selectors as sel_mod

    fake_db_rows = [
        {"ticker": "AAPL", "ml_score": 0.83, "sector": "Information Technology", "bucket": None},
        {"ticker": "MSFT", "ml_score": 0.79, "sector": "Information Technology", "bucket": None},
    ]
    captured = {}

    def fake_run(cfg_overrides):
        captured["cfg_overrides"] = cfg_overrides

    monkeypatch.setattr(sel_mod, "_run_finrl_pipeline", fake_run)

    class FakeRepo:
        def get_latest_selected_stocks(self):
            return fake_db_rows

    monkeypatch.setattr(sel_mod, "StockRepository", FakeRepo)

    selector = sel_mod.FinrlStockSelector(
        cfg={"source": "AISTOCK_DB", "top_quantile": 0.2}
    )
    out = selector.select(
        make_ctx(tmp_path, cfg={"stock_selection": {"finrl": {"top_quantile": 0.2}}})
    )
    assert [t.ticker for t in out] == ["AAPL", "MSFT"]
    assert out[0].ml_score == 0.83
    assert out[0].sector == "Information Technology"
    assert captured["cfg_overrides"]["top_quantile"] == 0.2


def test_finrl_registered_under_name():
    from pipeline.backends.selectors import SELECTOR_REGISTRY, FinrlStockSelector
    assert SELECTOR_REGISTRY.get("finrl") is FinrlStockSelector


# --- T08: FastEvaluator ABC + registry ---------------------------------------

def test_analyst_opinion_construction():
    from pipeline.backends.fast_evaluators import AnalystOpinion

    o = AnalystOpinion(
        analyst_name="warren_buffett",
        opinion="bullish",
        confidence=80.0,
        reasoning="strong moat",
    )
    assert o.opinion == "bullish"


def test_fast_evaluation_construction():
    from pipeline.backends.fast_evaluators import AnalystOpinion, FastEvaluation

    fe = FastEvaluation(
        ticker="NVDA",
        start_date="2026-02-01",
        end_date="2026-05-01",
        opinions=[
            AnalystOpinion("a", "bullish", 80.0, ""),
            AnalystOpinion("b", "bearish", 40.0, ""),
        ],
        consensus_score=0.33,
    )
    assert fe.ticker == "NVDA"
    assert len(fe.opinions) == 2


def test_fast_evaluator_is_abstract():
    from pipeline.backends.fast_evaluators import FastEvaluator
    with pytest.raises(TypeError):
        FastEvaluator()  # type: ignore[abstract]


def test_fake_fast_evaluator_registers(tmp_path):
    from pipeline.backends.fast_evaluators import (
        AnalystOpinion,
        FAST_EVALUATOR_REGISTRY,
        FastEvaluation,
        FastEvaluator,
    )

    @FAST_EVALUATOR_REGISTRY.register
    class FakeFE(FastEvaluator):
        name = "fake_fe_test"

        def __init__(self, cfg=None):
            self.cfg = cfg or {}

        def evaluate(self, tickers, ctx):
            return [
                FastEvaluation(
                    ticker=t,
                    start_date="2026-01-01",
                    end_date="2026-05-01",
                    opinions=[AnalystOpinion("x", "bullish", 90.0, "ok")],
                    consensus_score=0.9,
                )
                for t in tickers
            ]

    out = FakeFE().evaluate(["A", "B"], make_ctx(tmp_path))
    assert [e.ticker for e in out] == ["A", "B"]
    FAST_EVALUATOR_REGISTRY.unregister("fake_fe_test")


# --- T09: AIHedgeFundFastEvaluator concrete ----------------------------------

def test_ai_hedge_fund_fast_evaluator_parses_signals(monkeypatch, tmp_path):
    from pipeline.backends import fast_evaluators as fe_mod

    fake_result = {
        "decisions": {"NVDA": {"action": "buy", "quantity": 0}},
        "analyst_signals": {
            "warren_buffett_agent": {
                "NVDA": {"signal": "bullish", "confidence": 80, "reasoning": "moat"}
            },
            "michael_burry_agent": {
                "NVDA": {"signal": "bearish", "confidence": 60, "reasoning": "bubble"}
            },
            "fundamentals_analyst_agent": {
                "NVDA": {"signal": "neutral", "confidence": 50, "reasoning": "mixed"}
            },
        },
    }
    captured = {}

    def fake_run_hedge_fund(**kwargs):
        captured.update(kwargs)
        return fake_result

    monkeypatch.setattr(fe_mod, "_call_run_hedge_fund", fake_run_hedge_fund)

    ev = fe_mod.AIHedgeFundFastEvaluator(
        cfg={
            "model_name": "deepseek-v4-pro",
            "model_provider": "DeepSeek",
            "start_date": "2026-02-01",
            "end_date": "2026-05-01",
            "selected_analysts": ["warren_buffett", "michael_burry", "fundamentals_analyst"],
        }
    )
    out = ev.evaluate(["NVDA"], make_ctx(tmp_path))
    assert len(out) == 1
    fe = out[0]
    assert fe.ticker == "NVDA"
    assert {o.analyst_name for o in fe.opinions} == {
        "warren_buffett_agent", "michael_burry_agent", "fundamentals_analyst_agent",
    }
    # consensus = (1*80 + -1*60 + 0*50) / (80+60+50) = 20/190 ≈ 0.105
    assert abs(fe.consensus_score - (20 / 190)) < 1e-6
    assert captured["tickers"] == ["NVDA"]
    assert captured["model_name"] == "deepseek-v4-pro"


def test_ai_hedge_fund_registered_under_name():
    from pipeline.backends.fast_evaluators import (
        FAST_EVALUATOR_REGISTRY,
        AIHedgeFundFastEvaluator,
    )
    assert FAST_EVALUATOR_REGISTRY.get("ai_hedge_fund") is AIHedgeFundFastEvaluator


# --- T10: DeepEvaluator + TradingAgentsDeepEvaluator -------------------------

def test_deep_evaluator_is_abstract():
    from pipeline.backends.deep_evaluators import DeepEvaluator
    with pytest.raises(TypeError):
        DeepEvaluator()  # type: ignore[abstract]


def test_deep_evaluation_dataclass():
    from pipeline.backends.deep_evaluators import DeepEvaluation
    de = DeepEvaluation(
        ticker="NVDA",
        evaluation_date="2026-05-17",
        agent_outputs={"market_report": "x"},
        extra_outputs={"foo": 1},
        final_decision="BUY",
    )
    assert de.agent_outputs["market_report"] == "x"
    assert de.extra_outputs["foo"] == 1


def test_trading_agents_evaluator_maps_final_state(monkeypatch, tmp_path):
    from pipeline.backends import deep_evaluators as de_mod

    fake_final_state = {
        "market_report": "trends up",
        "sentiment_report": "buzz",
        "news_report": "press",
        "fundamentals_report": "PE ok",
        "investment_plan": "long-term BUY",
        "trader_investment_plan": "Buy 100",
        "final_trade_decision": "BUY 100 shares of NVDA",
        "bull_argument": "bullish thesis",
        "bear_argument": "bearish thesis",
        "risk_debate_aggressive": "aggressive view",
        "risk_debate_conservative": "conservative view",
        "risk_debate_neutral": "neutral view",
    }

    class FakeGraph:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def propagate(self, company_name, trade_date):
            return fake_final_state, "BUY"

    captured = {"installs": 0}

    def fake_install_cache():
        captured["installs"] += 1

    monkeypatch.setattr(de_mod, "_install_news_cache", fake_install_cache)
    monkeypatch.setattr(de_mod, "_build_graph", lambda **kw: FakeGraph(**kw))

    evaluator = de_mod.TradingAgentsDeepEvaluator(
        cfg={
            "model_name": "deepseek-v4-pro",
            "use_news_cache": True,
            "selected_analysts": ["market", "social", "news", "fundamentals"],
            "evaluation_date": "2026-05-17",
        }
    )
    out = evaluator.evaluate(["NVDA"], make_ctx(tmp_path))
    assert len(out) == 1
    de = out[0]
    assert de.ticker == "NVDA"
    assert de.final_decision == "BUY"
    assert de.agent_outputs["market_report"] == "trends up"
    assert de.agent_outputs["bull_argument"] == "bullish thesis"
    assert de.agent_outputs["risk_aggressive"] == "aggressive view"
    assert captured["installs"] == 1


def test_trading_agents_registered_under_name():
    from pipeline.backends.deep_evaluators import (
        DEEP_EVALUATOR_REGISTRY,
        TradingAgentsDeepEvaluator,
    )
    assert DEEP_EVALUATOR_REGISTRY.get("trading_agents") is TradingAgentsDeepEvaluator


def test_use_news_cache_false_skips_install(monkeypatch, tmp_path):
    from pipeline.backends import deep_evaluators as de_mod

    class FakeGraph:
        def __init__(self, **kw): pass
        def propagate(self, c, d): return {}, "HOLD"

    captured = {"installs": 0}
    monkeypatch.setattr(
        de_mod, "_install_news_cache",
        lambda: captured.__setitem__("installs", captured["installs"] + 1),
    )
    monkeypatch.setattr(de_mod, "_build_graph", lambda **kw: FakeGraph())

    ev = de_mod.TradingAgentsDeepEvaluator(cfg={"use_news_cache": False})
    ev.evaluate(["NVDA"], make_ctx(tmp_path))
    assert captured["installs"] == 0
