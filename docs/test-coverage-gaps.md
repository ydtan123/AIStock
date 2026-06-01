# AIStock Test Coverage Gap Analysis

**Date:** 2026-05-30 (fresh run)  
**Overall Coverage:** 30% (1,156 / 3,917 statements)  
**Tests:** 172 total (140 passed, 12 failed, 20 errors)  

---

## Current State

| Metric | Count |
|--------|-------|
| Modules at 0% coverage | 24 |
| Modules 1-49% | 5 |
| Modules 50-79% | 3 |
| Modules 80-99% | 10 |
| Modules 100% | 8 |
| **Total modules tracked** | **50** |

### 🔴 CRITICAL: Broken Tests (Block Coverage)

1. **`tests/test_pipeline_data_update.py`** — All 4 tests fail. `_run_pipeline` now takes 3 args `(source, step_cfg, full_cfg)` but monkeypatches use 2-arg lambda `lambda source, step_cfg: fake_result`. Caught by `except Exception` in `DataUpdateStep.run()` → returns status "failed" → tests assert "success".

2. **`tests/test_pipeline_backends.py`** — `test_finrl_stock_selector_uses_run_pipeline` references deleted `_run_finrl_pipeline` attribute on selectors module. Refactored into `finrl_runner.run_pipeline_and_save_report`.

3. **`tests/test_repository.py`** — All 20 tests ERROR with `TypeError`. Tests call methods that no longer exist (e.g. `get_stocks`, `get_active_stocks`, `get_active_symbols`). Renamed/removed during refactoring.

4. **`tests/test_scheduler.py`** — 6 tests FAIL. Assertions likely broken by DB schema changes.

5. **`tests/test_database.py`** — 1 test FAIL (`test_creates_all_tables_without_error`).

### Quick-Win Fixes Required

1. Fix `test_pipeline_data_update.py`: Change monkeypatches to 3-arg `lambda source, step_cfg, full_cfg: fake_result`
2. Fix `test_pipeline_backends.py:82`: Update ref from `_run_finrl_pipeline` to `finrl_runner.run_pipeline_and_save_report`
3. Fix `test_repository.py`: Update method names to match current `repository.py` API
4. Fix `_clean` bug in `ingestion/symbols.py`: `float("inf")` returns `True` instead of `None`

---

## Module-by-Module Gap Analysis

### A. 0% Coverage Modules (Complete Test Gaps)

#### 1. `src/ingestion/pipeline.py` (262 stmts, 0%)

**Functions:** `_prefetch_stock_dates`, `_fetch_and_store_prices`, `_upsert_fundamentals`, `_refresh_snapshots`, `_batch_update_checkpoints`, `_needs_full_backfill`, `_fetch_stock_news`, `_process_symbol`, `run_daily_pipeline`, `run_bootstrap`, `_auto_activate`

**Error handling gaps:**
- `_refresh_snapshots`, `_batch_update_checkpoints`, `_needs_full_backfill`, `_auto_activate` — **no exception handlers**
- `_fetch_stock_news` — silently swallows all exceptions, returns 0
- `_process_symbol` — swallows per-symbol errors into result dict
- Module-level code (lines 27-41) runs `load_config()`, writes `os.environ` — import safety untested

**Test skeletons:**

```python
# tests/test_ingestion_pipeline.py
import pytest
from unittest.mock import MagicMock, patch

class TestPrefetchStockDates:
    def test_empty_stock_ids_returns_empty_dict(self):
        from ingestion.pipeline import _prefetch_stock_dates
        result = _prefetch_stock_dates([])
        assert result == {"min_price_dates": {}, "max_price_dates": {}, "last_price_fetch": {}}

class TestFetchAndStorePrices:
    def test_deadlock_retry_exhausted(self):
        """After 5 deadlock retries, re-raises exception."""
        pass

    def test_fetcher_connection_error_propagates(self):
        """Network failure propagates without dirty session state."""
        pass

    def test_empty_fetch_returns_zero(self):
        """fetcher returns empty DataFrame → (0, max_date)."""
        pass

    def test_start_after_end_date(self):
        """start > end → (0, max_date) without API call."""
        pass

class TestUpsertFundamentals:
    def test_deadlock_retry_exhausted(self):
        """After 3 deadlock retries, re-raises."""
        pass

    def test_partial_overview_data_no_crash(self):
        """get_overview returns only mandatory keys — doesn't crash."""
        pass

    def test_fresh_indicator_skips_fetch(self):
        """Recent indicator_last_updated skips API call."""
        pass

class TestProcessSymbol:
    def test_partial_failure_continues(self):
        """Prices succeed, fundamentals fail → error in result dict, no crash."""
        pass

    def test_prefetch_none_guard_works(self):
        """prefetch=None guarded by conditional at line 378."""
        pass

class TestRunDailyPipeline:
    def test_partial_suite_failure(self):
        """80% stocks succeed, 20% fail → summary.errors count correct."""
        pass

    def test_thread_pool_exception_caught(self):
        """pool.submit() exception caught by outer except."""
        pass

class TestRunBootstrap:
    def test_all_symbols_fail_still_completes(self):
        """Every _upsert_fundamentals fails → errors > 0, no crash."""
        pass

    def test_empty_stock_list(self):
        """Zero stocks → completes without crash."""
        pass

class TestAutoActivate:
    def test_no_stocks_pass_criteria(self):
        """Empty filter results → no stocks updated."""
        pass

    def test_missing_criteria_keys_all_active(self):
        """criteria={} → all stocks activated (filters skip)."""
        pass

class TestRefreshSnapshots:
    def test_sql_failure_propagates(self):
        """conn.execute() failure → exception propagates (no handler)."""
        pass

class TestModuleLevelInit:
    def test_load_config_failure_handled(self):
        """config.yaml missing → graceful failure, not crash on import."""
        pass
```

---

#### 2. `src/fetcher/alpha_vantage.py` (124 stmts, 19% = 100 missed)

**Methods:** `_get`, `get_daily`, `get_overview`, `get_income_statement`, `get_balance_sheet`, `get_cash_flow`, `get_earnings`, `get_listing`

**Error handling gaps:**
- `_get` retry logic (rate limiting, HTTP 5xx, exponential backoff) — untested
- `get_earnings` `surprisePercentage` parsing (TypeError/ValueError) — untested
- No test for `requests.ConnectionError`, `JSONDecodeError`

```python
# tests/test_alpha_vantage.py
class TestGetRetryLogic:
    def test_rate_limit_note_backs_off(self):
        """Response with "Note" → backs off and retries."""
        pass

    def test_rate_limit_information_backs_off(self):
        """Response with "Information" → backs off and retries."""
        pass

    def test_http_5xx_retry_exponential_backoff(self):
        """502/503 → retries up to 3x with backoff (5s, 10s, 20s)."""
        pass

    def test_http_4xx_no_retry(self):
        """401/403/404 → re-raises immediately."""
        pass

    def test_all_retries_exhausted_raises_runtimeerror(self):
        """3 retries all fail → RuntimeError with last error message."""
        pass

    def test_timeout_retry(self):
        """requests.Timeout → retries with backoff."""
        pass

    def test_connection_error_propagates(self):
        """requests.ConnectionError → no handler, propagates to caller."""
        pass

class TestGetListing:
    def test_csv_parsing_column_rename(self):
        """Valid CSV → columns renamed, correct types."""
        pass

    def test_filter_inactive_symbols(self):
        """status != 'Active' excluded."""
        pass

    def test_filter_non_nyse_nasdaq(self):
        """Only NYSE/NASDAQ exchanges retained."""
        pass

    def test_filter_colon_symbols_excluded(self):
        """Symbols with ':' excluded."""
        pass

class TestGetDaily:
    def test_compact_vs_full_output_size(self):
        """start < 100 days → compact; older → full."""
        pass

    def test_empty_time_series_returns_empty_df(self):
        """API returns empty Time Series → empty DataFrame."""
        pass

    def test_date_range_filtering(self):
        """Rows outside [start, end] filtered out."""
        pass

class TestGetEarnings:
    def test_surprise_percentage_variants(self):
        """% sign, None, 'None', empty string, invalid string."""
        pass
```

---

#### 3. `src/repository.py` (158 stmts, 28% = 113 missed)

**Untested methods:** `find_stock`, `get_prices`, `get_indicator`, `get_snapshot`, `get_tech_indicators`, `screen_stocks`, `list_stocks`, `save_predict_only_results`

**Error handling gaps:**
- **Zero try/except blocks in entire file** — all DB errors propagate raw
- `bulk_set_active` raw SQL — no constraint violation handling
- `session.commit()` failures — untested

```python
# tests/test_repository.py (supplement existing)
class TestFindStock:
    def test_exact_symbol_found(self):
        """AAPL → Stock object returned."""
        pass

    def test_no_match_returns_none(self):
        """NONEXISTENT → None."""
        pass

class TestGetPrices:
    def test_empty_date_range(self):
        """start > end → empty DataFrame."""
        pass

    def test_returns_expected_columns(self):
        """Has date, open, high, low, close, volume."""
        pass

class TestGetTechIndicators:
    def test_null_indicators_json(self):
        """r.indicators is None → DataFrame with date column only."""
        pass

    def test_indicators_expanded_to_columns(self):
        """JSON keys become DataFrame columns."""
        pass

class TestScreenStocks:
    def test_all_criteria_none(self):
        """Default ScreenCriteria() → all rows."""
        pass

    def test_combined_filters_and_logic(self):
        """sector=X + exchange=Y + min_market_cap=Z → AND clause."""
        pass

    def test_zero_results(self):
        """min_market_cap=1e12 → empty DataFrame, no crash."""
        pass

class TestListStocks:
    def test_active_inactive_all(self):
        """Status filter: active, inactive, all."""
        pass

    def test_search_plus_filter(self):
        """search='apple' + sector='Technology' → combined AND."""
        pass

class TestSavePredictOnlyResults:
    def test_inserts_multiple_predictions(self):
        """List of prediction dicts → correct row count."""
        pass

    def test_missing_ml_score_defaults_zero(self):
        """No ml_score key → defaults to 0.0."""
        pass

    def test_empty_list_returns_zero(self):
        """[] → 0 rows inserted."""
        pass
```

---

#### 4. `src/finrl_runner.py` (277 stmts, 0%)

**Functions:** `run_pipeline_and_save_report`, `run_predict_only`, `_equal_weight_fallback`, `_run_simple_backtest`, `_compute_metrics`, `_build_selection_summary`

```python
# tests/test_finrl_runner.py
class TestRunPipelineAndSaveReport:
    def test_happy_path_writes_csv(self):
        """All steps succeed → report CSV written."""
        pass

    def test_ml_selection_failure_falls_back(self):
        """MLBucketSelector.fit_predict raises → equal_weight_fallback used."""
        pass

    def test_backtest_failure_does_not_abort(self):
        """_run_simple_backtest raises → pipeline continues, report written."""
        pass

class TestRunPredictOnly:
    def test_empty_model_directory_raises(self):
        """No .pkl files → FileNotFoundError with clear message."""
        pass

    def test_unmapped_sectors_handled(self):
        """Unknown gsector → rows logged and dropped."""
        pass

    def test_empty_symbols_from_db_raises(self):
        """get_latest_selected_stocks returns [] → ValueError."""
        pass

class TestComputeMetrics:
    def test_single_return_value(self):
        """len(returns)==1 → returns {}."""
        pass

    def test_zero_variance_returns(self):
        """All returns equal → std=0 handled safely."""
        pass
```

---

#### 5. `src/ingestion/symbols.py` (38 stmts, 0%)

**Bug found:** `_clean` returns `True` for `float("inf")` instead of `None`.

```python
# tests/test_symbols.py
class TestClean:
    def test_none_returns_none(self):
        from ingestion.symbols import _clean
        assert _clean(None) is None

    def test_nan_returns_none(self):
        import math
        assert _clean(float("nan")) is None

    def test_inf_returns_none(self):  # CURRENTLY FAILS — returns True
        import math
        assert _clean(float("inf")) is None

    def test_string_nan_returns_none(self):
        assert _clean("nan") is None

    def test_string_none_returns_none(self):
        assert _clean("None") is None

    def test_valid_number_unchanged(self):
        assert _clean(42.5) == 42.5

class TestRefreshSymbols:
    def test_empty_listing_returns_zero(self):
        pass

    def test_missing_symbol_column_raises_keyerror(self):
        pass
```

---

#### 6. `src/ingestion/indicators.py` (64 stmts, 0%)

```python
# tests/test_indicators.py
class TestComputeIndicators:
    def test_empty_price_table_returns_zero(self):
        """stock_id has no daily_prices → 0."""
        pass

    def test_db_connection_failure_propagates(self):
        """get_session() fails → exception, no UnboundLocalError in finally."""
        pass

    def test_all_nan_ohlcv_inputs(self):
        """All OHLCV values NULL → indicators computed, no div-by-zero."""
        pass

    def test_insufficient_warmup_days(self):
        """< 260 data rows → still produces usable indicators."""
        pass

    def test_deadlock_retry_exhausted(self):
        """5 consecutive MySQL deadlocks → re-raises on 5th attempt."""
        pass

    def test_since_date_filters_all_rows(self):
        """since_date after all data → returns 0 early."""
        pass
```

---

#### 7. `src/scheduler.py` (78 stmts, 23% = 60 missed)

```python
# tests/test_scheduler.py (supplement existing)
class TestMain:
    def test_invalid_run_time_format_raises(self):
        """scheduler.daily_run_time = 'abc' → ValueError."""
        pass

    def test_missing_scheduler_section_defaults(self):
        """config has no 'scheduler' key → defaults to 18:00."""
        pass

class TestRecordJobStart:
    def test_db_connection_failure_no_nameerror(self):
        """get_session() fails → no NameError on session.close() in finally."""
        pass
```

---

#### 8. `src/main.py` (93 stmts, 0%)

```python
# tests/test_main.py
class TestResolveSymbols:
    def test_empty_list(self):
        """[] → []."""
        pass

    def test_comma_separated(self):
        """'AAPL,MSFT,GOOG' → ['AAPL', 'MSFT', 'GOOG']."""
        pass

    def test_mixed_space_comma(self):
        """'AAPL MSFT, GOOG' → ['AAPL', 'MSFT', 'GOOG']."""
        pass

    def test_case_normalization(self):
        """'aapl' → ['AAPL']."""
        pass

    def test_deduplication(self):
        """'AAPL,AAPL,MSFT' → ['AAPL', 'MSFT']."""
        pass

class TestEnsureStock:
    def test_not_found_not_forced_exits(self):
        """sys.exit(1) called."""
        pass

    def test_not_found_forced_creates(self):
        """New Stock with is_active=True created."""
        pass

    def test_inactive_not_forced_exits(self):
        """is_active=False + not forced → sys.exit(1)."""
        pass

    def test_inactive_forced_activates(self):
        """is_active=False + forced → activated."""
        pass

    def test_commit_failure_propagates_session_closes(self):
        """session.commit() IntegrityError → propagates, finally closes."""
        pass
```

---

#### 9. `src/ml_bucket_selector.py` (90 stmts, 0%)

```python
# tests/test_ml_bucket_selector.py
class TestFitPredict:
    def test_happy_path(self):
        """Valid fund_df → weights DataFrame with date/gvkey/weight."""
        pass

    def test_empty_fundamentals_raises(self):
        """fund_df empty → ValueError."""
        pass

    def test_single_bucket_failure_continues(self):
        """One sector raises → logged, other buckets still processed."""
        pass

    def test_all_buckets_fail_raises(self):
        """Every bucket fails → RuntimeError."""
        pass

    def test_missing_feature_columns_imputed(self):
        """Missing FEATURE_COLS → NaNs imputed with median."""
        pass

    def test_division_by_zero_protection(self):
        """ocf=0 in fcf_to_ocf → NaN, then imputed."""
        pass
```

---

#### 10-12. Quick Skeletons

```python
# tests/test_logging_config.py
class TestSetupLogging:
    def test_sets_level(self):
        """setup_logging(logging.DEBUG) → root logger level correct."""
        pass
    def test_idempotent(self):
        """Second call doesn't raise."""
        pass

# tests/test_full_pipeline_cli.py
class TestParseArgs:
    def test_defaults(self): pass
    def test_resume_from_valid_step(self): pass

class TestMain:
    def test_happy_path_returns_zero(self): pass
    def test_pipeline_error_returns_two(self): pass
    def test_config_not_found_error(self): pass

# tests/test_config.py
class TestLoadConfig:
    def test_loads_and_caches(self): pass
    def test_missing_config_yaml_exits(self): pass
    def test_malformed_yaml_propagates(self): pass
```

---

### B. Partially Covered Modules (Selective Gaps)

#### `src/pipeline/backends/deep_evaluators.py` (80% — 18 missed)

```python
# tests/test_backends_deep.py (supplement)
class TestExtractDecision:
    def test_sell_and_hold_parsed(self):
        """**SELL** → SELL, **HOLD** → HOLD."""
        pass

    def test_no_recognized_token_returns_empty(self):
        """No BUY/SELL/HOLD marker → empty fields."""
        pass

    def test_fallback_decision_path(self):
        """fallback_decision=HOLD used when no token found."""
        pass

class TestTradingAgentsEvaluate:
    def test_empty_tickers_early_return(self):
        """tickers=[] → empty dict."""
        pass

    def test_graph_exception_per_ticker_continues(self):
        """Ticker #1 raises → ticker #2 still evaluated."""
        pass

    def test_news_cache_install_exception_caught(self):
        """install_news_cache raises → caught, logged, continued."""
        pass

class TestInjectApiKeys:
    def test_respects_existing_env_vars(self):
        """Existing TAVILY_API_KEY not overwritten."""
        pass

    def test_sets_keys_when_missing(self):
        """No env vars → keys injected from config."""
        pass
```

#### `src/pipeline/backends/fast_evaluators.py` (81% — 17 missed)

```python
# tests/test_backends_fast.py (supplement)
class TestLastTradingDate:
    def test_sunday_returns_friday(self):
        """Sunday → previous Friday."""
        pass

    def test_saturday_returns_friday(self):
        """Saturday → previous Friday."""
        pass

    def test_weekday_unchanged(self):
        """Wednesday → same date returned."""
        pass

class TestResolveDates:
    def test_start_none_90_day_lookback(self):
        """start=None → computed as end minus 90 days."""
        pass

class TestComputeConsensus:
    def test_all_zero_confidence_returns_zero(self):
        """total_conf=0 → consensus_score=0.0."""
        pass

    def test_mixed_confidence_weights(self):
        """bull=0.8, bear=0.2 → weighted avg correct."""
        pass

class TestEnsureAiHedgeFundPath:
    def test_already_in_sys_path_not_duplicated(self):
        """Path present → second insert skipped."""
        pass
```

#### `src/pipeline/backends/selectors.py` (70% — 18 missed)

```python
# tests/test_backends_selectors.py (supplement)
class TestRegistry:
    def test_names_returns_sorted(self):
        """_Registry.names() → alphabetically sorted list."""
        pass

class TestFinrlStockSelector:
    def test_empty_db_rows_returns_empty(self):
        """get_latest_selected_stocks returns [] → [ScoredTicker] empty."""
        pass

    def test_sector_falls_back_to_bucket(self):
        """sector=None, bucket='Technology' → sector = 'Technology'."""
        pass

    def test_ml_score_zero_not_overwritten(self):
        """ml_score=0 → ScoredTicker(score=0.0)."""
        pass
```

#### `src/pipeline/base.py` (89% — 5 missed)

```python
# tests/test_pipeline_base.py (supplement)
class TestOpenSession:
    def test_plain_factory_without_context_manager(self):
        """Factory returns object without __enter__ → fallback path used."""
        pass

class TestRegisteredBackend:
    def test_subclass_without_name_raises(self):
        """Concrete subclass missing name attribute → TypeError."""
        pass

class TestPipelineStep:
    def test_empty_name_raises(self):
        """PipelineStep(name='') → TypeError."""
        pass
```

#### Other partial gaps (orchestrator 95%, config 95%, stock_selection 94%, fast_eval 96%, deep_eval 95%)

```python
# tests/test_pipeline_orchestrator.py (supplement)
class TestSelectSteps:
    def test_resume_from_unknown_raises_valueerror(self):
        """resume_from='nonexistent' → ValueError."""
        pass

class TestLoadPriorResults:
    def test_corrupt_json_skipped_silently(self):
        """JSON syntax error → silently skipped."""
        pass

# tests/test_pipeline_config.py (supplement)
class TestConfigLoader:
    def test_write_effective_without_load_raises(self):
        """call write_effective() before load() → RuntimeError."""
        pass

    def test_override_yaml_parse_fallback(self):
        """yaml.safe_load fails → uses raw string value."""
        pass

# tests/test_pipeline_stock_selection.py (supplement)
class TestStockSelection:
    def test_selector_init_exception_wraps_to_stepresult(self):
        """selector_cls(cfg=...) raises → StepResult(status='failed')."""
        pass

# tests/test_pipeline_fast_evaluation.py (supplement)
class TestFastEvaluation:
    def test_evaluator_exception_wraps_to_stepresult(self):
        """evaluator.evaluate() raises → StepResult(status='failed')."""
        pass

# tests/test_pipeline_deep_evaluation.py (supplement)
class TestDeepEvaluation:
    def test_evaluator_exception_wraps_to_stepresult(self):
        """evaluator.evaluate() raises → StepResult(status='failed')."""
        pass

    def test_date_parsing_iso_format(self):
        """ISO datetime in evaluation_date parsed correctly."""
        pass
```

---

### C. Error Handling Gap Summary

| Pattern | Module(s) | Count | Risk |
|---------|-----------|-------|------|
| No try/except at all | `repository.py`, `symbols.py`, `config.py`, `logging_config.py` | 4 files | **HIGH** |
| Wildcard `except Exception` swallows | `pipeline.py::_fetch_stock_news`, `pipeline.py::_process_symbol` | 8 blocks | **MEDIUM** |
| Wildcard `except Exception` re-raises | `pipeline.py::_fetch_and_store_prices`, `indicators.py::compute_indicators` | 5 blocks | **LOW** |
| `finally` with potential `UnboundLocalError` | `indicators.py`, `scheduler.py` | 2 blocks | **HIGH** |
| No deadlock retry test coverage | `pipeline.py`, `indicators.py` | 3 functions | **MEDIUM** |

### D. Integration Test Gaps

| Gap | Description | Priority |
|-----|-------------|----------|
| DB → ingestion pipeline | Full round-trip: fetch prices → store → compute indicators | HIGH |
| finrl_runner → DB | `run_pipeline_and_save_report` writes to `selected_stocks` table | HIGH |
| Scheduler → pipeline | Cron job fires → pipeline runs → DB records | MEDIUM |
| API rate limit recovery | Alpha Vantage rate limit → backoff → retry success | MEDIUM |
| Partial pipeline failure | Stock #1 succeeds, Stock #2 fails → run continues | MEDIUM |
| Config bridge | data_update step bridges `alpha_vantage.api_key` to ingestion | MEDIUM |

### E. Actionable Checklist

- [ ] Fix `test_pipeline_data_update.py` (3-arg lambda) — unblocks 4 tests, recovers ~30 pipeline stmts
- [ ] Fix `test_pipeline_backends.py:82` (removed `_run_finrl_pipeline`) — unblocks backend tests
- [ ] Fix `test_repository.py` (renamed methods) — unblocks 20 tests
- [ ] Fix `_clean` bug in `symbols.py` (`inf` returns `True` not `None`)
- [ ] Add `try/except` to `_refresh_snapshots`, `_batch_update_checkpoints`
- [ ] Write `test_alpha_vantage.py` (highest-value 0% module with complex retry logic)
- [ ] Write `test_ingestion_pipeline.py` (largest 0% module, core business logic)
- [ ] Write `test_repository.py` supplements (7 untested methods)
- [ ] Write `test_finrl_runner.py` (critical ML pipeline path)
- [ ] Write `test_main.py` (CLI entry point)
- [ ] Write `test_symbols.py` (small module, quick win)
- [ ] Write `test_ml_bucket_selector.py` (ML selection logic)
- [ ] Write `test_indicators.py` (technical indicator computation)
- [ ] Fill in partial-coverage gaps for backends (2-3 tests each)
- [ ] Add integration test for full pipeline round-trip
