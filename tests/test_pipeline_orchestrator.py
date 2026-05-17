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
                status TEXT DEFAULT 'running'
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
    pipeline = FullPipeline(
        steps=[_OkStep(), _OkStep()],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    pipeline.steps[1].name = "ok_step_2"
    run_id = pipeline.run()
    assert run_id is not None
    with factory() as s:
        run = s.execute(
            text("SELECT status FROM pipeline_runs WHERE id = :rid"),
            {"rid": run_id},
        ).fetchone()
        assert run[0] == "success"
    rep_dir = tmp_path / str(run_id)
    assert (rep_dir / "ok_step.json").exists()
    assert (rep_dir / "ok_step_2.json").exists()
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
