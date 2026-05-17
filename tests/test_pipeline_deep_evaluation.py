"""DeepEvaluationStep tests."""
import logging
import datetime as dt
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from pipeline.backends.deep_evaluators import (
    DEEP_EVALUATOR_REGISTRY,
    DeepEvaluation,
    DeepEvaluator,
)
from pipeline.base import StepContext
from pipeline.deep_evaluation import DeepEvaluationStep


def _create_schema(engine):
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT DEFAULT 'running'
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fast_evaluation_conclusion (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
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
                model_name TEXT,
                model_provider TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS deep_evaluation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
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
def env(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    _create_schema(engine)
    with Session(engine) as s:
        s.execute(text("INSERT INTO pipeline_runs (status) VALUES ('running')"))
        s.commit()
        run_id = s.execute(text("SELECT last_insert_rowid()")).scalar()
        now = dt.datetime.utcnow().isoformat()
        for ticker, score in [("AAA", 0.9), ("BBB", 0.5), ("CCC", -0.2)]:
            s.execute(
                text("INSERT INTO fast_evaluation_conclusion "
                     "(pipeline_run_id, ticker, backend, start_date, end_date, "
                     "evaluation_date, positive_count, negative_count, neutral_count, "
                     "total_count, consensus_score) "
                     "VALUES (:rid, :t, 'ai_hedge_fund', '2026-02-01', '2026-05-01', "
                     ":now, 5, 1, 1, 7, :score)"),
                {"rid": run_id, "t": ticker, "now": now, "score": score},
            )
        s.commit()

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    yield factory, run_id


@pytest.fixture
def fake_de():
    class FakeDE(DeepEvaluator):
        name = "fake_de_step4_test"

        def __init__(self, cfg=None):
            self.cfg = cfg or {}

        def evaluate(self, tickers, ctx):
            return [
                DeepEvaluation(
                    ticker=t,
                    evaluation_date="2026-05-17",
                    agent_outputs={"market_report": f"{t} up", "bull_argument": "buy"},
                    extra_outputs={"misc": 1},
                    final_decision="BUY",
                )
                for t in tickers
            ]

    DEEP_EVALUATOR_REGISTRY.register(FakeDE)
    yield "fake_de_step4_test"
    DEEP_EVALUATOR_REGISTRY.unregister("fake_de_step4_test")


def make_ctx(factory, run_id, tmp_path, backend, top_n=2):
    return StepContext(
        cfg={
            "deep_evaluation": {
                "backend": backend,
                "top_n": top_n,
                backend: {},
            }
        },
        run_id=run_id,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: factory().__enter__(),
    )


def test_deep_eval_picks_top_n_by_consensus(env, fake_de, tmp_path):
    factory, run_id = env
    ctx = make_ctx(factory, run_id, tmp_path, fake_de, top_n=2)
    result = DeepEvaluationStep().run(ctx)
    assert result.status == "success"
    evals = result.payload["evaluations"]
    assert [e["ticker"] for e in evals] == ["AAA", "BBB"]

    with factory() as s:
        rows = s.execute(
            text("SELECT ticker, market_report, bull_argument, "
                 "extra_outputs, final_decision FROM deep_evaluation "
                 "ORDER BY ticker")
        ).fetchall()
        assert {r[0] for r in rows} == {"AAA", "BBB"}
        assert rows[0][1] == "AAA up"    # market_report
        assert rows[0][2] == "buy"       # bull_argument
        assert rows[0][4] == "BUY"       # final_decision


def test_deep_eval_empty_upstream_returns_success(env, fake_de, tmp_path):
    factory, run_id = env
    with factory() as s:
        s.execute(text("INSERT INTO pipeline_runs (status) VALUES ('running')"))
        s.commit()
        empty_id = s.execute(text("SELECT last_insert_rowid()")).scalar()

    ctx = make_ctx(factory, empty_id, tmp_path, fake_de, top_n=2)
    result = DeepEvaluationStep().run(ctx)
    assert result.status == "success"
    assert result.payload["evaluations"] == []


def test_deep_eval_unknown_backend_fails(env, tmp_path):
    factory, run_id = env
    ctx = make_ctx(factory, run_id, tmp_path, "nope", top_n=2)
    result = DeepEvaluationStep().run(ctx)
    assert result.status == "failed"
