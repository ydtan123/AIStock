# AIStock Test Coverage Gap Analysis v2

**Date**: 2026-05-30 (updated 19:30)
**Overall**: **29%** -- 4,000 statements, 2,839 missing, 1,161 covered
**Tests**: 172 total -- 140 passed, **12 failed, 20 errors**

---

## Executive Summary

| Tier | Files | Statements | Status |
|------|-------|-----------|--------|
| 100% | 11 | utils, models, display, rate_limiter, fetcher/* | Fully covered |
| 80-99% | 8 | pipeline core (orchestrator, config, fast_eval, deep_eval, stock_selection, deep_evaluators, fast_evaluators, base, database) | Acceptable |
| 50-79% | 2 | news_cache (54%), selectors (70%) | Needs extension |
| 1-49% | 6 | repository (29%), alpha_vantage (19%), scheduler (23%), data_update (44%), yahoo (38%), config (36%) | Sparse |
| **0%** | **24** | ingestion/*, finrl_runner, ml_bucket_selector, all ui/pages/*, app.py, main.py, ta_run.py | **Critical gap** |

## Existing Test Issues (Blocking)

### 12 Tests Failing

| Test | Reason |
|------|--------|
| `test_e2e_dashboard.py` | Chromium not installed in test env |
| `test_database.py` | SQLite incompatibility with MySQL DDL (`ON DUPLICATE KEY UPDATE`) |
| `test_full_pipeline_e2e.py` | `pipeline.base` import error |
| `test_pipeline_backends.py` | `finrl_runner` API changed after refactoring |
| `test_pipeline_data_update.py` (2 tests) | Config bypass fix changed mock signature |
| `test_scheduler.py` (6 tests) | `_record_job_start`/`_record_job_end` return type mismatch |

### 20 Tests Erroring (test_repository.py)

All 20 repository tests error because `StockRepository` methods were renamed/removed:

| Old method (test calls) | New API |
|--------------------------|---------|
| `get_stocks()` | `list_stocks(filters=StockFilters())` |
| `get_active_stocks()` | `list_stocks(filters=StockFilters(status="active"))` |
| `get_active_symbols()` | `list_stocks(...)` + extract symbols |
| `get_sectors()` | Same name, but signature changed |
| `get_job_runs()` | Same name, but return type changed |

**Fix priority**: Highest -- these tests are already written, just need API updates.

---

## Gap Analysis by Priority

### Tier 1 -- Critical (0% coverage, high business impact)

#### `src/ingestion/pipeline.py` -- 262 stmts, 0%

Core data ingestion orchestrator. **12 functions, 18 try/except blocks.**

Untested functions: `_prefetch_stock_dates`, `_fetch_and_store_prices`, `_upsert_fundamentals`, `_refresh_snapshots`, `_batch_update_checkpoints`, `_needs_full_backfill`, `_fetch_stock_news`, `_process_symbol`, `run_daily_pipeline`, `run_bootstrap`, `_auto_activate`

Critical error paths untested:
- Deadlock retry (3-attempt loop, line 145)
- ThreadPoolExecutor exception propagation (line 492)
- Pipeline failure recording in finally block (line 460)
- Empty stock list leads to clean summary
- All API calls fail leads to error count = stock count

#### `src/finrl_runner.py` -- 277 stmts, 0%

ML pipeline orchestrator. **7 functions, 12 raise statements.**

Untested: `run_pipeline_and_save_report`, `run_predict_only`, `_equal_weight_fallback`, `_run_simple_backtest`, `_compute_metrics`, `_build_selection_summary`

Critical error paths: No tickers (RuntimeError), no fundamentals (RuntimeError), bucket failure falls to fallback, backtest failure gives empty metrics, no model files (FileNotFoundError), all buckets empty (RuntimeError)

#### `src/ml_bucket_selector.py` -- 90 stmts, 0%

Sector ML pipeline wrapper. **2 methods, 3 raise statements.**

Untested: `MLBucketSelector.__init__`, `fit_predict`

Error paths: no rows after bucket gives ValueError, <2 dates gives ValueError, all buckets empty gives RuntimeError, per-sector exception is caught

#### `src/ingestion/indicators.py` -- 64 stmts, 0%

Technical indicator computation. pandas_ta integration, batch insert with deadlock retry (5 attempts).

#### `src/ingestion/symbols.py` -- 38 stmts, 0%

Symbol refresh from CSV listing. `_clean()` value sanitization, `refresh_symbols()` upsert pipeline.

### Tier 2 -- Sparse (<50% coverage)

#### `src/fetcher/alpha_vantage.py` -- 19% (100 missing lines)

API integration with retry logic. Untested: `_get()` retry/backoff, all financial statement parsing, rate limit handling, Timeout vs HTTPError distinction.

#### `src/repository.py` -- 29% (115 missing lines)

Data access layer. Newly refactored methods need tests: `find_stock`, `find_stocks_batch`, `get_prices`, `get_indicator`, `get_snapshot`, `get_tech_indicators`, `screen_stocks`, `list_stocks`, `save_predict_only_results`.

#### `src/scheduler.py` -- 23% (60 missing lines)

APScheduler jobs. Untested: `_record_job_start`, `_record_job_end`, `job_daily_pipeline`, `job_refresh_symbols`, `main()`.

#### `src/news_cache.py` -- 54% (42 missing lines)

News caching layer. Untested: cache miss path, `set_cached` write path, `install()` monkey-patching, `_ensure_table()`.

#### `src/config.py` -- 36% (9 missing lines)

Config loading. Untested: missing file leads to sys.exit, cache hit path.

### Tier 3 -- UI (0% coverage, low unit-test ROI)

**13 Streamlit page modules** (~940 stmts total). These need Playwright E2E tests, not pytest unit tests. See existing `tests/test_e2e_dashboard.py` for pattern.

---

## Integration Test Gaps

| Scenario | Status |
|----------|--------|
| Full ingestion: API to DB (prices, fundamentals, indicators) | Missing |
| Pipeline orchestrator: 4-step sequence, failure stopping | Missing |
| Pipeline resume: `--resume-from` skips completed steps | Missing |
| ML pipeline: `run_pipeline_and_save_report` to CSV/JSON output | Missing |
| ML predict-only: DB to predictions to selected_stocks table | Missing |
| Backtest: metrics computation, benchmark comparison | Missing |
| Scheduler: job registration to trigger to DB record | Missing |
| News cache: cache hit/miss to TradingAgents bypass | Missing |
| DB migrations: idempotency (run twice) | Covered |

---

## Error Handling Test Matrix

| Pattern | Count | Location | Test Needed |
|---------|-------|----------|-------------|
| MySQL deadlock retry (1213) | 2 | indicators.py:128, pipeline.py | Mock OperationalError |
| Rate limit backoff | 3 | alpha_vantage.py:37-42, pipeline.py | Verify wait intervals |
| Session cleanup in finally | 15+ | repository, news_cache, scheduler, pipeline | Verify close() always called |
| Rollback on error | 4 | symbols, indicators, pipeline | Verify rollback before re-raise |
| ThreadPoolExecutor exceptions | 1 | pipeline.py | Future.exception() propagation |
| Config missing key to default | 3 | scheduler.py:91, data_update.py:38 | Missing keys |
| Empty response to empty return | 6 | alpha_vantage, yahoo | Mock empty JSON/CSV |
| NaN/Inf sanitization | 3 | indicators.py:101, symbols.py:14 | Boundary float values |

---

## Test Skeletons

### 1. `tests/test_ingestion_pipeline.py`

```python
"""Tests for ingestion pipeline (src/ingestion/pipeline.py)."""
import pytest
from unittest.mock import MagicMock, patch, Mock
from datetime import date
import pandas as pd


class TestPrefetchStockDates:
    def test_empty_ids_returns_empty_dict(self):
        """Empty stock_ids returns empty maps, no DB query."""
        from ingestion.pipeline import _prefetch_stock_dates
        result = _prefetch_stock_dates([])
        assert result == {"max_price_dates": {}, "first_indicator_dates": {},
                          "first_price_dates": {}}

    def test_db_error_returns_empty_dict(self):
        """DB failure returns graceful fallback to empty maps."""
        with patch("ingestion.pipeline.get_session",
                   side_effect=Exception("DB down")):
            from ingestion.pipeline import _prefetch_stock_dates
            result = _prefetch_stock_dates([1, 2, 3])
            assert result == {"max_price_dates": {}, "first_indicator_dates": {},
                              "first_price_dates": {}}


class TestNeedsFullBackfill:
    def test_no_indicator_data_returns_true(self):
        from ingestion.pipeline import _needs_full_backfill
        assert _needs_full_backfill(1, first_indicator_date=None,
                                    first_price_date=date(2020, 1, 1))

    def test_no_price_data_returns_false(self):
        from ingestion.pipeline import _needs_full_backfill
        assert not _needs_full_backfill(1, first_indicator_date=date(2020, 6, 1),
                                        first_price_date=None)

    def test_gap_gt_3_days_returns_true(self):
        from ingestion.pipeline import _needs_full_backfill
        assert _needs_full_backfill(1, first_indicator_date=date(2020, 1, 10),
                                    first_price_date=date(2020, 1, 1))

    def test_gap_le_3_days_returns_false(self):
        from ingestion.pipeline import _needs_full_backfill
        assert not _needs_full_backfill(1, first_indicator_date=date(2020, 1, 3),
                                        first_price_date=date(2020, 1, 1))


class TestBatchUpdateCheckpoints:
    def test_empty_ids_noop(self):
        """Empty list means no DB call."""
        from ingestion.pipeline import _batch_update_checkpoints
        _batch_update_checkpoints([])  # Should not raise


class TestRunDailyPipeline:
    def test_empty_stock_list_returns_clean_summary(self, mock_fetcher):
        """No active stocks gives processed=0, errors=0."""
        with patch("ingestion.pipeline.get_session") as mock_sess:
            mock_sess.return_value.query.return_value.filter.\
                return_value.all.return_value = []
            from ingestion.pipeline import run_daily_pipeline
            summary = run_daily_pipeline(mock_fetcher)
            assert summary["processed"] == 0
            assert summary["errors"] == 0

    def test_all_failures_counts_errors(self, mock_fetcher):
        """Every stock raises gives error count = stock count."""
        pass

    def test_partial_failures_mixed_summary(self, mock_fetcher):
        """2 of 5 fail gives errors=2, processed=5."""
        pass

    def test_pipeline_run_record_created(self, mock_fetcher):
        """PipelineRun inserted with started_at, status='running'."""
        pass
```

### 2. `tests/test_repository_fix.py` (fix existing + extend)

```python
"""Fix broken repository tests + add coverage for new methods."""
import pytest
import pandas as pd
from datetime import date


class TestFindStock:
    def test_existing_symbol_returns_stock(self, repo):
        stock = repo.find_stock("AAPL")
        assert stock is not None
        assert stock.symbol == "AAPL"

    def test_nonexistent_returns_none(self, repo):
        assert repo.find_stock("ZZZZ") is None

    def test_case_insensitive(self, repo):
        stock = repo.find_stock("aapl")
        assert stock is not None


class TestFindStocksBatch:
    def test_multiple_symbols_returns_dict(self, repo):
        result = repo.find_stocks_batch(["AAPL", "MSFT"])
        assert len(result) == 2
        assert "AAPL" in result

    def test_empty_list_returns_empty_dict(self, repo):
        assert repo.find_stocks_batch([]) == {}

    def test_partial_match_returns_only_found(self, repo):
        result = repo.find_stocks_batch(["AAPL", "NONEXISTENT"])
        assert len(result) == 1


class TestGetPrices:
    def test_returns_dataframe_with_columns(self, repo):
        df = repo.get_prices(1, date(2020, 1, 1), date(2020, 12, 31))
        assert isinstance(df, pd.DataFrame)

    def test_no_data_returns_empty_dataframe(self, repo):
        df = repo.get_prices(99999, date(2020, 1, 1), date(2020, 12, 31))
        assert len(df) == 0


class TestScreenStocks:
    def test_all_none_criteria_returns_all(self, repo):
        from repository import ScreenCriteria
        df = repo.screen_stocks(ScreenCriteria())
        assert len(df) > 0


class TestBulkSetActive:
    def test_empty_ids_noop(self, repo):
        repo.bulk_set_active([], True)  # Should not raise


class TestSaveSelectedStocks:
    def test_empty_records_noop(self, repo):
        count = repo.save_selected_stocks([])
        assert count == 0
```

### 3. `tests/test_alpha_vantage_fetcher.py`

```python
"""Tests for AlphaVantageFetcher (src/fetcher/alpha_vantage.py)."""
import pytest
import requests
from unittest.mock import patch, Mock

from fetcher.alpha_vantage import AlphaVantageFetcher


@pytest.fixture
def fetcher():
    return AlphaVantageFetcher(api_key="test_key")


class TestPrivateGet:
    def test_successful_response(self, fetcher):
        with patch("requests.get") as mock_get:
            mock_get.return_value = Mock(
                status_code=200,
                json=lambda: {"key": "value"},
                raise_for_status=Mock(),
            )
            result = fetcher._get({"function": "OVERVIEW"})
            assert result == {"key": "value"}

    def test_rate_limit_response_retries(self, fetcher):
        """'Note' in JSON triggers wait then retry."""
        pass

    def test_error_message_raises(self, fetcher):
        """'Error Message' in JSON gives RuntimeError."""
        pass

    def test_all_retries_exhausted(self, fetcher):
        with patch("requests.get", side_effect=requests.Timeout()):
            with pytest.raises(RuntimeError, match="Failed after"):
                fetcher._get({"function": "OVERVIEW"})

    def test_retry_on_timeout_then_succeed(self, fetcher):
        pass

    def test_4xx_raises_immediately(self, fetcher):
        """4xx client error means no retry, raise HTTPError."""
        pass


class TestGetOverview:
    def test_valid_ticker_returns_dict(self, fetcher):
        with patch.object(fetcher, "_get",
                          return_value={"Symbol": "AAPL"}):
            result = fetcher.get_overview("AAPL")
            assert result["Symbol"] == "AAPL"

    def test_empty_response_returns_empty_dict(self, fetcher):
        with patch.object(fetcher, "_get", return_value={}):
            assert fetcher.get_overview("ZZZZ") == {}


class TestGetEarnings:
    def test_valid_earnings_returns_dataframe(self, fetcher):
        pass

    def test_type_error_in_parsing_handled(self, fetcher):
        """Non-numeric EPS values caught, empty DataFrame returned."""
        pass
```

### 4. `tests/test_ml_bucket_selector.py`

```python
"""Tests for MLBucketSelector (src/ml_bucket_selector.py)."""
import pytest
import pandas as pd
from unittest.mock import patch

from ml_bucket_selector import MLBucketSelector


def _make_fund_df(n_rows=20):
    dates = pd.date_range("2024-01-01", periods=n_rows, freq="QE")
    return pd.DataFrame({
        "ticker": ["AAPL"] * n_rows,
        "datadate": dates,
        "gsector": ["Technology"] * n_rows,
        "market_cap": [1e12] * n_rows,
    })


class TestMLBucketSelector:
    def test_init_stores_config(self):
        sel = MLBucketSelector(top_quantile=0.2,
                               weight_method="inverse_volatility")
        assert sel.top_quantile == 0.2

    def test_no_rows_after_bucket_raises(self):
        sel = MLBucketSelector()
        fund_df = _make_fund_df()
        fund_df["gsector"] = "UnknownSector"
        with pytest.raises(ValueError, match="No rows remain"):
            sel.fit_predict(fund_df)

    def test_single_date_raises(self):
        sel = MLBucketSelector()
        with pytest.raises(ValueError, match="≥2 distinct datadates"):
            sel.fit_predict(_make_fund_df(1))

    def test_all_buckets_empty_raises(self):
        sel = MLBucketSelector(top_quantile=0.3)
        with patch("ml_bucket_selector.run_bucket",
                   return_value=pd.DataFrame()):
            with pytest.raises(RuntimeError, match="All buckets returned empty"):
                sel.fit_predict(_make_fund_df())

    def test_partial_bucket_failure_continues(self):
        """One sector fails, others processed, partial results returned."""
        sel = MLBucketSelector(top_quantile=0.3)
        call_count = [0]

        def flaky_run(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Sector failed")
            return pd.DataFrame({
                "ticker": ["AAPL"], "ml_score": [0.8],
                "weight": [1.0], "bucket": ["Tech"],
            })

        with patch("ml_bucket_selector.run_bucket", flaky_run):
            result = sel.fit_predict(_make_fund_df())
            assert len(result) > 0
```

### 5. `tests/test_news_cache_extended.py`

```python
"""Extended news cache tests (src/news_cache.py)."""
import pytest
from unittest.mock import patch


class TestGetCached:
    def test_non_cacheable_tool_returns_none(self):
        from news_cache import get_cached
        assert get_cached("some_other_tool", ("AAPL",), {}) is None

    def test_db_error_returns_none(self):
        with patch("news_cache._get_session",
                   side_effect=Exception("DB down")):
            from news_cache import get_cached
            assert get_cached("get_news", ("AAPL",), {}) is None


class TestSetCached:
    def test_empty_result_skipped(self):
        from news_cache import set_cached
        set_cached("get_news", ("AAPL",), {}, "")    # Should not raise
        set_cached("get_news", ("AAPL",), {}, "   ")  # Should not raise

    def test_non_cacheable_tool_skipped(self):
        from news_cache import set_cached
        set_cached("other_tool", ("AAPL",), {}, "result")


class TestKey:
    def test_get_news_extracts_ticker_and_dates(self):
        from news_cache import _key
        ticker, start, end = _key(
            "get_news", ("AAPL", "2024-01-01", "2024-01-31"), {})
        assert ticker == "AAPL"
        assert start == "2024-01-01"

    def test_get_global_news_uses_global_marker(self):
        from news_cache import _key
        ticker, _, end = _key(
            "get_global_news", ("2024-01-31", 7, 10), {})
        assert ticker == "__global__"

    def test_get_insider_extracts_ticker(self):
        from news_cache import _key
        ticker, start, end = _key(
            "get_insider_transactions", ("AAPL",), {})
        assert ticker == "AAPL"
        assert start == ""

    def test_unknown_tool_returns_placeholder(self):
        from news_cache import _key
        ticker, _, _ = _key("unknown_func", (), {})
        assert ticker == "__unknown__"


class TestInstall:
    def test_idempotent(self):
        from news_cache import install
        install()
        install()  # Should not double-wrap

    def test_import_error_graceful(self):
        with patch("news_cache.importlib.import_module",
                   side_effect=ImportError):
            from news_cache import install
            install()  # Should not raise
```

### 6. `tests/test_scheduler_fix.py`

```python
"""Fix + extend scheduler tests (src/scheduler.py)."""
import pytest
from unittest.mock import patch


class TestRecordJobStart:
    def test_creates_running_record(self):
        from scheduler import _record_job_start
        run_id = _record_job_start("test_job")
        assert isinstance(run_id, int)

    def test_db_failure_returns_none(self):
        with patch("scheduler.get_session",
                   side_effect=Exception("DB down")):
            from scheduler import _record_job_start
            assert _record_job_start("test_job") is None


class TestRecordJobEnd:
    def test_success_sets_completed(self):
        pass

    def test_failure_sets_error_message(self):
        pass

    def test_error_truncated_to_2000_chars(self):
        from scheduler import _record_job_end, _record_job_start
        run_id = _record_job_start("test_job")
        _record_job_end(run_id, error="X" * 5000)
        # Verify truncation


class TestJobDailyPipeline:
    def test_catches_exceptions_does_not_crash(self):
        with patch("scheduler.run_daily_pipeline",
                   side_effect=Exception("Boom")):
            from scheduler import job_daily_pipeline
            job_daily_pipeline()  # Should not raise


class TestJobRefreshSymbols:
    def test_catches_exceptions_does_not_crash(self):
        with patch("scheduler.refresh_symbols",
                   side_effect=Exception("Boom")):
            from scheduler import job_refresh_symbols
            job_refresh_symbols()  # Should not raise
```

### 7. `tests/test_config.py`

```python
"""Tests for top-level config loader (src/config.py)."""
import pytest
from unittest.mock import patch


class TestLoadConfig:
    def test_cache_hit_returns_cached(self):
        import config
        config._config = {"cached": True}
        result = config.load_config()
        assert result == {"cached": True}

    def test_missing_config_yaml_exits(self):
        import config
        config._config = None
        with patch.object(config.Path, "exists", return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                config.load_config()
            assert exc_info.value.code == 1
```

### 8. `tests/test_integration_pipeline.py`

```python
"""Integration tests: pipeline orchestrator end-to-end."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile


@pytest.fixture
def temp_report_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestFullPipelineE2E:
    def test_all_steps_succeed_end_to_end(self, temp_report_dir):
        """4 steps run, reports written, pipeline_runs status='completed'."""
        pass

    def test_step_failure_stops_pipeline(self, temp_report_dir):
        """Step 2 fails, steps 3 and 4 never execute."""
        pass

    def test_resume_from_skips_completed(self, temp_report_dir):
        """--resume-from fast_evaluation skips first 2 steps."""
        pass

    def test_report_files_written(self, temp_report_dir):
        """Each step writes {name}.json + {name}.md."""
        pass


class TestIngestionIntegration:
    def test_full_ingestion_writes_prices(self, mock_fetcher):
        """Mock API, verify daily_prices has rows."""
        pass

    def test_full_ingestion_writes_fundamentals(self, mock_fetcher):
        """Mock API, verify stock_indicators has rows."""
        pass

    def test_partial_failure_counts_errors(self, mock_fetcher):
        """2 of 5 symbols fail, errors=2."""
        pass
```

---

## Prioritized Action Plan

### 🔴 Phase 1: Fix Broken Tests
1. Fix `test_repository.py` -- update 20 method calls to match new API
2. Fix `test_scheduler.py` -- update 6 assertion signatures
3. Fix `test_pipeline_data_update.py` -- update 2 config injection mocks
4. Fix `test_pipeline_backends.py` -- update finrl_runner import path
5. Fix `test_database.py` -- SQLite DDL compatibility
6. Skip `test_e2e_dashboard.py` in CI (needs browser)

**Est. gain**: ~5% (all broken tests pass)

### 🟡 Phase 2: Critical Module Tests
7. `tests/test_ingestion_pipeline.py` -- 262 stmts
8. `tests/test_ingestion_indicators.py` -- 64 stmts
9. `tests/test_ingestion_symbols.py` -- 38 stmts
10. `tests/test_alpha_vantage_fetcher.py` -- 100 missing lines
11. `tests/test_repository_fix.py` -- 115 missing lines
12. `tests/test_ml_bucket_selector.py` -- 90 stmts

**Est. gain**: ~15% (all critical 0% modules covered)

### 🟢 Phase 3: Integration + Error Handling
13. `tests/test_integration_pipeline.py` -- cross-module integration
14. `tests/test_error_handling.py` -- session cleanup, deadlock retry, rate limits
15. `tests/test_finrl_runner.py` -- 277 stmts
16. `tests/test_scheduler_fix.py` -- 60 missing lines

**Est. gain**: ~8% (integration gaps closed)

### 🔵 Phase 4: Lower Priority
17. `tests/test_config.py` -- 9 missing lines
18. `tests/test_yahoo_fetcher.py` -- 13 missing lines
19. `tests/test_ta_run.py` -- 309 stmts (needs mock LLM)
20. Playwright E2E tests for UI pages (~940 stmts)

**Est. gain**: ~10%

### Projected Coverage Trajectory

| Milestone | Coverage | Delta |
|-----------|----------|-------|
| Current | 29% | -- |
| Phase 1 (fix broken) | ~34% | +5% |
| Phase 2 (critical modules) | ~49% | +15% |
| Phase 3 (integration) | ~57% | +8% |
| Phase 4 (lower priority) | ~67% | +10% |
| **Target** | **~72%** | +43% |

Remaining gap: `ta_run.py` (~309 stmts, needs mock LLM), `main.py` (93 stmts, CLI), `full_pipeline.py` (55 stmts, CLI shim), `app.py` (203 stmts, Streamlit).

---

## New Test Files to Create

| File | Statements to Cover | Phase |
|------|---------------------|-------|
| `tests/test_ingestion_pipeline.py` | 262 | 2 |
| `tests/test_ingestion_indicators.py` | 64 | 2 |
| `tests/test_ingestion_symbols.py` | 38 | 2 |
| `tests/test_alpha_vantage_fetcher.py` | ~100 | 2 |
| `tests/test_ml_bucket_selector.py` | 90 | 2 |
| `tests/test_finrl_runner.py` | 277 | 3 |
| `tests/test_integration_pipeline.py` | -- | 3 |
| `tests/test_error_handling.py` | -- | 3 |
| `tests/test_config.py` | 9 | 4 |
| `tests/test_yahoo_fetcher.py` | 13 | 4 |
| `tests/test_ta_run.py` | 309 | 4 |
