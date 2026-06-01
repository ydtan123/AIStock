# Test Coverage Gap Analysis — AIStock

**Date:** 2026-05-30
**Baseline:** 28.7% (4,081 stmts, 2,908 missing)
**Tests:** 172 total (140 passed, 12 failed, 20 errors)
**Target:** 80%+

---

## 1. Root Cause: Existing Failures Must Be Fixed First

### 1.1 `database.py:get_engine()` SQLite Incompatibility (CRITICAL)

**Symptom:** 20 errors in `test_repository.py`, 6 failures in `test_scheduler.py`

```
TypeError: Invalid argument(s) 'max_overflow' sent to create_engine(),
using configuration SQLiteDialect_pysqlite/SingletonThreadPool/Engine.
```

**Root cause:** `src/database.py:24` passes `pool_size=15, max_overflow=10` — MySQL-specific params unsupported by SQLite's `SingletonThreadPool`.

**Fix:**
```python
# src/database.py — get_engine()
if "sqlite" in url:
    _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600)
else:
    _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600,
                            pool_size=15, max_overflow=10)
```

### 1.2 `test_finrl_stock_selector_uses_run_pipeline` Stale Mock

**Symptom:** `AttributeError: module 'pipeline.backends.selectors' has no attribute '_run_finrl_pipeline'`

**Root cause:** Refactored to `finrl_runner._run_finrl_pipeline`. Test monkeypatches old location.

**Fix:** Update monkeypatch target to `finrl_runner._run_finrl_pipeline`.

### 1.3 `test_pipeline_data_update` Config Bypass (2 failures)

**Symptom:** `assert 'failed' == 'success'`

**Root cause:** `DataUpdateStep.run()` calls `load_config()` internally, bypassing test's `ctx.cfg`.

**Fix:** Pass `ctx.cfg` to `_run_pipeline()` instead of reloading config.

---

## 2. Per-File Gap Analysis & Test Skeletons

### 2.1 `src/config.py` (35% → target 95%)

Missing: `load_config()` cache-hit, stale-mtime, missing-file, force-reload paths.

```python
# tests/test_config.py (NEW)
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

class TestLoadConfig:
    def test_loads_yaml_and_caches(self):
        """Second call returns cached config without re-reading file."""

    def test_force_reload_ignores_cache(self):
        """force=True re-reads YAML even when mtime unchanged."""

    def test_stale_mtime_triggers_reload(self):
        """When config.yaml mtime changes, reload automatically."""

    def test_missing_config_exits(self):
        """Missing config.yaml → sys.exit(1) with stderr message."""

    def test_invalid_yaml_raises_clear_error(self):
        """Malformed YAML → parse error with filename."""

    def test_empty_config_returns_defaults(self):
        """Empty config.yaml → sensible defaults."""
```

### 2.2 `src/logging_config.py` (0% → target 100%)

Missing: All of `setup_logging()`, `get_logger()`.

```python
# tests/test_logging_config.py (NEW)
import logging
from src.logging_config import setup_logging, get_logger

class TestSetupLogging:
    def test_returns_configured_logger(self):
        """Returns logger with given name at specified level."""

    def test_adds_file_handler_when_log_file_provided(self, tmp_path):
        """FileHandler added; log file created on write."""

    def test_skips_file_handler_when_log_file_none(self):
        """No FileHandler when log_file is None."""

    def test_default_level_is_info(self):
        """Default level is INFO when not specified."""

    def test_formatter_includes_timestamp_and_level(self):
        """Log format includes timestamp, level, and message."""

class TestGetLogger:
    def test_returns_existing_logger(self):
        """Same name → same logger instance."""

    def test_adds_stream_handler_if_none(self):
        """Adds StreamHandler if logger has no handlers."""
```

### 2.3 `src/ingestion/symbols.py` (0% → target 80%)

Missing: `fetch_sp500_wikipedia()`, `fetch_symbols_from_sources()`.

```python
# tests/test_ingestion_symbols.py (NEW)
from unittest.mock import patch, MagicMock
import pytest
from src.ingestion.symbols import fetch_sp500_wikipedia, fetch_symbols_from_sources

class TestFetchSp500Wikipedia:
    def test_returns_ticker_list(self):
        """Successful fetch returns list of S&P 500 tickers."""

    def test_handles_http_error_gracefully(self):
        """HTTPError → returns empty list, logs warning."""

    def test_handles_malformed_html(self):
        """Invalid HTML → returns empty list, doesn't crash."""

    def test_deduplicates_tickers(self):
        """Duplicate tickers in HTML table are deduplicated."""

    def test_filters_invalid_entries(self):
        """Non-ticker rows filtered out."""

class TestFetchSymbolsFromSources:
    def test_primary_source_success_skips_fallback(self):
        """Only calls fallback when primary returns empty."""

    def test_fallback_called_on_empty_primary(self):
        """Calls secondary source(s) when primary yields nothing."""

    def test_deduplicates_across_sources(self):
        """Same ticker from multiple sources appears once."""

    def test_all_sources_empty_returns_empty(self):
        """All sources empty → returns []. No crash."""

    def test_sorts_result_alphabetically(self):
        """Output ticker list is alphabetically sorted."""
```

### 2.4 `src/ingestion/indicators.py` (0% → target 85%)

Missing: `compute_indicators()` and all indicator helpers.

```python
# tests/test_ingestion_indicators.py (NEW)
import pandas as pd
import numpy as np
import pytest
from datetime import date

class TestComputeIndicators:
    @pytest.fixture
    def ohlcv_df(self):
        """60-day OHLCV DataFrame with realistic prices."""
        dates = pd.date_range('2025-01-01', periods=60, freq='B')
        return pd.DataFrame({
            'open': np.linspace(100, 110, 60) + np.random.randn(60),
            'high': np.linspace(102, 112, 60) + np.random.randn(60),
            'low': np.linspace(98, 108, 60) + np.random.randn(60),
            'close': np.linspace(101, 111, 60) + np.random.randn(60),
            'volume': np.random.randint(10**6, 10**7, 60),
        }, index=dates)

    def test_returns_dataframe_with_expected_columns(self, ohlcv_df):

    def test_sma_values_within_expected_range(self, ohlcv_df):

    def test_rsi_bounded_0_to_100(self, ohlcv_df):

    def test_macd_components_present(self, ohlcv_df):

    def test_bollinger_bands_upper_gt_middle_gt_lower(self, ohlcv_df):

    def test_atr_all_positive(self, ohlcv_df):

    def test_empty_dataframe_returns_empty(self):

    def test_single_row_handled_gracefully(self):

    def test_all_nan_column_does_not_crash(self):

    def test_missing_close_column_raises_clear_error(self):

    def test_since_date_filters_early_rows(self, ohlcv_df):
```

### 2.5 `src/ingestion/pipeline.py` (0% → target 60%)

Key functions: `run_daily_pipeline`, `_process_symbol`, `_fetch_and_store_prices`,
`_upsert_fundamentals`, `_refresh_snapshots`, `_prefetch_stock_dates`,
`_needs_full_backfill`, `_batch_update_checkpoints`, `_fetch_stock_news`, `_auto_activate`.

```python
# tests/test_ingestion_pipeline.py (NEW)
from unittest.mock import MagicMock, patch, call
import pytest
from datetime import date

class TestRunDailyPipeline:
    def test_processes_all_active_stocks(self):
        """Calls _process_symbol for each active stock."""

    def test_returns_summary_dict(self):
        """Return dict has prices_updated, fundamentals_updated, errors."""

    def test_continues_on_per_symbol_error(self):
        """One symbol failing does not stop the pipeline."""

    def test_respects_force_flag(self):
        """force=True passes through to _process_symbol."""

class TestProcessSymbol:
    def test_fetches_prices_and_fundamentals(self):

    def test_skips_fundamentals_on_api_error(self):

    def test_updates_checkpoint_after_success(self):

class TestFetchAndStorePrices:
    def test_stores_prices_in_db(self):

    def test_handles_empty_api_response(self):

    def test_skips_duplicate_dates(self):

class TestUpsertFundamentals:
    def test_upserts_quarterly_data(self):

    def test_handles_stock_with_no_fundamentals(self):

    def test_force_overwrites_existing(self):

class TestRefreshSnapshots:
    def test_updates_all_snapshot_fields(self):

    def test_handles_empty_indicators_table(self):

class TestNeedsFullBackfill:
    def test_no_indicator_date_returns_true(self):
        """Null indicator date → needs full backfill."""

    def test_stale_indicator_returns_true(self):
        """Indicator older than threshold → needs backfill."""

    def test_recent_indicator_returns_false(self):
        """Recent indicator → no backfill needed."""

class TestPrefetchStockDates:
    def test_returns_min_max_dates_per_stock(self):

    def test_stock_with_no_prices_returns_none(self):

class TestBatchUpdateCheckpoints:
    def test_updates_multiple_stock_checkpoints(self):

    def test_empty_list_is_noop(self):
```

### 2.6 `src/news_cache.py` (54% → target 90%)

Missing: `_key()` arg parsing, `get_cached()` miss, `set_cached()` expiry.

```python
# tests/test_news_cache.py (NEW)
from unittest.mock import MagicMock, patch
import pytest
from src import news_cache

class TestCacheKey:
    def test_get_news_extracts_ticker_start_end(self):
        """_key('get_news', ('AAPL','2024-01-01','2024-01-31'), {}) → correct tuple."""

    def test_kwargs_fallback(self):
        """_key extracts from kwargs when args insufficient."""

    def test_unknown_tool_returns_empty_strings(self):
        """Unknown tool_name → empty-string tuple fields."""

class TestGetCached:
    def test_returns_none_when_cache_empty(self, clean_db):

    def test_returns_none_when_expired(self, clean_db):

    def test_returns_value_when_fresh(self, clean_db):

class TestSetCached:
    def test_stores_and_retrieves_roundtrip(self, clean_db):

    def test_upserts_existing_entry(self, clean_db):

class TestInstall:
    def test_decorator_caches_repeated_identical_calls(self, clean_db):

    def test_different_params_get_different_cache_entries(self, clean_db):
```

### 2.7 `src/fetcher/alpha_vantage.py` (19% → target 70%)

Missing: `__init__` config, `fetch_daily_adjusted` error paths, `fetch_quote`.

```python
# tests/test_fetcher_alpha_vantage.py (NEW)
from unittest.mock import patch, MagicMock
import pytest
import requests

class TestAlphaVantageInit:
    def test_init_requires_api_key(self):
        """Missing API key in config and env → ValueError."""

    def test_init_loads_key_from_config_dict(self):
        """API key read from config dict."""

    def test_init_loads_key_from_env_var(self):
        """API key read from ALPHA_VANTAGE_API_KEY env var."""

class TestFetchDailyAdjusted:
    def test_parses_valid_response_to_dataframe(self, fetcher):

    def test_rate_limit_triggers_retry(self, fetcher):

    def test_api_error_message_raises(self, fetcher):

    def test_empty_time_series_returns_empty_df(self, fetcher):

    def test_network_timeout_handled(self, fetcher):

    def test_invalid_json_response_handled(self, fetcher):

class TestFetchQuote:
    def test_parses_global_quote(self, fetcher):

    def test_unknown_symbol_returns_none(self, fetcher):
```

### 2.8 `src/fetcher/yahoo.py` (38% → target 80%)

```python
# tests/test_fetcher_yahoo.py (NEW)
class TestYahooFetcher:
    def test_fetch_daily_returns_dataframe_with_ohlcv(self):

    def test_unknown_symbol_returns_empty_dataframe(self):

    def test_respects_start_and_end_date(self):

    def test_network_error_returns_empty_not_crash(self):

    def test_auto_adjusts_for_splits_and_dividends(self):
```

### 2.9 `src/repository.py` (29% → target 80%)

All 20 tests currently error out (§1.1). After fix, add:

```python
# tests/test_repository.py (APPEND after fixing §1.1)
class TestFindStocksBatch:
    def test_returns_dict_keyed_by_symbol(self):

    def test_partial_match_on_some_symbols(self):

    def test_case_insensitive_lookup(self):

class TestGetPrices:
    def test_returns_date_indexed_dataframe(self):

    def test_empty_range_returns_empty_dataframe(self):

    def test_end_before_start_returns_empty(self):

class TestScreenStocks:
    def test_filters_by_sector(self):

    def test_filters_by_market_cap_range(self):

    def test_filters_by_pe_ratio(self):

    def test_combined_filters(self):

    def test_no_matches_returns_empty(self):

class TestSavePredictOnlyResults:
    def test_inserts_predictions_with_timestamp(self):

    def test_overwrites_previous_predictions_for_same_label(self):

class TestGetLatestSelectedStocks:
    def test_returns_most_recent_run_only(self):

    def test_empty_table_returns_empty_list(self):
```

### 2.10 `src/scheduler.py` (23% → target 70%)

After fixing §1.1, add:

```python
# tests/test_scheduler.py (APPEND)
class TestSchedulerLifecycle:
    def test_all_jobs_registered_on_init(self):

    def test_daily_pipeline_job_fires_at_configured_time(self):

    def test_pause_and_resume_work(self):

    def test_concurrent_execution_is_prevented(self):

    def test_shutdown_waits_for_running_jobs(self):

    def test_misfire_grace_time_applied(self):
```

### 2.11 `src/pipeline/data_update.py` (44% → target 80%)

```python
# tests/test_pipeline_data_update.py (APPEND after fixing §1.3)
class TestDataUpdateEdgeCases:
    def test_run_passes_force_flag_to_pipeline(self):

    def test_run_captures_exception_in_metadata(self):

    def test_run_returns_failed_status_on_error(self):

    def test_different_data_source_changes_fetcher(self):

    def test_empty_symbol_list_skips_gracefully(self):
```

### 2.12 `src/ml_bucket_selector.py` (0% → target 80%)

```python
# tests/test_ml_bucket_selector.py (NEW)
import pandas as pd
import numpy as np
import pytest
from src.ml_bucket_selector import MLBucketSelector

class TestMLBucketSelector:
    @pytest.fixture
    def fund_df(self):
        return pd.DataFrame({
            'ticker': ['A', 'B', 'C', 'D', 'E'] * 4,
            'sector': ['Tech'] * 20,
            'pe_ratio': np.random.uniform(5, 50, 20),
            'revenue_growth': np.random.uniform(-0.2, 0.5, 20),
        })

    def test_init_default_parameters(self):

    def test_fit_predict_returns_weighted_dataframe(self, fund_df):

    def test_handles_empty_dataframe(self):

    def test_handles_missing_feature_columns(self):

    def test_save_models_dir_creates_files(self, fund_df, tmp_path):

    def test_nan_values_handled(self):

    def test_single_stock_input_does_not_crash(self, fund_df):
```

### 2.13 `src/finrl_runner.py` (0% → target 60%)

```python
# tests/test_finrl_runner.py (NEW)
from unittest.mock import patch, MagicMock
import pytest
from src import finrl_runner

class TestRunFinrlPipeline:
    def test_returns_pipeline_result_dict(self):

    def test_writes_selection_report_csv(self, tmp_path):

    def test_handles_empty_sp500_list(self):

    def test_backtest_includes_benchmark_comparison(self):

    def test_interrupted_pipeline_cleanup(self):

    def test_writes_backtest_json(self, tmp_path):
```

### 2.14 `src/full_pipeline.py` / `src/main.py` / `src/ta_run.py` (0%)

CLI glue; limit to argument parsing + error path tests.

```python
# tests/test_cli_entry_points.py (NEW)
class TestFullPipelineCli:
    def test_parses_resume_from_and_run_id(self):
    def test_parses_set_overrides(self):
    def test_unknown_step_name_exits_with_error(self):

class TestMainCli:
    def test_requires_symbol_argument(self):
    def test_accepts_incremental_flag(self):
    def test_config_missing_exits(self):
    def test_api_error_prints_message(self):

class TestTaRun:
    def test_computes_indicators_for_active_stocks(self):
    def test_handles_empty_db(self):
    def test_force_flag_recomputes_all(self):
```

---

## 3. Error Handling Gaps

### 3.1 API Error Handling (untested)

| Pattern | Where | Test needed |
|---------|-------|------------|
| Rate limit → retry + backoff | `alpha_vantage.py` | Max retries exhausted → clear error |
| Network timeout | `alpha_vantage.py`, `yahoo.py` | Timeout → retry or clean error |
| Malformed JSON response | `alpha_vantage.py` | HTML error page, empty body |
| API key expired | `alpha_vantage.py` | Clear message, not cryptic traceback |
| DNS resolution failure | both fetchers | ConnectionError → retry or error |

### 3.2 DB Error Handling (untested)

| Pattern | Where | Test needed |
|---------|-------|------------|
| Connection lost mid-transaction | `repository.py` | Reconnect + retry |
| Duplicate key on insert | all save methods | Upsert vs error |
| FK constraint violation | `repository.py` | Clear error, not silent fail |
| Table missing on startup | `news_cache.py` | Auto-create table |

### 3.3 Pipeline Error Handling (partially covered)

| Pattern | Where | Status |
|---------|-------|--------|
| Step failure stops orchestrator | `orchestrator.py` | ✅ Tested |
| Per-symbol failure continues | `data_update.py` | ❌ Untested |
| Resume from step N | `orchestrator.py` | ✅ Tested |
| Empty input list to step | `stock_selection.py` | ❌ Untested |
| Config validation failure | `pipeline/config.py` | ❌ Untested |

```python
# tests/test_error_handling.py (NEW)
class TestConfigValidationErrors:
    def test_missing_required_keys(self):
    def test_invalid_source_name(self):
    def test_missing_api_key_for_source(self):
    def test_type_mismatch_in_numeric_field(self):
    def test_empty_config_file(self):

class TestDatabaseErrorRecovery:
    def test_connection_lost_during_query_retries(self):
    def test_duplicate_key_insert_upserts(self):
    def test_transaction_rollback_on_error(self):

class TestApiErrorRecovery:
    def test_rate_limit_retry_exhaustion(self):
    def test_network_timeout_retry(self):
    def test_dns_failure_graceful_error(self):
```

---

## 4. Integration Test Gaps

### 4.1 Pipeline E2E

```python
# tests/test_integration_pipeline.py (NEW)
@pytest.mark.integration
class TestPipelineIntegration:
    def test_full_4_step_pipeline_e2e(self, clean_db):
        """data_update → stock_selection → fast_eval → deep_eval."""

    def test_resume_from_step_3(self, clean_db):
        """Skip data_update + selection, start at fast_evaluation."""

    def test_stops_on_first_step_failure(self, clean_db):

    def test_concurrent_runs_get_different_ids(self, clean_db):

    def test_all_step_reports_written_to_disk(self, clean_db, tmp_path):
```

### 4.2 API Contract Tests

```python
# tests/test_api_contracts.py (NEW)
@pytest.mark.slow
class TestAlphaVantageContract:
    def test_daily_adjusted_schema_matches_expected(self):
        """Real API call; verify JSON structure matches parser expectations."""

class TestYahooContract:
    def test_history_returns_expected_columns(self):
        """Real API call; verify DataFrame columns match expectations."""
```

### 4.3 Streamlit Smoke Tests

```python
# tests/test_smoke_streamlit.py (NEW)
@pytest.mark.smoke
class TestStreamlitSmoke:
    def test_app_module_imports_without_error(self):

    def test_each_page_renders_without_exception(self):

    def test_page_error_shows_friendly_message(self):
```

---

## 5. Edge Cases Needing Tests

| Category | Case | Where |
|----------|------|-------|
| **Boundary** | Zero-volume trading day | indicators |
| **Boundary** | Negative price (data error) | ingestion |
| **Boundary** | Date range: end before start | get_prices |
| **Boundary** | Symbol > 20 chars | find_stock |
| **Null** | All-NaN fundamentals row | ML, indicators |
| **Null** | Stock with 0 rows of price history | ingestion, ML |
| **Concurrency** | Two pipeline runs simultaneously | orchestrator |
| **Concurrency** | Session closed during long query | repository |
| **Volume** | 10,000+ stock insert batch | bulk operations |
| **Encoding** | Non-ASCII ticker symbols | find_stock, DB |

---

## 6. Implementation Roadmap

### Phase 1: Fix Infrastructure (prerequisite — unblocks 26 tests)

| # | Fix | Impact |
|---|-----|--------|
| 1 | `get_engine()` SQLite `max_overflow` bug | Unblocks 20 test_repository + 6 test_scheduler |
| 2 | Stale monkeypatch in `test_finrl_stock_selector` | Unblocks 1 test_pipeline_backends |
| 3 | Config bypass in `test_pipeline_data_update` | Fixes 2 test_pipeline_data_update |

### Phase 2: Core Business Logic (highest ROI)

| File | Current | Target | New Tests |
|------|---------|--------|-----------|
| `config.py` | 35% | 95% | 6 |
| `logging_config.py` | 0% | 100% | 7 |
| `news_cache.py` | 54% | 90% | 8 |
| `repository.py` | 29% | 80% | 15 |
| `ingestion/symbols.py` | 0% | 85% | 10 |
| `ingestion/indicators.py` | 0% | 85% | 11 |
| `ml_bucket_selector.py` | 0% | 80% | 7 |

### Phase 3: Data Fetching & Pipeline

| File | Current | Target | New Tests |
|------|---------|--------|-----------|
| `fetcher/alpha_vantage.py` | 19% | 70% | 11 |
| `fetcher/yahoo.py` | 38% | 80% | 5 |
| `pipeline/data_update.py` | 44% | 80% | 5 |
| `pipeline/backends/selectors.py` | 70% | 85% | 4 |
| `ingestion/pipeline.py` | 0% | 60% | 18 |
| `scheduler.py` | 23% | 70% | 6 |

### Phase 4: Error Handling, Integration & Edge Cases

| Area | New Tests |
|------|-----------|
| Error handling (API, DB, config, pipeline) | 12 |
| Integration (pipeline E2E, DB, API contracts) | 8 |
| Edge cases (boundary, concurrency, null data) | 10 |
| Streamlit smoke tests | 4 |
| CLI entry points | 10 |

### Projected Outcome

- **Total new test functions:** ~157
- **Estimated coverage after Phase 4:** 75-82%
- **Remaining untested (acceptable):** Streamlit UI rendering (hard to unit test), `ta_run.py` (integration-heavy)

---

## 7. New Test File Checklist

- [ ] `tests/test_config.py` — 6 tests
- [ ] `tests/test_logging_config.py` — 7 tests
- [ ] `tests/test_news_cache.py` — 8 tests
- [ ] `tests/test_ingestion_symbols.py` — 10 tests
- [ ] `tests/test_ingestion_indicators.py` — 11 tests
- [ ] `tests/test_ingestion_pipeline.py` — 18 tests
- [ ] `tests/test_ml_bucket_selector.py` — 7 tests
- [ ] `tests/test_fetcher_alpha_vantage.py` — 11 tests
- [ ] `tests/test_fetcher_yahoo.py` — 5 tests
- [ ] `tests/test_finrl_runner.py` — 6 tests
- [ ] `tests/test_cli_entry_points.py` — 10 tests
- [ ] `tests/test_error_handling.py` — 12 tests
- [ ] `tests/test_integration_pipeline.py` — 5 tests
- [ ] `tests/test_api_contracts.py` — 2 tests
- [ ] `tests/test_smoke_streamlit.py` — 4 tests
- [ ] Fix `tests/test_repository.py` — unblock 20 tests
- [ ] Fix `tests/test_scheduler.py` — unblock 6 tests
- [ ] Fix `tests/test_pipeline_data_update.py` — 2 tests
- [ ] Fix `tests/test_pipeline_backends.py` — 1 test

**Total:** 15 new test files, 19 files modified, ~157 new test functions + 29 existing tests unblocked.
