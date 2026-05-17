"""Schema tests: new tables build via create_all, basic insert + constraints."""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import (
    DeepEvaluationRow,
    FastEvaluationAnalyst,
    FastEvaluationConclusion,
    PipelineRun,
    SchemaMigration,
    SelectedStock,
)


_SCHEMA_DDL = [
    # SQLAlchemy's BigInteger PK doesn't autoincrement on SQLite.
    # Recreate all needed tables with INTEGER PRIMARY KEY.
    """CREATE TABLE IF NOT EXISTS pipeline_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      finished_at DATETIME,
      symbols_processed INTEGER DEFAULT 0,
      errors_count INTEGER DEFAULT 0,
      status VARCHAR(30) DEFAULT 'running'
    )""",
    """CREATE TABLE IF NOT EXISTS selected_stocks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ticker VARCHAR(10) NOT NULL,
      model_name VARCHAR(50) NOT NULL,
      ml_score FLOAT NOT NULL,
      bucket VARCHAR(50),
      weight FLOAT,
      date_selected DATE NOT NULL,
      model_file VARCHAR(255),
      pipeline_run_at DATETIME NOT NULL,
      predicted_return FLOAT,
      predicted_at DATETIME,
      actual_return FLOAT,
      pipeline_run_id INTEGER REFERENCES pipeline_runs(id),
      sector VARCHAR(64),
      backend VARCHAR(32)
    )""",
    """CREATE TABLE IF NOT EXISTS fast_evaluation_conclusion (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      pipeline_run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
      ticker VARCHAR(10) NOT NULL,
      backend VARCHAR(32) NOT NULL,
      start_date DATE NOT NULL,
      end_date DATE NOT NULL,
      evaluation_date DATETIME NOT NULL,
      positive_count INTEGER NOT NULL,
      negative_count INTEGER NOT NULL,
      neutral_count INTEGER NOT NULL,
      total_count INTEGER NOT NULL,
      consensus_score FLOAT NOT NULL,
      model_name VARCHAR(64) NOT NULL,
      model_provider VARCHAR(32) NOT NULL,
      UNIQUE(pipeline_run_id, ticker, backend)
    )""",
    """CREATE TABLE IF NOT EXISTS fast_evaluation_analysts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      pipeline_run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
      ticker VARCHAR(10) NOT NULL,
      backend VARCHAR(32) NOT NULL,
      analyst_name VARCHAR(64) NOT NULL,
      opinion VARCHAR(24) NOT NULL,
      confidence FLOAT NOT NULL,
      reasoning TEXT NOT NULL,
      start_date DATE NOT NULL,
      end_date DATE NOT NULL,
      evaluation_date DATETIME NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS deep_evaluation (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      pipeline_run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
      ticker VARCHAR(10) NOT NULL,
      backend VARCHAR(32) NOT NULL,
      evaluation_date DATETIME NOT NULL,
      market_report TEXT,
      bull_argument TEXT,
      bear_argument TEXT,
      research_manager_decision VARCHAR(24),
      trader_plan TEXT,
      final_decision VARCHAR(24),
      model_name VARCHAR(64),
      extra_outputs JSON
    )""",
    """CREATE TABLE IF NOT EXISTS schema_migrations (
      version VARCHAR(128) PRIMARY KEY,
      applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    # Build tables with raw DDL — SQLAlchemy's BigInteger PK doesn't
    # autoincrement on SQLite, and MEDIUMTEXT is MySQL-only.
    with engine.connect() as conn:
        for ddl in _SCHEMA_DDL:
            conn.exec_driver_sql(ddl)
        conn.commit()
    with Session(engine) as s:
        yield s


def test_selected_stocks_new_columns(session):
    run = PipelineRun(status="running")
    session.add(run)
    session.flush()
    s = SelectedStock(
        ticker="AAPL",
        model_name="finrl",
        ml_score=0.83,
        date_selected=dt.date(2026, 5, 17),
        pipeline_run_id=run.id,
        sector="Tech",
        backend="finrl",
    )
    session.add(s)
    session.commit()
    assert s.pipeline_run_id == run.id
    assert s.sector == "Tech"
    assert s.backend == "finrl"


def test_fast_evaluation_conclusion_insert(session):
    run = PipelineRun(status="running")
    session.add(run)
    session.flush()
    fec = FastEvaluationConclusion(
        pipeline_run_id=run.id,
        ticker="NVDA",
        backend="ai_hedge_fund",
        start_date=dt.date(2026, 2, 1),
        end_date=dt.date(2026, 5, 1),
        evaluation_date=dt.datetime(2026, 5, 17, 10, 0, 0),
        positive_count=12,
        negative_count=1,
        neutral_count=2,
        total_count=15,
        consensus_score=0.71,
        model_name="deepseek-v4-pro",
        model_provider="DeepSeek",
    )
    session.add(fec)
    session.commit()
    assert fec.id is not None


def test_fast_evaluation_conclusion_unique_constraint(session):
    run = PipelineRun(status="running")
    session.add(run)
    session.flush()
    for ticker in ["NVDA", "NVDA"]:
        session.add(
            FastEvaluationConclusion(
                pipeline_run_id=run.id,
                ticker=ticker,
                backend="ai_hedge_fund",
                start_date=dt.date(2026, 2, 1),
                end_date=dt.date(2026, 5, 1),
                evaluation_date=dt.datetime(2026, 5, 17),
                positive_count=1, negative_count=0, neutral_count=0,
                total_count=1, consensus_score=1.0,
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()


def test_fast_evaluation_analysts_insert(session):
    run = PipelineRun(status="running")
    session.add(run)
    session.flush()
    a = FastEvaluationAnalyst(
        pipeline_run_id=run.id,
        ticker="NVDA",
        backend="ai_hedge_fund",
        analyst_name="warren_buffett",
        opinion="bullish",
        confidence=85.0,
        reasoning="Strong moat",
        start_date=dt.date(2026, 2, 1),
        end_date=dt.date(2026, 5, 1),
        evaluation_date=dt.datetime(2026, 5, 17),
    )
    session.add(a)
    session.commit()
    assert a.id is not None


def test_deep_evaluation_insert(session):
    run = PipelineRun(status="running")
    session.add(run)
    session.flush()
    d = DeepEvaluationRow(
        pipeline_run_id=run.id,
        ticker="NVDA",
        backend="trading_agents",
        evaluation_date=dt.datetime(2026, 5, 17),
        market_report="trends up",
        bull_argument="growth",
        bear_argument="valuation",
        research_manager_decision="BUY",
        trader_plan="Buy 100 shares",
        final_decision="BUY",
        model_name="deepseek-v4-pro",
        extra_outputs={"reflection": "n/a"},
    )
    session.add(d)
    session.commit()
    assert d.id is not None
    fetched = session.query(DeepEvaluationRow).first()
    assert fetched.extra_outputs == {"reflection": "n/a"}


def test_schema_migration_tracking(session):
    m = SchemaMigration(version="2026_05_17_pipeline_oop")
    session.add(m)
    session.commit()
    assert m.applied_at is not None
