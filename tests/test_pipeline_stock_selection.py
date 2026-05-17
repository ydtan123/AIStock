"""StockSelectionStep tests."""
import logging
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from pipeline.backends.selectors import (
    SELECTOR_REGISTRY,
    ScoredTicker,
    StockSelector,
)
from pipeline.base import StepContext
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
        conn.commit()


@pytest.fixture
def engine_session():
    engine = create_engine("sqlite:///:memory:")
    _create_schema(engine)
    with Session(engine) as s:
        s.execute(text("INSERT INTO pipeline_runs (status) VALUES ('running')"))
        s.commit()
        run_id = s.execute(text("SELECT last_insert_rowid()")).scalar()

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    yield factory, run_id


@pytest.fixture
def fake_selector():
    class FakeSel(StockSelector):
        name = "fake_test_sel"

        def __init__(self, cfg=None):
            self.cfg = cfg or {}

        def select(self, ctx):
            return [
                ScoredTicker(ticker="AAPL", ml_score=0.9, sector="Tech"),
                ScoredTicker(ticker="MSFT", ml_score=0.8, sector="Tech"),
            ]

    SELECTOR_REGISTRY.register(FakeSel)
    yield "fake_test_sel"
    SELECTOR_REGISTRY.unregister("fake_test_sel")


def make_ctx(engine_session_factory, run_id, tmp_path, backend_name):
    return StepContext(
        cfg={
            "stock_selection": {
                "backend": backend_name,
                backend_name: {},
            }
        },
        run_id=run_id,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: engine_session_factory().__enter__(),
    )


def test_stock_selection_writes_to_db(engine_session, fake_selector, tmp_path):
    factory, run_id = engine_session
    ctx = make_ctx(factory, run_id, tmp_path, fake_selector)

    step = StockSelectionStep()
    result = step.run(ctx)

    assert result.status == "success"
    assert len(result.payload["tickers_ranked"]) == 2
    assert result.payload["backend"] == fake_selector

    with factory() as s:
        rows = s.execute(
            text("SELECT ticker, ml_score, backend, sector FROM selected_stocks "
                 "WHERE pipeline_run_id = :rid ORDER BY ml_score DESC"),
            {"rid": run_id},
        ).fetchall()
        assert [r[0] for r in rows] == ["AAPL", "MSFT"]
        assert rows[0][2] == fake_selector  # backend
        assert rows[0][3] == "Tech"          # sector


def test_stock_selection_unknown_backend_fails(engine_session, tmp_path):
    factory, run_id = engine_session
    ctx = StepContext(
        cfg={"stock_selection": {"backend": "does_not_exist"}},
        run_id=run_id,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: factory().__enter__(),
    )
    step = StockSelectionStep()
    result = step.run(ctx)
    assert result.status == "failed"
    assert "does_not_exist" in result.error


def test_stock_selection_empty_output_is_success(engine_session, tmp_path):
    factory, run_id = engine_session

    class EmptySel(StockSelector):
        name = "empty_sel"

        def __init__(self, cfg=None):
            pass

        def select(self, ctx):
            return []

    SELECTOR_REGISTRY.register(EmptySel)
    try:
        ctx = make_ctx(factory, run_id, tmp_path, "empty_sel")
        result = StockSelectionStep().run(ctx)
        assert result.status == "success"
        assert result.payload["tickers_ranked"] == []
        assert "empty" in result.summary.get("note", "").lower()
    finally:
        SELECTOR_REGISTRY.unregister("empty_sel")
