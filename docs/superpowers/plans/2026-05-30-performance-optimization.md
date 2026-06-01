# Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply all 24 performance fixes from the v6 audit in 4 sequential batches, reducing DB round-trips 60-85%, UI queries 80-95%, and 3× speedup on deep evaluation.

**Architecture:** Each batch is self-contained and reversible. Batch 1 (add_all) and Batch 4 (parallel eval) modify pipeline internals. Batch 2 (memory) touches app.py queue lifecycle. Batch 3 (caching) wraps existing functions without logic changes.

**Tech Stack:** Python, SQLAlchemy, Streamlit, pandas, ThreadPoolExecutor

---

## Batch 1 — Critical N+1 DB Fixes

### Task 1.1: `add()` → `add_all()` in FastEvaluationStep

**Files:**
- Modify: `src/pipeline/fast_evaluation.py:75-113`

- [ ] **Step 1: Read current code**

```bash
sed -n '70,120p' src/pipeline/fast_evaluation.py
```

- [ ] **Step 2: Replace per-row `session.add()` with `add_all()`**

Find the evaluation save loop after the evaluate call. Replace with list collection + `add_all()`:

```python
with open_session(ctx) as session:
    session.query(FastEvaluationAnalyst).filter_by(
        pipeline_run_id=ctx.run_id
    ).delete()
    session.query(FastEvaluationConclusion).filter_by(
        pipeline_run_id=ctx.run_id
    ).delete()

    conclusions: list[FastEvaluationConclusion] = []
    analysts: list[FastEvaluationAnalyst] = []
    ranked: list[dict] = []
    now = dt.datetime.utcnow()

    for ev in evaluations:
        pos, neg, neu = _count_by_opinion(ev.opinions)
        conclusions.append(FastEvaluationConclusion(
            pipeline_run_id=ctx.run_id, ticker=ev.ticker, backend=backend_name,
            start_date=dt.date.fromisoformat(ev.start_date),
            end_date=dt.date.fromisoformat(ev.end_date),
            evaluation_date=now, positive_count=pos, negative_count=neg,
            neutral_count=neu, total_count=pos + neg + neu,
            consensus_score=ev.consensus_score,
            model_name=evaluator_cfg.get("model_name", ""),
            model_provider=evaluator_cfg.get("model_provider", ""),
        ))
        for op in ev.opinions:
            analysts.append(FastEvaluationAnalyst(
                pipeline_run_id=ctx.run_id, ticker=ev.ticker, backend=backend_name,
                analyst_name=op.analyst_name, opinion=op.opinion,
                confidence=op.confidence, reasoning=op.reasoning,
                start_date=dt.date.fromisoformat(ev.start_date),
                end_date=dt.date.fromisoformat(ev.end_date),
                evaluation_date=now,
            ))

    session.add_all(conclusions)
    session.add_all(analysts)
    session.commit()

    conclusions_sorted = sorted(conclusions, key=lambda c: c.consensus_score, reverse=True)
    for c in conclusions_sorted:
        ranked.append({
            "ticker": c.ticker, "consensus_score": c.consensus_score,
            "pos": c.positive_count, "neg": c.negative_count, "neu": c.neutral_count,
        })
```

Note: This also resolves finding #17 (_count_by_opinion dedup) since ranking reads from already-computed conclusion fields.

- [ ] **Step 3: Syntax check**

```bash
python -c "import py_compile; py_compile.compile('src/pipeline/fast_evaluation.py', doraise=True)" && echo OK
```

- [ ] **Step 4: Commit**

```bash
git add src/pipeline/fast_evaluation.py
git commit -m "perf: add_all() pattern in FastEvaluationStep; dedup _count_by_opinion"
```

---

### Task 1.2: `add()` → `add_all()` in DeepEvaluationStep

**Files:**
- Modify: `src/pipeline/deep_evaluation.py:75-100`

- [ ] **Step 1: Replace per-row `session.add()` with list + `add_all()`**

```python
rows: list[DeepEvaluationRow] = []
for ev in evaluations:
    rows.append(DeepEvaluationRow(
        pipeline_run_id=ctx.run_id, ticker=ev.ticker,
        evaluation_date=now.date(), backend=backend_name,
        final_decision=ev.final_decision,
        market_report=ev.agent_outputs.get("market_report", ""),
        bull_argument=ev.agent_outputs.get("bull_argument", ""),
        bear_argument=ev.agent_outputs.get("bear_argument", ""),
        research_manager_decision=ev.agent_outputs.get("research_manager_decision", ""),
        trader_plan=ev.agent_outputs.get("trader_plan", ""),
        extra_outputs=ev.extra_outputs,
    ))

session.add_all(rows)
session.commit()
```

- [ ] **Step 2: Syntax check + commit**

```bash
python -c "import py_compile; py_compile.compile('src/pipeline/deep_evaluation.py', doraise=True)" && echo OK
git add src/pipeline/deep_evaluation.py
git commit -m "perf: add_all() pattern in DeepEvaluationStep"
```

---

### Task 1.3: `add()` → `add_all()` in Repository

**Files:**
- Modify: `src/repository.py` (save_selected_stocks, save_predict_only_results)

- [ ] **Step 1: Replace both methods with `add_all()` pattern**

```python
def save_selected_stocks(self, records: list[dict], pipeline_run_id: int | None = None) -> int:
    def _query(s):
        if pipeline_run_id is not None:
            s.query(SelectedStock).filter_by(pipeline_run_id=pipeline_run_id).delete()
        else:
            s.query(SelectedStock).delete()
        run_at = datetime.now()
        rows = []
        for rec in records:
            ml_score = float(rec.get("ml_score", 0))
            rows.append(SelectedStock(
                ticker=rec["ticker"], model_name=rec.get("model_name", ""),
                ml_score=ml_score, bucket=rec.get("bucket"),
                weight=float(rec["weight"]) if rec.get("weight") is not None else None,
                date_selected=rec.get("date_selected", date.today()),
                model_file=rec.get("model_file"),
                pipeline_run_at=run_at, predicted_return=ml_score,
                predicted_at=run_at, pipeline_run_id=pipeline_run_id,
            ))
        s.add_all(rows)
        s.commit()
        return len(rows)
    return self._with_session(_query)
```

Same `rows.append()` + `s.add_all(rows)` pattern for `save_predict_only_results`.

- [ ] **Step 2: Syntax check + commit**

```bash
python -c "import py_compile; py_compile.compile('src/repository.py', doraise=True)" && echo OK
git add src/repository.py
git commit -m "perf: add_all() pattern in repository save methods"
```

---

### Task 1.4: Batch stock lookup in predict-only path

**Files:**
- Modify: `src/repository.py` (add method), `src/app.py:170-195`

- [ ] **Step 1: Add `find_stocks_batch` to repository.py**

```python
def find_stocks_batch(self, symbols: list[str]) -> dict[str, Stock]:
    """Look up multiple stocks in a single query. Returns {SYMBOL: Stock}."""
    def _query(s):
        rows = s.query(Stock).filter(
            Stock.symbol.in_([str(x).upper() for x in symbols])
        ).all()
        return {r.symbol: r for r in rows}
    return self._with_session(_query)
```

- [ ] **Step 2: Update predict-only loop in app.py**

Replace per-ticker `find_stock()` + `iterrows()` with batch lookup + `itertuples()`:

```python
unique_symbols = pred_df["ticker"].dropna().unique().tolist()
stock_map = _repo.find_stocks_batch(unique_symbols)

for row in pred_df.itertuples():
    ticker = str(row.ticker).upper()
    dd = pd.to_datetime(row.datadate).date()
    stock = stock_map.get(ticker)
    if stock is None:
        actual_returns.append(None)
        continue
    prices = _repo.get_prices(stock.id, dd, _date.today())
    # ... rest unchanged ...
```

- [ ] **Step 3: Syntax check + commit**

```bash
python -c "import py_compile; py_compile.compile('src/repository.py', doraise=True); py_compile.compile('src/app.py', doraise=True)" && echo OK
git add src/repository.py src/app.py
git commit -m "perf: batch stock lookup; find_stocks_batch(); iterrows→itertuples"
```

---

## Batch 2 — Memory Leak Fixes

### Task 2.1: Cap ml_log_lines + clear queue sentinels

**Files:**
- Modify: `src/app.py`
- Modify: `src/ui/pages/ml_pipeline.py`

- [ ] **Step 1: Add cap to log_lines polling**

```python
MAX_LOG_LINES = 1000

# In polling loop, after appending:
if len(st.session_state.ml_log_lines) > MAX_LOG_LINES:
    st.session_state.ml_log_lines = st.session_state.ml_log_lines[-MAX_LOG_LINES:]
```

- [ ] **Step 2: Clear on pipeline start**

Before launching pipeline thread in ml_pipeline.py:
```python
st.session_state.ml_log_lines = []
while not st.session_state.ml_log_queue.empty():
    try:
        st.session_state.ml_log_queue.get_nowait()
    except queue.Empty:
        break
```

- [ ] **Step 3: Syntax check + commit**

```bash
python -c "import py_compile; py_compile.compile('src/app.py', doraise=True)" && echo OK
git add src/app.py src/ui/pages/ml_pipeline.py
git commit -m "fix: cap ml_log_lines at 1000; clear queue sentinels on pipeline start"
```

---

## Batch 3 — UI Caching

### Task 3.1: `@st.cache_data` on DB query pages

**Files:**
- Modify: `src/ui/pages/stock_lookup.py`, `stock_technical.py`, `stock_screener.py`, `stock_manager.py`, `overview.py`, `portfolio.py`, `job_history.py`

- [ ] **Step 1: Wrap DB queries**

For each page, add module-level cached wrappers:

**stock_lookup.py:**
```python
@st.cache_data(ttl=300, show_spinner=False)
def _cached_find_stock(symbol: str) -> dict | None:
    from repository import StockRepository
    stock = StockRepository().find_stock(symbol)
    return {"id": stock.id, "symbol": stock.symbol, ...} if stock else None

@st.cache_data(ttl=60, show_spinner=False)
def _cached_get_prices(stock_id: int, start_date: str, end_date: str):
    from repository import StockRepository
    from datetime import date
    return StockRepository().get_prices(stock_id, date.fromisoformat(start_date), date.fromisoformat(end_date))
```

**stock_technical.py**: `@st.cache_data(ttl=60)` on `get_prices`, `get_tech_indicators`

**stock_screener.py**: `@st.cache_data(ttl=300)` on `screen_stocks`

**stock_manager.py**: `@st.cache_data(ttl=300)` on `list_stocks`

**overview.py**: `@st.cache_data(ttl=60)` on `count_summary`

**portfolio.py**: `@st.cache_data(ttl=300)` on `get_latest_selected_stocks`

**job_history.py**: `@st.cache_data(ttl=300)` on `get_job_runs`

- [ ] **Step 2: Update render() calls**

Replace `ctx.repo.find_stock(symbol)` with `_cached_find_stock(symbol)`, etc.

- [ ] **Step 3: Syntax check + commit**

```bash
for f in src/ui/pages/stock_lookup.py src/ui/pages/stock_technical.py src/ui/pages/stock_screener.py src/ui/pages/stock_manager.py src/ui/pages/overview.py src/ui/pages/portfolio.py src/ui/pages/job_history.py; do
  python -c "import py_compile; py_compile.compile('$f', doraise=True)" && echo "$f OK"
done
```

```bash
git add src/ui/pages/
git commit -m "perf: add @st.cache_data to UI pages (80-95% query reduction)"
```

---

## Batch 4 — Remaining Fixes

### Task 4.1: Parallel deep evaluation

**Files:**
- Modify: `src/pipeline/backends/deep_evaluators.py:140-180`

- [ ] **Step 1: Replace serial loop with ThreadPoolExecutor**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _evaluate_one(tkr, g, edate):
    try:
        result = g.propagate(tkr, edate)
        return tkr, result, None
    except Exception as e:
        return tkr, None, str(e)

out: list[DeepEvaluation] = []
max_workers = min(len(tickers), 3)
with ThreadPoolExecutor(max_workers=max_workers) as pool:
    futures = {pool.submit(_evaluate_one, t, graph, eval_date): t for t in tickers}
    for future in as_completed(futures):
        ticker, result, error = future.result(timeout=300)
        if error:
            ctx.logger.exception("TradingAgents failed: %s", error)
            continue
        # ... process result into DeepEvaluation ...
```

- [ ] **Step 2: Syntax check + commit**

```bash
git add src/pipeline/backends/deep_evaluators.py
git commit -m "perf: parallel deep evaluation with ThreadPoolExecutor (3× speedup)"
```

---

### Task 4.2: Batch symbol refresh + iterrows cleanup

**Files:**
- Modify: `src/ingestion/symbols.py:35-65`
- Modify: `src/ingestion/pipeline.py:126`
- Modify: `src/ingestion/indicators.py:97`
- Modify: `src/ui/pages/paper_trading.py:50`

- [ ] **Step 1: Batch INSERT in symbols.py**

```python
BATCH_SIZE = 200
all_values = []
for row in df.itertuples():
    all_values.append({"symbol": row.symbol, "name": ..., "exchange": ..., "is_active": False})

for i in range(0, len(all_values), BATCH_SIZE):
    batch = all_values[i:i + BATCH_SIZE]
    stmt = insert(Stock).values(batch).on_duplicate_key_update(...)
    session.execute(stmt)
session.commit()
```

- [ ] **Step 2: Vectorize iterrows in other files**

- `ingestion/pipeline.py:126`: `df[COLUMNS].to_dict(orient="records")`
- `ingestion/indicators.py:97`: `itertuples()` 
- `ui/pages/paper_trading.py:50`: `set_index().to_dict()`

- [ ] **Step 3: Syntax check + commit**

```bash
git add src/ingestion/ src/ui/pages/paper_trading.py
git commit -m "perf: batch symbol refresh; vectorized iterrows in 4 files"
```

---

### Task 4.3: Low-impact fixes (12-14, 18-20, 23-24)

**Files:**
- Modify: `src/fetcher/alpha_vantage.py` (#12), `src/config.py` (#13), `src/database.py` (#14), `src/ingestion/pipeline.py` (#18-20), `src/app.py` (#24)

- [ ] **Step 1: Apply all low-impact fixes**

#12: Parquet cache for AV `get_listing()` (TTL=6h)
#13: Config mtime revalidation in `load_config()`
#14: `pool_size=8` → `15`, `max_overflow=4` → `10`
#18: Merge 2 sessions into 1 in `_fetch_and_store_prices()`
#20: Remove redundant `load_config()` call in `_upsert_fundamentals()`
#24: Queue drop counter + warning in `_QueueHandler`

- [ ] **Step 2: Syntax check + commit**

```bash
for f in src/fetcher/alpha_vantage.py src/config.py src/database.py src/ingestion/pipeline.py src/app.py; do
  python -c "import py_compile; py_compile.compile('$f', doraise=True)" || echo "FAIL: $f"
done
```

```bash
git add src/fetcher/ src/config.py src/database.py src/ingestion/ src/app.py
git commit -m "perf: low-impact fixes — AV cache, config mtime, pool size, session merge, queue warning"
```

---

## Verification

- [ ] **Final: Full pipeline dry-run**

```bash
PYTHONPATH=src python src/full_pipeline.py --dry-run && echo "All imports OK"
```
