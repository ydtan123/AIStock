# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Stock Data Ingestion & Visualization System. Fetches OHLCV + fundamental data from Alpha Vantage or Yahoo Finance, stores in MySQL, and exposes a Streamlit web dashboard.

## Tech Stack

- **Language**: Python
- **ORM**: SQLAlchemy 2.0 (declarative unified style)
- **Database**: MySQL via `pymysql` driver
- **Data sources**: Alpha Vantage (`TIME_SERIES_DAILY_ADJUSTED`, `OVERVIEW` endpoints) or `yfinance`
- **Web app**: Streamlit + Plotly (`plotly.graph_objects` for candlestick charts)
- **CLI**: `argparse`

## Configuration

`config.yaml` at project root:

```yaml
source: "alpha_vantage"  # or "yahoo"
alpha_vantage:
  api_key: "YOUR_KEY_HERE"
database:
  url: "mysql+pymysql://user:pass@localhost/stock_db"
```

## Directory Structure

```
src/          # all source code
  app.py        Streamlit dashboard
  config.py     config loader (reads config.yaml from project root)
  database.py   engine creation, session factory, get_session()
  display.py    formatting utilities
  main.py       CLI entry point (--symbol, --start, --end)
  models.py     SQLAlchemy models: Stock, DailyPrice, StockIndicator
  repository.py data access layer
  scheduler.py  APScheduler background job
  fetcher/      Alpha Vantage / yfinance fetch logic
  ingestion/    pipeline, indicators computation
  model/        XGBoost training, inference, labels, feature builder
tests/        pytest smoke tests
scripts/      one-off utility scripts
docs/         ADRs and agent docs
launchd/      macOS launchd plist templates
config.yaml   API keys, data source selection, DB connection URL
```

## Key Files

| File | Purpose |
|------|---------|
| `config.yaml` | API keys, data source selection, DB connection URL |
| `src/models.py` | SQLAlchemy models: `Stock`, `DailyPrice`, `StockIndicator` |
| `src/database.py` | Engine creation, session factory, `get_session()` |
| `src/fetcher/` | Alpha Vantage / yfinance fetch logic, incremental update logic |
| `src/main.py` | CLI entry point (`--symbol`, `--start`, `--end`) |
| `src/app.py` | Streamlit dashboard |

## Database Schema

Three tables:

- **stocks**: `id`, `symbol` (unique), `company_name`, `sector`
- **daily_prices**: `id`, `stock_id` (FK), `date`, `open`, `high`, `low`, `close`, `volume` — unique index on `(stock_id, date)`
- **stock_indicators**: `id`, `stock_id` (FK), `pe_ratio`, `market_cap`, `dividend_yield`, `last_updated` — upsert on update

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize / migrate database tables
python -c "import sys; sys.path.insert(0,'src'); from database import engine; from models import Base; Base.metadata.create_all(engine)"

# Fetch data for a symbol (full history)
python src/main.py --symbol AAPL

# Fetch with custom date range
python src/main.py --symbol AAPL --start 2020-01-01 --end 2024-12-31

# Incremental refresh (fetches only missing dates)
python src/main.py --symbol AAPL --incremental

# Launch Streamlit dashboard
streamlit run src/app.py
```

## Architecture Notes

**Incremental update**: Before fetching, query `max(date)` from `daily_prices` for the symbol. Request API data from `max_date + 1 day` through today. Skip fetch entirely if already up to date.

**Upsert for indicators**: Alpha Vantage `OVERVIEW` data changes over time. Use SQLAlchemy's `INSERT ... ON DUPLICATE KEY UPDATE` (MySQL dialect) or merge logic to update existing `stock_indicators` rows rather than inserting duplicates.

**Rate limiting**: Alpha Vantage free tier allows 5 calls/minute, 500/day. The fetcher must respect this — add `time.sleep(12)` between calls when batch-processing multiple symbols.

**Source abstraction**: `fetcher.py` should expose a common interface regardless of source. The `config.yaml` `source` key selects the backend; callers should not need to know which provider is active.

**Streamlit dashboard layout**:
- Sidebar: symbol search input
- Main panel: Plotly candlestick chart, metric cards (PE ratio, market cap, volume), recent data table

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `ydtan123/AIStock`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
