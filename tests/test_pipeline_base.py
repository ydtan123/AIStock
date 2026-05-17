"""Tests for pipeline base abstractions."""
import logging
from pathlib import Path

import pytest

from pipeline.base import (
    PipelineError,
    PipelineStep,
    StepContext,
    StepResult,
)


def test_step_result_defaults():
    r = StepResult(step_name="data_update", status="success", summary={"x": 1})
    assert r.payload == {}
    assert r.error is None


def test_step_result_failed():
    r = StepResult(
        step_name="stock_selection",
        status="failed",
        summary={},
        error="boom",
    )
    assert r.status == "failed"
    assert r.error == "boom"


def test_step_context_construction(tmp_path):
    ctx = StepContext(
        cfg={"data_update": {"source": "yahoo"}},
        run_id=42,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )
    assert ctx.run_id == 42
    assert ctx.prior_results == {}


def test_pipeline_step_is_abstract():
    with pytest.raises(TypeError):
        PipelineStep()  # type: ignore[abstract]


def test_pipeline_step_subclass_run_required():
    class IncompleteStep(PipelineStep):
        name = "incomplete"

    with pytest.raises(TypeError):
        IncompleteStep()  # type: ignore[abstract]


def test_pipeline_step_subclass_with_run_works(tmp_path):
    class FakeStep(PipelineStep):
        name = "fake"

        def run(self, ctx):
            return StepResult(step_name=self.name, status="success", summary={})

    step = FakeStep()
    ctx = StepContext(
        cfg={"fake": {"k": "v"}},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )
    result = step.run(ctx)
    assert result.status == "success"


def test_pipeline_step_step_config_helper(tmp_path):
    class FakeStep(PipelineStep):
        name = "fake"

        def run(self, ctx):
            return StepResult(step_name=self.name, status="success", summary={})

    step = FakeStep()
    ctx = StepContext(
        cfg={"fake": {"k": "v"}},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )
    assert step.step_config(ctx) == {"k": "v"}


def test_pipeline_step_step_config_missing_returns_empty(tmp_path):
    class FakeStep(PipelineStep):
        name = "missing"

        def run(self, ctx):
            return StepResult(step_name=self.name, status="success", summary={})

    step = FakeStep()
    ctx = StepContext(
        cfg={},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )
    assert step.step_config(ctx) == {}


def test_pipeline_error_is_exception():
    assert issubclass(PipelineError, Exception)
