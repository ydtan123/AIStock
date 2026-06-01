# AIStock Performance Analysis — v12

**Date:** 2026-05-30
**Scope:** Full codebase (`src/` — 45+ `.py` files)
**Methodology:** Static analysis tracing query patterns, session lifecycle, caching, memory allocation, thread-pool behavior.
**Changes from v11:** Verified 5 fixes applied; found 6 new issues; 10 still outstanding.

---

## TL;DR

| Severity | Count | Category |
|----------|-------|----------|
| ✅ Fixed (v11) | 5 | `get_prices_batch`, double COUNT, page-level cache, deque in ml_pipeline, cached_repo.py |
| 🔴 Critical | 3 | DB session-per-thread pool exhaustion; no cache_resource singleton for repo; per-symbol news HTTP |
| 🟠 High | 5 | Unbounded log buffer in app.py; dual-iteration eval loops; 3 sequential sessions; per-symbol upsert session; per-thread indicator compute |
| 🟡 Medium | 6 | Median-impute loop; sort-key dict; os.environ leak; redundant utcnow; JSON round-trip; subprocess timeout |
| 🟢 Low | 2 | Config hot-reload; ThreadPoolExecutor (correct) |

---

## ✅ Confirmed Fixed (from v11)

### F1. `get_prices_batch()` — Removes N+1 Price Queries
**File:** `src/repository.py:78`, `src/app.py:188`
Batch method exists. 20 DB round-trips → 1.

### F2. Single `COUNT(*)` in `count_summary()`
**File:** `src/repository.py:210`
```sql
SELECT COUNT(*), COALESCE(SUM(CASE WHEN is_active THEN 1 ELSE 0 END), 0) FROM stocks
```

### F3. `@st.cache_data` on UI Pages
**Files:** `overview.py` (ttl=60), `job_history.py` (ttl=300), `portfolio.py` (ttl=300), `stock_lookup.py` (ttl=60), `stock_manager.py` (ttl=60+300), `stock_screener.py` (ttl=300), `stock_technical.py` (ttl=60), `ml_pipeline.py` (ttl=3600). 13 total cached functions.

### F4. `deque(maxlen=1000)` in `ml_pipeline.py`
**File:** `src/ui/pages/ml_pipeline.py:365,394`
Both `ml_log_lines` initializations use bounded deque.

### F5. `cached_repo.py` — Shared Cache Module
**File:** `src/ui/cached_repo.py`
`cached_find_stock()` and `cached_get_prices()` wrappers.

---

## 🔴 Critical

### C1. DB Session-Per-Thread Exhaustion in ThreadPoolExecutor

**File:** `src/ingestion/pipeline.py:539` → `_process_symbol()` → `_upsert_fundamentals()`

**Problem:** `ThreadPoolExecutor(max_workers=MAX_WORKERS)` submits `_process_symbol()` N times. `_upsert_fundamentals()` creates its own `session = get_session()` per invocation. With `pool_size=15` and N=100, every thread checks out a connection that blocks while waiting for HTTP (API timeouts up to 30s). Workers waiting on I/O hold DB connections idle.

**Impact:** Pipeline stall when pool exhausted. MySQL connection timeout risk.

```python
# _upsert_fundamentals (pipeline.py:590) — creates session per symbol:
session = get_session()          # checks out connection for THIS thread
existing = session.query(...)    # holds connection during API fetch
# ... HTTP overhead (2-5s per stock) while holding DB connection
session.commit()
session.close()
```

**Fix — thread-local session or lower max_workers:**

```python
# Option A: Thread-local session
import threading

_thread_local = threading.local()

def _get_thread_session():
    if not hasattr(_thread_local, 'session'):
        _thread_local.session = get_session()
    return _thread_local.session

# Option B: Cap workers below pool_size
MAX_WORKERS = max(1, min(10, pool_size - 5))  # leave headroom
```

---

### C2. 12× `StockRepository()` Construction — No Singleton

**Files:** `app.py:49,166`, `job_history.py:10`, `ml_pipeline.py:89`, `overview.py:9`, `portfolio.py:12`, `stock_detail.py:11`, `stock_lookup.py:17`, `stock_manager.py:13,19,36`, `stock_screener.py:26,32`, `stock_technical.py:16`, `cached_repo.py:10,20`

**Problem:** Every `@st.cache_data` wrapper and page function creates `StockRepository()`. Each resolves `get_engine()` (cheap, module-level singleton) but creates redundant Python object per call site.

**Fix — `@st.cache_resource` singleton:**

```python
# src/ui/cached_repo.py — add:
@st.cache_resource
def _get_repo() -> StockRepository:
    return StockRepository()

# Update all call sites:
@st.cache_data(ttl=300, show_spinner=False)
def cached_find_stock(symbol: str) -> dict | None:
    stock = _get_repo().find_stock(symbol)  # reuse singleton
    # ...
```

Streamlit's `@st.cache_resource` survives rerenders; `@st.cache_data` re-executes after TTL.

---

### C3. Per-Symbol News HTTP — No Batch Gap Detection

**File:** `src/ingestion/pipeline.py:443` → `_fetch_stock_news()`

**Problem:** Called for every symbol where `force or prices_inserted > 0`. Each call checks DB cache, then fetches from Alpha Vantage / TradingAgents per symbol. No batch pre-check.

**Impact:** 100 symbols with new prices = 100 sequential DB cache checks + HTTP API calls.

**Fix — `_prefetch_news_gaps()`:**

```python
def _prefetch_news_gaps(symbols: list[str], session) -> set[str]:
    """Single query finds symbols with stale/missing news."""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=7)
    rows = session.execute(
        text("SELECT symbol, MAX(fetched_at) FROM stock_news "
             "WHERE symbol IN :syms GROUP BY symbol"),
        {"syms": tuple(symbols)}
    ).fetchall()
    fresh = {r[0] for r in rows if r[1] and r[1] >= cutoff}
    return set(symbols) - fresh

# Caller: only fetch for stale symbols
stale = _prefetch_news_gaps([s.symbol for s in changed], session)
for symbol in stale:
    _fetch_stock_news(symbol, fetcher=fetcher)
```

---

## 🟠 High

### H1. `ml_log_lines` Still Unbounded in `app.py`

**File:** `src/app.py:54-55`

```python
if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = []  # still unbounded list
```

`ml_pipeline.py` already uses `deque(maxlen=1000)`. `app.py` was missed.

**Fix:**
```python
from collections import deque

if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = deque(maxlen=1000)
```

---

### H2. Dual-Iteration Evaluation Loops

**Files:** `src/pipeline/fast_evaluation.py:38` + `:148`, `src/pipeline/deep_evaluation.py:78` + `:100`

**Problem:** Both pipeline steps iterate `for ev in evaluations` twice — report markdown + DB inserts. `_count_by_opinion()` recomputed on each pass.

```python
# fast_evaluation.py — first pass (report):
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)  # compute
    # ... write markdown

# second pass (DB write):
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)  # recompute
    conclusions.append(FastEvaluationConclusion(...))
```

**Fix — single pass, reuse counts:**

```python
results = []
conclusions = []
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)
    total = pos + neg + neu
    conclusions.append(FastEvaluationConclusion(
        pipeline_run_id=ctx.run_id, ticker=ev.ticker,
        positive_count=pos, negative_count=neg,
        neutral_count=neu, consensus_score=ev.consensus_score,
        # ...
    ))
    results.append({"ev": ev, "pos": pos, "neg": neg, "neu": neu, "total": total})

# Report from results dict
for r in results:
    lines.append(_format_line(r))

# DB insert from pre-built list
session.bulk_save_objects(conclusions)
```

---

### H3. Three Sequential DB Sessions in `run_daily_pipeline()`

**File:** `src/ingestion/pipeline.py:491-585`

```python
# Session 1 — create pipeline run
session = get_session(); session.add(run); session.commit(); session.close()

# Session 2 — prefetch stale stocks
session = get_session(); session.query(Stock)...; session.close()

# Session 3 — update run status
session = get_session(); session.query(PipelineRun)...; session.commit(); session.close()
```

**Fix — single session for metadata:**
```python
session = get_session()
try:
    session.add(run)
    session.flush()  # get run.id without commit
    prefetch = _prefetch_stock_dates(session, symbols)
    # ... run ThreadPoolExecutor ...
    session.query(PipelineRun).filter_by(id=run.id).update({
        "finished_at": datetime.utcnow(), "status": "completed"
    })
    session.commit()
finally:
    session.close()
```

---

### H4. `_upsert_fundamentals` — Per-Symbol Session

**File:** `src/ingestion/pipeline.py:573-623`

**Problem:** Creates `session = get_session()` per symbol inside ThreadPoolExecutor. Also uses individual `session.execute(stmt)` per row instead of bulk insert. Duplicates session lifecycle logic that `repository._with_session()` already handles.

**Fix — accept session parameter:**
```python
def _upsert_fundamentals(session, fetcher, stock, force, indicator_last_updated, refresh_days):
    """Use passed-in session from thread-local or caller."""
    # Same logic, accept session as parameter
    # ... 
```

---

### H5. `compute_indicators()` Called Per-Symbol in Worker

**File:** `src/ingestion/pipeline.py:443` → `_process_symbol()`

**Problem:** Each `_process_symbol` calls `compute_indicators(stock.id, ...)` which opens its own DB session. Runs inside ThreadPoolExecutor — N symbols = N concurrent indicator compute sessions.

**Fix — defer to after worker pool:**
```python
# After all symbols processed:
changed_ids = [sid for sid in processed_ids if sid in symbols_with_new_prices]
for sid in changed_ids:
    compute_indicators(sid, since_date=price_dates[sid])
```

---

## 🟡 Medium

### M1. Median-Impute Loop — Still Per-Column

**File:** `src/ml_bucket_selector.py:100-103`

```python
for col in FEATURE_COLS:              # N columns = N .median() calls
    if df[col].isna().any():
        median = df[col].median()
        df[col] = df[col].fillna(median if pd.notna(median) else 0.0)
```

**Fix (1 pass):**
```python
feature_df = df[FEATURE_COLS]
medians = feature_df.median()
df[FEATURE_COLS] = feature_df.fillna(medians.fillna(0.0))
```

---

### M2. Sort-Key Dict Allocated Per Opinion

**File:** `src/pipeline/fast_evaluation.py:61`

```python
sorted_ops = sorted(ev.opinions, key=lambda o: (
    {"bullish": 0, "bearish": 1, "neutral": 2}.get(o.opinion, 3), -o.confidence))
#   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ new dict per iteration
```

**Fix — module constant:**
```python
_OPINION_ORDER = {"bullish": 0, "bearish": 1, "neutral": 2}

sorted_ops = sorted(ev.opinions, key=lambda o: (_OPINION_ORDER.get(o.opinion, 3), -o.confidence))
```

---

### M3. `os.environ` Permanent Mutation

**File:** `src/pipeline/backends/deep_evaluators.py:71`

```python
for env_var, value in mapping.items():
    if value and not os.environ.get(env_var):
        os.environ[env_var] = value  # permanent global mutation
```

**Fix — context manager:**
```python
from contextlib import contextmanager

@contextmanager
def _temp_env(**kwargs):
    old = {k: os.environ.get(k) for k in kwargs}
    for k, v in kwargs.items():
        if v:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
```

---

### M4. Redundant `datetime.utcnow()` Per Step

**Files:** `src/pipeline/stock_selection.py`, `src/pipeline/fast_evaluation.py`

Multiple `dt.datetime.utcnow()` calls within same `execute()` method. Each returns slightly different time.

**Fix:** Capture once: `now = dt.datetime.utcnow()`, pass to downstream.

---

### M5. Orchestrator Redundant JSON Round-Trip

**File:** `src/pipeline/orchestrator.py:182,197,223`

```python
body = json.loads(f.read_text())           # read + parse
# ... intermediate step ...
json.dumps(body, indent=2, default=str)     # re-serialize same data
```

**Fix:** Keep parsed body in memory. Only serialize at final write step.

---

### M6. Subprocess Timeout Gap in AI-Hedge-Fund Backend

**File:** `src/pipeline/backends/fast_evaluators.py`

**Problem:** Backend spawns subprocess via `external/ai-hedge-fund`. No timeout. If AI inference hangs, pipeline blocks indefinitely.

**Fix:**
```python
result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
```

---

## 🟢 Already Good

- **ThreadPoolExecutor**: 4 instances all use `with` context manager. No leaks.
- **Config caching**: `config.load_config()` uses module-level `_cached_config`.
- **SQL queries**: All parameterized via SQLAlchemy. No f-string SQL injection.
- **Session lifecycle**: `_with_session()` correctly closes in `finally`.
- **Pool config**: `pool_pre_ping=True`, `pool_recycle=3600`, `pool_size=15`, `max_overflow=10`.
- **News cache**: `news_cache.py` DB-backed dedup. Working correctly.
- **Listing cache**: Parquet cache with 6-hour TTL. Efficient.
- **String accumulation**: `"\n".join(lines)` used in reports. O(n).

---

## Summary Matrix

| # | Severity | Pattern | Files | Effort |
|---|----------|---------|-------|--------|
| C1 | 🔴 Critical | Session-per-thread pool exhaustion | `ingestion/pipeline.py` | Medium |
| C2 | 🔴 Critical | 12× StockRepository() no singleton | 12 UI files | Low |
| C3 | 🔴 Critical | Per-symbol news HTTP | `ingestion/pipeline.py` | Medium |
| H1 | 🟠 High | Unbounded ml_log_lines app.py | `app.py:54` | Tiny |
| H2 | 🟠 High | Dual-iteration eval loops | `fast/deep_evaluation.py` | Low |
| H3 | 🟠 High | 3 sequential sessions | `ingestion/pipeline.py` | Low |
| H4 | 🟠 High | Per-symbol upsert session | `ingestion/pipeline.py` | Medium |
| H5 | 🟠 High | Per-thread indicator compute | `ingestion/pipeline.py` | Low |
| M1 | 🟡 Medium | Median-impute loop | `ml_bucket_selector.py` | Tiny |
| M2 | 🟡 Medium | Sort-key dict per eval | `fast_evaluation.py` | Tiny |
| M3 | 🟡 Medium | os.environ mutation | `deep_evaluators.py` | Low |
| M4 | 🟡 Medium | Redundant utcnow() | pipeline steps | Tiny |
| M5 | 🟡 Medium | JSON round-trip | `orchestrator.py` | Low |
| M6 | 🟡 Medium | Subprocess timeout | `fast_evaluators.py` | Tiny |

---

## Action Sequence

### Phase 1 — Tiny Fixes (~30 min)
1. **H1**: `deque(maxlen=1000)` in `app.py:55`
2. **M1**: Vectorize median impute — 2 lines
3. **M2**: Module constant `_OPINION_ORDER` — 3 lines
4. **M4**: Single `utcnow()` per step
5. **M6**: `timeout=300` on subprocess

### Phase 2 — Low Effort (~2h)
6. **C2**: `@st.cache_resource` singleton, update 12 call sites
7. **H2**: Single-pass evaluation loops
8. **H3**: Merge 3 sessions in `run_daily_pipeline()`
9. **H5**: Defer `compute_indicators()` after pool

### Phase 3 — Medium Effort (~4h)
10. **C1**: Thread-local session or pool_size-aware workers
11. **C3**: `_prefetch_news_gaps()` batch query
12. **H4**: Pass session to `_upsert_fundamentals()`
13. **M3**: `_temp_env` context manager
14. **M5**: Eliminate redundant JSON serialize/deserialize

---

## Notes

- **Not React** — Streamlit (Python). "Re-render" = Streamlit widget-induced rerender. No React components exist.
- **No memory leaks**. `ml_log_lines` is a soft leak (unbounded within run). All other resources properly cleaned.
- **DB pool config correct**. Issues are usage patterns, not configuration.
- **5 of 11 v11 issues fixed**. 6 new issues found. 10 remain actionable.
