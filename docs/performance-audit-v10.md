# AIStock Performance Audit v10

**Date:** 2026-05-30
**Scope:** Full codebase — N+1 queries, Streamlit re-renders, caching, memory leaks, redundant computation

---

## 1. N+1 Query Patterns

### 1.1 CRITICAL — Per-ticker price fetch in predict-only thread

**File:** `src/app.py:183-198` (`_predict_only_thread_target`)

```python
# CURRENT: N+1 — each ticker triggers a separate get_prices() DB call
for row in pred_df.itertuples():
    prices = _repo.get_prices(stock.id, dd, _date.today())
```

Each `get_prices()` opens a session, runs `SELECT * FROM daily_prices WHERE stock_id=?`, and closes. For 100 tickers → 100 sessions/transactions.

**Fix:** Add batch-fetch method to `StockRepository`:

```python
# src/repository.py — add method
def get_prices_batch(
    self, stocks: list[tuple[int, date, date]]
) -> dict[int, pd.DataFrame]:
    """Fetch prices for multiple stocks in one query. Returns {stock_id: DataFrame}."""
    if not stocks:
        return {}
    from sqlalchemy import or_, and_
    conditions = [
        and_(DailyPrice.stock_id == sid,
             DailyPrice.date >= s, DailyPrice.date <= e)
        for sid, s, e in stocks
    ]
    def _query(s):
        rows = s.query(DailyPrice).filter(or_(*conditions)).order_by(DailyPrice.date).all()
        result: dict[int, list[dict]] = {}
        for r in rows:
            result.setdefault(r.stock_id, []).append({
                "date": r.date, "open": r.open, "high": r.high,
                "low": r.low, "close": r.close, "adj_close": r.adj_close,
                "volume": r.volume,
            })
        return {sid: pd.DataFrame(recs) for sid, recs in result.items()}
    return self._with_session(_query)
```

**Expected impact:** 100 queries → 1 query per predict-only run. ~100x DB round-trip reduction.

---

### 1.2 HIGH — Two COUNT queries where one suffices

**File:** `src/repository.py:191-196` (`count_summary`)

```python
# CURRENT: Two separate COUNT(*) queries
total = s.query(Stock).count()
active = s.query(Stock).filter_by(is_active=True).count()
```

**Fix:** Single aggregation query:

```python
# FIXED: One query with conditional aggregation
row = s.execute(text(
    "SELECT COUNT(*), COALESCE(SUM(CASE WHEN is_active THEN 1 ELSE 0 END), 0) FROM stocks"
)).fetchone()
total, active = row[0], row[1]
return {"total": total, "active": active, "inactive": total - active}
```

**Expected impact:** 2 queries → 1. Every sidebar render hits this path.

---

### 1.3 MEDIUM — `_prefetch_stock_dates` sends duplicate table query

**File:** `src/ingestion/pipeline.py:85-103`

```python
# CURRENT: Two queries against daily_prices table
rows = session.execute(text("SELECT stock_id, MAX(date) FROM daily_prices ...")).fetchall()
rows = session.execute(text("SELECT stock_id, MIN(date) FROM daily_prices ...")).fetchall()
```

**Fix:** Combine into single query:

```python
rows = session.execute(text(
    "SELECT stock_id, MAX(date), MIN(date) FROM daily_prices "
    "WHERE stock_id IN :ids GROUP BY stock_id"
), {"ids": ids}).fetchall()
max_price_dates = {r[0]: r[1] for r in rows}
first_price_dates = {r[0]: r[2] for r in rows}
```

**Expected impact:** 4 queries → 3 in `_prefetch_stock_dates`. Already well-optimized otherwise.

---

## 2. Streamlit Re-renders

Note: This is a Streamlit app, not React. Streamlit re-executes the entire script on every widget interaction. The equivalent concept is avoiding redundant full-script re-execution.

### 2.1 HIGH — No `@st.fragment` boundaries

**File:** `src/app.py` (full module)

Streamlit re-runs the entire script on every widget interaction. `repo = StockRepository()` is re-created, all page modules re-imported, `_build_ctx()` creates new `PageContext` each render.

**Fix:** Wrap independent sections in `@st.fragment`:

```python
# src/app.py
@st.fragment
def sidebar_nav():
    with st.sidebar:
        page = st.selectbox("Navigation", [...])
        display_quick_stats(repo)
    return page

@st.fragment
def render_page_content(page, ctx):
    if page == "Overview":
        render_overview(ctx)
    elif page == "Stock Data":
        page_stock_data(ctx)
    # ...

# main()
page = sidebar_nav()
ctx = _build_ctx()
render_page_content(page, ctx)
```

**Expected impact:** Sidebar interactions don't re-render main content; vice versa.

---

### 2.2 HIGH — Active polling loop for pipeline logs

**File:** `src/ui/pages/ml_pipeline.py:440-443`

```python
# CURRENT: Full page re-render every 1s during pipeline run
if status == "Running":
    time.sleep(1)
    ctx.st.rerun()
```

This also rebuilds the full log string every second:

```python
log_text = "\n".join(list(ctx.session_state.ml_log_lines)[-200:])
```

**Fix:** Use `st.fragment(run_every=N)` for the log area:

```python
@st.fragment(run_every=2)
def _show_pipeline_logs(log_lines, status):
    if log_lines:
        log_text = "\n".join(list(log_lines)[-200:])
    elif status == "Running":
        log_text = "Pipeline starting..."
    else:
        log_text = "No runs yet."
    st.code(log_text, language=None)

# Replace polling loop + log display with:
_show_pipeline_logs(ctx.session_state.ml_log_lines, status)
```

**Expected impact:** Only the log area re-renders every 2s; rest of page stays static during pipeline run.

---

### 2.3 MEDIUM — `_build_ctx()` creates new object per render

**File:** `src/app.py:262-269`

```python
def _build_ctx() -> PageContext:
    return PageContext(...)  # new instance every call
```

**Fix:** Cache ctx in session_state:

```python
def _build_ctx() -> PageContext:
    if "ctx" not in st.session_state:
        st.session_state.ctx = PageContext(
            st=st, repo=repo, session_state=st.session_state,
            pipeline_thread_target=_pipeline_thread_target,
            predict_only_thread_target=_predict_only_thread_target,
        )
    return st.session_state.ctx
```

---

## 3. Caching Opportunities

### 3.1 HIGH — `load_config()` called per symbol in ingestion hot path

**File:** `src/ingestion/pipeline.py:194`

```python
# CURRENT: Called inside _upsert_fundamentals() — per stock (500+ times)
def _upsert_fundamentals(fetcher, stock, force=False, ...):
    config = load_config()
    refresh_days = config.get("scheduler", {}).get("overview_refresh_days", 7)
```

Although `load_config()` uses mtime-based cache (`config.py:24`), `stat().st_mtime` is called per invocation.

**Fix:** Pass config from the caller:

```python
# In run_daily_pipeline():
cfg = load_config()  # ONCE at pipeline start
refresh_days = cfg.get("scheduler", {}).get("overview_refresh_days", 7)

# Refactor signature — pass refresh_days instead of loading inside
def _upsert_fundamentals(fetcher, stock, force=False,
                         indicator_last_updated=None,
                         refresh_days=7):
    ...  # Use passed refresh_days, no internal load_config()
```

**Expected impact:** ~500 `stat()` syscalls → 0 per pipeline run.

---

### 3.2 HIGH — `_last_trading_date()` called 3× per stock in news path

**File:** `src/ingestion/pipeline.py:354-409`

```python
# _fetch_stock_news() calls _last_trading_date() (line 371)
# _fetch_stock_news_av() calls _last_trading_date() (line 402)
# Each call hits pandas_market_calendars for NYSE schedule parsing
```

**Fix:** Add `@lru_cache(maxsize=1)` — one-line fix:

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def _last_trading_date() -> date:
    ...  # existing implementation
```

Also compute once in `run_daily_pipeline()` and pass downstream to avoid repeated cache lookups.

**Expected impact:** N×3 calls → 1 call per pipeline run. For 500 stocks → ~1500 redundant calendar parses eliminated.

---

### 3.3 MEDIUM — Duplicate `@st.cache_data` wrappers across UI pages

**File:** `src/ui/pages/stock_lookup.py:33-36` and `src/ui/pages/stock_technical.py:20-23`

Two pages define identical cache wrappers around `StockRepository().get_prices()`. Same for `_cached_find_stock` / `_cached_find_stock_ta`.

**Fix:** Extract to shared module:

```python
# New file: src/ui/cached_repo.py
import streamlit as st
from datetime import date
from repository import StockRepository

@st.cache_data(ttl=60, show_spinner=False)
def cached_get_prices(stock_id: int, start_str: str, end_str: str):
    return StockRepository().get_prices(
        stock_id, date.fromisoformat(start_str), date.fromisoformat(end_str)
    )

@st.cache_data(ttl=300, show_spinner=False)
def cached_find_stock(symbol: str):
    stock = StockRepository().find_stock(symbol)
    if stock is None:
        return None
    return {"id": stock.id, "symbol": stock.symbol, "name": stock.name,
            "exchange": stock.exchange, "sector": stock.sector,
            "industry": stock.industry, "is_active": stock.is_active}
```

---

## 4. Memory Leaks

### 4.1 HIGH — Log handler left on root logger after pipeline thread crash

**File:** `src/app.py:81-95, 129-150`

```python
def _pipeline_thread_target(cfg_overrides, log_queue):
    handler = _QueueHandler(log_queue)
    root = logging.getLogger()
    root.addHandler(handler)  # ADDED to root before try block
    try:
        ... pipeline work ...
    finally:
        root.removeHandler(handler)
```

If thread is killed between `addHandler` and `try`, handler stays on root forever. Every log message thereafter filters through it.

**Fix:** Use child logger instead of mutating root:

```python
def _pipeline_thread_target(cfg_overrides, log_queue):
    handler = _QueueHandler(log_queue)
    pl = logging.getLogger("pipeline.thread")
    pl.addHandler(handler)
    pl.propagate = False  # Don't double-log to root
    try:
        ... pipeline work ...
    finally:
        try:
            pl.removeHandler(handler)
        except Exception:
            pass
```

**Expected impact:** No handler accumulation across repeated pipeline runs.

---

### 4.2 MEDIUM — `ml_log_lines` deque may lose `maxlen` across Streamlit serialization

**File:** `src/ui/pages/ml_pipeline.py:365, 429`

```python
# Line 365: Sets deque with maxlen=1000
ctx.session_state.ml_log_lines = deque(maxlen=1000)

# Line 429: Appends — but if serialization converts deque → list,
# maxlen is lost and list grows unbounded
ctx.session_state.ml_log_lines.append(str(msg))
```

**Fix:** Enforce cap explicitly on append:

```python
items = ctx.session_state.ml_log_lines
items.append(str(msg))
if len(items) > 1000:
    ctx.session_state.ml_log_lines = (
        items if hasattr(items, 'maxlen')
        else items[-1000:]
    )
```

---

### 4.3 LOW — `os.environ` API key injection never cleaned up

**File:** `src/ingestion/pipeline.py:53-61`, `src/pipeline/backends/fast_evaluators.py:72-90`

```python
os.environ["GOOGLE_API_KEY"] = _common["google_api_key"]
```

Keys persist for process lifetime. By design (TradingAgents reads from `os.environ`). Not a memory leak — global mutable state. Document the expectation.

---

## 5. Redundant Computations

### 5.1 HIGH — `pd.DataFrame` built via dict-per-row list comprehension

**File:** `src/repository.py:67-78` (`get_prices`), `src/repository.py:100-106` (`get_tech_indicators`)

```python
# CURRENT: Per-row dict allocation → list → DataFrame constructor
return self._with_session(lambda s: pd.DataFrame([{
    "date": r.date, "open": r.open, ...
} for r in s.query(DailyPrice).filter(...).all()]))
```

For 5 years of daily data (~1250 rows), this creates 1250 dicts + a list, then `pd.DataFrame()` re-parses.

**Fix:** Use `pd.read_sql()` — C-optimized:

```python
def get_prices(self, stock_id: int, start: date, end: date) -> pd.DataFrame:
    def _query(s):
        return pd.read_sql(
            text("SELECT date, open, high, low, close, adj_close, volume "
                 "FROM daily_prices WHERE stock_id = :sid "
                 "AND date >= :start AND date <= :end ORDER BY date"),
            s.get_bind(),
            params={"sid": stock_id, "start": start, "end": end},
        )
    return self._with_session(_query)
```

**Expected impact:** ~3-5x faster DataFrame construction. `pd.read_sql` uses numpy/C-level parsing vs Python dict-per-row.

---

### 5.2 MEDIUM — `load_config()` at module level AND function level in same file

**File:** `src/ingestion/pipeline.py`

```python
# Line 51: Module-level
_cfg = load_config()
# Line 194: Function-level (inside _upsert_fundamentals)
config = load_config()
```

Module-level `_cfg` used for API key injection only. Function-level in `_upsert_fundamentals` is redundant.

**Fix:** See 3.1 — pass `refresh_days` to `_upsert_fundamentals` instead of re-loading config.

---

### 5.3 MEDIUM — Column name sniffing repeated on every UI render

**File:** `src/ui/pages/ml_pipeline.py:78-83`

```python
s_col = next((c for c in ["sector", "gsector"] if c in fdf.columns), None)
t_col = next((c for c in ["tic", "ticker"] if c in fdf.columns), None)
```

**Fix:** Normalize column names once at load time in `_load_ml_results()`:

```python
RENAME_MAP = {"tic": "ticker", "gsector": "sector"}
df = df.rename(columns={k: v for k, v in RENAME_MAP.items() if k in df.columns})
```

Then downstream code uses fixed column names: `df["ticker"]`, `df["sector"]`.

---

### 5.4 LOW — `_abbr()` helper redefined inside render function

**File:** `src/ui/pages/stock_detail.py:20-35`

```python
def render(ctx, symbol):
    def _abbr(v):  # Redefined every render call
        ...
```

**Fix:** Move to module level. No closure needed.

---

## 6. Additional Findings

### 6.1 SECURITY — `joblib.load()` without model validation

**File:** `src/finrl_runner.py:149, 359`

```python
artifact = joblib.load(mp)  # Arbitrary code execution via pickle deserialization
```

**Fix:** Hash-verify model files before loading, or migrate to `safetensors`/`onnx`.

---

### 6.2 CONFIG — `MAX_WORKERS` hardcoded

**File:** `src/ingestion/pipeline.py:25`

```python
MAX_WORKERS = 5
```

**Fix:**

```python
import os
MAX_WORKERS = max(2, min(8, (os.cpu_count() or 4) + 2))
```

---

## Summary Table

| # | Category | Severity | File | Fix |
|---|----------|----------|------|-----|
| 1.1 | N+1 Query | **CRITICAL** | `app.py:183-198` | Batch price fetch in one query |
| 1.2 | N+1 Query | HIGH | `repository.py:191-196` | Single COUNT with CASE WHEN |
| 1.3 | N+1 Query | MEDIUM | `pipeline.py:85-103` | Combine MIN/MAX into one query |
| 2.1 | Re-render | HIGH | `app.py` | Add `@st.fragment` boundaries |
| 2.2 | Re-render | HIGH | `ml_pipeline.py:440` | `st.fragment(run_every=2)` for logs |
| 2.3 | Re-render | MEDIUM | `app.py:262` | Cache PageContext in session_state |
| 3.1 | Caching | HIGH | `pipeline.py:194` | Pass config to _upsert_fundamentals |
| 3.2 | Caching | HIGH | `pipeline.py:354-409` | `@lru_cache` on _last_trading_date |
| 3.3 | Caching | MEDIUM | `stock_lookup.py`, `stock_technical.py` | Extract shared cached repo module |
| 4.1 | Memory Leak | HIGH | `app.py:81-150` | Use child logger instead of root |
| 4.2 | Memory Leak | MEDIUM | `ml_pipeline.py:365` | Enforce maxlen on log deque |
| 5.1 | Redundant | HIGH | `repository.py:67-78` | Use `pd.read_sql()` |
| 5.2 | Redundant | MEDIUM | `pipeline.py:51,194` | Remove duplicate load_config() |
| 5.3 | Redundant | MEDIUM | `ml_pipeline.py:78-83` | Normalize column names at load |
| 5.4 | Redundant | LOW | `stock_detail.py:20` | Move _abbr() to module level |
| 6.1 | Security | HIGH | `finrl_runner.py:149` | Validate model files before load |
| 6.2 | Config | MEDIUM | `pipeline.py:25` | Derive MAX_WORKERS from cpu_count |

**Total:** 18 findings. 1 CRITICAL, 8 HIGH, 8 MEDIUM, 1 LOW.

## Quick Wins (implement first)

1. **Batch price fetch** (1.1) — biggest impact, ~100x DB load reduction
2. **`@lru_cache` on `_last_trading_date()`** (3.2) — one-line decorator
3. **`pd.read_sql()` in `get_prices`** (5.1) — 3-5x DataFrame construction speedup
4. **Pass config to `_upsert_fundamentals`** (3.1) — eliminate 500 `stat()` calls
5. **Child logger instead of root** (4.1) — prevent handler leak across pipeline runs
