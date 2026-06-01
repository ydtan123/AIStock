# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Stock Data Ingestion, ML Stock Selection, Evaluation & Visualization System. Four subsystems share a MySQL database:

- **AIStock** (`src/`) — price/fundamental ingestion, 4-step pipeline orchestration, Streamlit web app
- **FinRL-Trading** (`external/FinRL-Trading/`) — sector ML stock selection via `run_bucket()`
- **TradingAgents** (`external/TradingAgents/`) — multi-agent LLM deep evaluation of selected stocks
- **ai-hedge-fund** (`external/ai-hedge-fund/`) — multi-analyst LLM fast evaluation of selected stocks

## Tech Stack

- **Language**: Python, `.venv` at project root
- **ORM**: SQLAlchemy 2.0 (declarative unified style)
- **Database**: MySQL via `pymysql`
- **Data sources**: Alpha Vantage, yfinance, or AIStock DB (for FinRL pipeline)
- **Web app**: Streamlit + Plotly (`plotly.graph_objects`)
- **ML**: Ridge/Stacking ensemble (sector ML via FinRL)

## Commands

```bash
# Run dashboard
PYTHONPATH=src streamlit run src/app.py

# Full 4-step OOP pipeline
PYTHONPATH=src python src/full_pipeline.py
PYTHONPATH=src python src/full_pipeline.py --resume-from fast_evaluation --run-id 42
PYTHONPATH=src python src/full_pipeline.py --set fast_evaluation.top_n=5

# Initialize DB tables
python -c "import sys; sys.path.insert(0,'src'); from database import engine; from models import Base; Base.metadata.create_all(engine)"

# Run pipeline tests
PYTHONPATH=src pytest tests/test_pipeline_*.py tests/test_full_pipeline_*.py -v
# Run smoke tests (requires DB with data)
PYTHONPATH=src pytest tests/test_smoke_pipeline.py -m smoke -s
# Single label
PYTHONPATH=src pytest tests/test_smoke_pipeline.py -m smoke -k max_high_5pct -s
```

## Configuration

`config.yaml` at project root:

```yaml
source: "alpha_vantage"  # or "yahoo"
alpha_vantage:
  api_key: "YOUR_KEY_HERE"
database:
  url: "mysql+pymysql://user:pass@localhost/stock_db"
```

## Architecture

### sys.path Hazard (Critical)

`external/FinRL-Trading/src/data/data_fetcher.py` inserts `external/FinRL-Trading/src/` at `sys.path[0]` unconditionally on import. This makes `import config` resolve to FinRL's `config/` package instead of AIStock's `src/config.py`.

**The fix (already applied in `src/finrl_pipeline.py`):** Pre-import `config`, `database`, `repository` at module level before any FinRL imports so `sys.modules` caches the correct AIStock versions. Never change this ordering.

### AIStock Subsystem (`src/`)

```
config.py         loads config.yaml — import this before database.py
database.py       engine + get_session() — depends on config.py
models.py         SQLAlchemy models (~400 lines, 14 tables)
repository.py     StockRepository — all DB queries go here
fetcher/          FetcherBase + AlphaVantage/Yahoo implementations, TokenBucket rate limiter
ingestion/        pipeline.py (batch ingest), indicators.py, symbols.py
scheduler.py      APScheduler wrapping ingestion pipeline
app.py            Streamlit entry point (~350 lines); routes to src/ui/pages/
ui/pages/         one module per page (overview, selected_stocks, fast_evaluation_page, deep_evaluation_page, stock_lookup, stock_technical, stock_screener, stock_manager, strategy_backtest, live_trading, paper_trading, portfolio, settings, job_history)
ml_bucket_selector.py  MLBucketSelector class wrapping external run_bucket()
full_pipeline.py  CLI shim for OOP pipeline orchestrator
pipeline/         OOP pipeline package
  ├── base.py           PipelineStep ABC + StepResult + StepContext
  ├── config.py         ConfigLoader (yaml + dotted-path overrides)
  ├── orchestrator.py   FullPipeline
  ├── data_update.py    DataUpdateStep (step 1)
  ├── stock_selection.py     StockSelectionStep (step 2)
  ├── fast_evaluation.py     FastEvaluationStep (step 3)
  ├── deep_evaluation.py     DeepEvaluationStep (step 4)
  └── backends/         pluggable selector/evaluator implementations
migrations/         idempotent SQL migration runner + .sql files
```

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

### FinRL Subsystem (`external/FinRL-Trading/src/`)

Only these paths matter for AIStock integration:
- `strategies/ml_bucket_selection.py` — `run_bucket()`, `FEATURE_COLS`, `SECTOR_TO_BUCKET`
- `data/data_fetcher.py` — `AIStockDBSource` added by this project; `create_data_source("aistock_db")`

### Dashboard Pages (`src/app.py` + `src/ui/pages/`)

Sidebar `st.selectbox` routes to these page functions:

| Page | Function | Notes |
|------|----------|-------|
| Full Pipeline | `render_full_pipeline()` | 4-step OOP pipeline with real-time log streaming |
| Selected Stocks | `render_selected_stocks()` | ML-selected stocks table with detail popup |
| Fast Evaluation | `render_fast_evaluation()` | Per-run/per-stock analyst breakdown |
| Deep Evaluation | `render_deep_evaluation()` | Per-run/per-stock LLM agent reports |
| Stock Data | `page_stock_data()` | Tabs: Lookup, Technical, Screener, Manager, Predictions |
| Strategy Backtesting | `render_strategy_backtest()` | |
| Live Trading | `render_live_trading()` | |
| Paper Trading | `render_paper_trading()` | |
| Portfolio Analysis | `render_portfolio()` | |
| Settings | `render_settings()` | |
| Job History | `render_job_history()` | |

### Benchmark Comparison

`_run_simple_backtest()` accepts `benchmarks: list[str]` (default `["SPY", "QQQ"]`). Fetches benchmark price series from same `data_source`, stores `benchmark_values` and `benchmark_metrics` in the backtest JSON. UI plots all as `go.Scatter` traces (dashed lines) on the same chart.

## Database Schema

### Core tables

- **stocks**: `id`, `symbol` (unique), `company_name`, `sector`, `is_active`, `exchange`, `currency`, `country`, `industry`, `shares_outstanding`, `shares_float`
- **daily_prices**: `(stock_id, date)` unique — OHLCV + `dividend_amount`, `split_coefficient`
- **stock_indicators**: `stock_id` FK — PE, market cap, EBITDA, EPS, revenue, margins, ROE/ROA, analyst ratings, dividend yield — upsert on update
- **technical_indicators**: `stock_id` FK + `date` — `indicators` (JSON blob)
- **stock_snapshots**: `stock_id` PK — screening fast-lookup table
- **quarterly_fundamentals**: `(stock_id, symbol, datadate)` — 70+ financial metrics per stock-quarter

### Pipeline & scheduling

- **pipeline_runs**: `id`, `started_at`, `finished_at`, `symbols_processed`, `errors_count`, `status`
- **selected_stocks**: stocks selected by ML pipeline — columns include `pipeline_run_id`, `sector`, `backend` (added by migration `2026_05_17_pipeline_oop.sql`); indexed by `(pipeline_run_id, ml_score)` for top-N queries
- **fast_evaluation_conclusion**: `(pipeline_run_id, ticker, backend)` unique — counts of positive/negative/neutral analysts plus `consensus_score`; indexed for top-N queries
- **fast_evaluation_analysts**: `(pipeline_run_id, ticker)` — one row per analyst opinion with `confidence` and `reasoning`
- **deep_evaluation**: `(pipeline_run_id, ticker)` — wide row of per-agent text fields (`market_report`, `bull_argument`, `bear_argument`, `research_manager_decision`, `trader_plan`) plus `extra_outputs` JSON for backend-specific data; `final_decision` ∈ {BUY, SELL, HOLD}
- **schema_migrations**: `version` PK — tracks applied raw-SQL migrations for idempotency

## MCP Tools: code-review-graph

**ALWAYS use code-review-graph MCP tools BEFORE Grep/Glob/Read to explore the codebase.**

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes |
| `get_review_context` | Need source snippets for review |
| `get_impact_radius` | Blast radius of a change |
| `get_affected_flows` | Which execution paths are impacted |
| `query_graph` | Trace callers, callees, imports, tests |
| `semantic_search_nodes` | Find functions/classes by name or keyword |
| `get_architecture_overview` | High-level community structure |

Graph auto-updates on file changes via hooks. 7 communities, 0 cross-community edges.

## Agent Skills

- Issues: GitHub Issues on `ydtan123/AIStock` — see `docs/agents/issue-tracker.md`
- Triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`
- Domain docs: `CONTEXT.md` + `docs/adr/` at repo root


## Security / Performance Audits — On-Demand Only

Security audits and performance audits are **gated**: only run when the user explicitly requests them via `/security-audit`, `/performance-audit`, or an explicit "run a security audit" / "run a performance audit" command. Do NOT auto-trigger on code changes, edits, or session start.

When explicitly requested:
- **Security audit checklist**: hardcoded secrets in .yaml/.env/.py, XSS in Streamlit, .env in .gitignore. Output to docs/security-audit.md.
- **Performance audit categories**: DB/N+1 queries, caching gaps, Streamlit re-renders, I/O blocking, algorithmic complexity. Output to docs/performance-audit.md with severity ratings.
- **Test coverage**: `pytest --cov --cov-report=term-missing` → identify untested modules → docs/coverage-gap-analysis.md.

## Tests

**Always** add end to end tests to cover the new functionalities when new functionalities are added in the web app. **Always** run all tests after the web app is changed. Make sure all tests passed before continue.  

## Output Conventions

All reports write to docs/ as markdown, never chat-only. JSON alongside .md for structured outputs.

