# Test Coverage Gap Analysis v5

**Date:** 2026-05-30 22:21
**Overall Coverage:** 29% (4188 statements, 1210 covered, 2978 missing)
**Test Results:** 131 passed, 12 failed, 29 errors (external tests excluded)

---

## 1. Infrastructure Bugs (Blocking 28 Tests)

### Bug 1: `database.py:24` — MySQL pool args crash SQLite

`pool_size=15, max_overflow=10` rejected by SQLite's `SingletonThreadPool`.

**Affected:** 20 repository tests + 6 scheduler tests = 26 at ERROR.

**Fix:**

```python
# database.py — add URL detection
def get_engine():
    global _engine
    if _engine is None:
        url = _url or load_config()["database"]["url"]
        if "sqlite" in url:
            _engine = create_engine(url, pool_pre_ping=True)
        else:
            _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600,
                                    pool_size=15, max_overflow=10)
    return _engine
```

### Bug 2: `test_pipeline_data_update.py` — lambda arity mismatch

`_run_pipeline(source, step_cfg, full_cfg)` takes 3 args; tests monkeypatch with 2-arg lambda.

**Fix:** Update lambdas to `lambda source, step_cfg, full_cfg: fake_result`.

### Bug 3: `external/TradingAgents/test_tools.py:228` — `sys.exit(1)`

Module-level `sys.exit(1)` crashes collection. Add `norecursedirs = ["external"]` to pytest config.

---

## 2. Coverage by Module

### 0% Coverage (24 files, ~2400 stmts)

| Module | Stmts | Risk |
|--------|-------|------|
| `ingestion/pipeline.py` | 317 | **CRITICAL** |
| `ta_run.py` | 309 | HIGH |
| `ui/pages/ml_pipeline.py` | 322 | MEDIUM |
| `finrl_runner.py` | 277 | **CRITICAL** |
| `app.py` | 208 | MEDIUM |
| `ui/pages/stock_detail.py` | 102 | LOW |
| `main.py` | 93 | MEDIUM |
| `ui/pages/stock_technical.py` | 91 | LOW |
| `ml_bucket_selector.py` | 90 | HIGH |
| `ui/pages/paper_trading.py` | 79 | LOW |
| `ui/pages/stock_lookup.py` | 78 | LOW |
| `full_pipeline.py` | 76 | **CRITICAL** |
| `ingestion/indicators.py` | 66 | HIGH |
| `ui/pages/live_trading.py` | 63 | LOW |
| `ui/pages/stock_manager.py` | 67 | LOW |
| `ui/pages/stock_screener.py` | 51 | LOW |
| `ui/pages/strategy_backtest.py` | 51 | LOW |
| `ui/pages/portfolio.py` | 47 | LOW |
| `ingestion/symbols.py` | 39 | MEDIUM |
| `ui/pages/settings.py` | 35 | LOW |
| `ui/pages/overview.py` | 16 | LOW |
| `ui/pages/__init__.py` | 15 | LOW |
| `ui/pages/job_history.py` | 15 | LOW |
| `logging_config.py` | 5 | LOW |

### Low Coverage (1-50%)

| Module | Cov | Stmts | Miss |
|--------|-----|-------|------|
| `fetcher/alpha_vantage.py` | 19% | 149 | 121 |
| `scheduler.py` | 23% | 78 | 60 |
| `repository.py` | 29% | 161 | 115 |
| `config.py` | 35% | 17 | 11 |
| `fetcher/yahoo.py` | 38% | 21 | 13 |
| `pipeline/data_update.py` | 43% | 35 | 20 |

### High Coverage (80%+)

`display.py`, `fetcher/base.py`, `fetcher/rate_limiter.py`, `models.py`, `migrations/run.py`, `utils.py`, `pipeline/*` orchestration files — all 89-100%.

---

## 3. Untested Function Inventory

### `ingestion/pipeline.py` (13 functions, 317 stmts)

| Function | Risk | Key paths untested |
|----------|------|--------------------|
| `_last_trading_date` | HIGH | NYSE calendar fetch, empty schedule, weekend fallback |
| `_prefetch_stock_dates` | HIGH | 4 batch queries, skip_stock_ids computation |
| `_fetch_and_store_prices` | **CRITICAL** | Deadlock retry 5x, batch insert, empty DataFrame |
| `_upsert_fundamentals` | **CRITICAL** | Deadlock retry 3x, freshness check, empty data |
| `_refresh_snapshots` | MEDIUM | Raw SQL REPLACE INTO |
| `_batch_update_checkpoints` | LOW | Bulk UPDATE |
| `_needs_full_backfill` | MEDIUM | Indicator/price gap > 365 days |
| `_fetch_stock_news` | HIGH | Google → AV fallback, rate-limit flag |
| `_fetch_stock_news_av` | MEDIUM | news_cache.set_cached direct call |
| `_process_symbol` | **CRITICAL** | Orchestrates all 4 operations per symbol |
| `run_daily_pipeline` | **CRITICAL** | ThreadPoolExecutor, progress tracking, PipelineRun lifecycle |
| `run_bootstrap` | HIGH | Full overview fetch, auto-activate |
| `_auto_activate` | MEDIUM | Dynamic filter query |

### `repository.py` (17 methods, 161 stmts)

All 15 data methods untested: `find_stock`, `find_stocks_batch`, `get_prices`, `get_indicator`, `get_snapshot`, `get_tech_indicators`, `screen_stocks`, `list_stocks`, `count_summary`, `bulk_set_active`, `get_sectors`, `save_selected_stocks`, `save_predict_only_results`, `get_latest_selected_stocks`, `get_job_runs`.

### `scheduler.py` (5 functions, 78 stmts)

All untested: `_record_job_start`, `_record_job_end`, `job_daily_pipeline`, `job_refresh_symbols`, `main`.

### `fetcher/alpha_vantage.py` (10 methods, 149 stmts)

8 HTTP methods untested: `get_daily`, `get_overview`, `get_income_statement`, `get_balance_sheet`, `get_cashflow`, `get_fundamentals`, `get_listing`, `get_news_sentiment`. Retry logic in `_get` partially covered.

---

## 4. Test Skeletons by Category

### 4.1 Deadlock Retry (MySQL 1213)

```python
# tests/test_ingestion_pipeline.py
class TestDeadlockRetry:
    def test_prices_retries_on_deadlock_then_succeeds(self, monkeypatch):
        """5 attempts: fails twice with 1213, succeeds 3rd time."""

    def test_prices_fails_on_non_deadlock_error(self, monkeypatch):
        """Error 2006 (server gone) → raise immediately, no retry."""

    def test_prices_exhausts_retries_then_raises(self, monkeypatch):
        """5 consecutive 1213 errors → raise after 5th attempt."""

    def test_fundamentals_retries_on_deadlock_then_succeeds(self, monkeypatch):
        """3 attempts: fails once with 1213, succeeds 2nd time."""

    def test_fundamentals_exhausts_retries_then_raises(self, monkeypatch):
        """3 consecutive 1213 errors → raise after 3rd attempt."""
```

### 4.2 News Rate Limit Fallback

```python
class TestNewsRateLimitFallback:
    def test_rate_limit_switches_to_av_fallback(self, monkeypatch):
        """Google returns 'rate limit exceeded' → set flag, call AV."""

    def test_non_rate_limit_error_does_not_set_flag(self, monkeypatch):
        """Network timeout → log warning, return 0, keep flag False."""

    def test_flag_persists_across_symbols(self, monkeypatch):
        """Flag True → subsequent symbols skip Google entirely."""

    def test_av_fallback_returns_zero_on_error(self, monkeypatch):
        """AV also fails → return 0, no crash."""
```

### 4.3 DataUpdateStep Status Logic

```python
class TestDataUpdateStepStatusLogic:
    def test_zero_attempted_zero_failed_is_success(self):
        """symbols_attempted=0 → success (nothing to do)."""

    def test_all_attempted_none_succeeded_is_failed(self):
        """5 attempted, 0 succeeded → failed."""

    def test_partial_failure_is_success(self):
        """5 attempted, 4 succeeded → success (not all failed)."""

    def test_exception_during_run_returns_failed_stepresult(self):
        """_run_pipeline raises → StepResult(status='failed') with error."""
```

### 4.4 Session Cleanup

```python
class TestSessionCleanup:
    def test_session_closed_after_success(self, monkeypatch):
        """Normal completion → session.close() called."""

    def test_session_closed_after_deadlock_exhaustion(self, monkeypatch):
        """After 5 retries exhausted → session.close() still called."""

    def test_session_rolled_back_on_error(self, monkeypatch):
        """Exception → session.rollback() before re-raise."""

    def test_session_closed_even_if_rollback_fails(self, monkeypatch):
        """rollback() itself raises → close() still called in finally."""
```

### 4.5 Empty / None Edge Cases

```python
class TestEmptyEdgeCases:
    def test_prefetch_empty_stock_ids_returns_empty_dicts(self):
        """_prefetch_stock_dates([]) → all empty dicts + empty skip set."""

    def test_pipeline_empty_symbols_list_runs_zero_stocks(self, monkeypatch):
        """symbols=[] → no stocks processed, run record completed."""

    def test_empty_price_dataframe_returns_zero_rows(self, monkeypatch):
        """fetcher.get_daily returns empty DF → 0 inserted, no crash."""

    def test_empty_overview_data_returns_false(self, monkeypatch):
        """fetcher.get_overview returns {} → False, no upsert."""

    def test_no_selected_stocks_returns_empty_list(self, db_session):
        """Empty selected_stocks table → get_latest returns []."""

    def test_null_indicators_json_returns_date_only(self, db_session):
        """TechnicalIndicator.indicators = None → DF with date column only."""

    def test_start_after_end_skips_fetch(self, monkeypatch):
        """max_date = last_trading_date → start > end → return 0."""

    def test_none_weight_in_save_predictions(self, db_session):
        """weight=None → stored as None, no TypeError."""
```

### 4.6 Boundary Values

```python
class TestBoundaryValues:
    def test_single_stock_prefetch(self, monkeypatch):
        """_prefetch_stock_dates with 1-element list."""

    def test_batch_insert_exactly_one_row(self, monkeypatch):
        """Single price row → insert batch of size 1."""

    def test_error_message_exactly_2000_chars(self, db_session):
        """2000-char error → stored as-is (no truncation)."""

    def test_error_message_2001_chars_truncated(self, db_session):
        """2001-char error → truncated to 2000."""

    def test_limit_zero_returns_empty_dataframe(self, db_session):
        """get_job_runs(limit=0) → empty DataFrame."""

    def test_zero_volume_in_prices(self, monkeypatch):
        """Volume=0 rows → inserted normally."""
```

### 4.7 Alpha Vantage Retry/Error

```python
class TestAlphaVantageRetry:
    def test_retries_on_rate_limit_429(self, requests_mock):
        """429 → wait → retry → succeed."""

    def test_retries_on_server_error_503(self, requests_mock):
        """503 → retry → succeed."""

    def test_exhausts_retries_on_persistent_429(self, requests_mock):
        """5 consecutive 429s → raise rate limit error."""

    def test_no_retry_on_403_forbidden(self, requests_mock):
        """403 → raise immediately."""

    def test_empty_json_response_returns_empty(self, requests_mock):
        """{} body → return {}."""

    def test_malformed_json_raises(self, requests_mock):
        """'Not JSON' body → ValueError."""

    def test_rate_limit_info_message_handled(self, requests_mock):
        """AV's 'Thank you for using Alpha Vantage' → no crash."""
```

### 4.8 Repository Integration

```python
class TestRepositoryMethods:
    def test_find_stock_exact_symbol_match(self, db_session):
        """Symbol lookup returns correct Stock object."""

    def test_find_stock_missing_returns_none(self, db_session):
        """Unknown symbol → None."""

    def test_find_stocks_batch_returns_dict(self, db_session):
        """Multiple symbols → {SYMBOL: Stock} mapping."""

    def test_get_prices_date_range(self, db_session):
        """Date filtering returns correct window."""

    def test_screen_stocks_with_all_criteria(self, db_session):
        """All ScreenCriteria fields applied → filtered results."""

    def test_screen_stocks_null_values_passed_through(self, db_session):
        """NULL PE/RSI → included (not filtered out)."""

    def test_save_selected_with_pipeline_run_id_scoped(self, db_session):
        """Different run_ids → independent delete scope."""

    def test_save_selected_overwrites_same_run_id(self, db_session):
        """Same run_id twice → first rows deleted, second inserted."""

    def test_count_summary_empty_db(self, db_session):
        """No stocks → total=0, active=0, inactive=0."""

    def test_bulk_set_active_empty_ids_noop(self, db_session):
        """ids=[] → no query executed, no crash."""

    def test_bulk_set_active_sets_timestamp(self, db_session):
        """Active=True → activated_at set to now."""

    def test_get_sectors_distinct_sorted(self, db_session):
        """Returns alphabetically sorted distinct sectors."""
```

### 4.9 Integration Flows

```python
# tests/test_integration_data_update.py
class TestDataUpdateIntegration:
    def test_price_fetch_stores_in_db(self, db_session):
        """Mock fetcher → rows appear in daily_prices."""

    def test_pipeline_creates_run_record(self, db_session):
        """run_daily_pipeline → PipelineRun row with status='completed'."""

    def test_pipeline_updates_run_on_partial_error(self, db_session):
        """One symbol fails → status='completed_with_errors'."""

    def test_skip_up_to_date_stocks(self, db_session):
        """Fresh price + fundamentals → stock excluded from processing."""

# tests/test_integration_scheduler.py
class TestSchedulerIntegration:
    def test_job_records_start_and_end(self, db_session):
        """Job → start record created, end record updated."""

    def test_job_records_failure_with_error_message(self, db_session):
        """Exception in job → status='failed', error stored."""

    def test_job_error_truncated_to_2000_chars(self, db_session):
        """Long error → truncated to 2000 chars."""

# tests/test_integration_full_pipeline.py
class TestFullPipelineIntegration:
    def test_four_steps_run_in_order(self, db_session, tmp_path):
        """Orchestrator → data_update → selection → fast_eval → deep_eval."""

    def test_pipeline_stops_on_failed_step(self, db_session, tmp_path):
        """Failed step → halt, no subsequent steps run."""

    def test_resume_from_skips_completed(self, db_session, tmp_path):
        """--resume-from fast_evaluation → skips first 2 steps."""

    def test_symbols_filter_passes_through(self, db_session, tmp_path):
        """--symbols AAPL,MSFT → selection step skipped, symbols flow through."""
```

### 4.10 `utcnow()` Deprecation

`datetime.datetime.utcnow()` deprecated in Python 3.12+. 6+ sites generate warnings in test output. Replace with `datetime.datetime.now(datetime.UTC)`.

---

## 5. Prioritized Remediation Plan

| Phase | Work | Tests | Target Coverage |
|-------|------|-------|-----------------|
| **Phase 1** | Fix 3 infrastructure bugs | Unblock 28 tests | 29% → 35% |
| **Phase 2** | Critical modules: ingestion/pipeline, repository, scheduler, alpha_vantage, finrl_runner | +85 new tests | 35% → 60% |
| **Phase 3** | Error handling + edge cases | +37 new tests | 60% → 72% |
| **Phase 4** | Integration tests | +19 new tests | 72% → 78% |
| **Phase 5** | UI smoke tests | +12 new tests | 78% → 82% |

**Total effort:** ~8-10 days to reach 80%+ coverage with ~150 additional tests.
