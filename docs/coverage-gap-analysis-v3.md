# AIStock Test Coverage Gap Analysis v3 — with Test Skeletons

**Date:** 2026-05-30
**Baseline:** 29% overall (140 passed, 12 failed, 20 errors)
**Modules:** 53 total, 24 zero-coverage, 21 >=80%

See `docs/coverage-gap-analysis.md` (v2) for the summary dashboard. This v3 adds detailed test skeletons for every gap category.

---

## Priority Work Plan

| Sprint | Scope | Tests | Coverage Gain |
|--------|-------|-------|---------------|
| **Sprint 0: Fix existing failures** | repo (20 err), scheduler (6 fail), database (1 fail) | ~27 restored | +5% → 34% |
| **Sprint 1: Ingestion core** | pipeline, indicators, symbols | ~32 new | +12% → 46% |
| **Sprint 2: Fetchers** | alpha_vantage, yahoo | ~21 new | +6% → 52% |
| **Sprint 3: Repo + integration** | repository extend, error handling, integration | ~40 new | +10% → 62% |
| **Sprint 4: Remaining** | ml_bucket_selector, news_cache, ta_run | ~22 new | +5% → 67% |

Target: **67%** (80% requires UI page tests tracked separately).

---

## Gap Category 1: Untested Functions (Zero-Coverage Modules)

### 1.1 `src/ingestion/pipeline.py` — 289 stmts, 0% coverage **P0**

Core data ingestion pipeline. 15 functions, all untested.

**Functions:**
```
_last_trading_date()                          — date utility
_prefetch_stock_dates(stock_ids)              — DB query batching
_fetch_and_store_prices(fetcher, stock, ...)  — API + DB write
_upsert_fundamentals(fetcher, stock, ...)     — API + DB upsert
_refresh_snapshots()                          — materialized view
_batch_update_checkpoints(stock_ids)          — DB batch update
_needs_full_backfill(first_ind, first_price)  — decision logic
_fetch_stock_news(symbol, fetcher)            — Google → AV fallback
_fetch_stock_news_av(symbol, fetcher)         — AV news
_process_symbol(fetcher, stock, ...)          — per-stock orchestrator
run_daily_pipeline(fetcher, force)            — main entry point
run_bootstrap(fetcher, auto_activate_criteria) — bootstrap entry
_auto_activate(criteria)                      — auto-activation
```

**Test skeletons** (`tests/test_ingestion_pipeline.py`):

```python
"""Tests for src/ingestion/pipeline.py."""


class TestLastTradingDate:
    """_last_trading_date() returns the most recent trading day."""

    def test_returns_today_when_market_open(self, monkeypatch):
        """Tuesday 2pm → returns today."""
        from datetime import datetime
        import ingestion.pipeline as mod

        tuesday_2pm = datetime(2026, 5, 26, 14, 0, 0)
        monkeypatch.setattr(mod, "datetime", type("fake", (), {
            "now": lambda tz=None: tuesday_2pm,
            "date": type("d", (), {"today": lambda: tuesday_2pm.date()}),
        }))
        result = mod._last_trading_date()
        assert result == tuesday_2pm.date()

    def test_returns_friday_on_saturday(self, monkeypatch):
        """Saturday → returns Friday."""
        from datetime import datetime
        import ingestion.pipeline as mod

        saturday = datetime(2026, 5, 30, 10, 0, 0)
        monkeypatch.setattr(mod, "datetime", type("fake", (), {
            "now": lambda tz=None: saturday,
            "date": type("d", (), {"today": lambda: saturday.date()}),
        }))
        result = mod._last_trading_date()
        assert result.weekday() == 4  # Friday

    def test_returns_friday_on_sunday(self, monkeypatch):
        """Sunday → returns Friday."""
        pass

    def test_returns_previous_day_after_market_close(self, monkeypatch):
        """After 4pm ET → returns previous trading day."""
        pass


class TestNeedsFullBackfill:
    """_needs_full_backfill(first_indicator_date, first_price_date)."""

    def test_no_dates_means_full_backfill(self):
        """Both None → True."""
        from ingestion.pipeline import _needs_full_backfill
        assert _needs_full_backfill(None, None) is True

    def test_indicator_before_price_means_full_backfill(self):
        """Indicator predates price → True."""
        from datetime import date
        from ingestion.pipeline import _needs_full_backfill
        assert _needs_full_backfill(date(2020, 1, 1), date(2023, 1, 1)) is True

    def test_close_dates_means_no_backfill(self):
        """Dates within 30 days → False."""
        from datetime import date
        from ingestion.pipeline import _needs_full_backfill
        assert _needs_full_backfill(date(2026, 5, 1), date(2026, 5, 15)) is False

    def test_indicator_after_price_means_no_backfill(self):
        """Indicator date is newer → False."""
        pass


class TestFetchAndStorePrices:
    """_fetch_and_store_prices(fetcher, stock, max_date)."""

    def test_fetches_and_stores_new_prices(self, monkeypatch, db_session):
        """Fetcher returns DataFrame → rows inserted into daily_prices."""
        pass

    def test_empty_dataframe_skips_insert(self, monkeypatch, db_session):
        """Fetcher returns empty DataFrame → no insert, success logged."""
        pass

    def test_api_error_returns_zero_count(self, monkeypatch, db_session):
        """Fetcher raises exception → logged, returns 0."""
        pass

    def test_duplicate_price_rows_upsert(self, monkeypatch, db_session):
        """Existing (stock_id, date) pairs updated, not duplicated."""
        pass

    def test_uses_last_trading_date_as_end(self, monkeypatch):
        """End date matches _last_trading_date(), not datetime.today()."""
        pass


class TestUpsertFundamentals:
    """_upsert_fundamentals(fetcher, stock, force, indicator_last_updated)."""

    def test_upserts_new_fundamentals(self, monkeypatch, db_session):
        """Fetcher returns data → stock_indicators row upserted."""
        pass

    def test_skips_when_indicator_fresh(self, monkeypatch, db_session):
        """Indicator updated within refresh_window → skip API call."""
        pass

    def test_force_overrides_freshness_check(self, monkeypatch, db_session):
        """force=True → always calls API regardless of last_updated."""
        pass

    def test_api_error_returns_false(self, monkeypatch, db_session):
        """API failure → logged, returns False."""
        pass


class TestFetchStockNews:
    """_fetch_stock_news(symbol, fetcher) with Google → AV fallback."""

    def test_google_news_success(self, monkeypatch):
        """Google returns valid data → returned as list of dicts."""
        pass

    def test_google_rate_limit_falls_back_to_av(self, monkeypatch):
        """Google returns rate-limit error → falls back to Alpha Vantage."""
        pass

    def test_both_apis_fail_returns_empty(self, monkeypatch):
        """Both Google and AV fail → returns empty list, no crash."""
        pass

    def test_empty_news_list_stored_as_null(self, monkeypatch, db_session):
        """No news found → NULL stored, not error."""
        pass


class TestProcessSymbol:
    """_process_symbol(fetcher, stock, force, prefetch) orchestrates per-stock flow."""

    def test_returns_tuple_of_counts(self, monkeypatch):
        """Returns (prices_count, indicators_count, news_count)."""
        pass

    def test_partial_failure_continues(self, monkeypatch):
        """Price fetch fails → still attempts indicators and news."""
        pass

    def test_inactive_stock_skipped(self, monkeypatch):
        """stock.is_active == False → skipped entirely."""
        pass

    def test_all_failures_returns_zeros(self, monkeypatch):
        """All three fetches fail → (0, 0, 0)."""
        pass


class TestRunDailyPipeline:
    """run_daily_pipeline(fetcher, force) — main entry point."""

    def test_processes_all_active_stocks(self, monkeypatch, db_session):
        """Iterates all active stocks, calls _process_symbol for each."""
        pass

    def test_force_flag_overrides_incremental(self, monkeypatch):
        """force=True → _process_symbol called with force=True."""
        pass

    def test_returns_summary_dict(self, monkeypatch):
        """Returns {total, prices, indicators, news, errors, ...}."""
        pass

    def test_error_in_one_stock_doesnt_stop_pipeline(self, monkeypatch):
        """Single stock failure → continues to next stock."""
        pass

    def test_progress_logging_includes_count(self, monkeypatch, caplog):
        """Log line includes [N/total] progress counter."""
        pass


class TestRunBootstrap:
    """run_bootstrap(fetcher, auto_activate_criteria)."""

    def test_auto_activates_eligible_stocks(self, monkeypatch, db_session):
        pass

    def test_respects_auto_activate_criteria(self, monkeypatch):
        pass


class TestRefreshSnapshots:
    """_refresh_snapshots() — refreshes materialized snapshot table."""

    def test_recomputes_all_snapshots(self, db_session):
        pass

    def test_empty_stock_table_no_error(self, db_session):
        pass


class TestBatchUpdateCheckpoints:
    """_batch_update_checkpoints(stock_ids) — bulk timestamp update."""

    def test_updates_multiple_stock_ids(self, db_session):
        pass

    def test_empty_list_noop(self, db_session):
        pass
```

### 1.2 `src/ingestion/indicators.py` — 66 stmts, 0% **P1**

```python
# tests/test_ingestion_indicators.py

class TestComputeIndicators:
    """compute_indicators(stock_id, since_date)."""

    def test_computes_indicators_from_prices(self, db_session):
        """Given price data → returns count > 0."""
        pass

    def test_no_price_data_returns_zero(self, db_session):
        pass

    def test_since_date_filters_old_prices(self, db_session):
        """Only indicator rows after since_date are computed."""
        pass

    def test_missing_stock_id_returns_zero(self, db_session):
        pass

    def test_partial_technical_data_handled(self, db_session):
        """Some indicator calculations fail → rest still written."""
        pass
```

### 1.3 `src/ingestion/symbols.py` — 39 stmts, 0% **P1**

```python
# tests/test_ingestion_symbols.py

class TestClean:
    """_clean(val) — whitespace/normalization helper."""

    def test_normal_string(self):
        from ingestion.symbols import _clean
        assert _clean("AAPL") == "AAPL"

    def test_whitespace_stripped(self):
        from ingestion.symbols import _clean
        assert _clean("  AAPL  ") == "AAPL"

    def test_none_returns_none(self):
        from ingestion.symbols import _clean
        assert _clean(None) is None

    def test_empty_string_returns_empty(self):
        from ingestion.symbols import _clean
        assert _clean("") == ""


class TestRefreshSymbols:
    """refresh_symbols(fetcher)."""

    def test_adds_new_symbols(self, monkeypatch, db_session):
        """Fetcher returns new tickers → inserted into stocks table."""
        pass

    def test_updates_existing_symbols(self, monkeypatch, db_session):
        """Existing ticker → updates company_name, sector, etc."""
        pass

    def test_marks_delisted_as_inactive(self, monkeypatch, db_session):
        """Ticker no longer in listing → is_active = False."""
        pass

    def test_empty_listing_returns_zero(self, monkeypatch, db_session):
        pass

    def test_api_error_returns_zero(self, monkeypatch, db_session):
        pass
```

### 1.4 `src/ml_bucket_selector.py` — 90 stmts, 0% **P2**

```python
# tests/test_ml_bucket_selector.py

class TestMLBucketSelector:
    """MLBucketSelector wraps FinRL run_bucket per sector."""

    def test_init_defaults(self):
        from ml_bucket_selector import MLBucketSelector
        sel = MLBucketSelector()
        assert sel.top_quantile > 0

    def test_fit_predict_returns_dataframe(self, monkeypatch):
        pass

    def test_empty_fundamentals_returns_empty(self, monkeypatch):
        pass

    def test_saves_models_to_directory(self, tmp_path, monkeypatch):
        pass

    def test_missing_feature_columns_raises_clear_error(self, monkeypatch):
        """Missing required columns → ValueError, not KeyError."""
        pass

    def test_single_sector_handled(self, monkeypatch):
        """Only one sector → runs single bucket, no crash."""
        pass
```

### 1.5 `src/ta_run.py` — 309 stmts, 0% **P2** (TradingAgents runner)

```python
# tests/test_ta_run.py

class TestIsEmpty:
    """_is_empty(value)."""

    def test_none_is_empty(self):
        from ta_run import _is_empty
        assert _is_empty(None) is True

    def test_empty_string_is_empty(self):
        from ta_run import _is_empty
        assert _is_empty("") is True

    def test_whitespace_only_is_empty(self):
        from ta_run import _is_empty
        assert _is_empty("   ") is True

    def test_nan_is_empty(self):
        from ta_run import _is_empty
        assert _is_empty(float("nan")) is True

    def test_non_empty_not_empty(self):
        from ta_run import _is_empty
        assert _is_empty("BUY") is False


class TestCallTracker:
    """_CallTracker counts LLM API calls."""

    def test_starts_at_zero(self):
        from ta_run import _CallTracker
        ct = _CallTracker(logger=None)
        assert ct.count == 0

    def test_increments_on_llm_start(self):
        pass

    def test_emits_state_on_llm_end(self):
        pass


class TestSaveReport:
    """_save_report(final_state, ticker, date, save_path)."""

    def test_writes_markdown_file(self, tmp_path):
        pass

    def test_creates_parent_directories(self, tmp_path):
        pass


class TestExtractDecision:
    """_extract_decision(final_state, fallback_decision)."""

    def test_extracts_buy(self):
        pass

    def test_extracts_sell(self):
        pass

    def test_fallback_when_missing(self):
        """Missing decision field → uses fallback."""
        pass


class TestSummariseReport:
    """_summarise_report(report_text, llm, label, logger)."""

    def test_extracts_key_bull_points(self, monkeypatch):
        pass

    def test_llm_error_returns_empty_list(self, monkeypatch):
        """LLM call fails → returns [], not exception."""
        pass
```

---

## Gap Category 2: Low-Coverage Modules (Edge Cases)

### 2.1 `src/fetcher/alpha_vantage.py` — 18.8%, 149 stmts **P0**

```python
# Extend tests/test_fetcher_alpha_vantage.py or create new test file

class TestAlphaVantageGet:
    """_get() — HTTP request with retry logic."""

    def test_rate_limit_triggers_retry(self, monkeypatch):
        """429 response → retries after backoff."""
        pass

    def test_max_retries_exceeded_raises(self, monkeypatch):
        """All retries exhausted → raises last error."""
        pass

    def test_api_key_included_in_params(self, monkeypatch):
        """Every request includes apikey param."""
        pass

    def test_non_json_response_returns_raw_text(self, monkeypatch):
        """HTML/text response → returns raw string, not parse error."""
        pass

    def test_timeout_handled_as_retry(self, monkeypatch):
        """Connection timeout → treated as retryable error."""
        pass


class TestGetOverview:
    """get_overview(symbol)."""

    def test_parses_full_company_overview(self, monkeypatch):
        pass

    def test_missing_optional_fields_return_none(self, monkeypatch):
        """Fields like 'Sector' missing → None, not KeyError."""
        pass

    def test_delisted_stock_handled(self, monkeypatch):
        pass


class TestGetNewsSentiment:
    """get_news_sentiment(symbol, days)."""

    def test_parses_news_items_correctly(self, monkeypatch):
        pass

    def test_no_news_returns_empty_list(self, monkeypatch):
        pass

    def test_rate_limit_returns_empty_list(self, monkeypatch):
        """Rate limit → empty list, not exception."""
        pass

    def test_days_parameter_respected(self, monkeypatch):
        """Request params include time_from with correct date."""
        pass

    def test_sentiment_score_is_float(self, monkeypatch):
        """Sentiment score parsed as float, not string."""
        pass


class TestGetEarnings:
    """get_earnings(symbol)."""

    def test_parses_quarterly_earnings(self, monkeypatch):
        pass

    def test_no_earnings_returns_empty_dataframe(self, monkeypatch):
        pass

    def test_surprise_percent_calculated(self, monkeypatch):
        pass
```

### 2.2 `src/repository.py` — 28.6%, all 20 tests erroring **P0 BLOCKER**

Fix fixture first, then extend:

```python
# Fix and extend tests/test_repository.py

class TestFindStock:
    def test_returns_none_for_unknown_symbol(self, repo):
        """Symbol not in DB → None."""
        result = repo.find_stock("ZZZUNKNOWN")
        assert result is None

    def test_case_sensitivity(self, repo):
        """Symbol matching behavior — verify case handling."""
        pass


class TestFindStocksBatch:
    """find_stocks_batch(symbols) — batch lookup."""

    def test_returns_dict_keyed_by_symbol(self, repo):
        pass

    def test_empty_list_returns_empty_dict(self, repo):
        pass

    def test_partial_match_returns_only_found(self, repo):
        """Some symbols missing → only found ones returned."""
        pass


class TestGetPrices:
    """get_prices(stock_id, start, end)."""

    def test_returns_dataframe_with_date_index(self, repo):
        pass

    def test_no_prices_returns_empty_dataframe(self, repo):
        pass

    def test_date_range_filters_correctly(self, repo):
        """start <= rows <= end."""
        pass


class TestScreenStocks:
    """screen_stocks(criteria: ScreenCriteria)."""

    def test_filters_by_sector(self, repo):
        pass

    def test_filters_by_market_cap_range(self, repo):
        """min_market_cap and max_market_cap both applied."""
        pass

    def test_filters_by_pe_range(self, repo):
        pass

    def test_multiple_criteria_combined(self, repo):
        """Sector + market cap + PE filters applied together."""
        pass

    def test_no_matches_returns_empty_dataframe(self, repo):
        pass

    def test_null_values_in_filter_columns(self, repo):
        """Stocks with NULL PE/market_cap → excluded, not error."""
        pass


class TestListStocks:
    """list_stocks(filters: StockFilters)."""

    def test_sort_order_respected(self, repo):
        """sort_by='market_cap' → rows in descending order."""
        pass

    def test_pagination_limit(self, repo):
        """limit=N → returns at most N rows."""
        pass

    def test_pagination_offset(self, repo):
        """offset=N → skips first N rows."""
        pass


class TestSavePredictOnlyResults:
    """save_predict_only_results(predictions)."""

    def test_inserts_multiple_predictions(self, repo):
        pass

    def test_empty_list_noop(self, repo):
        pass

    def test_upserts_existing_prediction(self, repo):
        """Same (stock_id, label_method) → updates probability."""
        pass


class TestGetLatestSelectedStocks:
    """get_latest_selected_stocks()."""

    def test_returns_most_recent_run(self, repo):
        pass

    def test_no_selections_returns_empty_list(self, repo):
        pass
```

---

## Gap Category 3: Missing Error Handling Tests

```python
# tests/test_error_handling.py

class TestApiErrorHandling:
    """System behavior when external APIs fail."""

    def test_alpha_vantage_timeout_graceful(self):
        """Connection timeout → logged, operation continues to next stock."""
        pass

    def test_yahoo_rate_limit_not_fatal(self):
        """Rate limit → empty DataFrame, not exception."""
        pass

    def test_network_partition_mid_batch(self):
        """Network drops during batch → partial results, no data loss."""
        pass

    def test_invalid_api_key_clear_message(self):
        """Invalid key → actionable error message, not raw traceback."""
        pass


class TestDatabaseErrorHandling:
    """System behavior when database operations fail."""

    def test_connection_lost_rollback_and_retry(self):
        """DB drops mid-transaction → rollback + retry."""
        pass

    def test_unique_constraint_violation_upserts(self):
        """Duplicate (stock_id, date) → ON DUPLICATE KEY UPDATE works."""
        pass

    def test_connection_pool_exhaustion_clear_error(self):
        """All connections in use → clear PoolLimitError, not hang."""
        pass


class TestConfigErrorHandling:
    """System behavior with invalid configuration."""

    def test_missing_config_file_clear_error(self):
        """config.yaml absent → FileNotFoundError with path."""
        pass

    def test_invalid_yaml_syntax_parse_error(self):
        """Malformed YAML → error with line number."""
        pass

    def test_missing_required_api_key_startup_error(self):
        """Required key absent → RuntimeError with key name."""
        pass

    def test_invalid_database_url_connection_error(self):
        """Bad DB URL → actionable error, not raw exception chain."""
        pass


class TestDataEdgeCases:
    """System behavior with unusual/edge-case data."""

    def test_all_zero_ohlcv_data(self):
        """Zero prices → no division-by-zero in indicator calc."""
        pass

    def test_stock_with_no_fundamentals(self):
        """Has prices, no fundamentals → handled gracefully."""
        pass

    def test_negative_price_filtered(self):
        """Bad data: negative close → flagged, not propagated."""
        pass

    def test_missing_dates_in_price_series(self):
        """Gaps in daily data → interpolation or skip, not crash."""
        pass

    def test_dot_ticker_symbols(self):
        """Symbols like 'BRK.A', '9988.HK' → handled correctly."""
        pass

    def test_extremely_large_volume(self):
        """Volume > int32 max → no overflow."""
        pass
```

---

## Gap Category 4: Missing Integration Tests

```python
# tests/test_integration_pipeline.py

class TestDataUpdateFlow:
    """End-to-end: data_update step → DB tables populated."""

    def test_full_update_writes_prices(self, db_session, monkeypatch):
        """Run data_update → daily_prices has new rows."""
        pass

    def test_full_update_writes_indicators(self, db_session, monkeypatch):
        """Run data_update → stock_indicators has new rows."""
        pass

    def test_full_update_writes_news(self, db_session, monkeypatch):
        """Run data_update → stock_news has new rows."""
        pass

    def test_incremental_update_only_new_data(self, db_session, monkeypatch):
        """Second run → only fetches data after last stored date."""
        pass

    def test_news_google_to_av_fallback_integration(self, db_session, monkeypatch):
        """Google rate-limits → AV succeeds → pipeline completes."""
        pass


class TestStepChain:
    """Multi-step pipeline integration."""

    def test_data_update_feeds_stock_selection(self, db_session, tmp_path, monkeypatch):
        """step 1 output → step 2 reads from same DB."""
        pass

    def test_stock_selection_feeds_fast_evaluation(self, db_session, tmp_path, monkeypatch):
        """step 2 output → step 3 input."""
        pass

    def test_fast_evaluation_feeds_deep_evaluation(self, db_session, tmp_path, monkeypatch):
        """step 3 top-N → step 4 input."""
        pass

    def test_all_steps_share_pipeline_run_id(self, db_session, tmp_path, monkeypatch):
        """Single pipeline_run_id across all 4 steps."""
        pass


class TestSchedulerIntegration:
    """APScheduler jobs — end-to-end."""

    def test_daily_pipeline_job_writes_run_record(self, db_session, monkeypatch):
        """job_daily_pipeline() → writes to pipeline_runs table."""
        pass

    def test_job_failure_records_error(self, db_session, monkeypatch):
        """Job raises → error logged to scheduled_job_runs."""
        pass
```

---

## Gap Category 5: Existing Test Failures (Blocking Fixes)

### 5.1 Repository tests — All 20 error **P0 BLOCKER**

Root cause: `repo` fixture likely incompatible with current `StockRepository` session API. The `_get_session()` / `_with_session()` methods may not match fixture expectations.

**Fix approach:**
```python
# tests/conftest.py — verify repo fixture
@pytest.fixture
def repo(db_session):
    """Return StockRepository wired to test DB session."""
    from repository import StockRepository
    return StockRepository()  # verify this matches current __init__ signature
```

### 5.2 Scheduler tests — 6 of 6 fail **P1**

Root cause: `_record_job_start` returns `int` (run_id), tests may expect different type or the function signature changed.

### 5.3 Database test — 1 failure **P1**

`test_creates_all_tables_without_error` — SQLite backend incompatible with MySQL-specific DDL (`ON DUPLICATE KEY UPDATE`).

---

## Appendix: Full Module Coverage Table

| Module | Stmts | Cov% | Tests | Status |
|--------|-------|------|-------|--------|
| `ingestion/pipeline.py` | 289 | 0% | none | **Sprint 1** |
| `ta_run.py` | 309 | 0% | none | Sprint 4 |
| `finrl_runner.py` | 277 | 0% | none | Sprint 4 |
| `app.py` | 208 | 0% | E2E only | defer (UI) |
| `fetcher/alpha_vantage.py` | 149 | 18.8% | 4 tests | **Sprint 2** |
| `repository.py` | 161 | 28.6% | 20 tests (err) | **Sprint 0 fix + Sprint 3 extend** |
| `scheduler.py` | 78 | 23.1% | 6 tests (fail) | **Sprint 0 fix** |
| `ml_bucket_selector.py` | 90 | 0% | none | Sprint 4 |
| `news_cache.py` | 91 | 53.8% | 11 tests | Sprint 4 |
| `ingestion/indicators.py` | 66 | 0% | none | Sprint 1 |
| `ingestion/symbols.py` | 39 | 0% | none | Sprint 1 |
| `fetcher/yahoo.py` | 21 | 38.1% | minimal | Sprint 2 |
| `config.py` | 17 | 35.3% | partial | Sprint 2 |
| `pipeline/data_update.py` | 34 | 44.1% | 4 tests | Sprint 3 |
| `pipeline/backends/selectors.py` | 60 | 70.0% | 7 tests | Sprint 3 |
| `ui/pages/*` | ~700 | 0% | E2E only | defer (UI) |
| pipeline/* other | ~543 | 89-98% | good | — |
| utils/display/models/etc | ~374 | 100% | good | — |
