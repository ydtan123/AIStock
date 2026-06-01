# Test Coverage Gap Analysis — AIStock v3

**Date:** 2026-05-30 (21:41 GMT+8)
**Overall Coverage:** 29% (4142 statements, 2938 missed)
**Tests:** 131 passed, 12 failed, 29 errors

---

## 0. Build Blockers (Must Fix First)

**2 infrastructure bugs block 32 tests:**

### Bug #1: `database.py` — MySQL pool args crash SQLite tests
`src/database.py:24`: `max_overflow` incompatible with SQLite `SingletonThreadPool`. Affects ALL `test_repository.py` (20 errors) + `test_scheduler.py` (6 failures).

**Fix:** Conditional engine creation:
```python
if url.startswith("sqlite"):
    _engine = create_engine(url)
else:
    _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600,
                            pool_size=8, max_overflow=4)
```

### Bug #2: `models.py` — `MEDIUMTEXT()` doesn't work with SQLite
`stock_news.result` uses `MEDIUMTEXT()` → SQLite dialect compile error. Affects `test_database.py::test_creates_all_tables_without_error`.

**Fix:** Use `Text()` (SQLAlchemy generic type):
```python
from sqlalchemy import Text
result = Column(Text(), nullable=False)
```

| Bug | Tests Blocked | Impact |
|-----|--------------|--------|
| #1 pool args | 26 (20 errors + 6 fails) | repository, scheduler |
| #2 MEDIUMTEXT | 1 fail | database init |

---

## 1. Coverage by Module

### 0% Coverage (24 modules — 2400+ MISSED statements)

| Module | Stmts | Pri | Key Functions |
|--------|-------|-----|---------------|
| `src/ta_run.py` | 309 | M | Standalone CLI |
| `src/ui/pages/ml_pipeline.py` | 322 | H | Streamlit UI, config form, log streaming |
| `src/ingestion/pipeline.py` | 289 | **CRIT** | `run_daily_pipeline`, `_fetch_and_store_prices`, `_upsert_fundamentals`, `_process_symbol`, `run_bootstrap` |
| `src/finrl_runner.py` | 277 | **CRIT** | `run_pipeline_and_save_report`, `run_predict_only`, `_run_simple_backtest` |
| `src/app.py` | 208 | H | Streamlit dashboard, 11 pages |
| `src/main.py` | 93 | L | CLI entry, thin wrapper |
| `src/ml_bucket_selector.py` | 90 | H | ML model selection wrapper |
| `src/ui/pages/stock_detail.py` | 102 | M | Streamlit UI |
| `src/ui/pages/stock_technical.py` | 91 | M | Streamlit UI |
| `src/ui/pages/stock_lookup.py` | 78 | M | Streamlit UI |
| `src/ui/pages/paper_trading.py` | 79 | M | Streamlit UI |
| `src/ui/pages/stock_manager.py` | 67 | M | Streamlit UI |
| `src/full_pipeline.py` | 71 | L | CLI shim for orchestrator |
| `src/ingestion/indicators.py` | 66 | H | `compute_indicators` |
| `src/ui/pages/portfolio.py` | 47 | M | Streamlit UI |
| `src/ui/pages/stock_screener.py` | 51 | M | Streamlit UI |
| `src/ui/pages/strategy_backtest.py` | 51 | M | Streamlit UI |
| `src/ingestion/symbols.py` | 39 | M | `refresh_symbols`, `_clean` |
| `src/ui/pages/settings.py` | 35 | M | Streamlit UI |
| `src/ui/pages/overview.py` | 16 | L | Streamlit UI |
| `src/ui/pages/live_trading.py` | 63 | M | Streamlit UI |
| `src/ui/pages/job_history.py` | 15 | L | Streamlit UI |
| `src/ui/pages/__init__.py` | 15 | L | Streamlit UI |
| `src/logging_config.py` | 5 | L | `setup_logger` |

### Low Coverage (<80%)

| Module | Cov | Missed | Gaps |
|--------|-----|--------|------|
| `src/repository.py` | 29% | 115/161 | 12/15 methods mostly untested |
| `src/scheduler.py` | 23% | 60/78 | All 5 functions untested |
| `src/fetcher/alpha_vantage.py` | 19% | 121/149 | All 8 methods untested |
| `src/config.py` | 35% | 11/17 | `load_config()` untested |
| `src/news_cache.py` | 54% | 42/91 | Cache `get_cached`, `set_cached` untested |
| `src/fetcher/yahoo.py` | 38% | 13/21 | `get_daily`, `get_overview` untested |
| `src/pipeline/backends/selectors.py` | 70% | 18/60 | `select()` error paths only |

### Adequately Tested (80%+)

| Module | Cov | Notes |
|--------|-----|-------|
| `src/models.py` | 100% | Declarative base, all columns touched |
| `src/display.py` | 100% | Formatting utilities |
| `src/fetcher/base.py` | 100% | |
| `src/fetcher/rate_limiter.py` | 100% | Token bucket tests |
| `src/migrations/run.py` | 100% | Migration runner |
| `src/utils.py` | 100% | |
| `src/database.py` | 90% | Only pool config untested |
| `src/pipeline/config.py` | 95% | CLI override edge cases |
| `src/pipeline/orchestrator.py` | 95% | Edge cases only |
| `src/pipeline/fast_evaluation.py` | 98% | Near complete |
| `src/pipeline/deep_evaluation.py` | 95% | Near complete |
| `src/pipeline/stock_selection.py` | 94% | Near complete |
| `src/pipeline/base.py` | 89% | Serialization edge cases |
| `src/pipeline/backends/deep_evaluators.py` | 81% | Error paths only |
| `src/pipeline/backends/fast_evaluators.py` | 81% | Error paths only |

---

## 2. Untested Functions (Priority Order)

### 🔴 CRITICAL: `src/ingestion/pipeline.py` (289 stmts)

| Function | Lines | Missing Coverage |
|----------|-------|-----------------|
| `_last_trading_date()` | ~28 | Weekend handling, holiday edge cases |
| `_prefetch_stock_dates()` | ~40 | Empty list input, missing stock IDs |
| `_fetch_and_store_prices()` | ~80 | Deadlock retry exhaustion, empty API response, start>end date |
| `_upsert_fundamentals()` | ~75 | Skip on freshness, DB fallback, empty overview, deadlock retry |
| `_refresh_snapshots()` | ~47 | No active stocks, NULL handling |
| `_batch_update_checkpoints()` | ~13 | Empty list, partial failure |
| `_needs_full_backfill()` | ~35 | NULL indicator date, NULL price date, both NULL |
| `_fetch_stock_news()` | ~16 | Network error, empty response, AV fallback |
| `_fetch_stock_news_av()` | ~20 | AV rate limit, invalid symbol |
| `_process_symbol()` | ~34 | Error dict shape verification, news fetch conditions |
| `run_daily_pipeline()` | ~66 | ThreadPoolExecutor failure, progress counter accuracy |
| `run_bootstrap()` | ~24 | Empty OVERVIEW, API rate limit mid-bootstrap |
| `_auto_activate()` | ~17 | No matching criteria, all already active |

### 🔴 CRITICAL: `src/repository.py` (115 stmts missed)

| Method | Lines | Missing Coverage |
|--------|-------|-----------------|
| `find_stock()` | ~10 | Unknown symbol |
| `find_stocks_batch()` | ~10 | Entirely untested |
| `get_prices()` | ~12 | Entirely untested |
| `get_indicator()` | ~10 | Entirely untested |
| `get_snapshot()` | ~4 | Entirely untested |
| `get_tech_indicators()` | ~10 | Entirely untested |
| `screen_stocks()` | ~46 | Complex filtering with NULL-safe branches |
| `list_stocks()` | ~46 | LEFT JOIN no matches, empty filters |
| `save_selected_stocks()` | ~29 | Empty records, partial insert, rollback |
| `save_predict_only_results()` | ~23 | None weights, empty list, duplicates |
| `get_latest_selected_stocks()` | ~29 | No pipeline runs, tied timestamps |
| `get_job_runs()` | ~20 | limit=0, limit > row_count |

### 🔴 CRITICAL: `src/scheduler.py` (60 stmts missed)

| Function | Lines | Missing Coverage |
|----------|-------|-----------------|
| `_record_job_start()` | ~9 | DB failure, duplicate jobs |
| `_record_job_end()` | ~14 | Unknown run_id, error > 2000 chars |
| `job_daily_pipeline()` | ~17 | Pipeline exception → error recording |
| `job_refresh_symbols()` | ~16 | Same pattern |
| `main()` | ~40 | Invalid config, scheduler conflict |

---

## 3. Error Handling Gaps (~60 error blocks untested)

| Pattern | Count | Locations | Test Needed |
|---------|-------|-----------|-------------|
| Deadlock retry (error 1213) | 5 | `ingestion/pipeline.py`, `indicators.py` | Retry exhaustion, non-1213 re-raise, backoff timing |
| `except Exception` with logging | 12 | `pipeline/*`, `finrl_runner.py`, `deep_evaluators.py` | Error dict shape, warning logged |
| `try/finally` session close | 20+ | `repository.py`, `scheduler.py`, `ingestion/*` | Close on exception, no double-close |
| HTTP retry + rate limit | 1 | `fetcher/alpha_vantage.py::_get()` | 429 backoff, timeout retry, 5xx vs 4xx |
| `except KeyError` registry | 3 | `selectors.py`, evaluation steps | Unknown backend name |
| `except TypeError` validation | 3 | `base.py`, `selectors.py` | Missing `name` attribute |
| `except ImportError` fallback | 2 | `news_cache.py`, `deep_evaluators.py` | Optional dependency missing |

---

## 4. Edge Cases Not Covered

| Category | Count | Examples | Files |
|----------|-------|----------|-------|
| **Empty collections** | 25+ | empty stock_ids, empty tickers, empty DataFrame, empty dict | `ingestion/*`, `repository.py`, `finrl_runner.py` |
| **None/NaN/Inf** | 20+ | None weights, None sector, NaN indicators, Inf clipping | `repository.py`, `finrl_runner.py`, `indicators.py` |
| **Division by zero** | 6 | zero volatility → Sharpe, max_dd=0 → Calmar, total_confidence=0 → consensus | `finrl_runner.py`, `fast_evaluators.py` |
| **Boundary values** | 8 | limit=0, error > 2000 chars, date=weekend, start > end | `scheduler.py`, `repository.py`, ingestion |
| **Concurrency** | 3 | ThreadPoolExecutor partial failure, race in snapshots | `ingestion/pipeline.py` |
| **API failure modes** | 10 | Rate limit, timeout, 4xx, 5xx, invalid symbol, empty response | `fetcher/` |

---

## 5. Integration Test Gaps

| Flow | Status | Gap |
|------|--------|-----|
| Full pipeline E2E | 1 test, **FAILING** | `pipeline.base` attribute error |
| Data ingestion → DB | **NO tests** | fetch → upsert round-trip across 3 stores (prices, indicators, snapshots) |
| Stock selection → Fast eval → Deep eval | Partially tested | Cross-step data flow untested |
| ML model train → predict → store | 1 smoke test | Only `max_high_5pct` label, others untested |
| Scheduler job chain | **0 working** | start → pipeline → end |
| Fetcher → API | **NO tests** | AV rate limit, Yahoo fallback, error responses |
| Config hot-reload | **NO tests** | mtime detection, force reload |

---

## 6. Test Skeletons

### 6.1 `tests/test_ingestion_pipeline.py` (CRITICAL — largest gap)

```python
"""Tests for ingestion pipeline — daily data flow."""
import datetime as dt
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from database import configure, init_db, get_session
from models import Stock, DailyPrice, StockIndicator


@pytest.fixture(autouse=True)
def _setup_db():
    configure("sqlite:///:memory:")
    init_db()


# --- _last_trading_date ---
class TestLastTradingDate:
    def test_weekday_before_close_returns_same_day(self, monkeypatch):
        from ingestion.pipeline import _last_trading_date
        monkeypatch.setattr("ingestion.pipeline.dt.datetime", MagicMock(
            now=lambda: dt.datetime(2026, 5, 27, 10, 0),  # Wed 10am
        ))
        result = _last_trading_date()
        assert result == dt.date(2026, 5, 27)

    def test_saturday_returns_friday(self, monkeypatch):
        from ingestion.pipeline import _last_trading_date
        monkeypatch.setattr("ingestion.pipeline.dt.datetime", MagicMock(
            now=lambda: dt.datetime(2026, 5, 30, 10, 0),  # Sat
        ))
        result = _last_trading_date()
        assert result.weekday() == 4  # Friday


# --- _prefetch_stock_dates ---
class TestPrefetchStockDates:
    def test_empty_list_returns_empty_dict(self):
        from ingestion.pipeline import _prefetch_stock_dates
        result = _prefetch_stock_dates([])
        assert result == {"dates": {}, "indicators": {}}

    def test_stock_with_no_prices_returns_none(self):
        from ingestion.pipeline import _prefetch_stock_dates
        s = get_session()
        stock = Stock(symbol="EMPTY", name="Empty Inc.", is_active=True)
        s.add(stock); s.commit()
        sid = stock.id; s.close()
        result = _prefetch_stock_dates([sid])
        assert result["dates"].get(str(sid)) is None


# --- _fetch_and_store_prices ---
class TestFetchAndStorePrices:
    def test_empty_dataframe_returns_zero(self):
        from ingestion.pipeline import _fetch_and_store_prices
        mock_fetcher = MagicMock()
        mock_fetcher.get_daily.return_value = pd.DataFrame()
        stock = MagicMock(id=1, symbol="TEST")
        count, max_dt = _fetch_and_store_prices(
            mock_fetcher, stock,
            dt.date(2020, 1, 1), dt.date(2020, 1, 31),
            lambda *a: None
        )
        assert count == 0

    def test_deadlock_retry_exhausted_reraises(self):
        from ingestion.pipeline import _fetch_and_store_prices
        mock_fetcher = MagicMock()
        df = pd.DataFrame({
            "date": [dt.date(2020, 1, 2)],
            "open": [100], "high": [105], "low": [99],
            "close": [102], "volume": [1_000_000],
        })
        mock_fetcher.get_daily.return_value = df
        stock = MagicMock(id=1, symbol="TEST")

        call_count = [0]
        def mock_log_and_dispatch(*args, **kwargs):
            call_count[0] += 1
            raise Exception("Deadlock found when trying to get lock; try restarting transaction (1213)")

        with pytest.raises(Exception, match="1213"):
            _fetch_and_store_prices(
                mock_fetcher, stock,
                dt.date(2020, 1, 1), dt.date(2020, 1, 31),
                mock_log_and_dispatch
            )
        assert call_count[0] == 5  # all retries exhausted


# --- _upsert_fundamentals ---
class TestUpsertFundamentals:
    def test_skips_on_recent_indicator(self):
        from ingestion.pipeline import _upsert_fundamentals
        mock_fetcher = MagicMock()
        stock = MagicMock(id=1)
        result = _upsert_fundamentals(
            mock_fetcher, stock, force=False,
            indicator_last_updated=dt.datetime.utcnow()
        )
        assert result is False

    def test_force_overrides_age_check(self):
        from ingestion.pipeline import _upsert_fundamentals
        mock_fetcher = MagicMock()
        mock_fetcher.get_overview.return_value = {
            "Symbol": "TEST", "MarketCapitalization": "1000000000"
        }
        stock = MagicMock(id=1, symbol="TEST")
        result = _upsert_fundamentals(
            mock_fetcher, stock, force=True,
            indicator_last_updated=dt.datetime.utcnow()
        )
        assert result is True


# --- _process_symbol ---
class TestProcessSymbol:
    def test_returns_error_dict_on_exception(self):
        from ingestion.pipeline import _process_symbol
        mock_fetcher = MagicMock()
        mock_fetcher.get_daily.side_effect = RuntimeError("API down")
        stock = MagicMock(id=1, symbol="BAD", name="Bad Co.")
        result = _process_symbol(
            mock_fetcher, stock, force=False,
            skip_news=True, skip_indicators=True,
            global_progress=None, total=1, progress_lock=None
        )
        assert result["symbol"] == "BAD"
        assert result.get("error") is not None


# --- _fetch_stock_news ---
class TestFetchStockNews:
    def test_returns_zero_when_no_tradingagents_module(self, monkeypatch):
        """When tradingagents unavailable, should not crash."""
        from ingestion import pipeline
        monkeypatch.setitem(
            __import__("sys").modules, "tradingagents",
            type(sys)("tradingagents")
        )
        # If both Google and AV paths fail, should return 0
        monkeypatch.setattr(pipeline, "_fetch_stock_news_av", lambda *a: 0)
        result = pipeline._fetch_stock_news("AAPL")
        assert result == 0


# --- run_daily_pipeline ---
class TestRunDailyPipeline:
    def test_empty_active_stocks_returns_zero_summary(self, monkeypatch):
        from ingestion.pipeline import run_daily_pipeline
        mock_fetcher = MagicMock()
        monkeypatch.setattr(
            "ingestion.pipeline._prefetch_stock_dates",
            lambda *a: {"dates": {}, "indicators": {}}
        )
        summary = run_daily_pipeline(mock_fetcher, force=False)
        assert summary["processed"] == 0
        assert summary["errors"] == 0

    def test_tracks_errors_separate_from_processed(self, monkeypatch):
        from ingestion.pipeline import run_daily_pipeline
        mock_fetcher = MagicMock()
        s = get_session()
        s.add(Stock(symbol="A", name="A Inc.", is_active=True))
        s.add(Stock(symbol="B", name="B Inc.", is_active=True))
        s.commit(); s.close()

        def mock_process(fetcher, stock, **kwargs):
            if stock.symbol == "A":
                return {"symbol": "A", "prices": 10, "news": 3, "indicators": 5}
            raise RuntimeError("B failed")
        monkeypatch.setattr("ingestion.pipeline._process_symbol", mock_process)
        monkeypatch.setattr(
            "ingestion.pipeline._prefetch_stock_dates",
            lambda *a: {"dates": {}, "indicators": {}}
        )
        summary = run_daily_pipeline(mock_fetcher, force=False)
        assert summary["processed"] == 2
        assert summary["errors"] == 1
```


### 6.2 `tests/test_repository_methods.py` (HIGH — 115 stmts)

```python
"""Tests for uncovered StockRepository methods."""
import datetime as dt

import pandas as pd
import pytest

from database import configure, init_db, get_session
from models import Stock, StockIndicator, DailyPrice
from repository import StockRepository, ScreenCriteria, StockFilters


@pytest.fixture(autouse=True)
def _setup_db():
    configure("sqlite:///:memory:")
    init_db()


@pytest.fixture
def repo():
    return StockRepository()


def _seed(session_fn):
    s = get_session()
    session_fn(s)
    s.commit()
    s.close()


class TestFindStock:
    def test_unknown_symbol_returns_none(self, repo):
        assert repo.find_stock("ZZZZNONEXISTENT") is None

    def test_known_symbol_returns_stock(self, repo):
        _seed(lambda s: s.add(Stock(symbol="AAPL", name="Apple", is_active=True)))
        result = repo.find_stock("AAPL")
        assert result is not None
        assert result.symbol == "AAPL"


class TestFindStocksBatch:
    def test_empty_list_returns_empty_dict(self, repo):
        assert repo.find_stocks_batch([]) == {}

    def test_partial_hit_returns_none_for_missing(self, repo):
        _seed(lambda s: s.add(Stock(symbol="A", name="A")))
        result = repo.find_stocks_batch(["A", "B"])
        assert result["A"] is not None
        assert result.get("B") is None


class TestGetPrices:
    def test_no_data_returns_empty_dataframe(self, repo):
        _seed(lambda s: s.add(Stock(symbol="TEST", name="Test")))
        sid = get_session().query(Stock).first().id
        df = repo.get_prices(sid, dt.date(2020, 1, 1), dt.date(2020, 1, 31))
        assert df.empty

    def test_returns_correct_columns(self, repo):
        _seed(lambda s: s.add(Stock(symbol="T", name="T")))
        session = get_session()
        stock = session.query(Stock).first()
        for i in range(5):
            session.add(DailyPrice(
                stock_id=stock.id,
                date=dt.date(2024, 1, 1) + dt.timedelta(days=i),
                open=100+i, high=105+i, low=99+i, close=102+i, volume=1000000
            ))
        session.commit(); session.close()
        df = repo.get_prices(stock.id, dt.date(2024, 1, 1), dt.date(2024, 1, 10))
        assert set(df.columns) >= {"date", "open", "high", "low", "close", "volume"}


class TestGetIndicator:
    def test_no_indicator_returns_none(self, repo):
        assert repo.get_indicator(99999) is None

    def test_existing_indicator_returned(self, repo):
        _seed(lambda s: s.add(Stock(symbol="T", name="T")))
        s = get_session()
        stock = s.query(Stock).first()
        s.add(StockIndicator(stock_id=stock.id, pe_ratio=25.0,
                             last_updated=dt.datetime.utcnow()))
        s.commit(); s.close()
        ind = repo.get_indicator(stock.id)
        assert ind is not None
        assert ind.pe_ratio == 25.0


class TestScreenStocks:
    def test_empty_criteria_returns_all_active(self, repo):
        _seed(lambda s: s.add(Stock(symbol="A", name="A", is_active=True)))
        df = repo.screen_stocks(ScreenCriteria())
        assert isinstance(df, pd.DataFrame)
        assert not df.empty


class TestListStocks:
    def test_active_only_filter(self, repo):
        _seed(lambda s: [
            s.add(Stock(symbol="A", name="A", is_active=True)),
            s.add(Stock(symbol="B", name="B", is_active=False)),
        ])
        df = repo.list_stocks(StockFilters(active_only=True))
        assert len(df) == 1
        assert df.iloc[0]["symbol"] == "A"

    def test_sector_filter(self, repo):
        _seed(lambda s: [
            s.add(Stock(symbol="A", name="A", sector="Technology", is_active=True)),
            s.add(Stock(symbol="B", name="B", sector="Finance", is_active=True)),
        ])
        df = repo.list_stocks(StockFilters(sector="Technology"))
        assert len(df) == 1


class TestSavePredictOnly:
    def test_empty_list_returns_zero(self, repo):
        assert repo.save_predict_only_results([]) == 0

    def test_single_prediction_inserts(self, repo):
        result = repo.save_predict_only_results([
            {"symbol": "AAPL", "probability": 0.85, "label_method": "test_label"}
        ])
        assert result == 1

    def test_none_weight_handled(self, repo):
        result = repo.save_predict_only_results([
            {"symbol": "AAPL", "probability": 0.85,
             "label_method": "test", "weight": None}
        ])
        assert result == 1


class TestGetJobRuns:
    def test_empty_returns_empty_dataframe(self, repo):
        df = repo.get_job_runs()
        assert df.empty

    def test_limit_zero_returns_empty(self, repo):
        df = repo.get_job_runs(limit=0)
        assert df.empty
```


### 6.3 `tests/test_scheduler_functions.py` (MEDIUM)

```python
"""Tests for scheduler functions."""
import pytest
from unittest.mock import MagicMock, patch

from database import configure, init_db, get_session
from models import ScheduledJobRun


@pytest.fixture(autouse=True)
def _setup_db():
    configure("sqlite:///:memory:")
    init_db()


class TestRecordJobStart:
    def test_returns_run_id(self):
        from scheduler import _record_job_start
        run_id = _record_job_start("test_job")
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_status_is_running(self):
        from scheduler import _record_job_start
        rid = _record_job_start("my_job")
        s = get_session()
        run = s.query(ScheduledJobRun).filter_by(id=rid).first()
        assert run.status == "running"
        assert run.job_name == "my_job"
        s.close()


class TestRecordJobEnd:
    def test_success_marks_completed(self):
        from scheduler import _record_job_start, _record_job_end
        rid = _record_job_start("test")
        _record_job_end(rid, stocks_updated=42)
        s = get_session()
        run = s.query(ScheduledJobRun).filter_by(id=rid).first()
        assert run.status == "completed"
        assert run.stocks_updated == 42
        s.close()

    def test_error_marks_failed_and_stores_message(self):
        from scheduler import _record_job_start, _record_job_end
        rid = _record_job_start("failing")
        _record_job_end(rid, error="Connection timeout")
        s = get_session()
        run = s.query(ScheduledJobRun).filter_by(id=rid).first()
        assert run.status == "failed"
        assert "Connection timeout" in run.error_message
        s.close()

    def test_error_truncated_to_2000_chars(self):
        from scheduler import _record_job_start, _record_job_end
        rid = _record_job_start("long_error")
        long_msg = "x" * 3000
        _record_job_end(rid, error=long_msg)
        s = get_session()
        run = s.query(ScheduledJobRun).filter_by(id=rid).first()
        assert len(run.error_message) <= 2000
        s.close()


class TestJobDailyPipeline:
    @patch("scheduler.create_fetcher")
    @patch("ingestion.pipeline.run_daily_pipeline")
    def test_exception_caught_and_recorded(self, mock_run, mock_fetch):
        mock_run.side_effect = RuntimeError("API failure")
        from scheduler import job_daily_pipeline
        job_daily_pipeline()  # must not crash

    @patch("scheduler.create_fetcher")
    @patch("ingestion.pipeline.run_daily_pipeline")
    def test_success_path(self, mock_run, mock_fetch):
        mock_run.return_value = {"processed": 100, "errors": 0}
        from scheduler import job_daily_pipeline
        job_daily_pipeline()
        mock_run.assert_called_once()


class TestJobRefreshSymbols:
    @patch("scheduler.create_fetcher")
    @patch("ingestion.symbols.refresh_symbols")
    def test_refresh_count_recorded(self, mock_refresh, mock_fetch):
        mock_refresh.return_value = 50
        from scheduler import job_refresh_symbols
        job_refresh_symbols()
        mock_refresh.assert_called_once()
```


### 6.4 `tests/test_fetcher_alpha_vantage.py` (HIGH)

```python
"""Tests for Alpha Vantage fetcher."""
import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from fetcher.alpha_vantage import AlphaVantageFetcher


@pytest.fixture
def fetcher():
    return AlphaVantageFetcher(api_key="demo")


class TestGetDaily:
    def test_valid_csv_returns_dataframe(self, fetcher, monkeypatch):
        csv_data = "timestamp,open,high,low,close,volume\n2024-01-02,100.0,105.0,99.0,102.0,1000000\n"
        monkeypatch.setattr(fetcher, "_get", lambda *a, **kw: csv_data)
        df = fetcher.get_daily("AAPL", None, None)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_empty_response_returns_empty_dataframe(self, fetcher, monkeypatch):
        monkeypatch.setattr(fetcher, "_get", lambda *a, **kw: "")
        df = fetcher.get_daily("AAPL", None, None)
        assert df.empty

    def test_rate_limit_note_returns_empty(self, fetcher, monkeypatch):
        note = "Thank you for using Alpha Vantage. Our standard API rate limit is 25 requests per day."
        monkeypatch.setattr(fetcher, "_get", lambda *a, **kw: note)
        df = fetcher.get_daily("AAPL", None, None)
        assert len(df) == 0


class TestGetOverview:
    def test_valid_symbol_returns_dict(self, fetcher, monkeypatch):
        resp = json.dumps({"Symbol": "AAPL", "MarketCapitalization": "3000000000000"})
        monkeypatch.setattr(fetcher, "_get", lambda *a, **kw: resp)
        result = fetcher.get_overview("AAPL")
        assert isinstance(result, dict)
        assert result["Symbol"] == "AAPL"

    def test_invalid_symbol_returns_error_dict(self, fetcher, monkeypatch):
        resp = json.dumps({"Error Message": "Invalid API call"})
        monkeypatch.setattr(fetcher, "_get", lambda *a, **kw: resp)
        result = fetcher.get_overview("ZZZZZZZ")
        assert "Error Message" in result


class TestGetNewsSentiment:
    def test_no_feed_key_returns_empty_list(self, fetcher, monkeypatch):
        monkeypatch.setattr(fetcher, "_get", lambda *a, **kw: json.dumps({}))
        result = fetcher.get_news_sentiment("AAPL")
        assert result == []

    def test_valid_feed_returns_list(self, fetcher, monkeypatch):
        data = json.dumps({"feed": [{"title": "News 1", "url": "http://x.com/1"}]})
        monkeypatch.setattr(fetcher, "_get", lambda *a, **kw: data)
        result = fetcher.get_news_sentiment("AAPL")
        assert isinstance(result, list)
        assert len(result) == 1


class TestGetListing:
    def test_empty_response_returns_empty_dataframe(self, fetcher, monkeypatch):
        monkeypatch.setattr(fetcher, "_get", lambda *a, **kw: "")
        df = fetcher.get_listing()
        assert df.empty
```


### 6.5 `tests/test_indicators.py` (HIGH)

```python
"""Tests for technical indicator computation."""
import datetime as dt

import numpy as np
import pytest

from database import configure, init_db, get_session
from models import Stock, DailyPrice


@pytest.fixture(autouse=True)
def _setup_db():
    configure("sqlite:///:memory:")
    init_db()


class TestComputeIndicators:
    def test_empty_prices_returns_zero(self):
        from ingestion.indicators import compute_indicators
        s = get_session()
        stock = Stock(symbol="E", name="E"); s.add(stock); s.commit()
        sid = stock.id; s.close()
        assert compute_indicators(sid) == 0

    def test_insufficient_data_returns_zero(self):
        from ingestion.indicators import compute_indicators
        s = get_session()
        stock = Stock(symbol="FEW", name="Few"); s.add(stock); s.commit()
        for i in range(5):
            s.add(DailyPrice(
                stock_id=stock.id,
                date=dt.date(2024, 1, 1) + dt.timedelta(days=i),
                open=100+i, high=105+i, low=99+i, close=102+i, volume=1000000
            ))
        s.commit(); s.close()
        assert compute_indicators(stock.id) == 0

    def test_sufficient_data_returns_positive_count(self):
        from ingestion.indicators import compute_indicators
        s = get_session()
        stock = Stock(symbol="OK", name="OK"); s.add(stock); s.commit()
        for i in range(60):
            s.add(DailyPrice(
                stock_id=stock.id,
                date=dt.date(2024, 1, 1) + dt.timedelta(days=i),
                open=100.0+i*0.1, high=105.0+i*0.1,
                low=99.0+i*0.1, close=102.0+i*0.1,
                volume=1_000_000+i*100
            ))
        s.commit(); s.close()
        count = compute_indicators(stock.id)
        assert count > 0

    def test_since_date_filters(self):
        from ingestion.indicators import compute_indicators
        s = get_session()
        stock = Stock(symbol="FILTER", name="Filter"); s.add(stock); s.commit()
        for i in range(60):
            s.add(DailyPrice(
                stock_id=stock.id,
                date=dt.date(2024, 1, 1) + dt.timedelta(days=i),
                open=100.0, high=105.0, low=99.0, close=102.0, volume=1000000
            ))
        s.commit(); s.close()
        count = compute_indicators(stock.id, since_date=dt.date(2024, 2, 20))
        assert 0 < count <= 10
```


### 6.6 `tests/test_symbols.py` (MEDIUM)

```python
"""Tests for symbol refresh."""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock


class TestClean:
    def test_none_returns_none(self):
        from ingestion.symbols import _clean
        assert _clean(None) is None

    def test_nan_returns_none(self):
        from ingestion.symbols import _clean
        assert _clean(float("nan")) is None

    def test_integer_passthrough(self):
        from ingestion.symbols import _clean
        assert _clean(42) == 42

    def test_string_passthrough(self):
        from ingestion.symbols import _clean
        assert _clean("AAPL") == "AAPL"


class TestRefreshSymbols:
    def test_empty_listing_returns_zero(self, monkeypatch):
        from ingestion import symbols
        mock_fetcher = MagicMock()
        mock_fetcher.get_listing.return_value = pd.DataFrame()
        monkeypatch.setattr(symbols, "get_session", MagicMock())
        count = symbols.refresh_symbols(mock_fetcher)
        assert count == 0

    def test_fetcher_error_propagates(self, monkeypatch):
        from ingestion import symbols
        mock_fetcher = MagicMock()
        mock_fetcher.get_listing.side_effect = RuntimeError("API down")
        monkeypatch.setattr(symbols, "get_session", MagicMock())
        with pytest.raises(RuntimeError, match="API down"):
            symbols.refresh_symbols(mock_fetcher)
```


### 6.7 `tests/test_config.py` (MEDIUM)

```python
"""Tests for config loading."""
import pytest
import tempfile
import yaml
from pathlib import Path


class TestLoadConfig:
    def test_missing_config_exits(self, monkeypatch, tmp_path):
        monkeypatch.setattr("config.Path.__new__", lambda *a: MagicMock())
        with pytest.raises(SystemExit) as exc:
            import config
            config._config = None
            config._config_mtime = 0
            config.load_config(force=True)
        assert exc.value.code == 1

    def test_valid_yaml_loads(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({
            "source": "yahoo",
            "database": {"url": "sqlite:///:memory:"}
        }))
        monkeypatch.setattr("config.Path.__new__", lambda *a: MagicMock())
        import config
        config._config = None
        config._config_mtime = 0
        result = config.load_config(force=True)
        assert isinstance(result, dict)
```


---

## 7. Implemention Priority

| Phase | Task | Estimated Tests | Coverage Impact |
|-------|------|----------------|-----------------|
| **1: Fix** | database.py pool args + models.py MEDIUMTEXT | 0 new | Unblocks 32 tests |
| **2: Critical** | `test_ingestion_pipeline.py` | 25 | 0% → ~50% (largest module) |
| **3: Critical** | `test_repository_methods.py` | 18 | 29% → ~60% |
| **4: Critical** | `test_scheduler_functions.py` | 12 | 23% → ~65% |
| **5: High** | `test_fetcher_alpha_vantage.py` | 15 | 19% → ~55% |
| **6: High** | `test_indicators.py` + `test_symbols.py` | 12 | 0% → ~60% |
| **7: Medium** | `test_config.py` | 6 | 35% → ~80% |
| **8: Medium** | `test_fetcher_yahoo.py` | 5 | 38% → ~75% |
| **9: Medium** | Pipeline backend edge cases | 10 | 81% → ~95% |
| **10: Integration** | Cross-step data flow, E2E | 8 | Integration coverage |

### Projected Results

```
Coverage Report — Projected After Phase 10
──────────────────────────────────────────────
Phase  Coverage   Cumulative New Tests
──────────────────────────────────────────────
1      29% → 29%  (fix blockers, 0 new)
2-4    29% → 45%  55 new tests
5-7    45% → 55%  33 new tests
8-10   55% → 68%  23 new tests
──────────────────────────────────────────────
Final: ~68% (up from 29%)
Tests: ~242 (up from 131 passing)
```
