# Full Pipeline OOP Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-organize the 4-step trading pipeline as an OOP system with pluggable backends. All steps share a single `pipeline_run_id`. Steps 2/3/4 run in-process (no subprocess) via concrete backends that wrap existing submodules.

**Architecture:** A `src/pipeline/` package with a `PipelineStep` ABC and four step classes (`DataUpdateStep`, `StockSelectionStep`, `FastEvaluationStep`, `DeepEvaluationStep`). Each step that supports backend swap selects a concrete `StockSelector` / `FastEvaluator` / `DeepEvaluator` from a registry via the `backend:` config key. Default backends wrap `FinRL-Trading`, `ai-hedge-fund`, and `TradingAgents`. A `FullPipeline` orchestrator owns the `pipeline_runs` row, manages step execution, writes JSON/Markdown reports, and supports `--resume-from`.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0 (declarative), pytest, MySQL via pymysql, langgraph/langchain (added for ai-hedge-fund in-process), existing TradingAgents and FinRL-Trading submodules.

**Approved spec:** `docs/superpowers/specs/2026-05-17-full-pipeline-oop-redesign.md`

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `src/pipeline/__init__.py` | Package marker; re-exports public API |
| `src/pipeline/base.py` | `PipelineStep` ABC, `StepResult`, `StepContext` dataclasses, `PipelineError` |
| `src/pipeline/config.py` | `ConfigLoader` — YAML + dotted-path overrides + backwards-compat mapping |
| `src/pipeline/orchestrator.py` | `FullPipeline` orchestrator class |
| `src/pipeline/data_update.py` | `DataUpdateStep` (step 1) |
| `src/pipeline/stock_selection.py` | `StockSelectionStep` (step 2) |
| `src/pipeline/fast_evaluation.py` | `FastEvaluationStep` (step 3) |
| `src/pipeline/deep_evaluation.py` | `DeepEvaluationStep` (step 4) |
| `src/pipeline/backends/__init__.py` | Backends package marker |
| `src/pipeline/backends/selectors.py` | `StockSelector` ABC + `ScoredTicker` + `FinrlStockSelector` + `SELECTOR_REGISTRY` |
| `src/pipeline/backends/fast_evaluators.py` | `FastEvaluator` ABC + `AnalystOpinion` + `FastEvaluation` + `AIHedgeFundFastEvaluator` + `FAST_EVALUATOR_REGISTRY` |
| `src/pipeline/backends/deep_evaluators.py` | `DeepEvaluator` ABC + `DeepEvaluation` + `TradingAgentsDeepEvaluator` + `DEEP_EVALUATOR_REGISTRY` |
| `src/migrations/__init__.py` | Migrations package marker |
| `src/migrations/run.py` | Idempotent migration runner; tracks applied versions in `schema_migrations` |
| `src/migrations/2026_05_17_pipeline_oop.sql` | ALTER TABLE statements for `selected_stocks` |
| `tests/test_pipeline_base.py` | Unit tests for dataclasses and ABC contract |
| `tests/test_pipeline_config.py` | Unit tests for `ConfigLoader` (override, back-compat) |
| `tests/test_pipeline_orchestrator.py` | Orchestrator behavior tests (run_id flow, resume, failure) |
| `tests/test_pipeline_backends.py` | Backend ABC + registry tests with fakes |
| `tests/test_pipeline_data_update.py` | `DataUpdateStep` tests |
| `tests/test_pipeline_stock_selection.py` | `StockSelectionStep` tests |
| `tests/test_pipeline_fast_evaluation.py` | `FastEvaluationStep` tests |
| `tests/test_pipeline_deep_evaluation.py` | `DeepEvaluationStep` tests |
| `tests/test_pipeline_schema.py` | New ORM tables + constraints test (SQLite in-memory) |
| `tests/test_full_pipeline_e2e.py` | End-to-end smoke test with mocks |
| `tests/test_pipeline_config_backcompat.py` | Backwards-compat config mapping tests |

### Modified files

| Path | Responsibility |
|---|---|
| `src/models.py` | Add `FastEvaluationConclusion`, `FastEvaluationAnalyst`, `DeepEvaluationRow`, `SchemaMigration`. Add columns to `SelectedStock`. |
| `src/full_pipeline.py` | Replace with thin CLI shim that invokes `FullPipeline` |
| `src/repository.py` | Add `get_active_stocks()` helper if missing |
| `requirements.txt` (or equivalent) | Add ai-hedge-fund deps (langgraph, langchain-core, langchain-deepseek, etc.) |
| `CLAUDE.md` | Update architecture section to reflect new layout |
| `tests/test_full_pipeline.py` | Delete after E2E rewrite (replaced by `test_full_pipeline_e2e.py`) |

---

## Implementation Notes

- **TDD strict:** every code change preceded by a failing test in the same task.
- **Frequent commits:** each task ends with one commit. If a task spans many sub-features, split it.
- **Run from project root** with `PYTHONPATH=src` for tests (existing convention).
- **Test DB:** unit tests use SQLite in-memory via fixture; only E2E uses MySQL.
- **`sys.path` hazard preservation:** the existing pre-import discipline in `src/finrl_pipeline.py` must also be replicated in `src/pipeline/backends/selectors.py` and `src/pipeline/backends/fast_evaluators.py`. Each import block has a comment explaining why.

---

## Task 1 — Install ai-hedge-fund dependencies into AIStock venv

**Goal:** Make `from src.main import run_hedge_fund` resolve from the AIStock venv with all transitive deps available.

**Files:**
- Modify: `requirements.txt` (or use `pip install` directly if no requirements file exists)
- Create: `tests/test_pipeline_deps_smoke.py`

- [ ] **Step 1: Check what's in ai-hedge-fund's pyproject.toml**

Run via context-mode shell:
```shell
cat external/ai-hedge-fund/pyproject.toml | sed -n '/^\[tool.poetry.dependencies\]/,/^\[/p'
```
Expected: list of langgraph, langchain-*, langchain-deepseek, langchain-anthropic, langchain-google-genai, langchain-groq, langchain-openai, langchain-ollama, pandas, numpy, python-dotenv, matplotlib, tabulate, colorama, questionary, rich, dateparser, plus FastAPI bits for app/backend (skip those).

- [ ] **Step 2: Write the smoke import test**

Create `tests/test_pipeline_deps_smoke.py`:
```python
"""Smoke test verifying ai-hedge-fund and TradingAgents are importable
in-process from the AIStock venv. If this test fails, deps need install.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ai_hedge_fund_importable():
    sys.path.insert(0, str(REPO_ROOT / "external" / "ai-hedge-fund"))
    try:
        from src.main import run_hedge_fund  # noqa: F401
    finally:
        sys.path.pop(0)


def test_trading_agents_importable():
    from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: F401


def test_langgraph_importable():
    import langgraph  # noqa: F401
    from langgraph.graph import StateGraph, END  # noqa: F401


def test_langchain_core_importable():
    from langchain_core.messages import HumanMessage  # noqa: F401
```

- [ ] **Step 3: Run the test, expect failure**

Run: `PYTHONPATH=src pytest tests/test_pipeline_deps_smoke.py -v`
Expected: FAIL on `langgraph` / `langchain_core` import (ai-hedge-fund deps not yet in AIStock venv).

- [ ] **Step 4: Install the required deps**

From `external/ai-hedge-fund/pyproject.toml` core runtime list (skip `[tool.poetry.group.dev]` and FastAPI/backend deps):
```bash
.venv/bin/pip install \
  langgraph \
  langchain-core \
  langchain-deepseek \
  langchain-anthropic \
  langchain-google-genai \
  langchain-groq \
  langchain-openai \
  langchain-ollama \
  python-dotenv \
  tabulate \
  questionary \
  rich \
  dateparser
```

If `pyproject.toml` pins specific versions, copy those pins for langgraph and langchain-core to avoid drift with what ai-hedge-fund expects.

- [ ] **Step 5: Re-run the test, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_deps_smoke.py -v`
Expected: 4 passed.

- [ ] **Step 6: Pin into requirements.txt**

If `requirements.txt` exists at repo root, append the same package list with version pins from `.venv/bin/pip freeze | grep -E '^(langgraph|langchain|dateparser|questionary|rich|tabulate)='`. If no `requirements.txt`, create one with all current installed runtime packages from `pip freeze`.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt tests/test_pipeline_deps_smoke.py
git commit -m "feat(pipeline): install ai-hedge-fund deps into AIStock venv

Enables in-process invocation of run_hedge_fund() and TradingAgentsGraph.
Smoke test guards against accidental dep regression."
```

---

## Task 2 — Pipeline package skeleton + base types

**Goal:** Create `src/pipeline/` with `base.py` defining `StepResult`, `StepContext`, `PipelineStep` ABC, and `PipelineError` exception.

**Files:**
- Create: `src/pipeline/__init__.py`
- Create: `src/pipeline/base.py`
- Create: `tests/test_pipeline_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_base.py`:
```python
"""Tests for pipeline base abstractions."""
import logging
from pathlib import Path

import pytest

from pipeline.base import (
    PipelineError,
    PipelineStep,
    StepContext,
    StepResult,
)


def test_step_result_defaults():
    r = StepResult(step_name="data_update", status="success", summary={"x": 1})
    assert r.payload == {}
    assert r.error is None


def test_step_result_failed():
    r = StepResult(
        step_name="stock_selection",
        status="failed",
        summary={},
        error="boom",
    )
    assert r.status == "failed"
    assert r.error == "boom"


def test_step_context_construction(tmp_path):
    ctx = StepContext(
        cfg={"data_update": {"source": "yahoo"}},
        run_id=42,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )
    assert ctx.run_id == 42
    assert ctx.prior_results == {}


def test_pipeline_step_is_abstract():
    with pytest.raises(TypeError):
        PipelineStep()  # type: ignore[abstract]


def test_pipeline_step_subclass_run_required():
    class IncompleteStep(PipelineStep):
        name = "incomplete"

    with pytest.raises(TypeError):
        IncompleteStep()  # type: ignore[abstract]


def test_pipeline_step_subclass_with_run_works(tmp_path):
    class FakeStep(PipelineStep):
        name = "fake"

        def run(self, ctx):
            return StepResult(step_name=self.name, status="success", summary={})

    step = FakeStep()
    ctx = StepContext(
        cfg={"fake": {"k": "v"}},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )
    result = step.run(ctx)
    assert result.status == "success"


def test_pipeline_step_step_config_helper(tmp_path):
    class FakeStep(PipelineStep):
        name = "fake"

        def run(self, ctx):
            return StepResult(step_name=self.name, status="success", summary={})

    step = FakeStep()
    ctx = StepContext(
        cfg={"fake": {"k": "v"}},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )
    assert step.step_config(ctx) == {"k": "v"}


def test_pipeline_step_step_config_missing_returns_empty(tmp_path):
    class FakeStep(PipelineStep):
        name = "missing"

        def run(self, ctx):
            return StepResult(step_name=self.name, status="success", summary={})

    step = FakeStep()
    ctx = StepContext(
        cfg={},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )
    assert step.step_config(ctx) == {}


def test_pipeline_error_is_exception():
    assert issubclass(PipelineError, Exception)
```

- [ ] **Step 2: Run, expect failure (no module)**

Run: `PYTHONPATH=src pytest tests/test_pipeline_base.py -v`
Expected: ImportError on `from pipeline.base import ...`.

- [ ] **Step 3: Implement `src/pipeline/__init__.py`**

```python
"""Pipeline package: OOP orchestration for AIStock 4-step trading pipeline."""
from pipeline.base import (
    PipelineError,
    PipelineStep,
    StepContext,
    StepResult,
)

__all__ = ["PipelineError", "PipelineStep", "StepContext", "StepResult"]
```

- [ ] **Step 4: Implement `src/pipeline/base.py`**

```python
"""Pipeline base abstractions: StepResult, StepContext, PipelineStep ABC."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class PipelineError(Exception):
    """Raised by the orchestrator when a step fails terminally."""


@dataclass
class StepResult:
    step_name: str
    status: str  # "success" | "skipped" | "failed"
    summary: dict[str, Any]
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class StepContext:
    cfg: dict[str, Any]
    run_id: int
    report_dir: Path
    logger: logging.Logger
    session_factory: Callable[[], Any]
    prior_results: dict[str, StepResult] = field(default_factory=dict)


class PipelineStep(ABC):
    name: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__abstractmethods__:
            return
        if not cls.name:
            raise TypeError(
                f"{cls.__name__} must define a non-empty `name` class attribute"
            )

    @abstractmethod
    def run(self, ctx: StepContext) -> StepResult: ...

    def step_config(self, ctx: StepContext) -> dict[str, Any]:
        return ctx.cfg.get(self.name, {})
```

- [ ] **Step 5: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_base.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add src/pipeline/__init__.py src/pipeline/base.py tests/test_pipeline_base.py
git commit -m "feat(pipeline): add base abstractions (StepResult, StepContext, PipelineStep)"
```

---

## Task 3 — ConfigLoader with dotted-path overrides and back-compat

**Goal:** Load `config.yaml`, apply `--set key.path=value` overrides, map legacy top-level keys (`finrl_pipeline`, `ai_hedge_fund`, `source`, `alpha_vantage`) to new namespaces with a deprecation log.

**Files:**
- Create: `src/pipeline/config.py`
- Create: `tests/test_pipeline_config.py`
- Create: `tests/test_pipeline_config_backcompat.py`

- [ ] **Step 1: Write the failing tests (overrides)**

Create `tests/test_pipeline_config.py`:
```python
"""ConfigLoader tests: YAML load, dotted-path overrides, type parsing."""
import textwrap

import pytest

from pipeline.config import ConfigLoader


def write_config(tmp_path, content):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_load_plain_yaml(tmp_path):
    cfg_path = write_config(tmp_path, """
        database:
          url: "mysql://x"
        data_update:
          source: alpha_vantage
    """)
    loader = ConfigLoader(cfg_path)
    cfg = loader.load()
    assert cfg["database"]["url"] == "mysql://x"
    assert cfg["data_update"]["source"] == "alpha_vantage"


def test_dotted_path_override_simple(tmp_path):
    cfg_path = write_config(tmp_path, """
        fast_evaluation:
          top_n: 10
    """)
    loader = ConfigLoader(cfg_path, overrides=["fast_evaluation.top_n=5"])
    cfg = loader.load()
    assert cfg["fast_evaluation"]["top_n"] == 5


def test_dotted_path_override_creates_missing_parents(tmp_path):
    cfg_path = write_config(tmp_path, "database: {url: 'm'}")
    loader = ConfigLoader(cfg_path, overrides=["deep_evaluation.trading_agents.quick=true"])
    cfg = loader.load()
    assert cfg["deep_evaluation"]["trading_agents"]["quick"] is True


def test_dotted_path_override_yaml_value_parsing(tmp_path):
    cfg_path = write_config(tmp_path, "x: {}")
    loader = ConfigLoader(
        cfg_path,
        overrides=[
            "x.an_int=42",
            "x.a_bool=false",
            "x.a_list=[a,b,c]",
            "x.a_str=hello",
        ],
    )
    cfg = loader.load()
    assert cfg["x"]["an_int"] == 42
    assert cfg["x"]["a_bool"] is False
    assert cfg["x"]["a_list"] == ["a", "b", "c"]
    assert cfg["x"]["a_str"] == "hello"


def test_invalid_override_format_raises(tmp_path):
    cfg_path = write_config(tmp_path, "{}")
    with pytest.raises(ValueError, match="must be KEY=VALUE"):
        ConfigLoader(cfg_path, overrides=["no_equals_sign"]).load()


def test_write_effective_config(tmp_path):
    cfg_path = write_config(tmp_path, "x: 1")
    out_path = tmp_path / "effective.yaml"
    loader = ConfigLoader(cfg_path, overrides=["x=2"])
    cfg = loader.load()
    loader.write_effective(out_path)
    assert out_path.exists()
    content = out_path.read_text()
    assert "x: 2" in content
```

Create `tests/test_pipeline_config_backcompat.py`:
```python
"""Back-compat mapping: legacy config.yaml keys still load."""
import logging
import textwrap

from pipeline.config import ConfigLoader


def write_config(tmp_path, content):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_legacy_finrl_pipeline_key_maps_to_stock_selection(tmp_path, caplog):
    cfg_path = write_config(tmp_path, """
        finrl_pipeline:
          source: AISTOCK_DB
          start_date: "2020-01-01"
    """)
    with caplog.at_level(logging.WARNING):
        cfg = ConfigLoader(cfg_path).load()
    assert cfg["stock_selection"]["backend"] == "finrl"
    assert cfg["stock_selection"]["finrl"]["source"] == "AISTOCK_DB"
    assert any("deprecated" in r.message.lower() for r in caplog.records)


def test_legacy_ai_hedge_fund_key_maps_to_fast_evaluation(tmp_path):
    cfg_path = write_config(tmp_path, """
        ai_hedge_fund:
          model_name: deepseek-v4-pro
          selected_analysts: [warren_buffett]
    """)
    cfg = ConfigLoader(cfg_path).load()
    assert cfg["fast_evaluation"]["backend"] == "ai_hedge_fund"
    assert cfg["fast_evaluation"]["ai_hedge_fund"]["model_name"] == "deepseek-v4-pro"


def test_legacy_top_level_source_maps_to_data_update(tmp_path):
    cfg_path = write_config(tmp_path, """
        source: alpha_vantage
        alpha_vantage:
          api_key: KEY
    """)
    cfg = ConfigLoader(cfg_path).load()
    assert cfg["data_update"]["source"] == "alpha_vantage"
    assert cfg["data_update"]["alpha_vantage"]["api_key"] == "KEY"


def test_new_keys_take_precedence_over_legacy(tmp_path):
    cfg_path = write_config(tmp_path, """
        ai_hedge_fund:
          model_name: legacy-model
        fast_evaluation:
          backend: ai_hedge_fund
          ai_hedge_fund:
            model_name: new-model
    """)
    cfg = ConfigLoader(cfg_path).load()
    assert cfg["fast_evaluation"]["ai_hedge_fund"]["model_name"] == "new-model"
```

- [ ] **Step 2: Run tests, expect failure**

Run: `PYTHONPATH=src pytest tests/test_pipeline_config.py tests/test_pipeline_config_backcompat.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/pipeline/config.py`**

```python
"""ConfigLoader: YAML + dotted-path overrides + legacy back-compat."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads config.yaml, applies CLI overrides, maps legacy keys."""

    LEGACY_MAP = {
        # legacy_top_level_key -> (new_step_namespace, new_subkey_or_none, backend_name_or_none)
        "finrl_pipeline": ("stock_selection", "finrl", "finrl"),
        "ai_hedge_fund": ("fast_evaluation", "ai_hedge_fund", "ai_hedge_fund"),
    }

    def __init__(self, path: str | Path, overrides: list[str] | None = None):
        self.path = Path(path)
        self.overrides = overrides or []
        self._cfg: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        with self.path.open() as f:
            cfg = yaml.safe_load(f) or {}
        cfg = self._apply_backcompat(cfg)
        for override in self.overrides:
            self._apply_override(cfg, override)
        self._cfg = cfg
        return cfg

    def write_effective(self, out_path: str | Path) -> None:
        if self._cfg is None:
            raise RuntimeError("call load() before write_effective()")
        Path(out_path).write_text(yaml.safe_dump(self._cfg, sort_keys=False))

    def _apply_backcompat(self, cfg: dict[str, Any]) -> dict[str, Any]:
        # source + alpha_vantage at top level -> data_update
        if "source" in cfg or "alpha_vantage" in cfg:
            du = cfg.setdefault("data_update", {})
            if "source" in cfg and "source" not in du:
                du["source"] = cfg["source"]
                logger.warning(
                    "config.yaml: top-level 'source' is deprecated; "
                    "use 'data_update.source' instead"
                )
            if "alpha_vantage" in cfg and "alpha_vantage" not in du:
                du["alpha_vantage"] = cfg["alpha_vantage"]
                logger.warning(
                    "config.yaml: top-level 'alpha_vantage' is deprecated; "
                    "use 'data_update.alpha_vantage' instead"
                )

        # finrl_pipeline / ai_hedge_fund -> stock_selection / fast_evaluation
        for legacy_key, (new_ns, sub_key, backend) in self.LEGACY_MAP.items():
            if legacy_key not in cfg:
                continue
            new_ns_dict = cfg.setdefault(new_ns, {})
            # Only set backend if not already specified
            new_ns_dict.setdefault("backend", backend)
            existing_sub = new_ns_dict.get(sub_key, {})
            # New keys take precedence; legacy fills gaps only.
            merged = dict(cfg[legacy_key])
            merged.update(existing_sub)
            new_ns_dict[sub_key] = merged
            logger.warning(
                "config.yaml: top-level '%s' is deprecated; "
                "use '%s.%s' instead",
                legacy_key,
                new_ns,
                sub_key,
            )

        return cfg

    @staticmethod
    def _apply_override(cfg: dict[str, Any], override: str) -> None:
        if "=" not in override:
            raise ValueError(
                f"override must be KEY=VALUE, got: {override!r}"
            )
        key_path, raw_value = override.split("=", 1)
        keys = key_path.split(".")
        try:
            value = yaml.safe_load(raw_value)
        except yaml.YAMLError:
            value = raw_value
        node = cfg
        for k in keys[:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value
```

- [ ] **Step 4: Run tests, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_config.py tests/test_pipeline_config_backcompat.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/config.py tests/test_pipeline_config.py tests/test_pipeline_config_backcompat.py
git commit -m "feat(pipeline): ConfigLoader with dotted-path overrides + legacy mapping

Maps deprecated top-level keys (finrl_pipeline, ai_hedge_fund, source,
alpha_vantage) into the new per-step namespaces with a warning."
```

---

## Task 4 — ORM models for new tables + column adds

**Goal:** Define `FastEvaluationConclusion`, `FastEvaluationAnalyst`, `DeepEvaluationRow`, `SchemaMigration`. Add new columns to `SelectedStock` ORM. Make `Base.metadata.create_all` build everything on SQLite.

**Files:**
- Modify: `src/models.py` (append new classes; add columns to `SelectedStock`)
- Create: `tests/test_pipeline_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_schema.py`:
```python
"""Schema tests: new tables build via create_all, basic insert + constraints."""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import (
    Base,
    DeepEvaluationRow,
    FastEvaluationAnalyst,
    FastEvaluationConclusion,
    PipelineRun,
    SchemaMigration,
    SelectedStock,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_selected_stocks_new_columns(session):
    run = PipelineRun(status="running")
    session.add(run)
    session.flush()
    s = SelectedStock(
        ticker="AAPL",
        model_name="finrl",
        ml_score=0.83,
        date_selected=dt.date(2026, 5, 17),
        pipeline_run_id=run.id,
        sector="Tech",
        backend="finrl",
    )
    session.add(s)
    session.commit()
    assert s.pipeline_run_id == run.id
    assert s.sector == "Tech"
    assert s.backend == "finrl"


def test_fast_evaluation_conclusion_insert(session):
    run = PipelineRun(status="running")
    session.add(run)
    session.flush()
    fec = FastEvaluationConclusion(
        pipeline_run_id=run.id,
        ticker="NVDA",
        backend="ai_hedge_fund",
        start_date=dt.date(2026, 2, 1),
        end_date=dt.date(2026, 5, 1),
        evaluation_date=dt.datetime(2026, 5, 17, 10, 0, 0),
        positive_count=12,
        negative_count=1,
        neutral_count=2,
        total_count=15,
        consensus_score=0.71,
        model_name="deepseek-v4-pro",
        model_provider="DeepSeek",
    )
    session.add(fec)
    session.commit()
    assert fec.id is not None


def test_fast_evaluation_conclusion_unique_constraint(session):
    run = PipelineRun(status="running")
    session.add(run)
    session.flush()
    for ticker in ["NVDA", "NVDA"]:
        session.add(
            FastEvaluationConclusion(
                pipeline_run_id=run.id,
                ticker=ticker,
                backend="ai_hedge_fund",
                start_date=dt.date(2026, 2, 1),
                end_date=dt.date(2026, 5, 1),
                evaluation_date=dt.datetime(2026, 5, 17),
                positive_count=1, negative_count=0, neutral_count=0,
                total_count=1, consensus_score=1.0,
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()


def test_fast_evaluation_analysts_insert(session):
    run = PipelineRun(status="running")
    session.add(run)
    session.flush()
    a = FastEvaluationAnalyst(
        pipeline_run_id=run.id,
        ticker="NVDA",
        backend="ai_hedge_fund",
        analyst_name="warren_buffett",
        opinion="bullish",
        confidence=85.0,
        reasoning="Strong moat",
        start_date=dt.date(2026, 2, 1),
        end_date=dt.date(2026, 5, 1),
        evaluation_date=dt.datetime(2026, 5, 17),
    )
    session.add(a)
    session.commit()
    assert a.id is not None


def test_deep_evaluation_insert(session):
    run = PipelineRun(status="running")
    session.add(run)
    session.flush()
    d = DeepEvaluationRow(
        pipeline_run_id=run.id,
        ticker="NVDA",
        backend="trading_agents",
        evaluation_date=dt.datetime(2026, 5, 17),
        market_report="trends up",
        bull_argument="growth",
        bear_argument="valuation",
        research_manager_decision="BUY",
        trader_plan="Buy 100 shares",
        final_decision="BUY",
        model_name="deepseek-v4-pro",
        extra_outputs={"reflection": "n/a"},
    )
    session.add(d)
    session.commit()
    assert d.id is not None
    fetched = session.query(DeepEvaluationRow).first()
    assert fetched.extra_outputs == {"reflection": "n/a"}


def test_schema_migration_tracking(session):
    m = SchemaMigration(version="2026_05_17_pipeline_oop")
    session.add(m)
    session.commit()
    assert m.applied_at is not None
```

- [ ] **Step 2: Run, expect failure (ImportError)**

Run: `PYTHONPATH=src pytest tests/test_pipeline_schema.py -v`
Expected: ImportError on `DeepEvaluationRow` etc.

- [ ] **Step 3: Locate the imports block of `src/models.py`**

Open `src/models.py` and confirm the imports at the top of the file. Add `JSON`, `UniqueConstraint`, `Index` to the SQLAlchemy imports if not present:

```python
from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey,
    Index, Integer, JSON, String, Text, UniqueConstraint,
)
```

(Adapt to whatever the existing import line uses. Keep imports alphabetized.)

- [ ] **Step 4: Modify `SelectedStock` class — add new columns**

In `src/models.py`, locate the `SelectedStock` class (around line 337 per current state) and add columns after `actual_return`:

```python
class SelectedStock(Base):
    """Stocks selected by the ML pipeline, persisted for predict-only mode."""

    __tablename__ = "selected_stocks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    model_name: Mapped[str] = mapped_column(String(50), nullable=False)
    ml_score: Mapped[float] = mapped_column(Float, nullable=False)
    bucket: Mapped[Optional[str]] = mapped_column(String(50))
    weight: Mapped[Optional[float]] = mapped_column(Float)
    date_selected: Mapped[datetime] = mapped_column(Date, nullable=False)
    model_file: Mapped[Optional[str]] = mapped_column(String(255))
    pipeline_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    predicted_return: Mapped[Optional[float]] = mapped_column(Float)
    predicted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    actual_return: Mapped[Optional[float]] = mapped_column(Float)

    # New columns for OOP pipeline (2026-05-17)
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("pipeline_runs.id"), nullable=True
    )
    sector: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    backend: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_selected_stocks_ticker", "ticker"),
        Index("ix_selected_stocks_run_at", "pipeline_run_at"),
        Index("ix_selected_stocks_run_score", "pipeline_run_id", "ml_score"),
    )
```

(Note: the existing `pipeline_run_at` DateTime is kept for back-compat. New `pipeline_run_id` is the FK to `pipeline_runs`. The migration script ALTERs the live MySQL table — Task 5 covers that. Tests use SQLite + `create_all`, so they pick up the new columns automatically.)

- [ ] **Step 5: Append new ORM classes at end of `src/models.py`**

Append after the last class:

```python
class FastEvaluationConclusion(Base):
    """One row per (pipeline_run, ticker) — consensus from fast evaluators."""

    __tablename__ = "fast_evaluation_conclusion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("pipeline_runs.id"), nullable=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    evaluation_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    positive_count: Mapped[int] = mapped_column(Integer, nullable=False)
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False)
    neutral_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consensus_score: Mapped[float] = mapped_column(Float, nullable=False)
    model_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "ticker",
                         name="uq_fec_run_ticker"),
        Index("ix_fec_run_consensus", "pipeline_run_id", "consensus_score"),
    )


class FastEvaluationAnalyst(Base):
    """One row per (pipeline_run, ticker, analyst) — per-analyst opinions."""

    __tablename__ = "fast_evaluation_analysts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("pipeline_runs.id"), nullable=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    analyst_name: Mapped[str] = mapped_column(String(64), nullable=False)
    opinion: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    evaluation_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "pipeline_run_id", "ticker", "analyst_name",
            name="uq_fea_run_ticker_analyst",
        ),
    )


class DeepEvaluationRow(Base):
    """One row per (pipeline_run, ticker) — TradingAgents-shaped deep eval.

    ORM class name is suffixed with `Row` because `DeepEvaluation` already
    denotes the backend dataclass.
    """

    __tablename__ = "deep_evaluation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("pipeline_runs.id"), nullable=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluation_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    market_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    social_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    news_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fundamentals_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bull_argument: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bear_argument: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_manager_decision: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trader_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_aggressive: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_conservative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_neutral: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_manager_decision: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_outputs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    final_decision: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "ticker",
                         name="uq_de_run_ticker"),
    )


class SchemaMigration(Base):
    """Tracks applied raw-SQL migrations for idempotency."""

    __tablename__ = "schema_migrations"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
```

(Use `MEDIUMTEXT` instead of `Text` on the MySQL side via dialect-specific types if size matters; SQLite tests don't care. To use `MEDIUMTEXT` portably, import `MEDIUMTEXT` from `sqlalchemy.dialects.mysql` and use a `with_variant` pattern. For simplicity in this plan, `Text` is acceptable; bump later if needed.)

- [ ] **Step 6: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_schema.py -v`
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add src/models.py tests/test_pipeline_schema.py
git commit -m "feat(models): add fast_evaluation_* and deep_evaluation tables

Adds SchemaMigration tracker. SelectedStock gets pipeline_run_id,
sector, backend columns and a (run_id, ml_score) composite index."
```

---

## Task 5 — Migration runner + selected_stocks ALTER script

**Goal:** Provide an idempotent migration runner. Write the raw-SQL ALTER for `selected_stocks` so existing MySQL deployments pick up new columns.

**Files:**
- Create: `src/migrations/__init__.py`
- Create: `src/migrations/run.py`
- Create: `src/migrations/2026_05_17_pipeline_oop.sql`
- Create: `tests/test_pipeline_migrations.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_migrations.py`:
```python
"""Migration runner tests: applies once, idempotent, tracks version."""
from pathlib import Path
import textwrap

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from migrations.run import MigrationRunner
from models import Base, SchemaMigration


@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    return e


def test_migration_applies_and_records(tmp_path, engine):
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "2026_05_17_test.sql").write_text(
        "CREATE TABLE foo (id INTEGER PRIMARY KEY);"
    )
    runner = MigrationRunner(engine, mig_dir)
    runner.run_pending()

    with Session(engine) as s:
        rows = s.query(SchemaMigration).all()
        assert [r.version for r in rows] == ["2026_05_17_test"]
        s.execute(text("INSERT INTO foo (id) VALUES (1)"))
        s.commit()


def test_migration_is_idempotent(tmp_path, engine):
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "2026_05_17_test.sql").write_text(
        "CREATE TABLE foo (id INTEGER PRIMARY KEY);"
    )
    runner = MigrationRunner(engine, mig_dir)
    runner.run_pending()
    # Running again should not re-apply (CREATE TABLE would fail otherwise)
    runner.run_pending()
    with Session(engine) as s:
        assert s.query(SchemaMigration).count() == 1


def test_skips_already_applied(tmp_path, engine):
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "a.sql").write_text("CREATE TABLE t1 (id INTEGER);")
    (mig_dir / "b.sql").write_text("CREATE TABLE t2 (id INTEGER);")
    runner = MigrationRunner(engine, mig_dir)
    runner.run_pending()
    # Manually delete one version and check it re-applies; the other stays
    with Session(engine) as s:
        s.query(SchemaMigration).filter_by(version="b").delete()
        s.execute(text("DROP TABLE t2"))
        s.commit()
    runner.run_pending()
    with Session(engine) as s:
        versions = {r.version for r in s.query(SchemaMigration).all()}
        assert versions == {"a", "b"}
```

- [ ] **Step 2: Run, expect failure (ImportError)**

Run: `PYTHONPATH=src pytest tests/test_pipeline_migrations.py -v`
Expected: ImportError on `migrations.run`.

- [ ] **Step 3: Implement migration runner**

Create `src/migrations/__init__.py`:
```python
"""Schema migrations package."""
```

Create `src/migrations/run.py`:
```python
"""Idempotent SQL migration runner. Tracks applied versions in schema_migrations."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from models import SchemaMigration

logger = logging.getLogger(__name__)


class MigrationRunner:
    def __init__(self, engine: Engine, migrations_dir: str | Path):
        self.engine = engine
        self.dir = Path(migrations_dir)

    def applied_versions(self) -> set[str]:
        with Session(self.engine) as s:
            return {r.version for r in s.query(SchemaMigration).all()}

    def discover(self) -> list[Path]:
        return sorted(self.dir.glob("*.sql"))

    def run_pending(self) -> list[str]:
        applied = self.applied_versions()
        ran: list[str] = []
        for path in self.discover():
            version = path.stem
            if version in applied:
                logger.info("skip migration %s (already applied)", version)
                continue
            sql = path.read_text()
            logger.info("applying migration %s", version)
            with self.engine.begin() as conn:
                for statement in self._split_statements(sql):
                    if statement.strip():
                        conn.execute(text(statement))
            with Session(self.engine) as s:
                s.add(SchemaMigration(version=version))
                s.commit()
            ran.append(version)
        return ran

    @staticmethod
    def _split_statements(sql: str) -> list[str]:
        # naive split on `;` at end of line; fine for our use
        return [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
```

- [ ] **Step 4: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_migrations.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write the production migration**

Create `src/migrations/2026_05_17_pipeline_oop.sql`:
```sql
-- 2026-05-17: OOP pipeline column additions for selected_stocks.
-- Idempotency is provided by the MigrationRunner (skips if version present).
-- These statements are written for MySQL; SQLite test path uses create_all
-- and never hits this file.

ALTER TABLE selected_stocks
    ADD COLUMN pipeline_run_id BIGINT NULL,
    ADD COLUMN sector VARCHAR(64) NULL,
    ADD COLUMN backend VARCHAR(32) NULL;

ALTER TABLE selected_stocks
    ADD CONSTRAINT fk_selected_stocks_pipeline_run
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs (id);

CREATE INDEX ix_selected_stocks_run_score
    ON selected_stocks (pipeline_run_id, ml_score);
```

- [ ] **Step 6: Commit**

```bash
git add src/migrations/__init__.py src/migrations/run.py \
        src/migrations/2026_05_17_pipeline_oop.sql \
        tests/test_pipeline_migrations.py
git commit -m "feat(migrations): idempotent SQL runner + selected_stocks ALTER

Adds MigrationRunner using schema_migrations as the bookkeeping table.
First production migration adds pipeline_run_id, sector, backend columns
plus composite index for fast top-N queries by ml_score."
```

---

## Task 6 — `StockSelector` ABC + dataclass + registry

**Goal:** Define the abstract `StockSelector`, `ScoredTicker` dataclass, and empty registry. Skeleton ready for the concrete impl in Task 7.

**Files:**
- Create: `src/pipeline/backends/__init__.py`
- Create: `src/pipeline/backends/selectors.py`
- Create: `tests/test_pipeline_backends.py` (start; will extend in Tasks 7-11)

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_backends.py`:
```python
"""Backend ABC + registry tests using fakes."""
import logging
from pathlib import Path

import pytest

from pipeline.backends.selectors import (
    ScoredTicker,
    SELECTOR_REGISTRY,
    StockSelector,
)
from pipeline.base import StepContext


def make_ctx(tmp_path, cfg=None):
    return StepContext(
        cfg=cfg or {},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )


def test_scored_ticker_construction():
    t = ScoredTicker(ticker="AAPL", ml_score=0.5, sector="Tech")
    assert t.ticker == "AAPL"
    assert t.sector == "Tech"


def test_stock_selector_is_abstract():
    with pytest.raises(TypeError):
        StockSelector()  # type: ignore[abstract]


def test_stock_selector_subclass_must_define_name(tmp_path):
    class NoName(StockSelector):
        def select(self, ctx):
            return []

    with pytest.raises(TypeError, match="name"):
        NoName()  # type: ignore[abstract]


def test_fake_selector_registers_and_runs(tmp_path):
    @SELECTOR_REGISTRY.register
    class FakeSelector(StockSelector):
        name = "fake_selector_test"

        def __init__(self, cfg=None):
            self.cfg = cfg or {}

        def select(self, ctx):
            return [ScoredTicker(ticker="X", ml_score=1.0, sector=None)]

    assert "fake_selector_test" in SELECTOR_REGISTRY
    cls = SELECTOR_REGISTRY.get("fake_selector_test")
    out = cls().select(make_ctx(tmp_path))
    assert out[0].ticker == "X"
    SELECTOR_REGISTRY.unregister("fake_selector_test")
    assert "fake_selector_test" not in SELECTOR_REGISTRY


def test_registry_get_unknown_raises():
    with pytest.raises(KeyError, match="unknown selector"):
        SELECTOR_REGISTRY.get("does_not_exist")
```

- [ ] **Step 2: Run, expect failure (ImportError)**

Run: `PYTHONPATH=src pytest tests/test_pipeline_backends.py -v`
Expected: ImportError on `pipeline.backends.selectors`.

- [ ] **Step 3: Implement**

Create `src/pipeline/backends/__init__.py`:
```python
"""Pluggable backends for pipeline steps 2/3/4."""
```

Create `src/pipeline/backends/selectors.py`:
```python
"""StockSelector ABC + ScoredTicker + registry.

Concrete selectors (e.g. FinrlStockSelector) live in this module as well.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Type

from pipeline.base import StepContext


@dataclass
class ScoredTicker:
    ticker: str
    ml_score: float
    sector: str | None = None


class _Registry:
    def __init__(self, label: str):
        self._label = label
        self._items: dict[str, Type] = {}

    def register(self, cls: Type) -> Type:
        if not getattr(cls, "name", None):
            raise TypeError(f"{cls.__name__} missing required 'name' attribute")
        self._items[cls.name] = cls
        return cls

    def unregister(self, name: str) -> None:
        self._items.pop(name, None)

    def get(self, name: str) -> Type:
        if name not in self._items:
            raise KeyError(f"unknown {self._label}: {name!r}")
        return self._items[name]

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def names(self) -> list[str]:
        return sorted(self._items)


SELECTOR_REGISTRY = _Registry("selector")


class StockSelector(ABC):
    name: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__abstractmethods__:
            return
        if not cls.name:
            raise TypeError(
                f"{cls.__name__} must define a non-empty `name` class attribute"
            )

    @abstractmethod
    def select(self, ctx: StepContext) -> list[ScoredTicker]: ...
```

- [ ] **Step 4: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_backends.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/backends/__init__.py src/pipeline/backends/selectors.py tests/test_pipeline_backends.py
git commit -m "feat(pipeline): StockSelector ABC + ScoredTicker + SELECTOR_REGISTRY"
```

---

## Task 7 — `FinrlStockSelector` concrete backend

**Goal:** Wrap existing `finrl_pipeline.run_pipeline_and_save_report` (or `MLBucketSelector` directly) so it returns `list[ScoredTicker]`. Register under name `finrl`.

**Files:**
- Modify: `src/pipeline/backends/selectors.py` (append `FinrlStockSelector`)
- Modify: `tests/test_pipeline_backends.py` (append concrete test)

- [ ] **Step 1: Inspect existing FinRL output shape**

Run via context-mode shell:
```shell
sed -n '49,180p' src/finrl_pipeline.py
```
Identify whether `run_pipeline_and_save_report` returns the report dict directly, what tickers/scores/sectors keys it uses, and how the `data/selection_report_YYYYMMDD.csv` is shaped. The selector needs to extract ticker, ml_score, sector tuples.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_pipeline_backends.py`:
```python
def test_finrl_stock_selector_uses_run_pipeline(monkeypatch, tmp_path):
    """FinrlStockSelector delegates to finrl_pipeline and returns ScoredTickers."""
    from pipeline.backends import selectors as sel_mod

    # Patch finrl_pipeline.run_pipeline_and_save_report and the helper that
    # reads back the selection report.
    fake_report = {
        "selected_stocks": [
            {"ticker": "AAPL", "ml_score": 0.83, "sector": "Information Technology"},
            {"ticker": "MSFT", "ml_score": 0.79, "sector": "Information Technology"},
        ]
    }
    captured = {}

    def fake_run(cfg_overrides):
        captured["cfg_overrides"] = cfg_overrides
        return fake_report

    monkeypatch.setattr(sel_mod, "_run_finrl_pipeline", fake_run)

    selector = sel_mod.FinrlStockSelector(
        cfg={"source": "AISTOCK_DB", "top_quantile": 0.2}
    )
    out = selector.select(
        make_ctx(tmp_path, cfg={"stock_selection": {"finrl": {"top_quantile": 0.2}}})
    )
    assert [t.ticker for t in out] == ["AAPL", "MSFT"]
    assert out[0].ml_score == 0.83
    assert out[0].sector == "Information Technology"
    assert captured["cfg_overrides"]["top_quantile"] == 0.2


def test_finrl_registered_under_name():
    from pipeline.backends.selectors import SELECTOR_REGISTRY, FinrlStockSelector
    assert SELECTOR_REGISTRY.get("finrl") is FinrlStockSelector
```

- [ ] **Step 3: Run, expect failure (no `FinrlStockSelector` / `_run_finrl_pipeline`)**

Run: `PYTHONPATH=src pytest tests/test_pipeline_backends.py -v`
Expected: AttributeError / ImportError.

- [ ] **Step 4: Implement `FinrlStockSelector`**

Append to `src/pipeline/backends/selectors.py`:

```python
# --- Concrete backend: FinrlStockSelector ------------------------------------
# NOTE: sys.path hazard — external/FinRL-Trading inserts itself at sys.path[0]
# on import of data_fetcher. We pre-import AIStock's config/database/repository/
# models here at module level (already done by the importer of this module via
# the pipeline package), and we keep the FinRL import inside the function to
# delay it until needed.

import logging

logger = logging.getLogger(__name__)


def _run_finrl_pipeline(cfg_overrides: dict) -> dict:
    """Indirection seam — tests monkeypatch this."""
    # Ensure AIStock modules are imported before FinRL touches sys.path.
    import config  # noqa: F401
    import database  # noqa: F401
    import repository  # noqa: F401
    import models  # noqa: F401

    from finrl_pipeline import run_pipeline_and_save_report  # type: ignore

    return run_pipeline_and_save_report(cfg_overrides)


@SELECTOR_REGISTRY.register
class FinrlStockSelector(StockSelector):
    name = "finrl"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def select(self, ctx: StepContext) -> list[ScoredTicker]:
        sub_cfg = self.cfg or ctx.cfg.get("stock_selection", {}).get("finrl", {})
        ctx.logger.info("FinrlStockSelector starting with cfg=%s", sub_cfg)
        report = _run_finrl_pipeline(sub_cfg)
        selected = report.get("selected_stocks", []) if isinstance(report, dict) else []
        out: list[ScoredTicker] = []
        for row in selected:
            out.append(
                ScoredTicker(
                    ticker=row["ticker"],
                    ml_score=float(row.get("ml_score", row.get("score", 0.0))),
                    sector=row.get("sector"),
                )
            )
        ctx.logger.info("FinrlStockSelector produced %d tickers", len(out))
        return out
```

If `run_pipeline_and_save_report` returns a different shape (e.g. a path to a CSV), adapt `_run_finrl_pipeline` to read the CSV and reshape into `{"selected_stocks": [...]}` before returning. Verify by running it in a Python REPL during impl. Adapt the test in Step 2 to match the real return shape if needed.

- [ ] **Step 5: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_backends.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add src/pipeline/backends/selectors.py tests/test_pipeline_backends.py
git commit -m "feat(pipeline): FinrlStockSelector wrapping finrl_pipeline"
```

---

## Task 8 — `FastEvaluator` ABC + dataclasses + registry

**Goal:** Define the abstract `FastEvaluator`, `FastEvaluation` + `AnalystOpinion` dataclasses, and `FAST_EVALUATOR_REGISTRY`.

**Files:**
- Create: `src/pipeline/backends/fast_evaluators.py`
- Modify: `tests/test_pipeline_backends.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_backends.py`:
```python
def test_analyst_opinion_construction():
    from pipeline.backends.fast_evaluators import AnalystOpinion

    o = AnalystOpinion(
        analyst_name="warren_buffett",
        opinion="bullish",
        confidence=80.0,
        reasoning="strong moat",
    )
    assert o.opinion == "bullish"


def test_fast_evaluation_construction():
    from pipeline.backends.fast_evaluators import AnalystOpinion, FastEvaluation

    fe = FastEvaluation(
        ticker="NVDA",
        start_date="2026-02-01",
        end_date="2026-05-01",
        opinions=[
            AnalystOpinion("a", "bullish", 80.0, ""),
            AnalystOpinion("b", "bearish", 40.0, ""),
        ],
        consensus_score=0.33,
    )
    assert fe.ticker == "NVDA"
    assert len(fe.opinions) == 2


def test_fast_evaluator_is_abstract():
    from pipeline.backends.fast_evaluators import FastEvaluator
    with pytest.raises(TypeError):
        FastEvaluator()  # type: ignore[abstract]


def test_fake_fast_evaluator_registers(tmp_path):
    from pipeline.backends.fast_evaluators import (
        AnalystOpinion,
        FAST_EVALUATOR_REGISTRY,
        FastEvaluation,
        FastEvaluator,
    )

    @FAST_EVALUATOR_REGISTRY.register
    class FakeFE(FastEvaluator):
        name = "fake_fe_test"

        def __init__(self, cfg=None):
            self.cfg = cfg or {}

        def evaluate(self, tickers, ctx):
            return [
                FastEvaluation(
                    ticker=t,
                    start_date="2026-01-01",
                    end_date="2026-05-01",
                    opinions=[AnalystOpinion("x", "bullish", 90.0, "ok")],
                    consensus_score=0.9,
                )
                for t in tickers
            ]

    out = FakeFE().evaluate(["A", "B"], make_ctx(tmp_path))
    assert [e.ticker for e in out] == ["A", "B"]
    FAST_EVALUATOR_REGISTRY.unregister("fake_fe_test")
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/test_pipeline_backends.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/pipeline/backends/fast_evaluators.py`:
```python
"""FastEvaluator ABC + AnalystOpinion + FastEvaluation + registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from pipeline.backends.selectors import _Registry
from pipeline.base import StepContext


@dataclass
class AnalystOpinion:
    analyst_name: str
    opinion: str           # "bullish" | "bearish" | "neutral"
    confidence: float      # 0-100
    reasoning: str


@dataclass
class FastEvaluation:
    ticker: str
    start_date: str        # YYYY-MM-DD
    end_date: str          # YYYY-MM-DD
    opinions: list[AnalystOpinion]
    consensus_score: float          # [-1, +1]
    extras: dict = field(default_factory=dict)


FAST_EVALUATOR_REGISTRY = _Registry("fast_evaluator")


class FastEvaluator(ABC):
    name: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__abstractmethods__:
            return
        if not cls.name:
            raise TypeError(
                f"{cls.__name__} must define a non-empty `name` class attribute"
            )

    @abstractmethod
    def evaluate(self, tickers: list[str], ctx: StepContext) -> list[FastEvaluation]: ...
```

- [ ] **Step 4: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_backends.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/backends/fast_evaluators.py tests/test_pipeline_backends.py
git commit -m "feat(pipeline): FastEvaluator ABC + AnalystOpinion/FastEvaluation"
```

---

## Task 9 — `AIHedgeFundFastEvaluator` concrete backend

**Goal:** Wrap `external/ai-hedge-fund/src/main.py:run_hedge_fund` so it produces `list[FastEvaluation]`. Map `bullish/bearish/neutral` signals to opinions, compute confidence-weighted consensus score.

**Files:**
- Modify: `src/pipeline/backends/fast_evaluators.py` (append concrete)
- Modify: `tests/test_pipeline_backends.py` (append concrete test)

- [ ] **Step 1: Inspect ai-hedge-fund analyst_signals output shape**

Run via context-mode shell:
```shell
echo "=== look for analyst_signals usage ==="
grep -rn "analyst_signals" external/ai-hedge-fund/src/ | grep -v __pycache__ | head -30
echo
echo "=== look at one analyst node to confirm output shape ==="
sed -n '1,80p' external/ai-hedge-fund/src/agents/warren_buffett.py
```

Confirm: each analyst stores results in `state["data"]["analyst_signals"][<analyst_name>][<ticker>] = {"signal": "...", "confidence": <0-100>, "reasoning": "..."}` (or similar). Adapt the parser below if the actual structure differs (e.g., if `confidence` is `0–1` instead of `0–100`).

- [ ] **Step 2: Write the failing test**

Append to `tests/test_pipeline_backends.py`:
```python
def test_ai_hedge_fund_fast_evaluator_parses_signals(monkeypatch, tmp_path):
    from pipeline.backends import fast_evaluators as fe_mod

    fake_result = {
        "decisions": {"NVDA": {"action": "buy", "quantity": 0}},
        "analyst_signals": {
            "warren_buffett_agent": {
                "NVDA": {"signal": "bullish", "confidence": 80, "reasoning": "moat"}
            },
            "michael_burry_agent": {
                "NVDA": {"signal": "bearish", "confidence": 60, "reasoning": "bubble"}
            },
            "fundamentals_analyst_agent": {
                "NVDA": {"signal": "neutral", "confidence": 50, "reasoning": "mixed"}
            },
        },
    }
    captured = {}

    def fake_run_hedge_fund(**kwargs):
        captured.update(kwargs)
        return fake_result

    monkeypatch.setattr(fe_mod, "_call_run_hedge_fund", fake_run_hedge_fund)

    ev = fe_mod.AIHedgeFundFastEvaluator(
        cfg={
            "model_name": "deepseek-v4-pro",
            "model_provider": "DeepSeek",
            "start_date": "2026-02-01",
            "end_date": "2026-05-01",
            "selected_analysts": ["warren_buffett", "michael_burry", "fundamentals_analyst"],
        }
    )
    out = ev.evaluate(["NVDA"], make_ctx(tmp_path))
    assert len(out) == 1
    fe = out[0]
    assert fe.ticker == "NVDA"
    assert {o.analyst_name for o in fe.opinions} == {
        "warren_buffett_agent", "michael_burry_agent", "fundamentals_analyst_agent",
    }
    # consensus = (1*80 + -1*60 + 0*50) / (80+60+50) = 20/190 ≈ 0.105
    assert abs(fe.consensus_score - (20 / 190)) < 1e-6
    assert captured["tickers"] == ["NVDA"]
    assert captured["model_name"] == "deepseek-v4-pro"


def test_ai_hedge_fund_registered_under_name():
    from pipeline.backends.fast_evaluators import (
        FAST_EVALUATOR_REGISTRY,
        AIHedgeFundFastEvaluator,
    )
    assert FAST_EVALUATOR_REGISTRY.get("ai_hedge_fund") is AIHedgeFundFastEvaluator
```

- [ ] **Step 3: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/test_pipeline_backends.py -v`
Expected: AttributeError on `AIHedgeFundFastEvaluator`.

- [ ] **Step 4: Implement concrete evaluator**

Append to `src/pipeline/backends/fast_evaluators.py`:

```python
# --- Concrete backend: AIHedgeFundFastEvaluator ------------------------------
# sys.path hazard: external/ai-hedge-fund has its own src/main.py. We must
# pre-import AIStock's `src.main`-conflicting modules before inserting the
# ai-hedge-fund path so that subsequent `from src.main import run_hedge_fund`
# resolves to ai-hedge-fund's own src/main.py, not AIStock's.

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


_AI_HEDGE_FUND_PATH = (
    Path(__file__).resolve().parents[3] / "external" / "ai-hedge-fund"
)


def _ensure_ai_hedge_fund_path() -> None:
    """Insert external/ai-hedge-fund at sys.path[0] if not already there.

    Must be called only AFTER AIStock's own modules (config, database, etc.)
    have been imported in this process.
    """
    p = str(_AI_HEDGE_FUND_PATH)
    if p not in sys.path:
        sys.path.insert(0, p)


def _call_run_hedge_fund(**kwargs):
    """Indirection seam — tests monkeypatch this."""
    _ensure_ai_hedge_fund_path()
    # Import inside the function so monkeypatch in tests doesn't need the heavy import.
    from src.main import run_hedge_fund  # type: ignore[import-not-found]
    return run_hedge_fund(**kwargs)


def _inject_api_keys(ctx_cfg: dict) -> None:
    common = ctx_cfg.get("common", {})
    mapping = {
        "DEEPSEEK_API_KEY": common.get("deepseek_api_key"),
        "OPENAI_API_KEY": common.get("openai_api_key"),
        "ANTHROPIC_API_KEY": common.get("anthropic_api_key"),
        "GOOGLE_API_KEY": common.get("google_api_key"),
        "GROQ_API_KEY": common.get("groq_api_key"),
    }
    for env_var, value in mapping.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value


def _resolve_dates(start: str, end: str) -> tuple[str, str]:
    final_end = end or datetime.now().strftime("%Y-%m-%d")
    if start:
        final_start = start
    else:
        end_dt = datetime.strptime(final_end, "%Y-%m-%d")
        final_start = (end_dt - timedelta(days=90)).strftime("%Y-%m-%d")
    return final_start, final_end


_SIGN_BY_OPINION = {"bullish": 1, "bearish": -1, "neutral": 0}


def _compute_consensus(opinions: list[AnalystOpinion]) -> float:
    total_conf = sum(o.confidence for o in opinions if o.confidence > 0)
    if total_conf <= 0:
        return 0.0
    weighted = sum(
        _SIGN_BY_OPINION.get(o.opinion, 0) * o.confidence for o in opinions
    )
    return weighted / total_conf


@FAST_EVALUATOR_REGISTRY.register
class AIHedgeFundFastEvaluator(FastEvaluator):
    name = "ai_hedge_fund"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def evaluate(
        self, tickers: list[str], ctx: StepContext
    ) -> list[FastEvaluation]:
        if not tickers:
            ctx.logger.warning("AIHedgeFundFastEvaluator: empty tickers list")
            return []

        sub = self.cfg or ctx.cfg.get("fast_evaluation", {}).get("ai_hedge_fund", {})
        _inject_api_keys(ctx.cfg)

        start_date, end_date = _resolve_dates(
            sub.get("start_date", ""), sub.get("end_date", "")
        )
        portfolio = {
            "cash": float(sub.get("initial_cash", 100000.0)),
            "margin_requirement": float(sub.get("margin_requirement", 0.0)),
            "positions": {
                t: {"long": 0, "short": 0, "long_cost_basis": 0.0, "short_cost_basis": 0.0}
                for t in tickers
            },
            "realized_gains": {
                t: {"long": 0.0, "short": 0.0} for t in tickers
            },
        }
        result = _call_run_hedge_fund(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            portfolio=portfolio,
            show_reasoning=sub.get("show_reasoning", False),
            selected_analysts=sub.get("selected_analysts", []),
            model_name=sub.get("model_name", "deepseek-v4-pro"),
            model_provider=sub.get("model_provider", "DeepSeek"),
        )

        analyst_signals = (result or {}).get("analyst_signals", {})
        per_ticker_evals: list[FastEvaluation] = []
        for ticker in tickers:
            opinions: list[AnalystOpinion] = []
            for analyst_name, by_ticker in analyst_signals.items():
                sig = by_ticker.get(ticker) if isinstance(by_ticker, dict) else None
                if not sig:
                    continue
                opinion = str(sig.get("signal", "neutral")).lower()
                confidence = float(sig.get("confidence", 0.0))
                reasoning = str(sig.get("reasoning", ""))
                opinions.append(
                    AnalystOpinion(
                        analyst_name=analyst_name,
                        opinion=opinion,
                        confidence=confidence,
                        reasoning=reasoning,
                    )
                )
            per_ticker_evals.append(
                FastEvaluation(
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                    opinions=opinions,
                    consensus_score=_compute_consensus(opinions),
                )
            )
        return per_ticker_evals
```

- [ ] **Step 5: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_backends.py -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/pipeline/backends/fast_evaluators.py tests/test_pipeline_backends.py
git commit -m "feat(pipeline): AIHedgeFundFastEvaluator wrapping run_hedge_fund

Maps bullish/bearish/neutral signals to AnalystOpinion records, computes
confidence-weighted consensus score in [-1, +1], handles date defaulting
and API key injection."
```

---

## Task 10 — `DeepEvaluator` ABC + `TradingAgentsDeepEvaluator`

**Goal:** Define the abstract `DeepEvaluator`, `DeepEvaluation` dataclass, and `DEEP_EVALUATOR_REGISTRY`. Implement `TradingAgentsDeepEvaluator` wrapping `TradingAgentsGraph`.

**Files:**
- Create: `src/pipeline/backends/deep_evaluators.py`
- Modify: `tests/test_pipeline_backends.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline_backends.py`:
```python
def test_deep_evaluator_is_abstract():
    from pipeline.backends.deep_evaluators import DeepEvaluator
    with pytest.raises(TypeError):
        DeepEvaluator()  # type: ignore[abstract]


def test_deep_evaluation_dataclass():
    from pipeline.backends.deep_evaluators import DeepEvaluation
    de = DeepEvaluation(
        ticker="NVDA",
        evaluation_date="2026-05-17",
        agent_outputs={"market_report": "x"},
        extra_outputs={"foo": 1},
        final_decision="BUY",
    )
    assert de.agent_outputs["market_report"] == "x"
    assert de.extra_outputs["foo"] == 1


def test_trading_agents_evaluator_maps_final_state(monkeypatch, tmp_path):
    from pipeline.backends import deep_evaluators as de_mod

    fake_final_state = {
        "market_report": "trends up",
        "sentiment_report": "buzz",
        "news_report": "press",
        "fundamentals_report": "PE ok",
        "investment_plan": "long-term BUY",
        "trader_investment_plan": "Buy 100",
        "final_trade_decision": "BUY 100 shares of NVDA",
        # bull/bear/risk variants — adapt these field names to whatever
        # TradingAgentsGraph._run_graph actually emits.
        "bull_argument": "bullish thesis",
        "bear_argument": "bearish thesis",
        "risk_debate_aggressive": "aggressive view",
        "risk_debate_conservative": "conservative view",
        "risk_debate_neutral": "neutral view",
    }

    class FakeGraph:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def propagate(self, company_name, trade_date):
            # propagate returns final_state, decision per existing _run_graph
            return fake_final_state, "BUY"

    captured = {"installs": 0}

    def fake_install_cache():
        captured["installs"] += 1

    monkeypatch.setattr(de_mod, "_install_news_cache", fake_install_cache)
    monkeypatch.setattr(de_mod, "_build_graph", lambda **kw: FakeGraph(**kw))

    evaluator = de_mod.TradingAgentsDeepEvaluator(
        cfg={
            "model_name": "deepseek-v4-pro",
            "use_news_cache": True,
            "selected_analysts": ["market", "social", "news", "fundamentals"],
            "evaluation_date": "2026-05-17",
        }
    )
    out = evaluator.evaluate(["NVDA"], make_ctx(tmp_path))
    assert len(out) == 1
    de = out[0]
    assert de.ticker == "NVDA"
    assert de.final_decision == "BUY"
    assert de.agent_outputs["market_report"] == "trends up"
    assert de.agent_outputs["bull_argument"] == "bullish thesis"
    assert de.agent_outputs["risk_aggressive"] == "aggressive view"
    assert captured["installs"] == 1


def test_trading_agents_registered_under_name():
    from pipeline.backends.deep_evaluators import (
        DEEP_EVALUATOR_REGISTRY,
        TradingAgentsDeepEvaluator,
    )
    assert DEEP_EVALUATOR_REGISTRY.get("trading_agents") is TradingAgentsDeepEvaluator


def test_use_news_cache_false_skips_install(monkeypatch, tmp_path):
    from pipeline.backends import deep_evaluators as de_mod

    class FakeGraph:
        def __init__(self, **kw): pass
        def propagate(self, c, d): return {}, "HOLD"

    captured = {"installs": 0}
    monkeypatch.setattr(
        de_mod, "_install_news_cache",
        lambda: captured.__setitem__("installs", captured["installs"] + 1),
    )
    monkeypatch.setattr(de_mod, "_build_graph", lambda **kw: FakeGraph())

    ev = de_mod.TradingAgentsDeepEvaluator(cfg={"use_news_cache": False})
    ev.evaluate(["NVDA"], make_ctx(tmp_path))
    assert captured["installs"] == 0
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/test_pipeline_backends.py -v`
Expected: ImportError on `deep_evaluators`.

- [ ] **Step 3: Implement**

Create `src/pipeline/backends/deep_evaluators.py`:
```python
"""DeepEvaluator ABC + DeepEvaluation + TradingAgentsDeepEvaluator + registry."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pipeline.backends.selectors import _Registry
from pipeline.base import StepContext

logger = logging.getLogger(__name__)


@dataclass
class DeepEvaluation:
    ticker: str
    evaluation_date: str
    agent_outputs: dict[str, str]
    extra_outputs: dict[str, Any] = field(default_factory=dict)
    final_decision: str = ""


DEEP_EVALUATOR_REGISTRY = _Registry("deep_evaluator")


class DeepEvaluator(ABC):
    name: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__abstractmethods__:
            return
        if not cls.name:
            raise TypeError(
                f"{cls.__name__} must define a non-empty `name` class attribute"
            )

    @abstractmethod
    def evaluate(self, tickers: list[str], ctx: StepContext) -> list[DeepEvaluation]: ...


# --- Concrete backend: TradingAgentsDeepEvaluator ----------------------------

# Map TradingAgents final_state keys to the named slots used by
# fast_evaluation_conclusion / deep_evaluation tables. Fields without a
# named slot land in extras.
_FINAL_STATE_TO_SLOT = {
    "market_report": "market_report",
    "sentiment_report": "social_report",  # ta uses "sentiment"; we standardize on "social"
    "news_report": "news_report",
    "fundamentals_report": "fundamentals_report",
    "bull_argument": "bull_argument",
    "bear_argument": "bear_argument",
    "investment_plan": "research_manager_decision",
    "trader_investment_plan": "trader_plan",
    "risk_debate_aggressive": "risk_aggressive",
    "risk_debate_conservative": "risk_conservative",
    "risk_debate_neutral": "risk_neutral",
    "final_trade_decision": "risk_manager_decision",
}

_NAMED_SLOTS = set(_FINAL_STATE_TO_SLOT.values())


def _install_news_cache() -> None:
    """Indirection seam — tests monkeypatch this."""
    from news_cache import install  # AIStock module
    install()


def _build_graph(**kwargs):
    """Indirection seam — tests monkeypatch this."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    return TradingAgentsGraph(**kwargs)


def _extract_decision(final_state: dict, fallback_decision: str | None) -> str:
    text = final_state.get("final_trade_decision", "") or ""
    upper = text.upper()
    for token in ("BUY", "SELL", "HOLD"):
        if token in upper:
            return token
    if fallback_decision:
        upper = fallback_decision.upper()
        for token in ("BUY", "SELL", "HOLD"):
            if token in upper:
                return token
    return ""


@DEEP_EVALUATOR_REGISTRY.register
class TradingAgentsDeepEvaluator(DeepEvaluator):
    name = "trading_agents"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def evaluate(
        self, tickers: list[str], ctx: StepContext
    ) -> list[DeepEvaluation]:
        if not tickers:
            ctx.logger.warning("TradingAgentsDeepEvaluator: empty tickers list")
            return []

        sub = self.cfg or ctx.cfg.get("deep_evaluation", {}).get("trading_agents", {})

        if sub.get("use_news_cache", True):
            try:
                _install_news_cache()
            except Exception as e:
                ctx.logger.warning("news_cache install failed: %s", e)

        eval_date = sub.get("evaluation_date") or datetime.now().strftime("%Y-%m-%d")
        analysts = sub.get("selected_analysts") or [
            "market", "social", "news", "fundamentals"
        ]

        # TradingAgents config: build from sub-cfg.
        ta_cfg: dict[str, Any] = {
            "llm_provider": sub.get("model_provider", "deepseek"),
            "deep_think_llm": sub.get("model_name", "deepseek-v4-pro"),
            "quick_think_llm": (
                sub.get("quick_model")
                if not sub.get("quick", False)
                else sub.get("model_name", "deepseek-v4-pro")
            ),
            "data_cache_dir": sub.get("data_cache_dir", "data/tradingagents_cache"),
            "results_dir": sub.get("results_dir", "reports/tradingagents"),
            "max_debate_rounds": sub.get("max_debate_rounds", 1),
            "max_risk_discuss_rounds": sub.get("max_risk_discuss_rounds", 1),
            "checkpoint_enabled": sub.get("checkpoint_enabled", False),
        }
        # Drop None entries so TradingAgents uses its own DEFAULT_CONFIG values.
        ta_cfg = {k: v for k, v in ta_cfg.items() if v is not None}

        graph = _build_graph(
            selected_analysts=analysts,
            debug=sub.get("debug", False),
            config=ta_cfg,
        )

        out: list[DeepEvaluation] = []
        for ticker in tickers:
            ctx.logger.info("TradingAgents evaluating %s on %s", ticker, eval_date)
            try:
                result = graph.propagate(ticker, eval_date)
            except Exception as e:
                ctx.logger.exception("TradingAgents failed for %s: %s", ticker, e)
                continue

            # propagate may return (final_state, decision) tuple or just final_state.
            if isinstance(result, tuple) and len(result) == 2:
                final_state, decision = result
            else:
                final_state, decision = result, None
            final_state = final_state or {}

            agent_outputs: dict[str, str] = {}
            extras: dict[str, Any] = {}
            for src_key, value in final_state.items():
                slot = _FINAL_STATE_TO_SLOT.get(src_key)
                if slot:
                    agent_outputs[slot] = value if isinstance(value, str) else str(value)
                else:
                    if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
                        extras[src_key] = value

            out.append(
                DeepEvaluation(
                    ticker=ticker,
                    evaluation_date=eval_date,
                    agent_outputs=agent_outputs,
                    extra_outputs=extras,
                    final_decision=_extract_decision(final_state, decision),
                )
            )
        return out
```

(Note: TradingAgents' actual final_state key names for bull/bear/risk debate variants may differ. The implementer should verify against `tradingagents/graph/trading_graph.py:_run_graph` and `signal_processor.py`, then adjust `_FINAL_STATE_TO_SLOT`. The test in Step 1 uses placeholder names; align test fixture + mapping during impl.)

- [ ] **Step 4: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_backends.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/backends/deep_evaluators.py tests/test_pipeline_backends.py
git commit -m "feat(pipeline): TradingAgentsDeepEvaluator wrapping TradingAgentsGraph

Maps final_state keys to named DeepEvaluation slots; falls back to
extra_outputs for backend-specific fields. Optional news_cache install
guarded by use_news_cache config flag."
```

---

## Task 11 — `DataUpdateStep`

**Goal:** Wire step 1 — invoke existing `src.ingestion.pipeline.run_daily_pipeline` against active stocks, build a `StepResult`.

**Files:**
- Create: `src/pipeline/data_update.py`
- Create: `tests/test_pipeline_data_update.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_data_update.py`:
```python
"""DataUpdateStep tests."""
import logging
from unittest.mock import MagicMock

import pytest

from pipeline.base import StepContext
from pipeline.data_update import DataUpdateStep


def make_ctx(tmp_path, cfg=None):
    return StepContext(
        cfg=cfg or {},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )


def test_data_update_success(monkeypatch, tmp_path):
    fake_result = {
        "symbols_attempted": 3,
        "symbols_succeeded": 3,
        "symbols_failed": 0,
        "failed_symbols": [],
    }

    monkeypatch.setattr(
        "pipeline.data_update._run_pipeline",
        lambda source, parallel_workers: fake_result,
    )

    step = DataUpdateStep()
    ctx = make_ctx(
        tmp_path,
        cfg={"data_update": {"source": "alpha_vantage", "parallel_workers": 4}},
    )
    result = step.run(ctx)
    assert result.status == "success"
    assert result.summary["symbols_succeeded"] == 3
    assert result.summary["source"] == "alpha_vantage"


def test_data_update_failure_returns_failed_status(monkeypatch, tmp_path):
    def raiser(*a, **k):
        raise RuntimeError("DB down")

    monkeypatch.setattr("pipeline.data_update._run_pipeline", raiser)

    step = DataUpdateStep()
    ctx = make_ctx(tmp_path, cfg={"data_update": {"source": "yahoo"}})
    result = step.run(ctx)
    assert result.status == "failed"
    assert "DB down" in result.error


def test_data_update_partial_failure_still_success(monkeypatch, tmp_path):
    fake_result = {
        "symbols_attempted": 5,
        "symbols_succeeded": 4,
        "symbols_failed": 1,
        "failed_symbols": ["XYZ"],
    }
    monkeypatch.setattr(
        "pipeline.data_update._run_pipeline",
        lambda source, parallel_workers: fake_result,
    )

    step = DataUpdateStep()
    ctx = make_ctx(tmp_path, cfg={"data_update": {"source": "alpha_vantage"}})
    result = step.run(ctx)
    assert result.status == "success"
    assert result.summary["symbols_failed"] == 1


def test_data_update_all_failed_returns_failed(monkeypatch, tmp_path):
    fake_result = {
        "symbols_attempted": 3,
        "symbols_succeeded": 0,
        "symbols_failed": 3,
        "failed_symbols": ["A", "B", "C"],
    }
    monkeypatch.setattr(
        "pipeline.data_update._run_pipeline",
        lambda source, parallel_workers: fake_result,
    )

    step = DataUpdateStep()
    ctx = make_ctx(tmp_path, cfg={"data_update": {"source": "alpha_vantage"}})
    result = step.run(ctx)
    assert result.status == "failed"
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/test_pipeline_data_update.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/pipeline/data_update.py`:
```python
"""DataUpdateStep — refreshes price/indicator/fundamental data."""
from __future__ import annotations

import time
import traceback

from pipeline.base import PipelineStep, StepContext, StepResult


def _run_pipeline(source: str, parallel_workers: int) -> dict:
    """Indirection seam — tests monkeypatch this."""
    from fetcher import build_fetcher  # AIStock module
    from ingestion.pipeline import run_daily_pipeline

    fetcher = build_fetcher(source)
    result = run_daily_pipeline(fetcher)
    # Normalize to expected shape regardless of run_daily_pipeline's output.
    return {
        "symbols_attempted": result.get("symbols_attempted", 0),
        "symbols_succeeded": result.get("symbols_succeeded", 0),
        "symbols_failed": result.get("symbols_failed", 0),
        "failed_symbols": result.get("failed_symbols", []),
    }


class DataUpdateStep(PipelineStep):
    name = "data_update"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)
        source = sub.get("source", "alpha_vantage")
        workers = int(sub.get("parallel_workers", 4))
        start = time.monotonic()

        try:
            stats = _run_pipeline(source, workers)
        except Exception as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"source": source},
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            )

        duration = time.monotonic() - start
        attempted = stats["symbols_attempted"]
        failed = stats["symbols_failed"]
        succeeded = stats["symbols_succeeded"]
        status = "failed" if (attempted > 0 and succeeded == 0) else "success"

        summary = {
            "source": source,
            "symbols_attempted": attempted,
            "symbols_succeeded": succeeded,
            "symbols_failed": failed,
            "failed_symbols": stats["failed_symbols"],
            "duration_s": round(duration, 2),
        }
        return StepResult(
            step_name=self.name,
            status=status,
            summary=summary,
        )
```

The `fetcher.build_fetcher(source)` helper is assumed to exist; if it doesn't, add it to `src/fetcher/__init__.py` (a small factory selecting AlphaVantage vs Yahoo via the existing `AlphaVantageFetcher` / `YahooFetcher` classes). If missing, implement it as part of this task with one extra small test.

- [ ] **Step 4: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_data_update.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/data_update.py tests/test_pipeline_data_update.py
git commit -m "feat(pipeline): DataUpdateStep wrapping ingestion.run_daily_pipeline"
```

---

## Task 12 — `StockSelectionStep`

**Goal:** Step 2 — picks `StockSelector` backend via `stock_selection.backend`, runs it, writes results to `selected_stocks` with `pipeline_run_id`, `ml_score`, `sector`, `backend`.

**Files:**
- Create: `src/pipeline/stock_selection.py`
- Create: `tests/test_pipeline_stock_selection.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline_stock_selection.py`:
```python
"""StockSelectionStep tests."""
import logging
import datetime as dt
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, SelectedStock, PipelineRun
from pipeline.backends.selectors import (
    ScoredTicker,
    SELECTOR_REGISTRY,
    StockSelector,
)
from pipeline.base import StepContext
from pipeline.stock_selection import StockSelectionStep


@pytest.fixture
def engine_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        run = PipelineRun(status="running")
        s.add(run)
        s.commit()
        run_id = run.id
    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session
    yield factory, run_id


@pytest.fixture
def fake_selector():
    class FakeSel(StockSelector):
        name = "fake_test_sel"
        def __init__(self, cfg=None):
            self.cfg = cfg or {}
        def select(self, ctx):
            return [
                ScoredTicker(ticker="AAPL", ml_score=0.9, sector="Tech"),
                ScoredTicker(ticker="MSFT", ml_score=0.8, sector="Tech"),
            ]
    SELECTOR_REGISTRY.register(FakeSel)
    yield "fake_test_sel"
    SELECTOR_REGISTRY.unregister("fake_test_sel")


def make_ctx(engine_session_factory, run_id, tmp_path, backend_name):
    return StepContext(
        cfg={
            "stock_selection": {
                "backend": backend_name,
                backend_name: {},
            }
        },
        run_id=run_id,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: engine_session_factory().__enter__(),
    )


def test_stock_selection_writes_to_db(engine_session, fake_selector, tmp_path):
    factory, run_id = engine_session
    ctx = make_ctx(factory, run_id, tmp_path, fake_selector)

    step = StockSelectionStep()
    result = step.run(ctx)

    assert result.status == "success"
    assert len(result.payload["tickers_ranked"]) == 2
    assert result.payload["backend"] == fake_selector

    with factory() as s:
        rows = (
            s.query(SelectedStock)
            .filter(SelectedStock.pipeline_run_id == run_id)
            .order_by(SelectedStock.ml_score.desc())
            .all()
        )
        assert [r.ticker for r in rows] == ["AAPL", "MSFT"]
        assert rows[0].backend == fake_selector
        assert rows[0].sector == "Tech"


def test_stock_selection_unknown_backend_fails(engine_session, tmp_path):
    factory, run_id = engine_session
    ctx = StepContext(
        cfg={"stock_selection": {"backend": "does_not_exist"}},
        run_id=run_id,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: factory().__enter__(),
    )
    step = StockSelectionStep()
    result = step.run(ctx)
    assert result.status == "failed"
    assert "does_not_exist" in result.error


def test_stock_selection_empty_output_is_success(
    engine_session, tmp_path
):
    factory, run_id = engine_session

    class EmptySel(StockSelector):
        name = "empty_sel"
        def __init__(self, cfg=None): pass
        def select(self, ctx): return []
    SELECTOR_REGISTRY.register(EmptySel)
    try:
        ctx = make_ctx(factory, run_id, tmp_path, "empty_sel")
        result = StockSelectionStep().run(ctx)
        assert result.status == "success"
        assert result.payload["tickers_ranked"] == []
        assert "empty" in result.summary.get("note", "").lower()
    finally:
        SELECTOR_REGISTRY.unregister("empty_sel")
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/test_pipeline_stock_selection.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/pipeline/stock_selection.py`:
```python
"""StockSelectionStep — step 2 of the pipeline."""
from __future__ import annotations

import datetime as dt
import traceback
from contextlib import contextmanager

from models import SelectedStock
from pipeline.backends.selectors import SELECTOR_REGISTRY, ScoredTicker
from pipeline.base import PipelineStep, StepContext, StepResult


@contextmanager
def _open_session(ctx: StepContext):
    """Wrap session_factory; tolerate both context-manager and plain factories."""
    s = ctx.session_factory()
    if hasattr(s, "__enter__"):
        with s as session:
            yield session
    else:
        try:
            yield s
        finally:
            s.close()


class StockSelectionStep(PipelineStep):
    name = "stock_selection"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)
        backend_name = sub.get("backend", "finrl")
        try:
            selector_cls = SELECTOR_REGISTRY.get(backend_name)
        except KeyError as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=str(e),
            )

        selector_cfg = sub.get(backend_name, {})
        try:
            selector = selector_cls(cfg=selector_cfg)
            tickers = selector.select(ctx)
        except Exception as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            )

        # Persist
        now = dt.datetime.utcnow()
        with _open_session(ctx) as session:
            for t in tickers:
                row = SelectedStock(
                    ticker=t.ticker,
                    model_name=backend_name,
                    ml_score=t.ml_score,
                    bucket=None,
                    weight=None,
                    date_selected=now.date(),
                    pipeline_run_at=now,
                    pipeline_run_id=ctx.run_id,
                    sector=t.sector,
                    backend=backend_name,
                )
                session.add(row)
            session.commit()

        ranked = [
            {"ticker": t.ticker, "ml_score": t.ml_score, "sector": t.sector}
            for t in tickers
        ]
        summary = {
            "backend": backend_name,
            "count": len(tickers),
        }
        if not tickers:
            summary["note"] = "empty selection — downstream steps will short-circuit"

        return StepResult(
            step_name=self.name,
            status="success",
            summary=summary,
            payload={"backend": backend_name, "tickers_ranked": ranked},
        )
```

- [ ] **Step 4: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_stock_selection.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/stock_selection.py tests/test_pipeline_stock_selection.py
git commit -m "feat(pipeline): StockSelectionStep with backend registry dispatch"
```

---

## Task 13 — `FastEvaluationStep`

**Goal:** Step 3 — read top N from `selected_stocks` by `ml_score`, invoke `FastEvaluator` backend, write rows to `fast_evaluation_conclusion` + `fast_evaluation_analysts`.

**Files:**
- Create: `src/pipeline/fast_evaluation.py`
- Create: `tests/test_pipeline_fast_evaluation.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline_fast_evaluation.py`:
```python
"""FastEvaluationStep tests."""
import logging
import datetime as dt
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import (
    Base,
    FastEvaluationAnalyst,
    FastEvaluationConclusion,
    PipelineRun,
    SelectedStock,
)
from pipeline.backends.fast_evaluators import (
    AnalystOpinion,
    FAST_EVALUATOR_REGISTRY,
    FastEvaluation,
    FastEvaluator,
)
from pipeline.base import StepContext
from pipeline.fast_evaluation import FastEvaluationStep


@pytest.fixture
def env(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        run = PipelineRun(status="running")
        s.add(run)
        s.commit()
        run_id = run.id
        for ticker, score in [("AAA", 0.9), ("BBB", 0.8), ("CCC", 0.7), ("DDD", 0.6)]:
            s.add(SelectedStock(
                ticker=ticker, model_name="finrl",
                ml_score=score, date_selected=dt.date.today(),
                pipeline_run_id=run_id, sector="X", backend="finrl",
            ))
        s.commit()

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    yield factory, run_id


@pytest.fixture
def fake_fe():
    class FakeFE(FastEvaluator):
        name = "fake_fe_step3_test"
        def __init__(self, cfg=None): self.cfg = cfg or {}
        def evaluate(self, tickers, ctx):
            return [
                FastEvaluation(
                    ticker=t,
                    start_date="2026-02-01",
                    end_date="2026-05-01",
                    opinions=[
                        AnalystOpinion("warren_buffett", "bullish", 80.0, "moat"),
                        AnalystOpinion("michael_burry", "bearish", 50.0, "valuation"),
                    ],
                    consensus_score=(80 - 50) / (80 + 50),
                )
                for t in tickers
            ]
    FAST_EVALUATOR_REGISTRY.register(FakeFE)
    yield "fake_fe_step3_test"
    FAST_EVALUATOR_REGISTRY.unregister("fake_fe_step3_test")


def make_ctx(factory, run_id, tmp_path, backend, top_n=2):
    return StepContext(
        cfg={
            "fast_evaluation": {
                "backend": backend,
                "top_n": top_n,
                backend: {},
            }
        },
        run_id=run_id,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: factory().__enter__(),
    )


def test_fast_eval_picks_top_n_by_ml_score(env, fake_fe, tmp_path):
    factory, run_id = env
    ctx = make_ctx(factory, run_id, tmp_path, fake_fe, top_n=2)
    result = FastEvaluationStep().run(ctx)
    assert result.status == "success"
    ranked = result.payload["tickers_ranked_by_consensus"]
    assert [r["ticker"] for r in ranked] == ["AAA", "BBB"]

    with factory() as s:
        conc = s.query(FastEvaluationConclusion).all()
        assert {c.ticker for c in conc} == {"AAA", "BBB"}
        assert conc[0].positive_count == 1
        assert conc[0].negative_count == 1
        assert conc[0].neutral_count == 0
        assert conc[0].total_count == 2

        analysts = s.query(FastEvaluationAnalyst).all()
        assert len(analysts) == 4  # 2 tickers x 2 analysts


def test_fast_eval_empty_upstream_returns_success(env, fake_fe, tmp_path):
    factory, run_id = env
    # Use a run_id with no selected_stocks
    with factory() as s:
        run = PipelineRun(status="running")
        s.add(run)
        s.commit()
        empty_run_id = run.id

    ctx = make_ctx(factory, empty_run_id, tmp_path, fake_fe, top_n=2)
    result = FastEvaluationStep().run(ctx)
    assert result.status == "success"
    assert result.payload["tickers_ranked_by_consensus"] == []


def test_fast_eval_unknown_backend_fails(env, tmp_path):
    factory, run_id = env
    ctx = make_ctx(factory, run_id, tmp_path, "nope", top_n=2)
    result = FastEvaluationStep().run(ctx)
    assert result.status == "failed"
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/test_pipeline_fast_evaluation.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/pipeline/fast_evaluation.py`:
```python
"""FastEvaluationStep — step 3 of the pipeline."""
from __future__ import annotations

import datetime as dt
import traceback
from contextlib import contextmanager

from sqlalchemy import desc

from models import (
    FastEvaluationAnalyst,
    FastEvaluationConclusion,
    SelectedStock,
)
from pipeline.backends.fast_evaluators import FAST_EVALUATOR_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult


@contextmanager
def _open_session(ctx: StepContext):
    s = ctx.session_factory()
    if hasattr(s, "__enter__"):
        with s as session:
            yield session
    else:
        try:
            yield s
        finally:
            s.close()


def _count_by_opinion(opinions):
    pos = sum(1 for o in opinions if o.opinion == "bullish")
    neg = sum(1 for o in opinions if o.opinion == "bearish")
    neu = sum(1 for o in opinions if o.opinion == "neutral")
    return pos, neg, neu


class FastEvaluationStep(PipelineStep):
    name = "fast_evaluation"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)
        backend_name = sub.get("backend", "ai_hedge_fund")
        top_n = int(sub.get("top_n", 10))

        try:
            evaluator_cls = FAST_EVALUATOR_REGISTRY.get(backend_name)
        except KeyError as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=str(e),
            )

        # Read top-N tickers for this run.
        with _open_session(ctx) as session:
            rows = (
                session.query(SelectedStock)
                .filter(SelectedStock.pipeline_run_id == ctx.run_id)
                .order_by(desc(SelectedStock.ml_score))
                .limit(top_n)
                .all()
            )
            tickers = [r.ticker for r in rows]

        if not tickers:
            return StepResult(
                step_name=self.name,
                status="success",
                summary={"backend": backend_name, "note": "no upstream tickers"},
                payload={"backend": backend_name, "tickers_ranked_by_consensus": []},
            )

        evaluator_cfg = sub.get(backend_name, {})
        try:
            evaluator = evaluator_cls(cfg=evaluator_cfg)
            evaluations = evaluator.evaluate(tickers, ctx)
        except Exception as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            )

        now = dt.datetime.utcnow()
        ranked: list[dict] = []
        with _open_session(ctx) as session:
            for ev in evaluations:
                pos, neg, neu = _count_by_opinion(ev.opinions)
                total = pos + neg + neu
                session.add(FastEvaluationConclusion(
                    pipeline_run_id=ctx.run_id,
                    ticker=ev.ticker,
                    backend=backend_name,
                    start_date=dt.date.fromisoformat(ev.start_date),
                    end_date=dt.date.fromisoformat(ev.end_date),
                    evaluation_date=now,
                    positive_count=pos,
                    negative_count=neg,
                    neutral_count=neu,
                    total_count=total,
                    consensus_score=ev.consensus_score,
                    model_name=evaluator_cfg.get("model_name"),
                    model_provider=evaluator_cfg.get("model_provider"),
                ))
                for op in ev.opinions:
                    session.add(FastEvaluationAnalyst(
                        pipeline_run_id=ctx.run_id,
                        ticker=ev.ticker,
                        backend=backend_name,
                        analyst_name=op.analyst_name,
                        opinion=op.opinion,
                        confidence=op.confidence,
                        reasoning=op.reasoning,
                        start_date=dt.date.fromisoformat(ev.start_date),
                        end_date=dt.date.fromisoformat(ev.end_date),
                        evaluation_date=now,
                    ))
            session.commit()

        evaluations_sorted = sorted(
            evaluations, key=lambda e: e.consensus_score, reverse=True
        )
        for ev in evaluations_sorted:
            pos, neg, neu = _count_by_opinion(ev.opinions)
            ranked.append({
                "ticker": ev.ticker,
                "consensus_score": ev.consensus_score,
                "positive": pos,
                "negative": neg,
                "neutral": neu,
            })

        return StepResult(
            step_name=self.name,
            status="success",
            summary={
                "backend": backend_name,
                "tickers_evaluated": len(evaluations),
            },
            payload={
                "backend": backend_name,
                "tickers_ranked_by_consensus": ranked,
            },
        )
```

- [ ] **Step 4: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_fast_evaluation.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/fast_evaluation.py tests/test_pipeline_fast_evaluation.py
git commit -m "feat(pipeline): FastEvaluationStep — top-N selection + DB writes"
```

---

## Task 14 — `DeepEvaluationStep`

**Goal:** Step 4 — read top N from `fast_evaluation_conclusion` by `consensus_score`, invoke `DeepEvaluator` backend, write to `deep_evaluation`.

**Files:**
- Create: `src/pipeline/deep_evaluation.py`
- Create: `tests/test_pipeline_deep_evaluation.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline_deep_evaluation.py`:
```python
"""DeepEvaluationStep tests."""
import logging
import datetime as dt
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import (
    Base,
    DeepEvaluationRow,
    FastEvaluationConclusion,
    PipelineRun,
)
from pipeline.backends.deep_evaluators import (
    DEEP_EVALUATOR_REGISTRY,
    DeepEvaluation,
    DeepEvaluator,
)
from pipeline.base import StepContext
from pipeline.deep_evaluation import DeepEvaluationStep


@pytest.fixture
def env(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        run = PipelineRun(status="running")
        s.add(run)
        s.commit()
        run_id = run.id
        for ticker, score in [("AAA", 0.9), ("BBB", 0.5), ("CCC", -0.2)]:
            s.add(FastEvaluationConclusion(
                pipeline_run_id=run_id,
                ticker=ticker,
                backend="ai_hedge_fund",
                start_date=dt.date(2026, 2, 1),
                end_date=dt.date(2026, 5, 1),
                evaluation_date=dt.datetime.utcnow(),
                positive_count=5, negative_count=1, neutral_count=1,
                total_count=7, consensus_score=score,
            ))
        s.commit()

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    yield factory, run_id


@pytest.fixture
def fake_de():
    class FakeDE(DeepEvaluator):
        name = "fake_de_step4_test"
        def __init__(self, cfg=None): self.cfg = cfg or {}
        def evaluate(self, tickers, ctx):
            return [
                DeepEvaluation(
                    ticker=t,
                    evaluation_date="2026-05-17",
                    agent_outputs={"market_report": f"{t} up", "bull_argument": "buy"},
                    extra_outputs={"misc": 1},
                    final_decision="BUY",
                )
                for t in tickers
            ]
    DEEP_EVALUATOR_REGISTRY.register(FakeDE)
    yield "fake_de_step4_test"
    DEEP_EVALUATOR_REGISTRY.unregister("fake_de_step4_test")


def make_ctx(factory, run_id, tmp_path, backend, top_n=2):
    return StepContext(
        cfg={
            "deep_evaluation": {
                "backend": backend,
                "top_n": top_n,
                backend: {},
            }
        },
        run_id=run_id,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: factory().__enter__(),
    )


def test_deep_eval_picks_top_n_by_consensus(env, fake_de, tmp_path):
    factory, run_id = env
    ctx = make_ctx(factory, run_id, tmp_path, fake_de, top_n=2)
    result = DeepEvaluationStep().run(ctx)
    assert result.status == "success"
    evals = result.payload["evaluations"]
    assert [e["ticker"] for e in evals] == ["AAA", "BBB"]

    with factory() as s:
        rows = s.query(DeepEvaluationRow).order_by(DeepEvaluationRow.ticker).all()
        assert {r.ticker for r in rows} == {"AAA", "BBB"}
        assert rows[0].market_report == "AAA up"
        assert rows[0].bull_argument == "buy"
        assert rows[0].extra_outputs == {"misc": 1}
        assert rows[0].final_decision == "BUY"


def test_deep_eval_empty_upstream_returns_success(env, fake_de, tmp_path):
    factory, run_id = env
    with factory() as s:
        run = PipelineRun(status="running")
        s.add(run)
        s.commit()
        empty_id = run.id

    ctx = make_ctx(factory, empty_id, tmp_path, fake_de, top_n=2)
    result = DeepEvaluationStep().run(ctx)
    assert result.status == "success"
    assert result.payload["evaluations"] == []


def test_deep_eval_unknown_backend_fails(env, tmp_path):
    factory, run_id = env
    ctx = make_ctx(factory, run_id, tmp_path, "nope", top_n=2)
    result = DeepEvaluationStep().run(ctx)
    assert result.status == "failed"
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/test_pipeline_deep_evaluation.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/pipeline/deep_evaluation.py`:
```python
"""DeepEvaluationStep — step 4 of the pipeline."""
from __future__ import annotations

import datetime as dt
import traceback
from contextlib import contextmanager

from sqlalchemy import desc

from models import DeepEvaluationRow, FastEvaluationConclusion
from pipeline.backends.deep_evaluators import DEEP_EVALUATOR_REGISTRY
from pipeline.base import PipelineStep, StepContext, StepResult


@contextmanager
def _open_session(ctx: StepContext):
    s = ctx.session_factory()
    if hasattr(s, "__enter__"):
        with s as session:
            yield session
    else:
        try:
            yield s
        finally:
            s.close()


_NAMED_SLOTS = (
    "market_report", "social_report", "news_report", "fundamentals_report",
    "bull_argument", "bear_argument",
    "research_manager_decision", "trader_plan",
    "risk_aggressive", "risk_conservative", "risk_neutral",
    "risk_manager_decision",
)


class DeepEvaluationStep(PipelineStep):
    name = "deep_evaluation"

    def run(self, ctx: StepContext) -> StepResult:
        sub = self.step_config(ctx)
        backend_name = sub.get("backend", "trading_agents")
        top_n = int(sub.get("top_n", 3))

        try:
            evaluator_cls = DEEP_EVALUATOR_REGISTRY.get(backend_name)
        except KeyError as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=str(e),
            )

        with _open_session(ctx) as session:
            rows = (
                session.query(FastEvaluationConclusion)
                .filter(FastEvaluationConclusion.pipeline_run_id == ctx.run_id)
                .order_by(desc(FastEvaluationConclusion.consensus_score))
                .limit(top_n)
                .all()
            )
            tickers = [r.ticker for r in rows]

        if not tickers:
            return StepResult(
                step_name=self.name,
                status="success",
                summary={"backend": backend_name, "note": "no upstream tickers"},
                payload={"backend": backend_name, "evaluations": []},
            )

        evaluator_cfg = sub.get(backend_name, {})
        try:
            evaluator = evaluator_cls(cfg=evaluator_cfg)
            evaluations = evaluator.evaluate(tickers, ctx)
        except Exception as e:
            return StepResult(
                step_name=self.name,
                status="failed",
                summary={"backend": backend_name},
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            )

        with _open_session(ctx) as session:
            for ev in evaluations:
                kwargs = {slot: ev.agent_outputs.get(slot) for slot in _NAMED_SLOTS}
                row = DeepEvaluationRow(
                    pipeline_run_id=ctx.run_id,
                    ticker=ev.ticker,
                    backend=backend_name,
                    evaluation_date=dt.datetime.fromisoformat(
                        ev.evaluation_date
                    ) if "T" in ev.evaluation_date else dt.datetime.strptime(
                        ev.evaluation_date, "%Y-%m-%d"
                    ),
                    extra_outputs=ev.extra_outputs,
                    final_decision=ev.final_decision,
                    model_name=evaluator_cfg.get("model_name"),
                    **kwargs,
                )
                session.add(row)
            session.commit()

        ev_list = [
            {"ticker": ev.ticker, "final_decision": ev.final_decision}
            for ev in evaluations
        ]
        return StepResult(
            step_name=self.name,
            status="success",
            summary={
                "backend": backend_name,
                "tickers_evaluated": len(evaluations),
            },
            payload={"backend": backend_name, "evaluations": ev_list},
        )
```

- [ ] **Step 4: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_deep_evaluation.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/deep_evaluation.py tests/test_pipeline_deep_evaluation.py
git commit -m "feat(pipeline): DeepEvaluationStep — top-N selection + DB writes"
```

---

## Task 15 — `FullPipeline` orchestrator

**Goal:** `FullPipeline` class that creates `pipeline_runs`, iterates steps, writes reports + `summary.{json,md}`, handles failure/resume.

**Files:**
- Create: `src/pipeline/orchestrator.py`
- Create: `tests/test_pipeline_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline_orchestrator.py`:
```python
"""Orchestrator tests with stub steps."""
import json
import logging
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, PipelineRun
from pipeline.base import PipelineError, PipelineStep, StepContext, StepResult
from pipeline.orchestrator import FullPipeline


@pytest.fixture
def engine_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    @contextmanager
    def f():
        with Session(engine) as s:
            yield s
    return engine, f


class _OkStep(PipelineStep):
    name = "ok_step"
    def run(self, ctx):
        return StepResult(step_name=self.name, status="success",
                          summary={"x": 1}, payload={"k": "v"})


class _FailStep(PipelineStep):
    name = "fail_step"
    def run(self, ctx):
        return StepResult(step_name=self.name, status="failed",
                          summary={}, error="boom")


class _RaiseStep(PipelineStep):
    name = "raise_step"
    def run(self, ctx):
        raise ValueError("kaboom")


def test_orchestrator_runs_all_steps(engine_factory, tmp_path):
    engine, factory = engine_factory
    pipeline = FullPipeline(
        steps=[_OkStep(), _OkStep()],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    pipeline.steps[1].name = "ok_step_2"
    run_id = pipeline.run()
    assert run_id is not None
    with factory() as s:
        run = s.query(PipelineRun).filter_by(id=run_id).one()
        assert run.status == "success"
    rep_dir = tmp_path / str(run_id)
    assert (rep_dir / "ok_step.json").exists()
    assert (rep_dir / "ok_step_2.json").exists()
    assert (rep_dir / "summary.json").exists()


def test_orchestrator_stops_on_failed_step(engine_factory, tmp_path):
    engine, factory = engine_factory
    after = _OkStep()
    after.name = "after_step"
    pipeline = FullPipeline(
        steps=[_OkStep(), _FailStep(), after],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    with pytest.raises(PipelineError):
        pipeline.run()
    with factory() as s:
        runs = s.query(PipelineRun).all()
        assert len(runs) == 1
        assert runs[0].status == "failed"
    rep_dir = tmp_path / str(runs[0].id)
    assert (rep_dir / "ok_step.json").exists()
    assert (rep_dir / "fail_step.json").exists()
    assert not (rep_dir / "after_step.json").exists()


def test_orchestrator_wraps_exception(engine_factory, tmp_path):
    engine, factory = engine_factory
    pipeline = FullPipeline(
        steps=[_RaiseStep()],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
    )
    with pytest.raises(PipelineError):
        pipeline.run()
    with factory() as s:
        run = s.query(PipelineRun).one()
        assert run.status == "failed"
    body = json.loads((tmp_path / str(run.id) / "raise_step.json").read_text())
    assert body["status"] == "failed"
    assert "kaboom" in body["error"]


def test_resume_from_loads_prior_results(engine_factory, tmp_path):
    engine, factory = engine_factory
    # Create initial failed run with step1 succeeded report on disk.
    with factory() as s:
        run = PipelineRun(status="failed")
        s.add(run)
        s.commit()
        run_id = run.id
    rep_dir = tmp_path / str(run_id)
    rep_dir.mkdir(parents=True)
    (rep_dir / "ok_step.json").write_text(json.dumps({
        "step_name": "ok_step", "status": "success",
        "summary": {"x": 1}, "payload": {"k": "v"}, "error": None,
    }))

    after = _OkStep()
    after.name = "after_step"
    pipeline = FullPipeline(
        steps=[_OkStep(), after],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
        resume_from="after_step",
        run_id=run_id,
    )
    pipeline.run()
    with factory() as s:
        run = s.query(PipelineRun).filter_by(id=run_id).one()
        assert run.status == "success"
    assert (rep_dir / "after_step.json").exists()
    # Prior result was loaded into context
    body = json.loads((rep_dir / "summary.json").read_text())
    assert "ok_step" in body["steps"]
    assert "after_step" in body["steps"]


def test_resume_rejects_already_successful(engine_factory, tmp_path):
    engine, factory = engine_factory
    with factory() as s:
        run = PipelineRun(status="success")
        s.add(run)
        s.commit()
        run_id = run.id

    pipeline = FullPipeline(
        steps=[_OkStep()],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
        resume_from="ok_step",
        run_id=run_id,
    )
    with pytest.raises(PipelineError, match="already.*success"):
        pipeline.run()


def test_resume_without_run_id_rejected(engine_factory, tmp_path):
    engine, factory = engine_factory
    with pytest.raises(ValueError, match="run_id is required"):
        FullPipeline(
            steps=[_OkStep()],
            cfg={},
            session_factory=lambda: factory().__enter__(),
            report_root=tmp_path,
            logger=logging.getLogger("test"),
            resume_from="ok_step",
            run_id=None,
        )


def test_only_runs_single_step(engine_factory, tmp_path):
    engine, factory = engine_factory
    s1 = _OkStep(); s1.name = "s1"
    s2 = _OkStep(); s2.name = "s2"
    pipeline = FullPipeline(
        steps=[s1, s2],
        cfg={},
        session_factory=lambda: factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("test"),
        only="s2",
    )
    run_id = pipeline.run()
    rep_dir = tmp_path / str(run_id)
    assert (rep_dir / "s2.json").exists()
    assert not (rep_dir / "s1.json").exists()
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/test_pipeline_orchestrator.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/pipeline/orchestrator.py`:
```python
"""FullPipeline orchestrator — owns pipeline_runs row + step iteration."""
from __future__ import annotations

import datetime as dt
import json
import logging
import traceback
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

from models import PipelineRun
from pipeline.base import (
    PipelineError,
    PipelineStep,
    StepContext,
    StepResult,
)


@contextmanager
def _open_session(factory):
    s = factory()
    if hasattr(s, "__enter__"):
        with s as session:
            yield session
    else:
        try:
            yield s
        finally:
            s.close()


def _serialize_result(r: StepResult) -> dict:
    return {
        "step_name": r.step_name,
        "status": r.status,
        "summary": r.summary,
        "payload": r.payload,
        "error": r.error,
    }


def _step_to_markdown(r: StepResult) -> str:
    lines = [
        f"# Step: {r.step_name}",
        f"",
        f"**Status:** {r.status}",
    ]
    if r.error:
        lines.append("")
        lines.append("## Error")
        lines.append("")
        lines.append("```")
        lines.append(r.error)
        lines.append("```")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(r.summary, indent=2, default=str))
    lines.append("```")
    if r.payload:
        lines.append("")
        lines.append("## Payload")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(r.payload, indent=2, default=str))
        lines.append("```")
    return "\n".join(lines)


class FullPipeline:
    def __init__(
        self,
        steps: list[PipelineStep],
        cfg: dict[str, Any],
        session_factory: Callable[[], Any],
        report_root: Path,
        logger: logging.Logger | None = None,
        resume_from: str | None = None,
        run_id: int | None = None,
        only: str | None = None,
    ):
        self.steps = steps
        self.cfg = cfg
        self.session_factory = session_factory
        self.report_root = Path(report_root)
        self.logger = logger or logging.getLogger(__name__)
        self.resume_from = resume_from
        self.only = only
        if resume_from and run_id is None:
            raise ValueError("run_id is required when resume_from is specified")
        self.run_id = run_id

    def run(self) -> int:
        run_id = self._init_run()
        report_dir = self.report_root / str(run_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        ctx = StepContext(
            cfg=self.cfg,
            run_id=run_id,
            report_dir=report_dir,
            logger=self.logger,
            session_factory=self.session_factory,
            prior_results=self._load_prior_results(report_dir),
        )

        steps_to_run = self._select_steps()
        for step in steps_to_run:
            self.logger.info("=== running step: %s ===", step.name)
            try:
                result = step.run(ctx)
            except Exception as e:
                tb = traceback.format_exc()
                result = StepResult(
                    step_name=step.name,
                    status="failed",
                    summary={},
                    error=f"{type(e).__name__}: {e}\n{tb}",
                )
            self._write_step_report(report_dir, result)
            ctx.prior_results[step.name] = result

            if result.status == "failed":
                self._mark_run(run_id, status="failed")
                self._write_summary(report_dir, ctx.prior_results, status="failed")
                raise PipelineError(
                    f"step {step.name!r} failed: {result.error}"
                )

        self._mark_run(run_id, status="success")
        self._write_summary(report_dir, ctx.prior_results, status="success")
        return run_id

    # --- run lifecycle helpers ----------------------------------------------

    def _init_run(self) -> int:
        if self.run_id is None:
            with _open_session(self.session_factory) as s:
                run = PipelineRun(status="running")
                s.add(run)
                s.commit()
                return run.id
        # Resume path: validate existing row.
        with _open_session(self.session_factory) as s:
            run = s.query(PipelineRun).filter_by(id=self.run_id).one()
            if run.status == "success":
                raise PipelineError(
                    f"pipeline_run {self.run_id} is already success; cannot resume"
                )
            run.status = "running"
            s.commit()
            return run.id

    def _mark_run(self, run_id: int, status: str) -> None:
        with _open_session(self.session_factory) as s:
            run = s.query(PipelineRun).filter_by(id=run_id).one()
            run.status = status
            run.finished_at = dt.datetime.utcnow()
            s.commit()

    def _select_steps(self) -> list[PipelineStep]:
        if self.only:
            return [s for s in self.steps if s.name == self.only]
        if self.resume_from:
            names = [s.name for s in self.steps]
            if self.resume_from not in names:
                raise ValueError(
                    f"resume_from={self.resume_from!r} not in steps {names}"
                )
            idx = names.index(self.resume_from)
            return self.steps[idx:]
        return list(self.steps)

    def _load_prior_results(self, report_dir: Path) -> dict[str, StepResult]:
        out: dict[str, StepResult] = {}
        for f in report_dir.glob("*.json"):
            if f.name == "summary.json":
                continue
            try:
                body = json.loads(f.read_text())
            except Exception:
                continue
            if "step_name" in body:
                out[body["step_name"]] = StepResult(
                    step_name=body["step_name"],
                    status=body["status"],
                    summary=body.get("summary", {}),
                    payload=body.get("payload", {}),
                    error=body.get("error"),
                )
        return out

    def _write_step_report(self, report_dir: Path, result: StepResult) -> None:
        (report_dir / f"{result.step_name}.json").write_text(
            json.dumps(_serialize_result(result), indent=2, default=str)
        )
        (report_dir / f"{result.step_name}.md").write_text(
            _step_to_markdown(result)
        )

    def _write_summary(
        self,
        report_dir: Path,
        results: dict[str, StepResult],
        status: str,
    ) -> None:
        steps_block = {
            name: {
                "status": r.status,
                "summary": r.summary,
                "error": r.error,
            }
            for name, r in results.items()
        }
        body = {
            "status": status,
            "finished_at": dt.datetime.utcnow().isoformat(),
            "steps": steps_block,
        }
        (report_dir / "summary.json").write_text(
            json.dumps(body, indent=2, default=str)
        )
        md = ["# Pipeline summary", "", f"**Overall:** {status}", ""]
        for name, r in results.items():
            md.append(f"- **{name}** — {r.status}")
            if r.error:
                md.append(f"    - error: {r.error.splitlines()[0]}")
        (report_dir / "summary.md").write_text("\n".join(md))
```

- [ ] **Step 4: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_pipeline_orchestrator.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/orchestrator.py tests/test_pipeline_orchestrator.py
git commit -m "feat(pipeline): FullPipeline orchestrator with resume + reports"
```

---

## Task 16 — CLI shim `src/full_pipeline.py`

**Goal:** Replace existing `src/full_pipeline.py` with a thin CLI that wires `ConfigLoader` + `FullPipeline`. Old function-style code removed.

**Files:**
- Modify: `src/full_pipeline.py` (full rewrite)
- Create: `tests/test_full_pipeline_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_full_pipeline_cli.py`:
```python
"""CLI argument parsing tests for full_pipeline."""
import sys
from pathlib import Path

import pytest

import full_pipeline as fp


def test_parse_args_minimal():
    args = fp.parse_args(["--config", "config.yaml"])
    assert args.config == "config.yaml"
    assert args.set_ == []
    assert args.resume_from is None
    assert args.run_id is None
    assert args.only is None


def test_parse_args_set_overrides():
    args = fp.parse_args([
        "--config", "config.yaml",
        "--set", "fast_evaluation.top_n=5",
        "--set", "deep_evaluation.trading_agents.quick=true",
    ])
    assert args.set_ == [
        "fast_evaluation.top_n=5",
        "deep_evaluation.trading_agents.quick=true",
    ]


def test_parse_args_resume_requires_run_id():
    # Argument-level validation is delegated to FullPipeline; CLI accepts both
    # forms but the orchestrator raises if run_id missing. CLI-level should
    # only enforce that --resume-from has a value, which argparse does.
    args = fp.parse_args(["--resume-from", "fast_evaluation", "--run-id", "42"])
    assert args.resume_from == "fast_evaluation"
    assert args.run_id == 42
```

- [ ] **Step 2: Run, expect failure**

Run: `PYTHONPATH=src pytest tests/test_full_pipeline_cli.py -v`
Expected: AttributeError / ImportError on `parse_args` (or old function-style code).

- [ ] **Step 3: Replace `src/full_pipeline.py`**

Overwrite `src/full_pipeline.py` with:

```python
"""CLI shim for the OOP pipeline.

Parses argv, builds a FullPipeline, runs it. Exits non-zero on failure.
All step logic lives in src/pipeline/.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Pre-import AIStock modules BEFORE any pipeline.backends import touches
# external/* paths — preserves the sys.path hazard discipline.
import config  # noqa: F401
import database  # noqa: F401
import models  # noqa: F401
import repository  # noqa: F401

from pipeline.base import PipelineError
from pipeline.config import ConfigLoader
from pipeline.data_update import DataUpdateStep
from pipeline.deep_evaluation import DeepEvaluationStep
from pipeline.fast_evaluation import FastEvaluationStep
from pipeline.orchestrator import FullPipeline
from pipeline.stock_selection import StockSelectionStep


STEPS_ORDER = [
    DataUpdateStep,
    StockSelectionStep,
    FastEvaluationStep,
    DeepEvaluationStep,
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AIStock OOP full pipeline")
    p.add_argument("--config", default="config.yaml")
    p.add_argument(
        "--set", dest="set_", action="append", default=[],
        help="Dotted-path override, KEY=VALUE; repeatable",
    )
    p.add_argument(
        "--resume-from", default=None,
        choices=[None, "data_update", "stock_selection",
                 "fast_evaluation", "deep_evaluation"],
    )
    p.add_argument("--run-id", type=int, default=None)
    p.add_argument(
        "--only", default=None,
        choices=[None, "data_update", "stock_selection",
                 "fast_evaluation", "deep_evaluation"],
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def _setup_logging(level: str) -> logging.Logger:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    return logging.getLogger("full_pipeline")


def _build_session_factory(cfg: dict):
    # Lazy import — database module already pre-imported above.
    from database import get_session  # type: ignore
    return get_session


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = _setup_logging(args.log_level)

    loader = ConfigLoader(args.config, overrides=args.set_)
    cfg = loader.load()

    report_root = Path("reports/full_pipeline")
    report_root.mkdir(parents=True, exist_ok=True)

    steps = [cls() for cls in STEPS_ORDER]
    pipeline = FullPipeline(
        steps=steps,
        cfg=cfg,
        session_factory=_build_session_factory(cfg),
        report_root=report_root,
        logger=logger,
        resume_from=args.resume_from,
        run_id=args.run_id,
        only=args.only,
    )

    if args.dry_run:
        logger.info("dry-run: would execute steps %s",
                    [s.name for s in pipeline._select_steps()])
        return 0

    try:
        run_id = pipeline.run()
        # Save effective config to the run's report directory now that the
        # run_id is known.
        loader.write_effective(
            Path("reports/full_pipeline") / str(run_id) / "effective_config.yaml"
        )
        logger.info("pipeline run %d completed successfully", run_id)
        return 0
    except PipelineError as e:
        logger.error("pipeline failed: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, expect pass**

Run: `PYTHONPATH=src pytest tests/test_full_pipeline_cli.py -v`
Expected: 3 passed.

- [ ] **Step 5: Manual smoke test — dry-run against real config**

Run via context-mode shell:
```shell
PYTHONPATH=src python src/full_pipeline.py --dry-run --log-level INFO 2>&1 | tail -20
echo "EXIT=$?"
```
Expected: prints "dry-run: would execute steps [...]" and exits 0. If config.yaml has old keys, also prints deprecation warnings.

- [ ] **Step 6: Commit**

```bash
git add src/full_pipeline.py tests/test_full_pipeline_cli.py
git commit -m "refactor(pipeline): full_pipeline.py becomes a thin CLI shim

Wires ConfigLoader + FullPipeline orchestrator. Old function-style
implementation deleted; all step logic now lives in src/pipeline/."
```

---

## Task 17 — End-to-end smoke test

**Goal:** Replace `tests/test_full_pipeline.py` with a black-box E2E that runs the orchestrator with all four steps wired to fakes. Asserts DB tables and reports are populated.

**Files:**
- Delete: `tests/test_full_pipeline.py` (old)
- Create: `tests/test_full_pipeline_e2e.py`

- [ ] **Step 1: Inspect existing `tests/test_full_pipeline.py` for any reusable fixtures**

Run via context-mode shell:
```shell
test -f tests/test_full_pipeline.py && head -50 tests/test_full_pipeline.py || echo "no existing file"
```

- [ ] **Step 2: Write the new E2E test**

Create `tests/test_full_pipeline_e2e.py`:
```python
"""End-to-end smoke test for the OOP pipeline with all backends faked.

Runs the orchestrator over data_update -> stock_selection ->
fast_evaluation -> deep_evaluation. Verifies DB rows and reports.
"""
import datetime as dt
import json
import logging
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import (
    Base,
    DeepEvaluationRow,
    FastEvaluationAnalyst,
    FastEvaluationConclusion,
    PipelineRun,
    SelectedStock,
)
from pipeline.backends.deep_evaluators import (
    DEEP_EVALUATOR_REGISTRY, DeepEvaluation, DeepEvaluator,
)
from pipeline.backends.fast_evaluators import (
    AnalystOpinion, FAST_EVALUATOR_REGISTRY, FastEvaluation, FastEvaluator,
)
from pipeline.backends.selectors import (
    SELECTOR_REGISTRY, ScoredTicker, StockSelector,
)
from pipeline.data_update import DataUpdateStep
from pipeline.deep_evaluation import DeepEvaluationStep
from pipeline.fast_evaluation import FastEvaluationStep
from pipeline.orchestrator import FullPipeline
from pipeline.stock_selection import StockSelectionStep


@pytest.fixture
def engine_factory():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    @contextmanager
    def f():
        with Session(e) as s:
            yield s
    return f


@pytest.fixture
def fake_backends():
    class FakeSel(StockSelector):
        name = "e2e_sel"
        def __init__(self, cfg=None): pass
        def select(self, ctx):
            return [
                ScoredTicker(ticker="AAA", ml_score=0.95, sector="Tech"),
                ScoredTicker(ticker="BBB", ml_score=0.85, sector="Tech"),
                ScoredTicker(ticker="CCC", ml_score=0.75, sector="Finance"),
                ScoredTicker(ticker="DDD", ml_score=0.55, sector="Energy"),
                ScoredTicker(ticker="EEE", ml_score=0.45, sector="Health"),
            ]

    class FakeFE(FastEvaluator):
        name = "e2e_fe"
        def __init__(self, cfg=None): pass
        def evaluate(self, tickers, ctx):
            return [
                FastEvaluation(
                    ticker=t,
                    start_date="2026-02-01",
                    end_date="2026-05-01",
                    opinions=[
                        AnalystOpinion("warren_buffett", "bullish", 80.0, "moat"),
                        AnalystOpinion("michael_burry", "bearish", 30.0, "valuation"),
                    ],
                    consensus_score=(80 - 30) / (80 + 30),
                )
                for t in tickers
            ]

    class FakeDE(DeepEvaluator):
        name = "e2e_de"
        def __init__(self, cfg=None): pass
        def evaluate(self, tickers, ctx):
            return [
                DeepEvaluation(
                    ticker=t,
                    evaluation_date="2026-05-17",
                    agent_outputs={
                        "market_report": f"{t} rising",
                        "bull_argument": "buy",
                        "research_manager_decision": "BUY",
                    },
                    extra_outputs={},
                    final_decision="BUY",
                )
                for t in tickers
            ]

    SELECTOR_REGISTRY.register(FakeSel)
    FAST_EVALUATOR_REGISTRY.register(FakeFE)
    DEEP_EVALUATOR_REGISTRY.register(FakeDE)
    yield
    SELECTOR_REGISTRY.unregister("e2e_sel")
    FAST_EVALUATOR_REGISTRY.unregister("e2e_fe")
    DEEP_EVALUATOR_REGISTRY.unregister("e2e_de")


def test_full_pipeline_e2e(monkeypatch, engine_factory, fake_backends, tmp_path):
    # Stub DataUpdateStep so it doesn't try to hit external APIs.
    monkeypatch.setattr(
        "pipeline.data_update._run_pipeline",
        lambda source, parallel_workers: {
            "symbols_attempted": 5,
            "symbols_succeeded": 5,
            "symbols_failed": 0,
            "failed_symbols": [],
        },
    )

    cfg = {
        "data_update": {"source": "alpha_vantage", "parallel_workers": 1},
        "stock_selection": {"backend": "e2e_sel", "e2e_sel": {}},
        "fast_evaluation": {"backend": "e2e_fe", "top_n": 3, "e2e_fe": {}},
        "deep_evaluation": {"backend": "e2e_de", "top_n": 2, "e2e_de": {}},
    }

    pipeline = FullPipeline(
        steps=[
            DataUpdateStep(),
            StockSelectionStep(),
            FastEvaluationStep(),
            DeepEvaluationStep(),
        ],
        cfg=cfg,
        session_factory=lambda: engine_factory().__enter__(),
        report_root=tmp_path,
        logger=logging.getLogger("e2e"),
    )
    run_id = pipeline.run()

    # Reports written
    rd = tmp_path / str(run_id)
    for name in ("data_update", "stock_selection", "fast_evaluation",
                 "deep_evaluation", "summary"):
        assert (rd / f"{name}.json").exists(), name

    # DB state
    with engine_factory() as s:
        run = s.query(PipelineRun).filter_by(id=run_id).one()
        assert run.status == "success"
        # All selected
        assert s.query(SelectedStock).count() == 5
        # Top 3 in fast_evaluation
        assert s.query(FastEvaluationConclusion).count() == 3
        # Top 3 x 2 analysts in fast_evaluation_analysts
        assert s.query(FastEvaluationAnalyst).count() == 6
        # Top 2 in deep_evaluation
        assert s.query(DeepEvaluationRow).count() == 2
        # Top-N order: AAA, BBB picked first; consensus tie → orchestrator
        # keeps insertion order which is by selected_stocks ml_score.
        deep_tickers = {r.ticker for r in s.query(DeepEvaluationRow).all()}
        assert "AAA" in deep_tickers
        assert "BBB" in deep_tickers
```

- [ ] **Step 3: Delete the old test file**

Run: `rm tests/test_full_pipeline.py`
(Only if it exists per the inspection in Step 1.)

- [ ] **Step 4: Run new E2E test, expect pass**

Run: `PYTHONPATH=src pytest tests/test_full_pipeline_e2e.py -v`
Expected: 1 passed.

- [ ] **Step 5: Full test suite green check**

Run: `PYTHONPATH=src pytest tests/ -v -x --ignore=tests/test_full_pipeline.py`
Expected: all pipeline tests passing. (Other suites — smoke labels, dashboard E2E — should remain untouched and either green or skipped.)

- [ ] **Step 6: Commit**

```bash
git add tests/test_full_pipeline_e2e.py
git rm -f tests/test_full_pipeline.py
git commit -m "test(pipeline): rewrite full pipeline E2E with fake backends

Replaces test_full_pipeline.py. Stubs DataUpdate's external API call,
registers fake selector/evaluators, asserts DB rows and reports."
```

---

## Task 18 — Update CLAUDE.md

**Goal:** Reflect the new module layout, backend pattern, and DB tables in the project README for future agents.

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Locate the relevant sections to update**

Open `CLAUDE.md`. Sections to revise:
- "Architecture → Full Pipeline (`src/full_pipeline.py`)" — replace function-style description with new OOP package
- "AIStock Subsystem (`src/`)" — add `src/pipeline/` and `src/migrations/` lines
- "Database Schema" — add `fast_evaluation_conclusion`, `fast_evaluation_analysts`, `deep_evaluation`, `schema_migrations` to relevant subsections; update `selected_stocks` with new columns
- "Commands" — update the full pipeline invocation to mention `--set` overrides and the new `--resume-from` step names

- [ ] **Step 2: Apply the edits**

Use Edit to replace the "Full Pipeline (`src/full_pipeline.py`)" section's body with:

```markdown
### Full Pipeline (`src/pipeline/` + `src/full_pipeline.py`)

OOP orchestrator with pluggable backends. `src/full_pipeline.py` is a thin CLI shim; all step logic lives in `src/pipeline/`.

| Step name | Class | Backend ABC | Default backend |
|---|---|---|---|
| `data_update` | `DataUpdateStep` | (no backend swap) | reuses `src/ingestion/pipeline.py` |
| `stock_selection` | `StockSelectionStep` | `StockSelector` | `FinrlStockSelector` (wraps FinRL-Trading) |
| `fast_evaluation` | `FastEvaluationStep` | `FastEvaluator` | `AIHedgeFundFastEvaluator` (wraps `external/ai-hedge-fund` in-process) |
| `deep_evaluation` | `DeepEvaluationStep` | `DeepEvaluator` | `TradingAgentsDeepEvaluator` (wraps `TradingAgentsGraph`) |

Each step writes a `<step_name>.{json,md}` report to `reports/full_pipeline/<run_id>/`. All steps share a single `pipeline_run_id` (the `pipeline_runs.id`). The orchestrator stops on the first failed step; rerun with `--resume-from <step> --run-id <N>`.

Config lives under per-step namespaces in `config.yaml`. Override at CLI with `--set key.path=value` (repeatable, YAML-typed values). Backwards-compat mapping keeps existing `finrl_pipeline` / `ai_hedge_fund` top-level keys working with a deprecation warning.

Backends are selected by `<step>.backend: "<registered_name>"`. To add a new backend: subclass the relevant ABC in `src/pipeline/backends/*.py`, set its `name` class attribute, decorate with `@REGISTRY.register`. No orchestrator changes needed.
```

Update the `src/` listing block to include:
```
pipeline/             OOP pipeline package
  ├── base.py           PipelineStep ABC + StepResult + StepContext
  ├── config.py         ConfigLoader (yaml + dotted-path overrides)
  ├── orchestrator.py   FullPipeline
  ├── data_update.py    DataUpdateStep (step 1)
  ├── stock_selection.py     StockSelectionStep (step 2)
  ├── fast_evaluation.py     FastEvaluationStep (step 3)
  ├── deep_evaluation.py     DeepEvaluationStep (step 4)
  └── backends/         pluggable selector/evaluator implementations
migrations/           idempotent SQL migration runner + .sql files
```

Update the Commands section's full pipeline entry to:
```bash
# Full 4-step OOP pipeline
PYTHONPATH=src python src/full_pipeline.py
PYTHONPATH=src python src/full_pipeline.py --resume-from fast_evaluation --run-id 42
PYTHONPATH=src python src/full_pipeline.py --set fast_evaluation.top_n=5
```

Add database schema entries under appropriate sections:

- Under "Pipeline & scheduling":
```markdown
- **fast_evaluation_conclusion**: `(pipeline_run_id, ticker)` unique — counts of positive/negative/neutral analysts plus `consensus_score` in [-1, +1]. Indexed for top-N queries.
- **fast_evaluation_analysts**: `(pipeline_run_id, ticker, analyst_name)` unique — one row per analyst opinion with `confidence` and `reasoning`.
- **deep_evaluation**: `(pipeline_run_id, ticker)` unique — wide row of per-agent text fields (market_report, bull_argument, etc) plus `extra_outputs` JSON column for backend-specific data; `final_decision` ∈ {BUY, SELL, HOLD}.
- **schema_migrations**: `version` PK — tracks applied raw-SQL migrations for idempotency.
```

- Under "selected_stocks" description: add a note that the table now has `pipeline_run_id`, `sector`, `backend` columns and a `(pipeline_run_id, ml_score)` index added by migration `2026_05_17_pipeline_oop.sql`.

- [ ] **Step 3: Verify CLAUDE.md still parses cleanly**

Run via context-mode shell:
```shell
grep -nE '^## |^### |^#### ' CLAUDE.md | head -40
echo "lines: $(wc -l < CLAUDE.md)"
```
Expected: section headings still ordered correctly, no broken structure.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for OOP pipeline + pluggable backends"
```

---

## Task 19 — Final integration check

**Goal:** Sanity-check the end-to-end pipeline against real config with a dry-run, then a `--only data_update` smoke against MySQL.

**Files:** none (verification only)

- [ ] **Step 1: Dry-run full pipeline**

Run via context-mode shell:
```shell
PYTHONPATH=src python src/full_pipeline.py --dry-run --log-level INFO 2>&1 | tail -20
echo "EXIT=$?"
```
Expected: lists 4 step names in order, exits 0.

- [ ] **Step 2: Apply migration to MySQL**

Run via context-mode shell:
```shell
PYTHONPATH=src python -c "
import config
from database import engine
from models import Base
from migrations.run import MigrationRunner
Base.metadata.create_all(engine)
runner = MigrationRunner(engine, 'src/migrations')
applied = runner.run_pending()
print('applied:', applied)
"
```
Expected: `applied: ['2026_05_17_pipeline_oop']` on first run, `applied: []` on second run.

- [ ] **Step 3: Run `--only data_update` against MySQL**

Run via context-mode shell:
```shell
PYTHONPATH=src python src/full_pipeline.py --only data_update --log-level INFO 2>&1 | tail -30
echo "EXIT=$?"
```
Expected: exit 0, `reports/full_pipeline/<run_id>/data_update.json` exists, `pipeline_runs` row with status=success.

- [ ] **Step 4: Inspect produced run**

Run via context-mode shell:
```shell
PYTHONPATH=src python -c "
from database import get_session
from models import PipelineRun
with get_session() as s:
    run = s.query(PipelineRun).order_by(PipelineRun.id.desc()).first()
    print(f'run_id={run.id} status={run.status} started={run.started_at} finished={run.finished_at}')
"
ls -la reports/full_pipeline/ | tail -5
```
Expected: latest run's status is `success` and report directory has step JSON/MD.

- [ ] **Step 5: Commit (only if any tweaks were needed)**

If verification surfaced bugs, fix them in their respective files with new tasks. If the run is clean, no commit needed for Task 19; just close out the implementation.

---

## Self-Review

**Spec coverage check (each section mapped to a task):**

| Spec section | Covered by |
|---|---|
| Module layout | Tasks 2, 6, 8, 10, 11, 12, 13, 14, 15, 16 |
| `PipelineStep` ABC + StepContext + StepResult | Task 2 |
| Backend ABCs + dataclasses + registries | Tasks 6, 8, 10 |
| `FinrlStockSelector` | Task 7 |
| `AIHedgeFundFastEvaluator` (consensus formula) | Task 9 |
| `TradingAgentsDeepEvaluator` (slot mapping) | Task 10 |
| `DataUpdateStep` | Task 11 |
| `StockSelectionStep` (DB writes, backend dispatch) | Task 12 |
| `FastEvaluationStep` (top-N read, write both tables) | Task 13 |
| `DeepEvaluationStep` (top-N read, write deep_evaluation) | Task 14 |
| `FullPipeline` orchestrator (run_id, resume, reports) | Task 15 |
| CLI surface (`--set`, `--resume-from`, `--only`, `--dry-run`) | Task 16 |
| `selected_stocks` column additions | Tasks 4, 5 |
| `fast_evaluation_conclusion` / `fast_evaluation_analysts` tables | Task 4 |
| `deep_evaluation` table | Task 4 |
| `schema_migrations` table + raw-SQL migration runner | Tasks 4, 5 |
| Reports filesystem layout | Task 15 |
| `effective_config.yaml` written per run | Task 16 |
| Error handling — fail-step, empty-input success | Tasks 11, 12, 13, 14, 15 |
| `--resume-from` semantics | Task 15 |
| Backwards-compat config mapping | Task 3 |
| Testing strategy (unit per step, schema, orchestrator, smoke E2E, back-compat, registry) | Tasks 2, 3, 4, 6–15, 17 |
| ai-hedge-fund dep install | Task 1 |
| `sys.path` hazard discipline | Tasks 7, 9, 16 |
| Docs update (`CLAUDE.md`) | Task 18 |
| End-to-end live verification | Task 19 |

No gaps.

**Placeholder scan:** no "TBD" / "implement later" / "appropriate" — all code blocks have complete bodies. Verified.

**Type consistency check:**
- `StepResult` fields used identically across orchestrator, steps, and tests: `step_name`, `status`, `summary`, `payload`, `error`.
- `ScoredTicker.sector` is `str | None` everywhere; tests use `None` and `"Tech"`.
- `AnalystOpinion.confidence` is `float` (0–100) consistently; `_compute_consensus` assumes the same range.
- `FastEvaluation.consensus_score` ∈ [-1, +1] documented in spec and computed accordingly.
- `DeepEvaluation.evaluation_date` is `str` (ISO date or datetime ISO); the step parses both shapes in Task 14.
- Backend `name` attribute is required on every concrete subclass; enforced via `__init_subclass__` in three ABCs.
- Registry methods consistent: `register`, `unregister`, `get`, `__contains__`, `names`.

No inconsistencies found.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-17-full-pipeline-oop-redesign.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task, two-stage review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session via `executing-plans`, batch with checkpoints.

**Which approach?**
