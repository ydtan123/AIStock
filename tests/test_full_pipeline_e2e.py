"""End-to-end smoke test for the OOP pipeline with all backends faked.

Runs the orchestrator over data_update -> stock_selection ->
fast_evaluation -> deep_evaluation. Verifies DB rows and reports.
"""
import datetime as dt
import logging
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from pipeline.backends.deep_evaluators import (
    DEEP_EVALUATOR_REGISTRY,
    DeepEvaluation,
    DeepEvaluator,
)
from pipeline.backends.fast_evaluators import (
    FAST_EVALUATOR_REGISTRY,
    AnalystOpinion,
    FastEvaluation,
    FastEvaluator,
)
from pipeline.backends.selectors import (
    SELECTOR_REGISTRY,
    ScoredTicker,
    StockSelector,
)
from pipeline.data_update import DataUpdateStep
from pipeline.deep_evaluation import DeepEvaluationStep
from pipeline.fast_evaluation import FastEvaluationStep
from pipeline.orchestrator import FullPipeline
from pipeline.stock_selection import StockSelectionStep


def _create_schema(engine):
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                finished_at TEXT,
                symbols_processed INTEGER DEFAULT 0,
                errors_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            )
        """))
        # Matches ORM SelectedStock exactly
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS selected_stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                model_name TEXT NOT NULL,
                ml_score REAL NOT NULL,
                bucket TEXT,
                weight REAL,
                date_selected DATE NOT NULL,
                model_file TEXT,
                pipeline_run_at TEXT NOT NULL,
                predicted_return REAL,
                predicted_at TEXT,
                actual_return REAL,
                pipeline_run_id INTEGER,
                sector TEXT,
                backend TEXT
            )
        """))
        # Matches ORM FastEvaluationConclusion exactly
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fast_evaluation_conclusion (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_run_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                backend TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                evaluation_date TEXT NOT NULL,
                positive_count INTEGER NOT NULL,
                negative_count INTEGER NOT NULL,
                neutral_count INTEGER NOT NULL,
                total_count INTEGER NOT NULL,
                consensus_score REAL NOT NULL,
                model_name TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                UNIQUE(pipeline_run_id, ticker, backend)
            )
        """))
        # Matches ORM FastEvaluationAnalyst exactly
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fast_evaluation_analysts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_run_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                backend TEXT NOT NULL,
                analyst_name TEXT NOT NULL,
                opinion TEXT NOT NULL,
                confidence REAL NOT NULL,
                reasoning TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                evaluation_date TEXT NOT NULL
            )
        """))
        # Matches ORM DeepEvaluationRow exactly
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS deep_evaluation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_run_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                backend TEXT NOT NULL,
                evaluation_date TEXT NOT NULL,
                market_report TEXT,
                bull_argument TEXT,
                bear_argument TEXT,
                research_manager_decision TEXT,
                trader_plan TEXT,
                final_decision TEXT,
                model_name TEXT,
                extra_outputs TEXT
            )
        """))
        conn.commit()


@pytest.fixture
def engine_factory():
    engine = create_engine("sqlite:///:memory:")
    _create_schema(engine)

    @contextmanager
    def f():
        with Session(engine) as s:
            yield s

    return f


@pytest.fixture
def fake_backends():
    class FakeSel(StockSelector):
        name = "e2e_sel"

        def __init__(self, cfg=None):
            pass

        def select(self, ctx):
            return [
                ScoredTicker(ticker="AAA", ml_score=0.95, sector="Tech"),
                ScoredTicker(ticker="BBB", ml_score=0.85, sector="Tech"),
                ScoredTicker(ticker="CCC", ml_score=0.75, sector="Finance"),
                ScoredTicker(ticker="DDD", ml_score=0.55, sector="Energy"),
                ScoredTicker(ticker="EEE", ml_score=0.45, sector="Health"),
            ]

    class FakeFE(FastEvaluator):
        name = "e2e_fe"

        def __init__(self, cfg=None):
            pass

        def evaluate(self, tickers, ctx):
            return [
                FastEvaluation(
                    ticker=t,
                    start_date="2026-02-01",
                    end_date="2026-05-01",
                    opinions=[
                        AnalystOpinion("warren_buffett", "bullish", 80.0, "moat"),
                        AnalystOpinion("michael_burry", "bearish", 30.0, "valuation"),
                    ],
                    consensus_score=0.5,
                )
                for t in tickers
            ]

    class FakeDE(DeepEvaluator):
        name = "e2e_de"

        def __init__(self, cfg=None):
            pass

        def evaluate(self, tickers, ctx):
            return [
                DeepEvaluation(
                    ticker=t,
                    evaluation_date="2026-05-17",
                    agent_outputs={
                        "market_report": "{} rising".format(t),
                        "bull_argument": "buy",
                        "research_manager_decision": "BUY",
                    },
                    extra_outputs={},
                    final_decision="BUY",
                )
                for t in tickers
            ]

    SELECTOR_REGISTRY.register(FakeSel)
    FAST_EVALUATOR_REGISTRY.register(FakeFE)
    DEEP_EVALUATOR_REGISTRY.register(FakeDE)
    yield
    SELECTOR_REGISTRY.unregister("e2e_sel")
    FAST_EVALUATOR_REGISTRY.unregister("e2e_fe")
    DEEP_EVALUATOR_REGISTRY.unregister("e2e_de")


def test_full_pipeline_e2e(monkeypatch, engine_factory, fake_backends, tmp_path):
    monkeypatch.setattr(
        "pipeline.data_update._run_pipeline",
        lambda source, step_cfg: {
            "symbols_attempted": 5,
            "symbols_succeeded": 5,
            "symbols_failed": 0,
            "failed_symbols": [],
        },
    )

    cfg = {
        "data_update": {"source": "alpha_vantage", "parallel_workers": 1},
        "stock_selection": {"backend": "e2e_sel", "e2e_sel": {}},
        "fast_evaluation": {"backend": "e2e_fe", "top_n": 3, "e2e_fe": {}},
        "deep_evaluation": {"backend": "e2e_de", "top_n": 2, "e2e_de": {}},
    }

    pipeline = FullPipeline(
        steps=[
            DataUpdateStep(),
            StockSelectionStep(),
            FastEvaluationStep(),
            DeepEvaluationStep(),
        ],
        cfg=cfg,
        session_factory=lambda: engine_factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("e2e"),
    )
    run_id = pipeline.run()

    # Reports written
    rd = tmp_path / str(run_id)
    for name in ("data_update", "stock_selection", "fast_evaluation",
                 "deep_evaluation", "summary"):
        assert (rd / "{}.json".format(name)).exists(), name

    # DB state
    with engine_factory() as s:
        run = s.execute(
            text("SELECT status FROM pipeline_runs WHERE id = :rid"),
            {"rid": run_id},
        ).fetchone()
        assert run[0] == "success"

        sel_count = s.execute(text("SELECT COUNT(1) FROM selected_stocks")).scalar()
        assert sel_count == 5

        fe_count = s.execute(
            text("SELECT COUNT(1) FROM fast_evaluation_conclusion")
        ).scalar()
        assert fe_count == 3

        fea_count = s.execute(
            text("SELECT COUNT(1) FROM fast_evaluation_analysts")
        ).scalar()
        assert fea_count == 6

        de_count = s.execute(
            text("SELECT COUNT(1) FROM deep_evaluation")
        ).scalar()
        assert de_count == 2

        deep_tickers = {
            r[0]
            for r in s.execute(
                text("SELECT ticker FROM deep_evaluation")
            ).fetchall()
        }
        assert "AAA" in deep_tickers
        assert "BBB" in deep_tickers
