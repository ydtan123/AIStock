# AIStock Performance Optimization Report v4

**Date:** 2026-05-30  
**Scope:** Full codebase — N+1 queries, caching, memory leaks, redundant computations, Streamlit rendering  
**Severity:** 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low

---

## 🔴 Critical Issues

### C1. N+1 Query: Predict-Only Pipeline — Per-Stock DB Queries

**File:** `src/app.py:175-190` (`_predict_only_thread_target`)  
**Impact:** For N predictions, makes 2N+1 DB queries (find_stock + get_prices per ticker). With 500 tickers = ~1000 queries.

**Current code:**
```python
for _, row in pred_df.iterrows():
    ticker = row["ticker"]
    dd = _pd.to_datetime(row["datadate"]).date()
    stock = _repo.find_stock(str(ticker))      # N+1: query per ticker
    if stock is None:
        actual_returns.append(None)
        continue
    prices = _repo.get_prices(stock.id, dd, _date.today())  # N+1: query per ticker
```

**Fix — batch lookup + single query for all prices:**
```python
# Step 1: Resolve all tickers in ONE query
tickers = pred_df["ticker"].astype(str).str.upper().tolist()
with get_session() as s:
    stocks = s.query(Stock).filter(Stock.symbol.in_(tickers)).all()
stock_map = {st.symbol: st for st in stocks}

# Step 2: Build (stock_id, start_date) pairs
price_queries: dict[tuple[int, date], int] = {}  # (stock_id, start_date) -> row_idx
for idx, row in pred_df.iterrows():
    ticker = str(row["ticker"]).upper()
    stk = stock_map.get(ticker)
    if stk is None:
        actual_returns.insert(idx, None)
        continue
    dd = _pd.to_datetime(row["datadate"]).date()
    price_queries[(stk.id, dd)] = idx

# Step 3: Single batch query for latest close per stock
actual_returns = [None] * len(pred_df)
if price_queries:
    with get_session() as s:
        for (stock_id, start_dt), idx in price_queries.items():
            latest = (
                s.query(DailyPrice.adj_close)
                .filter(DailyPrice.stock_id == stock_id,
                        DailyPrice.date >= start_dt)
                .order_by(DailyPrice.date.desc())
                .limit(1)
                .scalar()
            )
            if latest:
                start_px = (
                    s.query(DailyPrice.adj_close)
                    .filter(DailyPrice.stock_id == stock_id,
                            DailyPrice.date >= start_dt)
                    .order_by(DailyPrice.date.asc())
                    .limit(1)
                    .scalar()
                )
                if start_px and start_px > 0:
                    actual_returns[idx] = float((latest / start_px) - 1)
```

**Even better — single SQL with window functions:**
```python
# One query per stock_id group using LAG or subquery
# For simplicity, batch all stock_ids into a UNION ALL query
if price_queries:
    with get_session() as s:
        stock_ids = list({sid for sid, _ in price_queries})
        # Get min/max close per stock in one shot
        rows = s.execute(
            text("""
                SELECT stock_id, 
                       MIN(CASE WHEN rn_asc = 1 THEN adj_close END) as first_close,
                       MAX(CASE WHEN rn_desc = 1 THEN adj_close END) as last_close
                FROM (
                    SELECT stock_id, adj_close,
                           ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date ASC) as rn_asc,
                           ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) as rn_desc
                    FROM daily_prices
                    WHERE stock_id IN :ids AND date >= :global_start
                ) sub
                WHERE rn_asc = 1 OR rn_desc = 1
                GROUP BY stock_id
            """),
            {"ids": tuple(stock_ids), "global_start": min(d for _, d in price_queries)},
        ).fetchall()
        px_map = {r[0]: (r[1], r[2]) for r in rows}
        for (stock_id, start_dt), idx in price_queries.items():
            first, last = px_map.get(stock_id, (None, None))
            if first and last and first > 0:
                actual_returns[idx] = float((last / first) - 1)
```

**Expected improvement:** 1000 queries → 1-2 queries. ~500x speedup for 500 tickers.

---

### C2. No Streamlit Cache — Every Interaction Re-Queries DB

**File:** Entire codebase  
**Impact:** Streamlit reruns the entire script on every widget change. Every DB query executes fresh on every interaction — `count_summary()`, `get_prices()`, `get_sectors()`, CSV reads, JSON reads all repeat.

**Fix — Apply `@st.cache_data` strategically:**

```python
# src/repository.py — add cached wrapper functions at module level
import streamlit as st

@st.cache_data(ttl=60, show_spinner=False)
def cached_count_summary() -> dict:
    return StockRepository().count_summary()

@st.cache_data(ttl=300, show_spinner=False)
def cached_get_sectors(table: str = "stock_snapshots") -> list[str]:
    return StockRepository().get_sectors(table)

@st.cache_data(ttl=60, show_spinner=False)
def cached_get_latest_selected_stocks() -> list[dict]:
    return StockRepository().get_latest_selected_stocks()
```

```python
# src/ui/pages/ml_pipeline.py
@st.cache_data(ttl=300, show_spinner="Loading results...")
def _cached_read_weights(data_dir: str) -> pd.DataFrame | None:
    """Read weights CSV. TTL invalidates when file changes."""
    for candidate in ["ml_weights_sector.csv", "ml_weights_today.csv"]:
        p = Path(data_dir) / candidate
        if p.exists():
            return pd.read_csv(p)
    return None

@st.cache_data(ttl=300, show_spinner=False)
def _cached_read_backtest(data_dir: str) -> dict | None:
    """Read latest backtest JSON."""
    bt_files = sorted(Path(data_dir).glob("backtest_result_*.json"), reverse=True)
    if not bt_files:
        return None
    with open(bt_files[0]) as f:
        return json.load(f)
```

**Usage in page functions:**
```python
# Instead of:
summary = ctx.repo.count_summary()
# Use:
summary = cached_count_summary()
```

**Expected improvement:** Navigation between pages does 0 DB queries instead of 5-10 per render.

---

## 🟠 High Impact

### H1. N+1 Query: ML Results Company Name Lookup

**File:** `src/ui/pages/ml_pipeline.py:57-68`  
**Impact:** For every unique ticker in the weights file (100-500 symbols), makes an individual `find_stock()` call.

**Current code:**
```python
name_map: dict = {}
for sym in wdf[ticker_col].dropna().unique():
    stock = _repo.find_stock(str(sym))  # N+1
    name_map[sym] = stock.name if stock else ""
wdf["company"] = wdf[ticker_col].map(name_map)
```

**Fix — single batch query:**
```python
symbols = [str(x) for x in wdf[ticker_col].dropna().unique()]
with get_session() as s:
    stocks = s.query(Stock.symbol, Stock.name).filter(
        Stock.symbol.in_(symbols)
    ).all()
name_map = {st.symbol: st.name or "" for st in stocks}
wdf["company"] = wdf[ticker_col].astype(str).map(name_map)
```

**Expected improvement:** 100-500 queries → 1 query.

---

### H2. Streamlit Poll Loop — Full Rerender Every Second

**File:** `src/ui/pages/ml_pipeline.py:406-409`  
**Impact:** While pipeline runs, entire page rerenders every 1 second. All DB queries, CSV reads, charts regenerate 60x/minute.

```python
if status == "Running":
    import time as _time
    _time.sleep(1)
    ctx.st.rerun()
```

**Fix — use `st.fragment(run_every=...)` for polling:**

```python
@st.fragment(run_every=1)
def _poll_pipeline_status(ctx):
    """Lightweight poll — only renders status bar + log tail, skips heavy content."""
    # Drain queue into session state (no DB queries, no CSV reads)
    while True:
        try:
            msg = ctx.session_state.ml_log_queue.get_nowait()
        except queue.Empty:
            break
        if isinstance(msg, str) and msg.startswith("__REPORT__:"):
            ctx.session_state.ml_report_path = msg[len("__REPORT__:"):]
            ctx.session_state.ml_status = "Complete"
        elif isinstance(msg, str) and msg.startswith("__ERROR__:"):
            ctx.session_state.ml_error = msg[len("__ERROR__:"):]
            ctx.session_state.ml_status = "Error"
        elif isinstance(msg, str) and msg.startswith("__PREDICT_DF__:"):
            ctx.session_state.ml_predict_only_df = json.loads(msg[len("__PREDICT_DF__:"):])
        else:
            ctx.session_state.ml_log_lines.append(str(msg))
            # Truncate to prevent unbounded growth
            if len(ctx.session_state.ml_log_lines) > 500:
                ctx.session_state.ml_log_lines = ctx.session_state.ml_log_lines[-500:]

    status = ctx.session_state.get("ml_status", "Idle")
    elapsed = time.time() - ctx.session_state.get("ml_start_time", 0)
    ctx.st.markdown(f"**Status:** {status} | Elapsed: {elapsed:.0f}s")

    log_text = "\n".join(ctx.session_state.ml_log_lines[-200:])
    ctx.st.code(log_text or "Starting...", language="text")
```

Then in `render()`, replace the poll loop + result display with:
```python
_poll_pipeline_status(ctx)

# Only render heavy content when pipeline is done
if ctx.session_state.get("ml_status") == "Complete":
    if ctx.session_state.get("ml_predict_only_df"):
        _show_predict_only_results(ctx, ctx.session_state.ml_predict_only_df)
    else:
        _show_ml_results(ctx)
        _show_ml_backtest(ctx)
elif ctx.session_state.get("ml_status") == "Error":
    ctx.st.error(f"Pipeline failed: {ctx.session_state.ml_error}")
```

**Expected improvement:** Heavy content rendered once instead of 60x/minute.

---

### H3. Double `_count_by_opinion` Computation

**File:** `src/pipeline/fast_evaluation.py:83,119`  
**Impact:** Same opinion triples counted twice — once for DB insert (line 83), again for payload ranking (line 119).

**Fix — compute once, reuse:**
```python
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)
    total = pos + neg + neu
    # Attach counts to evaluation object for reuse
    ev._counts = (pos, neg, neu, total)  # type: ignore[attr-defined]
    
    session.add(FastEvaluationConclusion(
        ...,
        positive_count=pos, negative_count=neg, neutral_count=neu, total_count=total,
    ))

# Later — use cached counts:
evaluations_sorted = sorted(evaluations, key=lambda e: e.consensus_score, reverse=True)
for ev in evaluations_sorted:
    pos, neg, neu, _ = ev._counts  # type: ignore[attr-defined]
    ranked.append({
        "ticker": ev.ticker, "consensus_score": ev.consensus_score,
        "positive": pos, "negative": neg, "neutral": neu,
    })
```

---

### H4. Config Loaded Per-Stock in Ingestion Pipeline

**File:** `src/ingestion/pipeline.py:183`  
**Impact:** `_upsert_fundamentals` calls `load_config()` every invocation. With 500 stocks, that's 500 YAML file reads + parses.

**Fix — load once at module level:**
```python
# Top of pipeline.py, already loads config:
_cfg = load_config()
_REFRESH_DAYS = _cfg.get("scheduler", {}).get("overview_refresh_days", 7)

# In _upsert_fundamentals, replace:
#   config = load_config()
#   refresh_days = config.get("scheduler", {}).get("overview_refresh_days", 7)
# With:
    refresh_days = _REFRESH_DAYS
```

---

## 🟡 Medium Impact

### M1. DataFrame Row-by-Row Construction in `get_prices`

**File:** `src/repository.py:58-69`  
**Impact:** Builds list of dicts in Python loop, then wraps in DataFrame. For 5 years of daily data (~1250 rows per stock), this is O(n) in Python overhead.

**Current:**
```python
return self._with_session(lambda s: pd.DataFrame([{
    "date": r.date, "open": r.open, ...
} for r in s.query(DailyPrice).filter(...).all()]))
```

**Fix — use `pd.read_sql`:**
```python
def get_prices(self, stock_id: int, start: date, end: date) -> pd.DataFrame:
    def _query(s):
        stmt = (
            s.query(DailyPrice)
            .filter(DailyPrice.stock_id == stock_id,
                    DailyPrice.date >= start,
                    DailyPrice.date <= end)
            .order_by(DailyPrice.date)
            .statement
        )
        return pd.read_sql(stmt, s.bind,
                          columns=["date", "open", "high", "low", "close", "adj_close", "volume"])
    return self._with_session(_query)
```

---

### M2. `ml_log_lines` Unbounded in Session State

**File:** `src/ui/pages/ml_pipeline.py:395`  
**Impact:** All log lines stored indefinitely. For pipeline generating 10,000+ lines, memory grows without bound. Only last 200 lines displayed (line 399).

**Fix — truncate on append:**
```python
MAX_LOG_LINES = 500
ctx.session_state.ml_log_lines.append(str(msg))
if len(ctx.session_state.ml_log_lines) > MAX_LOG_LINES:
    ctx.session_state.ml_log_lines = ctx.session_state.ml_log_lines[-MAX_LOG_LINES:]
```

---

### M3. `StockRepository` Instantiated Multiple Times

**File:** `src/ui/pages/stock_detail.py:11`, `src/app.py:160`  
**Impact:** `stock_detail.py` creates its own `StockRepository()` instead of using `ctx.repo`. The `_predict_only_thread_target` also creates a new instance.

**Fix — use ctx.repo in stock_detail.py:**
```python
# src/ui/pages/stock_detail.py
# Replace:
#   from repository import StockRepository
#   _repo = StockRepository()
#   stock = _repo.find_stock(symbol)
# With:
stock = ctx.repo.find_stock(symbol)
indicator = ctx.repo.get_indicator(stock.id) if stock else None
snapshot = ctx.repo.get_snapshot(stock.id) if stock else None
```

---

### M4. Iterator Over DataFrame with `iterrows()`

**File:** `src/app.py:175`, `src/ingestion/pipeline.py:126`, `src/fetcher/alpha_vantage.py:68`  
**Impact:** `iterrows()` returns a Series copy per row — slowest DataFrame iteration method. Each row creates a new Series object.

**Fix for ingestion pipeline (`src/ingestion/pipeline.py:126`):**
```python
# Instead of:
values = []
for _, row in df.iterrows():
    values.append({...})

# Use:
values = df.to_dict("records")
```

**Fix for alpha_vantage (`src/fetcher/alpha_vantage.py:68`):**
```python
# Instead of building rows one dict at a time:
# Build column-oriented dict (faster):
cols = {"date": [], "open": [], "high": [], "low": [], "close": [],
        "adj_close": [], "volume": [], "dividend_amount": [], "split_coefficient": []}
for date_str, vals in ts.items():
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    if d < start or d > end:
        continue
    cols["date"].append(d)
    cols["open"].append(safe_float(vals.get("1. open")))
    cols["high"].append(safe_float(vals.get("2. high")))
    # ... etc
df = pd.DataFrame(cols)
```

---

## 🟢 Low Impact

### L1. Logger Handler Accumulation Risk

**File:** `src/app.py:128,153`  
**Impact:** If pipeline thread is killed mid-execution, `root.removeHandler(handler)` never runs. Over long-running Streamlit sessions, root logger accumulates orphaned handlers.

**Fix — use dedicated logger, not root:**
```python
pl = logging.getLogger("pipeline.thread")
pl.propagate = False  # Don't bubble to root
pl.addHandler(handler)
# ... cleanup:
pl.removeHandler(handler)
```

---

### L2. `st.code()` Without Language Spec

**File:** `src/ui/pages/ml_pipeline.py:404`  
**Fix:**
```python
ctx.st.code(log_text, language="text")  # was: language=None
```

---

### L3. Hardcoded `MAX_WORKERS = 5`

**File:** `src/ingestion/pipeline.py:22`  
**Fix:**
```python
MAX_WORKERS = int(os.environ.get("AISTOCK_MAX_WORKERS", "5"))
```

---

### L4. Missing Index on `daily_prices(stock_id, date DESC)`

**File:** `src/ingestion/pipeline.py:254-300`  
**Impact:** The `stock_snapshots` REPLACE INTO query joins 5 tables. The subquery `MAX(date) GROUP BY stock_id` benefits from a composite index.

**Verify:**
```sql
SHOW INDEX FROM daily_prices WHERE Key_name LIKE '%stock%date%';
```

**If missing:**
```sql
CREATE INDEX idx_daily_stock_date_desc ON daily_prices(stock_id, date DESC);
CREATE INDEX idx_tech_ind_stock_date_desc ON technical_indicators(stock_id, date DESC);
```

---

## Summary Table

| # | Severity | Category | File | Lines | Effort |
|---|----------|----------|------|-------|--------|
| C1 | 🔴 Critical | N+1 Query | `app.py` | 175-190 | Medium |
| C2 | 🔴 Critical | Missing Cache | All pages | — | Low |
| H1 | 🟠 High | N+1 Query | `ml_pipeline.py` | 57-68 | Low |
| H2 | 🟠 High | Rerender Loop | `ml_pipeline.py` | 406-409 | Medium |
| H3 | 🟠 High | Redundant Compute | `fast_evaluation.py` | 83,119 | Low |
| H4 | 🟠 High | Redundant I/O | `pipeline.py` | 183 | Low |
| M1 | 🟡 Medium | DataFrame Perf | `repository.py` | 58-69 | Low |
| M2 | 🟡 Medium | Memory Growth | `ml_pipeline.py` | 395 | Low |
| M3 | 🟡 Medium | Dup Instances | `stock_detail.py` | 11 | Low |
| M4 | 🟡 Medium | iterrows() | Multiple files | — | Low |
| L1 | 🟢 Low | Handler Leak | `app.py` | 128,153 | Low |
| L2 | 🟢 Low | Rendering Hint | `ml_pipeline.py` | 404 | Trivial |
| L3 | 🟢 Low | Configurability | `pipeline.py` | 22 | Trivial |
| L4 | 🟢 Low | DB Index | `pipeline.py` | 254 | Trivial |

**Estimated total improvement:** C1 alone saves ~1000 queries per predict-only run. C2 saves 5-10 DB queries per page navigation. Together with H1-H4, expect 10-100x throughput improvement for common operations. Memory usage for long-running Streamlit sessions drops significantly with M2 + L1 fixes.
