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
├── base.py              # PipelineStep ABC, StepContext, StepResult dataclasses
├── context.py           # StepContext dataclass
├── orchestrator.py      # FullPipeline class
├── config.py            # ConfigLoader (yaml + dotted-path overrides + back-compat)
├── step1_data_update.py # DataUpdateStep
├── step2_finrl.py       # FinrlSelectionStep
├── step3_hedge_fund.py  # HedgeFundEvaluationStep
└── step4_trading_agents.py # TradingAgentsEvaluationStep
```

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
    name: str                         # e.g. "step1_data_update"
    @abstractmethod
    def run(self, ctx: StepContext) -> StepResult: ...
    def step_config(self, ctx: StepContext) -> dict:
        return ctx.cfg.get(self.name, {})
```

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

- **Step 2:** existing `MLBucketSelector` and `finrl_pipeline.run_pipeline_and_save_report` — already in-process. Step class wraps them. **Submodule changes required in `external/FinRL-Trading`:** none.
- **Step 3:** `from src.main import run_hedge_fund` after `sys.path.insert(0, "external/ai-hedge-fund")`. Requires installing ai-hedge-fund's deps (langgraph, langchain-*, etc.) into the AIStock venv. No subprocess. **Submodule changes required in `external/ai-hedge-fund`:** none (only dependency install on the host venv).
- **Step 4:** import `TradingAgentsGraph` from `external/TradingAgents/tradingagents/graph/trading_graph.py` directly. Call `graph.propagate(ticker, eval_date)` per ticker. `ta_run.py` CLI shim keeps working for dashboard usage by importing the same step helpers. **Submodule changes required in `external/TradingAgents`:** none.

## Step contracts

### `DataUpdateStep` (`step1_data_update`)

Reuses `src/fetcher/` and `src/ingestion/`. Refreshes price + indicator + fundamental data for **all active stocks** in the `stocks` table.

Config (`config.yaml → step1_data_update`):

```yaml
step1_data_update:
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

### `FinrlSelectionStep` (`step2_finrl`)

Reads price + fundamental + indicator data from `AISTOCK_DB`, runs the FinRL ML pipeline, writes selected tickers to `selected_stocks` with `pipeline_run_id` and `ml_score`. Minimum changes in `external/FinRL-Trading` — call existing `run_bucket()` via `MLBucketSelector` as today.

Config (`config.yaml → step2_finrl`):

```yaml
step2_finrl:
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
{ "tickers_ranked": [{"ticker": "AAPL", "ml_score": 0.83, "sector": "Information Technology"}, ...] }
```

### `HedgeFundEvaluationStep` (`step3_hedge_fund`)

Selects top N tickers from `selected_stocks WHERE pipeline_run_id = ctx.run_id ORDER BY ml_score DESC LIMIT N`. Calls `run_hedge_fund(...)` per ticker (or batched if supported) and writes:

- One row per analyst per ticker → `ai_hedge_fund_stocks`.
- One row per ticker → `ai_hedge_fund_conclusion`.

Opinion mapping: ai-hedge-fund analyst signals `bullish | bearish | neutral` map to `positive | negative | neutral`. `confidence` is preserved per row.

Consensus score formula (per ticker):

```
consensus_score = Σ(sign_i × confidence_i) / Σ(confidence_i)
  where sign_i = +1 (bullish), 0 (neutral), -1 (bearish)
  range: [-1, +1]
```

Confidence values that the source reports on a 0–100 scale are divided by 100 before applying the formula to keep the result in [-1, +1].

Config (`config.yaml → step3_hedge_fund`):

```yaml
step3_hedge_fund:
  top_n: 10
  start_date: ""               # empty = 3 months before end_date
  end_date: ""                 # empty = today
  model_name: "deepseek-v4-pro"
  model_provider: "DeepSeek"
  initial_cash: 100000.0
  margin_requirement: 0.0
  selected_analysts: [warren_buffett, technical_analyst, fundamentals_analyst, ...]
```

`StepResult.payload`:

```json
{ "tickers_ranked_by_consensus": [{"ticker": "NVDA", "consensus_score": 0.71, "positive": 12, "negative": 1, "neutral": 2}, ...] }
```

### `TradingAgentsEvaluationStep` (`step4_trading_agents`)

Selects top N tickers from `ai_hedge_fund_conclusion WHERE pipeline_run_id = ctx.run_id ORDER BY consensus_score DESC LIMIT N`. Calls `news_cache.install()` (idempotent), then for each ticker constructs a `TradingAgentsGraph` and calls `graph.propagate(ticker, eval_date)`. Extracts the per-agent text fields from the final state and writes one row to `ta_evaluation`.

Config (`config.yaml → step4_trading_agents`):

```yaml
step4_trading_agents:
  top_n: 3
  model_name: "deepseek-v4-pro"
  quick: false                 # quick model for non-critical agents
  use_news_cache: true
  selected_analysts: [market, social, news, fundamentals]
  evaluation_date: ""          # empty = today
```

`StepResult.payload`:

```json
{ "evaluations": [{"ticker": "NVDA", "final_decision": "BUY"}, ...] }
```

## Database schema changes

### Modified: `selected_stocks`

Add columns:

| Column | Type | Notes |
|---|---|---|
| `pipeline_run_id` | `INT NULL` | FK → `pipeline_runs.id`, indexed |
| `ml_score` | `FLOAT NULL` | model output |
| `sector` | `VARCHAR(64) NULL` | denormalized for rank queries |
| `selected_at` | `DATETIME NULL` | write timestamp |

Index: `(pipeline_run_id, ml_score DESC)`.

### New: `ai_hedge_fund_conclusion`

| Column | Type | Notes |
|---|---|---|
| `id` | `INT PK AUTO` | |
| `pipeline_run_id` | `INT NULL FK → pipeline_runs.id` | indexed |
| `ticker` | `VARCHAR(16) NOT NULL` | |
| `start_date` | `DATE NOT NULL` | |
| `end_date` | `DATE NOT NULL` | |
| `evaluation_date` | `DATETIME NOT NULL` | |
| `positive_count` | `INT NOT NULL` | bullish analysts |
| `negative_count` | `INT NOT NULL` | bearish analysts |
| `neutral_count` | `INT NOT NULL` | |
| `total_count` | `INT NOT NULL` | sum |
| `consensus_score` | `FLOAT NOT NULL` | range [-1, +1] |
| `model_name` | `VARCHAR(64)` | |
| `model_provider` | `VARCHAR(32)` | |

Unique: `(pipeline_run_id, ticker)`. Index: `(pipeline_run_id, consensus_score DESC)`.

### New: `ai_hedge_fund_stocks`

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGINT PK AUTO` | |
| `pipeline_run_id` | `INT NULL FK → pipeline_runs.id` | indexed |
| `ticker` | `VARCHAR(16) NOT NULL` | |
| `analyst_name` | `VARCHAR(64) NOT NULL` | e.g. `warren_buffett` |
| `opinion` | `VARCHAR(16) NOT NULL` | `bullish` / `bearish` / `neutral` |
| `confidence` | `FLOAT NOT NULL` | 0–100 |
| `reasoning` | `MEDIUMTEXT` | analyst rationale |
| `start_date` | `DATE NOT NULL` | |
| `end_date` | `DATE NOT NULL` | |
| `evaluation_date` | `DATETIME NOT NULL` | |

Unique: `(pipeline_run_id, ticker, analyst_name)`.

### New: `ta_evaluation`

(ORM class: `TAEvaluation`; table name lowercased per MySQL convention.)

| Column | Type | Notes |
|---|---|---|
| `id` | `INT PK AUTO` | |
| `pipeline_run_id` | `INT NULL FK → pipeline_runs.id` | indexed |
| `ticker` | `VARCHAR(16) NOT NULL` | |
| `evaluation_date` | `DATETIME NOT NULL` | |
| `market_report` | `MEDIUMTEXT` | |
| `social_report` | `MEDIUMTEXT` | |
| `news_report` | `MEDIUMTEXT` | |
| `fundamentals_report` | `MEDIUMTEXT` | |
| `bull_argument` | `MEDIUMTEXT` | |
| `bear_argument` | `MEDIUMTEXT` | |
| `research_manager_decision` | `MEDIUMTEXT` | judge synthesis |
| `trader_plan` | `MEDIUMTEXT` | |
| `risk_aggressive` | `MEDIUMTEXT` | |
| `risk_conservative` | `MEDIUMTEXT` | |
| `risk_neutral` | `MEDIUMTEXT` | |
| `risk_manager_decision` | `MEDIUMTEXT` | |
| `final_decision` | `VARCHAR(16)` | `BUY` / `SELL` / `HOLD` |
| `model_name` | `VARCHAR(64)` | |

Unique: `(pipeline_run_id, ticker)`.

### Migration

- All new tables: defined in `src/models.py`, applied via `Base.metadata.create_all(engine)` on first run.
- `selected_stocks` column additions: raw-SQL migration script `src/migrations/2026_05_17_pipeline_oop.sql` invoked once. The script uses `ADD COLUMN IF NOT EXISTS` semantics (or guarded SQL for MySQL versions that lack it).
- Migration runner: a small `src/migrations/run.py` that records applied versions in a `schema_migrations` table to make migrations idempotent.

## Configuration

### `config.yaml` reorganization

Per-step namespaces replace the existing top-level `finrl_pipeline` and `ai_hedge_fund` keys. `database`, `common`, `log_dir`, and `scheduler` remain at top level.

```yaml
database: {url: "..."}
common: {deepseek_api_key: "...", openai_api_key: "...", ...}
log_dir: "logs"
scheduler: {daily_run_time: "09:30", ...}

step1_data_update:
  source: "alpha_vantage"
  alpha_vantage: {api_key: "..."}
  parallel_workers: 4

step2_finrl:
  source: "AISTOCK_DB"
  start_date: "2020-01-01"
  end_date: "2026-03-31"
  top_quantile: 0.1
  prediction_mode: "regression"
  weight_method: "equal"
  rebalance_freq: "Q"
  benchmarks: [SPY, QQQ]

step3_hedge_fund:
  top_n: 10
  start_date: ""
  end_date: ""
  model_name: "deepseek-v4-pro"
  model_provider: "DeepSeek"
  initial_cash: 100000.0
  margin_requirement: 0.0
  selected_analysts: [warren_buffett, technical_analyst, ...]

step4_trading_agents:
  top_n: 3
  model_name: "deepseek-v4-pro"
  quick: false
  use_news_cache: true
  selected_analysts: [market, social, news, fundamentals]
  evaluation_date: ""
```

### Backward compatibility

`ConfigLoader` reads old top-level keys (`finrl_pipeline`, `ai_hedge_fund`, `source`, `alpha_vantage`) and, when the new per-step keys are absent, maps them as defaults under the corresponding `stepN_*` namespace. A deprecation warning is logged. No existing `config.yaml` breaks.

### CLI surface (`src/full_pipeline.py`)

```
python -m src.full_pipeline [options]

Options:
  --config PATH               Path to config file (default: config.yaml)
  --set KEY=VALUE             Dotted-path override, repeatable.
                              e.g. --set step3_hedge_fund.top_n=5
                                   --set step4_trading_agents.quick=true
                                   --set step3_hedge_fund.selected_analysts='[warren_buffett,ben_graham]'
  --resume-from STEP          One of: step1_data_update, step2_finrl,
                                       step3_hedge_fund, step4_trading_agents
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
├── step1_data_update.{json,md}
├── step2_finrl.{json,md}
├── step3_hedge_fund.{json,md}
├── step4_trading_agents.{json,md}
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
  3. Load prior steps' results from `reports/full_pipeline/N/stepM_*.json` into `ctx.prior_results`.
  4. Iterate from the named step onward.
- `--resume-from` without `--run-id` is an error. Resume is explicit.

## Testing strategy

| Test | Scope |
|---|---|
| Unit tests per step class | Mock fetcher, DB session, `run_hedge_fund`, `TradingAgentsGraph`. Cover: success, partial-ticker failure, empty input, config defaulting, output schema. |
| Schema test | `Base.metadata.create_all` on SQLite in-memory; insert sample rows for each new table; verify constraints and indexes. |
| Orchestrator tests | Stub steps returning canned `StepResult`. Verify run_id propagation, `prior_results` passing, failure stop, `--resume-from` loads correct prior results. |
| Smoke E2E | Rewrite `tests/test_full_pipeline.py`: synthetic 5-ticker universe, mocked LLM calls, run full pipeline, assert tables populated and FK consistent. |
| Backwards-compat | Load old-format `config.yaml` (top-level `finrl_pipeline`/`ai_hedge_fund` keys), assert mapping to `stepN_*` namespaces and deprecation log. |

## Open dependencies and risks

- **ai-hedge-fund deps in AIStock venv:** `pip install` of `langgraph`, `langchain-*`, `langchain-deepseek`, `colorama`, `python-dotenv`. Risk of conflict with TradingAgents' versions. Mitigation: pin TradingAgents and ai-hedge-fund to versions known to share compatible langchain ranges; run smoke import test after install.
- **`sys.path` hazard:** existing pre-import discipline for FinRL applies. The new `step3_hedge_fund.py` must pre-import `config`, `database`, `repository`, `models` before `sys.path.insert(0, "external/ai-hedge-fund")` to avoid `src.main` collisions (ai-hedge-fund also has a `src/main.py`). Document this in `src/pipeline/step3_hedge_fund.py` with a comment.
- **TradingAgents `final_state` schema:** the exact keys for per-agent reports must be verified against the current `TradingAgentsGraph` output before mapping to `ta_evaluation` columns. If keys differ, the step's extractor adapts; schema stays as designed.

## Out of scope (deferred)

- Dashboard `Analysis Reports` page updates: still uses `ta_run.py` CLI shim. `ta_run.py` keeps its current interface; its core logic is extracted into helpers that `TradingAgentsEvaluationStep` also calls.
- Scheduler daemon integration: existing daemon either keeps calling `step1_data_update` directly or invokes the full pipeline; not changed here.
- Removal of the `ai-hedge-fund` Poetry venv: documented but not deleted in this work; allows rollback.
