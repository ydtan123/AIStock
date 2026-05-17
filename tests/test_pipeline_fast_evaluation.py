"""FastEvaluationStep tests."""
import logging
import datetime as dt
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from pipeline.backends.fast_evaluators import (
    AnalystOpinion,
    FAST_EVALUATOR_REGISTRY,
    FastEvaluation,
    FastEvaluator,
)
from pipeline.base import StepContext
from pipeline.fast_evaluation import FastEvaluationStep


def _create_schema(engine):
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT DEFAULT 'running'
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS selected_stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                model_name TEXT NOT NULL,
                ml_score REAL NOT NULL,
                bucket TEXT,
                weight REAL,
                date_selected TEXT NOT NULL,
                model_file TEXT,
                pipeline_run_at TEXT NOT NULL,
                predicted_return REAL,
                predicted_at TEXT,
                actual_return REAL,
                pipeline_run_id INTEGER REFERENCES pipeline_runs(id),
                sector TEXT,
                backend TEXT
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
            CREATE TABLE IF NOT EXISTS fast_evaluation_analysts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
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
        for ticker, score in [("AAA", 0.9), ("BBB", 0.8), ("CCC", 0.7), ("DDD", 0.6)]:
            s.execute(
                text("INSERT INTO selected_stocks "
                     "(ticker, model_name, ml_score, date_selected, pipeline_run_id, "
                     "sector, backend, pipeline_run_at) "
                     "VALUES (:t, 'finrl', :s, :d, :rid, 'X', 'finrl', :now)"),
                {"t": ticker, "s": score, "d": dt.date.today().isoformat(),
                 "rid": run_id, "now": now},
            )
        s.commit()

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    yield factory, run_id


@pytest.fixture
def fake_fe():
    class FakeFE(FastEvaluator):
        name = "fake_fe_step3_test"

        def __init__(self, cfg=None):
            self.cfg = cfg or {}

        def evaluate(self, tickers, ctx):
            return [
                FastEvaluation(
                    ticker=t,
                    start_date="2026-02-01",
                    end_date="2026-05-01",
                    opinions=[
                        AnalystOpinion("warren_buffett", "bullish", 80.0, "moat"),
                        AnalystOpinion("michael_burry", "bearish", 50.0, "valuation"),
                    ],
                    consensus_score=(80 - 50) / (80 + 50),
                )
                for t in tickers
            ]

    FAST_EVALUATOR_REGISTRY.register(FakeFE)
    yield "fake_fe_step3_test"
    FAST_EVALUATOR_REGISTRY.unregister("fake_fe_step3_test")


def make_ctx(factory, run_id, tmp_path, backend, top_n=2):
    return StepContext(
        cfg={
            "fast_evaluation": {
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


def test_fast_eval_picks_top_n_by_ml_score(env, fake_fe, tmp_path):
    factory, run_id = env
    ctx = make_ctx(factory, run_id, tmp_path, fake_fe, top_n=2)
    result = FastEvaluationStep().run(ctx)
    assert result.status == "success"
    ranked = result.payload["tickers_ranked_by_consensus"]
    assert [r["ticker"] for r in ranked] == ["AAA", "BBB"]

    with factory() as s:
        conc = s.execute(
            text("SELECT ticker, positive_count, negative_count, neutral_count, total_count "
                 "FROM fast_evaluation_conclusion ORDER BY consensus_score DESC")
        ).fetchall()
        assert {c[0] for c in conc} == {"AAA", "BBB"}
        assert conc[0][1] == 1  # positive_count
        assert conc[0][2] == 1  # negative_count
        assert conc[0][3] == 0  # neutral_count
        assert conc[0][4] == 2  # total_count

        analysts = s.execute(
            text("SELECT ticker, analyst_name FROM fast_evaluation_analysts")
        ).fetchall()
        assert len(analysts) == 4  # 2 tickers x 2 analysts


def test_fast_eval_empty_upstream_returns_success(env, fake_fe, tmp_path):
    factory, run_id = env
    with factory() as s:
        s.execute(text("INSERT INTO pipeline_runs (status) VALUES ('running')"))
        s.commit()
        empty_run_id = s.execute(text("SELECT last_insert_rowid()")).scalar()

    ctx = make_ctx(factory, empty_run_id, tmp_path, fake_fe, top_n=2)
    result = FastEvaluationStep().run(ctx)
    assert result.status == "success"
    assert result.payload["tickers_ranked_by_consensus"] == []


def test_fast_eval_unknown_backend_fails(env, tmp_path):
    factory, run_id = env
    ctx = make_ctx(factory, run_id, tmp_path, "nope", top_n=2)
    result = FastEvaluationStep().run(ctx)
    assert result.status == "failed"
