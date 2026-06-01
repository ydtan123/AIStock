# AIStock Test Coverage Gap Analysis v4

**Date**: 2026-05-31
**Overall Coverage**: 29.7% (1,267 / 4,270 statements)
**Modules with Tests**: 14 / 39 (36%)
**Modules at 0%**: 25 / 39 (64%)

---

## Summary

| Category | Count | Statements |
|----------|-------|------------|
| 0% coverage modules | 25 | ~2,500 |
| Partially covered (<50%) | 4 | ~400 |
| Partially covered (50-90%) | 3 | ~350 |
| Well covered (>90%) | 7 | ~1,020 |

---

## Category 1: Untested Functions and Classes (0% Coverage)

### 1.1 `src/main.py` (93 stmts, 0%)

**Functions**: `cmd_init_db`, `cmd_bootstrap`, `cmd_run`, `_resolve_symbols`, `_ensure_stock`, `main`

**Gaps**: No CLI argument parsing tests, no command dispatch tests, no error path for missing symbols, no `--force` flag behavior tests, no `--source` override tests.

```python
# tests/test_main.py
import pytest
from unittest import mock

class TestCmdInitDb:
    def test_calls_init_db(self):
        from main import cmd_init_db
        args = mock.Mock()
        with mock.patch("main.init_db") as m:
            cmd_init_db(args)
            m.assert_called_once()

class TestResolveSymbols:
    def test_single_symbol(self):
        from main import _resolve_symbols
        args = mock.Mock(symbol=["AAPL"])
        assert _resolve_symbols(args) == ["AAPL"]

    def test_comma_separated(self):
        from main import _resolve_symbols
        args = mock.Mock(symbol=["AAPL,MSFT,GOOGL"])
        assert _resolve_symbols(args) == ["AAPL", "MSFT", "GOOGL"]

    def test_mixed_space_and_comma(self):
        from main import _resolve_symbols
        args = mock.Mock(symbol=["AAPL,MSFT", "GOOGL"])
        assert _resolve_symbols(args) == ["AAPL", "MSFT", "GOOGL"]

    def test_empty_returns_empty(self):
        from main import _resolve_symbols
        args = mock.Mock(symbol=[])
        assert _resolve_symbols(args) == []

    def test_strips_whitespace(self):
        from main import _resolve_symbols
        args = mock.Mock(symbol=[" AAPL , MSFT "])
        assert _resolve_symbols(args) == ["AAPL", "MSFT"]

class TestEnsureStock:
    def test_missing_stock_no_force_exits(self):
        from main import _ensure_stock
        with pytest.raises(SystemExit):
            _ensure_stock("MISSING", force=False)

    def test_missing_stock_with_force_creates(self):
        """New Stock created when force=True."""
        pass

class TestCmdRun:
    def test_no_symbols_runs_daily_pipeline(self):
        pass

    def test_with_symbols_processes_each(self):
        pass

    def test_source_override_passed_to_fetcher(self):
        pass

    def test_force_flag_passed_through(self):
        pass

    def test_refresh_snapshots_called_after_process(self):
        pass

class TestMain:
    def test_init_db_subcommand(self):
        pass

    def test_bootstrap_subcommand(self):
        pass

    def test_run_subcommand(self):
        pass

    def test_missing_command_exits(self):
        pass

class TestMainEdgeCases:
    def test_duplicate_symbols_deduplicated(self):
        pass

    def test_lowercase_input_uppercased(self):
        pass

    def test_empty_force_no_symbols(self):
        pass
```

---

### 1.2 `src/full_pipeline.py` (76 stmts, 0%)

**Functions**: `parse_args`, `_setup_logging`, `_build_session_factory`, `main`

**Gaps**: No argument parsing tests, no config loading error paths, no dry-run mode tests, no `--resume-from` behavior tests, no pipeline error exit code testing.

```python
# tests/test_full_pipeline.py
import pytest
from unittest import mock

class TestParseArgs:
    def test_default_config(self):
        from full_pipeline import parse_args
        args = parse_args([])
        assert args.config == "config.yaml"

    def test_custom_config(self):
        from full_pipeline import parse_args
        args = parse_args(["--config", "custom.yaml"])
        assert args.config == "custom.yaml"

    def test_set_overrides(self):
        from full_pipeline import parse_args
        args = parse_args(["--set", "key=value"])
        assert "key=value" in args.set_

    def test_resume_from_step(self):
        from full_pipeline import parse_args
        args = parse_args(["--resume-from", "fast_evaluation"])
        assert args.resume_from == "fast_evaluation"

    def test_resume_from_invalid_rejected(self):
        from full_pipeline import parse_args
        with pytest.raises(SystemExit):
            parse_args(["--resume-from", "nonexistent"])

    def test_dry_run_flag(self):
        from full_pipeline import parse_args
        args = parse_args(["--dry-run"])
        assert args.dry_run is True

class TestSetupLogging:
    def test_creates_log_directory(self, tmp_path):
        pass

    def test_sets_level_from_arg(self):
        pass

    def test_handlers_configured(self):
        pass

class TestMain:
    def test_dry_run_exits_zero_without_execution(self):
        from full_pipeline import main
        with mock.patch("full_pipeline.FullPipeline") as mock_fp:
            instance = mock_fp.return_value
            instance.run.return_value = 42
            instance._select_steps.return_value = []
            result = main(["--dry-run"])
            assert result == 0

    def test_pipeline_error_exits_two(self):
        from pipeline.base import PipelineError
        from full_pipeline import main
        with mock.patch("full_pipeline.FullPipeline") as mock_fp:
            instance = mock_fp.return_value
            instance.run.side_effect = PipelineError("test failure")
            result = main(["--config", "test.yaml"])
            assert result == 2

    def test_symbols_filter_applied(self):
        pass
```

---

### 1.3 `src/finrl_runner.py` (277 stmts, 0%)

**Functions**: `run_pipeline_and_save_report`, `run_predict_only`, `_equal_weight_fallback`, `_run_simple_backtest`, `_compute_metrics`, `_build_selection_summary`

**Gaps**: No ML pipeline execution tests, no backtest computation tests, no report generation tests, no error recovery from failed ML runs, no `_compute_metrics` mathematical correctness tests.

```python
# tests/test_finrl_runner.py
import pandas as pd
import pytest
from unittest import mock

class TestComputeMetrics:
    def test_positive_returns(self):
        from finrl_runner import _compute_metrics
        returns = pd.Series([0.01, 0.02, -0.005, 0.03])
        result = _compute_metrics(returns)
        assert "sharpe_ratio" in result
        assert "total_return" in result
        assert "max_drawdown" in result
        assert "annual_volatility" in result

    def test_all_negative_returns(self):
        from finrl_runner import _compute_metrics
        returns = pd.Series([-0.01, -0.02, -0.005])
        result = _compute_metrics(returns)
        assert result["total_return"] < 0

    def test_single_value_returns(self):
        from finrl_runner import _compute_metrics
        returns = pd.Series([0.01])
        result = _compute_metrics(returns)
        assert result is not None

    def test_zero_returns(self):
        from finrl_runner import _compute_metrics
        returns = pd.Series([0.0, 0.0, 0.0])
        result = _compute_metrics(returns)
        assert result is not None

    def test_nan_in_returns(self):
        from finrl_runner import _compute_metrics
        returns = pd.Series([0.01, float("nan"), 0.02])
        result = _compute_metrics(returns)
        assert result is not None

    def test_inf_in_returns(self):
        from finrl_runner import _compute_metrics
        returns = pd.Series([0.01, float("inf"), 0.02])
        result = _compute_metrics(returns)
        assert result is not None

class TestEqualWeightFallback:
    def test_produces_equal_weights(self):
        from finrl_runner import _equal_weight_fallback
        fund_df = pd.DataFrame({"tic": ["A", "B", "C", "D"]})
        tickers_df = pd.DataFrame({"tic": ["A", "B", "C", "D"]})
        result = _equal_weight_fallback(fund_df, tickers_df, 0.75)
        unique = result["weight"].unique()
        assert len(unique) == 1

    def test_empty_input(self):
        from finrl_runner import _equal_weight_fallback
        fund_df = pd.DataFrame(columns=["tic"])
        tickers_df = pd.DataFrame(columns=["tic"])
        result = _equal_weight_fallback(fund_df, tickers_df, 0.75)
        assert len(result) == 0

class TestRunSimpleBacktest:
    def test_returns_backtest_dict(self):
        pass

    def test_benchmarks_included(self):
        pass

    def test_rebalance_frequency_respected(self):
        pass

    def test_empty_tickers_no_crash(self):
        pass

class TestBuildSelectionSummary:
    def test_formats_selected_stocks(self):
        from finrl_runner import _build_selection_summary
        summary = _build_selection_summary(
            [{"ticker": "AAPL", "weight": 0.5}],
            ["/tmp/model.pkl"],
        )
        assert "selected_stocks" in summary
        assert "saved_models" in summary

    def test_empty_inputs(self):
        from finrl_runner import _build_selection_summary
        summary = _build_selection_summary([], [])
        assert summary["selected_stocks"] == []
        assert summary["saved_models"] == []
```

---

### 1.4 `src/ta_run.py` (309 stmts, 0%)

**Functions**: `main`, `_emit`, `_print_summary`, async analysis functions.

**Gaps**: CLI argument parsing, JSON stdout emission format, async TradingAgents graph execution, error handling for missing API keys, timeout handling, empty analyst output handling.

```python
# tests/test_ta_run.py
import pytest
from unittest import mock

class TestEmit:
    def test_outputs_valid_json_line(self, capsys):
        from ta_run import _emit
        _emit({"type": "start", "ticker": "AAPL"})
        captured = capsys.readouterr()
        assert '"type": "start"' in captured.out
        assert '"ticker": "AAPL"' in captured.out

class TestPrintSummary:
    def test_formats_summary_correctly(self, capsys):
        from ta_run import _print_summary
        rows = [{"ticker": "AAPL", "decision": "BUY"}]
        logger = mock.Mock()
        _print_summary(rows, 10, {"analyst_a": 5}, logger)
        logger.info.assert_called()

class TestMain:
    def test_parses_tickers_arg(self):
        pass

    def test_parses_date_arg(self):
        pass

    def test_no_tickers_exits_with_error(self):
        pass

    def test_tradingagents_not_installed_handled(self):
        pass
```

---

### 1.5 `src/ingestion/pipeline.py` (318 stmts, 0%)

**Functions**: `_last_trading_date`, `_prefetch_stock_dates`, `_fetch_and_store_prices`, `_upsert_fundamentals`, `_refresh_snapshots`, `_batch_update_checkpoints`, `_needs_full_backfill`, `_fetch_stock_news`, `_fetch_stock_news_av`, `_process_symbol`, `run_daily_pipeline`, `run_bootstrap`

**Gaps**: Date boundary calculations, price fetching with error recovery, fundamental upsert logic, snapshot refresh aggregation, checkpoint update batching, news fetching with cache integration, symbol processing with retry, pipeline summary statistics.

```python
# tests/test_ingestion_pipeline.py
import pytest
from datetime import date, timedelta
from unittest import mock

class TestLastTradingDate:
    def test_weekday_returns_today(self):
        from ingestion.pipeline import _last_trading_date
        with mock.patch("ingestion.pipeline.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 29)
            mock_date.fromordinal.side_effect = date.fromordinal
            result = _last_trading_date()
            assert result == date(2026, 5, 29)

    def test_saturday_returns_friday(self, monkeypatch):
        pass

    def test_sunday_returns_friday(self, monkeypatch):
        pass

    def test_monday_after_holiday(self, monkeypatch):
        pass

class TestPrefetchStockDates:
    def test_returns_date_range_per_stock(self):
        pass

    def test_empty_input_returns_empty(self):
        pass

    def test_stock_with_no_prices_no_crash(self):
        pass

class TestFetchAndStorePrices:
    def test_inserts_new_prices(self):
        pass

    def test_skips_duplicate_dates(self):
        pass

    def test_api_error_returns_empty(self):
        pass

    def test_empty_result_from_api(self):
        pass

class TestUpsertFundamentals:
    def test_inserts_new_fundamentals(self):
        pass

    def test_updates_existing_record(self):
        pass

    def test_empty_overview_no_crash(self):
        pass

    def test_force_bypasses_quarter_check(self):
        pass

class TestRefreshSnapshots:
    def test_aggregates_latest_indicators(self):
        pass

    def test_no_indicators_no_crash(self):
        pass

class TestNeedsFullBackfill:
    def test_no_indicators_requires_backfill(self):
        from ingestion.pipeline import _needs_full_backfill
        assert _needs_full_backfill(None) is True

    def test_recent_indicator_skips_backfill(self):
        from ingestion.pipeline import _needs_full_backfill
        recent = date.today() - timedelta(days=1)
        assert _needs_full_backfill(recent) is False

    def test_stale_indicator_requires_backfill(self):
        from ingestion.pipeline import _needs_full_backfill
        stale = date.today() - timedelta(days=30)
        assert _needs_full_backfill(stale) is True

class TestFetchStockNews:
    def test_alpha_vantage_fetcher_path(self):
        pass

    def test_yahoo_fetcher_fallback(self):
        pass

    def test_no_fetcher_uses_config(self):
        pass

class TestProcessSymbol:
    def test_processes_prices_and_indicators(self):
        pass

    def test_inactive_symbol_skipped(self):
        pass

    def test_api_rate_limit_handled(self):
        pass

    def test_network_error_survives(self):
        pass

class TestRunDailyPipeline:
    def test_returns_summary_dict(self):
        pass

    def test_parallel_workers_config_respected(self):
        pass

    def test_empty_active_symbols(self):
        pass

    def test_all_symbols_fail_no_crash(self):
        pass

class TestRunBootstrap:
    def test_activates_stocks_by_criteria(self):
        pass

    def test_criteria_none_skips_activation(self):
        pass
```

---

### 1.6 `src/ingestion/indicators.py` (66 stmts, 0%)

**Function**: `compute_indicators`

```python
# tests/test_ingestion_indicators.py
import pytest
from datetime import date
from unittest import mock

class TestComputeIndicators:
    def test_computes_for_stock_with_prices(self):
        pass

    def test_returns_zero_when_no_prices(self):
        pass

    def test_since_date_filters(self):
        pass

    def test_single_price_row_no_crash(self):
        pass

    def test_missing_stock_id_no_crash(self):
        pass

    def test_talib_not_installed_handled(self):
        pass
```

---

### 1.7 `src/ingestion/symbols.py` (39 stmts, 0%)

**Functions**: `refresh_symbols`, `_fetch_symbols`

```python
# tests/test_ingestion_symbols.py
import pytest
from unittest import mock

class TestRefreshSymbols:
    def test_inserts_new_symbols(self):
        pass

    def test_updates_existing_is_active(self):
        pass

    def test_rate_limit_handled(self):
        pass

    def test_empty_api_response(self):
        pass

class TestFetchSymbols:
    def test_alpha_vantage_format_parsed(self):
        pass

    def test_yahoo_format_parsed(self):
        pass
```

---

### 1.8 `src/ml_bucket_selector.py` (90 stmts, 0%)

**Class**: `MLBucketSelector`

**Gaps**: No ML model training tests, no feature column missing handling, no median imputation tests, no saved model path tests, no empty/corrupt DataFrame handling.

```python
# tests/test_ml_bucket_selector.py
import pandas as pd
import pytest
from ml_bucket_selector import MLBucketSelector

class TestMLBucketSelector:
    @pytest.fixture
    def selector(self):
        return MLBucketSelector(top_quantile=0.75, test_quarters=3)

    @pytest.fixture
    def sample_fund_df(self):
        return pd.DataFrame({
            "tic": ["A", "B", "C", "A", "B"],
            "datadate": ["2024-12-31"] * 5,
            "gsector": ["Tech", "Finance", "Tech", "Tech", "Finance"],
            "y_return": [0.05, -0.02, 0.10, 0.03, 0.01],
        })

    def test_fit_predict_returns_dataframe(self, selector, sample_fund_df):
        result = selector.fit_predict(sample_fund_df)
        assert isinstance(result, pd.DataFrame)

    def test_missing_feature_cols_imputed(self, selector, sample_fund_df):
        pass

    def test_all_nan_column_imputed_to_zero(self):
        pass

    def test_empty_dataframe_no_crash(self, selector):
        df = pd.DataFrame(columns=["tic", "datadate", "gsector", "y_return"])
        result = selector.fit_predict(df)
        assert len(result) == 0

    def test_save_models_writes_files(self, selector, sample_fund_df, tmp_path):
        pass

    def test_weight_method_equal(self):
        s = MLBucketSelector(weight_method="equal")
        pass

    def test_weight_method_inverse_volatility(self):
        s = MLBucketSelector(weight_method="inverse_volatility")
        pass

    def test_single_stock_no_crash(self, selector):
        pass

    def test_gsector_missing_handled(self, selector):
        pass

    def test_dates_normalized_to_strings(self, selector, sample_fund_df):
        pass
```

---

### 1.9 UI Modules (12 files, all 0%)

**Modules**: `app.py`, `cached_repo.py`, `pages/*.py`

**Strategy**: Streamlit rendering tested via Playwright E2E. Key missing E2E tests:

```python
# tests/test_e2e_ml_pipeline.py
def test_ml_pipeline_run_button_triggers_thread(page):
    pass

def test_ml_pipeline_log_lines_stream(page):
    pass

def test_ml_pipeline_error_displayed(page):
    pass

def test_ml_pipeline_report_download_link(page):
    pass

def test_predict_only_mode_uses_db_symbols(page):
    pass

# tests/test_e2e_stock_detail.py
def test_stock_detail_loads_prices_chart(page):
    pass

def test_stock_detail_no_data_shows_empty_state(page):
    pass

# tests/test_e2e_stock_screener.py
def test_screener_filters_by_sector(page):
    pass

def test_screener_empty_results_shows_message(page):
    pass

# tests/test_e2e_error_states.py
def test_database_error_shows_fallback_ui(page):
    pass

def test_api_unreachable_shows_warning(page):
    pass
```

---

## Category 2: Partially Covered Modules (<50%)

### 2.1 `src/repository.py` (27.2%, 173 stmts)

**Tested** (9/19 methods): `get_stocks`, `get_active_stocks`, `get_active_symbols`, `count_summary`, `save_selected_stocks`, `get_latest_selected_stocks`, `bulk_set_active`, `get_job_runs`, `get_sectors`

**Untested** (10/19 methods): `_get_session`, `_with_session`, `find_stock`, `find_stocks_batch`, `get_prices`, `get_prices_batch`, `get_indicator`, `get_snapshot`, `get_tech_indicators`, `screen_stocks`, `list_stocks`, `save_predict_only_results`

```python
# tests/test_repository_extended.py

class TestFindStock:
    def test_existing_symbol_returns_stock(self, repo):
        _seed_stock("AAPL")
        stock = repo.find_stock("AAPL")
        assert stock is not None
        assert stock.symbol == "AAPL"

    def test_missing_symbol_returns_none(self, repo):
        stock = repo.find_stock("NONEXISTENT")
        assert stock is None

    def test_case_sensitive_match(self, repo):
        _seed_stock("AAPL")
        stock = repo.find_stock("aapl")
        pass  # Document behavior (case-sensitive or not)

class TestFindStocksBatch:
    def test_returns_dict_indexed_by_symbol(self, repo):
        _seed_stock("AAPL")
        _seed_stock("MSFT")
        result = repo.find_stocks_batch(["AAPL", "MSFT"])
        assert isinstance(result, dict)
        assert "AAPL" in result
        assert "MSFT" in result

    def test_missing_symbols_excluded(self, repo):
        result = repo.find_stocks_batch(["NONEXISTENT"])
        assert len(result) == 0

    def test_partial_match(self, repo):
        _seed_stock("AAPL")
        result = repo.find_stocks_batch(["AAPL", "NONEXISTENT"])
        assert len(result) == 1
        assert "AAPL" in result

    def test_empty_input_returns_empty(self, repo):
        result = repo.find_stocks_batch([])
        assert isinstance(result, dict)
        assert len(result) == 0

class TestGetPrices:
    def test_returns_dataframe_with_expected_columns(self, repo):
        pass

    def test_filters_by_date_range(self, repo):
        pass

    def test_no_prices_returns_empty_dataframe(self, repo):
        pass

    def test_start_equals_end_returns_single_day(self, repo):
        pass

class TestGetPricesBatch:
    def test_returns_dict_by_stock_id(self, repo):
        pass

    def test_partial_data_stocks_included(self, repo):
        pass

class TestGetIndicator:
    def test_returns_indicator_if_exists(self, repo):
        pass

    def test_returns_none_if_no_indicator(self, repo):
        pass

class TestGetSnapshot:
    def test_returns_snapshot_if_exists(self, repo):
        pass

    def test_returns_none_if_no_snapshot(self, repo):
        pass

class TestGetTechIndicators:
    def test_returns_dataframe_with_date_range(self, repo):
        pass

    def test_no_data_returns_empty_df(self, repo):
        pass

class TestScreenStocks:
    def test_filters_by_sector(self, repo):
        pass

    def test_filters_by_market_cap_range(self, repo):
        pass

    def test_filters_by_pe_range(self, repo):
        pass

    def test_combined_filters(self, repo):
        pass

    def test_empty_results_no_crash(self, repo):
        pass

    def test_missing_snapshot_data_handled(self, repo):
        pass

class TestListStocks:
    def test_paginates_results(self, repo):
        pass

    def test_sorts_by_column(self, repo):
        pass

    def test_filters_by_active_status(self, repo):
        pass

class TestSavePredictOnlyResults:
    def test_inserts_predictions(self, repo):
        predictions = [{"ticker": "AAPL", "decision": "BUY", "confidence": 0.85}]
        count = repo.save_predict_only_results(predictions)
        assert count == 1

    def test_empty_list_returns_zero(self, repo):
        count = repo.save_predict_only_results([])
        assert count == 0

    def test_latest_only_flag(self, repo):
        pass

class TestRepositoryErrorHandling:
    def test_session_failure_rolls_back(self, repo):
        pass

    def test_query_timeout_handled(self, repo):
        pass

    def test_connection_lost_recovery(self, repo):
        pass
```

---

### 2.2 `src/scheduler.py` (23.1%, 78 stmts)

**Tested**: `_record_job_start`, `_record_job_end`

**Untested**: `job_daily_pipeline`, `job_refresh_symbols`, `main`

```python
# tests/test_scheduler_extended.py

class TestJobDailyPipeline:
    def test_success_updates_record(self, monkeypatch):
        pass

    def test_refresh_snapshots_path(self, monkeypatch):
        pass

    def test_stocks_updated_count_correct(self, monkeypatch):
        pass

class TestJobRefreshSymbols:
    def test_success_updates_count(self, monkeypatch):
        pass

    def test_failure_sets_error(self, monkeypatch):
        pass

class TestSchedulerMain:
    def test_parses_run_time_from_config(self, monkeypatch):
        pass

    def test_parses_timezone_from_config(self, monkeypatch):
        pass

    def test_weekday_schedule_correct(self, monkeypatch):
        pass

    def test_invalid_time_config_handled(self, monkeypatch):
        pass

class TestSchedulerErrorHandling:
    def test_db_connection_lost_during_job(self, monkeypatch):
        pass

    def test_config_missing_scheduler_section(self, monkeypatch):
        pass
```

---

### 2.3 `src/fetcher/alpha_vantage.py` (18.8%, 149 stmts)

**Class**: `AlphaVantageFetcher` — most `fetch_*` and `get_*` methods untested.

```python
# tests/test_alpha_vantage_fetcher.py
import pytest
from unittest import mock

class TestAlphaVantageFetcher:
    @pytest.fixture
    def fetcher(self):
        from fetcher.alpha_vantage import AlphaVantageFetcher
        cfg = {"alpha_vantage": {"api_key": "TEST_KEY", "premium": False}}
        return AlphaVantageFetcher(cfg)

    def test_fetch_daily_prices(self, fetcher):
        pass

    def test_fetch_daily_prices_empty_result(self, fetcher):
        pass

    def test_fetch_daily_prices_rate_limited(self, fetcher):
        pass

    def test_fetch_overview(self, fetcher):
        pass

    def test_fetch_overview_missing_symbol(self, fetcher):
        pass

    def test_fetch_income_statement(self, fetcher):
        pass

    def test_fetch_balance_sheet(self, fetcher):
        pass

    def test_fetch_cash_flow(self, fetcher):
        pass

    def test_fetch_earnings(self, fetcher):
        pass

    def test_get_news_sentiment(self, fetcher):
        pass

    def test_list_symbols(self, fetcher):
        pass

    def test_api_error_returns_empty(self, fetcher):
        pass

    def test_json_decode_error_handled(self, fetcher):
        pass

    def test_api_key_missing_raises(self):
        pass

    def test_premium_endpoint_used_when_configured(self):
        pass
```

---

### 2.4 `src/fetcher/yahoo.py` (38.1%, 21 stmts)

```python
# tests/test_yahoo_fetcher.py
class TestYahooFetcher:
    def test_fetch_daily_prices(self):
        pass

    def test_fetch_overview(self):
        pass

    def test_yfinance_not_installed_handled(self):
        pass

    def test_ticker_not_found(self):
        pass

    def test_rate_limit_handled(self):
        pass
```

---

## Category 3: Partially Covered (50-90%)

### 3.1 `src/news_cache.py` (53.8%, 91 stmts)

**Untested**: `get_cached` (with data), `set_cached` (with data), `install` (success path), `_get_session`

```python
# tests/test_news_cache_extended.py

class TestGetCachedFull:
    def test_cache_hit_returns_data(self):
        pass

    def test_cache_miss_returns_none(self):
        pass

    def test_expired_cache_returns_none(self, monkeypatch):
        pass

    def test_different_args_different_cache_keys(self):
        pass

class TestSetCachedFull:
    def test_stores_and_retrieves_structured_data(self):
        pass

    def test_none_value_skipped(self):
        pass

    def test_oversized_result_truncated_or_skipped(self):
        pass

class TestGetSession:
    def test_session_is_singleton(self):
        pass

    def test_thread_safety(self):
        pass
```

---

### 3.2 `src/pipeline/data_update.py` (42.9%, 35 stmts)

```python
# tests/test_pipeline_data_update_extended.py

class TestDataUpdate:
    def test_empty_symbols_list(self):
        pass

    def test_parallel_worker_failure_isolation(self):
        pass

    def test_snapshot_refresh_after_update(self):
        pass
```

---

### 3.3 `src/config.py` (35.3%, 17 stmts)

```python
# tests/test_config.py
class TestLoadConfig:
    def test_loads_yaml(self):
        pass

    def test_missing_file_raises(self):
        pass

    def test_environment_override(self):
        pass

    def test_invalid_yaml_raises(self):
        pass

    def test_dotted_path_override(self):
        pass
```

---

## Category 4: Missing Error Handling Tests

### 4.1 Database Errors

```python
# tests/test_error_handling_database.py

class TestDatabaseErrors:
    def test_connection_refused(self):
        pass

    def test_connection_timeout(self):
        pass

    def test_transaction_deadlock(self):
        pass

    def test_table_not_found(self):
        pass

    def test_disk_full_on_write(self):
        pass

    def test_mysql_strict_mode_violation(self):
        pass
```

### 4.2 API/Network Errors

```python
# tests/test_error_handling_network.py

class TestNetworkErrors:
    def test_dns_resolution_failure(self):
        pass

    def test_tls_certificate_error(self):
        pass

    def test_http_429_rate_limit(self):
        pass

    def test_http_500_server_error(self):
        pass

    def test_http_403_api_key_invalid(self):
        pass

    def test_response_truncated(self):
        pass

    def test_socket_timeout(self):
        pass

    def test_connection_reset(self):
        pass
```

### 4.3 Data Integrity Errors

```python
# tests/test_error_handling_data.py

class TestDataErrors:
    def test_nan_in_price_column(self):
        pass

    def test_negative_price_values(self):
        pass

    def test_future_date_in_data(self):
        pass

    def test_duplicate_primary_key_on_insert(self):
        pass

    def test_null_required_field(self):
        pass

    def test_encoding_error_in_news_text(self):
        pass

    def test_zero_division_in_indicator_calc(self):
        pass

    def test_empty_dataframe_passed_to_ml(self):
        pass

    def test_single_row_dataframe_passed_to_regression(self):
        pass

    def test_correlated_features_in_ml(self):
        pass
```

---

## Category 5: Integration Test Gaps

### 5.1 Pipeline Step Integration

```python
# tests/test_integration_pipeline_chain.py

class TestPipelineChainIntegration:
    def test_data_update_feeds_stock_selection(self):
        pass

    def test_selection_feeds_evaluation(self):
        pass

    def test_step_failure_halts_pipeline(self):
        pass

    def test_resume_from_mid_pipeline(self):
        pass

    def test_config_override_flows_through_pipeline(self):
        pass
```

### 5.2 Database + Repository Integration

```python
# tests/test_integration_db_repo.py

class TestDBRepoIntegration:
    def test_insert_and_retrieve_stock_full_cycle(self):
        pass

    def test_price_insert_then_indicator_compute(self):
        pass

    def test_snapshot_refresh_correctness(self):
        pass

    def test_migration_runner_applies_all(self):
        pass
```

### 5.3 Fetcher + Ingestion Integration

```python
# tests/test_integration_fetcher_ingestion.py

class TestFetcherIngestionIntegration:
    def test_fetch_prices_then_store(self):
        pass

    def test_fetch_fundamentals_then_upsert(self):
        pass

    def test_source_switch_mid_run(self):
        pass
```

### 5.4 CLI End-to-End

```python
# tests/test_integration_cli.py

class TestCLIIntegration:
    def test_init_db_creates_all_tables(self):
        pass

    def test_bootstrap_full_flow_dry_run(self):
        pass

    def test_run_single_symbol_e2e(self):
        pass

    def test_full_pipeline_cli_dry_run(self):
        pass
```

---

## Priority Matrix

| Priority | Module | Gap Type | Risk | Est. |
|----------|--------|----------|------|------|
| **P0** | `repository.py` | 10 untested data access methods | High | 8h |
| **P0** | `ingestion/pipeline.py` | All core ETL logic | Critical | 12h |
| **P0** | Error handling (DB) | Zero coverage on DB errors | High | 6h |
| **P1** | `finrl_runner.py` | ML pipeline untested | High | 8h |
| **P1** | `main.py` | CLI commands untested | Medium | 4h |
| **P1** | `ml_bucket_selector.py` | ML logic untested | High | 6h |
| **P1** | `ingestion/indicators.py` | Indicator computation | Medium | 4h |
| **P1** | `ingestion/symbols.py` | Symbol ingestion | Medium | 2h |
| **P2** | `scheduler.py` | Job functions | Medium | 4h |
| **P2** | `full_pipeline.py` | CLI shim | Low | 3h |
| **P2** | `ta_run.py` | TradingAgents wrapper | Medium | 6h |
| **P2** | `fetcher/alpha_vantage.py` | Most fetch methods | Medium | 6h |
| **P2** | `fetcher/yahoo.py` | Most fetch methods | Low | 3h |
| **P2** | `news_cache.py` | Cache read/write paths | Low | 2h |
| **P3** | UI modules | All 12 pages | Low | 16h |
| **P3** | `config.py` | Config loading | Low | 2h |
| **P3** | Integration tests | Cross-module chains | Medium | 10h |
| **P3** | Error handling (API) | Network error paths | Medium | 6h |
| **P3** | Error handling (Data) | Data integrity paths | Medium | 6h |

**Total estimated effort**: ~114 hours across all priorities.

---

## Quick Wins (High Impact, Low Effort)

1. `test_needs_full_backfill` — 3 tests, 15 min
2. `test_ensure_stock` — 2 tests, 30 min  
3. `test_resolve_symbols` — 5 tests, 20 min
4. `test_find_stock` / `test_find_stocks_batch` — 6 tests, 1h
5. `test_get_prices` — 4 tests, 1h
6. `test_compute_metrics` — 6 tests, 1h
7. `test_load_config` — 4 tests, 30 min
8. `test_screen_stocks` — 5 tests, 1.5h

**Quick wins total**: ~6h, raising coverage from 29.7% to ~38%.

---

## Appendix: Coverage by Module

| File | Coverage | Statements |
|------|----------|------------|
| `src/app.py` | 0.0% | 219 |
| `src/config.py` | 35.3% | 17 |
| `src/database.py` | 89.7% | 29 |
| `src/display.py` | 100.0% | 16 |
| `src/fetcher/__init__.py` | 100.0% | 10 |
| `src/fetcher/alpha_vantage.py` | 18.8% | 149 |
| `src/fetcher/base.py` | 100.0% | 10 |
| `src/fetcher/rate_limiter.py` | 100.0% | 29 |
| `src/fetcher/yahoo.py` | 38.1% | 21 |
| `src/finrl_runner.py` | 0.0% | 277 |
| `src/full_pipeline.py` | 0.0% | 76 |
| `src/ingestion/indicators.py` | 0.0% | 66 |
| `src/ingestion/pipeline.py` | 0.0% | 318 |
| `src/ingestion/symbols.py` | 0.0% | 39 |
| `src/logging_config.py` | 0.0% | 5 |
| `src/main.py` | 0.0% | 93 |
| `src/migrations/run.py` | 100.0% | 39 |
| `src/ml_bucket_selector.py` | 0.0% | 90 |
| `src/models.py` | 100.0% | 299 |
| `src/news_cache.py` | 53.8% | 91 |
| `src/pipeline/backends/deep_evaluators.py` | 81.0% | 100 |
| `src/pipeline/backends/fast_evaluators.py` | 81.3% | 91 |
| `src/pipeline/backends/selectors.py` | 70.0% | 60 |
| `src/pipeline/base.py` | 89.1% | 46 |
| `src/pipeline/config.py` | 95.0% | 60 |
| `src/pipeline/data_update.py` | 42.9% | 35 |
| `src/pipeline/deep_evaluation.py` | 90.5% | 105 |
| `src/pipeline/fast_evaluation.py` | 95.5% | 89 |
| `src/pipeline/orchestrator.py` | 94.7% | 133 |
| `src/pipeline/stock_selection.py` | 88.6% | 35 |
| `src/repository.py` | 27.2% | 173 |
| `src/scheduler.py` | 23.1% | 78 |
| `src/ta_run.py` | 0.0% | 309 |
| `src/ui/cached_repo.py` | 0.0% | 13 |
| `src/ui/pages/job_history.py` | 0.0% | 15 |
| `src/ui/pages/live_trading.py` | 0.0% | 63 |
| `src/ui/pages/ml_pipeline.py` | 0.0% | 325 |
| `src/ui/pages/overview.py` | 0.0% | 16 |
| `src/ui/pages/paper_trading.py` | 0.0% | 79 |
| `src/ui/pages/portfolio.py` | 0.0% | 47 |
| `src/ui/pages/settings.py` | 0.0% | 35 |
| `src/ui/pages/stock_detail.py` | 0.0% | 102 |
| `src/ui/pages/stock_lookup.py` | 0.0% | 68 |
| `src/ui/pages/stock_manager.py` | 0.0% | 67 |
| `src/ui/pages/stock_screener.py` | 0.0% | 51 |
| `src/ui/pages/stock_technical.py` | 0.0% | 81 |
| `src/ui/pages/strategy_backtest.py` | 0.0% | 51 |
| `src/utils.py` | 100.0% | 33 |
| **TOTAL** | **29.7%** | **4,270** |
