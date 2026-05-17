# Full Pipeline OOP Redesign

**Status:** Draft — pending user review
**Date:** 2026-05-17
**Author:** brainstorming session
**Supersedes:** existing `src/full_pipeline.py` (function-style orchestrator)
**Related:** `docs/Design of full pipeline.txt` (requirements)

## Goal

Re-organize the 4-step trading pipeline as an object-oriented system. Each step becomes a class with a uniform interface. All four steps share a single `pipeline_run_id`, and steps 2/3/4 are invoked **in-process** (no subprocess) by importing the corresponding submodule's Python entry point. Configuration lives in `config.yaml` with dotted-path CLI overrides.

## Non-Goals

- Refactoring dashboard pages (`src/app.py`).
- Removing the `ta_run.py` CLI shim (kept for dashboard "Analysis Reports" page).
- Deleting the `ai-hedge-fund` Poetry venv (kept as rollback).
- Scheduler daemon changes.

## Architecture

### Module layout

```
src/pipeline/
├── __init__.py
├── base.py                 # PipelineStep ABC, StepContext, StepResult dataclasses
├── context.py              # StepContext dataclass
├── orchestrator.py         # FullPipeline class
├── config.py               # ConfigLoader (yaml + dotted-path overrides + back-compat)
├── data_update.py          # DataUpdateStep (step 1)
├── stock_selection.py      # StockSelectionStep (step 2)
├── fast_evaluation.py      # FastEvaluationStep (step 3)
├── deep_evaluation.py      # DeepEvaluationStep (step 4)
└── backends/               # Pluggable backend implementations
    ├── __init__.py
    ├── selectors.py        # StockSelector ABC + FinrlStockSelector
    ├── fast_evaluators.py  # FastEvaluator ABC + AIHedgeFundFastEvaluator
    └── deep_evaluators.py  # DeepEvaluator ABC + TradingAgentsDeepEvaluator
```

The four step classes are **thin wrappers** — they handle DB I/O, report writing, and backend selection. The actual evaluation/selection logic lives in pluggable backend classes. Adding a new backend (e.g. a different stock selector) is a matter of subclassing the relevant ABC and registering it under a name; no orchestrator or step-class changes required.

`src/full_pipeline.py` becomes a thin CLI shim that parses `argv`, constructs a `StepContext`, and calls `FullPipeline(ctx).run()`. All step logic lives in `src/pipeline/`.

### Core types (`src/pipeline/base.py`)

```python
@dataclass
class StepResult:
    step_name: str
    status: str                       # "success" | "skipped" | "failed"
    summary: dict[str, Any]           # report-friendly, written as JSON + Markdown
    payload: dict[str, Any] = field(default_factory=dict)  # passed to next step
    error: str | None = None          # traceback when status == "failed"

@dataclass
class StepContext:
    cfg: dict                         # full merged config (yaml + CLI overrides)
    run_id: int                       # pipeline_runs.id
    report_dir: Path                  # reports/full_pipeline/<run_id>/
    logger: logging.Logger
    session_factory: Any              # callable returning a SQLAlchemy Session
    prior_results: dict[str, StepResult] = field(default_factory=dict)

class PipelineStep(ABC):
    name: str                         # e.g. "data_update", "stock_selection"
    @abstractmethod
    def run(self, ctx: StepContext) -> StepResult: ...
    def step_config(self, ctx: StepContext) -> dict:
        return ctx.cfg.get(self.name, {})
```

### Backend abstractions (`src/pipeline/backends/`)

Each of steps 2/3/4 defines an ABC that decouples *what* the step does from *how* a specific submodule implements it. The step class is constant; the backend is swappable per config.

```python
# selectors.py
@dataclass
class ScoredTicker:
    ticker: str
    ml_score: float
    sector: str | None

class StockSelector(ABC):
    name: str                         # registry key, e.g. "finrl"
    @abstractmethod
    def select(self, ctx: StepContext) -> list[ScoredTicker]: ...

class FinrlStockSelector(StockSelector):
    name = "finrl"
    # wraps existing finrl_pipeline + MLBucketSelector

# fast_evaluators.py
@dataclass
class AnalystOpinion:
    analyst_name: str
    opinion: str                      # "bullish" | "bearish" | "neutral"
    confidence: float                 # 0-100
    reasoning: str

@dataclass
class FastEvaluation:
    ticker: str
    start_date: str
    end_date: str
    opinions: list[AnalystOpinion]
    consensus_score: float            # [-1, +1]
    # positive/negative/neutral counts derived from opinions

class FastEvaluator(ABC):
    name: str                         # registry key, e.g. "ai_hedge_fund"
    @abstractmethod
    def evaluate(self, tickers: list[str], ctx: StepContext) -> list[FastEvaluation]: ...

class AIHedgeFundFastEvaluator(FastEvaluator):
    name = "ai_hedge_fund"
    # wraps external/ai-hedge-fund src.main.run_hedge_fund

# deep_evaluators.py
@dataclass
class DeepEvaluation:
    ticker: str
    evaluation_date: str
    agent_outputs: dict[str, str]     # per-agent text fields (named slots: market_report, bull_argument, ...)
    extra_outputs: dict[str, Any]     # backend-specific anything else (JSON-serialisable)
    final_decision: str               # "BUY" | "SELL" | "HOLD" | other

class DeepEvaluator(ABC):
    name: str                         # registry key, e.g. "trading_agents"
    @abstractmethod
    def evaluate(self, tickers: list[str], ctx: StepContext) -> list[DeepEvaluation]: ...

class TradingAgentsDeepEvaluator(DeepEvaluator):
    name = "trading_agents"
    # wraps external/TradingAgents TradingAgentsGraph.propagate
```

**Registries.** Each backend module exposes a `REGISTRY: dict[str, type[BackendABC]]`. The step class looks up `cfg["backend"]` against the registry and instantiates. Adding a new backend = subclass + add to registry.

### Orchestrator (`src/pipeline/orchestrator.py`)

`FullPipeline` responsibilities:

1. Create a `pipeline_runs` row → assigns `run_id`. Mark `status='running'`.
2. Resolve which steps to execute (`--resume-from` may skip earlier ones).
3. For each step in order:
   - Log start.
   - Invoke `step.run(ctx)` inside try/except. Exceptions wrap as `StepResult(status="failed", error=traceback)`.
   - Write `<report_dir>/<step_name>.json` and `<step_name>.md`.
   - Store result in `ctx.prior_results[step.name]`.
   - If failed: update `pipeline_runs.status='failed'`, raise `PipelineError`, exit non-zero.
4. After all succeed: write `summary.{json,md}`, update `pipeline_runs.status='success'`.

### In-process submodule integration

The current set of backends wraps the existing submodules. Future backends may target different libraries; the step classes don't change.

- **`stock_selection` / `FinrlStockSelector`:** uses existing `MLBucketSelector` and `finrl_pipeline.run_pipeline_and_save_report` — already in-process. **Submodule changes required in `external/FinRL-Trading`:** none.
- **`fast_evaluation` / `AIHedgeFundFastEvaluator`:** `from src.main import run_hedge_fund` after `sys.path.insert(0, "external/ai-hedge-fund")`. Requires installing ai-hedge-fund's deps (langgraph, langchain-*, etc.) into the AIStock venv. No subprocess. **Submodule changes required in `external/ai-hedge-fund`:** none (only dependency install on the host venv).
- **`deep_evaluation` / `TradingAgentsDeepEvaluator`:** import `TradingAgentsGraph` from `external/TradingAgents/tradingagents/graph/trading_graph.py` directly. Call `graph.propagate(ticker, eval_date)` per ticker. `ta_run.py` CLI shim keeps working for dashboard usage by importing the same backend class. **Submodule changes required in `external/TradingAgents`:** none.

## Step contracts

### `DataUpdateStep` (`data_update`)

Reuses `src/fetcher/` and `src/ingestion/`. Refreshes price + indicator + fundamental data for **all active stocks** in the `stocks` table.

Config (`config.yaml → data_update`):

```yaml
data_update:
  source: "alpha_vantage"      # alpha_vantage | yahoo
  alpha_vantage:
    api_key: "..."
  parallel_workers: 4
```

`StepResult.summary` schema:

```json
{
  "source": "alpha_vantage",
  "symbols_attempted": 423,
  "symbols_succeeded": 421,
  "symbols_failed": 2,
  "failed_symbols": ["XYZ", "ABC"],
  "duration_s": 142.7
}
```

`StepResult.payload` is empty (downstream reads from DB).

### `StockSelectionStep` (`stock_selection`)

Selects a ranked list of tickers using the configured `StockSelector` backend. Writes results to `selected_stocks` with `pipeline_run_id`, `ml_score`, `sector`, and a `backend` column recording which selector produced the row.

Default backend `FinrlStockSelector` reads price + fundamental + indicator data from `AISTOCK_DB` and runs the FinRL ML pipeline (existing `MLBucketSelector` + `run_bucket()`). No `external/FinRL-Trading` changes.

Config (`config.yaml → stock_selection`):

```yaml
stock_selection:
  backend: "finrl"
  finrl:
    source: "AISTOCK_DB"
    start_date: "2020-01-01"
    end_date: "2026-03-31"
    top_quantile: 0.1
    prediction_mode: "regression"
    weight_method: "equal"
    rebalance_freq: "Q"
    benchmarks: [SPY, QQQ]
```

`StepResult.payload`:

```json
{
  "backend": "finrl",
  "tickers_ranked": [
    {"ticker": "AAPL", "ml_score": 0.83, "sector": "Information Technology"},
    ...
  ]
}
```

### `FastEvaluationStep` (`fast_evaluation`)

Selects top N tickers from `selected_stocks WHERE pipeline_run_id = ctx.run_id ORDER BY ml_score DESC LIMIT N`. Invokes the configured `FastEvaluator` backend to get a per-ticker `FastEvaluation`, then writes:

- One row per analyst per ticker → `fast_evaluation_analysts`.
- One row per ticker → `fast_evaluation_conclusion`.

The `backend` column on both tables records which evaluator produced the row.

Default backend `AIHedgeFundFastEvaluator` calls `run_hedge_fund(...)` from `external/ai-hedge-fund/src/main.py`. It maps ai-hedge-fund analyst signals `bullish | bearish | neutral` to `positive | negative | neutral` and computes the consensus score below.

Consensus score formula (per ticker, used by the AIHedgeFund backend; other backends may reuse or override):

```
consensus_score = Σ(sign_i × confidence_i) / Σ(confidence_i)
  where sign_i = +1 (bullish), 0 (neutral), -1 (bearish)
  range: [-1, +1]
```

Confidence values that the source reports on a 0–100 scale are divided by 100 before applying the formula to keep the result in [-1, +1]. The score is stored in `fast_evaluation_conclusion.consensus_score`; backends are responsible for producing a score in `[-1, +1]`.

Config (`config.yaml → fast_evaluation`):

```yaml
fast_evaluation:
  backend: "ai_hedge_fund"
  top_n: 10
  ai_hedge_fund:
    start_date: ""             # empty = 3 months before end_date
    end_date: ""               # empty = today
    model_name: "deepseek-v4-pro"
    model_provider: "DeepSeek"
    initial_cash: 100000.0
    margin_requirement: 0.0
    selected_analysts: [warren_buffett, technical_analyst, fundamentals_analyst, ...]
```

`StepResult.payload`:

```json
{
  "backend": "ai_hedge_fund",
  "tickers_ranked_by_consensus": [
    {"ticker": "NVDA", "consensus_score": 0.71, "positive": 12, "negative": 1, "neutral": 2},
    ...
  ]
}
```

### `DeepEvaluationStep` (`deep_evaluation`)

Selects top N tickers from `fast_evaluation_conclusion WHERE pipeline_run_id = ctx.run_id ORDER BY consensus_score DESC LIMIT N`. Invokes the configured `DeepEvaluator` backend, then writes one row per ticker to `deep_evaluation`. The `backend` column records which evaluator produced the row.

Default backend `TradingAgentsDeepEvaluator` calls `news_cache.install()` (idempotent), constructs a `TradingAgentsGraph`, and calls `graph.propagate(ticker, eval_date)` per ticker. It maps the final state to named agent slots (`market_report`, `social_report`, `news_report`, `fundamentals_report`, `bull_argument`, `bear_argument`, `research_manager_decision`, `trader_plan`, `risk_aggressive`, `risk_conservative`, `risk_neutral`, `risk_manager_decision`) plus `final_decision`. Backend-specific fields that don't fit named slots go in `extra_outputs` (JSON column).

Config (`config.yaml → deep_evaluation`):

```yaml
deep_evaluation:
  backend: "trading_agents"
  top_n: 3
  trading_agents:
    model_name: "deepseek-v4-pro"
    quick: false               # quick model for non-critical agents
    use_news_cache: true
    selected_analysts: [market, social, news, fundamentals]
    evaluation_date: ""        # empty = today
```

`StepResult.payload`:

```json
{
  "backend": "trading_agents",
  "evaluations": [{"ticker": "NVDA", "final_decision": "BUY"}, ...]
}
```

## Database schema changes

### Modified: `selected_stocks`

Add columns:

| Column | Type | Notes |
|---|---|---|
| `pipeline_run_id` | `INT NULL` | FK → `pipeline_runs.id`, indexed |
| `ml_score` | `FLOAT NULL` | model output from the selector |
| `sector` | `VARCHAR(64) NULL` | denormalized for rank queries |
| `backend` | `VARCHAR(32) NULL` | which selector wrote the row (e.g. `finrl`) |
| `selected_at` | `DATETIME NULL` | write timestamp |

Index: `(pipeline_run_id, ml_score DESC)`.

### New: `fast_evaluation_conclusion`

| Column | Type | Notes |
|---|---|---|
| `id` | `INT PK AUTO` | |
| `pipeline_run_id` | `INT NULL FK → pipeline_runs.id` | indexed |
| `ticker` | `VARCHAR(16) NOT NULL` | |
| `backend` | `VARCHAR(32) NOT NULL` | which evaluator produced this row (e.g. `ai_hedge_fund`) |
| `start_date` | `DATE NOT NULL` | |
| `end_date` | `DATE NOT NULL` | |
| `evaluation_date` | `DATETIME NOT NULL` | |
| `positive_count` | `INT NOT NULL` | bullish-equivalent analysts |
| `negative_count` | `INT NOT NULL` | bearish-equivalent analysts |
| `neutral_count` | `INT NOT NULL` | |
| `total_count` | `INT NOT NULL` | sum |
| `consensus_score` | `FLOAT NOT NULL` | range [-1, +1] |
| `model_name` | `VARCHAR(64)` | |
| `model_provider` | `VARCHAR(32)` | |

Unique: `(pipeline_run_id, ticker)`. Index: `(pipeline_run_id, consensus_score DESC)`.

### New: `fast_evaluation_analysts`

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGINT PK AUTO` | |
| `pipeline_run_id` | `INT NULL FK → pipeline_runs.id` | indexed |
| `ticker` | `VARCHAR(16) NOT NULL` | |
| `backend` | `VARCHAR(32) NOT NULL` | which evaluator produced this row |
| `analyst_name` | `VARCHAR(64) NOT NULL` | e.g. `warren_buffett` |
| `opinion` | `VARCHAR(16) NOT NULL` | `bullish` / `bearish` / `neutral` |
| `confidence` | `FLOAT NOT NULL` | 0–100 |
| `reasoning` | `MEDIUMTEXT` | analyst rationale |
| `start_date` | `DATE NOT NULL` | |
| `end_date` | `DATE NOT NULL` | |
| `evaluation_date` | `DATETIME NOT NULL` | |

Unique: `(pipeline_run_id, ticker, analyst_name)`.

### New: `deep_evaluation`

(ORM class: `DeepEvaluationRow`; table name lowercased per MySQL convention.)

Wide-column shape matches the current default `TradingAgentsDeepEvaluator` output. Backends that don't fill every slot leave it `NULL`. Backend-specific extras go in `extra_outputs` (JSON).

| Column | Type | Notes |
|---|---|---|
| `id` | `INT PK AUTO` | |
| `pipeline_run_id` | `INT NULL FK → pipeline_runs.id` | indexed |
| `ticker` | `VARCHAR(16) NOT NULL` | |
| `backend` | `VARCHAR(32) NOT NULL` | which evaluator produced this row (e.g. `trading_agents`) |
| `evaluation_date` | `DATETIME NOT NULL` | |
| `market_report` | `MEDIUMTEXT NULL` | |
| `social_report` | `MEDIUMTEXT NULL` | |
| `news_report` | `MEDIUMTEXT NULL` | |
| `fundamentals_report` | `MEDIUMTEXT NULL` | |
| `bull_argument` | `MEDIUMTEXT NULL` | |
| `bear_argument` | `MEDIUMTEXT NULL` | |
| `research_manager_decision` | `MEDIUMTEXT NULL` | judge synthesis |
| `trader_plan` | `MEDIUMTEXT NULL` | |
| `risk_aggressive` | `MEDIUMTEXT NULL` | |
| `risk_conservative` | `MEDIUMTEXT NULL` | |
| `risk_neutral` | `MEDIUMTEXT NULL` | |
| `risk_manager_decision` | `MEDIUMTEXT NULL` | |
| `extra_outputs` | `JSON NULL` | backend-specific fields not fitting named slots |
| `final_decision` | `VARCHAR(16)` | `BUY` / `SELL` / `HOLD` / other |
| `model_name` | `VARCHAR(64)` | |

Unique: `(pipeline_run_id, ticker)`.

### Migration

- All new tables: defined in `src/models.py`, applied via `Base.metadata.create_all(engine)` on first run.
- `selected_stocks` column additions: raw-SQL migration script `src/migrations/2026_05_17_pipeline_oop.sql` invoked once. The script uses `ADD COLUMN IF NOT EXISTS` semantics (or guarded SQL for MySQL versions that lack it).
- Migration runner: a small `src/migrations/run.py` that records applied versions in a `schema_migrations` table to make migrations idempotent.

## Configuration

### `config.yaml` reorganization

Per-step namespaces replace the existing top-level `finrl_pipeline` and `ai_hedge_fund` keys. `database`, `common`, `log_dir`, and `scheduler` remain at top level. Each step that supports pluggable backends has a `backend` field plus a per-backend subsection of options.

```yaml
database: {url: "..."}
common: {deepseek_api_key: "...", openai_api_key: "...", ...}
log_dir: "logs"
scheduler: {daily_run_time: "09:30", ...}

data_update:
  source: "alpha_vantage"
  alpha_vantage: {api_key: "..."}
  parallel_workers: 4

stock_selection:
  backend: "finrl"
  finrl:
    source: "AISTOCK_DB"
    start_date: "2020-01-01"
    end_date: "2026-03-31"
    top_quantile: 0.1
    prediction_mode: "regression"
    weight_method: "equal"
    rebalance_freq: "Q"
    benchmarks: [SPY, QQQ]

fast_evaluation:
  backend: "ai_hedge_fund"
  top_n: 10
  ai_hedge_fund:
    start_date: ""
    end_date: ""
    model_name: "deepseek-v4-pro"
    model_provider: "DeepSeek"
    initial_cash: 100000.0
    margin_requirement: 0.0
    selected_analysts: [warren_buffett, technical_analyst, ...]

deep_evaluation:
  backend: "trading_agents"
  top_n: 3
  trading_agents:
    model_name: "deepseek-v4-pro"
    quick: false
    use_news_cache: true
    selected_analysts: [market, social, news, fundamentals]
    evaluation_date: ""
```

### Backward compatibility

`ConfigLoader` reads old top-level keys (`finrl_pipeline`, `ai_hedge_fund`, `source`, `alpha_vantage`) and, when the new per-step keys are absent, maps them as defaults under the corresponding new namespace:

- old `source` / `alpha_vantage` → `data_update.source` / `data_update.alpha_vantage`
- old `finrl_pipeline` → `stock_selection.finrl` (with `stock_selection.backend = "finrl"`)
- old `ai_hedge_fund` → `fast_evaluation.ai_hedge_fund` (with `fast_evaluation.backend = "ai_hedge_fund"`)

A deprecation warning is logged. No existing `config.yaml` breaks.

### CLI surface (`src/full_pipeline.py`)

```
python -m src.full_pipeline [options]

Options:
  --config PATH               Path to config file (default: config.yaml)
  --set KEY=VALUE             Dotted-path override, repeatable.
                              e.g. --set fast_evaluation.top_n=5
                                   --set deep_evaluation.trading_agents.quick=true
                                   --set fast_evaluation.ai_hedge_fund.selected_analysts='[warren_buffett,ben_graham]'
                                   --set stock_selection.backend=finrl
  --resume-from STEP          One of: data_update, stock_selection,
                                       fast_evaluation, deep_evaluation
  --run-id N                  Required with --resume-from. Reuses pipeline_runs row N.
  --only STEP                 Run a single step (for development).
  --dry-run                   Log the plan; do not execute steps.
  --log-level LEVEL           DEBUG | INFO | WARN | ERROR (default INFO)
```

`--set` values are parsed as YAML so booleans, ints, lists work naturally. The effective merged config is written to `<report_dir>/effective_config.yaml` for reproducibility.

## Reports

```
reports/full_pipeline/<run_id>/
├── effective_config.yaml
├── data_update.{json,md}
├── stock_selection.{json,md}
├── fast_evaluation.{json,md}
├── deep_evaluation.{json,md}
├── summary.json
└── summary.md
```

DB tables are canonical. Files exist for human review and reproducibility.

## Error handling and resume

- Per-ticker failures inside a step do not abort the step. Step records `succeeded` and `failed` lists. Step status is `success` if at least one ticker succeeds, `failed` only if all fail (or a top-level setup error).
- Empty input is treated as success: if a step receives zero tickers from its upstream query (e.g. step 2 produced none), the step logs a warning, writes an empty summary, and returns `status='success'` with an empty payload. Downstream steps will also short-circuit cleanly.
- A failed step stops the pipeline. `pipeline_runs.status` becomes `failed`, the CLI exits non-zero, and the run remains available for resume.
- `--resume-from STEP --run-id N` semantics:
  1. Load `pipeline_runs.id = N`. If `status == 'success'`, reject.
  2. Set `status = 'running'`.
  3. Load prior steps' results from `reports/full_pipeline/N/<step_name>.json` into `ctx.prior_results`.
  4. Iterate from the named step onward.
- `--resume-from` without `--run-id` is an error. Resume is explicit.

## Testing strategy

| Test | Scope |
|---|---|
| Unit tests per step class | Mock the configured backend instance via the registry — step class should not call submodules directly. Cover: success, partial-ticker failure, empty input, unknown backend name (error), config defaulting, output schema. |
| Unit tests per backend | Mock submodule calls (`run_bucket`, `run_hedge_fund`, `TradingAgentsGraph`). Cover: happy path, empty input, malformed submodule output. |
| Schema test | `Base.metadata.create_all` on SQLite in-memory; insert sample rows for each new table; verify constraints and indexes. |
| Orchestrator tests | Stub steps returning canned `StepResult`. Verify run_id propagation, `prior_results` passing, failure stop, `--resume-from` loads correct prior results. |
| Smoke E2E | Rewrite `tests/test_full_pipeline.py`: synthetic 5-ticker universe, mocked LLM calls, run full pipeline, assert tables populated and FK consistent. |
| Backwards-compat | Load old-format `config.yaml` (top-level `finrl_pipeline`/`ai_hedge_fund` keys), assert mapping to new namespaces and deprecation log. |
| Backend registry | Register a fake `StockSelector`/`FastEvaluator`/`DeepEvaluator` in tests via the registry, set `backend:` to its name, assert step picks it up. Demonstrates extensibility. |

## Open dependencies and risks

- **ai-hedge-fund deps in AIStock venv:** `pip install` of `langgraph`, `langchain-*`, `langchain-deepseek`, `colorama`, `python-dotenv`. Risk of conflict with TradingAgents' versions. Mitigation: pin TradingAgents and ai-hedge-fund to versions known to share compatible langchain ranges; run smoke import test after install.
- **`sys.path` hazard:** existing pre-import discipline for FinRL applies. The new `backends/fast_evaluators.py` (AIHedgeFundFastEvaluator) must pre-import `config`, `database`, `repository`, `models` before `sys.path.insert(0, "external/ai-hedge-fund")` to avoid `src.main` collisions (ai-hedge-fund also has a `src/main.py`). Document this with a comment at the import block.
- **TradingAgents `final_state` schema:** the exact keys for per-agent reports must be verified against the current `TradingAgentsGraph` output before mapping to `deep_evaluation` columns. If keys differ, the `TradingAgentsDeepEvaluator` extractor adapts; schema stays as designed.

## Out of scope (deferred)

- Dashboard `Analysis Reports` page updates: still uses `ta_run.py` CLI shim. `ta_run.py` keeps its current interface; its core logic is extracted into the `TradingAgentsDeepEvaluator` backend that `DeepEvaluationStep` also uses.
- Scheduler daemon integration: existing daemon either keeps calling the new `DataUpdateStep` directly or invokes the full pipeline; not changed here.
- Removal of the `ai-hedge-fund` Poetry venv: documented but not deleted in this work; allows rollback.
