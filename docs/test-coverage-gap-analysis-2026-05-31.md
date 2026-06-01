# AIStock Test Coverage Gap Analysis v2
**Date**: 2026-05-31
**Baseline**: ~10,180 source LOC, ~3,017 test LOC → ~30% test-to-source ratio
**Framework**: pytest + monkeypatch + sqlite in-memory

---

## Summary

| Status | Count | Source LOC | Test LOC | Est. Coverage |
|--------|-------|-----------|----------|---------------|
| Covered (has tests) | 11 modules | ~3,500 | ~3,017 | ~60% |
| Untested (0 tests) | 16 modules | ~6,680 | 0 | **0%** |

**65% of source code has zero coverage.** Core modules `ingestion/pipeline.py` (623L), `ta_run.py` (510L), `models.py` (429L), `finrl_runner.py` (390L), `app.py` (332L) are completely untested.

---

## Section 1: Completely Untested Modules (0% coverage)

### 1.1 `src/models.py` (429 lines) — CRITICAL

15 SQLAlchemy/dataclass models. Every module depends on these.

| Entity | Lines | Risk |
|--------|-------|------|
| `Base` | L11 | Base class |
| `Stock` | L15-44 | HIGH — core entity |
| `DailyPrice` | L45-67 | HIGH — all OHLCV data |
| `StockIndicator` | L68-117 | HIGH — fundamental indicators |
| `TechnicalIndicator` | L118-134 | MEDIUM — JSON blob storage |
| `StockSnapshot` | L135-167 | HIGH — screening lookup |
| `ScheduledJobRun` | L168-179 | HIGH — job tracking |
| `PipelineRun` | L180-190 | HIGH — pipeline metadata |
| `QuarterlyFundamentals` | L191-299 | HIGH — 70+ financial fields |
| `SelectedStock` | L300-327 | HIGH — ML output decisions |
| `StockNews` | L328-349 | MEDIUM — news storage |
| `FastEvaluationConclusion` | L350-375 | MEDIUM — LLM eval cache |
| `FastEvaluationAnalyst` | L376-397 | MEDIUM — analyst config |
| `DeepEvaluationRow` | L398-422 | MEDIUM — deep eval results |
| `SchemaMigration` | L423-429 | LOW — migration tracking |

```python
# tests/test_models.py
import pytest
from datetime import date
from sqlalchemy import create_engine, exc
from sqlalchemy.orm import Session
from src.models import Base, Stock, DailyPrice, StockIndicator, StockSnapshot
from src.models import ScheduledJobRun, PipelineRun, QuarterlyFundamentals
from src.models import SelectedStock, TechnicalIndicator, StockNews
from src.models import FastEvaluationConclusion, FastEvaluationAnalyst, DeepEvaluationRow

@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    return e

@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s

class TestStock:
    def test_create_minimal_fields(self, session):
        s = Stock(symbol="AAPL")
        session.add(s)
        session.commit()
        assert s.id is not None
        assert s.active is True

    def test_symbol_unique_constraint(self, session):
        session.add(Stock(symbol="AAPL"))
        session.commit()
        session.add(Stock(symbol="AAPL"))
        with pytest.raises(exc.IntegrityError):
            session.commit()

    def test_all_fields_persisted(self, session):
        s = Stock(symbol="MSFT", name="Microsoft Corp", sector="Technology",
                   exchange="NASDAQ", currency="USD", country="US",
                   industry="Software", shares_outstanding=7_500_000_000)
        session.add(s)
        session.commit()
        got = session.get(Stock, s.id)
        assert got.sector == "Technology"
        assert got.shares_outstanding == 7_500_000_000

class TestDailyPrice:
    def test_create_price(self, session):
        s = Stock(symbol="AAPL")
        session.add(s); session.commit()
        dp = DailyPrice(stock_id=s.id, date=date(2026, 5, 30),
                        open=190.0, high=195.0, low=189.0, close=194.0, volume=50_000_000)
        session.add(dp)
        session.commit()
        assert dp.id is not None

    def test_stock_date_unique(self, session):
        s = Stock(symbol="AAPL")
        session.add(s); session.commit()
        session.add(DailyPrice(stock_id=s.id, date=date(2026,5,30),
                    open=190, high=195, low=189, close=194, volume=5e7))
        session.commit()
        session.add(DailyPrice(stock_id=s.id, date=date(2026,5,30),
                    open=191, high=196, low=190, close=195, volume=5e7))
        with pytest.raises(exc.IntegrityError):
            session.commit()

    def test_nullable_dividend_split(self, session):
        s = Stock(symbol="AAPL")
        session.add(s); session.commit()
        dp = DailyPrice(stock_id=s.id, date=date(2026,5,30),
                        open=190, high=195, low=189, close=194, volume=5e7)
        session.add(dp)
        session.commit()
        assert dp.dividend_amount is None
        assert dp.split_coefficient is None

class TestQuarterlyFundamentals:
    def test_create_fundamentals(self, session):
        s = Stock(symbol="AAPL")
        session.add(s); session.commit()
        qf = QuarterlyFundamentals(
            stock_id=s.id, symbol="AAPL",
            fiscal_date_ending=date(2025, 12, 31),
            revenue=124_300_000_000, eps=2.40, net_income=36_300_000_000)
        session.add(qf)
        session.commit()
        assert qf.id is not None

    def test_nullable_fields_handled(self, session):
        s = Stock(symbol="AAPL")
        session.add(s); session.commit()
        qf = QuarterlyFundamentals(stock_id=s.id, symbol="AAPL",
                                    fiscal_date_ending=date(2025, 12, 31))
        session.add(qf)
        session.commit()
        assert qf.revenue is None

class TestSelectedStock:
    def test_create_selection(self, session):
        s = Stock(symbol="AAPL")
        session.add(s); session.commit()
        sel = SelectedStock(pipeline_run_id=1, stock_id=s.id, symbol="AAPL",
                            sector="Technology", ml_score=0.85, weight=0.25)
        session.add(sel)
        session.commit()
        assert sel.id is not None

    def test_predict_only_flag(self, session):
        s = Stock(symbol="AAPL")
        session.add(s); session.commit()
        sel = SelectedStock(pipeline_run_id=1, stock_id=s.id, symbol="AAPL",
                            sector="Technology", ml_score=0.85, weight=0.0,
                            predict_only=True)
        session.add(sel)
        session.commit()
        assert sel.predict_only is True

class TestPipelineRun:
    def test_create_run(self, session):
        pr = PipelineRun(status="started", symbols_processed=0)
        session.add(pr)
        session.commit()
        assert pr.id is not None
        assert pr.started_at is not None

class TestStockSnapshot:
    def test_create_snapshot(self, session):
        s = Stock(symbol="AAPL")
        session.add(s); session.commit()
        snap = StockSnapshot(stock_id=s.id, market_cap=3_000_000_000_000,
                             sector="Technology", price=195.0)
        session.add(snap)
        session.commit()
        assert snap.stock_id == s.id

class TestScheduledJobRun:
    def test_job_lifecycle(self, session):
        jr = ScheduledJobRun(job_name="daily_pipeline", status="running")
        session.add(jr)
        session.commit()
        assert jr.started_at is not None
        jr.status = "success"
        jr.finished_at = date(2026, 5, 30)
        session.commit()
        assert jr.status == "success"
```

---

### 1.2 `src/ingestion/pipeline.py` (623 lines) — CRITICAL

Largest single module. 13 functions, entire data ingestion logic.

| Function | Lines | Difficulty |
|----------|-------|------------|
| `_last_trading_date()` | L30-69 | EASY — pure date logic |
| `_prefetch_stock_dates()` | L70-144 | MEDIUM — DB read |
| `_fetch_and_store_prices()` | L145-212 | MEDIUM — API + DB |
| `_upsert_fundamentals()` | L213-289 | MEDIUM — API + DB |
| `_refresh_snapshots()` | L290-338 | MEDIUM — DB write |
| `_batch_update_checkpoints()` | L339-353 | EASY — DB write |
| `_needs_full_backfill()` | L354-378 | EASY — decision logic |
| `_fetch_stock_news()` | L379-415 | HARD — API + DB |
| `_fetch_stock_news_av()` | L416-442 | HARD — API + DB |
| `_process_symbol()` | L443-487 | HARD — orchestrator |
| `run_daily_pipeline()` | L488-580 | HARD — entry point |
| `run_bootstrap()` | L581-606 | HARD — backfill entry |
| `_auto_activate()` | L607-621 | EASY — DB mutation |

```python
# tests/test_ingestion_pipeline.py
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from src.ingestion.pipeline import (
    _last_trading_date, _needs_full_backfill, _auto_activate,
    _batch_update_checkpoints, _prefetch_stock_dates,
    _fetch_and_store_prices, _upsert_fundamentals,
    _refresh_snapshots, _fetch_stock_news, _process_symbol,
    run_daily_pipeline, run_bootstrap,
)

class TestLastTradingDate:
    def test_monday_returns_last_friday(self):
        assert _last_trading_date(ref=date(2026, 6, 1)) == date(2026, 5, 29)

    def test_tuesday_returns_monday(self):
        assert _last_trading_date(ref=date(2026, 6, 2)) == date(2026, 6, 1)

    def test_saturday_returns_friday(self):
        assert _last_trading_date(ref=date(2026, 6, 6)) == date(2026, 6, 5)

    def test_sunday_returns_friday(self):
        assert _last_trading_date(ref=date(2026, 6, 7)) == date(2026, 6, 5)

    def test_returns_date_not_datetime(self):
        result = _last_trading_date()
        assert isinstance(result, date)
        assert not isinstance(result, datetime)

class TestNeedsFullBackfill:
    def test_no_prices_returns_true(self):
        assert _needs_full_backfill(last_price_date=None) is True

    def test_old_prices_returns_true(self):
        assert _needs_full_backfill(last_price_date=date(2020, 1, 1)) is True

    def test_recent_prices_returns_false(self):
        assert _needs_full_backfill(last_price_date=date(2026, 5, 29)) is False

class TestAutoActivate:
    @patch("src.ingestion.pipeline.get_session")
    def test_stocks_with_prices_activated(self, mock_session):
        ...

    @patch("src.ingestion.pipeline.get_session")
    def test_already_active_unchanged(self, mock_session):
        ...

    @patch("src.ingestion.pipeline.get_session")
    def test_stocks_without_prices_not_activated(self, mock_session):
        ...

class TestFetchAndStorePrices:
    @patch("src.ingestion.pipeline.get_session")
    def test_fetches_and_inserts_daily_prices(self, mock_session):
        ...

    def test_upsert_handles_existing_rows(self):
        ...

    def test_empty_api_response_graceful(self):
        """No data from API → skip, no crash"""

    def test_network_error_logged_not_crashed(self):
        """ConnectionError → logged, pipeline continues"""

class TestUpsertFundamentals:
    @patch("src.ingestion.pipeline.get_session")
    def test_fundamentals_inserted(self, mock_session):
        ...

    def test_empty_quarterly_data_handled(self):
        ...

    def test_null_financial_fields_accepted(self):
        """Some fields null → others still inserted"""

class TestRunDailyPipeline:
    @patch("src.ingestion.pipeline._process_symbol")
    @patch("src.ingestion.pipeline._fetch_stock_news")
    @patch("src.ingestion.pipeline._auto_activate")
    def test_full_flow_runs(self, *mocks):
        ...

    def test_single_stock_failure_does_not_block_others(self):
        """One stock fails → remaining still processed"""

    def test_empty_stock_list_no_error(self):
        """Zero active stocks → no error, return empty report"""

    def test_progress_reported_per_batch(self):
        ...

class TestRunBootstrap:
    @patch("src.ingestion.pipeline._process_symbol")
    def test_historical_backfill_called(self, mock_process):
        ...

    def test_symbol_limit_respected(self):
        ...
```

---

### 1.3 `src/finrl_runner.py` (390 lines) — HIGH

ML-to-trade bridge. Backtesting, portfolio metrics, selection summary.

```python
# tests/test_finrl_runner.py
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from src.finrl_runner import (
    run_pipeline_and_save_report, run_predict_only,
    _equal_weight_fallback, _run_simple_backtest,
    _compute_metrics, _build_selection_summary,
)

class TestComputeMetrics:
    def test_positive_returns(self):
        r = pd.Series([0.01, 0.02, -0.005, 0.03, 0.01])
        m = _compute_metrics(r)
        assert m["total_return"] > 0
        assert "sharpe_ratio" in m
        assert "max_drawdown" in m
        assert "win_rate" in m

    def test_all_negative(self):
        r = pd.Series([-0.01, -0.02, -0.01])
        m = _compute_metrics(r)
        assert m["total_return"] < 0
        assert m["win_rate"] == 0.0

    def test_empty_returns(self):
        m = _compute_metrics(pd.Series([], dtype=float))
        assert m["total_return"] == 0.0

    def test_single_return(self):
        m = _compute_metrics(pd.Series([0.05]))
        assert m["total_return"] == 0.05

    def test_sharpe_zero_std(self):
        """All returns identical → sharpe 0, no div-by-zero"""
        r = pd.Series([0.01, 0.01, 0.01])
        m = _compute_metrics(r)
        assert m["sharpe_ratio"] == 0.0

class TestEqualWeightFallback:
    def test_selects_top_quantile(self):
        ...

    def test_empty_input(self):
        ...

    def test_all_same_score(self):
        """Identical scores → all selected"""
        ...

class TestRunSimpleBacktest:
    @patch("src.finrl_runner.get_session")
    def test_backtest_returns_json_path(self, mock_session):
        ...

    def test_benchmark_comparison_included(self):
        """SPY/QQQ benchmarks appear in backtest results"""
        ...

class TestRunPredictOnly:
    @patch("src.finrl_runner.MLBucketSelector")
    def test_skips_data_refresh(self, mock_selector):
        ...

class TestRunPipelineAndSaveReport:
    @patch("src.finrl_runner.run_daily_pipeline")
    @patch("src.finrl_runner._run_simple_backtest")
    def test_pipeline_then_backtest_ordering(self, mock_bt, mock_pipeline):
        ...
```

---

### 1.4 `src/ta_run.py` (510 lines) — HIGH

Technical analysis runner. LLM summarization, report generation.

```python
# tests/test_ta_run.py
import pytest
from unittest.mock import MagicMock, patch, mock_open
from src.ta_run import (_emit, _is_empty, _CallTracker,
    _save_report, _summarise_report, _print_summary, main)

class TestIsEmpty:
    def test_none(self): assert _is_empty(None) is True
    def test_empty_str(self): assert _is_empty("") is True
    def test_whitespace(self): assert _is_empty("   ") is True
    def test_nonempty(self): assert _is_empty("AAPL") is False
    def test_zero(self): assert _is_empty(0) is False
    def test_false(self): assert _is_empty(False) is False

class TestCallTracker:
    def test_tracks_call_count(self):
        ...
    def test_computes_token_cost(self):
        ...
    def test_max_retry_exceeded_raises(self):
        ...
    def test_empty_response_retried(self):
        ...

class TestSaveReport:
    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_saves_markdown_report(self, mock_mkdir, mock_file):
        ...

class TestSummariseReport:
    @patch("src.ta_run.ChatOpenAI")
    def test_llm_summary_generated(self, mock_llm):
        ...

class TestMain:
    @patch("sys.argv", ["ta_run.py", "--symbols", "AAPL,MSFT"])
    def test_cli_args_parsed(self):
        ...
```

---

### 1.5 `src/ml_bucket_selector.py` (191 lines) — MEDIUM

```python
# tests/test_ml_bucket_selector.py
import pytest
import pandas as pd
import numpy as np
from src.ml_bucket_selector import MLBucketSelector

class TestMLBucketSelector:
    @pytest.fixture
    def sample_data(self):
        np.random.seed(42)
        return pd.DataFrame({
            "symbol": ["A"] * 50 + ["B"] * 50,
            "return_1d": np.random.randn(100),
            "return_5d": np.random.randn(100),
            "volume_ratio": np.random.uniform(0.5, 2, 100),
            "rsi": np.random.uniform(20, 80, 100),
        })

    def test_fit_predict_returns_buckets(self, sample_data):
        selector = MLBucketSelector(n_buckets=3)
        result = selector.fit_predict(sample_data)
        assert "bucket" in result.columns

    def test_empty_dataframe(self):
        result = MLBucketSelector().fit_predict(pd.DataFrame())
        assert result.empty

    def test_input_not_mutated(self, sample_data):
        original = sample_data.copy()
        MLBucketSelector().fit_predict(sample_data)
        pd.testing.assert_frame_equal(original, sample_data)

    def test_single_stock_handled(self):
        ...

    def test_missing_columns_raises(self):
        ...

    def test_all_identical_values(self):
        ...

    def test_save_models_writes_files(self, tmp_path, sample_data):
        ...
```

---

### 1.6 `src/app.py` (332 lines) — HIGH

```python
# tests/test_app.py
import pytest
from unittest.mock import MagicMock, patch
from src.app import (PageContext, _QueueHandler, _StdoutToQueue,
    _pipeline_thread_target, _predict_only_thread_target,
    display_quick_stats, _build_ctx, sidebar_nav, render_page_content, main)

class TestQueueHandler:
    def test_emit_appends_to_queue(self):
        ...
    def test_full_queue_handled_gracefully(self):
        """Queue full → log dropped, no exception"""

class TestStdoutToQueue:
    def test_write_appends_to_queue(self):
        ...
    def test_flush_is_noop(self):
        ...

class TestPageContext:
    def test_context_holds_page_registry(self):
        ...
    def test_register_page_adds_entry(self):
        ...

class TestPipelineThreadTarget:
    @patch("src.app.run_pipeline_and_save_report")
    def test_pipeline_called_in_thread(self, mock_run):
        ...
    def test_exception_logged_not_crashed(self):
        ...

class TestPredictOnlyThreadTarget:
    @patch("src.app.run_predict_only")
    def test_predict_only_called(self, mock_run):
        ...

class TestBuildCtx:
    @patch("src.app.get_session")
    def test_ctx_includes_repository(self, mock_session):
        ...

class TestDisplayQuickStats:
    @patch("streamlit.metric")
    def test_stats_displayed(self, mock_metric):
        ...

    def test_empty_database_shows_zeros(self):
        """No stocks → stats show 0, not crash"""
        ...
```

---

### 1.7 `src/fetcher/alpha_vantage.py` (317 lines) — MEDIUM

```python
# tests/test_alpha_vantage.py
import pytest
import responses
from src.fetcher.alpha_vantage import AlphaVantageFetcher

class TestAlphaVantageFetcher:
    @pytest.fixture
    def fetcher(self):
        return AlphaVantageFetcher(api_key="test-key")

    @responses.activate
    def test_get_daily_returns_prices(self, fetcher):
        ...

    @responses.activate
    def test_rate_limit_429_retried(self, fetcher):
        ...

    @responses.activate
    def test_api_key_invalid_raises(self, fetcher):
        ...

    @responses.activate
    def test_network_timeout_handled(self, fetcher):
        ...

    @responses.activate
    def test_malformed_json_handled(self, fetcher):
        ...

    @responses.activate
    def test_empty_response_handled(self, fetcher):
        ...

    @responses.activate
    def test_get_overview(self, fetcher):
        ...

    @responses.activate
    def test_get_income_statement(self, fetcher):
        ...

    @responses.activate
    def test_get_balance_sheet(self, fetcher):
        ...

    @responses.activate
    def test_get_cash_flow(self, fetcher):
        ...

    @responses.activate
    def test_get_earnings(self, fetcher):
        ...

    @responses.activate
    def test_get_listing_downloads_csv(self, fetcher):
        ...

    @responses.activate
    def test_get_news_sentiment(self, fetcher):
        ...
```

---

### 1.8 `src/ingestion/indicators.py` (138 lines) — MEDIUM

```python
# tests/test_indicators.py
import pytest
import pandas as pd
import numpy as np
from src.ingestion.indicators import compute_indicators

class TestComputeIndicators:
    @pytest.fixture
    def prices(self):
        dates = pd.date_range("2024-01-01", periods=200, freq="B")
        np.random.seed(42)
        price = 100 + np.cumsum(np.random.randn(200) * 2)
        return pd.DataFrame({
            "date": dates, "open": price*0.99, "high": price*1.02,
            "low": price*0.98, "close": price,
            "volume": np.random.randint(1e6, 1e7, 200),
        })

    def test_all_indicators_present(self, prices):
        r = compute_indicators(prices)
        for col in ["rsi", "macd", "macd_signal", "bb_upper", "bb_lower",
                     "sma_20", "sma_50", "volume_sma"]:
            assert col in r.columns

    def test_insufficient_data_returns_empty(self):
        short = pd.DataFrame({"close": [100]*20, "high": [102]*20,
                              "low": [98]*20, "volume": [1e6]*20})
        r = compute_indicators(short)
        assert r.empty

    def test_rsi_bounded_0_to_100(self, prices):
        r = compute_indicators(prices)
        assert r["rsi"].between(0, 100).all()

    def test_all_same_price_no_div_zero(self):
        ...

    def test_nan_in_input_handled(self):
        ...

    def test_missing_columns_raises_keyerror(self):
        ...
```

---

### 1.9-1.14 Remaining untested modules

| Module | Lines | Functions/Classes | Priority |
|--------|-------|-------------------|----------|
| `config.py` | ~20 | `load_config()` | P3 |
| `display.py` | ~15 | `fmt_market_cap()` | P3 |
| `main.py` | 132 | `cmd_init_db()`, `cmd_bootstrap()`, `cmd_run()`, `main()` | P3 |
| `full_pipeline.py` | 146 | `parse_args()`, `_setup_logging()`, `_build_session_factory()`, `main()` | P2 |
| `ui/pages/stock_detail.py` | 187 | `render()` | P3 |
| `ui/pages/ml_pipeline.py` | 460 | `_load_ml_results()`, `_load_ml_backtest()`, `_show_ml_results()`, `_show_ml_backtest()`, `_show_predict_only_results()`, `render()` | P2 |
| `logging_config.py` | ~15 | `setup_logging()` | P3 |

Compact test skeletons for each:

```python
# tests/test_config.py
class TestLoadConfig:
    def test_loads_yaml_file(self, tmp_path): ...
    def test_missing_file_raises(self): ...
    def test_invalid_yaml_raises(self, tmp_path): ...
    def test_env_var_override(self, monkeypatch, tmp_path): ...
    def test_config_cached_second_call(self, tmp_path): ...

# tests/test_display.py
class TestFmtMarketCap:
    def test_trillions(self): assert fmt_market_cap(2.5e12) == "$2.50T"
    def test_billions(self): assert fmt_market_cap(5e11) == "$500.00B"
    def test_millions(self): assert fmt_market_cap(1.5e8) == "$150.00M"
    def test_zero(self): assert fmt_market_cap(0) == "$0.00"
    def test_none(self): assert fmt_market_cap(None) in ("N/A", "—")

# tests/test_main.py
class TestCmdInitDb:
    @patch("src.main.init_db")
    def test_init_db_called(self, mock_init): ...
class TestCmdBootstrap:
    @patch("src.main.run_bootstrap")
    def test_bootstrap_called(self, mock_run): ...
class TestMain:
    @patch("sys.argv", ["main.py", "init-db"])
    def test_init_db_subcommand(self): ...

# tests/test_logging_config.py
class TestSetupLogging:
    def test_returns_logger(self): ...
    def test_level_set(self): ...
    def test_idempotent_call(self): ...
    def test_console_handler_added(self): ...

# tests/test_ui_stock_detail.py
class TestStockDetailRender:
    @patch("streamlit.header")
    def test_renders_header(self, mock_header): ...
    def test_no_stock_selected_shows_message(self): ...
    def test_price_chart_displayed(self): ...

# tests/test_ui_ml_pipeline.py
class TestLoadMlResults:
    @patch("src.ui.pages.ml_pipeline.get_session")
    def test_loads_latest_selections(self, mock_session): ...
    def test_empty_results_returns_empty_df(self): ...
class TestShowMlResults:
    @patch("streamlit.dataframe")
    def test_displays_results_table(self, mock_df): ...
class TestRender:
    @patch("streamlit.header")
    def test_render_shows_title(self, mock_header): ...
```

---

## Section 2: Error Handling Test Gaps (Cross-Cutting)

### 2.1 Database Errors
```python
# tests/test_error_handling_db.py

def test_connection_lost_during_transaction():
    """OperationalError → rollback + retry"""

def test_deadlock_retry_up_to_3_times():
    """SQLite busy / DB deadlock → retry logic → then raise"""

def test_foreign_key_violation_clear_message():
    """IntegrityError on missing FK → human-readable error"""

def test_unique_constraint_violation_caught():
    """Duplicate unique key → IntegrityError caught gracefully"""

def test_table_not_found_helpful_message():
    """'no such table' → error suggests running init_db/migrations"""
```

### 2.2 API/Network Errors
```python
# tests/test_error_handling_api.py

def test_request_timeout_exponential_backoff():
    """ReadTimeout → backoff 1s, 2s, 4s → retry 3x"""

def test_rate_limit_429_waits_retry_after():
    """HTTP 429 → wait Retry-After header → retry"""

def test_server_error_5xx_retried():
    """500/502/503 → retry with backoff"""

def test_client_error_4xx_fail_fast():
    """400/401/403/404 → do NOT retry, raise immediately"""

def test_malformed_json_returns_safe_default():
    """JSONDecodeError → logged, returns empty result"""

def test_connection_refused_graceful_degradation():
    """ConnectionError → clear message, no stack trace leak"""

def test_empty_response_body_handled():
    """200 OK with empty body → safe default"""
```

### 2.3 Data Integrity Errors
```python
# tests/test_error_handling_data.py

def test_nan_in_calculation_logged():
    """NaN input → NaN output logged → not silently propagated"""

def test_zero_division_in_sharpe_ratio():
    """Std dev = 0 → sharpe = 0, not ZeroDivisionError"""

def test_negative_price_value_handled():
    """Price < 0 → logged warning, not crash"""

def test_dataframe_column_mismatch_helpful_keyerror():
    """Expected column missing → KeyError with context"""

def test_null_foreign_key_integrity_error():
    """NULL FK → IntegrityError with column name"""
```

---

## Section 3: Integration Test Gaps

| Flow | Status | Priority |
|------|--------|----------|
| Daily pipeline: ingestion → indicators → evaluation → selection | ❌ No E2E test | **CRITICAL** |
| Bootstrap: empty DB → full backfill → operational | ❌ No test | HIGH |
| Predict-only: existing data → ML selection → backtest | ❌ No test | HIGH |
| Config-driven pipeline variant selection | ❌ No test | MEDIUM |
| Scheduled job: cron → pipeline → status update | ⚠️ Unit only | MEDIUM |
| LLM evaluation: stock data → analyst opinions → consensus | ❌ No integration | MEDIUM |
| Data flow integrity: Stock → Price → Indicator → Snapshot → Selection | ❌ No test | MEDIUM |

```python
# tests/test_integration_daily_pipeline.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.models import Base, Stock

@pytest.mark.integration
class TestDailyPipelineIntegration:
    @pytest.fixture
    def engine(self):
        e = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(e)
        return e

    @pytest.fixture
    def db_with_stocks(self, engine):
        with Session(engine) as s:
            s.add(Stock(symbol="AAPL", name="Apple Inc.", active=True))
            s.add(Stock(symbol="MSFT", name="Microsoft Corp.", active=True))
            s.commit()

    def test_full_flow_empty_db_to_selection(self, db_with_stocks):
        """1. Ingest → 2. Compute indicators → 3. Evaluate → 4. Select"""
        ...

    def test_rollback_on_mid_pipeline_failure(self, db_with_stocks):
        """Mid-pipeline failure → DB state unchanged"""
        ...

    def test_idempotent_pipeline_rerun(self, db_with_stocks):
        """Running pipeline twice → no duplicate data"""
        ...

    def test_concurrent_pipeline_run_detected(self, db_with_stocks):
        """Two simultaneous runs → one wins, lock detected"""
        ...

    def test_data_propagates_through_pipeline(self, db_with_stocks):
        """Verify: ingestion output → evaluation input → selection output"""
        ...
```

---

## Section 4: Edge Cases Missing in Existing Tests

### `utils.py` additions
```python
def test_safe_float_scientific_notation():
    assert safe_float("1.5e-3") == 0.0015

def test_safe_float_unicode_minus():
    assert safe_float("−100") == -100  # minus sign, not hyphen

def test_safe_float_boolean():
    assert safe_float(True) is None

def test_safe_int_overflow():
    assert safe_int("99999999999999999999") == 99999999999999999999

def test_nan_safe_nested_dict():
    assert nan_safe({"a": {"b": float("nan")}}) == {"a": {"b": None}}
```

### `repository.py` additions
```python
def test_get_prices_reversed_date_range(self, repo):
    """start > end → returns empty, not error"""

def test_get_prices_batch_empty_list(self, repo):
    """[] → {}"""

def test_save_selected_stocks_empty_list(self, repo):
    """[] → no-op"""

def test_count_summary_after_bulk_delete(self, repo):
    """Consistent counts after mass deletion"""

def test_bulk_set_active_nonexistent_ids(self, repo):
    """Non-existent stock_ids → silently skipped"""
```

### `scheduler.py` additions
```python
def test_overlapping_job_prevented(self):
    """Job running → second invocation skipped"""

def test_job_timeout_handled(self):
    """Job exceeds max runtime → marked failed"""

def test_midnight_boundary_handled(self):
    """Job spans midnight → date tracked correctly"""
```

---

## Section 5: Priority & Effort Matrix

| Priority | Module | Lines | Est. Hours | Impact |
|----------|--------|-------|-----------|--------|
| **P0** | `models.py` | 429 | 3 | Every module depends on models |
| **P0** | `ingestion/pipeline.py` | 623 | 6 | Core data pipeline |
| **P1** | `finrl_runner.py` | 390 | 4 | ML-to-trade bridge |
| **P1** | `ta_run.py` | 510 | 4 | TA report generation |
| **P1** | `ml_bucket_selector.py` | 191 | 2 | ML classification |
| **P2** | `app.py` | 332 | 3 | App entry point |
| **P2** | `fetcher/alpha_vantage.py` | 317 | 3 | API integration |
| **P2** | `ui/pages/ml_pipeline.py` | 460 | 3 | UI rendering |
| **P2** | `ingestion/indicators.py` | 138 | 2 | Indicator computation |
| **P2** | `full_pipeline.py` | 146 | 2 | CLI orchestrator |
| **P3** | `ui/pages/stock_detail.py` | 187 | 2 | Stock detail UI |
| **P3** | `main.py` | 132 | 1 | CLI entry points |
| **P3** | `config.py` | ~20 | 0.5 | Config loading |
| **P3** | `display.py` | ~15 | 0.5 | Formatting |
| **P3** | `logging_config.py` | ~15 | 0.3 | Logging setup |
| **P4** | Error handling (cross-cut) | N/A | 4 | Robustness |
| **P4** | Integration flows | N/A | 6 | End-to-end validation |

**Total**: ~46 hours to reach 80%+ coverage.

---

## Section 6: Coverage Projection

| Phase | Modules Added | Est. Cumulative Coverage | Effort |
|-------|--------------|--------------------------|--------|
| Current | — | ~30% | — |
| P0 (models + ingestion pipeline) | 2 | ~45% | 9h |
| P1 (finrl + ta_run + ml_bucket) | 3 | ~60% | 10h |
| P2 (app + fetcher + UI + indicators + full_pipeline) | 5 | ~75% | 13h |
| P3 (remaining small modules) | 4 | ~80% | 3.8h |
| P4 (error handling + integration) | cross-cutting | ~85% | 10h |

---

## Section 7: Test Infrastructure Recommendations

1. **Shared fixtures** (add to `tests/conftest.py`):
```python
@pytest.fixture
def engine():
    from sqlalchemy import create_engine
    from src.models import Base
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    return e

@pytest.fixture
def session(engine):
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        yield s

@pytest.fixture
def sample_stocks(session):
    from src.models import Stock
    for sym in ["AAPL", "MSFT", "GOOGL"]:
        session.add(Stock(symbol=sym, name=f"{sym} Inc."))
    session.commit()
```

2. **pytest.ini additions**:
```ini
markers =
    slow: tests that hit external APIs or take >1s
    integration: tests requiring database
    unit: pure logic tests, no I/O
```

3. **CI test stages**:
   - Stage 1: `pytest -m "unit"` — fast, no DB, no network
   - Stage 2: `pytest -m "integration"` — in-memory SQLite
   - Stage 3: `pytest -m "e2e"` — Playwright (requires running Streamlit)
