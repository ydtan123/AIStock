# AIStock Test Coverage Gap Analysis v2

**Date**: 2026-05-31
**Baseline**: 21 test files covering ~36% of modules (pipeline, database, repository, utils, scheduler, rate_limiter, news_cache, fetcher_factory)
**Untested**: 18 source modules (64%) with 0 test coverage

---

## 1. Completely Untested Modules (0% coverage)

### 1.1 `src/models.py` (429 lines, 15 ORM classes) — CRITICAL

15 SQLAlchemy models define the database schema. No validation tests exist.

| Model | Risk |
|-------|------|
| `Stock`, `DailyPrice`, `StockIndicator` | Core data integrity |
| `TechnicalIndicator` | JSON blob validation |
| `QuarterlyFundamentals` | 70+ columns, no schema checks |
| `PipelineRun`, `SelectedStock` | Pipeline state integrity |
| `FastEvaluationConclusion`, `DeepEvaluationRow` | ML output schema |

**Test skeleton:**

```python
# tests/test_models.py
import pytest
from models import Stock, DailyPrice, StockIndicator, TechnicalIndicator

class TestStockModel:
    def test_create_minimal_stock(self, session):
        stock = Stock(symbol="AAPL", name="Apple Inc.", is_active=True)
        session.add(stock); session.commit()
        assert stock.id is not None
        assert stock.created_at is not None  # server_default

    def test_symbol_unique_constraint(self, session):
        session.add(Stock(symbol="AAPL", name="A"))
        session.commit()
        with pytest.raises(Exception):  # IntegrityError
            session.add(Stock(symbol="AAPL", name="B"))
            session.commit()

    def test_is_active_default(self, session):
        stock = Stock(symbol="TSLA")
        session.add(stock); session.commit()
        assert stock.is_active is True

class TestTechnicalIndicator:
    def test_json_column_accepts_dict(self, session):
        """indicators column is MySQL JSON — verify dict round-trip."""
        ind = TechnicalIndicator(stock_id=1, date="2024-01-15",
                                 indicators={"rsi": 55.5, "macd": 1.2})
        session.add(ind); session.commit()
        loaded = session.get(TechnicalIndicator, ind.id)
        assert loaded.indicators["rsi"] == 55.5

    def test_json_column_null_allowed(self, session):
        ind = TechnicalIndicator(stock_id=1, date="2024-01-15", indicators=None)
        session.add(ind); session.commit()
        assert session.get(TechnicalIndicator, ind.id).indicators is None

class TestQuarterlyFundamentals:
    def test_minimal_row_persists(self, session):
        from models import QuarterlyFundamentals
        qf = QuarterlyFundamentals(
            stock_id=1, symbol="AAPL", datadate="2024-03-31",
            total_revenue=90000000000, net_income=23000000000
        )
        session.add(qf); session.commit()
        assert qf.id is not None
```

### 1.2 `src/config.py` (30 lines) — MEDIUM

`load_config()` caches + revalidates on file mtime. Critical path: all modules depend on config.

**Edge cases:**
- Missing config.yaml → `sys.exit(1)`
- Stale cache not invalidated when mtime unchanged
- `force=True` bypasses cache
- Corrupt YAML → ConfigLoader error propagation

**Test skeleton:**

```python
# tests/test_config.py
import pytest
from pathlib import Path

class TestLoadConfig:
    def test_returns_cached_on_same_mtime(self, tmp_path, monkeypatch):
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text("source: alpha_vantage\n")
        monkeypatch.setattr("config.Path", lambda *args: (
            yaml_path if "config.yaml" in str(args) else Path(*args)))
        import config
        config._config = None
        a = config.load_config()
        b = config.load_config()
        assert a is b  # cached — same object

    def test_force_reload_bypasses_cache(self, tmp_path, monkeypatch):
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text("source: alpha_vantage\n")
        monkeypatch.setattr("config.Path", lambda *args: (
            yaml_path if "config.yaml" in str(args) else Path(*args)))
        import config
        config._config = None
        a = config.load_config()
        b = config.load_config(force=True)
        assert a == b

    def test_missing_config_calls_sys_exit(self, tmp_path, monkeypatch):
        missing = tmp_path / "nonexistent.yaml"
        monkeypatch.setattr("config.Path", lambda *args: (
            missing if "config.yaml" in str(args) else Path(*args)))
        import config
        config._config = None
        with pytest.raises(SystemExit):
            config.load_config()
```

### 1.3 `src/logging_config.py` (15 lines) — LOW

```python
# tests/test_logging_config.py
import logging
from logging_config import setup_logging

def test_setup_logging_configures_root_logger():
    setup_logging(level=logging.WARNING)
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert len(root.handlers) >= 1

def test_setup_logging_default_level():
    setup_logging()
    root = logging.getLogger()
    assert root.level == logging.INFO
```

### 1.4 `src/ingestion/indicators.py` (138 lines) — MEDIUM

`compute_indicators(stock_id, since_date)` — computes 22 technical indicators from OHLCV data.

**Edge cases:**
- Empty price data → returns 0
- `since_date` filtering — rows before cutoff excluded from write
- MySQL deadlock retry (error 1213) with exponential backoff (5 attempts)
- Infinity/NaN values in computed indicators → replaced with None
- No `daily_prices` for stock_id → returns 0

```python
# tests/test_indicators.py
import pytest
from datetime import date, timedelta

class TestComputeIndicators:
    def test_empty_prices_returns_zero(self, session, stock_id):
        from ingestion.indicators import compute_indicators
        result = compute_indicators(stock_id)
        assert result == 0

    def test_computes_indicators_from_prices(self, session, stock_id_with_prices):
        from ingestion.indicators import compute_indicators
        count = compute_indicators(stock_id_with_prices)
        assert count > 0

    def test_since_date_filters_old_rows(self, session, stock_id_with_prices):
        from ingestion.indicators import compute_indicators
        cutoff = date.today() - timedelta(days=10)
        count = compute_indicators(stock_id_with_prices, since_date=cutoff)
        assert count >= 0

    def test_handles_infinity_values(self, session, stock_id):
        """NaN/Inf indicator values → replaced with None, not stored as JSON."""
        pass
```

### 1.5 `src/ingestion/symbols.py` (42 lines) — LOW

`refresh_symbols(fetcher)` — fetches NASDAQ+NYSE listing, upserts into DB.

**Edge cases:**
- Empty listing from fetcher → returns 0
- Batch upsert boundary (BATCH_SIZE=200, e.g., 250 symbols → 2 batches)
- Exception → rollback + session.close() in finally
- `_clean()` NaN → None conversion

```python
# tests/test_ingestion_symbols.py
import pytest
from unittest.mock import MagicMock
import pandas as pd

class TestRefreshSymbols:
    def test_empty_listing_returns_zero(self, session):
        from ingestion.symbols import refresh_symbols
        fetcher = MagicMock()
        fetcher.get_listing.return_value = pd.DataFrame(
            columns=["symbol", "name", "asset_type", "exchange"])
        result = refresh_symbols(fetcher)
        assert result == 0

    def test_upserts_across_batches(self, session):
        from ingestion.symbols import refresh_symbols
        fetcher = MagicMock()
        fetcher.get_listing.return_value = pd.DataFrame([{
            "symbol": f"TICK{i:03d}", "name": f"Ticker {i}",
            "asset_type": "Stock", "exchange": "NASDAQ",
        } for i in range(250)])
        result = refresh_symbols(fetcher)
        assert result == 250

    def test_clean_converts_nan_to_none(self):
        from ingestion.symbols import _clean
        assert _clean(float('nan')) is None
        assert _clean(None) is None
        assert _clean("AAPL") == "AAPL"

    def test_rollback_on_exception(self, session):
        from ingestion.symbols import refresh_symbols
        fetcher = MagicMock()
        fetcher.get_listing.side_effect = RuntimeError("API down")
        with pytest.raises(RuntimeError):
            refresh_symbols(fetcher)
```

### 1.6 `src/ml_bucket_selector.py` (191 lines) — HIGH

`MLBucketSelector.fit_predict()` — trains per-sector ML, selects top stocks.

**Edge cases:**
- Empty fund_df → ValueError("No rows remain")
- Single datadate → ValueError("Need ≥2 distinct datadates")
- All bucket predictions fail → RuntimeError("All buckets returned empty")
- Missing feature columns → median-imputed with warning
- Zero revenue/OCF/assets → derived ratios = NaN → median-imputed
- Unmapped gsector → rows dropped with warning
- `weight_method="ml_score"` with all-zero predicted_return → weight = 1/N

```python
# tests/test_ml_bucket_selector.py
import pytest
import pandas as pd
import numpy as np
from ml_bucket_selector import MLBucketSelector

@pytest.fixture
def sample_fund_df():
    return pd.DataFrame({
        "tic": ["AAPL", "MSFT", "GOOGL", "AMZN"],
        "datadate": ["2024-03-31", "2024-03-31", "2024-06-30", "2024-06-30"],
        "gsector": ["Technology", "Technology", "Technology", "Technology"],
        "y_return": [0.05, 0.03, 0.07, 0.02],
        "operating_cashflow": [100, 80, 90, 120],
        "free_cash_flow": [80, 60, 70, 100],
        "total_revenue": [200, 180, 190, 220],
        "net_income": [50, 40, 45, 55],
        "total_assets": [500, 450, 480, 520],
    })

class TestMLBucketSelector:
    def test_empty_dataframe_raises_valueerror(self, sample_fund_df):
        selector = MLBucketSelector()
        empty_df = sample_fund_df.iloc[0:0]
        with pytest.raises(ValueError, match="No rows remain"):
            selector.fit_predict(empty_df)

    def test_division_by_zero_in_derived_ratios(self, sample_fund_df):
        """Zero operating_cashflow → fcf_to_ocf = NaN → median-imputed safely."""
        df = sample_fund_df.copy()
        df.loc[0, "operating_cashflow"] = 0.0
        selector = MLBucketSelector()
        # Should not raise ZeroDivisionError during ratio derivation
        # Depends on run_bucket; verify df has no Inf after pre-processing

    def test_all_buckets_fail_raises_runtimeerror(self, sample_fund_df, monkeypatch):
        """Every run_bucket raises → RuntimeError."""
        selector = MLBucketSelector()
        # Requires mocking run_bucket to raise; verify error message

    def test_weight_method_ml_score_zero_scores(self, sample_fund_df):
        """All predicted_return < 0 → clip to 0 → uniform weights."""
        pass
```

### 1.7 `src/ta_run.py` (510 lines) — HIGH

Async TradingAgents wrapper — CLI entry for Streamlit dashboard.

**Pure functions to test (no LLM/mock needed):**

| Function | Testable |
|----------|----------|
| `_is_empty()` | Unit — pure function |
| `_CallTracker` | Unit — thread-safe counter |

**Edge cases for `_is_empty`:**
- `None`, `""`, `"   "` → True
- Magic strings: `"None"`, `"null"`, `"{}"`, `"[]"`, `"n/a"` → True
- `0` (int) → False (valid value)
- `False` → False (valid value)

```python
# tests/test_ta_run.py
import pytest
from ta_run import _is_empty

class TestIsEmpty:
    @pytest.mark.parametrize("value", [
        None, "", "   ", "None", "null", "{}", "[]", "n/a", "N/A",
        [], {},
    ])
    def test_empty_values(self, value):
        assert _is_empty(value) is True

    @pytest.mark.parametrize("value", [
        "BUY", "text", 0, 1, False, True, [1], {"k": "v"},
    ])
    def test_non_empty_values(self, value):
        assert _is_empty(value) is False
```

### 1.8 `src/finrl_runner.py` (390 lines) — HIGH

ML pipeline runner — stock selection + backtest. 6 functions.

**Testable pure functions:** `_compute_metrics`, `_equal_weight_fallback`

**Edge cases:**
- `_compute_metrics` with <2 returns → `{}`
- `_compute_metrics` with zero volatility → sharpe=0, calmar=0
- `_equal_weight_fallback` with empty tickers → single row? or empty? (verify intended behavior)
- `_build_selection_summary` with corrupt joblib files → Exception swallowed per-file
- `_build_selection_summary` with model that has neither `feature_importances_` nor `coef_` → skipped

```python
# tests/test_finrl_runner.py
import pytest
import numpy as np
import pandas as pd
from finrl_runner import _compute_metrics, _equal_weight_fallback

class TestComputeMetrics:
    def test_insufficient_data_returns_empty(self):
        returns = pd.Series([0.01])
        assert _compute_metrics(returns) == {}

    def test_zero_volatility(self):
        returns = pd.Series([0.0, 0.0, 0.0])
        m = _compute_metrics(returns)
        assert m["sharpe_ratio"] == 0.0
        assert m["annual_volatility"] == 0.0

    def test_positive_returns(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 252))
        m = _compute_metrics(returns)
        assert "sharpe_ratio" in m
        assert "max_drawdown" in m
        assert m["max_drawdown"] <= 0.0

    def test_negative_returns(self):
        returns = pd.Series([-0.01] * 252)
        m = _compute_metrics(returns)
        assert m["annual_return"] < 0

    def test_zero_returns_flat_equity(self):
        returns = pd.Series([0.0] * 252)
        m = _compute_metrics(returns)
        assert m["annual_return"] == 0.0
        assert m["max_drawdown"] == 0.0

class TestEqualWeightFallback:
    def test_selects_top_quantile(self):
        fund_df = pd.DataFrame()
        tickers_df = pd.DataFrame({"tickers": [f"T{i}" for i in range(100)]})
        result = _equal_weight_fallback(fund_df, tickers_df, top_quantile=0.9)
        assert len(result) == 10
        assert abs(result["weight"].sum() - 1.0) < 0.001

    def test_single_ticker(self):
        fund_df = pd.DataFrame()
        tickers_df = pd.DataFrame({"tickers": ["AAPL"]})
        result = _equal_weight_fallback(fund_df, tickers_df, top_quantile=0.75)
        assert len(result) == 1
        assert result.iloc[0]["weight"] == 1.0

    def test_empty_tickers(self):
        fund_df = pd.DataFrame()
        tickers_df = pd.DataFrame({"tickers": []})
        result = _equal_weight_fallback(fund_df, tickers_df, 0.75)
        # Current behavior: max(1, 0) = 1, selected = [][:1] = [] — verify
        pass

class TestBuildSelectionSummary:
    def test_empty_stocks_returns_empty_summary(self):
        from finrl_runner import _build_selection_summary
        result = _build_selection_summary([], [])
        assert result == {"total": 0, "stocks": []}

    def test_stock_sort_by_ml_score_descending(self):
        from finrl_runner import _build_selection_summary
        stocks = [
            {"ticker": "A", "ml_score": 0.5, "bucket": "tech"},
            {"ticker": "B", "ml_score": 0.9, "bucket": "tech"},
        ]
        result = _build_selection_summary(stocks, [])
        assert result["stocks"][0]["ticker"] == "B"  # highest score first
```

### 1.9 `src/ingestion/pipeline.py` (623 lines) — CRITICAL

Core data ingestion pipeline. 13 functions.

**Testable pure/isolated functions:** `_last_trading_date`, `_needs_full_backfill`

```python
# tests/test_ingestion_pipeline.py
import pytest
from datetime import date, timedelta

class TestLastTradingDate:
    def test_weekday_returns_same_day(self):
        from ingestion.pipeline import _last_trading_date
        import datetime
        wed = datetime.date(2024, 1, 10)
        assert _last_trading_date(wed) == wed

    def test_saturday_returns_friday(self):
        from ingestion.pipeline import _last_trading_date
        import datetime
        sat = datetime.date(2024, 1, 13)
        assert _last_trading_date(sat) == datetime.date(2024, 1, 12)

    def test_sunday_returns_friday(self):
        from ingestion.pipeline import _last_trading_date
        import datetime
        sun = datetime.date(2024, 1, 14)
        assert _last_trading_date(sun) == datetime.date(2024, 1, 12)

class TestNeedsFullBackfill:
    def test_no_existing_prices_returns_true(self, session, stock_id):
        from ingestion.pipeline import _needs_full_backfill
        assert _needs_full_backfill(session, stock_id) is True

    def test_has_recent_prices_returns_false(self, session, stock_id):
        from models import DailyPrice
        from datetime import date
        dp = DailyPrice(stock_id=stock_id, date=date.today() - timedelta(days=1),
                        open=100, high=101, low=99, close=100, volume=1000)
        session.add(dp); session.commit()
        from ingestion.pipeline import _needs_full_backfill
        assert _needs_full_backfill(session, stock_id) is False

class TestRunDailyPipeline:
    def test_no_active_symbols_returns_early(self, session):
        from ingestion.pipeline import run_daily_pipeline
        result = run_daily_pipeline()
        assert result is not None
```

### 1.10 `src/ui/cached_repo.py` (30 lines) — MEDIUM

Two Streamlit-cached functions wrapping repository queries.

```python
# tests/test_cached_repo.py
import pytest

class TestUnderlyingRepoQueries:
    """Test the repository methods that cached_repo wraps."""

    def test_find_stock_returns_none_for_unknown(self, session):
        from repository import StockRepository
        repo = StockRepository()
        result = repo.find_stock("NONEXISTENT")
        assert result is None

    def test_find_stock_returns_dict_for_known(self, session):
        from models import Stock
        stock = Stock(symbol="AAPL", name="Apple Inc.")
        session.add(stock); session.commit()
        from repository import StockRepository
        repo = StockRepository()
        result = repo.find_stock("AAPL")
        assert result is not None
        assert result["symbol"] == "AAPL"
```

---

## 2. Error Handling Test Gaps (Cross-Cutting)

### 2.1 Database Session Errors

**Gap**: No tests for session rollback, deadlock retry, or connection reuse.

```python
# tests/test_error_handling_db.py
class TestDatabaseErrorHandling:
    def test_rollback_on_integrity_error(self, session):
        from models import Stock
        s1 = Stock(symbol="AAPL", name="Apple")
        session.add(s1); session.commit()
        s2 = Stock(symbol="AAPL", name="Duplicate")
        session.add(s2)
        with pytest.raises(Exception):
            session.commit()
        session.rollback()
        s3 = Stock(symbol="MSFT", name="Microsoft")
        session.add(s3); session.commit()
        assert s3.id is not None

    def test_get_session_returns_distinct_objects(self):
        from database import get_session
        s1 = get_session()
        s2 = get_session()
        assert s1 is not s2
        s1.close(); s2.close()
```

### 2.2 Empty/Null Data Propagation

**Gap**: No tests verify graceful handling of empty DataFrames in pipeline steps.

```python
# tests/test_error_handling_empty_data.py

class TestEmptyDataPropagation:
    def test_empty_fundamentals_raises_in_finrl_runner(self):
        """run_pipeline_and_save_report raises RuntimeError on empty fund_df."""
        pass

    def test_empty_tickers_in_equal_weight(self):
        from finrl_runner import _equal_weight_fallback
        import pandas as pd
        result = _equal_weight_fallback(
            pd.DataFrame(), pd.DataFrame({"tickers": []}), 0.75)
        # Verify intended behavior — currently max(1, 0)=1, select=[][:1]=[]
        assert len(result) >= 0

    def test_empty_price_data_returns_zero_indicators(self, session, stock_id):
        from ingestion.indicators import compute_indicators
        assert compute_indicators(stock_id) == 0
```

### 2.3 Missing Error Handlers — Specific Functions

| File | Function | Missing Check |
|------|----------|---------------|
| `config.py` | `load_config()` | Corrupt YAML, empty file |
| `ml_bucket_selector.py` | `fit_predict()` | All-NaN feature columns |
| `finrl_runner.py` | `_build_selection_summary()` | Corrupt joblib artifacts |
| `ta_run.py` | `_summarise_report()` | LLM returns non-bullet response |
| `app.py` | `_pipeline_thread_target()` | Thread crash — queue error propagation |
| `ingestion/symbols.py` | `refresh_symbols()` | MySQL connection lost during batch |

```python
# tests/test_error_handling_functions.py

class TestConfigErrorHandling:
    def test_corrupt_yaml_raises(self, tmp_path, monkeypatch):
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(": invalid yaml: :")
        monkeypatch.setattr("config.Path", lambda *args: (
            yaml_path if "config.yaml" in str(args) else Path(*args)))
        import config
        config._config = None
        with pytest.raises(Exception):  # yaml.YAMLError
            config.load_config()

class TestMLBucketSelectorErrors:
    def test_all_nan_features_median_imputed(self, sample_fund_df):
        """All-NaN feature columns → median=NaN → fillna(0.0)."""
        df = sample_fund_df.copy()
        # Add a feature column that's all NaN
        df["some_feature"] = float("nan")
        selector = MLBucketSelector()
        # Verify no crash during fillna / median computation
        pass

class TestBuildSelectionSummaryErrors:
    def test_corrupt_joblib_skipped_silently(self, tmp_path):
        """Corrupt .pkl file → Exception caught per-file, bucket skipped."""
        from finrl_runner import _build_selection_summary
        bad_path = tmp_path / "bad.pkl"
        bad_path.write_text("not a pickle file")
        stocks = [{"ticker": "AAPL", "ml_score": 0.5, "bucket": "tech"}]
        result = _build_selection_summary(stocks, [str(bad_path)])
        assert result["total"] == 1  # stocks still included
        assert result["stocks"][0]["top_feature"] == "N/A"  # no model data
```

---

## 3. Edge Cases in Already-Tested Modules

### 3.1 `src/display.py` — fmt_market_cap (tested, missing edges)

- Negative market cap → formats as negative currency (intended?)
- Zero market cap → `$0`
- Boolean `True` → int(True)=1 → `$1` (surprising)

```python
# Additional tests for test_utils.py::TestFmtMarketCap:
def test_zero_market_cap(self):
    result = fmt_market_cap(0)
    assert result == "$0"

def test_negative_market_cap(self):
    result = fmt_market_cap(-1000000)
    # Current: "-$1.0M" — document expected behavior

def test_boolean_input(self):
    result = fmt_market_cap(True)
    assert result == "$1"
```

### 3.2 `src/utils.py` — safe_float/safe_int/safe_date

- `safe_float(True)` → `float(True)=1.0` (type coercion edge case)
- `safe_int(False)` → `int(False)=0` (type coercion edge case)

```python
# Additional tests for test_utils.py:
def test_safe_float_bool_input(self):
    """safe_float(True) = 1.0 — may want to return None for bool."""
    assert safe_float(True) == 1.0  # Document: deliberate or gap?

def test_safe_int_bool_input(self):
    assert safe_int(False) == 0
```

### 3.3 `src/repository.py` — tested, missing edges

- `get_latest_selected_stocks` when table empty
- `save_selected_stocks` with empty list
- `bulk_set_active` with invalid stock IDs

```python
# Additional tests for test_repository.py:
def test_get_latest_selected_stocks_empty_table(self, session):
    from repository import StockRepository
    repo = StockRepository()
    result = repo.get_latest_selected_stocks()
    assert result == []

def test_save_selected_stocks_empty_list(self, session):
    from repository import StockRepository
    repo = StockRepository()
    repo.save_selected_stocks([], pipeline_run_id=1)
    # Verify no-op, no error
```

---

## 4. Integration Test Gaps

### 4.1 Database Schema Creation

```python
# tests/test_integration_schema.py
class TestSchemaCreation:
    def test_all_tables_created(self, engine):
        from models import Base
        Base.metadata.create_all(engine)
        tables = Base.metadata.tables.keys()
        assert "stocks" in tables
        assert "daily_prices" in tables
        assert "technical_indicators" in tables

    def test_stock_with_prices_relationship(self, session):
        from models import Stock, DailyPrice
        from datetime import date
        stock = Stock(symbol="AAPL", name="Apple")
        session.add(stock); session.flush()
        dp = DailyPrice(stock_id=stock.id, date=date.today(),
                        open=100, high=101, low=99, close=100, volume=1000)
        session.add(dp); session.commit()
        # Verify relationship
        loaded = session.get(Stock, stock.id)
        assert len(loaded.daily_prices) == 1
```

### 4.2 Indicator Computation End-to-End

```python
# tests/test_integration_indicators.py
class TestIndicatorsIntegration:
    def test_price_to_indicator_full_cycle(self, session, stock_id):
        """Seed DailyPrice → compute_indicators → verify TechnicalIndicator rows."""
        from models import DailyPrice
        from datetime import date, timedelta
        import pandas as pd

        # Seed 260 days of price data
        base = date.today() - timedelta(days=400)
        for i in range(300):
            dp = DailyPrice(
                stock_id=stock_id, date=base + timedelta(days=i),
                open=100+i, high=102+i, low=99+i, close=101+i, volume=1000000
            )
            session.add(dp)
        session.commit()

        from ingestion.indicators import compute_indicators
        count = compute_indicators(stock_id)
        assert count > 0
        # Verify indicator columns present
        from models import TechnicalIndicator
        row = session.query(TechnicalIndicator).filter_by(stock_id=stock_id).first()
        assert row is not None
        assert "rsi" in row.indicators or row.indicators is not None
```

### 4.3 Pipeline Config Override Propagation

```python
# tests/test_integration_pipeline_config.py
class TestPipelineConfigOverride:
    def test_cli_set_overrides_propagate(self):
        """--set fast_evaluation.top_n=5 should reach FastEvaluationStep."""
        pass

    def test_backwards_compat_keys_emit_warning(self):
        """Old finrl_pipeline.* keys → deprecation warning → still work."""
        pass
```

---

## 5. Summary

| Category | Count | Priority |
|----------|-------|----------|
| Completely untested modules | 18 | 1 CRITICAL, 2 HIGH |
| Error handling gaps | 15+ functions | HIGH |
| Edge cases in tested modules | 8 | MEDIUM |
| Integration test gaps | 5 scenarios | MEDIUM |
| Test skeletons provided | 25 | — |

### Implementation Order

1. **Phase 1 (1-2 days):** `test_models.py`, `test_config.py`, `test_ingestion_pipeline.py` — schema + config + data integrity
2. **Phase 2 (1-2 days):** `test_finrl_runner.py`, `test_ml_bucket_selector.py`, `test_indicators.py` — computation logic
3. **Phase 3 (1-2 days):** `test_ta_run.py`, `test_error_handling_*.py` — error paths + async
4. **Phase 4 (1 day):** Integration tests, `test_cached_repo.py`, edge case additions to existing tests

### pytest.ini additions

```ini
[pytest]
markers =
    smoke: smoke tests — train + predict pipelines with real DB data
    e2e: end-to-end Playwright tests — require running Streamlit server
    unit: pure logic tests, no I/O
    integration: tests requiring database
    slow: tests that hit external APIs or take >1s
```
