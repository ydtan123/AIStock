# AIStock Test Coverage Gap Analysis — 2026-05-31

**Overall: 29.67%** (1,267 / 4,270 lines covered)
**Branches: 0/0** (branch coverage not tracked)
**Missing: 3,003 lines**

---

## Summary by Severity

| Tier | Files | Missing Lines | Priority |
|------|-------|---------------|----------|
| 🔴 **0% coverage** | 22 files | 2,250+ | CRITICAL |
| 🟠 **<50% coverage** | 4 files | 202 | HIGH |
| 🟡 **50-80% coverage** | 2 files | 60 | MEDIUM |
| 🟢 **80%+ coverage** | 10 files | 19 | LOW (near-target) |
| ✅ **100% coverage** | 5 files | 0 | DONE |

---

## 🔴 CRITICAL — 0% Coverage (Must Fix First)

### 1. `src/ingestion/pipeline.py` — 318 lines, 0%

**Untested functions:**
- `_last_trading_date()` — NYSE calendar lookup
- `_fetch_stock_news(symbol, fetcher)` — multi-path news fetch with fallback
- `_fetch_and_store_prices(fetcher, stock, max_date)` — OHLCV ingestion
- `_upsert_fundamentals(fetcher, stock, force, ...)` — fundamentals upsert
- `_process_symbol(fetcher, stock, force, prefetch, refresh_days)` — per-stock orchestration
- `run_daily_pipeline(fetcher, force, symbols)` — daily pipeline entry
- `run_bootstrap(fetcher, auto_activate_criteria)` — initial setup
- `_auto_activate(criteria)` — auto-activation filter
- `_needs_full_backfill(first_indicator_date, first_price_date)` — backfill detection
- `_batch_update_checkpoints(session, stocks)` — pre-fetch query optimization
- `_refresh_snapshots()` — snapshot recomputation

**Edge cases not covered:**
- Empty symbol list → no-op
- API rate limit during news fetch → fallback to Alpha Vantage
- Google Gemini rate limit flag → permanent fallback
- Stock with no price data yet → skip
- ThreadPoolExecutor error in one worker → others continue
- MySQL deadlock on concurrent upserts → retry logic
- Market holiday → `_last_trading_date()` fallback

**Error handling gaps:**
- Network timeout during `_fetch_and_store_prices`
- Corrupt OHLCV data (NaN, inf)
- Database connection lost mid-pipeline
- `compute_indicators()` raises on malformed data
- Duplicate key violation on concurrent insert

<details>
<summary><b>Test skeletons</b></summary>

```python
# tests/test_ingestion_pipeline.py
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, datetime

from ingestion.pipeline import (
    _last_trading_date, _fetch_stock_news, _fetch_and_store_prices,
    _upsert_fundamentals, _process_symbol, run_daily_pipeline,
    run_bootstrap, _auto_activate, _needs_full_backfill,
    _batch_update_checkpoints, _refresh_snapshots,
)

# --- _last_trading_date ---
def test_last_trading_date_weekday_returns_previous_session():
    """NYSE calendar returns prior trading day on a weekday."""

def test_last_trading_date_weekend_falls_back_to_friday():
    """Saturday/Sunday → fallback to Friday via simple weekday check."""

def test_last_trading_date_empty_schedule_uses_weekday_fallback():
    """When NYSE calendar returns no sessions, use day-of-week fallback."""

# --- _needs_full_backfill ---
def test_needs_full_backfill_no_indicator_date_returns_true():
    """first_indicator_date is None → needs full backfill."""

def test_needs_full_backfill_no_price_date_returns_true():
    """first_price_date is None → needs full backfill."""

def test_needs_full_backfill_both_present_returns_false():
    """Both dates exist → no full backfill needed."""

# --- _auto_activate ---
def test_auto_activate_filters_by_market_cap(session_mock):
    """Only stocks above min_market_cap get activated."""

def test_auto_activate_filters_by_exchange(session_mock):
    """Only stocks on configured exchanges get activated."""

def test_auto_activate_no_criteria_noop(session_mock):
    """Empty criteria dict → no stocks activated."""

# --- _fetch_stock_news ---
def test_fetch_stock_news_primary_path_returns_count(session_mock):
    """TradingAgents → Google Gemini path succeeds, returns news count."""

def test_fetch_stock_news_falls_back_to_alpha_vantage():
    """When Google Gemini rate-limited, fallback to Alpha Vantage fetcher."""

def test_fetch_stock_news_both_paths_fail_returns_zero():
    """Both primary and fallback fail → returns 0."""

def test_fetch_stock_news_rate_limit_flag_set():
    """When Gemini returns rate-limit error, _google_news_rate_limited = True."""

# --- _fetch_and_store_prices ---
def test_fetch_and_store_prices_new_data_inserts_rows(session_mock, fetcher_mock):
    """Fetcher returns new dates → rows inserted, returns (count, max_date)."""

def test_fetch_and_store_prices_no_new_data_skips():
    """All dates already in DB → returns (0, None)."""

def test_fetch_and_store_prices_empty_api_response():
    """Fetcher returns empty DataFrame → returns (0, None)."""

def test_fetch_and_store_prices_handles_dividend_adjustment():
    """Stock with dividend/split → adjusted_close used correctly."""

def test_fetch_and_store_prices_invalid_date_skipped():
    """Row with malformed date → skipped, others inserted."""

# --- _upsert_fundamentals ---
def test_upsert_fundamentals_new_stock_inserts(session_mock, fetcher_mock):
    """No existing indicator → INSERT new row."""

def test_upsert_fundamentals_existing_stock_updates(session_mock, fetcher_mock):
    """Existing indicator within refresh window → UPDATE."""

def test_upsert_fundamentals_within_refresh_days_skips(session_mock, fetcher_mock):
    """Last updated < refresh_days ago → skip, returns False."""

def test_upsert_fundamentals_api_returns_empty_handles_gracefully():
    """OVERVIEW returns {} → no crash, returns False."""

# --- _process_symbol ---
def test_process_symbol_happy_path(session_mock, fetcher_mock):
    """Prices + fundamentals + indicators + news all succeed."""

def test_process_symbol_price_fetch_fails_others_continue(session_mock, fetcher_mock):
    """Price fetch raises → error recorded, fundamentals still attempted."""

def test_process_symbol_full_backfill_when_no_indicators():
    """No prior indicators → compute_indicators(since_date=None)."""

def test_process_symbol_incremental_backfill_when_prices_new():
    """New prices but existing indicators → compute_indicators(since_date=new_max)."""

def test_process_symbol_skips_indicators_when_no_new_prices():
    """No new prices and indicators exist → skip indicator computation."""

# --- run_daily_pipeline ---
def test_run_daily_pipeline_all_symbols(session_mock, fetcher_mock):
    """Default: process all active stocks, return summary with counts."""

def test_run_daily_pipeline_filtered_symbols(session_mock, fetcher_mock):
    """--symbol AAPL MSFT → only those processed."""

def test_run_daily_pipeline_records_pipeline_run(session_mock, fetcher_mock):
    """PipelineRun row created with started_at, finished_at, status."""

def test_run_daily_pipeline_one_stock_fails_others_continue(session_mock):
    """One _process_symbol raises → error count incremented, others proceed."""

def test_run_daily_pipeline_updates_checkpoints(session_mock, fetcher_mock):
    """Calls _batch_update_checkpoints for N+1 query optimization."""

# --- run_bootstrap ---
def test_run_bootstrap_fetches_all_stocks(session_mock, fetcher_mock):
    """OVERVIEW fetched for every stock in DB."""

def test_run_bootstrap_with_auto_activate(session_mock, fetcher_mock):
    """After bootstrap, auto_activate called with criteria."""

def test_run_bootstrap_one_stock_fails_increments_errors(session_mock):
    """Exception in one stock → error count incremented, others continue."""
```
</details>

---

### 2. `src/finrl_runner.py` — 277 lines, 0%

**Untested functions:**
- `run_pipeline_and_save_report(cfg_overrides)` — full ML pipeline + backtest
- `run_predict_only(cfg_overrides)` — predict without backtest
- `_equal_weight_fallback()` — fallback when ML fails
- `_run_simple_backtest(weights_df, cfg, benchmarks)` — backtest computation
- `_compute_metrics(portfolio_values, benchmark_values)` — Sharpe, max drawdown
- `_build_selection_summary(weights_df, bt_result)` — report generation

**Edge cases not covered:**
- Empty prediction result → fallback to equal weight
- Single stock in bucket → no prediction error
- All NaN features → fillna(0) fallback
- Benchmark data missing → skip benchmark comparison
- `saved_models/` directory empty → raise or fallback

<details>
<summary><b>Test skeletons</b></summary>

```python
# tests/test_finrl_runner.py
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from finrl_runner import (
    run_pipeline_and_save_report, run_predict_only,
    _equal_weight_fallback, _run_simple_backtest,
    _compute_metrics, _build_selection_summary,
)

# --- run_predict_only ---
def test_predict_only_empty_result_falls_back_to_equal_weight(session_mock):
    """ML returns 0 stocks → equal_weight_fallback used."""

def test_predict_only_bucket_empty_skipped():
    """Bucket with no stocks → log warning, continue to next bucket."""

def test_predict_only_missing_feature_cols_filled_with_zero():
    """Feature column not in DataFrame → filled with 0.0."""

def test_predict_only_nan_median_imputation():
    """NaN features → imputed with column median."""

# --- run_pipeline_and_save_report ---
def test_run_pipeline_full_flow_saves_artifacts(tmp_path):
    """All 4 steps complete → report + weights + backtest saved."""

def test_run_pipeline_backtest_fails_logs_warning():
    """Backtest raises → warning logged, pipeline continues."""

def test_run_pipeline_no_models_dir_creates():
    """saved_models/ dir missing → created automatically."""

# --- _equal_weight_fallback ---
def test_equal_weight_fallback_returns_equal_weights():
    """N stocks → each weight = 1/N."""

# --- _compute_metrics ---
def test_compute_metrics_positive_returns():
    """Upward portfolio → positive Sharpe, positive total return."""

def test_compute_metrics_negative_returns():
    """Downward portfolio → negative Sharpe, max drawdown > 0."""

def test_compute_metrics_zero_volatility():
    """Flat portfolio → Sharpe handled gracefully."""

def test_compute_metrics_empty_benchmark_skipped():
    """No benchmark data → metrics omit benchmark comparison."""

# --- _run_simple_backtest ---
def test_run_simple_backtest_quarterly_rebalance():
    """Rebalance frequency Q → trades executed quarterly."""

def test_run_simple_backtest_initial_capital_applied():
    """Config initial_capital → portfolio starts at that value."""
```
</details>

---

### 3. `src/app.py` — 219 lines, 0%

**Untested:**
- `PageContext`, `_QueueHandler`, `_StdoutToQueue` classes
- `_pipeline_thread_target()`, `_predict_only_thread_target()`
- `display_quick_stats()`, `page_stock_data()`, `_build_ctx()`
- `sidebar_nav()`, `render_page_content()`, `main()`

**Edge cases:** No active stocks → empty quick stats; pipeline thread crashes → error in UI; queue full → backpressure.

<details>
<summary><b>Test skeletons</b></summary>

```python
# tests/test_app.py
import pytest
from unittest.mock import patch, MagicMock
from app import (
    PageContext, _QueueHandler, _StdoutToQueue,
    _pipeline_thread_target, _predict_only_thread_target,
    display_quick_stats, _build_ctx, sidebar_nav,
    render_page_content, main,
)

def test_page_context_init_defaults():
    """Default initialization sets required attributes."""

def test_queue_handler_emit_enqueues_record():
    """LogRecord emitted → put on queue."""

def test_stdout_to_queue_write_enqueues():
    """write('hello') → 'hello' put on queue."""

@patch("app.StockRepository")
def test_display_quick_stats_no_stocks(repo_mock):
    """count_summary returns 0 → displays 'No stocks tracked'."""

@patch("app.StockRepository")
def test_display_quick_stats_with_data(repo_mock):
    """count_summary returns counts → displays metric cards."""

def test_render_page_content_unknown_page_shows_error():
    """Unknown page name → st.error() called."""

def test_render_page_content_dispatches_to_correct_page():
    """page_name='overview' → overview.render() called."""

@patch("streamlit.set_page_config")
@patch("app.sidebar_nav")
@patch("app.render_page_content")
def test_main_flow(render_mock, sidebar_mock, config_mock):
    """main() sets page config → sidebar → render content."""
```
</details>

---

### 4. `src/ml_bucket_selector.py` — 90 lines, 0%

**Untested:** `MLBucketSelector.__init__()`, `MLBucketSelector.fit_predict()`

**Edge cases:** Empty fund_df → error; single stock in bucket → equal weight; all NaN features; all negative predictions; `inverse_volatility` with zero vol.

<details>
<summary><b>Test skeletons</b></summary>

```python
# tests/test_ml_bucket_selector.py
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch

from ml_bucket_selector import MLBucketSelector

@pytest.fixture
def sample_fund_df():
    return pd.DataFrame({
        "tic": ["AAPL", "MSFT", "GOOG", "JPM", "BAC"],
        "datadate": ["2024-01-01"] * 5,
        "sector": ["Technology", "Technology", "Technology", "Financial", "Financial"],
        "feature1": [1.0, 2.0, 3.0, 4.0, 5.0],
        "feature2": [10.0, 20.0, 30.0, 40.0, 50.0],
    })

def test_init_default_values():
    s = MLBucketSelector()
    assert s.top_quantile == 0.75
    assert s.weight_method == "equal"

def test_init_custom_values():
    s = MLBucketSelector(top_quantile=0.5, weight_method="inverse_volatility")
    assert s.top_quantile == 0.5

@patch("ml_bucket_selector.run_bucket_selection")
def test_fit_predict_happy_path(mock_run, sample_fund_df):
    mock_run.return_value = pd.DataFrame({
        "tic": ["AAPL", "MSFT"], "weight": [0.6, 0.4],
        "bucket": ["Technology", "Technology"],
    })
    result = MLBucketSelector().fit_predict(sample_fund_df)
    assert len(result) == 2
    assert "weight" in result.columns

def test_fit_predict_empty_df_raises():
    """Empty DataFrame → ValueError."""

def test_fit_predict_missing_sector_column_raises():
    """No 'sector' column → KeyError."""

@patch("ml_bucket_selector.run_bucket_selection")
def test_fit_predict_inverse_volatility_weight_method(mock_run, sample_fund_df):
    mock_run.return_value = pd.DataFrame({
        "tic": ["AAPL"], "weight": [1.0], "bucket": ["Technology"],
    })
    s = MLBucketSelector(weight_method="inverse_volatility")
    result = s.fit_predict(sample_fund_df)
    assert abs(result["weight"].sum() - 1.0) < 0.01

@patch("ml_bucket_selector.run_bucket_selection")
def test_fit_predict_all_negative_predictions_still_weights(mock_run, sample_fund_df):
    mock_run.return_value = pd.DataFrame({
        "tic": ["AAPL", "MSFT"], "weight": [0.5, 0.5],
        "bucket": ["Technology", "Technology"],
    })
    MLBucketSelector().fit_predict(sample_fund_df)  # should not raise
```
</details>

---

### 5. `src/main.py` — 93 lines, 0%

**Untested:** `cmd_init_db()`, `cmd_bootstrap()`, `_resolve_symbols()`, `_ensure_stock()`, `cmd_run()`, `main()`

<details>
<summary><b>Test skeletons</b></summary>

```python
# tests/test_main.py
import pytest
from unittest.mock import patch, MagicMock
from main import (
    cmd_init_db, cmd_bootstrap, _resolve_symbols,
    _ensure_stock, cmd_run, main,
)

def test_resolve_symbols_space_separated():
    args = MagicMock(symbol=["AAPL", "MSFT"])
    assert _resolve_symbols(args) == ["AAPL", "MSFT"]

def test_resolve_symbols_comma_separated():
    args = MagicMock(symbol=["AAPL,MSFT,GOOG"])
    assert _resolve_symbols(args) == ["AAPL", "MSFT", "GOOG"]

def test_resolve_symbols_mixed():
    args = MagicMock(symbol=["AAPL,MSFT", "GOOG"])
    assert _resolve_symbols(args) == ["AAPL", "MSFT", "GOOG"]

def test_resolve_symbols_empty_returns_empty_list():
    args = MagicMock(symbol=None)
    assert _resolve_symbols(args) == []

@patch("main.init_db")
def test_cmd_init_db_calls_init_db(init_db_mock):
    cmd_init_db(MagicMock())
    init_db_mock.assert_called_once()

@patch("main.get_session")
def test_ensure_stock_existing_active(session_mock):
    """Stock exists and is_active → returns stock."""

@patch("main.get_session")
def test_ensure_stock_inactive_no_force_exits(session_mock):
    """Stock inactive, no --force → sys.exit(1)."""

@patch("main.get_session")
def test_ensure_stock_not_in_db_creates(session_mock):
    """Stock not found → fetched from listing, inserted."""

@patch("main.load_config")
@patch("main.create_fetcher")
@patch("main.run_daily_pipeline")
def test_cmd_run_all_stocks(pipeline_mock, fetcher_mock, config_mock):
    """No --symbol → run daily pipeline for all active stocks."""

@patch("main.load_config")
@patch("main.create_fetcher")
def test_cmd_run_single_symbol(fetcher_mock, config_mock):
    """--symbol AAPL → process single stock."""
```
</details>

---

### 6. `src/ingestion/indicators.py` — 66 lines, 0%

**Untested:** `compute_indicators(stock_id, since_date)`

<details>
<summary><b>Test skeletons</b></summary>

```python
# tests/test_ingestion_indicators.py
import pytest
from unittest.mock import patch
from ingestion.indicators import compute_indicators

@patch("ingestion.indicators.get_engine")
def test_compute_indicators_happy_path(engine_mock):
    """OHLCV data available → returns positive row count."""

@patch("ingestion.indicators.get_engine")
def test_compute_indicators_no_price_data_returns_zero(engine_mock):
    """No rows for stock_id → returns 0."""

@patch("ingestion.indicators.get_engine")
def test_compute_indicators_with_since_date_loads_lookback(engine_mock):
    """since_date set → loads extra _LOOKBACK_DAYS for warm-up."""

@patch("ingestion.indicators.get_engine")
def test_compute_indicators_inf_values_replaced_with_none(engine_mock):
    """Computed inf → stored as None."""

@patch("ingestion.indicators.get_engine")
def test_compute_indicators_nan_values_replaced_with_none(engine_mock):
    """Computed NaN → stored as None."""

@patch("ingestion.indicators.get_engine")
def test_compute_indicators_empty_after_since_date_filter_returns_zero(engine_mock):
    """since_date after all data → filter yields empty, returns 0."""
```
</details>

---

### 7. `src/ingestion/symbols.py` — 39 lines, 0%

<details>
<summary><b>Test skeletons</b></summary>

```python
# tests/test_ingestion_symbols.py
import pytest
import math
from unittest.mock import patch
from ingestion.symbols import _clean, refresh_symbols

def test_clean_none_returns_none():
    assert _clean(None) is None

def test_clean_nan_returns_none():
    assert _clean(float("nan")) is None

def test_clean_string_returns_string():
    assert _clean("AAPL") == "AAPL"

def test_clean_zero_returns_zero():
    assert _clean(0) == 0

@patch("ingestion.symbols.get_session")
def test_refresh_symbols_happy_path(session_mock):
    """Fetcher returns listing → upserted into DB, returns count."""

@patch("ingestion.symbols.get_session")
def test_refresh_symbols_empty_listing(session_mock):
    """Fetcher returns 0 rows → returns 0."""

@patch("ingestion.symbols.get_session")
def test_refresh_symbols_rollback_on_error(session_mock):
    """DB error → session.rollback() called, exception re-raised."""
```
</details>

---

### 8. `src/logging_config.py` — 5 lines, 0%

```python
# tests/test_logging_config.py
import logging
from logging_config import setup_logging

def test_setup_logging_default_level():
    setup_logging()
    assert logging.getLogger().level == logging.INFO

def test_setup_logging_custom_level():
    setup_logging(level=logging.DEBUG)
    assert logging.getLogger().level == logging.DEBUG
```

---

### 9. `src/full_pipeline.py` — 76 lines, 0%

```python
# tests/test_full_pipeline.py
from full_pipeline import parse_args, _setup_logging, main

def test_parse_args_defaults():
    args = parse_args([])
    assert args.config == "config.yaml"
    assert args.dry_run is False

def test_parse_args_dry_run():
    args = parse_args(["--dry-run"])
    assert args.dry_run is True

def test_parse_args_set_overrides():
    args = parse_args(["--set", "pipeline.symbols=AAPL"])
    assert args.set_ == ["pipeline.symbols=AAPL"]

def test_main_dry_run_no_execution():
    """--dry-run → logs steps, returns 0, no pipeline.run()."""

def test_main_pipeline_error_returns_2():
    """PipelineError raised → returns 2."""

def test_main_success_returns_0():
    """Normal completion → returns 0."""
```

---

### 10. `src/ui/cached_repo.py` — 13 lines, 0%

```python
# tests/test_ui_cached_repo.py
from unittest.mock import patch, MagicMock
import pandas as pd
from datetime import date
from ui.cached_repo import cached_find_stock, cached_get_prices

@patch("ui.cached_repo.StockRepository")
def test_cached_find_stock_found(repo_mock):
    repo_mock.return_value.find_stock.return_value = MagicMock(
        id=1, symbol="AAPL", name="Apple Inc.",
        exchange="NASDAQ", sector="Technology",
        industry="Consumer Electronics", is_active=True,
    )
    result = cached_find_stock("AAPL")
    assert result["symbol"] == "AAPL"

@patch("ui.cached_repo.StockRepository")
def test_cached_find_stock_not_found(repo_mock):
    repo_mock.return_value.find_stock.return_value = None
    assert cached_find_stock("ZZZZ") is None

@patch("ui.cached_repo.StockRepository")
def test_cached_get_prices_returns_dataframe(repo_mock):
    repo_mock.return_value.get_prices.return_value = pd.DataFrame({
        "date": [date(2024, 1, 1)], "close": [150.0],
    })
    result = cached_get_prices(1, "2024-01-01", "2024-01-31")
    assert isinstance(result, pd.DataFrame)
```

---

### 11. `src/ui/pages/*` — all 0% (11 files)

All Streamlit UI pages have zero test coverage. Test via StreamlitTesting or E2E (Playwright):

```
src/ui/pages/job_history.py      — 114 lines
src/ui/pages/live_trading.py     — 80 lines
src/ui/pages/ml_pipeline.py      — 206 lines
src/ui/pages/overview.py         — 193 lines
src/ui/pages/paper_trading.py    — 33 lines
src/ui/pages/portfolio.py        — 76 lines
src/ui/pages/settings.py         — 88 lines
src/ui/pages/stock_detail.py     — 278 lines (largest UI page)
src/ui/pages/stock_lookup.py     — 12 lines
src/ui/pages/stock_manager.py    — 152 lines
src/ui/pages/stock_screener.py   — 51 lines
src/ui/pages/stock_technical.py  — 81 lines
src/ui/pages/strategy_backtest.py— 51 lines
```

Each page's `render()` function should be extractable for testing:

```python
# tests/test_ui_pages.py (per page)
from unittest.mock import patch, MagicMock

@patch("streamlit.header")
@patch("ui.pages.overview.StockRepository")
def test_overview_render_with_data(repo_mock, header_mock):
    """render() with active stocks → displays metrics and charts."""
    from ui.pages.overview import render
    repo_mock.return_value.count_summary.return_value = {
        "total_stocks": 100, "active_stocks": 50, "total_prices": 50000,
    }
    render()
    header_mock.assert_any_call("📊 Overview")

@patch("ui.pages.overview.StockRepository")
def test_overview_render_empty(repo_mock):
    """render() with no stocks → displays empty state."""
    from ui.pages.overview import render
    repo_mock.return_value.count_summary.return_value = {
        "total_stocks": 0, "active_stocks": 0, "total_prices": 0,
    }
    render()  # should not crash
```

---

## 🟠 HIGH — <50% Coverage

### 12. `src/fetcher/alpha_vantage.py` — 18.8% (121 lines missing)

**Untested methods:** `_get()`, `get_daily()`, `get_overview()`, `get_income_statement()`, `get_balance_sheet()`, `get_cash_flow()`, `get_earnings()`, `_fetch_listing_from_api()`, `get_listing()`, `get_news_sentiment()`

<details>
<summary><b>Test skeletons</b></summary>

```python
# tests/test_fetcher_alpha_vantage.py
import pytest
import requests
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
from fetcher.alpha_vantage import AlphaVantageFetcher

@pytest.fixture
def fetcher():
    return AlphaVantageFetcher(api_key="test_key")

@patch("fetcher.alpha_vantage.requests.get")
def test_get_success(requests_mock, fetcher):
    requests_mock.return_value.json.return_value = {"key": "value"}
    result = fetcher._get({"function": "OVERVIEW", "symbol": "AAPL"})
    assert result == {"key": "value"}

@patch("fetcher.alpha_vantage.requests.get")
def test_get_rate_limited_retries(requests_mock, fetcher):
    requests_mock.return_value.json.side_effect = [
        {"Note": "API rate limit"}, {"key": "value"},
    ]
    result = fetcher._get({"function": "OVERVIEW", "symbol": "AAPL"})
    assert result == {"key": "value"}

@patch("fetcher.alpha_vantage.requests.get")
def test_get_all_retries_exhausted(requests_mock, fetcher):
    requests_mock.return_value.json.return_value = {"Note": "API rate limit"}
    result = fetcher._get({"function": "OVERVIEW", "symbol": "AAPL"})
    assert result == {}

@patch("fetcher.alpha_vantage.requests.get")
def test_get_network_error(requests_mock, fetcher):
    requests_mock.side_effect = requests.RequestException("timeout")
    result = fetcher._get({"function": "OVERVIEW", "symbol": "AAPL"})
    assert result == {}

@patch.object(AlphaVantageFetcher, "_get")
def test_get_daily_compact_for_recent_start(mock_get, fetcher):
    mock_get.return_value = {"Time Series (Daily)": {}}
    fetcher.get_daily("AAPL", start=date.today() - timedelta(days=30))
    assert mock_get.call_args[0][0]["outputsize"] == "compact"

@patch.object(AlphaVantageFetcher, "_get")
def test_get_daily_full_for_old_start(mock_get, fetcher):
    mock_get.return_value = {"Time Series (Daily)": {}}
    fetcher.get_daily("AAPL", start=date(2022, 1, 1))
    assert mock_get.call_args[0][0]["outputsize"] == "full"

@patch.object(AlphaVantageFetcher, "_get")
def test_get_overview_happy_path(mock_get, fetcher):
    mock_get.return_value = {"Symbol": "AAPL", "Name": "Apple Inc"}
    result = fetcher.get_overview("AAPL")
    assert result["symbol"] == "AAPL"

@patch.object(AlphaVantageFetcher, "_get")
def test_get_overview_empty_returns_empty_dict(mock_get, fetcher):
    mock_get.return_value = {}
    assert fetcher.get_overview("AAPL") == {}

@patch("fetcher.alpha_vantage._LISTING_CACHE.exists")
@patch.object(AlphaVantageFetcher, "_fetch_listing_from_api")
def test_get_listing_cache_hit(mock_fetch, cache_exists, fetcher):
    cache_exists.return_value = True
    with patch("pandas.read_parquet") as mock_read:
        mock_read.return_value = MagicMock()
        fetcher.get_listing()
        mock_fetch.assert_not_called()

@patch.object(AlphaVantageFetcher, "_get")
def test_get_news_sentiment_returns_list(mock_get, fetcher):
    mock_get.return_value = {"feed": [{"title": "News 1"}]}
    result = fetcher.get_news_sentiment("AAPL")
    assert len(result) == 1

@patch.object(AlphaVantageFetcher, "_get")
def test_get_news_sentiment_empty_returns_empty_list(mock_get, fetcher):
    mock_get.return_value = {}
    assert fetcher.get_news_sentiment("AAPL") == []
```
</details>

---

### 13. `src/repository.py` — 27.2% (126 lines missing)

**Untested/under-tested:** `find_stocks_batch()`, `get_prices()`, `get_prices_batch()`, `get_snapshots()`, `get_indicators()`, `count_summary()`, `search_stocks()`, `screen_stocks()`, `get_selected_stocks()`, `get_job_runs()`, `get_latest_fundamentals()`

<details>
<summary><b>Test skeletons</b></summary>

```python
# tests/test_repository_extended.py
import pytest
from unittest.mock import MagicMock
from datetime import date
from repository import StockRepository, ScreenCriteria, StockFilters

@pytest.fixture
def repo():
    return StockRepository()

def test_find_stocks_batch_returns_dict(repo):
    """Multiple symbols → {SYMBOL: Stock} dict."""

def test_find_stocks_batch_partial_match(repo):
    """Some symbols not found → only matching returned."""

def test_find_stocks_batch_empty_input(repo):
    """Empty list → empty dict."""

def test_get_prices_date_range(repo):
    """Returns DataFrame filtered by start/end."""

def test_get_prices_no_data_returns_empty_df(repo):
    """No prices in range → empty DataFrame."""

def test_count_summary_returns_dict(repo):
    """Returns dict with total_stocks, active_stocks, etc."""

def test_screen_stocks_by_sector(repo):
    """Criteria.sector='Technology' → only tech stocks."""

def test_screen_stocks_by_market_cap(repo):
    """min_market_cap filter applied."""

def test_screen_stocks_by_pe_range(repo):
    """min_pe/max_pe range filter."""

def test_screen_stocks_no_results(repo):
    """Impossible criteria → empty DataFrame."""

def test_screen_criteria_defaults():
    c = ScreenCriteria()
    assert c.min_market_cap == 0
    assert c.max_pe == 100.0
```
</details>

---

### 14. `src/scheduler.py` — 23.1% (60 lines missing)

```python
# tests/test_scheduler.py
from unittest.mock import patch
from scheduler import _record_job_start, _record_job_end, job_daily_pipeline, job_refresh_symbols

@patch("scheduler.get_session")
def test_record_job_start_creates_row(session_mock):
    run_id = _record_job_start("daily_pipeline")
    assert run_id is not None

@patch("scheduler.get_session")
def test_record_job_end_updates_row(session_mock):
    _record_job_end(1, stocks_updated=100, error=None)

@patch("scheduler.get_session")
def test_record_job_end_with_error(session_mock):
    _record_job_end(1, stocks_updated=0, error="timeout")

@patch("scheduler.run_daily_pipeline")
def test_job_daily_pipeline_success(pipeline_mock):
    pipeline_mock.return_value = {"processed": 42, "errors": 0}
    job_daily_pipeline()

@patch("scheduler.load_config")
def test_job_daily_pipeline_failure_records_error(config_mock):
    config_mock.side_effect = Exception("config missing")
    job_daily_pipeline()  # should not crash

@patch("scheduler.refresh_symbols")
def test_job_refresh_symbols_success(refresh_mock):
    refresh_mock.return_value = 5000
    job_refresh_symbols()
```

---

### 15. `src/config.py` — 35.3% (11 lines missing)

```python
# tests/test_config.py
import pytest
import yaml
from unittest.mock import patch, mock_open
from config import load_config

def test_load_config_loads_yaml():
    yaml_content = "database:\n  url: sqlite:///test.db\nfetcher:\n  type: alpha_vantage\n"
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("os.environ", {"ALPHA_VANTAGE_API_KEY": "test_key"}):
            config = load_config("config.yaml")
    assert config["database"]["url"] == "sqlite:///test.db"

def test_load_config_env_var_substitution():
    """${ALPHA_VANTAGE_API_KEY} → resolved from environment."""

def test_load_config_missing_file_raises():
    with patch("builtins.open", side_effect=FileNotFoundError):
        with pytest.raises(FileNotFoundError):
            load_config("nonexistent.yaml")
```

---

## 🟡 MEDIUM — 50-80% Coverage

### 16. `src/news_cache.py` — 53.8% (42 lines missing)

```python
# tests/test_news_cache_extended.py
from unittest.mock import patch, MagicMock
from news_cache import _key, get_cached, set_cached, install

def test_key_extracts_ticker_and_dates():
    result = _key("get_news", ("AAPL", "2024-01-01", "2024-01-31"), {})
    assert result[0] == "AAPL"

def test_get_cached_hit(session_mock):
    """Matching row in stock_news → returns content."""

def test_get_cached_miss_returns_none(session_mock):
    """No matching row → None."""

def test_get_cached_expired_returns_none(session_mock):
    """Row older than 7 days → None (cache miss)."""

def test_set_cached_inserts_row(session_mock):
    """New cache entry → insert into stock_news."""

def test_set_cached_updates_existing(session_mock):
    """Same key → UPDATE instead of INSERT."""

@patch("news_cache.sys.modules", {})
def test_install_patches_route_to_vendor():
    install()
    from tradingagents.dataflows import interface
    assert interface.route_to_vendor != _original
```

---

### 17. `src/pipeline/backends/selectors.py` — 70.0% (18 lines missing)

```python
# tests/test_pipeline_selectors_extended.py
def test_finrl_selector_empty_dataset_returns_empty():
    """No stocks pass criteria → empty DataFrame."""

def test_finrl_selector_all_nan_features():
    """All feature values NaN → graceful degradation."""

def test_top_n_selector_n_greater_than_available():
    """Request top 20 but only 5 stocks → returns all 5."""

def test_sector_selector_empty_sector():
    """Sector with no stocks → skipped, others proceed."""
```

---

## 🟢 LOW — 80%+ Coverage (Near-Target)

| File | Coverage | Missing | Gap |
|------|----------|---------|-----|
| `src/pipeline/backends/deep_evaluators.py` | 81.3% | 17 lines | Error paths in evaluator run() |
| `src/pipeline/backends/fast_evaluators.py` | 81.3% | 17 lines | Edge cases in opinion counting |
| `src/pipeline/stock_selection.py` | 88.6% | 4 lines | Empty selection handling |
| `src/pipeline/base.py` | 89.1% | 5 lines | Step error propagation |
| `src/database.py` | 89.7% | 3 lines | Connection failure handling |

---

## ✅ DONE — 100% Coverage

| File | Lines |
|------|-------|
| `src/models.py` | 299 |
| `src/utils.py` | 33 |
| `src/display.py` | 16 |
| `src/fetcher/rate_limiter.py` | 29 |
| `src/fetcher/base.py` | 10 |
| `src/migrations/run.py` | 39 |

---

## Integration Test Gaps

1. **Database → Fetcher → Ingestion flow** — `run_daily_pipeline()` against test DB
2. **ML Pipeline end-to-end** — `run_pipeline_and_save_report()` with real data
3. **Scheduler → Pipeline flow** — `job_daily_pipeline()` triggers full run
4. **CLI → Pipeline flow** — `main.py run --symbol AAPL`
5. **Streamlit UI → Repository flow** — page renders with test DB data

```python
# tests/test_integration_pipeline.py
import pytest

@pytest.mark.smoke
def test_daily_pipeline_end_to_end(test_db, mock_fetcher):
    """run_daily_pipeline() → DB has new DailyPrice rows."""
    from ingestion.pipeline import run_daily_pipeline
    summary = run_daily_pipeline(mock_fetcher, force=True)
    assert summary["processed"] > 0
    assert summary["errors"] == 0

@pytest.mark.smoke
def test_ml_pipeline_end_to_end(test_db, sample_fund_df):
    """run_pipeline_and_save_report() → SelectedStock rows."""

@pytest.mark.smoke
def test_cli_run_single_symbol(test_db, mock_fetcher, capsys):
    """python -m main run --symbol AAPL → success exit."""

@pytest.mark.smoke
def test_bootstrap_creates_stocks(test_db, mock_fetcher):
    """run_bootstrap() → Stock rows activated."""
```

---

## Error Handling Test Gaps (Cross-Cutting)

| Pattern | Files Missing |
|---------|---------------|
| ThreadPoolExecutor exception in worker | `ingestion/pipeline.py`, `finrl_runner.py` |
| Database session rollback | `ingestion/pipeline.py`, `repository.py`, `scheduler.py` |
| API rate limit / retry exhaustion | `fetcher/alpha_vantage.py`, `fetcher/yahoo.py` |
| Missing config keys | `config.py`, `full_pipeline.py`, `scheduler.py` |
| Empty API response | `fetcher/*.py`, `ingestion/pipeline.py` |
| NaN/Inf in computed values | `ingestion/indicators.py`, `ml_bucket_selector.py` |
| File not found (models dir, cache, config) | `finrl_runner.py`, `full_pipeline.py`, `fetcher/alpha_vantage.py` |
| Import error (optional dependency) | `finrl_runner.py`, `news_cache.py` |

---

## Priority Implementation Order

| # | Test File | Lines Gained | Impact |
|---|-----------|-------------|--------|
| 1 | `test_ingestion_pipeline.py` | ~318 | Core data pipeline |
| 2 | `test_fetcher_alpha_vantage.py` | ~121 | External API calls |
| 3 | `test_repository_extended.py` | ~126 | All DB queries |
| 4 | `test_finrl_runner.py` | ~277 | ML pipeline |
| 5 | `test_ml_bucket_selector.py` | ~90 | ML model wrapper |
| 6 | `test_main.py` | ~93 | CLI entry point |
| 7 | `test_app.py` | ~219 | Streamlit UI |
| 8 | `test_ingestion_indicators.py` | ~66 | Technical indicators |
| 9 | `test_scheduler.py` | ~60 | Job scheduling |
| 10 | `test_config.py` | ~11 | Configuration |
| 11 | `test_ui_cached_repo.py` | ~13 | UI cache layer |
| 12 | `test_news_cache.py` | ~42 | News caching |
| 13 | `test_full_pipeline.py` | ~76 | Pipeline orchestration |

**Estimated impact:** ~29.67% → ~75-80% (adds ~2,000 covered lines)
