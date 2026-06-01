# Test Coverage Gap Analysis — AIStock v2

**Date:** 2026-05-30  
**Overall Coverage:** 30% (3917 statements, 2761 missed)  
**Tests:** 172 collected, 140 passed, 12 failed, 20 errors  
**Baseline:** 17 files at 0% coverage, 28 files below 80%

---

## 1. Test Infrastructure Failures (Root Causes)

Before gap analysis, 32 tests are broken due to **2 infrastructure bugs**:

### Bug #1: `database.py` — MySQL-only pool args crash SQLite tests

`src/database.py:24`:
```python
_engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600, pool_size=8, max_overflow=4)
```

`max_overflow` incompatible with SQLite `SingletonThreadPool`. Affects ALL repository + scheduler tests (20 errors + 6 fails).

**Fix:** `database.py` should detect SQLite URL and skip pool args:
```python
if url.startswith("sqlite"):
    _engine = create_engine(url)
else:
    _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600, pool_size=8, max_overflow=4)
```

### Bug #2: `models.py` — MEDIUMTEXT column incompatible with SQLite

`stock_news.result` uses `MEDIUMTEXT()` which SQLite dialect can't compile. Affects `test_database.py::test_creates_all_tables_without_error`.

**Fix:** Use `Text()` (SQLAlchemy generic) which SQLAlchemy maps to SQLite TEXT:
```python
# models.py
from sqlalchemy import Text
result = Column(Text(), nullable=False)
```

---

## 2. Coverage by Module

### 0% Coverage (17 files, ~2000 statements — 51% of all missed lines)

| File | Stmts | Criticality | Reason |
|------|-------|-------------|--------|
| `src/ta_run.py` | 309 | Medium | Standalone CLI, no imports from pipeline |
| `src/ui/pages/ml_pipeline.py` | 299 | High | Streamlit UI, complex state management |
| `src/finrl_runner.py` | 277 | High | Core ML pipeline logic, 6 functions |
| `src/ingestion/pipeline.py` | 262 | Critical | Daily data pipeline, 11 functions, 15+ retry loops |
| `src/app.py` | 200 | High | Streamlit dashboard, 11 pages |
| `src/main.py` | 93 | Low | CLI entry, thin wrapper |
| `src/ml_bucket_selector.py` | 90 | High | ML model selection wrapper |
| `src/ui/pages/paper_trading.py` | 79 | Medium | Streamlit UI |
| `src/ingestion/indicators.py` | 64 | High | Technical indicator computation |
| `src/ui/pages/live_trading.py` | 63 | Medium | Streamlit UI |
| `src/ui/pages/stock_lookup.py` | 58 | Medium | Streamlit UI |
| `src/full_pipeline.py` | 55 | Low | CLI shim for orchestrator |
| `src/ui/pages/stock_manager.py` | 54 | Medium | Streamlit UI |
| `src/ui/pages/strategy_backtest.py` | 51 | Medium | Streamlit UI |
| `src/ui/pages/portfolio.py` | 42 | Medium | Streamlit UI |
| `src/ui/pages/stock_screener.py` | 42 | Medium | Streamlit UI |
| `src/ingestion/symbols.py` | 38 | High | Symbol refresh pipeline |

### Low Coverage (<80%, non-0%)

| File | Cover | Missed | Critical Gaps |
|------|-------|--------|---------------|
| `src/fetcher/alpha_vantage.py` | 19% | 100/124 | All 8 methods untested |
| `src/scheduler.py` | 23% | 60/78 | All 5 functions untested |
| `src/repository.py` | 28% | 113/158 | 12/15 methods untested |
| `src/config.py` | 36% | 9/14 | `load_config()` untested |
| `src/news_cache.py` | 54% | 42/91 | Cache fetch+store untested |
| `src/fetcher/yahoo.py` | 38% | 13/21 | 3/4 methods untested |
| `src/pipeline/backends/selectors.py` | 28% | 43/60 | `FinrlStockSelector.select()` untested |

### Adequately Tested (80%+)

| File | Cover | Notes |
|------|-------|-------|
| `src/models.py` | 100% | Declarative base, all tables touched |
| `src/migrations/run.py` | 100% | Migration runner tests exist |
| `src/display.py` | 100% | Formatting utilities |
| `src/fetcher/rate_limiter.py` | 100% | Token bucket tests |
| `src/database.py` | 90% | `init_db()` row counts only gap |
| `src/pipeline/backends/deep_evaluators.py` | 80% | Exception paths + edge cases only gap |
| `src/pipeline/backends/fast_evaluators.py` | 81% | `_last_trading_date()` edge cases |

---

## 3. Gap Analysis by Category

### 3.1 Untested Functions (by priority)

#### CRITICAL — Data Pipeline (`src/ingestion/pipeline.py`)

| Function | Lines | What's Missing |
|----------|-------|----------------|
| `_prefetch_stock_dates()` | 44-92 | Empty stock_ids return, DB connection lost mid-query |
| `_fetch_and_store_prices()` | 95-173 | Deadlock retry exhausted, start>end date, empty DataFrame, invalid API response |
| `_upsert_fundamentals()` | 176-251 | Stale indicator check, DB freshness fallback, empty overview response |
| `_refresh_snapshots()` | 254-300 | Empty data for all stocks, NULL handling in REPLACE INTO |
| `_batch_update_checkpoints()` | 303-315 | Empty stock_ids, partial failures |
| `_needs_full_backfill()` | 318-352 | No indicator data, no price data, both NULL |
| `_fetch_stock_news()` | 355-371 | Network failure, empty response, invalid symbol |
| `_process_symbol()` | 374-408 | All error is caught silently — verify error dict shape |
| `run_daily_pipeline()` | 411-477 | ThreadPoolExecutor partial failure, symbols_processed vs errors_count mismatch |
| `run_bootstrap()` | 480-503 | Empty OVERVIEW response, API rate limit mid-bootstrap |
| `_auto_activate()` | 506-522 | Empty criteria, no stocks match criteria |

#### HIGH — ML Runner (`src/finrl_runner.py`)

| Function | Lines | What's Missing |
|----------|-------|----------------|
| `run_pipeline_and_save_report()` | 45-130 | No tickers, no fundamentals, equal-weight fallback, backtest failure, selection summary save failure |
| `run_predict_only()` | 133-257 | No model files, empty selected_stocks table, missing feature columns, unmapped sectors, NaN outlier clipping |
| `_equal_weight_fallback()` | 262-268 | All-zero fund_df, division by zero |
| `_run_simple_backtest()` | 271-332 | Empty gvkeys, benchmark fetch failure, no trading days |
| `_compute_metrics()` | 335-350 | All-zero returns, max_dd=0, negative Sharpe |

#### HIGH — Repository (`src/repository.py`)

| Method | Lines | What's Missing |
|--------|-------|----------------|
| `screen_stocks()` | 102-138 | All criteria NULL, wildcard LIKE patterns, NULL-safe IS NULL branches |
| `list_stocks()` | 142-180 | Empty filters, LEFT JOIN with no matches, ORDER BY non-existent column |
| `save_selected_stocks()` | 211-239 | Empty records list, partial insert (some rows duplicate), rollback on error |
| `save_predict_only_results()` | 241-263 | None weight values, duplicate predictions for same stock, empty predictions list |
| `get_latest_selected_stocks()` | 265-293 | Multiple runs with same timestamp, zero selected stocks |
| `get_job_runs()` | 295-315 | Empty table, limit=0, limit>row_count |

#### HIGH — Scheduler (`src/scheduler.py`)

| Function | Lines | What's Missing |
|----------|-------|----------------|
| `_record_job_start()` | 23-31 | DB connection failure, duplicate job names |
| `_record_job_end()` | 34-47 | run_id not found, error_message > 2000 chars, NULL error |
| `job_daily_pipeline()` | 50-66 | Import failure from ingestion, pipeline returns errors |
| `job_refresh_symbols()` | 69-84 | API rate limit, empty listing response |
| `main()` | 87-127 | Invalid run_time format, scheduler already running |

### 3.2 Missing Error Handling Tests (~67 error handling blocks, ~60 untested)

| Pattern | Count | Location | Test Needed |
|---------|-------|----------|-------------|
| Deadlock retry loop (1213) | 5 | `ingestion/pipeline.py`, `indicators.py` | Retry exhausted, non-deadlock Exception re-raised, backoff timing |
| `except Exception` silent catch | 12 | `ingestion/pipeline.py`, `finrl_runner.py`, `deep_evaluators.py` | Verify error dict shape, verify non-fatal warnings logged |
| `try/finally` session close | 20+ | `repository.py`, `scheduler.py`, `ingestion/*` | Session close even on exception, no double-close |
| HTTP retry (rate limit + timeout) | 1 | `fetcher/alpha_vantage.py::_get()` | Rate limit 15-45s wait, timeout backoff, 5xx retry, 4xx re-raise |
| `except KeyError` registry | 3 | `pipeline/backends/selectors.py`, `deep_evaluation.py`, `fast_evaluation.py` | Unknown backend name |
| `except TypeError` validation | 3 | `pipeline/base.py`, `selectors.py` | Subclass without name attribute |

### 3.3 Edge Cases Not Covered

| Category | Examples | Files |
|----------|----------|-------|
| **Empty collections** | empty stock_ids, empty tickers, empty filters, empty DataFrames | `ingestion/pipeline.py`, `repository.py`, `deep_evaluators.py`, `fast_evaluators.py` |
| **None/missing values** | None weights, None indicators, None sector, None start/end dates | `repository.py`, `finrl_runner.py`, `fast_evaluators.py` |
| **Division by zero** | zero volatility, zero max drawdown, zero total confidence | `finrl_runner.py::_compute_metrics()`, `fast_evaluators.py::_compute_consensus()` |
| **Boundary values** | limit=0, error > 2000 chars, date=weekend | `scheduler.py`, `repository.py`, `fast_evaluators.py` |
| **Concurrency** | ThreadPoolExecutor partial failure, race conditions | `ingestion/pipeline.py::run_daily_pipeline()` |
| **NaN/Inf values** | indicators JSON with NaN → None conversion, inf clipping | `indicators.py`, `finrl_runner.py` |

### 3.4 Integration Test Gaps

| Flow | Status | Gap |
|------|--------|-----|
| **Full pipeline E2E** | 1 test exists, FAILING | test broken — `pipeline.base` attribute error |
| **Data ingestion → DB** | NO tests | fetch_and_store_prices → upsert, fundamentals → upsert, snapshots REFRESH |
| **Stock selection → evaluation** | NO tests | select tickers → fast evaluate → deep evaluate (3-step chain) |
| **ML model train → predict** | 1 smoke test | Only max_high_5pct label, other labels untested E2E |
| **Scheduler job chain** | 0 working tests | All 6 failed — job_start → pipeline → job_end chain |
| **Fetcher → API** | NO tests | Alpha Vantage rate limit retry, Yahoo fallback, error responses |
| **Streamlit dashboard** | 1 E2E test, FAILING | All 11 pages need at minimum smoke rendering tests |
| **CLI entry points** | NO tests | `main.py`, `full_pipeline.py`, `ta_run.py` |

---

## 4. Test Skeletons

### 4.1 `tests/test_ingestion_pipeline.py` (CRITICAL)

```python
"""Tests for src/ingestion/pipeline.py — daily data pipeline."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, timedelta


# ============================================================
# _prefetch_stock_dates
# ============================================================

class TestPrefetchStockDates:
    def test_empty_stock_ids_returns_empty_dict(self):
        """prefetch with [] returns {dates: {}, indicators: {}}."""
        from ingestion.pipeline import _prefetch_stock_dates
        result = _prefetch_stock_dates([])
        assert result == {"dates": {}, "indicators": {}}

    def test_returns_max_and_min_per_stock(self):
        """prefetch returns correct structure for valid stock_ids."""
        pass

    def test_stock_with_no_prices_has_none_values(self):
        """Stock with no daily_prices has None for both fields."""
        pass

    def test_session_closed_on_exception(self):
        """session.close() called even when query raises."""
        pass


# ============================================================
# _fetch_and_store_prices
# ============================================================

class TestFetchAndStorePrices:
    def test_returns_zero_on_empty_dataframe(self):
        """Returns (0, False, []) when Alpha Vantage returns empty data."""
        pass

    def test_returns_early_when_start_after_end(self):
        """When max_date is today, start > end → returns early with 0."""
        pass

    def test_deadlock_retry_on_mysql_1213(self):
        """Retries up to 5 times on deadlock error 1213."""
        pass

    def test_deadlock_exhausted_reraises(self):
        """After 5 deadlock retries, re-raises the original exception."""
        pass

    def test_non_deadlock_exception_not_retried(self):
        """Non-1213 errors (e.g., IntegrityError) re-raised immediately."""
        pass

    def test_session_rollback_on_error(self):
        """session.rollback() called in outer except block."""
        pass

    def test_new_prices_flag_true_when_inserted(self):
        """Returns (n, True, []) when rows inserted."""
        pass


# ============================================================
# _upsert_fundamentals
# ============================================================

class TestUpsertFundamentals:
    def test_skips_on_fresh_indicator_check(self):
        """Returns (False, False) when indicator_last_updated >= overview date."""
        pass

    def test_falls_back_to_db_when_no_prefetch(self):
        """Uses DB query when indicator_last_updated is None."""
        pass

    def test_returns_false_on_empty_overview(self):
        """Returns (False, False) when fetcher.get_overview() returns {}."""
        pass

    def test_returns_false_on_missing_symbol_key(self):
        """Returns (False, False) when Symbol key missing from response."""
        pass


# ============================================================
# _process_symbol
# ============================================================

class TestProcessSymbol:
    def test_catches_exceptions_returns_error_dict(self):
        """Returns dict with 'error' key on exception, doesn't re-raise."""
        pass

    def test_fetches_news_when_force_or_new_prices(self):
        """Calls _fetch_stock_news when force=True or new_prices=True."""
        pass

    def test_skips_news_when_not_forced_and_no_new_prices(self):
        """Skips news fetch for incremental runs without new data."""
        pass


# ============================================================
# _fetch_stock_news
# ============================================================

class TestFetchStockNews:
    def test_returns_zero_on_exception(self):
        """Returns 0 on any exception, never raises."""
        pass

    def test_returns_count_on_success(self):
        """Returns n where n > 0 on successful news fetch."""
        pass


# ============================================================
# run_daily_pipeline
# ============================================================

class TestRunDailyPipeline:
    def test_tracks_processed_vs_errors_separately(self):
        """Returns dict with 'processed', 'errors', 'status' keys."""
        pass

    def test_status_completed_when_no_errors(self):
        pass

    def test_status_completed_with_errors_when_some_fail(self):
        pass

    def test_thread_pool_partial_failure_continues(self):
        """One thread failing doesn't stop other stocks."""
        pass


# ============================================================
# run_bootstrap
# ============================================================

class TestRunBootstrap:
    def test_fetches_all_inactive_stocks(self):
        pass

    def test_auto_activates_based_on_criteria(self):
        pass
```

### 4.2 `tests/test_finrl_runner.py` (HIGH)

```python
"""Tests for src/finrl_runner.py — FinRL pipeline runner."""
import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
from datetime import date


class TestRunPipelineAndSaveReport:
    def test_raises_runtime_error_when_no_tickers(self):
        """RuntimeError when data source returns empty ticker list."""
        from finrl_runner import run_pipeline_and_save_report
        with patch("finrl_runner.create_data_source") as mock_src:
            mock_src.return_value.get_sp500_components.return_value = pd.DataFrame()
            with pytest.raises(RuntimeError, match="tickers"):
                run_pipeline_and_save_report(None)

    def test_raises_runtime_error_when_no_fundamental_data(self):
        """RuntimeError when fund_df is empty."""
        pass

    def test_equal_weight_fallback_on_ml_failure(self):
        """Uses _equal_weight_fallback when MLBucketSelector fails."""
        pass

    def test_backtest_failure_warns_but_does_not_raise(self):
        """Backtest Exception logged as warning, pipeline continues."""
        pass


class TestRunPredictOnly:
    def test_raises_file_not_found_when_no_models(self):
        """FileNotFoundError when models_dir has no .pkl files."""
        from finrl_runner import run_predict_only
        with pytest.raises(FileNotFoundError):
            run_predict_only(["AAPL"], "aistock_db", "/nonexistent/path")

    def test_raises_value_error_when_no_selected_stocks(self):
        """ValueError when selected_stocks table is empty."""
        pass

    def test_handles_missing_feature_columns(self):
        """Backfills missing feature columns with median, fills NaN with 0."""
        pass

    def test_clips_outliers_at_1st_and_99th_percentile(self):
        """Values outside [1st, 99th] percentile clipped."""
        pass

    def test_fills_nan_with_zero_before_prediction(self):
        """NaN values replaced with 0 before model.predict()."""
        pass

    def test_inf_values_replaced_with_zero(self):
        """np.inf and -np.inf replaced with 0."""
        pass

    def test_skips_unmapped_sector_rows(self):
        """Rows without gsector mapping excluded from prediction."""
        pass


class TestRunSimpleBacktest:
    def test_empty_gvkeys_returns_empty_dict(self):
        """Returns {} when no gvkeys after filtering."""
        pass

    def test_benchmark_fetch_failure_continues(self):
        """Per-benchmark Exception caught, other benchmarks still fetched."""
        pass

    def test_zero_trading_days_returns_empty_metrics(self):
        """Empty returns → empty metrics dict, no division by zero."""
        pass


class TestComputeMetrics:
    def test_zero_volatility_returns_zero_sharpe(self):
        """Sharpe ratio = 0 when volatility is 0."""
        from finrl_runner import _compute_metrics
        zero_returns = pd.Series([0.0, 0.0, 0.0])
        result = _compute_metrics(zero_returns)
        assert result["sharpe_ratio"] == 0.0

    def test_zero_max_drawdown_returns_zero_calmar(self):
        """Calmar ratio = 0 when max_drawdown is 0."""
        from finrl_runner import _compute_metrics
        positive_only = pd.Series([0.01, 0.02, 0.01])
        result = _compute_metrics(positive_only)
        assert result["calmar_ratio"] == 0.0

    def test_negative_returns_computed_correctly(self):
        """Sharpe < 0 for consistently negative returns."""
        pass

    def test_single_value_returns(self):
        """Single return value handled without error."""
        pass


class TestBuildSelectionSummary:
    def test_skips_failed_model_loads(self):
        """Exception on model load → stock skipped, summary continues."""
        pass

    def test_empty_models_returns_empty_summary(self):
        pass
```

### 4.3 `tests/test_repository_methods.py` (HIGH)

```python
"""Tests for uncovered StockRepository methods."""
import pytest
from datetime import date
from src.repository import StockRepository, ScreenCriteria, StockFilters


class TestScreenStocks:
    def test_all_criteria_none_returns_all_stocks(self):
        """When all ScreenCriteria fields are None, no WHERE clauses."""
        pass

    def test_partial_criteria_filters_correctly(self):
        """Some criteria set, some None → only set ones filter."""
        pass

    def test_price_range_filter_inclusive(self):
        """Price BETWEEN min and max inclusive."""
        pass

    def test_pattern_matching_with_percent_sign(self):
        """LIKE '%AAPL%' works correctly for wildcard name search."""
        pass

    def test_null_sector_included_by_default(self):
        """Stocks with NULL sector returned when sector filter is None."""
        pass


class TestListStocks:
    def test_empty_filters_returns_all_stocks(self):
        pass

    def test_left_join_with_no_indicator_data(self):
        """Stock without indicator row still returned via LEFT JOIN."""
        pass

    def test_sector_filter_exact_match(self):
        pass

    def test_exchange_filter_case_sensitive(self):
        pass


class TestSaveSelectedStocks:
    def test_empty_records_list_noop(self):
        """Empty list → no insert, no error."""
        pass

    def test_bulk_upsert_on_duplicate_key(self):
        """Re-running with same pipeline_run_id + ticker updates row."""
        pass

    def test_rollback_on_partial_failure(self):
        """If one row fails, entire transaction rolled back."""
        pass

    def test_correct_pipeline_run_id_assigned(self):
        pass


class TestSavePredictOnlyResults:
    def test_empty_predictions_noop(self):
        """Empty list → no insert, no error."""
        pass

    def test_none_weight_handled_gracefully(self):
        """pred.get("weight") returning None doesn't crash."""
        pass

    def test_duplicate_symbol_prediction_upserts(self):
        """Same symbol predicted twice → last write wins via upsert."""
        pass


class TestGetLatestSelectedStocks:
    def test_no_pipeline_runs_returns_empty_list(self):
        pass

    def test_most_recent_run_only(self):
        """Returns stocks from newest pipeline_run_id only."""
        pass

    def test_stocks_sorted_by_ml_score_desc(self):
        pass


class TestGetJobRuns:
    def test_empty_table_returns_empty_dataframe(self):
        pass

    def test_limit_zero_returns_empty(self):
        pass

    def test_respects_limit_param(self):
        """Returns at most `limit` rows."""
        pass

    def test_ordered_by_started_at_desc(self):
        """Most recent run first."""
        pass
```

### 4.4 `tests/test_alpha_vantage_fetcher.py` (HIGH)

```python
"""Tests for src/fetcher/alpha_vantage.py — Alpha Vantage API client."""
import pytest
import requests
from unittest.mock import MagicMock, patch
from src.fetcher.alpha_vantage import AlphaVantageFetcher


class TestHttpGet:
    def test_rate_limit_detected_by_note_key(self):
        """Response with 'Note' key → waits 15-45s, retries."""
        pass

    def test_rate_limit_detected_by_information_key(self):
        """Response with 'Information' key containing 'rate limit' → waits."""
        pass

    def test_timeout_retry_with_exponential_backoff(self):
        """requests.Timeout → retries with 5s, 10s, 20s backoff."""
        pass

    def test_http_4xx_error_reraises_immediately(self):
        """400-level errors not retried — re-raised immediately."""
        pass

    def test_http_5xx_error_retried(self):
        """500-level errors retried up to MAX_RETRIES."""
        pass

    def test_max_retries_exhausted_raises_runtime_error(self):
        """After MAX_RETRIES failures, RuntimeError raised."""
        pass


class TestGetDaily:
    def test_compact_vs_full_outputsize_selection(self):
        """compact when start within last 100 days, full otherwise."""
        pass

    def test_date_filter_skips_out_of_range_rows(self):
        pass

    def test_empty_response_returns_empty_dataframe(self):
        pass


class TestGetOverview:
    def test_missing_symbol_key_returns_empty_dict(self):
        """Response without 'Symbol' → {}."""
        pass

    def test_nan_values_converted_to_none(self):
        """NaN/inf fields → None via safe_float/safe_int/safe_date."""
        pass

    def test_all_fields_present_in_response(self):
        """Verify expected fields: MarketCapitalization, PERatio, etc."""
        pass


class TestGetListing:
    def test_filters_active_only(self):
        """Only status='Active' rows returned."""
        pass

    def test_filters_nyse_and_nasdaq_only(self):
        pass

    def test_filters_colon_symbols(self):
        """Symbols containing ':' excluded (ETFs/funds)."""
        pass

    def test_filters_long_symbols(self):
        """Symbols > 20 chars excluded."""
        pass
```

### 4.5 `tests/test_scheduler_functions.py` (MEDIUM)

```python
"""Tests for src/scheduler.py — APScheduler jobs."""
import pytest
from unittest.mock import MagicMock, patch


class TestRecordJobStart:
    def test_returns_run_id_on_success(self):
        pass

    def test_session_closed_after_insert(self):
        """session.close() called in finally block."""
        pass

    def test_db_connection_failure_raises(self):
        """If create_engine fails, exception propagated."""
        pass


class TestRecordJobEnd:
    def test_updates_finished_at_and_status(self):
        pass

    def test_error_message_truncated_to_2000_chars(self):
        """Messages longer than 2000 chars sliced."""
        pass

    def test_null_error_stored_as_none(self):
        """error=None → stored as NULL in DB."""
        pass

    def test_run_id_not_found_raises(self):
        """Nonexistent run_id → exception from UPDATE."""
        pass


class TestJobDailyPipeline:
    def test_records_job_start_and_end(self):
        """Ensures both _record_job_start and _record_job_end called."""
        pass

    def test_exception_in_pipeline_caught_and_stored(self):
        """Pipeline Exception → error message stored, job marked completed."""
        pass

    def test_finally_always_records_job_end(self):
        """_record_job_end called even when pipeline succeeds."""
        pass


class TestJobRefreshSymbols:
    def test_records_job_start_and_end(self):
        pass

    def test_exception_caught_and_stored(self):
        pass


class TestMain:
    def test_invalid_run_time_format_raises(self):
        """run_time='invalid' → ValueError."""
        pass

    def test_keyboard_interrupt_graceful_shutdown(self):
        """Ctrl+C → clean exit, no traceback."""
        pass

    def test_scheduler_adds_both_jobs(self):
        """Both daily_pipeline and refresh_symbols jobs registered."""
        pass
```

### 4.6 `tests/test_ingestion_indicators.py` (HIGH)

```python
"""Tests for src/ingestion/indicators.py — technical indicator computation."""
import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np


class TestComputeIndicators:
    def test_returns_zero_when_no_price_rows(self):
        """stock_id with no daily_prices → returns 0."""
        pass

    def test_fills_missing_ohlcv_with_zero(self):
        """NaN in OHLCV columns → filled with 0.0."""
        pass

    def test_filters_to_since_date_after_computation(self):
        """Only rows >= since_date returned."""
        pass

    def test_returns_zero_when_filtered_dataframe_empty(self):
        """All rows before since_date → returns 0."""
        pass

    def test_nan_inf_converted_to_none(self):
        """NaN, inf, -inf → None for JSON serialization."""
        pass

    def test_deadlock_retry_on_1213(self):
        """Retries INSERT ON DUPLICATE KEY UPDATE on deadlock."""
        pass

    def test_deadlock_exhausted_reraises(self):
        """After 5 retries, re-raises original exception."""
        pass

    def test_non_deadlock_exception_not_retried(self):
        """IntegrityError etc. re-raised immediately."""
        pass

    def test_session_closed_in_finally(self):
        """session.close() called even on exception."""
        pass
```

### 4.7 `tests/test_ingestion_symbols.py` (MEDIUM)

```python
"""Tests for src/ingestion/symbols.py — NASDAQ/NYSE listing refresh."""
import pytest
from unittest.mock import MagicMock, patch
import numpy as np


class TestClean:
    def test_none_returns_none(self):
        from ingestion.symbols import _clean
        assert _clean(None) is None

    def test_nan_returns_none(self):
        from ingestion.symbols import _clean
        assert _clean(float("nan")) is None

    def test_integer_returns_integer(self):
        from ingestion.symbols import _clean
        assert _clean(42) == 42

    def test_string_returns_string(self):
        from ingestion.symbols import _clean
        assert _clean("AAPL") == "AAPL"

    def test_type_error_returns_original(self):
        """Non-numeric conversion TypeError → original value returned."""
        from ingestion.symbols import _clean
        assert _clean([1, 2, 3]) == [1, 2, 3]


class TestRefreshSymbols:
    def test_empty_listing_returns_zero(self):
        """Fetcher returns empty CSV → count=0."""
        pass

    def test_upserts_new_symbols(self):
        """New symbols inserted, existing updated."""
        pass

    def test_session_rollback_on_error(self):
        """session.rollback() called, exception re-raised."""
        pass

    def test_cleans_nan_fields(self):
        """NaN in assetType, exchange → None in DB."""
        pass
```

### 4.8 `tests/test_pipeline_backends_deep.py` (MEDIUM)

```python
"""Tests for src/pipeline/backends/deep_evaluators.py extra paths."""
import pytest
from unittest.mock import MagicMock, patch


class TestExtractDecision:
    def test_extracts_buy_from_uppercase(self):
        from src.pipeline.backends.deep_evaluators import _extract_decision
        assert _extract_decision("decision: BUY", "HOLD") == "BUY"

    def test_extracts_sell_from_lowercase(self):
        from src.pipeline.backends.deep_evaluators import _extract_decision
        assert _extract_decision("decision: sell", "HOLD") == "SELL"

    def test_fallback_when_none_found(self):
        from src.pipeline.backends.deep_evaluators import _extract_decision
        assert _extract_decision("gibberish text", "HOLD") == "HOLD"

    def test_handle_found_in_prefix(self):
        """'handle' contains 'hold' — must not match substring."""
        from src.pipeline.backends.deep_evaluators import _extract_decision
        assert _extract_decision("I recommend to handle this as BUY", "HOLD") == "BUY"


class TestTradingAgentsDeepEvaluator:
    def test_empty_tickers_returns_empty_list(self):
        """evaluate([]) → []."""
        pass

    def test_ticker_exception_skipped_not_fatal(self):
        """One ticker failing doesn't stop others."""
        pass

    def test_news_cache_install_failure_non_fatal(self):
        """_install_news_cache Exception caught, evaluator continues."""
        pass

    def test_langchain_messages_skipped_in_serialization(self):
        """Messages objects excluded from extra_outputs dict."""
        pass

    def test_result_may_be_tuple_handled(self):
        """result may be (decision, reasoning) tuple."""
        pass
```

### 4.9 `tests/test_pipeline_backends_fast.py` (MEDIUM)

```python
"""Tests for src/pipeline/backends/fast_evaluators.py edge cases."""
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch


class TestLastTradingDate:
    def test_monday_returns_previous_friday(self):
        """Monday → last Friday."""
        pass

    def test_tuesday_returns_monday(self):
        """Tuesday → Monday."""
        pass

    def test_saturday_returns_friday(self):
        """Saturday → Friday (1 day back)."""
        pass

    def test_sunday_returns_friday(self):
        """Sunday → Friday (2 days back)."""
        pass

    def test_monday_jan1_handles_year_boundary(self):
        """Year boundary doesn't break date arithmetic."""
        pass


class TestComputeConsensus:
    def test_zero_total_confidence_returns_zero(self):
        """total_confidence <= 0 → 0.0."""
        from src.pipeline.backends.fast_evaluators import _compute_consensus
        opinions = [("analyst1", "bullish", 0.0, "reason")]
        assert _compute_consensus(opinions) == 0.0

    def test_mixed_opinions_weighted_correctly(self):
        """Weighted average with different confidences."""
        pass

    def test_bearish_opinions_subtract_from_score(self):
        """bearish weight * confidence subtracted."""
        pass

    def test_empty_opinions_returns_zero(self):
        pass


class TestResolveDates:
    def test_default_start_is_end_minus_90_days(self):
        pass

    def test_explicit_start_and_end_used_as_is(self):
        pass

    def test_both_none_uses_last_trading_date(self):
        pass
```

### 4.10 `tests/test_pipeline_orchestrator_edge.py` (MEDIUM)

```python
"""Tests for src/pipeline/orchestrator.py edge cases."""
import pytest
from src.pipeline.base import PipelineError


class TestFullPipelineEdgeCases:
    def test_resume_from_without_run_id_raises(self):
        """ValueError if resume_from set but run_id is None."""
        from src.pipeline.orchestrator import FullPipeline
        with pytest.raises(ValueError, match="run_id"):
            FullPipeline(steps=[], cfg={}, session_factory=None,
                        report_root=None, logger=None,
                        resume_from="deep_evaluation", run_id=None)

    def test_resume_already_successful_run_raises(self):
        """PipelineError if resuming a run already marked 'success'."""
        pass

    def test_unknown_resume_from_name_raises(self):
        """ValueError if resume_from step not in step list."""
        pass

    def test_serialize_result_handles_datetime_objects(self):
        """_serialize_result converts datetime to ISO string."""
        pass

    def test_step_to_markdown_with_empty_payload(self):
        """_step_to_markdown handles payload=None gracefully."""
        pass

    def test_step_failure_stops_pipeline_chain(self):
        """Remaining steps not executed after first failure."""
        pass

    def test_only_filter_runs_subset_of_steps(self):
        """only=['stock_selection'] runs only that step."""
        pass


class TestOpenSession:
    def test_non_context_manager_session(self):
        """Plain session object (not context manager) handled."""
        pass

    def test_context_manager_session(self):
        """Session factory returning context manager works."""
        pass
```

### 4.11 `tests/test_pipeline_config.py` (MEDIUM)

```python
"""Tests for src/pipeline/config.py — YAML config loader."""
import pytest
import yaml
from unittest.mock import mock_open, patch
from src.pipeline.config import ConfigLoader


class TestConfigLoader:
    def test_loads_and_applies_backcompat(self):
        """Legacy top-level keys migrated to namespaced keys."""
        pass

    def test_deprecation_warning_on_legacy_keys(self):
        """Warning emitted when legacy keys found."""
        pass

    def test_write_effective_before_load_raises(self):
        """RuntimeError if write_effective called before load()."""
        pass

    def test_override_dotted_path_sets_nested_value(self):
        """--set fast_evaluation.top_n=5 works."""
        pass

    def test_override_without_equals_raises(self):
        """ValueError if override doesn't contain '='."""
        pass

    def test_override_yaml_parsing_failure_falls_back_to_string(self):
        """If yaml.safe_load fails, raw string used as value."""
        pass

    def test_override_autovivifies_intermediate_keys(self):
        """--set new.nested.key=value creates intermediate dicts."""
        pass
```

---

## 5. Priority Action Plan

### Phase 1: Fix Test Infrastructure (unblocks 32 tests)

| Action | Impact |
|--------|--------|
| Fix `database.py:get_engine()` — skip pool args for SQLite | Unblocks 20 repository + 6 scheduler tests |
| Fix `models.py` — replace `MEDIUMTEXT` with `Text()` | Unblocks 1 database test |
| Fix `test_pipeline_data_update.py` — investigate assertion failures | Unblocks 2 tests |
| Fix `test_pipeline_backends.py` — investigate selector failure | Unblocks 1 test |
| Fix `test_full_pipeline_e2e.py` — `pipeline.base` attribute error | Unblocks 1 E2E test |

### Phase 2: Critical Module Coverage (biggest ROI)

| Module | New Tests | Target Coverage |
|--------|-----------|-----------------|
| `ingestion/pipeline.py` | 25 | 0% → 60% |
| `finrl_runner.py` | 20 | 0% → 55% |
| `repository.py` | 18 | 28% → 65% |
| `fetcher/alpha_vantage.py` | 12 | 19% → 60% |
| `scheduler.py` | 10 | 23% → 65% |

### Phase 3: Edge Case & Error Handling Coverage

| Category | New Tests |
|----------|-----------|
| Deadlock retry loops | 8 |
| Empty collection handling | 10 |
| NaN/Inf/None value handling | 8 |
| Exception propagation vs silent catch | 6 |
| Session lifecycle (try/finally) | 5 |

### Phase 4: Integration Tests

| Flow | Tests |
|------|-------|
| Data ingestion → DB round-trip | 3 |
| Select → Fast evaluate → Deep evaluate chain | 2 |
| ML train → predict → save results | 3 |
| Scheduler job chain (start → pipeline → end) | 2 |

### Phase 5: UI Smoke Tests

| Page | Tests |
|------|-------|
| All 11 Streamlit pages | 1 smoke test each |
| Dashboard E2E | Fix existing Playwright test |

---

## 6. Summary

```
Coverage Report — Current State
──────────────────────────────────────
Category                      Files   Covered   Target
──────────────────────────────────────
0% coverage modules           17       0%       60%
Low coverage (<80%)           7       19-54%   80%
Adequately covered (80%+)     8       80-100%  maintain
──────────────────────────────────────
Overall:                      34      30%       80% (target)
Tests passing:                140/172 (81% pass rate)
Tests blocked by infra:       32/172 (19%)
──────────────────────────────────────
```

**Bottom line:** 30% coverage, 32 tests blocked by 2 infrastructure bugs, ~67 error handling blocks untested, ~60 functions/classes at 0% coverage. Fix infrastructure first, then attack `ingestion/pipeline.py` (262 stmts, most complex), `finrl_runner.py` (277 stmts, core ML), and `repository.py` (remaining 12/15 methods).
