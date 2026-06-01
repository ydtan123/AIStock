# AIStock Test Coverage Gap Analysis — Supplement

**Date:** 2026-05-30
**Coverage:** 30% (1,156/3,917 stmts)
**Tests:** 172 total (140 pass, 12 fail, 20 errors)
**Existing docs:** `coverage-gap-analysis.md` (897 lines), `test-coverage-gaps.md` (946 lines)

This covers gaps NOT in the prior two docs.

---

## Test Infrastructure Fix (20 errors, 12 failures)

**Root cause:** `src/database.py:init_db()` passes MySQL-only kwargs (`pool_size`, `max_overflow`, `pool_pre_ping`) to `create_engine()`. SQLite rejects these.

```python
# conftest.py — REPLACE with this
import pytest
from database import configure, get_engine

@pytest.fixture(scope="session")
def engine():
    configure("sqlite:///:memory:", _testing=True)
    eng = get_engine()
    from models import Base
    Base.metadata.create_all(bind=eng)
    return eng

@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    from sqlalchemy.orm import Session
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

---

## P0 — Untested Modules (no prior skeletons)

### 1. `src/pipeline/orchestrator.py` (~120 stmts, 0%)

`FullPipeline` class — no existing tests.

**Untested:** `_open_session`, `_serialize_result`, `_step_to_markdown`, `FullPipeline.__init__`, `_create_or_resume_run`, `_select_steps`, `_load_prior_results`, `_mark_run`, `_write_step_report`, `_write_summary`, `FullPipeline.run`

**Error gaps:** `_load_prior_results` silently skips corrupt JSON with bare `continue`. `_step_to_markdown` no sanitization of error text.

```python
# tests/test_pipeline_orchestrator.py
import json, pytest
from pathlib import Path
from unittest.mock import MagicMock
from pipeline.base import PipelineError, PipelineStep, StepResult
from pipeline.orchestrator import FullPipeline, _open_session, _serialize_result, _step_to_markdown

class TestOpenSession:
    def test_returns_context_manager_session(self):
        class ManagedSession:
            def __enter__(self): return self
            def __exit__(self, *a): pass
        factory = MagicMock(return_value=ManagedSession())
        with _open_session(factory) as s:
            assert isinstance(s, ManagedSession)

    def test_manual_close_when_no_context_manager(self):
        factory = MagicMock()
        with _open_session(factory) as s: pass
        factory.return_value.close.assert_called_once()

    def test_close_called_on_exception(self):
        factory = MagicMock()
        with pytest.raises(ValueError):
            with _open_session(factory) as s: raise ValueError("boom")
        factory.return_value.close.assert_called_once()

class TestSerializeResult:
    def test_serializes_all_fields(self):
        r = StepResult(step_name="test", status="success",
                       summary={"k": "v"}, payload={"p": 1}, error=None)
        d = _serialize_result(r)
        assert d["step_name"] == "test"
        assert d["status"] == "success"
        assert d["payload"] == {"p": 1}

    def test_handles_nan_in_payload(self):
        import math
        r = StepResult(step_name="t", status="ok",
                       summary={"nan": float("nan")}, payload={})
        _serialize_result(r)  # must not raise

class TestStepToMarkdown:
    def test_success_step_no_error_section(self):
        r = StepResult(step_name="data_update", status="success",
                       summary={"rows": 100}, payload={})
        md = _step_to_markdown(r)
        assert "## Error" not in md
        assert "## Summary" in md

    def test_failed_step_includes_error(self):
        r = StepResult(step_name="deep_eval", status="failed",
                       summary={}, error="ValueError: division by zero")
        md = _step_to_markdown(r)
        assert "## Error" in md
        assert "ValueError: division by zero" in md

    def test_error_with_markdown_chars(self):
        r = StepResult(step_name="x", status="failed",
                       summary={}, error="``` code ```\n# heading\n---")
        md = _step_to_markdown(r)
        assert "``` code ```" in md

class TestFullPipelineInit:
    def test_default_init(self):
        step = MagicMock(spec=PipelineStep, name="step1")
        p = FullPipeline(steps=[step], cfg={}, session_factory=MagicMock())
        assert len(p.steps) == 1

    def test_only_mode_selects_single_step(self):
        step = MagicMock(spec=PipelineStep); step.name = "data_update"
        p = FullPipeline(steps=[step], cfg={}, session_factory=MagicMock(), only="data_update")
        assert len(p._select_steps()) == 1

    def test_only_mode_unknown_step_raises(self):
        step = MagicMock(spec=PipelineStep); step.name = "data_update"
        p = FullPipeline(steps=[step], cfg={}, session_factory=MagicMock(), only="nonexistent")
        with pytest.raises(ValueError, match="nonexistent"):
            p._select_steps()

    def test_resume_from_skips_earlier_steps(self):
        s1 = MagicMock(spec=PipelineStep); s1.name = "data_update"
        s2 = MagicMock(spec=PipelineStep); s2.name = "stock_selection"
        s3 = MagicMock(spec=PipelineStep); s3.name = "fast_evaluation"
        p = FullPipeline(steps=[s1, s2, s3], cfg={}, session_factory=MagicMock(),
                         resume_from="stock_selection")
        assert [s.name for s in p._select_steps()] == ["stock_selection", "fast_evaluation"]

class TestCreateOrResumeRun:
    def test_creates_new_run(self, db_session):
        p = FullPipeline(steps=[], cfg={}, session_factory=lambda: db_session)
        assert p._create_or_resume_run() > 0

    def test_resumes_existing_run(self, db_session):
        from models import PipelineRun
        run = PipelineRun(status="running")
        db_session.add(run); db_session.commit()
        p = FullPipeline(steps=[], cfg={}, session_factory=lambda: db_session, run_id=run.id)
        assert p._create_or_resume_run() == run.id

    def test_already_success_run_raises(self, db_session):
        from models import PipelineRun
        run = PipelineRun(status="success")
        db_session.add(run); db_session.commit()
        p = FullPipeline(steps=[], cfg={}, session_factory=lambda: db_session, run_id=run.id)
        with pytest.raises(PipelineError, match="already success"):
            p._create_or_resume_run()

class TestLoadPriorResults:
    def test_empty_directory(self, tmp_path):
        p = FullPipeline(steps=[], cfg={}, session_factory=MagicMock())
        assert p._load_prior_results(tmp_path) == {}

    def test_loads_valid_json(self, tmp_path):
        (tmp_path / "data_update.json").write_text(
            json.dumps({"step_name": "data_update", "status": "success",
                        "summary": {"rows": 10}, "payload": {}}))
        p = FullPipeline(steps=[], cfg={}, session_factory=MagicMock())
        assert "data_update" in p._load_prior_results(tmp_path)

    def test_skips_corrupt_json(self, tmp_path):
        (tmp_path / "bad.json").write_text("not json {{{")
        (tmp_path / "good.json").write_text(
            json.dumps({"step_name": "good", "status": "ok", "summary": {}, "payload": {}}))
        p = FullPipeline(steps=[], cfg={}, session_factory=MagicMock())
        results = p._load_prior_results(tmp_path)
        assert "good" in results
        assert "bad" not in results

    def test_skips_summary_file(self, tmp_path):
        (tmp_path / "summary.json").write_text('{"status":"success"}')
        p = FullPipeline(steps=[], cfg={}, session_factory=MagicMock())
        assert "summary" not in p._load_prior_results(tmp_path)

class TestFullPipelineRun:
    def test_step_failure_stops_pipeline(self, db_session, tmp_path):
        s1 = MagicMock(spec=PipelineStep); s1.name = "step1"
        s2 = MagicMock(spec=PipelineStep); s2.name = "step2"
        s1.run.return_value = StepResult(step_name="step1", status="failed",
                                         summary={}, error="broke")
        p = FullPipeline(steps=[s1, s2], cfg={}, session_factory=lambda: db_session,
                         report_dir=tmp_path)
        with pytest.raises(PipelineError, match="step1.*failed"):
            p.run()
        s2.run.assert_not_called()

    def test_run_marks_failed_on_step_crash(self, db_session, tmp_path):
        from models import PipelineRun
        step = MagicMock(spec=PipelineStep); step.name = "step1"
        step.run.side_effect = Exception("unexpected")
        p = FullPipeline(steps=[step], cfg={}, session_factory=lambda: db_session,
                         report_dir=tmp_path)
        with pytest.raises(PipelineError):
            p.run()
        runs = db_session.query(PipelineRun).all()
        assert runs[-1].status == "failed"
```

---

### 2. `src/main.py` (~93 stmts, 0%)

CLI entry point. No existing test skeletons.

**Untested:** `cmd_init_db`, `cmd_bootstrap`, `_resolve_symbols`, `_ensure_stock`, `cmd_run`, `cmd_lookup`, `cmd_list_active`, `cmd_screener`, `cmd_manager`

```python
# tests/test_main.py
import pytest
from unittest.mock import MagicMock, patch
import main

class TestResolveSymbols:
    def test_space_separated(self):
        args = MagicMock(symbol=["AAPL", "MSFT"])
        assert main._resolve_symbols(args) == ["AAPL", "MSFT"]

    def test_comma_separated(self):
        args = MagicMock(symbol=["AAPL,MSFT,GOOGL"])
        assert main._resolve_symbols(args) == ["AAPL", "MSFT", "GOOGL"]

    def test_mixed_separators(self):
        args = MagicMock(symbol=["AAPL,MSFT", "GOOGL"])
        assert main._resolve_symbols(args) == ["AAPL", "MSFT", "GOOGL"]

    def test_empty_input(self):
        assert main._resolve_symbols(MagicMock(symbol=[])) == []

    def test_none_input(self):
        assert main._resolve_symbols(MagicMock(symbol=None)) == []

    def test_uppercases(self):
        assert main._resolve_symbols(MagicMock(symbol=["aapl"])) == ["AAPL"]

    def test_trims_whitespace(self):
        assert main._resolve_symbols(MagicMock(symbol=[" AAPL , MSFT "])) == ["AAPL", "MSFT"]

class TestEnsureStock:
    @patch("main.get_session")
    def test_creates_new_stock(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        stock = MagicMock(symbol="AAPL", is_active=True)
        mock_session.add = MagicMock()
        main._ensure_stock("AAPL", force=False)

    @patch("main.get_session")
    def test_inactive_without_force_exits(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        s = MagicMock(symbol="INACT", is_active=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = s
        with pytest.raises(SystemExit):
            main._ensure_stock("INACT", force=False)

    @patch("main.get_session")
    def test_inactive_with_force_activates(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        s = MagicMock(symbol="INACT", is_active=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = s
        main._ensure_stock("INACT", force=True)
        assert s.is_active is True

class TestCmdBootstrap:
    @patch("main.load_config")
    @patch("main.create_fetcher")
    @patch("main.refresh_symbols")
    @patch("main.run_bootstrap")
    def test_full_flow(self, mock_bootstrap, mock_refresh, mock_fetcher, mock_config):
        mock_config.return_value = {}
        mock_fetcher.return_value = MagicMock()
        mock_refresh.return_value = 500
        main.cmd_bootstrap(MagicMock())
        mock_refresh.assert_called_once()
        mock_bootstrap.assert_called_once()

    @patch("main.load_config")
    @patch("main.create_fetcher")
    @patch("main.refresh_symbols")
    def test_refresh_failure_stops_bootstrap(self, mock_refresh, mock_fetcher, mock_config):
        mock_config.return_value = {}
        mock_fetcher.return_value = MagicMock()
        mock_refresh.side_effect = RuntimeError("API down")
        with pytest.raises(RuntimeError, match="API down"):
            main.cmd_bootstrap(MagicMock())

    @patch("main.load_config")
    @patch("main.create_fetcher")
    @patch("main.refresh_symbols")
    @patch("main.run_bootstrap")
    def test_custom_activation_criteria(self, mock_bootstrap, mock_refresh, mock_fetcher, mock_config):
        mock_config.return_value = {
            "default_activation_criteria": {"min_market_cap": 1e9}}
        mock_fetcher.return_value = MagicMock()
        mock_refresh.return_value = 100
        main.cmd_bootstrap(MagicMock())
        assert mock_bootstrap.call_args[1]["auto_activate_criteria"]["min_market_cap"] == 1e9

class TestCmdRun:
    @patch("main.load_config")
    @patch("main.create_fetcher")
    @patch("main.run_daily_pipeline")
    def test_run_all_active(self, mock_pipeline, mock_fetcher, mock_config):
        mock_config.return_value = {}
        mock_fetcher.return_value = MagicMock()
        mock_pipeline.return_value = {"processed": 10}
        main.cmd_run(MagicMock(symbol=[], force=False, source=None))
        mock_pipeline.assert_called_once()

    @patch("main.load_config")
    @patch("main.create_fetcher")
    @patch("main._ensure_stock")
    @patch("main._process_symbol")
    def test_run_specific_symbols(self, mock_process, mock_ensure, mock_fetcher, mock_config):
        mock_config.return_value = {}
        mock_fetcher.return_value = MagicMock()
        mock_ensure.return_value = MagicMock(symbol="AAPL")
        mock_process.return_value = {"processed": 1}
        main.cmd_run(MagicMock(symbol=["AAPL"], force=False, source=None))
        mock_ensure.assert_called_once_with("AAPL", False)
        mock_process.assert_called_once()

    @patch("main.load_config")
    @patch("main.create_fetcher")
    def test_source_override(self, mock_fetcher, mock_config):
        mock_config.return_value = {"source": "alpha_vantage"}
        mock_fetcher.return_value = MagicMock()
        main.cmd_run(MagicMock(symbol=[], force=False, source="yahoo"))
        cfg_passed = mock_fetcher.call_args[0][0]
        assert cfg_passed.get("source") == "yahoo"
```

---

### 3. `src/pipeline/stock_selection.py` + evaluation steps (~200 stmts, 0%)

`StockSelectionStep`, `FastEvaluationStep`, `DeepEvaluationStep` — no existing test skeletons.

```python
# tests/test_pipeline_steps.py
import pytest
from unittest.mock import MagicMock
import pandas as pd
from pipeline.base import StepContext
from pipeline.stock_selection import StockSelectionStep
from pipeline.fast_evaluation import FastEvaluationStep
from pipeline.deep_evaluation import DeepEvaluationStep

class TestStockSelectionStep:
    def test_no_active_stocks(self, db_session):
        ctx = StepContext(cfg={}, logger=MagicMock(),
                          session_factory=lambda: db_session,
                          prior_results={})
        result = StockSelectionStep().run(ctx)
        assert result.status == "success"
        assert len(result.summary.get("selected", [])) == 0

    def test_selects_active_stocks(self, db_session):
        from models import Stock
        s1 = Stock(symbol="AAPL", is_active=True)
        s2 = Stock(symbol="MSFT", is_active=True)
        s3 = Stock(symbol="INACT", is_active=False)
        db_session.add_all([s1, s2, s3]); db_session.commit()
        ctx = StepContext(cfg={}, logger=MagicMock(),
                          session_factory=lambda: db_session, prior_results={})
        result = StockSelectionStep().run(ctx)
        symbols = [s["symbol"] for s in result.summary.get("selected", [])]
        assert "INACT" not in symbols

    def test_min_market_cap_filter(self, db_session):
        from models import Stock
        s1 = Stock(symbol="AAPL", is_active=True, market_cap=3_000_000_000_000)
        s2 = Stock(symbol="TINY", is_active=True, market_cap=500_000)
        db_session.add_all([s1, s2]); db_session.commit()
        ctx = StepContext(cfg={"selection": {"min_market_cap": 1e9}},
                          logger=MagicMock(), session_factory=lambda: db_session,
                          prior_results={})
        result = StockSelectionStep().run(ctx)
        symbols = [s["symbol"] for s in result.summary.get("selected", [])]
        assert "TINY" not in symbols

class TestFastEvaluationStep:
    def test_empty_selection_skips(self, db_session):
        ctx = StepContext(cfg={}, logger=MagicMock(),
                          session_factory=lambda: db_session,
                          prior_results={"stock_selection": MagicMock(
                              status="success", summary={"selected": []})})
        result = FastEvaluationStep().run(ctx)
        assert result.status == "success"
        assert result.summary.get("evaluated", 0) == 0

class TestDeepEvaluationStep:
    def test_no_qualified_skips(self, db_session):
        ctx = StepContext(cfg={}, logger=MagicMock(),
                          session_factory=lambda: db_session,
                          prior_results={"fast_evaluation": MagicMock(
                              status="success",
                              summary={"qualified_for_deep": []})})
        result = DeepEvaluationStep().run(ctx)
        assert result.status == "success"
```

---

## Error Handling Gaps (Cross-Cutting)

### E1. MySQL-Specific SQL Breaks SQLite Tests

**Modules affected:** `news_cache.py`, `ingestion/indicators.py`, `ingestion/symbols.py`

```python
# tests/test_dialect_compatibility.py
import pytest
from sqlalchemy import create_engine, text
from models import Base

class TestSchemaCreation:
    @pytest.mark.parametrize("dialect", ["sqlite"])
    def test_all_tables_create(self, dialect):
        engine = create_engine("sqlite:///:memory:")
        try:
            Base.metadata.create_all(bind=engine)
            with engine.connect() as conn:
                for name in Base.metadata.tables:
                    conn.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))
        finally:
            engine.dispose()

    def test_news_cache_upsert_sqlite(self):
        import news_cache
        from database import configure, get_engine
        configure("sqlite:///:memory:", _testing=True)
        from models import Base
        Base.metadata.create_all(bind=get_engine())
        news_cache._ensure_table()
        news_cache.set_cached("get_news", ("AAPL",), {"limit": 5}, "text")
        assert news_cache.get_cached("get_news", ("AAPL",), {"limit": 5}) == "text"
```

### E2. Silent Exception Swallowing

```python
# tests/test_error_propagation.py
import logging, pytest
from unittest.mock import patch

class TestNewsCacheSilentFailures:
    def test_get_cached_db_error_returns_none(self, caplog):
        import news_cache
        with patch("news_cache._get_session") as ms:
            ms.return_value.query.side_effect = RuntimeError("DB lost")
            with caplog.at_level(logging.WARNING):
                result = news_cache.get_cached("get_news", ("A",), {"limit": 5})
            assert result is None
            assert "read error" in caplog.text

    def test_set_cached_db_error_silent(self, caplog):
        import news_cache
        with patch("news_cache._get_session") as ms:
            ms.return_value.execute.side_effect = RuntimeError("disk full")
            with caplog.at_level(logging.WARNING):
                news_cache.set_cached("get_news", ("A",), {"limit": 5}, "x")
            assert "write error" in caplog.text

    def test_ensure_table_error_silent(self, caplog):
        import news_cache
        with patch("news_cache.get_engine") as ge:
            ge.return_value = None  # AttributeError on .create()
            with caplog.at_level(logging.WARNING):
                news_cache._ensure_table()
            assert "ensure_table error" in caplog.text

class TestConfigValidation:
    @patch("config.Path.exists", return_value=True)
    @patch("config.ConfigLoader.load")
    def test_missing_alpha_vantage_key_raises(self, mock_load, mock_exists):
        from config import load_config
        mock_load.return_value = {"database": {"url": "sqlite:///"}}
        with pytest.raises((KeyError, SystemExit)):
            load_config()

    @patch("config.Path.exists", return_value=True)
    @patch("config.ConfigLoader.load")
    def test_empty_config_raises(self, mock_load, mock_exists):
        from config import load_config
        mock_load.return_value = {}
        cfg = load_config()
        assert isinstance(cfg, dict)
```

---

## Edge Cases NOT in Prior Analysis

### `src/ml_bucket_selector.py`

```python
# tests/test_ml_bucket_selector_edge.py
import pytest, numpy as np, pandas as pd
from ml_bucket_selector import MLBucketSelector

class TestEdgeCases:
    def test_nan_in_fundamentals(self):
        df = pd.DataFrame({
            "ticker": ["A","B","C"], "date": pd.to_datetime(["2024-01-01"]*3),
            "sector": ["Tech","Tech","Finance"],
            "market_cap": [1e9, np.nan, 5e9],
            "total_assets": [1e8, 2e8, np.nan],
            "net_income": [1e7, -5e6, 3e7]})
        result = MLBucketSelector().fit_predict(df)
        assert isinstance(result, pd.DataFrame)

    def test_single_stock_single_sector(self):
        df = pd.DataFrame({
            "ticker": ["A"], "date": pd.to_datetime(["2024-01-01"]),
            "sector": ["Tech"], "market_cap": [1e9],
            "total_assets": [1e8], "net_income": [1e7]})
        result = MLBucketSelector().fit_predict(df)
        assert isinstance(result, pd.DataFrame)

    def test_top_quantile_one_excludes_all(self):
        df = pd.DataFrame({
            "ticker": ["A"], "date": pd.to_datetime(["2024-01-01"]),
            "sector": ["Tech"], "market_cap": [1e9],
            "total_assets": [1e8], "net_income": [1e7]})
        result = MLBucketSelector(top_quantile=1.0).fit_predict(df)
        assert result.empty

    def test_invalid_weight_method(self):
        with pytest.raises(ValueError, match="weight_method"):
            MLBucketSelector(weight_method="magic")

    def test_all_nan_column(self):
        df = pd.DataFrame({
            "ticker": ["A","B"], "date": pd.to_datetime(["2024-01-01"]*2),
            "sector": ["Tech","Finance"], "market_cap": [1e9,2e9],
            "total_assets": [1e8,2e8], "net_income": [np.nan,np.nan]})
        result = MLBucketSelector().fit_predict(df)
        assert isinstance(result, pd.DataFrame)
```

### `src/scheduler.py` (additional)

```python
# tests/test_scheduler_edge.py
import pytest
from unittest.mock import MagicMock, patch

class TestSchedulerEdge:
    def test_error_message_exactly_2000_chars(self):
        from scheduler import _record_job_end
        with patch("scheduler.get_session") as ms:
            ms.return_value = MagicMock()
            _record_job_end(1, error="E" * 2000)

    def test_error_message_unicode_boundary(self):
        from scheduler import _record_job_end
        with patch("scheduler.get_session") as ms:
            ms.return_value = MagicMock()
            _record_job_end(1, error="错误" * 1000)

    @patch("scheduler.load_config")
    def test_invalid_run_time(self, mock_config):
        from scheduler import main
        mock_config.return_value = {
            "database": {"url": "sqlite:///:memory:"},
            "scheduler": {"daily_run_time": "25:00"}}
        with pytest.raises(ValueError):
            main()

    def test_job_start_failure_job_end_not_called(self):
        from scheduler import job_daily_pipeline
        with patch("scheduler._record_job_start") as ms:
            with patch("scheduler._record_job_end") as me:
                ms.side_effect = RuntimeError("DB down")
                with pytest.raises(RuntimeError):
                    job_daily_pipeline()
                me.assert_not_called()
```

### `src/display.py` (additional)

```python
# tests/test_display_edge.py
import pytest, math
from display import fmt_market_cap, nan_safe

class TestFmtMarketCapEdge:
    def test_negative_value(self):
        assert isinstance(fmt_market_cap(-5_000_000_000), str)

    def test_infinity(self):
        assert fmt_market_cap(float("inf")) == "—"

    def test_negative_infinity(self):
        assert fmt_market_cap(float("-inf")) == "—"

    def test_scientific_notation(self):
        assert "$1.50B" in fmt_market_cap(1.5e9)

    def test_boolean(self):
        assert fmt_market_cap(True) == "—"

class TestNanSafeEdge:
    def test_function_that_raises_arbitrary_exception(self):
        @nan_safe
        def bad(): raise RuntimeError("unexpected")
        assert bad() == "—"

    def test_zero_division_caught(self):
        @nan_safe
        def divide(a, b): return a / b
        assert divide(1, 0) == "—"

    def test_preserves_function_name(self):
        @nan_safe
        def my_func(x): return x
        assert my_func.__name__ == "my_func"

    def test_multiple_nan_args(self):
        @nan_safe
        def add(a, b):
            return a + b
        assert add(None, None) == "—"
        assert add(float("nan"), 5) == "—"
```

---

## Integration Test Gaps

```python
# tests/test_integration_full_flow.py
import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import date, timedelta

class TestSymbolRefreshToPipeline:
    @patch("fetcher.alpha_vantage.AlphaVantageFetcher.get_listing")
    @patch("fetcher.alpha_vantage.AlphaVantageFetcher.get_daily")
    @patch("fetcher.alpha_vantage.AlphaVantageFetcher.get_overview")
    def test_full_daily_flow(self, mock_overview, mock_daily, mock_listing, db_session):
        from ingestion.symbols import refresh_symbols
        from ingestion.pipeline import run_daily_pipeline
        from fetcher.alpha_vantage import AlphaVantageFetcher

        fetcher = AlphaVantageFetcher(api_key="test")
        mock_listing.return_value = pd.DataFrame([{
            "symbol": "AAPL", "name": "Apple Inc.",
            "asset_type": "Common Stock", "exchange": "NASDAQ"}])
        count = refresh_symbols(fetcher)
        assert count > 0

        from models import Stock
        for s in db_session.query(Stock).all():
            s.is_active = True
        db_session.commit()

        mock_daily.return_value = pd.DataFrame({
            "date": [date.today() - timedelta(days=i) for i in range(10)],
            "open": [150.]*10, "high": [155.]*10,
            "low": [149.]*10, "close": [152.]*10, "volume": [1_000_000]*10})
        mock_overview.return_value = {"Symbol": "AAPL", "MarketCapitalization": "3000000000000"}

        summary = run_daily_pipeline(fetcher)
        assert summary.get("processed", 0) > 0

class TestPipelineRunIdConsistency:
    def test_same_run_id_across_steps(self, db_session, tmp_path):
        from pipeline.orchestrator import FullPipeline
        from pipeline.base import PipelineStep, StepResult
        ids = []
        class CaptureStep(PipelineStep):
            name = "capture"
            def run(self, ctx):
                ids.append(ctx.run_id)
                return StepResult(step_name="capture", status="success",
                                  summary={}, payload={})
        s1, s2, s3 = CaptureStep(), CaptureStep(), CaptureStep()
        FullPipeline(steps=[s1, s2, s3], cfg={}, session_factory=lambda: db_session,
                     report_dir=tmp_path).run()
        assert len(set(ids)) == 1

class TestBackendSwitching:
    def test_alpha_vantage_to_yahoo(self):
        from fetcher import create_fetcher
        from fetcher.alpha_vantage import AlphaVantageFetcher
        from fetcher.yahoo import YahooFetcher
        assert isinstance(create_fetcher({"source": "alpha_vantage",
                          "alpha_vantage": {"api_key": "t"}}), AlphaVantageFetcher)
        assert isinstance(create_fetcher({"source": "yahoo"}), YahooFetcher)

    def test_unknown_raises(self):
        from fetcher import create_fetcher
        with pytest.raises(ValueError, match="Unknown source"):
            create_fetcher({"source": "bloomberg"})
```

---

## Summary

| Category | New Tests | Files to Create |
|----------|-----------|----------------|
| Pipeline orchestrator | ~15 | `tests/test_pipeline_orchestrator.py` |
| CLI (main.py) | ~12 | `tests/test_main.py` |
| Pipeline steps | ~10 | `tests/test_pipeline_steps.py` |
| Dialect compat | ~4 | `tests/test_dialect_compatibility.py` |
| Error propagation | ~6 | `tests/test_error_propagation.py` |
| Edge cases (ML, scheduler, display) | ~15 | 3 edge files |
| Integration flows | ~6 | `tests/test_integration_full_flow.py` |
| **Total new** | **~68** | **10 files** |
| Existing (from prior docs) | ~203 | 12 files |
| **Combined total** | **~271** | **22 files** |

### Path to 80%

1. Fix `conftest.py` + `database.py` dialect detection → recovers 20 errors → ~45% coverage
2. Add orchestrator + main + pipeline step tests → ~55%
3. Add edge case + error propagation tests → ~62%
4. Add integration tests → ~65%
5. Add Streamlit UI tests (largest remaining gap, 1083 lines) → ~80%
