"""DataUpdateStep tests."""
import logging

import pytest

from pipeline.base import StepContext
from pipeline.data_update import DataUpdateStep


def make_ctx(tmp_path, cfg=None):
    return StepContext(
        cfg=cfg or {},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )


def test_data_update_success(monkeypatch, tmp_path):
    fake_result = {
        "symbols_attempted": 3,
        "symbols_succeeded": 3,
        "symbols_failed": 0,
        "failed_symbols": [],
    }

    monkeypatch.setattr(
        "pipeline.data_update._run_pipeline",
        lambda source, parallel_workers: fake_result,
    )

    step = DataUpdateStep()
    ctx = make_ctx(
        tmp_path,
        cfg={"data_update": {"source": "alpha_vantage", "parallel_workers": 4}},
    )
    result = step.run(ctx)
    assert result.status == "success"
    assert result.summary["symbols_succeeded"] == 3
    assert result.summary["source"] == "alpha_vantage"


def test_data_update_failure_returns_failed_status(monkeypatch, tmp_path):
    def raiser(*a, **k):
        raise RuntimeError("DB down")

    monkeypatch.setattr("pipeline.data_update._run_pipeline", raiser)

    step = DataUpdateStep()
    ctx = make_ctx(tmp_path, cfg={"data_update": {"source": "yahoo"}})
    result = step.run(ctx)
    assert result.status == "failed"
    assert "DB down" in result.error


def test_data_update_partial_failure_still_success(monkeypatch, tmp_path):
    fake_result = {
        "symbols_attempted": 5,
        "symbols_succeeded": 4,
        "symbols_failed": 1,
        "failed_symbols": ["XYZ"],
    }
    monkeypatch.setattr(
        "pipeline.data_update._run_pipeline",
        lambda source, parallel_workers: fake_result,
    )

    step = DataUpdateStep()
    ctx = make_ctx(tmp_path, cfg={"data_update": {"source": "alpha_vantage"}})
    result = step.run(ctx)
    assert result.status == "success"
    assert result.summary["symbols_failed"] == 1


def test_data_update_all_failed_returns_failed(monkeypatch, tmp_path):
    fake_result = {
        "symbols_attempted": 3,
        "symbols_succeeded": 0,
        "symbols_failed": 3,
        "failed_symbols": ["A", "B", "C"],
    }
    monkeypatch.setattr(
        "pipeline.data_update._run_pipeline",
        lambda source, parallel_workers: fake_result,
    )

    step = DataUpdateStep()
    ctx = make_ctx(tmp_path, cfg={"data_update": {"source": "alpha_vantage"}})
    result = step.run(ctx)
    assert result.status == "failed"
