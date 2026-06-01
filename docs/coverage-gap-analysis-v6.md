# Test Coverage Gap Analysis v6

**Date**: 2026-05-30
**Overall Coverage**: 29% (1250/4247 statements)
**Tests**: 21 files, ~160 test functions, 13 failures, 19 errors

---

## 1. Infrastructure Blockers (Must Fix First)

These bugs block 30+ tests from running. Fix them before adding new tests.

### Bug 1: `test_pipeline_data_update.py` — Monkeypatch Arity Mismatch

**Root cause**: `_run_pipeline` signature is `(source, step_cfg, full_cfg)` but monkeypatches use 2-param lambdas.

```python
# src/pipeline/data_update.py line 10: actual signature
def _run_pipeline(source: str, step_cfg: dict, full_cfg: dict) -> dict:

# tests/test_pipeline_data_update.py lines 28-30: BROKEN
lambda source, step_cfg: fake_result,  # TypeError: takes 2 positional arguments but 3 were given
```

**Fix**: Add `full_cfg` parameter to all 4 monkeypatches:
```python
lambda source, step_cfg, full_cfg: fake_result,
```

### Bug 2: `test_repository.py` — Calling Non-Existent Methods

**Root cause**: Tests call `repo.get_stocks()`, `repo.get_active_stocks()`, `repo.get_active_symbols()` — these methods do not exist on `StockRepository`. Current class has `find_stock()`, `find_stocks_batch()`, `list_stocks()`.

**Fix**: Rewrite test methods to use current StockRepository API, or add compatibility wrappers.

### Bug 3: `test_scheduler.py` + `test_database.py` — SQLite pool_size Incompatibility

**Root cause**: `configure("sqlite:///:memory:")` passes `pool_size`, `max_overflow` kwargs in `database.py`, which SQLite `create_engine` rejects.

**Fix**: In `src/database.py::configure()`, conditionally apply pool args:
```python
if "mysql" in url:
    engine = create_engine(url, pool_size=10, max_overflow=5, pool_recycle=3600)
else:
    engine = create_engine(url)
```

---

## 2. Module-by-Module Coverage

### Critical (0-30% coverage, high business impact)

| Module | Stmts | Missing | Cov% | Risk | Key Gaps |
|--------|-------|---------|------|------|----------|
| `repository.py` | 173 | 126 | 27% | HIGH | 10 data-access methods untested |
| `scheduler.py` | 78 | 60 | 23% | HIGH | `main()` daemon entry, job success paths |
| `data_update.py` | 35 | 20 | 43% | HIGH | `_run_pipeline` body, success path |
| `ta_run.py` | 309 | 309 | 0% | MEDIUM | All technical analysis functions |
| `ui/cached_repo.py` | 13 | 13 | 0% | MEDIUM | Cached DB wrapper |

### Warning (30-79% coverage)

| Module | Stmts | Missing | Cov% | Key Gaps |
|--------|-------|---------|------|----------|
| `selectors.py` | 60 | 18 | 70% | `_run_finrl_runner`, `FinrlStockSelector.select` |

### OK (80%+ coverage, only edge cases missing)

| Module | Stmts | Missing | Cov% | Key Gaps |
|--------|-------|---------|------|----------|
| `fast_evaluators.py` | 91 | 17 | 81% | Error paths in `_resolve_dates`, `_compute_consensus` |
| `deep_evaluators.py` | 100 | 19 | 81% | `_extract_decision` edge cases, ThreadPoolExecutor errors |
| `base.py` | 46 | 5 | 89% | `PipelineError`, `StepResult.to_dict` |
| `stock_selection.py` | 35 | 4 | 89% | Backend not found, write error paths |
| `orchestrator.py` | 133 | 7 | 95% | Exception wrapping, resume-from paths |
| `config.py` | 60 | 3 | 95% | Invalid YAML, missing file |
| `fast_evaluation.py` | 89 | 4 | 96% | Empty upstream edge cases |
| `deep_evaluation.py` | 82 | 4 | 95% | Empty upstream edge cases |

### Streamlit UI (0% — inherently hard to unit test)

All 14 `src/ui/` modules at 0%. Strategy: integration tests via Playwright, not unit tests.

---

## 3. Test Skeletons by Module

### 3.1 `repository.py` — 10 Untested Methods

#### `find_stock` (line 53)
```python
class TestFindStock:
    def test_returns_stock_for_existing_symbol(self, repo):
        """Seed AAPL, find_stock('AAPL') returns Stock object."""
        _seed_stock("AAPL")
        result = repo.find_stock("AAPL")
        assert result is not None
        assert result.symbol == "AAPL"

    def test_case_insensitive_lookup(self, repo):
        """find_stock('aapl') matches 'AAPL'."""
        _seed_stock("AAPL")
        result = repo.find_stock("aapl")
        assert result is not None
        assert result.symbol == "AAPL"

    def test_returns_none_for_unknown_symbol(self, repo):
        """find_stock('ZZZZ') returns None."""
        result = repo.find_stock("ZZZZ")
        assert result is None

    def test_handles_empty_symbol(self, repo):
        """find_stock('') returns None without error."""
        result = repo.find_stock("")
        assert result is None
```

#### `find_stocks_batch` (line 58)
```python
class TestFindStocksBatch:
    def test_returns_dict_keyed_by_symbol(self, repo):
        """Batch lookup returns {SYMBOL: Stock} for all found symbols."""
        _seed_stock("AAPL"); _seed_stock("MSFT")
        result = repo.find_stocks_batch(["AAPL", "MSFT"])
        assert isinstance(result, dict)
        assert "AAPL" in result
        assert result["AAPL"].symbol == "AAPL"

    def test_missing_symbols_not_in_result(self, repo):
        """Symbols not in DB are omitted from result dict."""
        _seed_stock("AAPL")
        result = repo.find_stocks_batch(["AAPL", "ZZZZ"])
        assert "AAPL" in result
        assert "ZZZZ" not in result

    def test_empty_input_returns_empty_dict(self, repo):
        """Empty list returns {}."""
        result = repo.find_stocks_batch([])
        assert result == {}

    def test_case_insensitive_input(self, repo):
        """Lowercase input still matches uppercase DB values."""
        _seed_stock("AAPL")
        result = repo.find_stocks_batch(["aapl"])
        assert "AAPL" in result
```

#### `get_prices` (line 67)
```python
class TestGetPrices:
    def test_returns_dataframe_with_expected_columns(self, repo):
        """Returns DataFrame with OHLCV columns."""
        sid = _seed_stock("AAPL")
        _seed_price(sid, "2024-01-15", 150.0)
        df = repo.get_prices(sid, date(2024, 1, 1), date(2024, 1, 31))
        assert isinstance(df, pd.DataFrame)
        for col in ["open", "high", "low", "close", "adj_close", "volume"]:
            assert col in df.columns

    def test_date_range_filters_correctly(self, repo):
        """Only rows within [start, end] are returned."""
        sid = _seed_stock("AAPL")
        _seed_price(sid, "2024-01-01", 100.0)
        _seed_price(sid, "2024-02-01", 200.0)
        df = repo.get_prices(sid, date(2024, 1, 10), date(2024, 1, 20))
        assert len(df) == 0  # no prices in that window

    def test_no_data_returns_empty_dataframe(self, repo):
        """Returns empty DataFrame when no prices exist."""
        sid = _seed_stock("AAPL")
        df = repo.get_prices(sid, date(2020, 1, 1), date(2020, 1, 31))
        assert df.empty

    def test_invalid_stock_id_returns_empty(self, repo):
        """Non-existent stock_id returns empty DataFrame."""
        df = repo.get_prices(99999, date(2024, 1, 1), date(2024, 1, 31))
        assert df.empty
```

#### `get_prices_batch` (line 78)
```python
class TestGetPricesBatch:
    def test_returns_dict_of_dataframes(self, repo):
        """Returns {stock_id: DataFrame} for multiple stocks."""
        sid1 = _seed_stock("AAPL"); sid2 = _seed_stock("MSFT")
        _seed_price(sid1, "2024-01-15", 150.0)
        _seed_price(sid2, "2024-01-15", 300.0)
        result = repo.get_prices_batch([
            (sid1, date(2024, 1, 1), date(2024, 1, 31)),
            (sid2, date(2024, 1, 1), date(2024, 1, 31)),
        ])
        assert sid1 in result and sid2 in result
        assert len(result[sid1]) == 1

    def test_empty_input_returns_empty_dict(self, repo):
        """Empty stocks list returns {}."""
        assert repo.get_prices_batch([]) == {}

    def test_stock_with_no_prices_returns_empty_df(self, repo):
        """Stock with no data in range gets empty DataFrame."""
        sid = _seed_stock("AAPL")
        result = repo.get_prices_batch([
            (sid, date(2020, 1, 1), date(2020, 1, 31)),
        ])
        assert sid in result and result[sid].empty
```

#### `get_indicator` (line 99) + `get_snapshot` (line 104)
```python
class TestGetIndicator:
    def test_returns_indicator_for_existing_stock(self, repo):
        sid = _seed_stock("AAPL")
        _seed_indicator(sid, pe_ratio=25.0)
        result = repo.get_indicator(sid)
        assert result is not None and result.pe_ratio == 25.0

    def test_returns_none_when_no_data(self, repo):
        sid = _seed_stock("AAPL")
        assert repo.get_indicator(sid) is None


class TestGetSnapshot:
    def test_returns_snapshot_for_existing_stock(self, repo):
        sid = _seed_stock("AAPL")
        _seed_snapshot(sid, market_cap=3_000_000_000_000)
        assert repo.get_snapshot(sid) is not None

    def test_returns_none_when_no_data(self, repo):
        sid = _seed_stock("AAPL")
        assert repo.get_snapshot(sid) is None
```

#### `get_tech_indicators` (line 109)
```python
class TestGetTechIndicators:
    def test_returns_expanded_json_columns(self, repo):
        """JSON indicators column is expanded into separate DataFrame columns."""
        sid = _seed_stock("AAPL")
        _seed_tech_indicator(sid, "2024-01-15", {"sma_20": 150.0, "rsi_14": 55.0})
        df = repo.get_tech_indicators(sid, date(2024, 1, 1), date(2024, 1, 31))
        assert "sma_20" in df.columns

    def test_handles_null_indicators(self, repo):
        """Null JSON values do not crash expansion."""
        sid = _seed_stock("AAPL")
        _seed_tech_indicator(sid, "2024-01-15", None)
        df = repo.get_tech_indicators(sid, date(2024, 1, 1), date(2024, 1, 31))
        assert not df.empty  # date column still present

    def test_empty_date_range_returns_empty(self, repo):
        sid = _seed_stock("AAPL")
        df = repo.get_tech_indicators(sid, date(2020, 1, 1), date(2020, 1, 31))
        assert df.empty
```

#### `screen_stocks` (line 127)
```python
class TestScreenStocks:
    def test_filters_by_market_cap(self, repo):
        criteria = ScreenCriteria(min_market_cap=1_000_000_000_000)
        df = repo.screen_stocks(criteria)
        assert (df["Market Cap"] >= 1_000_000_000_000).all()

    def test_filters_by_pe_range(self, repo):
        criteria = ScreenCriteria(min_pe=5.0, max_pe=30.0)

    def test_filters_by_sector(self, repo):
        criteria = ScreenCriteria(sector="Technology")

    def test_filters_by_exchange(self, repo):
        criteria = ScreenCriteria(exchange="NASDAQ")

    def test_null_criteria_fields_use_sentinel_values(self, repo):
        """None fields get sentinel values (-999, 999) to match all rows."""
        criteria = ScreenCriteria()

    def test_result_limited_to_500(self, repo):
        """ORDER BY + LIMIT 500 prevents unbounded results."""

    def test_empty_database_returns_empty_dataframe(self, repo):
        """Returns DataFrame with columns but no rows."""
```

#### `list_stocks` (line 167)
```python
class TestListStocks:
    def test_returns_all_stocks_with_default_filters(self, repo):
        df = repo.list_stocks(StockFilters())

    def test_filters_by_exchange(self, repo):
        df = repo.list_stocks(StockFilters(exchange="NASDAQ"))

    def test_filters_by_sector(self, repo):
        df = repo.list_stocks(StockFilters(sector="Technology"))

    def test_market_cap_multiplied_by_billion(self, repo):
        """min_market_cap=100 → WHERE market_cap >= 100_000_000_000."""
        df = repo.list_stocks(StockFilters(min_market_cap=100.0))

    def test_status_active_filters_inactive(self, repo):
        df = repo.list_stocks(StockFilters(status="Active"))

    def test_status_inactive_filters_active(self, repo):
        df = repo.list_stocks(StockFilters(status="Inactive"))

    def test_default_thresholds_skip_filters(self, repo):
        """max_pe=999, min_roe=-200, max_beta=10 skip WHERE clauses."""
        df = repo.list_stocks(StockFilters())

    def test_empty_database_returns_empty_dataframe(self, repo):
        """Returns columns but no rows."""
```

#### `save_predict_only_results` (line 267)
```python
class TestSavePredictOnlyResults:
    def test_persists_predictions_to_selected_stocks(self, repo):
        predictions = [{"ticker": "AAPL", "ml_score": 0.85, "weight": 0.5,
                         "predicted_return": 0.12}]
        count = repo.save_predict_only_results(predictions)
        assert count == 1

    def test_does_not_set_pipeline_run_id(self, repo):
        """Unlike save_selected_stocks, no pipeline_run_id is set."""

    def test_empty_predictions_returns_zero(self, repo):
        assert repo.save_predict_only_results([]) == 0

    def test_missing_optional_fields_use_defaults(self, repo):
        predictions = [{"ticker": "AAPL"}]
        count = repo.save_predict_only_results(predictions)
        assert count == 1
```

---

### 3.2 `scheduler.py` — main() + Success Paths

```python
class TestMain:
    def test_parses_daily_run_time_from_config(self, monkeypatch):
        """Config {scheduler: {daily_run_time: '09:30'}} parses correctly."""

    def test_defaults_to_1800_when_not_configured(self, monkeypatch):
        """Missing daily_run_time defaults to '18:00'."""

    def test_defaults_timezone_to_america_new_york(self, monkeypatch):
        """Missing timezone defaults to 'America/New_York'."""

    def test_invalid_run_time_format_raises_value_error(self, monkeypatch):
        """'abc' raises ValueError during split/parsing."""

    def test_registers_daily_pipeline_job(self, monkeypatch):
        """job_daily_pipeline registered with CronTrigger."""

    def test_registers_weekly_symbol_refresh_job(self, monkeypatch):
        """job_refresh_symbols registered with CronTrigger."""

    def test_keyboard_interrupt_shutdown_gracefully(self, monkeypatch):
        """Ctrl+C triggers graceful shutdown log."""


class TestJobDailyPipelineSuccess:
    def test_success_path_records_completed(self, monkeypatch):
        """Normal execution: start → run → completed status."""

    def test_stocks_updated_count_from_summary(self, monkeypatch):
        """processed count from summary is passed to _record_job_end."""


class TestJobRefreshSymbolsSuccess:
    def test_success_path_records_completed(self, monkeypatch):
        """Normal execution: start → refresh → completed status."""

    def test_symbol_count_from_refresh(self, monkeypatch):
        """Symbol count from refresh_symbols passed to _record_job_end."""
```

---

### 3.3 `data_update.py` — _run_pipeline Body + Success Path

```python
class TestRunPipeline:
    def test_bridges_namespaced_config_to_flat(self, monkeypatch):
        """alpha_vantage key in step_cfg copied to top-level cfg."""

    def test_respects_pipeline_symbols_filter(self, monkeypatch):
        """pipeline.symbols passed to run_daily_pipeline."""

    def test_extracts_failed_symbols_from_result(self, monkeypatch):
        """Symbols with error field collected into failed_symbols."""

    def test_returns_correct_stats_structure(self, monkeypatch):
        """Return dict has symbols_attempted, symbols_succeeded, etc."""


class TestDataUpdateStepEdgeCases:
    def test_default_source_is_alpha_vantage(self, tmp_path):
        """Missing 'source' in config defaults to 'alpha_vantage'."""

    def test_zero_attempted_returns_success(self, monkeypatch, tmp_path):
        """0 symbols attempted (empty pipeline) still returns success."""

    def test_duration_is_recorded(self, monkeypatch, tmp_path):
        """duration_s field set in summary with 2 decimal places."""
```

---

### 3.4 `selectors.py` — FinrlStockSelector + Registry

```python
class TestFinrlStockSelector:
    def test_select_calls_runner_and_reads_db(self, monkeypatch):
        """select() calls _run_finrl_runner then reads from DB."""

    def test_empty_db_after_runner_returns_empty_list(self, monkeypatch):
        """No selected stocks in DB → empty list."""

    def test_scored_ticker_has_required_fields(self, monkeypatch):
        """Each ScoredTicker has ticker, ml_score, sector."""

    def test_falls_back_to_bucket_when_sector_missing(self, monkeypatch):
        """sector=None → uses bucket field."""

    def test_init_with_none_cfg_uses_empty_dict(self):
        """FinrlStockSelector(None) → self.cfg = {}."""


class TestRegistry:
    def test_register_rejects_class_without_name(self):
        """TypeError when registering class missing 'name' attr."""
        with pytest.raises(TypeError):
            class BadClass: pass
            SELECTOR_REGISTRY.register(BadClass)

    def test_names_returns_sorted_list(self):
        """names() returns sorted list of registered names."""
```

---

### 3.5 `fast_evaluators.py` — Edge Cases

```python
class TestResolveDates:
    def test_both_empty_uses_last_trading_date_and_90d_window(self):
        """start='', end='' → end=last trading date, start=end-90d."""

    def test_end_empty_uses_last_trading_date(self):
        """start='2024-01-01', end='' → end=last trading date."""

    def test_saturday_adjusts_to_friday(self, monkeypatch):
        """_last_trading_date on Saturday returns Friday."""

    def test_sunday_adjusts_to_friday(self, monkeypatch):
        """_last_trading_date on Sunday returns Friday."""


class TestComputeConsensus:
    def test_all_bullish_returns_positive(self):
        opinions = [AnalystOpinion("A", "bullish", 80, "")]

    def test_all_bearish_returns_negative(self):
        opinions = [AnalystOpinion("A", "bearish", 80, "")]

    def test_mixed_weighted_by_confidence(self):
        """High-conf bear outweighs low-conf bull."""

    def test_zero_total_confidence_returns_zero(self):
        """All confidences ≤ 0 → returns 0.0."""

    def test_empty_opinions_returns_zero(self):
        assert _compute_consensus([]) == 0.0

    def test_unknown_opinion_treated_as_neutral(self):
        """opinion='unknown' maps to 0 (neutral)."""


class TestInjectApiKeys:
    def test_does_not_overwrite_existing_env_vars(self, monkeypatch):
        """Already-set env vars preserved."""

    def test_skips_none_values(self):
        """None config values do not set env vars."""


class TestAIHedgeFundEvaluate:
    def test_empty_tickers_returns_empty_list(self):
        """Empty input → [] with warning."""

    def test_missing_ticker_in_signal_skipped(self, monkeypatch):
        """Ticker not in analyst_signals → empty opinions."""

    def test_consensus_score_computed_per_ticker(self, monkeypatch):
        """Each ticker gets its own consensus_score."""
```

---

### 3.6 `deep_evaluators.py` — Edge Cases

```python
class TestExtractDecision:
    def test_extracts_BUY_from_text(self):
        assert _extract_decision({"final_trade_decision": "BUY"}, None) == "BUY"

    def test_extracts_SELL_from_mixed_case(self):
        assert _extract_decision({"final_trade_decision": "Sell now"}, None) == "SELL"

    def test_falls_back_to_decision_param(self):
        assert _extract_decision({}, "HOLD") == "HOLD"

    def test_no_decision_returns_empty_string(self):
        assert _extract_decision({}, None) == ""

    def test_partial_word_not_matched(self):
        """'BUYING' does not match 'BUY' token boundary."""
        assert _extract_decision({"final_trade_decision": "BUYING"}, None) == ""


class TestTradingAgentsEvaluate:
    def test_empty_tickers_returns_empty_list(self):
        """Empty input → [] with warning."""

    def test_thread_pool_parallel_evaluation(self, monkeypatch):
        """Multiple tickers evaluated in parallel via ThreadPoolExecutor."""

    def test_ticker_failure_skipped_with_log(self, monkeypatch):
        """Failed ticker caught, logged, skipped — others proceed."""

    def test_max_3_workers(self, monkeypatch):
        """ThreadPoolExecutor max_workers capped at min(len(tickers), 3)."""

    def test_tuple_result_handled(self, monkeypatch):
        """(final_state, decision) tuple properly unpacked."""

    def test_dict_result_handled(self, monkeypatch):
        """Dict treated as final_state with None decision."""

    def test_messages_key_excluded_from_outputs(self, monkeypatch):
        """'messages' key (LangChain objects) excluded from agent_outputs."""

    def test_news_cache_install_failure_handled(self, monkeypatch):
        """Failed news_cache install logs warning but continues."""

    def test_api_keys_injected_before_graph_build(self, monkeypatch):
        """API keys set in os.environ before TradingAgentsGraph creation."""
```

---

### 3.7 `src/ui/cached_repo.py` — Cached Repository Wrapper

```python
class TestCachedRepo:
    def test_caches_first_call_result(self):
        """First call populates cache; subsequent calls return cached value."""

    def test_cache_invalidation_on_update(self):
        """After data update, cache invalidated and refreshed."""

    def test_different_methods_have_separate_caches(self):
        """get_summary cache ≠ get_sectors cache."""

    def test_cache_key_includes_arguments(self):
        """Different filter args produce different cache entries."""
```

---

### 3.8 Missing Error Handling Tests (Cross-Cutting)

```python
class TestDatabaseErrorHandling:
    def test_session_close_on_exception(self):
        """Session always closed even when query raises."""

    def test_connection_deadlock_retry(self):
        """MySQL 1213 deadlock triggers retry in ingestion pipeline."""

    def test_transaction_rollback_on_error(self):
        """Failed batch insert rolls back entire transaction."""


class TestFetcherErrorHandling:
    def test_alpha_vantage_rate_limit_429(self):
        """HTTP 429 triggers rate-limit wait and retry."""

    def test_alpha_vantage_service_unavailable_503(self):
        """HTTP 503 triggers retry with backoff."""

    def test_network_timeout_retry(self):
        """Connection timeout triggers retry, not immediate failure."""

    def test_invalid_api_key_response(self):
        """AV error message for invalid key handled gracefully."""

    def test_yfinance_empty_response(self):
        """yfinance returns empty DataFrame for delisted symbol."""


class TestPipelineErrorPropagation:
    def test_step_failure_stops_orchestrator(self):
        """Failed step prevents subsequent steps from executing."""

    def test_resume_from_skips_completed_steps(self):
        """--resume-from skips steps before the named one."""

    def test_report_written_even_on_failure(self):
        """Step report JSON written even when step fails."""
```

---

### 3.9 Integration Test Gaps

```python
class TestDataUpdateIntegration:
    """Test _run_pipeline without monkeypatching — real DB + mock fetcher."""

    def test_end_to_end_data_update_with_mock_fetcher(self):
        """Full flow: config → fetcher → pipeline → DB."""

    def test_symbol_filtering_integration(self):
        """--symbols option flows through to ingestion pipeline."""


class TestStockSelectionIntegration:
    """Test FinRL runner integration with real CSV output parsing."""

    def test_ml_output_to_db_to_selection_flow(self):
        """CSV → DB → StockRepository.get_latest_selected_stocks()."""


class TestSchedulerIntegration:
    """Test scheduler job lifecycle with real (but short) cron intervals."""

    def test_job_registration_and_execution(self):
        """Job registered, triggered, and recorded end-to-end."""

    def test_concurrent_job_safety(self):
        """APScheduler handles overlapping job runs safely."""


class TestPipelineE2E:
    """Full pipeline orchestration with mock backends — partially covered."""

    def test_symbols_option_skips_ml_selection(self):
        """--symbols makes stock_selection pass through without ML."""

    def test_run_id_persistence_across_steps(self):
        """Same pipeline_run_id used by all steps."""
```

---

## 4. Shared Test Infrastructure (conftest.py)

```python
# tests/conftest.py
import logging
import pytest
from database import configure, init_db, get_session

@pytest.fixture(scope="function")
def db_engine():
    """In-memory SQLite engine for isolated DB tests."""
    configure("sqlite:///:memory:")
    init_db()
    yield

@pytest.fixture
def db_session(db_engine):
    """Session bound to test DB."""
    s = get_session()
    yield s
    s.close()

@pytest.fixture
def repo(db_session):
    """StockRepository with test session override."""
    from repository import StockRepository
    r = StockRepository()
    r._get_session = lambda: db_session
    return r

def _seed_stock(symbol="AAPL", **kwargs):
    """Insert a stock row. Returns stock id."""
    ...

def _seed_price(stock_id, date_str, close_price):
    """Insert a daily_prices row."""
    ...

def _seed_indicator(stock_id, **fields):
    """Insert or update a stock_indicator row."""
    ...

def _seed_snapshot(stock_id, **fields):
    """Insert a stock_snapshot row."""
    ...

def _seed_tech_indicator(stock_id, date_str, indicators):
    """Insert a technical_indicator row with JSON blob."""
    ...

def pytest_configure(config):
    config.addinivalue_line("markers", "unit: fast unit tests")
    config.addinivalue_line("markers", "integration: tests requiring DB/network")
    config.addinivalue_line("markers", "e2e: end-to-end tests (Playwright/Streamlit)")
    config.addinivalue_line("markers", "slow: tests that take > 1 second")
```

---

## 5. Remediation Plan

### Phase 1: Fix Blockers (1-2 hours)
- Fix arity bug in `test_pipeline_data_update.py` (4 monkeypatches)
- Fix `test_repository.py` — replace removed method calls with current API
- Fix `test_scheduler.py` — conditional pool args in `database.py::configure()`
- Fix `test_database.py` — MEDIUMTEXT compatibility for SQLite
- **Expected**: 28 tests unblocked, ~13% coverage gain

### Phase 2: Repository Layer (3-4 hours)
- 40 tests for 10 untested methods
- Seed data helpers: `_seed_price()`, `_seed_indicator()`, `_seed_snapshot()`, `_seed_tech_indicator()`
- Test dynamic SQL builders (`screen_stocks`, `list_stocks`) with filter combinations
- **Expected**: repository.py 27% → 75%+

### Phase 3: Scheduler + Data Update (2-3 hours)
- 15 tests: `main()` config parsing, job success paths
- 10 tests: `_run_pipeline` body, `DataUpdateStep` edge cases
- **Expected**: scheduler.py 23% → 70%+, data_update.py 43% → 85%+

### Phase 4: Backend Edge Cases (2-3 hours)
- 15 tests: selectors (registry, FinrlStockSelector)
- 20 tests: fast_evaluators (dates, consensus, API keys, empty inputs)
- 20 tests: deep_evaluators (decision extraction, thread pool, error handling)
- **Expected**: selectors 70% → 90%+, fast/deep evaluators 81% → 92%+

### Phase 5: Integration + Error Handling (3-4 hours)
- 10 integration tests with mock fetcher + real DB
- 15 error handling tests (DB deadlock, HTTP retry, session cleanup)
- Create shared `conftest.py` with fixtures, markers, and SQLite helpers
- **Target**: 65-80% overall coverage

---

## 6. Summary Statistics

| Metric | Current | Target |
|--------|---------|--------|
| Overall coverage | 29% | 65-80% |
| Test files | 21 | 35+ |
| Test functions | ~160 | ~350+ |
| Passing tests | ~128 | ~330+ |
| Failing tests | 13 | 0 |
| Error tests | 19 | 0 |
| 0% coverage modules | 18 | 5 (UI only) |
| Critical modules < 30% | 3 | 0 |
| Shared fixtures (conftest) | 0 | 1 |
