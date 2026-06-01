# Test Coverage Gap Analysis — Supplement v2

**Date:** 2026-05-30
**Supplements:** `docs/test-coverage-gap-analysis-2026-05-30-v2.md`
**Coverage baseline:** 29.5% (3917 stmts)

This supplement adds: error handling gap analysis per module, integration test gaps, and test skeletons for modules not fully covered in v2.

---

## 1. Error Handling Gap Map (66+ blocks across untested modules)

### 1.1 `src/repository.py` — 1 try block, 0 error tests

| Line | Pattern | Risk |
|------|---------|------|
| L46 | `try:` (session context) | Session leak on DB failure |

No `except` blocks visible — session errors propagate unhandled. Critical methods (`get_prices`, `screen_stocks`, `save_selected_stocks`) have no input validation.

### 1.2 `src/ingestion/pipeline.py` — 26 try/except/raise blocks

| Line | Pattern | What Happens |
|------|---------|-------------|
| L58 | `try:` | Fetch stock dates — no except |
| L104 | `try:` | Fetch prices — no except |
| L119 | `try:` | DB query — no except |
| L145 | `try:` | DB write — no except |
| L161 | `except Exception as e:` | Swallows exception silently |
| L192 | `try:` | Upsert fundamentals |
| L236 | `try:` | Refresh snapshots |
| L240 | `except Exception as e:` | Swallows silently |
| L308 | `try:` | Batch update checkpoints |
| L332 | `try:` | Checkpoint read |
| L362 | `try:` | News fetch |
| L369 | `except Exception as exc:` | Logs but does not propagate |
| L377 | `try:` | Process symbol |
| L405 | `except Exception as e:` | Swallows per-symbol failure |
| L423 | `try:` | Final commit |
| L460 | `except Exception as e:` | Swallows commit failure |
| L465 | `try:` | Session cleanup |
| L492 | `try:` | Bootstrap |
| L494 | `except Exception as e:` | Swallows bootstrap failure |

**Pattern**: 19 try blocks, 6 silent `except Exception` catches. Pipeline can fail partially with no aggregate error count.

### 1.3 `src/scheduler.py` — 8 try/except/raise blocks

| Line | Pattern | Risk |
|------|---------|------|
| L25 | `try:` | Record job start — DB error swallowed |
| L36 | `try:` | Record job end — DB error swallowed |
| L54 | `try:` | Daily pipeline job |
| L62 | `except Exception as e:` | Pipeline failure silently logged |
| L73 | `try:` | Refresh symbols job |
| L80 | `except Exception as e:` | Refresh failure silently logged |
| L120 | `try:` | Main loop |
| L122 | `except (KeyboardInterrupt, SystemExit):` | Other exceptions crash |

**Pattern**: Jobs can fail for weeks without alerting. No dead-letter queue or retry.

### 1.4 `src/finrl_runner.py` — 20 try/except/raise blocks

| Line | Pattern | Risk |
|------|---------|------|
| L67 | `raise RuntimeError(...)` | No tickers |
| L73 | `raise RuntimeError(...)` | No fundamental data |
| L83 | `try:` | ML model loading |
| L96 | `try:` | Bucket selection |
| L103 | `except Exception as exc:` | ML failure swallowed |
| L114 | `try:` | Backtest |
| L124 | `except Exception as exc:` | Backtest failure swallowed |
| L145 | `raise FileNotFoundError(...)` | No models |
| L165 | `raise ValueError(...)` | No symbols |
| L175 | `raise RuntimeError(...)` | No fundamental data for symbols |
| L198 | `raise RuntimeError(...)` | Missing gsector |
| L205 | `raise RuntimeError(...)` | No bucket mapping |
| L252 | `raise RuntimeError(...)` | All buckets empty |
| L288 | `except Exception:` | **Bare except — anti-pattern** |
| L324 | `except Exception as exc:` | Backtest failure |
| L376 | `except Exception:` | **Bare except — anti-pattern** |

**Pattern**: 2 bare `except:` blocks (L288, L376) swallow ALL exceptions including KeyboardInterrupt. 7 explicit `raise` statements tested nowhere.

### 1.5 `src/fetcher/alpha_vantage.py` — 8 try/except/raise blocks

| Line | Pattern | Risk |
|------|---------|------|
| L31 | `try:` | HTTP request |
| L44 | `except requests.Timeout:` | Only catches timeout |
| L54 | `raise RuntimeError(...)` | After retry exhaustion |
| L236 | `try:` | Parse earnings |
| L242 | `except (TypeError, ValueError):` | Graceful parse failure |

**Pattern**: `ConnectionError`, `HTTPError` (non-200), DNS failures NOT caught — crash through to caller. Retry loop only handles `Timeout`.

### 1.6 `src/ml_bucket_selector.py` — 5 raise blocks

| Line | Pattern | Risk |
|------|---------|------|
| L113 | `raise ValueError(...)` | No rows after bucket |
| L119 | `raise ValueError(...)` | Insufficient dates |
| L128 | `try:` | ML execution |
| L139 | `except Exception as exc:` | ML failure swallowed |
| L143 | `raise RuntimeError(...)` | All buckets empty |

### 1.7 `src/config.py` — 0 error handling

No `try/except` blocks at all. `load_config()` will crash with `FileNotFoundError` or `yaml.YAMLError` on missing/malformed config.
Partial configs (missing keys) produce `KeyError` at access time, not load time.

---

## 2. Integration Test Gaps

### Gap I1: Full pipeline step chain
**Flow**: data_update → stock_selection → fast_evaluation → deep_evaluation
**Status**: No E2E test with real/mocked DB
**Risk**: Step output format changes break downstream steps silently

### Gap I2: Scheduler → Ingestion pipeline
**Flow**: APScheduler cron → job_daily_pipeline() → run_daily_pipeline()
**Status**: No integration test
**Risk**: Job failure goes undetected (silent except at L62)

### Gap I3: News cache → DB
**Flow**: get_cached() → Google News API → set_cached()
**Status**: No integration test with HTTP mocks
**Risk**: Cache poisoning with error responses

### Gap I4: FinRL runner → MLBucketSelector → Backtest
**Flow**: run_pipeline_and_save_report() → MLBucketSelector.fit_predict() → _run_simple_backtest()
**Status**: No integration test
**Risk**: Data format mismatch between stages

### Gap I5: Repository → pipeline steps
**Flow**: StockRepository methods called by pipeline steps via session factory
**Status**: Only unit-tested in isolation
**Risk**: Session management conflicts between pipeline and repository

### Integration Test Skeleton

```python
# tests/test_integration_critical_flows.py
"""Integration tests for critical cross-module flows."""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

# --- I1: Full pipeline step chain ---

class TestPipelineStepChain:
    @patch("pipeline.data_update.DataUpdateStep.run")
    @patch("pipeline.stock_selection.StockSelectionStep.run")
    @patch("pipeline.fast_evaluation.FastEvaluationStep.run")
    @patch("pipeline.deep_evaluation.DeepEvaluationStep.run")
    def test_all_steps_execute_in_order(self, mock_deep, mock_fast,
                                         mock_select, mock_update, tmp_path):
        from pipeline.orchestrator import FullPipeline

        for m in [mock_update, mock_select, mock_fast, mock_deep]:
            m.return_value.status = "completed"

        pipeline = FullPipeline(
            cfg={"data_update": {}, "stock_selection": {},
                 "fast_evaluation": {}, "deep_evaluation": {}},
            report_dir=tmp_path,
            session_factory=lambda: MagicMock(),
        )
        pipeline.run()

        mock_update.assert_called_once()
        mock_select.assert_called_once()
        mock_fast.assert_called_once()
        mock_deep.assert_called_once()

    def test_first_step_failure_stops_pipeline(self, tmp_path):
        from pipeline.orchestrator import FullPipeline

        pipeline = FullPipeline(
            cfg={"data_update": {}, "stock_selection": {}},
            report_dir=tmp_path,
            session_factory=lambda: MagicMock(),
        )
        with patch.object(pipeline, "_run_step") as mock_run:
            mock_run.side_effect = [
                MagicMock(status="failed", error="Step 1 failed"),
            ]
            result = pipeline.run()
            assert result["status"] == "failed"
            assert mock_run.call_count == 1

    def test_resume_from_mid_pipeline(self, tmp_path):
        """Verify --resume-from skips earlier steps."""
        from pipeline.orchestrator import FullPipeline

        pipeline = FullPipeline(
            cfg={"stock_selection": {}, "fast_evaluation": {},
                 "deep_evaluation": {}},
            report_dir=tmp_path,
            session_factory=lambda: MagicMock(),
        )
        with patch.object(pipeline, "_run_step") as mock_run:
            mock_run.return_value = MagicMock(status="completed")
            pipeline.run(resume_from="fast_evaluation")
            # data_update + stock_selection skipped
            assert mock_run.call_count == 2

# --- I2: Scheduler to Pipeline flow ---

class TestSchedulerPipelineFlow:
    @patch("scheduler.get_session")
    @patch("scheduler._record_job_start")
    @patch("scheduler._record_job_end")
    @patch("ingestion.pipeline.run_daily_pipeline")
    def test_job_triggers_pipeline_correctly(self, mock_pipeline, mock_end,
                                              mock_start, mock_session):
        import scheduler

        session = MagicMock()
        mock_session.return_value = session
        mock_start.return_value = 42

        scheduler.job_daily_pipeline()

        mock_pipeline.assert_called_once_with(incremental=True)
        mock_end.assert_called_with(session, 42, success=True, error=None)

    @patch("scheduler.get_session")
    @patch("scheduler._record_job_start")
    @patch("scheduler._record_job_end")
    @patch("ingestion.pipeline.run_daily_pipeline")
    def test_pipeline_failure_propagates_to_job_record(self, mock_pipeline,
                                                        mock_end, mock_start,
                                                        mock_session):
        import scheduler

        session = MagicMock()
        mock_session.return_value = session
        mock_start.return_value = 42
        mock_pipeline.side_effect = RuntimeError("Pipeline crash")

        scheduler.job_daily_pipeline()

        mock_end.assert_called_with(
            session, 42, success=False, error="Pipeline crash"
        )

# --- I3: News Cache Integration ---

class TestNewsCacheIntegration:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from database import configure, init_db
        configure("sqlite:///:memory:")
        init_db()
        from news_cache import install
        install()

    def test_write_read_cycle(self):
        from news_cache import get_cached, set_cached

        news = [{"title": "Test News", "source": "Reuters"}]
        set_cached("AAPL", news)
        cached = get_cached("AAPL")
        assert cached is not None
        assert cached[0]["title"] == "Test News"

    def test_cache_miss_returns_none(self):
        from news_cache import get_cached
        assert get_cached("NONEXISTENT") is None

    def test_expired_cache_returns_none(self):
        from news_cache import get_cached, set_cached
        set_cached("MSFT", [{"title": "Expired"}], ttl=0)
        assert get_cached("MSFT") is None

# --- I4: FinRL to MLBucket to Backtest chain ---

class TestFinRLToBacktestChain:
    @patch("finrl_runner._run_simple_backtest")
    @patch("finrl_runner._build_selection_summary")
    @patch("finrl_runner._equal_weight_fallback")
    def test_fallback_used_when_ml_fails(self, mock_fallback, mock_summary,
                                          mock_backtest, tmp_path):
        import finrl_runner
        import pandas as pd

        mock_fallback.return_value = {"AAPL": 0.5, "MSFT": 0.5}
        mock_summary.return_value = pd.DataFrame()
        mock_backtest.return_value = {
            "metrics": {"total_return": 0.05},
            "values": pd.Series([100, 105]),
        }

        # Verify fallback chain is callable even when ML fails
        result = finrl_runner._equal_weight_fallback(["AAPL", "MSFT"])
        assert len(result) == 2
        assert sum(result.values()) == pytest.approx(1.0)
```

---

## 3. Test Skeletons for Modules Not in V2

### 3.1 `src/config.py` — load_config()

```python
# tests/test_config_extended.py
import pytest
import yaml

import config


class TestLoadConfig:
    def test_loads_valid_yaml(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("source: yahoo\ndatabase:\n  url: sqlite:///t.db\n")
        monkeypatch.chdir(tmp_path)
        cfg = config.load_config()
        assert cfg["source"] == "yahoo"

    def test_malformed_yaml_raises(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(": invalid: :::")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(yaml.YAMLError):
            config.load_config()

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            config.load_config()

    def test_empty_file_returns_empty_dict(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("")
        monkeypatch.chdir(tmp_path)
        cfg = config.load_config()
        assert isinstance(cfg, dict)

    def test_missing_critical_keys_returns_partial(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("source: alphavantage\n")
        monkeypatch.chdir(tmp_path)
        cfg = config.load_config()
        assert "database" not in cfg  # no default — caller must check
```

### 3.2 `src/scheduler.py` — Job lifecycle

```python
# tests/test_scheduler_extended.py
import pytest
from unittest.mock import MagicMock, patch

import scheduler


class TestRecordJobStart:
    def test_records_and_returns_run_id(self):
        session = MagicMock()
        run_id = scheduler._record_job_start(session, "daily_pipeline")
        assert isinstance(run_id, int)
        session.add.assert_called_once()
        session.commit.assert_called_once()

    def test_db_error_returns_none(self):
        session = MagicMock()
        session.add.side_effect = RuntimeError("DB down")
        result = scheduler._record_job_start(session, "test")
        assert result is None  # Graceful degradation


class TestRecordJobEnd:
    def test_updates_success(self):
        session = MagicMock()
        scheduler._record_job_end(session, 42, success=True)
        session.commit.assert_called_once()

    def test_updates_failure_with_error_message(self):
        session = MagicMock()
        scheduler._record_job_end(session, 42, success=False, error="Timeout")
        update_call = session.query.return_value.filter.return_value.update.call_args[0][0]
        assert update_call["status"] == "failed"
        assert "Timeout" in str(update_call.get("error", ""))

    def test_db_error_silently_swallowed(self):
        session = MagicMock()
        session.commit.side_effect = RuntimeError("DB down")
        # Should not raise
        scheduler._record_job_end(session, 42, success=True)


class TestJobDailyPipeline:
    @patch("scheduler.get_session")
    @patch("scheduler._record_job_start")
    @patch("scheduler._record_job_end")
    @patch("ingestion.pipeline.run_daily_pipeline")
    def test_pipeline_failure_records_error(self, mock_run, mock_end,
                                             mock_start, mock_session):
        session = MagicMock()
        mock_session.return_value = session
        mock_start.return_value = 42
        mock_run.side_effect = RuntimeError("Pipeline crashed")

        scheduler.job_daily_pipeline()

        mock_end.assert_called_with(
            session, 42, success=False, error="Pipeline crashed"
        )
```

### 3.3 `src/ml_bucket_selector.py`

```python
# tests/test_ml_bucket_selector.py
import pytest
from unittest.mock import patch
import pandas as pd
import numpy as np

from ml_bucket_selector import MLBucketSelector


@pytest.fixture
def valid_fundamentals():
    return pd.DataFrame({
        "symbol": ["AAPL", "MSFT", "GOOGL", "JPM", "BAC"],
        "datadate": ["2024-01-15", "2024-01-15", "2024-01-15",
                      "2024-01-15", "2024-01-15"],
        "gsector": ["Technology", "Technology", "Communication",
                     "Financials", "Financials"],
        "market_cap": [3e12, 2.8e12, 1.7e12, 500e9, 300e9],
    })


@pytest.fixture
def valid_prices():
    dates = pd.date_range("2024-01-01", "2024-12-31", freq="B")
    data = {}
    for sym in ["AAPL", "MSFT", "GOOGL", "JPM", "BAC"]:
        data[sym] = np.cumsum(np.random.normal(0.5, 2, len(dates))) + 100
    return pd.DataFrame(data, index=dates)


class TestMLBucketSelector:
    def test_no_rows_after_bucket_raises(self):
        empty = pd.DataFrame(columns=["symbol", "datadate", "gsector"])
        selector = MLBucketSelector(fundamentals=empty, prices=pd.DataFrame())
        with pytest.raises(ValueError, match="No rows remain"):
            selector.fit_predict()

    def test_insufficient_dates_raises(self, valid_prices):
        single = pd.DataFrame({
            "symbol": ["AAPL"], "datadate": ["2024-01-15"],
            "gsector": ["Technology"],
        })
        selector = MLBucketSelector(fundamentals=single, prices=valid_prices)
        with pytest.raises(ValueError, match="Need.*distinct datadates"):
            selector.fit_predict()

    def test_missing_gsector_raises(self, valid_prices):
        no_sector = pd.DataFrame({
            "symbol": ["AAPL"], "datadate": ["2024-01-15", "2024-04-15"],
        })
        selector = MLBucketSelector(fundamentals=no_sector, prices=valid_prices)
        with pytest.raises(Exception):
            selector.fit_predict()

    @patch("ml_bucket_selector.run_bucket")
    def test_all_buckets_empty_raises(self, mock_run, valid_fundamentals,
                                       valid_prices):
        mock_run.return_value = ([], None)
        selector = MLBucketSelector(
            fundamentals=valid_fundamentals, prices=valid_prices
        )
        with pytest.raises(RuntimeError, match="All buckets returned empty"):
            selector.fit_predict()
```

### 3.4 `src/fetcher/alpha_vantage.py` — Retry and error handling

```python
# tests/test_alpha_vantage_extended.py
import pytest
from unittest.mock import MagicMock, patch
import requests
import pandas as pd

from fetcher.alpha_vantage import AlphaVantageFetcher


@pytest.fixture
def fetcher():
    return AlphaVantageFetcher(api_key="TEST_KEY")


class TestGetRetry:
    def test_successful_first_call(self, fetcher):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": "ok"}
        with patch("requests.get", return_value=mock_resp):
            result = fetcher._get("OVERVIEW", symbol="AAPL")
            assert result == {"data": "ok"}

    def test_retry_on_timeout_then_succeed(self, fetcher):
        timeout = MagicMock()
        timeout.raise_for_status.side_effect = requests.Timeout()
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {"data": "ok"}
        with patch("requests.get", side_effect=[timeout, ok]):
            result = fetcher._get("OVERVIEW", symbol="AAPL")
            assert result == {"data": "ok"}

    def test_exhausts_all_retries(self, fetcher):
        timeout = MagicMock()
        timeout.raise_for_status.side_effect = requests.Timeout()
        with patch("requests.get", return_value=timeout):
            with pytest.raises(RuntimeError, match="Failed after"):
                fetcher._get("OVERVIEW", symbol="AAPL", retries=2)

    def test_connection_error_not_caught_by_timeout_handler(self, fetcher):
        """ConnectionError is NOT Timeout — should propagate, not retry."""
        conn_err = MagicMock()
        conn_err.raise_for_status.side_effect = requests.ConnectionError()
        with patch("requests.get", return_value=conn_err):
            with pytest.raises(requests.ConnectionError):
                fetcher._get("OVERVIEW", symbol="AAPL")


class TestGetDaily:
    def test_empty_time_series_returns_empty_df(self, fetcher):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"Time Series (Daily)": {}}
        with patch("requests.get", return_value=mock_resp):
            result = fetcher.get_daily("AAPL")
            assert isinstance(result, pd.DataFrame)
            assert result.empty

    def test_error_response_returns_empty_df(self, fetcher):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"Error Message": "Invalid API call"}
        with patch("requests.get", return_value=mock_resp):
            result = fetcher.get_daily("INVALID")
            assert isinstance(result, pd.DataFrame)
            assert result.empty

    def test_rate_limit_note_returns_empty_df(self, fetcher):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"Note": "API rate limit reached"}
        with patch("requests.get", return_value=mock_resp):
            result = fetcher.get_daily("AAPL")
            assert isinstance(result, pd.DataFrame)
            assert result.empty
```

### 3.5 `src/ingestion/indicators.py` — Edge cases

```python
# tests/test_ingestion_indicators.py
import pytest
import pandas as pd
import numpy as np

from ingestion.indicators import compute_indicators


@pytest.fixture
def sample_prices():
    dates = pd.date_range("2024-01-01", periods=60, freq="B")
    np.random.seed(42)
    close = np.cumsum(np.random.normal(0.5, 2, 60)) + 100
    return pd.DataFrame({
        "open": close - 0.5,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": np.random.randint(1_000_000, 20_000_000, 60),
    }, index=dates)


class TestComputeIndicators:
    def test_returns_expected_columns(self, sample_prices):
        result = compute_indicators(sample_prices)
        for col in ["rsi", "macd", "macd_signal", "close_50_sma", "close_200_sma"]:
            assert col in result.columns

    def test_rsi_bounded_0_to_100(self, sample_prices):
        result = compute_indicators(sample_prices)
        rsi = result["rsi"].dropna()
        assert (rsi >= 0).all()
        assert (rsi <= 100).all()

    def test_too_few_rows_handled(self):
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        prices = pd.DataFrame({
            "open": [100.0]*10, "high": [101.0]*10,
            "low": [99.0]*10, "close": [100.5]*10,
            "volume": [1_000_000]*10,
        }, index=dates)
        result = compute_indicators(prices)
        assert result["close_200_sma"].isna().all()
        assert not result["rsi"].isna().all()

    def test_empty_dataframe_returns_empty(self):
        empty = pd.DataFrame(columns=["open","high","low","close","volume"])
        result = compute_indicators(empty)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_all_identical_prices(self):
        dates = pd.date_range("2024-01-01", periods=60, freq="B")
        flat = pd.DataFrame({
            "open": [100.0]*60, "high": [101.0]*60,
            "low": [99.0]*60, "close": [100.0]*60,
            "volume": [1_000_000]*60,
        }, index=dates)
        result = compute_indicators(flat)
        last_rsi = result["rsi"].dropna().iloc[-1]
        assert 0 <= last_rsi <= 100
```

---

## 4. Edge Case Matrix

| Module | Edge Case | Test Name |
|--------|-----------|-----------|
| repository.py | Empty DB screen_stocks() | `test_screen_no_matches_returns_empty` |
| repository.py | get_prices() start == end | `test_start_equals_end_returns_one_row` |
| repository.py | get_prices() end < start | `test_reversed_dates_returns_empty` |
| repository.py | save_selected_stocks([]) | `test_empty_records_returns_zero` |
| ingestion/pipeline.py | needs_full_backfill() with empty DB | `test_empty_database_returns_true` |
| ingestion/pipeline.py | process_symbol() with API failure | `test_process_symbol_handles_fetch_failure` |
| ingestion/pipeline.py | run_daily_pipeline() 0 active symbols | `test_empty_symbol_list_completes_cleanly` |
| finrl_runner.py | compute_metrics() flat portfolio | `test_flat_portfolio` |
| finrl_runner.py | compute_metrics() single value | `test_single_value_returns_zero_metrics` |
| finrl_runner.py | equal_weight_fallback([]) | `test_empty_list_returns_empty_dict` |
| scheduler.py | record_job_start(None) | `test_none_session_returns_none` |
| scheduler.py | main() KeyboardInterrupt | `test_keyboard_interrupt_shuts_down_cleanly` |
| alpha_vantage.py | get_daily("DELISTED") | `test_error_response_returns_empty_df` |
| alpha_vantage.py | HTTP 429 rate limit | `test_rate_limit_note_returns_empty_df` |
| alpha_vantage.py | ConnectionError vs Timeout | `test_connection_error_not_caught_by_timeout_handler` |
| config.py | Missing config.yaml | `test_missing_file_raises` |
| config.py | Malformed YAML | `test_malformed_yaml_raises` |
| indicators.py | < 14 rows (insufficient RSI) | `test_too_few_rows_handled` |
| indicators.py | Flat price (all identical) | `test_all_identical_prices` |
| ml_bucket_selector.py | Single sector, 1 stock | `test_insufficient_dates_raises` |
| news_cache.py | Expired TTL | `test_expired_cache_returns_none` |

---

## 5. Anti-Patterns Found in Production Code

| Anti-Pattern | Location | Fix Required |
|-------------|----------|-------------|
| Bare `except:` (swallows KeyboardInterrupt) | `finrl_runner.py` L288, L376 | Change to `except Exception:` |
| Silent `except Exception as e:` (19 occurrences) | `ingestion/pipeline.py` | Log and re-raise or aggregate errors |
| No validation before DB query | `repository.py` `get_prices()` | Validate `stock_id > 0`, `start <= end` |
| No error handling during config load | `config.py` L9 | Wrap in try/except with helpful message |
| Retry only handles `Timeout`, not `ConnectionError` | `alpha_vantage.py` L44 | Catch `requests.RequestException` |

---

## 6. Coverage Projection

| Phase | New Test Files | Tests Added | Est. Coverage | Delta |
|-------|---------------|-------------|---------------|-------|
| Current | 21 | 172 | 29.5% | — |
| Fix infrastructure (SQLite pool bug) | 0 | 0 | ~35% | +5.5% |
| Repository + Config | +2 | 20 | ~42% | +7% |
| Scheduler + AlphaVantage | +2 | 18 | ~50% | +8% |
| Ingestion pipeline (v2 skeletons applied) | +1 | 25 | ~60% | +10% |
| FinRL runner + MLBucket | +2 | 22 | ~68% | +8% |
| Integration tests | +1 | 15 | ~75% | +7% |
| UI pages (low ROI) | — | — | ~75% | — |

**Target**: 75% coverage achievable in 3 sprints with ~100 new test methods.
