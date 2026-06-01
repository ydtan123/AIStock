# AIStock Performance Audit — Comprehensive Analysis v2

**Date:** 2026-05-30
**Scope:** Full source tree — Python/Streamlit/MySQL stack
**Severity:** 🔴 Critical / 🟠 High / 🟡 Medium / 🟢 Low

> **Note on scope:** This codebase is Python/Streamlit, not React. "Re-renders" analysis covers Streamlit rerun behavior — every user interaction triggers full script re-execution, making caching critical.

---

## Summary

| Category | Count | Severity |
|----------|-------|----------|
| N+1 Query Patterns | 3 | 🔴×1 🟠×2 |
| Missing Streamlit Caching | 6 | 🔴×2 🟠×3 🟡×1 |
| Redundant Computations | 5 | 🟠×2 🟡×2 🟢×1 |
| Polling & Rerender Waste | 2 | 🔴×1 🟠×1 |
| Resource Management | 2 | 🟠×1 🟡×1 |
| DataFrame Performance | 3 | 🟠×1 🟡×2 |

**Estimated cumulative fix impact:** 60-85% fewer DB round-trips, 50-70% fewer rerender cycles.

---

## 🔴 Critical Issues

### 1. N+1 Query in Predict-Only Pipeline (`app.py:175-190`)

**File:** `src/app.py` — `_predict_only_thread_target()`

Each ticker triggers 2 DB queries inside a loop. 50 tickers = 100 DB calls.

```python
# CURRENT: N+1 — 2N DB calls for N tickers
for _, row in pred_df.iterrows():          # iterrows() also slow (see #9)
    ticker = row["ticker"]
    stock = _repo.find_stock(str(ticker))   # DB call #1 per ticker
    if stock is None:
        actual_returns.append(None)
        continue
    prices = _repo.get_prices(stock.id, dd, _date.today())  # DB call #2
```

**Fix:** Batch lookups into 2 total queries.

```python
# Add to src/repository.py:
def find_stocks_batch(self, symbols: list[str]) -> dict[str, Stock]:
    """Look up multiple stocks in a single query."""
    return self._with_session(lambda s: {
        stk.symbol: stk
        for stk in s.query(Stock).filter(Stock.symbol.in_(symbols)).all()
    })

def get_prices_batch(self, stock_ids: list[int], start: date, end: date) \
        -> dict[int, pd.DataFrame]:
    """Fetch prices for multiple stocks in a single query."""
    return self._with_session(lambda s: {
        sid: group.drop(columns="stock_id")
        for sid, group in pd.read_sql(
            text("SELECT stock_id, date, adj_close FROM daily_prices "
                 "WHERE stock_id IN :ids AND date BETWEEN :s AND :e "
                 "ORDER BY date"),
            s.bind,
            params={"ids": tuple(stock_ids), "s": start, "e": end},
            parse_dates=["date"],
        ).groupby("stock_id")
    })

# In _predict_only_thread_target:
tickers = pred_df["ticker"].unique().tolist()
stock_map = _repo.find_stocks_batch([str(t) for t in tickers])
stock_ids = {s: stock_map[s].id for s in stock_map}
min_date = pd.to_datetime(pred_df["datadate"].min()).date()
all_prices = _repo.get_prices_batch(list(stock_ids.values()), min_date, dt.date.today())

def _compute_actual(row):
    sid = stock_ids.get(str(row["ticker"]))
    prices = all_prices.get(sid) if sid else None
    if prices is None or len(prices) < 2:
        return None
    return float(prices["adj_close"].iloc[-1] / prices["adj_close"].iloc[0] - 1)

pred_df["actual_return"] = pred_df.apply(_compute_actual, axis=1)
```

**Impact:** ~98% reduction in DB calls (100 → 2 for 50 stocks).

---

### 2. Polling `st.rerun()` Sleep Loop (`ml_pipeline.py:406-409`)

**File:** `src/ui/pages/ml_pipeline.py` — `render()`

While pipeline runs, entire page re-renders every 1 second. All form widgets, DB queries (including `count_summary()` from sidebar), and plots re-execute each cycle.

```python
# CURRENT: reruns whole page every 1s
if status == "Running":
    import time as _time
    _time.sleep(1)
    ctx.st.rerun()
```

**Fix:** Use `st.fragment(run_every=1)` for log display area only.

```python
@st.fragment(run_every=1)
def _render_log_fragment(ctx):
    lines = ctx.session_state.get("ml_log_lines", [])
    log_text = "\n".join(lines[-200:]) if lines else "..."
    ctx.st.code(log_text, language=None)

# In render(), replace the polling block + log display with:
if ctx.session_state.get("ml_status") == "Running":
    _render_log_fragment(ctx)
# REMOVE: the `if status == "Running": time.sleep(1); st.rerun()` block
```

Also remove `st.rerun()` after launching thread (lines 363, 378) — use `st.rerun(scope="fragment")` instead.

**Impact:** Eliminates N unnecessary full-page rerenders (N = pipeline duration in seconds).

---

### 3. Zero Streamlit Caching on Count/Summary Queries

**Files:** `src/ui/pages/overview.py:8`, `src/app.py:222`

`repo.count_summary()` executes 3 `SELECT COUNT(*)` queries on EVERY page navigation and rerender. With the polling loop (#2), that's once per second during pipeline runs.

**Fix:**

```python
# In a shared cache module or at top of overview.py:
@st.cache_data(ttl=300, show_spinner=False)
def _cached_count_summary():
    from repository import StockRepository
    return StockRepository().count_summary()

# In render():
summary = _cached_count_summary()
```

**Impact:** 100% elimination of redundant count queries within 5-min TTL.

---

## 🟠 High-Severity Issues

### 4. N+1 Query in ML Results Display (`ml_pipeline.py:58-67`)

**File:** `src/ui/pages/ml_pipeline.py` — `_show_ml_results()`

Loops over unique tickers calling `find_stock()` individually:

```python
# CURRENT: N+1
for sym in wdf[ticker_col].dropna().unique():
    stock = _repo.find_stock(str(sym))
    name_map[sym] = stock.name if stock else ""
```

**Fix:** Use `find_stocks_batch()` from issue #1.

```python
syms = wdf[ticker_col].dropna().unique().tolist()
stock_map = _repo.find_stocks_batch([str(s) for s in syms])
name_map = {s: stock_map[s].name if s in stock_map else "" for s in syms}
```

**Impact:** ~95% fewer queries.

---

### 5. No `@st.cache_data` on Stock Lookup Queries

**File:** `src/ui/pages/stock_lookup.py:21,41-42`

```python
# CURRENT: 3 DB queries per rerun, even with unchanged inputs
stock = ctx.repo.find_stock(symbol)
ind = ctx.repo.get_indicator(stock.id)
prices_df = ctx.repo.get_prices(stock.id, start_date, end_date)
```

**Fix:**

```python
@st.cache_data(ttl=300, show_spinner="Loading data...")
def _cached_stock_data(symbol: str, start_iso: str, end_iso: str):
    from datetime import date as dt_date
    from repository import StockRepository
    repo = StockRepository()
    stock = repo.find_stock(symbol)
    if not stock:
        return None, None, None
    ind = repo.get_indicator(stock.id)
    prices = repo.get_prices(stock.id,
        dt_date.fromisoformat(start_iso),
        dt_date.fromisoformat(end_iso))
    return stock, ind, prices

# In render():
stock, ind, prices_df = _cached_stock_data(symbol, str(start_date), str(end_date))
```

**Impact:** Zero DB queries on repeated views of same stock with same date range.

---

### 6. Dual `_count_by_opinion()` Calls (`fast_evaluation.py:83,119`)

**File:** `src/pipeline/fast_evaluation.py`

Same opinions counted twice: first for DB persistence (line 83), then for report payload (line 119).

```python
# Line 83: counted for DB
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)
    session.add(FastEvaluationConclusion(...))

# Line 119: counted AGAIN
for ev in evaluations_sorted:
    pos, neg, neu = _count_by_opinion(ev.opinions)
    ranked.append({...})
```

**Fix:** Cache counts on evaluation objects.

```python
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)
    ev._counts = (pos, neg, neu)  # cache on dataclass instance
    session.add(FastEvaluationConclusion(
        positive_count=pos, negative_count=neg, neutral_count=neu, ...
    ))

for ev in evaluations_sorted:
    pos, neg, neu = ev._counts
    ranked.append({"ticker": ev.ticker, "positive": pos, ...})
```

**Impact:** 50% reduction in counting loops.

---

### 7. Redundant DB Round-Trip in `get_latest_selected_stocks()` (`repository.py:267-278`)

**File:** `src/repository.py`

Two queries when one subquery would suffice:

```python
# CURRENT: 2 round-trips
latest_run = s.query(SelectedStock.pipeline_run_at) \
    .order_by(SelectedStock.pipeline_run_at.desc()).limit(1).scalar()
rows = s.query(SelectedStock).filter(
    SelectedStock.pipeline_run_at == latest_run).all()
```

**Fix:**

```python
from sqlalchemy import func

subq = s.query(func.max(SelectedStock.pipeline_run_at)).scalar_subquery()
rows = s.query(SelectedStock).filter(
    SelectedStock.pipeline_run_at == subq).all()
```

**Impact:** 50% fewer round-trips.

---

### 8. No `@st.cache_data` on CSV/JSON Reads (`ml_pipeline.py:36-53,142`)

**File:** `src/ui/pages/ml_pipeline.py` — `_show_ml_results()`, `_show_ml_backtest()`

`fundamentals.csv`, `ml_weights_sector.csv`, and `backtest_result_*.json` re-read from disk on every rerender.

**Fix:**

```python
@st.cache_data(ttl=600, show_spinner="Loading results...")
def _load_ml_weights():
    from finrl_runner import DATA_DIR
    # read CSVs, merge, add company names
    ...
    return processed_data

@st.cache_data(ttl=600, show_spinner="Loading backtest...")
def _load_backtest():
    from finrl_runner import DATA_DIR
    bt_files = sorted(DATA_DIR.glob("backtest_result_*.json"), reverse=True)
    if not bt_files:
        return None
    with open(bt_files[0]) as f:
        return json.load(f)
```

**Impact:** Eliminates repeated disk I/O within TTL window.

---

## 🟡 Medium-Severity Issues

### 9. `iterrows()` Antipattern (`app.py:175`)

**File:** `src/app.py` — `_predict_only_thread_target()`

`pd.DataFrame.iterrows()` is ~10x slower than vectorized ops. Each iteration creates a Series object.

**Fix:** Replace with pre-computed vectorized dicts + `apply()` (see issue #1 for combined fix).

---

### 10. DataFrame from ORM List Comprehension (`repository.py:58-69`)

**File:** `src/repository.py` — `get_prices()`

Builds DataFrame row-by-row from ORM objects. `pd.read_sql` with native SQL is 2-5x faster for large datasets.

```python
# FIX:
def get_prices(self, stock_id: int, start: date, end: date) -> pd.DataFrame:
    return self._with_session(lambda s: pd.read_sql(
        text("SELECT date, open, high, low, close, adj_close, volume "
             "FROM daily_prices WHERE stock_id=:sid "
             "AND date>=:s AND date<=:e ORDER BY date"),
        s.bind, params={"sid": stock_id, "s": start, "e": end},
        parse_dates=["date"],
    ))
```

---

### 11. `load_config()` Called Per Render (`ml_pipeline.py:278-279`)

**File:** `src/ui/pages/ml_pipeline.py`

Config loaded on every form render for default widget values. Config already has module-level cache (line `_config` in `config.py:6`), but extracting defaults repeatedly wastes CPU.

**Fix:** Extract defaults once with `@st.cache_data`.

---

### 12. Thread Accumulation on Repeated Pipeline Runs (`ml_pipeline.py:361-363,376-378`)

**File:** `src/ui/pages/ml_pipeline.py`

Each "Run Pipeline" click spawns a new daemon thread. Old threads aren't tracked or joined. On repeated runs, orphaned threads accumulate until their work completes.

**Fix:** Track and join previous threads.

```python
if "pipeline_thread" not in ctx.session_state:
    ctx.session_state.pipeline_thread = None

# Before spawning new thread:
old = ctx.session_state.pipeline_thread
if old and old.is_alive():
    ctx.st.warning("Pipeline already running")
else:
    t = _threading.Thread(target=...)
    ctx.session_state.pipeline_thread = t
    t.start()
```

---

### 13. `to_datetime` → `strftime` Roundtrip in Fundamentals (`finrl_runner.py:178`)

**File:** `src/finrl_runner.py` — `run_predict_only()`

```python
# CURRENT: datetime → string → datetime (wasteful if already date type)
df["datadate"] = pd.to_datetime(df["datadate"]).dt.strftime("%Y-%m-%d")
```

**Fix:** Check if column is already datetime before converting.

---

## 🟢 Low-Severity Issues

### 14. `_inject_api_keys` Duplicated Logic (`fast_evaluators.py:72-89`, `deep_evaluators.py:54-70`)

Both files have near-identical `_inject_api_keys()` functions. Extract to shared utility.

### 15. `st.session_state.ml_log_lines` Unbounded Growth (`ml_pipeline.py`)

Log lines appended indefinitely. `[-200:]` slicing in display mitigates display cost but memory still grows. Cap at 500 lines.

### 16. No Connection Pool Tuning (`database.py`)

Default `pool_size=5` may bottleneck during parallel ingestion. Consider `pool_size=10, max_overflow=5` for pipeline workloads.

---

## Fix Priority Matrix

| # | Issue | Severity | Effort | Files Affected |
|---|-------|----------|--------|----------------|
| 3 | Cache count_summary | 🔴 | 5 min | `overview.py`, `app.py` |
| 5 | Cache stock lookup | 🟠 | 10 min | `stock_lookup.py` |
| 7 | Subquery `get_latest_selected_stocks` | 🟠 | 5 min | `repository.py` |
| 8 | Cache ML CSV/JSON reads | 🟠 | 15 min | `ml_pipeline.py` |
| 6 | Fix dual `_count_by_opinion` | 🟠 | 5 min | `fast_evaluation.py` |
| 2 | Fragment-based log polling | 🔴 | 30 min | `ml_pipeline.py` |
| 1 | Batch N+1 predict-only queries | 🔴 | 45 min | `app.py`, `repository.py` |
| 4 | Batch ML company names | 🟠 | 10 min | `ml_pipeline.py` |
| 12 | Thread leak fix | 🟡 | 10 min | `ml_pipeline.py` |
| 10 | `pd.read_sql` for prices | 🟡 | 10 min | `repository.py` |

---

## New Repository Methods Required

```python
# Add to src/repository.py — StockRepository class:

def find_stocks_batch(self, symbols: list[str]) -> dict[str, Stock]:
    """Look up multiple stocks in single query."""
    return self._with_session(lambda s: {
        stk.symbol: stk
        for stk in s.query(Stock).filter(Stock.symbol.in_(
            [sym.upper() for sym in symbols]
        )).all()
    })

def get_prices_batch(self, stock_ids: list[int], start: date, end: date) \
        -> dict[int, pd.DataFrame]:
    """Fetch prices for multiple stocks in single query."""
    if not stock_ids:
        return {}
    return self._with_session(lambda s: {
        sid: grp.drop(columns="stock_id")
        for sid, grp in pd.read_sql(
            text("SELECT stock_id, date, adj_close FROM daily_prices "
                 "WHERE stock_id IN :ids AND date BETWEEN :s AND :e "
                 "ORDER BY date"),
            s.bind,
            params={"ids": tuple(stock_ids), "s": start, "e": end},
            parse_dates=["date"],
        ).groupby("stock_id")
    })
```

---

## Quick Wins (< 30 min total)

These 3 fixes deliver the highest impact for minimal effort:

1. **`@st.cache_data(ttl=300)` on `count_summary()`** — 2 lines in `overview.py` + `app.py`, stops most redundant DB calls
2. **`@st.cache_data(ttl=300)` on `stock_lookup` queries** — 5 lines, stops repeat queries on tab switches
3. **Subquery in `get_latest_selected_stocks()`** — 3 lines in `repository.py`, halves round-trips
