# Full Pipeline Script — Design Spec
**Date:** 2026-05-16  
**Status:** Approved

---

## 1. Goal

Single CLI script (`src/full_pipeline.py`) that runs four sequential steps end-to-end:
1. Update daily prices, indicators, fundamentals from DB last date → today
2. FinRL ML stock selection → write results to DB + JSON report
3. ai-hedge-fund evaluation of top 10 by ML score → parse consensus
4. TradingAgents evaluation of top 3 by ai-hedge-fund net consensus score

All results saved to `reports/full_pipeline/YYYYMMDD-HHMMSS/` as `.md` + `.json` pairs.

---

## 2. Architecture

```
src/full_pipeline.py  (orchestrator)
│
├── Step 1 — run_daily_pipeline()
│   Direct import from src/ingestion/pipeline.py (same venv)
│   Returns: dict {processed, errors, symbols}
│
├── Step 2 — run_pipeline_and_save_report()
│   Direct import from src/finrl_pipeline.py (same venv)
│   Returns: selected_stocks_info list; top 10 read back from DB by ml_score
│
├── Step 3 — subprocess
│   cd external/ai-hedge-fund
│   poetry run python main_non_interactive.py \
│     --tickers T1,...,T10 \
│     --output-json /tmp/ahf_<run_id>.json
│   Parse: decisions dict → score BUY_conf - SELL_conf per ticker
│
├── Step 4 — subprocess
│   PYTHONPATH=src python src/ta_run.py \
│     --tickers T1,T2,T3 \
│     --date YYYY-MM-DD
│   Parse: stdout NDJSON → collect type=ticker_result events
│
└── Report writer
    reports/full_pipeline/YYYYMMDD-HHMMSS/
    ├── step1_daily_update.{md,json}
    ├── step2_finrl.{md,json}
    ├── step3_hedge_fund.{md,json}
    ├── step4_trading_agents.{md,json}
    └── summary.{md,json}
```

---

## 3. Components

### 3.1 `src/full_pipeline.py`

**Entry point:**
```
python src/full_pipeline.py [--config config.yaml] [--skip-step1] [--dry-run]
```

**Structure:**
```python
def step1_daily_update(cfg, report_dir) -> dict
def step2_finrl_selection(cfg, report_dir) -> list[dict]   # top 10 records
def step3_hedge_fund(tickers, cfg, report_dir) -> list[dict]  # scored tickers
def step4_trading_agents(tickers, cfg, report_dir) -> list[dict]
def write_summary(results, report_dir) -> None
def main() -> None
```

**Error handling:** Any step failure raises immediately. Orchestrator catches, writes partial `summary.json` with `status=failed`, `failed_at=stepN`, then re-raises (non-zero exit).

### 3.2 `main_non_interactive.py` change

Add `--output-json <path>` flag. When provided, write after `print_trading_output`:
```python
if args.output_json:
    with open(args.output_json, "w") as f:
        json.dump(result, f, indent=2, default=str)
```
`result` already has `{"decisions": {...}, "analyst_signals": {...}}`.

### 3.3 ta_run.py interface (no change needed)

Already emits NDJSON to stdout. Collect events where `type == "ticker_result"` (or similar from `_run_ticker` return). The `done` event has `summary` list.

---

## 4. Data Flow

### Step 2 → Step 3: top 10 tickers

After FinRL completes, query DB:
```sql
SELECT ticker, ml_score, bucket FROM selected_stocks
WHERE pipeline_run_at = (SELECT MAX(pipeline_run_at) FROM selected_stocks)
ORDER BY ml_score DESC LIMIT 10
```
Pass ticker list to Step 3.

### Step 3 → Step 4: top 3 by consensus

Parse `decisions` from ai-hedge-fund JSON output:
```python
# decisions = {"AAPL": {"action": "BUY", "quantity": 100, "confidence": 0.85}, ...}
scores = {t: d["confidence"] if d["action"]=="BUY" else -d["confidence"]
          for t, d in decisions.items()}
top3 = sorted(scores, key=scores.get, reverse=True)[:3]
```
Pass to Step 4.

### Step 4 output

Collect NDJSON from ta_run.py stdout. Extract per-ticker decision + bullet summaries.

---

## 5. Report Format

### Per-step JSON schema

```json
{
  "step": 1,
  "status": "success",
  "started_at": "2026-05-16T19:30:00",
  "finished_at": "2026-05-16T19:45:00",
  "data": { /* step-specific payload */ }
}
```

### Step-specific payloads

**Step 1:**
```json
{"processed": 420, "errors": 3, "symbols_updated": ["AAPL", ...]}
```

**Step 2:**
```json
{"total_selected": 70, "top10": [{"ticker":"X","ml_score":0.82,"bucket":"GROWTH_TECH","top_feature":"momentum_3m"}, ...]}
```

**Step 3:**
```json
{"tickers_evaluated": ["T1",...], "decisions": {"T1": {"action":"BUY","confidence":0.85,"net_score":0.85}}, "top3": ["T1","T2","T3"]}
```

**Step 4:**
```json
{"tickers_evaluated": ["T1","T2","T3"], "results": {"T1": {"decision":"BUY","summary_bullets":[...]}}}
```

### Markdown reports

Each step's `.md` contains:
- Run timestamp + duration
- Key metrics in a table
- Full detail in sections

### `summary.{md,json}`

```json
{
  "run_id": "20260516-193000",
  "status": "success",
  "steps_completed": 4,
  "final_recommendations": ["T1","T2","T3"],
  "report_dir": "reports/full_pipeline/20260516-193000"
}
```

---

## 6. Configuration

All parameters read from `config.yaml`. Full pipeline adds no new config section — reuses `finrl_pipeline:`, `ai_hedge_fund:`, and `common:` sections.

CLI override: `--config <path>` to point at alternate config file.  
`--skip-step1`: skip data update (useful for re-running analysis without re-fetching).

---

## 7. Environment Setup

| Step | Environment | How invoked |
|------|-------------|-------------|
| 1, 2 | AIStock `.venv` | Direct import |
| 3 | `external/ai-hedge-fund` poetry env | `subprocess.run(["poetry", "run", "python", ...], cwd=...)` |
| 4 | AIStock `.venv` (ta_run.py uses sys.path insert) | `subprocess.run([sys.executable, "src/ta_run.py", ...])` |

Step 4 uses the same Python interpreter (`sys.executable`) since `ta_run.py` handles its own `sys.path` insertion for TradingAgents.

---

## 8. Files to Create/Modify

| File | Action |
|------|--------|
| `src/full_pipeline.py` | **CREATE** — orchestrator |
| `external/ai-hedge-fund/main_non_interactive.py` | **MODIFY** — add `--output-json` flag |
| `reports/full_pipeline/` | Auto-created at runtime |

No other files need modification.

---

## 9. Out of Scope

- Scheduling (run via cron or launchd separately)
- Parallel step execution
- Retry logic (fail fast, fix and re-run)
- Web UI integration (CLI-first as decided)
