# Test Coverage Gap Analysis — AIStock

**Date**: 2026-05-30
**Stats**: 85 tests collected, 71 pass (1 E2E fail — needs Streamlit server) | **Overall: 24%** (4024 stmts, 3052 missed)
**Framework**: pytest 9.x + pytest-cov | **In-memory SQLite** for DB tests

---

## Summary

| Category | Count |
|----------|-------|
| Completely untested source files (0%) | 16 |
| Partially tested (<80%) | 4 |
| Well-tested (≥80%) | 14 |
| Missing error handling tests | 12 areas |
| Missing edge case tests | 10 areas |
| Integration test gaps | 5 areas |

### Actual Coverage by File (pytest --cov=src)

| File | Stmts | Miss | Cover | Status |
|------|-------|------|-------|--------|
| `src/models.py` | 299 | 0 | **100%** | PASS |
| `src/migrations/run.py` | 39 | 0 | **100%** | PASS |
| `src/pipeline/base.py` | 29 | 1 | **97%** | PASS |
| `src/pipeline/orchestrator.py` | 133 | 7 | **95%** | PASS |
| `src/pipeline/config.py` | 60 | 3 | **95%** | PASS |
| `src/pipeline/fast_evaluation.py` | 60 | 5 | **92%** | PASS |
| `src/pipeline/deep_evaluation.py` | 48 | 5 | **90%** | PASS |
| `src/pipeline/stock_selection.py` | 42 | 5 | **88%** | PASS |
| `src/pipeline/backends/selectors.py` | 60 | 9 | **85%** | PASS |
| `src/pipeline/backends/fast_evaluators.py` | 94 | 19 | **80%** | PASS |
| `src/pipeline/backends/deep_evaluators.py` | 95 | 20 | **79%** | GAP |
| `src/pipeline/data_update.py` | 35 | 13 | **63%** | GAP |
| `src/database.py` | 29 | 17 | **41%** | GAP |
| `src/config.py` | 14 | 9 | **36%** | GAP |
| `src/repository.py` | 190 | 144 | **24%** | GAP |
| `src/app.py` | 1083 | 1083 | **0%** | Streamlit UI |
| `src/finrl_pipeline.py` | 398 | 398 | **0%** | GAP |
| `src/ta_run.py` | 309 | 309 | **0%** | GAP |
| `src/ingestion/pipeline.py` | 262 | 262 | **0%** | GAP |
| `src/ingestion/indicators.py` | 64 | 64 | **0%** | GAP |
| `src/ingestion/symbols.py` | 38 | 38 | **0%** | GAP |
| `src/fetcher/alpha_vantage.py` | 140 | 140 | **0%** | GAP |
| `src/fetcher/yahoo.py` | 21 | 21 | **0%** | GAP |
| `src/fetcher/rate_limiter.py` | 29 | 29 | **0%** | GAP |
| `src/fetcher/base.py` | 10 | 10 | **0%** | GAP |
| `src/fetcher/__init__.py` | 10 | 10 | **0%** | GAP |
| `src/scheduler.py` | 78 | 78 | **0%** | GAP |
| `src/news_cache.py` | 91 | 91 | **0%** | GAP |
| `src/ml_bucket_selector.py` | 90 | 90 | **0%** | GAP |
| `src/display.py` | 24 | 24 | **0%** | GAP |
| `src/main.py` | 93 | 93 | **0%** | GAP |
| `src/full_pipeline.py` | 55 | 55 | **0%** | GAP |

---

## 1. Completely Untested Modules

### 1.1 `repository.py` — StockRepository (16 public methods, CRITICAL)

No tests exist for the central data access layer. Every pipeline step depends on this.

```python
# tests/test_repository.py

import pytest
from datetime import date
from unittest.mock import MagicMock, patch
from repository import StockRepository, ScreenCriteria, StockFilters


class TestStockRepository:
    """Tests for StockRepository using injected test session."""

    def test_find_stock_returns_stock_when_exists(self):
        """find_stock returns Stock object for known symbol."""
        ...

    def test_find_stock_returns_none_for_unknown_symbol(self):
        """find_stock returns None when symbol not in DB."""
        ...

    def test_find_stock_uppercases_symbol(self):
        """find_stock normalizes symbol to uppercase before query."""
        ...

    def test_get_prices_returns_empty_dataframe_for_no_data(self):
        """get_prices returns empty DataFrame when no prices in range."""
        ...

    def test_get_prices_returns_correct_columns(self):
        """get_prices DataFrame has expected OHLCV columns."""
        ...

    def test_get_tech_indicators_expands_json_indicators(self):
        """get_tech_indicators unpacks JSON indicator blob into columns."""
        ...

    def test_screen_stocks_with_all_criteria(self):
        """screen_stocks applies all ScreenCriteria filters."""
        ...

    def test_screen_stocks_with_nullable_criteria_handles_none(self):
        """screen_stocks uses safe defaults when criteria fields are None."""
        ...

    def test_list_stocks_with_status_all(self):
        """list_stocks with status='All' includes both active and inactive."""
        ...

    def test_list_stocks_with_status_active(self):
        """list_stocks filters to active stocks only."""
        ...

    def test_count_summary_returns_correct_totals(self):
        """count_summary dict has total, active, inactive counts."""
        ...

    def test_bulk_set_active_noop_on_empty_list(self):
        """bulk_set_active with empty list returns without DB call."""
        ...

    def test_bulk_set_active_sets_activated_at_for_activation(self):
        """bulk_set_active sets activated_at timestamp when activating."""
        ...

    def test_bulk_set_active_nulls_activated_at_for_deactivation(self):
        """bulk_set_active sets activated_at to None when deactivating."""
        ...

    def test_save_selected_stocks_deletes_previous_then_inserts(self):
        """save_selected_stocks wipes old selections then inserts new ones."""
        ...

    def test_save_selected_stocks_returns_insert_count(self):
        """save_selected_stocks returns number of rows inserted."""
        ...

    def test_save_predict_only_results_sets_predicted_return(self):
        """save_predict_only_results stores predicted_return field."""
        ...

    def test_get_latest_selected_stocks_returns_empty_list_when_no_run(self):
        """get_latest_selected_stocks returns [] when table is empty."""
        ...

    def test_get_latest_selected_stocks_returns_latest_batch_only(self):
        """get_latest_selected_stocks returns only the most recent run."""
        ...

    def test_get_job_runs_respects_limit(self):
        """get_job_runs returns at most `limit` rows."""
        ...

    def test_get_stock_news_filters_by_ticker_and_days(self):
        """get_stock_news returns only recent news for given ticker."""
        ...

    def test_get_insider_transactions_filters_correctly(self):
        """get_insider_transactions filters by ticker and tool_name."""
        ...

    def test_session_closed_after_error_in_query(self):
        """Session is closed in finally block even on query error."""
        ...
```

### 1.2 `fetcher/alpha_vantage.py` — AlphaVantageFetcher (7 methods)

No tests for the primary data source. External API calls must be mocked.

```python
# tests/test_fetcher_alpha_vantage.py

import pytest
import pandas as pd
from datetime import date
from unittest.mock import patch, MagicMock
from fetcher.alpha_vantage import AlphaVantageFetcher, _safe_float, _safe_int, _safe_date


class TestSafeConverters:
    def test_safe_float_returns_float_for_valid_string(self):
        assert _safe_float("3.14") == 3.14

    def test_safe_float_returns_none_for_none(self):
        assert _safe_float(None) is None

    def test_safe_float_returns_none_for_invalid_string(self):
        assert _safe_float("N/A") is None

    def test_safe_int_handles_float_string(self):
        assert _safe_int("3.0") == 3

    def test_safe_date_handles_none_value(self):
        assert _safe_date("None") is None
        assert _safe_date(None) is None

    def test_safe_date_handles_empty_string(self):
        assert _safe_date("") is None


class TestAlphaVantageFetcherGet:
    def test_get_returns_json_on_success(self):
        """_get parses JSON response from API."""
        ...

    def test_get_retries_on_rate_limit_note(self):
        """_get retries with backoff when 'Note' in response."""
        ...

    def test_get_retries_on_timeout(self):
        """_get retries with exponential backoff on Timeout."""
        ...

    def test_get_raises_runtime_error_after_max_retries(self):
        """_get raises RuntimeError after exhausting retries."""
        ...

    def test_get_returns_csv_text_for_csv_datatype(self):
        """_get returns raw text when datatype=csv."""
        ...

    def test_get_raises_on_4xx_http_error(self):
        """_get does not retry on client errors (4xx)."""
        ...

    def test_get_acquires_rate_limiter_before_request(self):
        """_get calls default_limiter.acquire() before HTTP request."""
        ...


class TestAlphaVantageFetcherGetDaily:
    def test_get_daily_returns_empty_df_for_missing_time_series(self):
        """Returns empty DataFrame when API response has no Time Series key."""
        ...

    def test_get_daily_filters_outside_date_range(self):
        """Only rows within [start, end] are included."""
        ...

    def test_get_daily_uses_compact_for_recent_start(self):
        """outputsize=compact when start date within 90 days."""
        ...

    def test_get_daily_uses_full_for_old_start(self):
        """outputsize=full when start date older than 90 days."""
        ...

    def test_get_daily_sorts_by_date(self):
        """Returned DataFrame is sorted ascending by date."""
        ...


class TestAlphaVantageFetcherGetOverview:
    def test_get_overview_returns_empty_dict_when_no_symbol_key(self):
        """Returns {} when API response lacks 'Symbol' key."""
        ...

    def test_get_overview_parses_all_fields_correctly(self):
        """All ~40 fields are extracted with safe converters."""
        ...


class TestAlphaVantageFetcherFinancials:
    def test_get_income_statement_returns_empty_df_for_no_reports(self):
        ...

    def test_get_balance_sheet_drops_rows_without_fiscal_date(self):
        ...

    def test_get_cash_flow_handles_alternate_dividend_field_name(self):
        """Falls back to 'dividendPayout' if 'dividendPayoutCommonStock' missing."""
        ...

    def test_get_earnings_handles_surprise_percentage_variants(self):
        """Surprise % can be None, 'None', empty string, or '12.5%'."""
        ...
```

### 1.3 `fetcher/rate_limiter.py` — TokenBucket

```python
# tests/test_rate_limiter.py

import pytest
import time
from fetcher.rate_limiter import TokenBucket, default_limiter


class TestTokenBucket:
    def test_acquire_returns_immediately_when_tokens_available(self):
        bucket = TokenBucket(capacity=10, refill_rate=100.0)
        # Manually fill to capacity
        bucket._tokens = bucket._capacity
        start = time.monotonic()
        bucket.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Should return near-instantly

    def test_acquire_blocks_when_empty(self):
        bucket = TokenBucket(capacity=1, refill_rate=0.1, max_per_sec=100.0)
        bucket._tokens = 0.0
        start = time.monotonic()
        bucket.acquire()
        elapsed = time.monotonic() - start
        assert elapsed > 0.05  # Should have waited for refill

    def test_acquire_respects_min_spacing(self):
        """Cannot acquire faster than max_per_sec allows."""
        bucket = TokenBucket(capacity=100, refill_rate=100.0, max_per_sec=2.0)
        bucket._tokens = 100.0
        t1 = time.monotonic()
        bucket.acquire()
        t2 = time.monotonic()
        bucket.acquire()
        t3 = time.monotonic()
        gap1 = t2 - t1
        gap2 = t3 - t2
        # Second acquire should have waited at least ~0.5s
        assert gap2 > 0.3

    def test_refill_does_not_exceed_capacity(self):
        """Tokens never exceed capacity even after long idle."""
        bucket = TokenBucket(capacity=5, refill_rate=1000.0)
        time.sleep(0.1)  # Enough to fill many times over
        bucket._refill()
        assert bucket._tokens <= 5

    def test_thread_safety_no_deadlock(self):
        """Multiple threads acquire without deadlock."""
        import threading
        bucket = TokenBucket(capacity=100, refill_rate=100.0)
        bucket._tokens = 100.0
        results = []

        def worker():
            for _ in range(10):
                bucket.acquire()
            results.append(True)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert len(results) == 4
```

### 1.4 `display.py` — Formatting Utilities

```python
# tests/test_display.py

import pytest
import pandas as pd
from display import fmt_market_cap, nan_safe


class TestFmtMarketCap:
    def test_formats_trillions(self):
        assert fmt_market_cap(2_500_000_000_000) == "$2.50T"

    def test_formats_billions(self):
        assert fmt_market_cap(1_200_000_000) == "$1.20B"

    def test_formats_millions(self):
        assert fmt_market_cap(500_000_000) == "$500.0M"

    def test_formats_small_value_with_commas(self):
        assert fmt_market_cap(123456) == "$123,456"

    def test_returns_emdash_for_none(self):
        assert fmt_market_cap(None) == "—"

    def test_returns_emdash_for_nan(self):
        assert fmt_market_cap(float("nan")) == "—"

    def test_returns_emdash_for_non_numeric_string(self):
        assert fmt_market_cap("abc") == "—"

    def test_handles_zero(self):
        assert fmt_market_cap(0) == "$0"


class TestNanSafe:
    def test_returns_emdash_for_none(self):
        fn = nan_safe(str.upper)
        assert fn(None) == "—"

    def test_returns_emdash_for_nan(self):
        fn = nan_safe(float)
        assert fn(float("nan")) == "—"

    def test_applies_function_for_valid_value(self):
        fn = nan_safe(lambda x: x * 2)
        assert fn(5) == 10

    def test_returns_emdash_on_type_error(self):
        fn = nan_safe(int)
        assert fn("not-a-number") == "—"

    def test_chaining_nan_safe_decorators(self):
        @nan_safe
        def double(x):
            return x * 2

        assert double(10) == 20
        assert double(None) == "—"
```

### 1.5 `database.py` — Database Connections

```python
# tests/test_database.py

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.engine import Engine
import database


class TestDatabase:
    def setup_method(self):
        database._url = None
        database._engine = None
        database._SessionFactory = None

    def test_configure_overrides_url_and_resets_caches(self):
        url = "mysql+pymysql://test:pass@localhost/test_db"
        database.configure(url)
        assert database._url == url
        assert database._engine is None
        assert database._SessionFactory is None

    def test_get_engine_creates_engine_with_pool_pre_ping(self):
        database._url = "sqlite:///:memory:"
        engine = database.get_engine()
        assert isinstance(engine, Engine)
        # pool_pre_ping and pool_recycle are set on the engine

    def test_get_engine_reuses_cached_engine(self):
        database._url = "sqlite:///:memory:"
        e1 = database.get_engine()
        e2 = database.get_engine()
        assert e1 is e2

    def test_get_session_returns_valid_session(self):
        database._url = "sqlite:///:memory:"
        session = database.get_session()
        assert session is not None
        session.close()

    def test_init_db_creates_tables(self):
        database._url = "sqlite:///:memory:"
        database.init_db()
        # Verify tables exist by querying
        engine = database.get_engine()
        with engine.connect() as conn:
            result = conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [r[0] for r in result]
        assert "stocks" in tables
```

### 1.6 `config.py` — Configuration Loading

```python
# tests/test_config.py  (separate from test_pipeline_config.py)

import pytest
from unittest.mock import patch
import config


class TestConfig:
    def setup_method(self):
        config._config = None

    def test_load_config_reads_yaml_file(self, tmp_path, monkeypatch):
        import yaml
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump({"key": "value"}))

        # Mock Path to point to our tmp_path
        with patch.object(config.Path, '__init__', return_value=None):
            with patch.object(config.Path, 'parent', create=True) as mock_parent:
                # Tricky to mock — use monkeypatch instead
                ...

    def test_load_config_caches_result(self):
        """Second call returns cached config without re-reading file."""
        ...

    def test_load_config_exits_when_file_missing(self):
        """sys.exit(1) when config.yaml not found."""
        ...
```

### 1.7 `ingestion/pipeline.py` — Data Ingestion Pipeline

```python
# tests/test_ingestion_pipeline.py

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import date, datetime
import pandas as pd
from ingestion.pipeline import (
    run_daily_pipeline, run_bootstrap, _prefetch_stock_dates,
    _fetch_and_store_prices, _upsert_fundamentals, _refresh_snapshots,
    _process_symbol, _needs_full_backfill, _fetch_stock_news,
)

# These tests require database mocking or SQLite in-memory DB.


class TestPrefetchStockDates:
    def test_returns_empty_dicts_for_empty_list(self):
        result = _prefetch_stock_dates([])
        assert result["max_price_dates"] == {}

    def test_returns_max_dates_for_valid_ids(self):
        """Batch query returns correct max dates for each stock_id."""
        ...


class TestFetchAndStorePrices:
    def test_skips_when_start_after_end(self):
        """Returns (0, max_date) when stock already up to date."""
        ...

    def test_inserts_batch_of_prices(self):
        """Inserts prices in batches of 100 with ON DUPLICATE KEY UPDATE."""
        ...

    def test_retries_on_deadlock_error_1213(self):
        """Retries up to 5 times on MySQL deadlock."""
        ...

    def test_reraises_after_deadlock_retries_exhausted(self):
        """Raises after 5 failed deadlock retries."""
        ...


class TestNeedsFullBackfill:
    def test_returns_true_when_no_indicators(self):
        """True when first_indicator_date is None."""
        assert _needs_full_backfill(1, first_indicator_date=None) is True

    def test_returns_false_when_no_prices(self):
        """False when first_price_date is None (no data to backfill)."""
        assert _needs_full_backfill(1, first_indicator_date=date(2020,1,1),
                                    first_price_date=None) is False

    def test_returns_true_when_gap_exceeds_365_days(self):
        assert _needs_full_backfill(1, first_indicator_date=date(2021,1,1),
                                    first_price_date=date(2019,1,1)) is True

    def test_returns_false_when_gap_within_365_days(self):
        assert _needs_full_backfill(1, first_indicator_date=date(2021,1,1),
                                    first_price_date=date(2020,7,1)) is False


class TestFetchStockNews:
    def test_returns_0_on_exception(self):
        """Returns 0 when news fetch fails, does not propagate exception."""
        ...

    def test_fetches_news_via_route_to_vendor(self):
        """Calls route_to_vendor with correct symbol and date range."""
        ...


class TestProcessSymbol:
    def test_captures_error_in_result_dict(self):
        """Error is stored as string in result['error'], not raised."""
        ...

    def test_computes_indicators_when_backfill_needed(self):
        """Calls compute_indicators with since_date=None when backfill needed."""
        ...

    def test_computes_incremental_indicators_otherwise(self):
        """Calls compute_indicators with since_date=new_max_date."""
        ...


class TestRunDailyPipeline:
    def test_creates_pipeline_run_record(self):
        """Creates PipelineRun with status='running' at start."""
        ...

    def test_updates_pipeline_run_on_completion(self):
        """Updates finished_at, symbols_processed, errors_count, status."""
        ...

    def test_sets_status_completed_with_errors_on_failures(self):
        """status='completed_with_errors' when errors_count > 0."""
        ...

    def test_handles_empty_active_stocks(self):
        """Pipeline completes successfully with 0 active stocks."""
        ...


class TestRunBootstrap:
    def test_processes_all_stocks_with_force(self):
        """Calls _upsert_fundamentals with force=True for all stocks."""
        ...

    def test_auto_activates_on_criteria_match(self):
        """Auto-activates stocks matching min_market_cap and exchanges."""
        ...
```

### 1.8 `migrations/run.py` — Migration Runner

```python
# tests/test_migration_runner.py

import pytest
from pathlib import Path
import tempfile
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from migrations.run import MigrationRunner
from models import Base, SchemaMigration


class TestMigrationRunner:
    @pytest.fixture
    def engine(self):
        eng = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(eng)
        return eng

    @pytest.fixture
    def migrations_dir(self):
        d = tempfile.mkdtemp()
        (Path(d) / "001_init.sql").write_text(
            "CREATE TABLE IF NOT EXISTS test_mig (id INT);"
        )
        (Path(d) / "002_add_col.sql").write_text(
            "ALTER TABLE test_mig ADD COLUMN name TEXT;"
        )
        return d

    def test_applied_versions_returns_empty_set_initially(self, engine):
        runner = MigrationRunner(engine, "/tmp")
        assert runner.applied_versions() == set()

    def test_discover_sorts_sql_files(self, migrations_dir, engine):
        runner = MigrationRunner(engine, migrations_dir)
        files = runner.discover()
        assert len(files) == 2
        assert files[0].stem == "001_init"
        assert files[1].stem == "002_add_col"

    def test_run_pending_applies_and_records_migrations(self, migrations_dir, engine):
        runner = MigrationRunner(engine, migrations_dir)
        ran = runner.run_pending()
        assert len(ran) == 2
        assert "001_init" in ran
        assert "002_add_col" in ran

    def test_run_pending_skips_already_applied(self, migrations_dir, engine):
        runner = MigrationRunner(engine, migrations_dir)
        runner.run_pending()
        ran_again = runner.run_pending()
        assert ran_again == []

    def test_run_pending_rolls_back_on_invalid_sql(self, engine):
        """Failed migration does not leave partial state."""
        d = tempfile.mkdtemp()
        (Path(d) / "001_bad.sql").write_text("INVALID SQL SYNTAX!!!;")
        runner = MigrationRunner(engine, d)
        with pytest.raises(Exception):
            runner.run_pending()
        # Verify no migration recorded
        assert "001_bad" not in runner.applied_versions()
```

### 1.9 `news_cache.py` — News DB Cache

```python
# tests/test_news_cache.py

import pytest
from unittest.mock import patch, MagicMock, call
import news_cache


class TestCacheKey:
    def test_key_for_get_news_returns_ticker_start_end(self):
        assert news_cache._key("get_news", ("AAPL",), {}) == ("AAPL", "", "")

    def test_key_for_get_global_news_returns_global_marker(self):
        ticker, _, _ = news_cache._key("get_global_news", ("2024-01-01",), {})
        assert ticker == "__global__"

    def test_key_for_unknown_tool_returns_unknown_marker(self):
        ticker, _, _ = news_cache._key("unknown_tool", (), {})
        assert ticker == "__unknown__"


class TestGetCached:
    def test_returns_none_for_non_cacheable_tool(self):
        assert news_cache.get_cached("some_other_tool", (), {}) is None

    def test_returns_none_on_db_error(self):
        """Returns None (not exception) when DB connection fails."""
        ...

    def test_returns_cached_result_on_hit(self):
        """Returns row.result when matching cache entry exists."""
        ...


class TestSetCached:
    def test_skips_non_cacheable_tools(self):
        """Returns without DB call for non-cacheable tool names."""
        ...

    def test_skips_empty_result(self):
        """Returns without DB call when result is empty string."""
        ...

    def test_skips_none_result(self):
        """Returns without DB call when result is None."""
        ...

    def test_upserts_on_duplicate_key(self):
        """Uses INSERT ... ON DUPLICATE KEY UPDATE."""
        ...


class TestInstall:
    def test_is_idempotent(self):
        """Second call to install() is a no-op."""
        ...

    def test_patches_route_to_vendor(self):
        """After install, route_to_vendor returns cached results."""
        ...

    def test_handles_missing_tradingagents_import(self):
        """Does not crash when tradingagents module is not importable."""
        ...
```

### 1.10 `fetcher/yahoo.py` — YahooFetcher

```python
# tests/test_fetcher_yahoo.py

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from fetcher.yahoo import YahooFetcher


class TestYahooFetcher:
    def test_get_daily_returns_empty_df_when_no_history(self):
        ...

    def test_get_daily_renames_columns_correctly(self):
        """Yahoo column names mapped to standard format."""
        ...

    def test_get_overview_extracts_info_fields(self):
        """Returns dict with expected fundamental fields."""
        ...

    def test_get_listing_raises_not_implemented(self):
        fetcher = YahooFetcher()
        with pytest.raises(NotImplementedError, match="listing"):
            fetcher.get_listing()
```

---

## 2. Error Handling Test Gaps

### 2.1 TokenBucket Infinite Wait

```python
def test_acquire_eventually_returns_even_with_slow_refill(self):
    """acquire should not hang indefinitely."""
    import threading
    bucket = TokenBucket(capacity=0, refill_rate=0.5, max_per_sec=100.0)
    bucket._tokens = 0.0
    result = []
    def timed_acquire():
        try:
            bucket.acquire()
            result.append(True)
        except Exception as e:
            result.append(e)
    t = threading.Thread(target=timed_acquire)
    t.start()
    t.join(timeout=5)
    assert t.is_alive() is False, "acquire() hung for >5 seconds"
    assert result == [True]
```

### 2.2 Database Connection Failure

```python
def test_get_engine_handles_connection_error(self):
    """get_engine propagates SQLAlchemy error on bad URL."""
    database._url = "mysql+pymysql://invalid:pass@nonexistent:3306/db"
    with pytest.raises(Exception):
        database.get_engine()

def test_get_session_fails_gracefully_on_engine_error(self):
    """get_session raises clear error when engine creation fails."""
    ...
```

### 2.3 API Error Propagation

```python
def test_get_daily_handles_non_dict_response(self):
    """get_daily handles case where _get returns a string instead of dict."""
    ...

def test_get_overview_handles_api_error_response(self):
    """get_overview returns {} when API returns error instead of data."""
    ...
```

### 2.4 Deadlock Retry Exhaustion

```python
def test_compute_indicators_raises_after_deadlock_retries(self):
    """After 5 deadlock retries, compute_indicators propagates the error."""
    ...

def test_fetch_and_store_prices_raises_after_deadlock_retries(self):
    """After 5 deadlock retries, _fetch_and_store_prices propagates the error."""
    ...

def test_upsert_fundamentals_raises_after_deadlock_retries(self):
    """After 3 deadlock retries, _upsert_fundamentals propagates the error."""
    ...
```

### 2.5 Missing Import Handling

```python
def test_news_cache_install_survives_missing_tradingagents(self):
    """install() logs warning but does not crash when tradingagents absent."""
    with patch.dict('sys.modules', {'tradingagents': None}):
        news_cache.install()  # Should not raise

def test_fetch_stock_news_returns_zero_on_import_error(self):
    """_fetch_stock_news returns 0 when tradingagents cannot be imported."""
    ...
```

---

## 3. Edge Case Gaps

### 3.1 Empty Data Handling

```python
def test_refresh_symbols_handles_empty_listing_df(self):
    """refresh_symbols returns 0 when fetcher returns empty DataFrame."""
    ...

def test_compute_indicators_returns_zero_for_stock_with_no_prices(self):
    """Returns 0 when daily_prices table has no rows for stock_id."""
    ...

def test_compute_indicators_handles_insufficient_warmup_data(self):
    """When price rows < lookback, compute only available range."""
    ...

def test_save_selected_stocks_handles_empty_record_list(self):
    """Returns 0 when records list is empty."""
    ...

def test_get_prices_handles_stock_with_no_numeric_values(self):
    """All-None columns produce empty DataFrame."""
    ...
```

### 3.2 Date Boundary Cases

```python
def test_get_daily_start_equals_end(self):
    """Single-day range returns one row."""
    ...

def test_get_daily_start_after_end_returns_empty(self):
    """Empty DataFrame when start date > end date."""
    ...
```

### 3.3 Numeric Edge Cases

```python
def test_fmt_market_cap_handles_negative_values(self):
    """Negative market cap should still format or show emdash."""
    ...

def test_compute_indicators_handles_inf_values(self):
    """NaN, inf, and -inf in computed indicators are stored as None."""
    ...

def test_safe_float_handles_scientific_notation(self):
    assert _safe_float("1.5e3") == 1500.0

def test_fit_predict_handles_division_by_zero_in_feature_computation(self):
    """fcf_to_ocf and ocf_ratio handle zero denominators."""
    ...
```

### 3.4 Session Lifecycle

```python
def test_repository_session_closed_on_attribute_error(self):
    """Session is closed even when an AttributeError occurs mid-query."""
    ...

def test_ingestion_session_closed_on_unexpected_error(self):
    """Session is closed in finally block regardless of error type."""
    ...
```

---

## 4. Integration Test Gaps

### 4.1 Repository ↔ Database (Full CRUD)

```python
# tests/test_integration_repository_db.py

import pytest

@pytest.mark.integration
class TestRepositoryDatabaseIntegration:
    """Requires test database. Tests full flow through StockRepository."""

    def test_full_stock_lifecycle(self):
        """Insert → read → update → delete through repository."""
        ...

    def test_screen_and_select_pipeline(self):
        """screen_stocks → save_selected_stocks → get_latest_selected_stocks."""
        ...

    def test_price_data_roundtrip(self):
        """Insert prices → get_prices → verify data integrity."""
        ...

    def test_concurrent_selected_stocks_writes(self):
        """Two concurrent save operations don't corrupt data."""
        ...
```

### 4.2 Fetcher → DB Pipeline

```python
@pytest.mark.integration
class TestFetcherToDbPipeline:
    """Fetch real or mock data and verify it lands in DB correctly."""

    def test_alpha_vantage_daily_to_db(self):
        """Mocked AV response → get_daily → insert into daily_prices."""
        ...

    def test_yahoo_overview_to_db(self):
        """Mocked Yahoo response → get_overview → upsert stock_indicators."""
        ...
```

### 4.3 Migration System

```python
@pytest.mark.integration
class TestMigrationSystem:
    """Run all pending SQL migrations against test DB."""

    def test_all_migrations_apply_cleanly(self):
        """Every .sql file in src/migrations/ runs without error."""
        ...

    def test_migration_idempotency(self):
        """Running migrations twice does not fail."""
        ...

    def test_migration_order_is_correct(self):
        """Migrations apply in correct order (no missing dependencies)."""
        ...
```

### 4.4 News Cache ↔ TradingAgents

```python
@pytest.mark.integration
class TestNewsCacheIntegration:
    """End-to-end cache behavior with real or mocked TradingAgents."""

    def test_cache_miss_triggers_fetch_and_store(self):
        """First call fetches, second call returns cached result."""
        ...

    def test_cache_invalidation_does_not_happen(self):
        """Cached results persist (no TTL expiration yet)."""
        ...
```

### 4.5 MLBucketSelector ↔ FinRL Pipeline

```python
@pytest.mark.integration
class TestMLBucketSelectorIntegration:
    """MLBucketSelector.fit_predict with real or synthetic fundamentals."""

    def test_fit_predict_with_minimal_valid_data(self):
        """Synthetic fundamentals DataFrame produces valid weights."""
        ...

    def test_fit_predict_handles_unmapped_sectors(self):
        """Sectors not in SECTOR_TO_BUCKET are dropped with warning."""
        ...

    def test_fit_predict_with_insufficient_dates_raises(self):
        """ValueError when < 2 distinct datadates."""
        ...

    def test_weight_methods_produce_correct_output(self):
        """equal, ml_score, and inverse_volatility methods all work."""
        ...
```

---

## 5. Priority Recommendations

### Immediate (CRITICAL)

| Priority | Module | Reason |
|----------|--------|--------|
| P0 | `repository.py` | Every pipeline step depends on it; bugs here corrupt all data |
| P0 | `fetcher/alpha_vantage.py` | Primary data source; no error handling coverage for API calls |
| P0 | `database.py` | Connection pool config affects all operations; silent failures possible |

### High

| Priority | Module | Reason |
|----------|--------|--------|
| P1 | `ingestion/pipeline.py` | Complex multi-step pipeline; deadlock retry logic needs tests |
| P1 | `ingestion/indicators.py` | Technical indicator computation; NaN/Inf handling critical |
| P1 | `news_cache.py` | Monkey-patching code fragile; needs import error coverage |

### Medium

| Priority | Module | Reason |
|----------|--------|--------|
| P2 | `fetcher/rate_limiter.py` | Thread safety and fairness important for rate limiting |
| P2 | `display.py` | Simple but used in all UI rendering |
| P2 | `migrations/run.py` | Idempotency critical for deployments |
| P2 | `config.py` | Single point of failure for all config loading |

### Low

| Priority | Module | Reason |
|----------|--------|--------|
| P3 | `fetcher/yahoo.py` | Secondary data source; less critical |
| P3 | `ml_bucket_selector.py` | Hard to test without FinRL dependency; integration test sufficient |
| P3 | `ingestion/symbols.py` | Simple upsert logic; basic coverage needed |

---

## Test Infrastructure Recommendation

### Fixtures needed:

```python
# tests/conftest.py additions

@pytest.fixture
def sqlite_session_factory():
    """In-memory SQLite session factory for all DB tests."""
    ...

@pytest.fixture
def mock_av_response():
    """Fixture returning typical Alpha Vantage JSON responses."""
    ...

@pytest.fixture
def sample_stocks():
    """Pre-populated test stocks: AAPL, MSFT, GOOGL, TSLA."""
    ...
```

### Markers to add:

```ini
# pyproject.toml or pytest.ini
[pytest]
markers =
    smoke: smoke tests — train + predict pipelines with real DB data
    e2e: end-to-end Playwright tests — require running Streamlit server
    unit: pure unit tests — no DB or network
    integration: integration tests — require test DB
    slow: tests that take >2 seconds
```
