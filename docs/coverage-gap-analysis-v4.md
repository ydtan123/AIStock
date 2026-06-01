# AIStock Test Coverage Gap Analysis v4 — with Test Skeletons

**Date:** 2026-05-30
**Baseline:** 28.7% overall (140 passed, 12 failed, 20 errors, 4148 stmts)
**Modules:** 53 total, 27 zero-coverage (excl. `__init__.py`), 16 at 100%

---

## Summary Dashboard

| Tier | Modules | Total Stmts | Gain Target |
|------|---------|-------------|-------------|
| **P0 — Critical** (0%, core logic) | ingestion/pipeline, finrl_runner, ml_bucket_selector, main, full_pipeline, indicators, symbols, ta_run | 1,244 | +30% → 59% |
| **P1 — Partial** (<50%) | repository, scheduler, alpha_vantage, yahoo, config, data_update, news_cache | 561 | +9% → 68% |
| **P2 — Near target** (<80%) | selectors, deep_evaluators, fast_evaluators | 251 | +1% → 69% |
| **UI — Separate track** | 12 ui/pages/*.py, app.py | 1,254 | Playwright required |

**Theoretical ceiling without UI tests: ~69%**

---

## Category 1: Untested Functions & Classes (Zero-Coverage)

### 1.1 `src/ingestion/pipeline.py` — 295 stmts, 0% 🔴 P0

Core data ingestion. 15+ functions, all untested.

**Functions:**
```
_last_trading_date()                    — NYSE calendar utility
_prefetch_stock_dates(stock_ids)        — batch DB query (4 queries)
_fetch_and_store_prices(fetcher, stock) — API fetch + MySQL upsert + deadlock retry
_upsert_fundamentals(fetcher, stock)    — overview data + indicator fields upsert
_refresh_snapshots()                    — bulk REPLACE INTO stock_snapshots
_batch_update_checkpoints(stock_ids)    — batch update pipeline_runs
_needs_full_backfill(first_ind, first_price) — backfill decision logic
_fetch_stock_news(symbol, fetcher)      — Google AI → AV fallback
_fetch_stock_news_av(symbol, fetcher)   — AV news direct
_process_symbol(fetcher, stock, ...)    — per-stock orchestrator
run_daily_pipeline(fetcher, force)      — main daily entry
run_bootstrap(fetcher, auto_activate_criteria) — initial bootstrap
_auto_activate(criteria)                — auto-activation logic
```

**Test skeleton** (`tests/test_ingestion_pipeline.py`):

```python
"""Tests for src/ingestion/pipeline.py — core data ingestion."""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

# ---------------------------------------------------------------------------
# _last_trading_date
# ---------------------------------------------------------------------------
class TestLastTradingDate:
    def test_returns_date_on_trading_day(self):
        """NYSE open on a Tuesday → returns that day."""
        from ingestion.pipeline import _last_trading_date
        result = _last_trading_date()
        assert isinstance(result, date)

    def test_returns_previous_trading_day_on_weekend(self, mocker):
        """Saturday → returns Friday."""
        mocker.patch("ingestion.pipeline.pd.Timestamp")
        from ingestion.pipeline import _last_trading_date
        result = _last_trading_date()
        assert result.weekday() < 5

    def test_fallback_when_calendar_empty(self, mocker):
        """NYSE schedule empty → falls back to weekday check."""


# ---------------------------------------------------------------------------
# _prefetch_stock_dates
# ---------------------------------------------------------------------------
class TestPrefetchStockDates:
    def test_empty_ids_returns_empty_dicts(self):
        from ingestion.pipeline import _prefetch_stock_dates
        result = _prefetch_stock_dates([])
        assert result["max_price_dates"] == {}
        assert result["first_indicator_dates"] == {}
        assert result["first_price_dates"] == {}
        assert result["indicator_last_updated"] == {}

    def test_returns_date_maps_for_valid_ids(self, db_session):
        from ingestion.pipeline import _prefetch_stock_dates
        result = _prefetch_stock_dates([1, 2, 3])
        assert isinstance(result["max_price_dates"], dict)

    def test_closes_session_on_error(self, db_session):
        """Session always closed, even on exception."""


# ---------------------------------------------------------------------------
# _fetch_and_store_prices
# ---------------------------------------------------------------------------
class TestFetchAndStorePrices:
    def test_inserts_new_rows_for_first_fetch(self, db_session, mock_fetcher):
        """No existing prices → fetches from DEFAULT_START, inserts all rows."""
        from ingestion.pipeline import _fetch_and_store_prices
        stock = MagicMock(id=1, symbol="AAPL")
        mock_fetcher.get_daily.return_value = MagicMock(empty=False)
        count, new_max = _fetch_and_store_prices(mock_fetcher, stock)
        assert count > 0

    def test_skips_when_up_to_date(self, db_session, mock_fetcher):
        """max_date equals last trading day → skips, returns 0."""
        from ingestion.pipeline import _fetch_and_store_prices, _last_trading_date
        stock = MagicMock(id=1, symbol="AAPL")
        count, _ = _fetch_and_store_prices(mock_fetcher, stock, max_date=_last_trading_date())
        assert count == 0

    def test_incremental_fetch_resumes_from_max_date(self, db_session, mock_fetcher):
        """Has existing data → fetches from max_date+1."""

    def test_retries_on_deadlock_1213(self, db_session, mock_fetcher):
        """MySQL deadlock (1213) → retries up to 5 times."""

    def test_raises_on_non_deadlock_error(self, db_session, mock_fetcher):
        """Non-1213 exception → propagates immediately."""

    def test_handles_empty_api_response(self, db_session, mock_fetcher):
        """API returns empty DataFrame → returns 0, no insert."""


# ---------------------------------------------------------------------------
# _upsert_fundamentals
# ---------------------------------------------------------------------------
class TestUpsertFundamentals:
    def test_skips_when_fresh(self, db_session, mock_fetcher):
        """indicator_last_updated is < 7 days old → returns False."""
        from ingestion.pipeline import _upsert_fundamentals
        stock = MagicMock(id=1, symbol="AAPL")
        result = _upsert_fundamentals(
            mock_fetcher, stock,
            indicator_last_updated=datetime.utcnow() - timedelta(days=1)
        )
        assert result is False

    def test_upserts_new_data(self, db_session, mock_fetcher):
        """Stale indicator → fetches, upserts, updates Stock metadata."""

    def test_retries_deadlock_on_upsert(self, db_session, mock_fetcher):
        """1213 on upsert → retries 3 times."""

    def test_force_overrides_freshness(self, db_session, mock_fetcher):
        """force=True → fetches even if fresh."""

    def test_handles_empty_api_response(self, db_session, mock_fetcher):
        """API returns None/empty → returns False."""

    def test_rolls_back_on_error(self, db_session, mock_fetcher):
        """Exception during upsert → session.rollback() called, re-raised."""


# ---------------------------------------------------------------------------
# _refresh_snapshots
# ---------------------------------------------------------------------------
class TestRefreshSnapshots:
    def test_refreshes_all_active_stocks(self, db_session):
        from ingestion.pipeline import _refresh_snapshots
        _refresh_snapshots()

    def test_handles_empty_database(self, db_session):
        """No stocks → runs without error."""


# ---------------------------------------------------------------------------
# _needs_full_backfill
# ---------------------------------------------------------------------------
class TestNeedsFullBackfill:
    def test_backfill_needed_when_indicator_before_price(self):
        from ingestion.pipeline import _needs_full_backfill
        assert _needs_full_backfill(date(2020, 1, 1), date(2020, 6, 1))

    def test_backfill_not_needed_when_same_date(self):
        from ingestion.pipeline import _needs_full_backfill
        assert not _needs_full_backfill(date(2020, 1, 1), date(2020, 1, 1))

    def test_backfill_not_needed_when_indicator_after_price(self):
        from ingestion.pipeline import _needs_full_backfill
        assert not _needs_full_backfill(date(2020, 6, 1), date(2020, 1, 1))


# ---------------------------------------------------------------------------
# run_daily_pipeline (integration-style)
# ---------------------------------------------------------------------------
class TestRunDailyPipeline:
    def test_processes_active_stocks(self, db_session, mock_fetcher):
        from ingestion.pipeline import run_daily_pipeline
        summary = run_daily_pipeline(mock_fetcher)
        assert "processed" in summary
        assert "errors" in summary

    def test_records_pipeline_run_on_completion(self, db_session, mock_fetcher):
        """PipelineRun row written with status='completed'."""

    def test_records_pipeline_run_on_failure(self, db_session, mock_fetcher):
        """PipelineRun row written with status='failed' on exception."""

    def test_handles_all_stocks_inactive(self, db_session, mock_fetcher):
        """No active stocks → completes with 0 processed."""

    def test_parallel_worker_respects_max_workers(self, db_session, mock_fetcher):
        """ThreadPoolExecutor workers ≤ MAX_WORKERS."""


# ---------------------------------------------------------------------------
# run_bootstrap
# ---------------------------------------------------------------------------
class TestRunBootstrap:
    def test_fetches_and_activates_all_sp500(self, db_session, mock_fetcher):
        from ingestion.pipeline import run_bootstrap
        summary = run_bootstrap(mock_fetcher)
        assert summary["processed"] > 0

    def test_respects_auto_activate_criteria(self, db_session, mock_fetcher):
        """Only activates stocks matching criteria."""
```

---

### 1.2 `src/finrl_runner.py` — 277 stmts, 0% 🔴 P0

ML pipeline runner extracted from legacy `finrl_pipeline.py`. Used by `app.py` and `selectors.py`.

**Functions:**
```
run_pipeline_and_save_report(cfg_overrides)  — 4-step ML pipeline
  ├─ Step 1: create_data_source(preferred_source)
  ├─ Step 2: get_sp500_components()
  ├─ Step 3: get_fundamental_data()
  └─ Step 4: run ML selection + backtest
_run_simple_backtest(weights, data_source, benchmarks, ...)  — backtesting
```

**Test skeleton** (`tests/test_finrl_runner.py`):

```python
"""Tests for src/finrl_runner.py — ML pipeline runner."""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

@pytest.fixture
def mock_data_source():
    src = MagicMock()
    src.get_sp500_components.return_value = MagicMock(empty=False, __len__=lambda s: 500)
    src.get_fundamental_data.return_value = MagicMock(empty=False)
    return src


class TestRunPipelineAndSaveReport:
    def test_full_pipeline_success(self, tmp_path, mocker, mock_data_source):
        """End-to-end: fetches tickers, fundamentals, runs ML, saves outputs."""
        mocker.patch("finrl_runner.DATA_DIR", tmp_path)
        mocker.patch("finrl_runner.create_data_source", return_value=mock_data_source)
        mock_weights = MagicMock(empty=False)
        mocker.patch("finrl_runner.MLBucketSelector.fit_predict", return_value=mock_weights)
        from finrl_runner import run_pipeline_and_save_report
        result = run_pipeline_and_save_report({"preferred_source": "aistock_db"})
        assert Path(result).exists()

    def test_raises_when_no_tickers(self, mocker, mock_data_source):
        """Empty tickers list → RuntimeError."""
        mock_data_source.get_sp500_components.return_value = MagicMock(empty=True)
        mocker.patch("finrl_runner.create_data_source", return_value=mock_data_source)
        from finrl_runner import run_pipeline_and_save_report
        with pytest.raises(RuntimeError, match="No tickers"):
            run_pipeline_and_save_report({"preferred_source": "aistock_db"})

    def test_raises_when_no_fundamentals(self, mocker, mock_data_source):
        """Empty fundamentals → RuntimeError."""
        mock_data_source.get_fundamental_data.return_value = MagicMock(empty=True)
        mocker.patch("finrl_runner.create_data_source", return_value=mock_data_source)
        from finrl_runner import run_pipeline_and_save_report
        with pytest.raises(RuntimeError, match="No fundamental"):
            run_pipeline_and_save_report({"preferred_source": "aistock_db"})

    def test_custom_benchmarks_passed_to_backtest(self, mocker, mock_data_source):
        """Benchmarks from cfg_overrides flow to backtest."""

    def test_predict_only_mode_skips_backtest(self, mocker, mock_data_source):
        """prediction_mode='predict_only' skips backtest but saves selection."""


class TestRunSimpleBacktest:
    def test_benchmark_values_included_in_result(self):
        """Backtest JSON includes benchmark_values for SPY and QQQ."""

    def test_handles_empty_weights(self):
        """Empty weights DataFrame → graceful handling."""

    def test_benchmark_fetch_failure_non_fatal(self):
        """Benchmark data fetch fails → backtest still completes."""
```

---

### 1.3 `src/ml_bucket_selector.py` — 90 stmts, 0% 🔴 P0

Wrapper around FinRL-Trading's `run_bucket()`. 1 class, 2 methods.

**Test skeleton** (`tests/test_ml_bucket_selector.py`):

```python
"""Tests for src/ml_bucket_selector.py."""
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

@pytest.fixture
def sample_fund_df():
    return pd.DataFrame({
        "tic": ["AAPL", "MSFT", "GOOGL"] * 10,
        "datadate": pd.date_range("2023-01-01", periods=30, freq="QE"),
        "gsector": [45, 45, 45] * 10,
        "y_return": [0.05, 0.03, 0.08] * 10,
        "market_cap": [2.8e12, 2.5e12, 1.8e12] * 10,
    })


class TestMLBucketSelector:
    def test_init_defaults(self):
        from ml_bucket_selector import MLBucketSelector
        sel = MLBucketSelector()
        assert sel.top_quantile == 0.75
        assert sel.test_quarters == 3
        assert sel.weight_method == "equal"

    def test_fit_predict_returns_weights_dataframe(self, sample_fund_df, mocker):
        """Returns DataFrame with date, gvkey, weight columns."""
        mocker.patch("ml_bucket_selector.run_bucket",
                     return_value=pd.DataFrame({"gvkey": [1, 2], "weight": [0.5, 0.5]}))
        from ml_bucket_selector import MLBucketSelector
        sel = MLBucketSelector(top_quantile=0.5, test_quarters=2)
        result = sel.fit_predict(sample_fund_df)
        assert "date" in result.columns
        assert "gvkey" in result.columns
        assert "weight" in result.columns

    def test_empty_fundamentals_returns_empty(self, mocker):
        """Empty DataFrame → empty result."""

    def test_single_sector_handled(self, mocker):
        """Only one sector present → runs single bucket."""

    def test_save_models_dir_serializes_models(self, tmp_path, sample_fund_df, mocker):
        """save_models_dir set → joblib dumps per bucket."""

    def test_equal_weight_method(self):
        """weight_method='equal' → equal weights per selected stock."""

    def test_ml_score_weight_method(self):
        """weight_method='ml_score' → weights proportional to score."""

    def test_inverse_volatility_weight_method(self):
        """weight_method='inverse_volatility' → weights ∝ 1/vol."""
```

---

### 1.4 `src/main.py` — 93 stmts, 0% 🟡 P0

CLI entry point. Argparse-based dispatch.

**Functions:** `cmd_init_db()`, `cmd_bootstrap()`, `_resolve_symbols()`, `_ensure_stock()`, `main()`

**Test skeleton** (`tests/test_main.py`):

```python
"""Tests for src/main.py — CLI entry point."""
import pytest
from unittest.mock import MagicMock, patch

class TestResolveSymbols:
    def test_single_symbol_returns_list(self):
        from main import _resolve_symbols
        assert _resolve_symbols("AAPL") == ["AAPL"]

    def test_comma_separated_splits(self):
        from main import _resolve_symbols
        assert _resolve_symbols("AAPL,MSFT,GOOGL") == ["AAPL", "MSFT", "GOOGL"]

    def test_all_flag_returns_active_symbols(self):
        """--all → fetches active symbols from DB."""

    def test_invalid_symbol_raises(self):
        """Non-existent stock in DB → SystemExit or ValueError."""


class TestCmdInitDb:
    def test_creates_all_tables(self, mocker):
        """Base.metadata.create_all called."""


class TestCmdBootstrap:
    def test_fetches_sp500_and_runs_pipeline(self, mocker):
        """Bootstrap flow: refresh_symbols → run_bootstrap."""


class TestMain:
    def test_init_db_flag(self):
        """--init-db dispatches to cmd_init_db."""

    def test_bootstrap_flag(self):
        """--bootstrap dispatches to cmd_bootstrap."""

    def test_missing_symbol_prints_error(self, capsys):
        """No --symbol or --all → prints usage, exits."""
```

---

### 1.5 `src/full_pipeline.py` — 71 stmts, 0% 🟡 P0

OOP pipeline CLI shim.

**Functions:** `parse_args()`, `_setup_logging()`, `_build_session_factory()`, `main()`

**Test skeleton** (`tests/test_full_pipeline_cli.py`):

```python
"""Tests for src/full_pipeline.py CLI shim."""
import pytest
from unittest.mock import MagicMock, patch

class TestParseArgs:
    def test_defaults(self):
        from full_pipeline import parse_args
        args = parse_args([])
        assert args.resume_from is None
        assert args.run_id is None
        assert args.set == []

    def test_resume_from_parses_step_name(self):
        from full_pipeline import parse_args
        args = parse_args(["--resume-from", "fast_evaluation", "--run-id", "42"])
        assert args.resume_from == "fast_evaluation"
        assert args.run_id == 42

    def test_set_overrides_parsed_as_key_value(self):
        from full_pipeline import parse_args
        args = parse_args([
            "--set", "fast_evaluation.top_n=5",
            "--set", "stock_selection.backend=finrl",
        ])
        assert len(args.set) == 2

    def test_resume_from_missing_run_id_errors(self):
        """--resume-from without --run-id raises argparse error."""


class TestMain:
    def test_runs_all_steps(self, mocker):
        """Full pipeline orchestrator invoked."""

    def test_resume_skips_completed_steps(self, mocker):
        """--resume-from skips earlier steps."""

    def test_logging_setup_includes_file_handler(self, tmp_path, mocker):
        """File handler writes to reports/full_pipeline/<run_id>/pipeline.log."""
```

---

### 1.6 `src/ingestion/indicators.py` — 66 stmts, 0% 🟡 P0

Single function: `compute_indicators(stock_id, since_date)`. 21 pandas_ta indicators.

**Test skeleton** (`tests/test_indicators.py`):

```python
"""Tests for src/ingestion/indicators.py."""
import pytest
import pandas as pd
from datetime import date, timedelta

class TestComputeIndicators:
    def test_computes_all_indicators(self, db_with_price_data):
        """Full history → returns positive count, all columns present."""
        from ingestion.indicators import compute_indicators
        count = compute_indicators(1)
        assert count > 0

    def test_incremental_only_updates_recent(self, db_with_price_data):
        """since_date set → only rows >= since_date written."""
        from ingestion.indicators import compute_indicators
        recent = date.today() - timedelta(days=30)
        count = compute_indicators(1, since_date=recent)
        assert count > 0

    def test_no_price_data_returns_zero(self, db_session):
        """Stock has no daily_prices rows → returns 0."""
        from ingestion.indicators import compute_indicators
        count = compute_indicators(99999)
        assert count == 0

    def test_handles_nan_and_inf_in_output(self, db_with_price_data):
        """NaN/Inf values → stored as NULL in JSON."""

    def test_deadlock_retry_on_insert(self, mocker):
        """MySQL 1213 on batch insert → retries with backoff."""

    def test_warmup_lookback_applied(self):
        """260-day lookback window loaded before since_date."""

    def test_partial_history_returns_partial_count(self, db_with_price_data):
        """Stock has <260 days of data → still computes."""
```

---

### 1.7 `src/ingestion/symbols.py` — 39 stmts, 0% 🟡 P0

Symbol refresh: `_clean(df)`, `refresh_symbols(fetcher)`.

**Test skeleton** (`tests/test_symbols.py`):

```python
"""Tests for src/ingestion/symbols.py."""
import pytest
import pandas as pd

class TestClean:
    def test_normalizes_columns(self):
        from ingestion.symbols import _clean
        df = pd.DataFrame({"symbol": [" AAPL ", " msft "], "name": ["Apple", "MSFT"]})
        result = _clean(df)
        assert result.iloc[0]["symbol"] == "AAPL"
        assert result.iloc[1]["symbol"] == "MSFT"

    def test_drops_rows_without_symbol(self):
        """Empty symbol → row dropped."""

    def test_deduplicates_by_symbol(self):
        """Duplicate symbols → keep first."""


class TestRefreshSymbols:
    def test_inserts_new_symbols(self, db_session, mock_fetcher):
        from ingestion.symbols import refresh_symbols
        mock_fetcher.get_sp500_listings.return_value = pd.DataFrame([...])
        count = refresh_symbols(mock_fetcher)
        assert count > 0

    def test_upserts_existing_symbols(self, db_session, mock_fetcher):
        """Existing ticker → upserts, doesn't duplicate."""

    def test_handles_empty_api_response(self, db_session, mock_fetcher):
        """API returns empty DataFrame → returns 0."""

    def test_deadlock_retry_on_batch_insert(self, db_session, mock_fetcher):
        """1213 → retries with backoff."""
```

---

## Category 2: Missing Edge Cases

### 2.1 `src/repository.py` — 28.6%, 115 missed 🔴 P1

25 methods tested at 28.6%. Tests exist but 20 ERRORs (TypeError on session mock). Missing edge cases:

| Method | Missing Edge Case |
|--------|------------------|
| `find_stock()` | Nonexistent symbol, case-insensitive lookup |
| `find_stocks_batch()` | Empty list, 100+ symbols, mixed existent/nonexistent |
| `get_prices()` | No data in range, start > end, single-day range |
| `get_indicator()` | Stock with no indicator row |
| `save_selected_stocks()` | Empty list, duplicate pipeline_run_id |
| `bulk_set_active()` | IDs that don't exist in DB, empty list, timestamp set |
| `get_job_runs()` | No runs in DB, limit=0, limit > total |
| `screen_stocks()` | No matching criteria → empty, all criteria set |
| `get_sectors()` | All stocks inactive, empty DB |
| `count_summary()` | Empty database, all inactive |

**Test skeleton additions** (`tests/test_repository_edge_cases.py`):

```python
"""Edge case tests for StockRepository."""
import pytest
from datetime import date

class TestFindStockEdgeCases:
    def test_nonexistent_symbol_returns_none(self, repo, db_session):
        assert repo.find_stock("ZZZXXX") is None

    def test_lowercase_input_normalized(self, repo, db_session):
        """'aapl' → finds 'AAPL'."""

    def test_whitespace_in_symbol_handled(self, repo):
        """' AAPL ' → strip + upper."""


class TestFindStocksBatchEdgeCases:
    def test_empty_list_returns_empty_dict(self, repo):
        assert repo.find_stocks_batch([]) == {}

    def test_mixed_existing_and_nonexistent(self, repo, db_session):
        """['AAPL', 'ZZZXXX'] → returns only AAPL."""

    def test_large_batch_no_performance_issue(self, repo, db_session):
        """500 symbols → single query, under 100ms."""


class TestGetPricesEdgeCases:
    def test_no_data_in_range_returns_empty_df(self, repo, db_session):
        df = repo.get_prices(1, date(1900, 1, 1), date(1900, 12, 31))
        assert df.empty

    def test_start_after_end_returns_empty(self, repo):
        df = repo.get_prices(1, date(2025, 1, 1), date(2020, 1, 1))
        assert df.empty

    def test_single_day_range(self, repo, db_session):
        """Start == end → one row or empty."""


class TestScreenStocksEdgeCases:
    def test_no_criteria_matches(self, repo, db_session):
        """min_market_cap=1e15 → empty."""
        from repository import ScreenCriteria
        result = repo.screen_stocks(ScreenCriteria(min_market_cap=1e15))
        assert len(result) == 0

    def test_all_criteria_set(self, repo, db_session):
        """Every filter active → no crash."""

    def test_null_criteria_fields_ignored(self, repo, db_session):
        """min_roe=None → not filtered."""


class TestCountSummaryEdgeCases:
    def test_empty_database_returns_zeros(self, repo):
        summary = repo.count_summary()
        assert summary["total"] == 0
        assert summary["active"] == 0
        assert summary["inactive"] == 0

    def test_all_inactive(self, repo, db_session):
        """All stocks is_active=False → active=0."""


class TestBulkSetActiveEdgeCases:
    def test_empty_ids_noop(self, repo):
        repo.bulk_set_active([])

    def test_nonexistent_ids_noop(self, repo):
        repo.bulk_set_active([99999, 99998])

    def test_timestamp_set_on_activation(self, repo, db_session):
        """Stock activated → last_active timestamp updated."""


class TestSaveSelectedStocksEdgeCases:
    def test_empty_list_with_pipeline_run_id(self, repo, db_session):
        repo.save_selected_stocks([], pipeline_run_id=1, backend="test")

    def test_duplicate_symbols_deduplicated(self, repo, db_session):
        """Same symbol twice → one row."""
```

---

### 2.2 `src/news_cache.py` — 53.8%, 42 missed 🟡 P1

Cache layer for TradingAgents news. Missing: global_news, insider transactions, error paths.

**Test skeleton additions**:

```python
class TestKey:
    def test_get_news_extracts_ticker_dates(self):
        from news_cache import _key
        ticker, start, end = _key("get_news", ("AAPL", "2024-01-01", "2024-01-07"), {})
        assert ticker == "AAPL"
        assert start == "2024-01-01"

    def test_get_global_news_uses_sentinel(self):
        from news_cache import _key
        ticker, start, end = _key("get_global_news", ("2024-01-01", 7, 5), {})
        assert ticker == "__global__"

    def test_get_insider_transactions(self):
        from news_cache import _key
        ticker, _, _ = _key("get_insider_transactions", ("AAPL",), {})
        assert ticker == "AAPL"

    def test_kwargs_fallback(self):
        """Args empty → kwargs used."""
        from news_cache import _key
        ticker, _, _ = _key("get_news", (), {"ticker": "MSFT"})
        assert ticker == "MSFT"


class TestGetCached:
    def test_non_cacheable_tool_returns_none(self):
        from news_cache import get_cached
        assert get_cached("get_stock_price", (), {}) is None

    def test_cache_miss_returns_none(self, db_session):
        from news_cache import get_cached
        assert get_cached("get_news", ("ZZZZ", "2020-01-01", "2020-01-07"), {}) is None

    def test_db_error_returns_none_not_raise(self, mocker):
        """SQL error → logs warning, returns None."""


class TestSetCached:
    def test_non_cacheable_skipped(self, db_session):
        from news_cache import set_cached
        set_cached("get_stock_price", (), {}, "result")

    def test_empty_result_skipped(self, db_session):
        from news_cache import set_cached
        set_cached("get_news", ("AAPL",), {}, "   ")

    def test_upsert_same_key(self, db_session):
        """Same ticker+dates → UPDATE not INSERT."""


class TestInstall:
    def test_idempotent(self, mocker):
        """Second install() → no-op."""
        from news_cache import install
        import news_cache as nc
        nc._INSTALLED = True
        install()

    def test_tradingagents_not_importable(self, mocker):
        """ImportError → logs warning, returns."""
```

---

## Category 3: Missing Error Handling Tests

### 3.1 Global Error Handler Audit

65 exception handlers found. Critical gaps:

| File | Handler lines | Tested? |
|------|--------------|---------|
| `ingestion/pipeline.py` | 14 try/except blocks, 5 retry loops | ❌ None |
| `repository.py` | `_with_session` finally block | ❌ Not tested |
| `news_cache.py` | get_cached / set_cached catch-all | ❌ Not tested |
| `scheduler.py` | job_daily_pipeline / job_refresh_symbols try/finally | ❌ 6 FAILED |
| `fetcher/alpha_vantage.py` | API error handling, rate limits | ❌ Only 18.8% |
| `finrl_runner.py` | RuntimeError on empty data | ❌ Not tested |
| `ingestion/indicators.py` | 5-attempt deadlock retry | ❌ Not tested |

### 3.2 Deadlock Retry Pattern (repeated in 4 places)

Pattern: `INSERT ... ON DUPLICATE KEY UPDATE` retry on MySQL error 1213. Used in:
- `_fetch_and_store_prices` (5 attempts)
- `_upsert_fundamentals` (3 attempts)
- `compute_indicators` (5 attempts)
- `refresh_symbols` (inside symbols.py)

**Test skeleton** (`tests/test_deadlock_retry.py`):

```python
"""Consolidated deadlock retry behavior tests."""
import pytest

class TestDeadlockRetry:
    """Verify 1213 retry pattern correct across all consumers."""

    def test_retries_on_1213_then_succeeds(self):
        """Fails with 1213 twice, succeeds on 3rd attempt."""

    def test_gives_up_after_max_attempts(self):
        """1213 on every attempt → re-raises after max."""

    def test_does_not_retry_other_errors(self):
        """Non-1213 error → re-raises immediately, no retry."""

    def test_exponential_backoff_between_attempts(self):
        """Sleep duration increases with attempt number."""

    def test_jitter_added_to_backoff(self):
        """random.uniform() called for jitter."""
```

### 3.3 Configuration Loading Failure

`load_config()` called at module level in `pipeline.py` (line 51). If `config.yaml` missing or malformed → import crash.

**Test skeleton**:

```python
class TestConfigLoadingFailure:
    def test_missing_config_yaml_graceful_error(self):
        """config.yaml absent → clear error message, not traceback dump."""

    def test_malformed_yaml_graceful_error(self):
        """Invalid YAML → YAMLError with file path in message."""

    def test_missing_required_keys(self):
        """database.url missing → KeyError with hint."""
```

---

## Category 4: Integration Test Gaps

### 4.1 DB Session Lifecycle (Blocking 20 ERRORs)

All `repository.py` tests ERROR because `_get_session()` returns real session. Need test DB fixture.

**Test skeleton** (`tests/conftest.py` additions):

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

@pytest.fixture(scope="function")
def test_db_session():
    """SQLite in-memory session with all tables created."""
    from models import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()

@pytest.fixture
def repo(test_db_session):
    """StockRepository with test session injected."""
    from repository import StockRepository
    class TestRepo(StockRepository):
        def _get_session(self):
            return test_db_session
    return TestRepo()
```

### 4.2 Pipeline Step Integration

No test runs the full 4-step OOP pipeline with mocked backends.

**Test skeleton** (`tests/test_pipeline_integration.py`):

```python
class TestFullPipelineIntegration:
    def test_all_steps_run_in_order(self, mock_backends):
        """data_update → stock_selection → fast_evaluation → deep_evaluation."""

    def test_stops_on_first_failure(self, mock_backends):
        """Step 2 fails → steps 3+4 not executed."""

    def test_resume_skips_completed_steps(self, mock_backends, db_session):
        """--resume-from deep_evaluation → runs only step 4."""

    def test_run_id_written_to_all_reports(self, mock_backends, tmp_path):
        """All step reports reference same pipeline_run_id."""

    def test_config_override_flows_to_backend(self, mock_backends):
        """--set fast_evaluation.top_n=3 → backend receives top_n=3."""

    def test_large_symbol_set_performance(self, mock_backends):
        """500 symbols → completes under 30s with mocked backends."""
```

### 4.3 Data Update → ML Pipeline Chain

Data ingestion produces data that `finrl_runner` consumes.

**Test skeleton**:

```python
class TestDataToMLChain:
    def test_ingested_price_data_usable_by_ml(self, test_db, mock_fetcher):
        """Run ingestion → ML pipeline reads from same DB."""

    def test_freshness_check_skips_redundant_fetch(self, test_db):
        """Ingestion skips up-to-date stocks → ML gets cached data."""
```

---

## Category 5: Fix Existing Test Failures 🔴

### 5.1 `test_repository.py` — 20 ERRORs

**Root cause:** `_get_session()` returns real session. Tests need in-memory SQLite fixture.
**Fix:** Add `conftest.py` fixture as shown in Section 4.1.

### 5.2 `test_scheduler.py` — 6 FAILED

**Likely root cause:** Tests try to create real `ScheduledJobRun` rows without fixture or mock.
**Fix:** Mock `get_session()` in tests.

### 5.3 `test_database.py` — 1 FAILED

**Likely root cause:** `test_creates_all_tables_without_error` connects to real DB.
**Fix:** Use SQLite in-memory for this test.

---

## Priority Work Plan

| Sprint | Scope | New Tests | Fixes | Coverage Gain |
|--------|-------|-----------|-------|---------------|
| **Sprint 0: Fix failures** | repo (20 err), scheduler (6 fail), database (1 fail) | 0 | 27 | 29% → 34%* |
| **Sprint 1: Ingestion core** | pipeline.py (14), indicators.py (7), symbols.py (6) | 27 | — | 34% → 43% |
| **Sprint 2: ML runner** | finrl_runner.py (10), ml_bucket_selector.py (8) | 18 | — | 43% → 49% |
| **Sprint 3: Repository** | repository edge cases (15), news_cache (10) | 25 | — | 49% → 55% |
| **Sprint 4: Fetchers + CLI** | alpha_vantage (12), yahoo (6), main.py (10), full_pipeline.py (8) | 36 | — | 55% → 62% |
| **Sprint 5: Integration** | pipeline integration (8), E2E chain (5) | 13 | — | 62% → 65% |

_*Gain from restored tests that were ERRORing, not new coverage._

**Target without UI tests: 65%** (up from 29%)

---

## Files NOT Worth Testing (Rationale)

| File | Reason |
|------|--------|
| `src/app.py` | Streamlit app shell, pure UI routing. Needs Playwright, not unit tests. |
| `src/ui/pages/*.py` (12 files) | Streamlit page functions. Visual regression > unit tests. |
| `src/ta_run.py` | Standalone tech analysis script. Likely one-off utility. |
| `src/logging_config.py` | 5 lines, trivial `dictConfig`. |
| `src/display.py` | Already 100% covered. |
| `src/migrations/run.py` | Already 100% covered. |
| `src/fetcher/rate_limiter.py` | Already 100% covered. |

---

## Appendix: Running Commands

```bash
# Full coverage run
PYTHONPATH=src python -m pytest tests/ \
  --cov=src --cov-report=term-missing --cov-report=json -v

# Fix failures first
PYTHONPATH=src python -m pytest tests/test_repository.py tests/test_scheduler.py -v

# Then run new tests
PYTHONPATH=src python -m pytest \
  tests/test_ingestion_pipeline.py \
  tests/test_finrl_runner.py \
  tests/test_ml_bucket_selector.py \
  tests/test_indicators.py \
  tests/test_symbols.py \
  tests/test_main.py \
  tests/test_full_pipeline_cli.py \
  tests/test_news_cache.py \
  tests/test_repository_edge_cases.py \
  tests/test_deadlock_retry.py \
  tests/test_pipeline_integration.py -v
```
