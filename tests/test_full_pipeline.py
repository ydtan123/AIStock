"""Unit tests for full_pipeline helpers."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ORDERING CRITICAL: import AIStock core before FinRL to prevent sys.path pollution
import config  # noqa: F401
import database  # noqa: F401
import repository  # noqa: F401

from full_pipeline import _write_step_report, _score_ticker


def test_write_step_report_creates_json_and_md():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_dir = Path(tmpdir)
        data = {
            "status": "success",
            "started_at": "2026-05-16T10:00:00",
            "finished_at": "2026-05-16T10:05:00",
            "data": {"processed": 42, "errors": 1},
        }
        _write_step_report(report_dir, "step1_daily_update", data)

        json_path = report_dir / "step1_daily_update.json"
        md_path = report_dir / "step1_daily_update.md"

        assert json_path.exists(), "JSON file not created"
        assert md_path.exists(), "MD file not created"

        loaded = json.loads(json_path.read_text())
        assert loaded["status"] == "success"
        assert loaded["data"]["processed"] == 42

        md_text = md_path.read_text().lower()
        assert "step1 daily update" in md_text
        assert "success" in md_text


def test_score_ticker_buy():
    assert _score_ticker({"action": "buy", "confidence": 80}) == pytest.approx(0.80)


def test_score_ticker_sell():
    assert _score_ticker({"action": "sell", "confidence": 60}) == pytest.approx(-0.60)


def test_score_ticker_short():
    assert _score_ticker({"action": "short", "confidence": 70}) == pytest.approx(-0.70)


def test_score_ticker_hold():
    assert _score_ticker({"action": "hold", "confidence": 50}) == pytest.approx(0.0)


def test_score_ticker_missing_fields():
    assert _score_ticker({}) == pytest.approx(0.0)
