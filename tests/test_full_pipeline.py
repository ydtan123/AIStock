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

from full_pipeline import _write_step_report, _score_ticker, _parse_ta_ndjson


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


def test_parse_ta_ndjson_extracts_ticker_results():
    ndjson = "\n".join([
        json.dumps({"type": "start", "tickers": ["AAPL", "NVDA"]}),
        json.dumps({"type": "ticker_start", "ticker": "AAPL"}),
        json.dumps({
            "type": "ticker_result",
            "ticker": "AAPL",
            "decision": "BUY",
            "bullet_summaries": {"Market": ["Bullish trend"]},
            "investment_plan": "Go long",
            "final_decision": "Strong buy",
            "llm_calls": 12,
        }),
        json.dumps({"type": "ticker_error", "ticker": "NVDA", "error": "timeout"}),
        json.dumps({"type": "done", "total_llm_calls": 12, "summary": []}),
        "this is not json and should be skipped",
    ])
    results = _parse_ta_ndjson(ndjson)

    assert "AAPL" in results
    assert results["AAPL"]["decision"] == "BUY"
    assert results["AAPL"]["bullet_summaries"]["Market"] == ["Bullish trend"]
    assert results["AAPL"]["llm_calls"] == 12
    assert "NVDA" not in results  # error event is not a ticker_result
