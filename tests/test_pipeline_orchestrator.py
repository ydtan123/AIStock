"""Orchestrator tests with stub steps."""
import json
import logging
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from pipeline.base import PipelineError, PipelineStep, StepContext, StepResult
from pipeline.orchestrator import FullPipeline


def _create_schema(engine):
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                finished_at TEXT,
                symbols_processed INTEGER DEFAULT 0,
                errors_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running',
                data_update_status TEXT,
                data_update_started_at TEXT,
                data_update_finished_at TEXT,
                stock_selection_status TEXT,
                stock_selection_started_at TEXT,
                stock_selection_finished_at TEXT,
                fast_evaluation_status TEXT,
                fast_evaluation_started_at TEXT,
                fast_evaluation_finished_at TEXT,
                deep_evaluation_status TEXT,
                deep_evaluation_started_at TEXT,
                deep_evaluation_finished_at TEXT,
                backtest_status TEXT,
                backtest_started_at TEXT,
                backtest_finished_at TEXT,
                trading_status TEXT,
                trading_started_at TEXT,
                trading_finished_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_run_id INTEGER NOT NULL,
                annual_return REAL,
                sharpe_ratio REAL,
                sortino_ratio REAL,
                max_drawdown REAL,
                volatility REAL,
                calmar_ratio REAL,
                start_date TEXT,
                end_date TEXT,
                initial_capital REAL,
                final_value REAL,
                num_tickers INTEGER,
                benchmark_metrics TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trading_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_run_id INTEGER NOT NULL,
                execution_mode TEXT NOT NULL DEFAULT 'dry_run',
                status TEXT NOT NULL DEFAULT 'pending',
                buys INTEGER,
                sells INTEGER,
                orders_json TEXT,
                portfolio_before_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
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

    return engine, f


class _OkStep(PipelineStep):
    name = "ok_step"

    def run(self, ctx):
        return StepResult(step_name=self.name, status="success",
                          summary={"x": 1}, payload={"k": "v"})


class _FailStep(PipelineStep):
    name = "fail_step"

    def run(self, ctx):
        return StepResult(step_name=self.name, status="failed",
                          summary={}, error="boom")


class _RaiseStep(PipelineStep):
    name = "raise_step"

    def run(self, ctx):
        raise ValueError("kaboom")


def test_orchestrator_runs_all_steps(engine_factory, tmp_path):
    engine, factory = engine_factory
    s1 = _StockSelectionOk()
    s2 = _DeepEvalOk()
    pipeline = FullPipeline(
        steps=[s1, s2],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    run_id = pipeline.run()
    assert run_id is not None
    with factory() as s:
        run = s.execute(
            text("SELECT status FROM pipeline_runs WHERE id = :rid"),
            {"rid": run_id},
        ).fetchone()
        assert run[0] == "partial"  # only 2 of 4 steps ran
    rep_dir = tmp_path / str(run_id)
    assert (rep_dir / "stock_selection.json").exists()
    assert (rep_dir / "deep_evaluation.json").exists()
    assert (rep_dir / "summary.json").exists()


def test_orchestrator_stops_on_failed_step(engine_factory, tmp_path):
    engine, factory = engine_factory
    after = _OkStep()
    after.name = "after_step"
    pipeline = FullPipeline(
        steps=[_OkStep(), _FailStep(), after],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    with pytest.raises(PipelineError):
        pipeline.run()
    with factory() as s:
        runs = s.execute(text("SELECT id, status FROM pipeline_runs")).fetchall()
        assert len(runs) == 1
        assert runs[0][1] == "failed"
        run_id = runs[0][0]
    rep_dir = tmp_path / str(run_id)
    assert (rep_dir / "ok_step.json").exists()
    assert (rep_dir / "fail_step.json").exists()
    assert not (rep_dir / "after_step.json").exists()


def test_orchestrator_wraps_exception(engine_factory, tmp_path):
    engine, factory = engine_factory
    pipeline = FullPipeline(
        steps=[_RaiseStep()],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    with pytest.raises(PipelineError):
        pipeline.run()
    with factory() as s:
        run = s.execute(text("SELECT id, status FROM pipeline_runs")).fetchone()
        assert run[1] == "failed"
        run_id = run[0]
    body = json.loads((tmp_path / str(run_id) / "raise_step.json").read_text())
    assert body["status"] == "failed"
    assert "kaboom" in body["error"]


def test_resume_from_loads_prior_results(engine_factory, tmp_path):
    engine, factory = engine_factory
    with factory() as s:
        s.execute(text("INSERT INTO pipeline_runs (status) VALUES ('failed')"))
        s.commit()
        run_id = s.execute(text("SELECT last_insert_rowid()")).scalar()
    rep_dir = tmp_path / str(run_id)
    rep_dir.mkdir(parents=True)
    (rep_dir / "ok_step.json").write_text(json.dumps({
        "step_name": "ok_step", "status": "success",
        "summary": {"x": 1}, "payload": {"k": "v"}, "error": None,
    }))

    after = _OkStep()
    after.name = "after_step"
    pipeline = FullPipeline(
        steps=[_OkStep(), after],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
        resume_from="after_step",
        run_id=run_id,
    )
    pipeline.run()
    with factory() as s:
        run = s.execute(
            text("SELECT status FROM pipeline_runs WHERE id = :rid"),
            {"rid": run_id},
        ).fetchone()
        assert run[0] == "success"
    assert (rep_dir / "after_step.json").exists()
    body = json.loads((rep_dir / "summary.json").read_text())
    assert "ok_step" in body["steps"]
    assert "after_step" in body["steps"]


def test_resume_rejects_already_successful(engine_factory, tmp_path):
    engine, factory = engine_factory
    with factory() as s:
        s.execute(text("INSERT INTO pipeline_runs (status) VALUES ('success')"))
        s.commit()
        run_id = s.execute(text("SELECT last_insert_rowid()")).scalar()

    pipeline = FullPipeline(
        steps=[_OkStep()],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
        resume_from="ok_step",
        run_id=run_id,
    )
    with pytest.raises(PipelineError, match="already.*success"):
        pipeline.run()


def test_resume_without_run_id_rejected(engine_factory, tmp_path):
    engine, factory = engine_factory
    with pytest.raises(ValueError, match="run_id is required"):
        FullPipeline(
            steps=[_OkStep()],
            cfg={},
            session_factory=lambda: factory().__enter__(),
            report_root=tmp_path,
            logger=logging.getLogger("test"),
            resume_from="ok_step",
            run_id=None,
        )


# --- Step classes with names in the guard set (real pipeline step names) -----


class _StockSelectionOk(PipelineStep):
    name = "stock_selection"

    def run(self, ctx):
        return StepResult(step_name=self.name, status="success",
                          summary={}, payload={})


class _FastEvalFail(PipelineStep):
    name = "fast_evaluation"

    def run(self, ctx):
        return StepResult(step_name=self.name, status="failed",
                          summary={}, error="boom")


class _DeepEvalOk(PipelineStep):
    name = "deep_evaluation"

    def run(self, ctx):
        return StepResult(step_name=self.name, status="success",
                          summary={}, payload={})


# --- Per-step status tracking tests -------------------------------------------


def test_step_status_tracked_on_success(engine_factory, tmp_path):
    """Step in guard set gets status='completed' + timestamps on success."""
    engine, factory = engine_factory
    pipeline = FullPipeline(
        steps=[_StockSelectionOk()],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    run_id = pipeline.run()
    with factory() as s:
        row = s.execute(text(
            "SELECT stock_selection_status, stock_selection_started_at, "
            "stock_selection_finished_at FROM pipeline_runs WHERE id = :rid"
        ), {"rid": run_id}).fetchone()
        assert row is not None
        assert row[0] == "completed"
        assert row[1] is not None  # started_at filled
        assert row[2] is not None  # finished_at filled


def test_step_status_tracked_on_failure(engine_factory, tmp_path):
    """Step in guard set gets status='failed' + finished_at on failure."""
    engine, factory = engine_factory
    pipeline = FullPipeline(
        steps=[_FastEvalFail()],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    with pytest.raises(PipelineError):
        pipeline.run()
    with factory() as s:
        row = s.execute(text(
            "SELECT fast_evaluation_status, fast_evaluation_finished_at "
            "FROM pipeline_runs WHERE id = (SELECT MAX(id) FROM pipeline_runs)"
        )).fetchone()
        assert row[0] == "failed"
        assert row[1] is not None


def test_arbitrary_step_not_tracked(engine_factory, tmp_path):
    """Steps outside the guard set are silently not tracked (columns stay NULL)."""
    engine, factory = engine_factory
    pipeline = FullPipeline(
        steps=[_OkStep()],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    run_id = pipeline.run()
    with factory() as s:
        row = s.execute(text(
            "SELECT stock_selection_status FROM pipeline_runs WHERE id = :rid"
        ), {"rid": run_id}).fetchone()
        assert row[0] is None  # never touched


def test_multiple_steps_all_tracked(engine_factory, tmp_path):
    """All steps in guard set get recorded correctly in sequence."""
    engine, factory = engine_factory
    pipeline = FullPipeline(
        steps=[_StockSelectionOk(), _DeepEvalOk()],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    run_id = pipeline.run()
    with factory() as s:
        row = s.execute(text(
            "SELECT stock_selection_status, stock_selection_finished_at, "
            "deep_evaluation_status, deep_evaluation_finished_at, status "
            "FROM pipeline_runs WHERE id = :rid"
        ), {"rid": run_id}).fetchone()
        assert row[0] == "completed"  # stock_selection
        assert row[1] is not None
        assert row[2] == "completed"  # deep_evaluation
        assert row[3] is not None
        assert row[4] == "partial"  # only 2 of 4 steps → partial


def test_full_pipeline_all_steps_success(engine_factory, tmp_path):
    """All 6 tracked steps complete → overall status = 'success'."""
    engine, factory = engine_factory

    _TRACKED = (
        "data_update", "stock_selection", "fast_evaluation", "deep_evaluation",
        "backtest", "trading",
    )
    steps: list[PipelineStep] = []
    for name in _TRACKED:
        step = _StockSelectionOk()
        step.name = name  # override to match each tracked step
        steps.append(step)

    pipeline = FullPipeline(
        steps=steps,
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    run_id = pipeline.run()
    with factory() as s:
        row = s.execute(text(
            "SELECT data_update_status, stock_selection_status, "
            "fast_evaluation_status, deep_evaluation_status, "
            "backtest_status, trading_status, status "
            "FROM pipeline_runs WHERE id = :rid"
        ), {"rid": run_id}).fetchone()
        for i in range(6):
            assert row[i] == "completed", f"step {i} should be completed"
        assert row[6] == "success"


def test_only_runs_single_step(engine_factory, tmp_path):
    engine, factory = engine_factory
    s1 = _OkStep()
    s1.name = "s1"
    s2 = _OkStep()
    s2.name = "s2"
    pipeline = FullPipeline(
        steps=[s1, s2],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
        only="s2",
    )
    run_id = pipeline.run()
    rep_dir = tmp_path / str(run_id)
    assert (rep_dir / "s2.json").exists()
    assert not (rep_dir / "s1.json").exists()
