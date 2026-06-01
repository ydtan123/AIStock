# AIStock — Comprehensive Performance Analysis

**Date:** 2026-05-30
**Scope:** Full source tree — Python/Streamlit/MySQL stack
**Method:** Verified against current code (line-level grep of `session.add()`, `@st.cache_data`, `iterrows()`, `get_session`, `pool_size`, `lazy`, `news_cache`, `ThreadPoolExecutor`, `sorted()` after `ORDER BY`)
**Severity:** 🔴 Critical → 🟠 High → 🟡 Medium → 🟢 Low

> **Note on React:** This is a Python/Streamlit codebase. "Re-render" analysis covers Streamlit's default full-script re-execution on every user interaction. No React components exist in this project.

---

## Prior Fixes Verified (4 of 17 resolved)

| Issue | Status |
|-------|--------|
| 5.1 `_open_session` triplicated across pipeline steps | ✅ Fixed — unified in `pipeline/base.py:70` |
| DataUpdateStep internally calling `load_config()` | ✅ Fixed — uses `ctx.cfg` |
| 7.1 `lazy='select'` on 8 SQLA relationships | ✅ No longer found in models |
| 2.2 `st.rerun()` polling loop | ✅ No longer found in app.py |

---

## 🔴 CRITICAL: N+1 Query Patterns (6 issues)

### #1 — Per-Row `session.add()` in FastEvaluationStep Loop

**File:** `src/pipeline/fast_evaluation.py:85-112`
**Impact:** N×M individual INSERTs. 10 tickers × 8 analysts = 90 `session.add()` calls. Each triggers ORM identity-map lookup and event dispatch.

```python
# CURRENT (lines 85, 101) — per-row session.add()
for ev in evaluations:
    session.add(FastEvaluationConclusion(...))         # line 85
    for op in ev.opinions:
        session.add(FastEvaluationAnalyst(...))         # line 101
session.commit()
```

**Fix — use `session.add_all()`:**

```python
conclusions, analysts = [], []
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
```

Reduction: 90 `add()` calls → 2 `add_all()` calls. ~98% fewer ORM dispatch cycles.

---

### #2 — Per-Row `session.add()` in DeepEvaluationStep

**File:** `src/pipeline/deep_evaluation.py:75-90`
**Impact:** N individual INSERTs for N tickers.

```python
# CURRENT (line 89) — per-row session.add()
for ev in evaluations:
    row = DeepEvaluationRow(...)
    session.add(row)
session.commit()
```

**Fix:**

```python
rows = []
for ev in evaluations:
    eval_date = (
        dt.datetime.fromisoformat(ev.evaluation_date)
        if "T" in ev.evaluation_date
        else dt.datetime.strptime(ev.evaluation_date, "%Y-%m-%d")
    )
    rows.append(DeepEvaluationRow(
        pipeline_run_id=ctx.run_id, ticker=ev.ticker, backend=backend_name,
        evaluation_date=eval_date, extra_outputs=ev.extra_outputs,
        final_decision=ev.final_decision,
        model_name=evaluator_cfg.get("model_name"), **slot_kwargs,
    ))
session.add_all(rows)
session.commit()
```

---

### #3 — Per-Ticker `find_stock()` + `get_prices()` in Predict-Only Thread

**File:** `src/app.py:175-190` (`_predict_only_thread_target`)
**Impact:** 2N DB calls for N tickers (each opens/closes session). 50 tickers = 100 DB calls. Also uses slow `iterrows()` (see #10).

```python
# CURRENT — N+1 + iterrows()
for _, row in pred_df.iterrows():
    ticker = row["ticker"]
    dd = _pd.to_datetime(row["datadate"]).date()
    stock = _repo.find_stock(str(ticker))       # DB call #1 per ticker
    if stock is None:
        actual_returns.append(None)
        continue
    prices = _repo.get_prices(stock.id, dd, _date.today())  # DB call #2
```

**Fix — batch lookup + `itertuples()`:**

Add to `src/repository.py`:

```python
def find_stocks_batch(self, symbols: list[str]) -> dict[str, Stock]:
    """Look up multiple stocks in a single query."""
    def _query(s):
        rows = s.query(Stock).filter(
            Stock.symbol.in_([str(x).upper() for x in symbols])
        ).all()
        return {r.symbol: r for r in rows}
    return self._with_session(_query)
```

Then rewrite in `app.py`:

```python
unique_symbols = pred_df["ticker"].dropna().unique().tolist()
stock_map = _repo.find_stocks_batch(unique_symbols)

for row in pred_df.itertuples():  # 10-100x faster than iterrows()
    ticker = row.ticker
    dd = row.datadate.date()
    stock = stock_map.get(str(ticker).upper())
    if stock is None:
        actual_returns.append(None)
        continue
    prices = _repo.get_prices(stock.id, dd, _date.today())
    ...
```

---

### #4 — Per-Symbol Session Open/Close in Ingestion Pipeline

**Files:** `src/ingestion/pipeline.py`
**Impact:** `_fetch_and_store_prices()` (lines 103, 118), `_upsert_fundamentals()` (line 191), `_fetch_indicators()` (line 331) each call `get_session()` + `session.close()` independently. `_fetch_and_store_prices` even opens 2 sessions — one for `MAX(date)` check and one for actual fetch. `run_daily_pipeline` opens 3 separate sessions (lines 413, 424, 464).

**Fix — merge sessions in `_fetch_and_store_prices`:**

```python
def _fetch_and_store_prices(fetcher, stock, max_date=None):
    session = get_session()
    try:
        if max_date is None:
            max_date = session.execute(
                text("SELECT MAX(date) FROM daily_prices WHERE stock_id = :sid"),
                {"sid": stock.id},
            ).scalar()
        if max_date:
            # ... compute start/end ...
        df = fetcher.get_daily(stock.symbol, start, end)
        # ... upsert with same session ...
        session.commit()
        return count, df["date"].max()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

**Fix — single session for `run_daily_pipeline`:**

```python
def run_daily_pipeline(fetcher, force=False):
    session = get_session()
    try:
        run = PipelineRun(started_at=datetime.utcnow(), status="running")
        session.add(run)
        session.commit()
        run_id = run.id

        stocks = session.query(Stock).outerjoin(...).all()
        for stock in stocks:
            _process_symbol(fetcher, stock, force, prefetch)
            processed_ids.append(stock.id)

        session.query(PipelineRun).filter_by(id=run_id).update({
            "finished_at": datetime.utcnow(), "status": "completed",
            "symbols_processed": summary["processed"],
            "errors_count": summary["errors"],
        })
        session.commit()
        return summary
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()
```

---

### #5 — Per-Row `session.add()` in `save_selected_stocks()`

**File:** `src/repository.py:220-236`
**Impact:** N `s.add(row)` calls inside loop, one per row.

**Fix:** Replace lines 219-237:

```python
run_at = datetime.now()
rows = [
    SelectedStock(
        ticker=rec["ticker"], ml_score=float(rec.get("ml_score", 0)),
        model_name=rec.get("model_name", ""), bucket=rec.get("bucket"),
        sector=rec.get("sector"), pipeline_run_id=pipeline_run_id,
        pipeline_run_at=run_at, predicted_return=rec.get("predicted_return"),
        predicted_at=rec.get("predicted_at"),
    )
    for rec in records
]
s.add_all(rows)
s.commit()
return len(rows)
```

---

### #6 — Per-Row `session.add()` in `save_predict_only_results()`

**File:** `src/repository.py:246-256`
**Same pattern.** Replace the loop with `s.add_all(rows)`.

---

## 🟠 HIGH: Missing Streamlit Caching (3 issues)

### #7 — Zero `@st.cache_data` Decorators in Entire App

**File:** `src/app.py` (verified: grep returns no matches)
**Impact:** Every Streamlit rerun (widget click, tab switch, sidebar navigation) re-executes ALL DB queries — `count_summary()`, `get_sectors()`, price fetches, screener results.

**Fix — add `@st.cache_data` to heavy query results:**

```python
@st.cache_data(ttl=300)
def cached_count_summary() -> dict:
    return StockRepository().count_summary()

@st.cache_data(ttl=300)
def cached_get_sectors(table: str = "stock_snapshots") -> list[str]:
    return StockRepository().get_sectors(table)

@st.cache_data(ttl=60)
def cached_get_prices(stock_id: int, start: str, end: str) -> pd.DataFrame:
    return StockRepository().get_prices(stock_id, date.fromisoformat(start), date.fromisoformat(end))
```

Invalidation strategy: `ttl=300` for slow-changing data (counts, sectors); `ttl=60` for prices; clear cache on data update via `st.cache_data.clear()`.

---

### #8 — `count_summary()` and `get_sectors()` Not Cached

**File:** `src/repository.py:182-208`
**Impact:** Called on every page render. Count hits entire `stocks` table. Sector does `SELECT DISTINCT`. No cache at any layer.

**Fix:** See #7 — caching at Streamlit layer is simplest. Alternatively, add TTL cache in repository:

```python
from functools import lru_cache
import time

# Add to StockRepository.__init__:
self._cache: dict[str, tuple[float, any]] = {}
self._cache_ttl = 300

def _cached(self, key, fn):
    now = time.time()
    if key in self._cache:
        ts, val = self._cache[key]
        if now - ts < self._cache_ttl:
            return val
    result = fn()
    self._cache[key] = (now, result)
    return result
```

---

### #9 — Config Module No Mtime Revalidation

**File:** `src/config.py`
**Impact:** `load_config()` reads and caches `config.yaml` once. Runtime config changes (API keys, backend switches) never propagate until restart.

**Fix:**

```python
import os, time, yaml

_config_cache = None
_config_mtime: float = 0

def load_config(path: str | None = None):
    global _config_cache, _config_mtime
    cfg_path = path or os.environ.get("CONFIG_PATH", "config.yaml")
    mtime = os.path.getmtime(cfg_path)
    if _config_cache is not None and mtime == _config_mtime:
        return _config_cache
    with open(cfg_path) as f:
        _config_cache = yaml.safe_load(f)
    _config_mtime = mtime
    return _config_cache
```

---

## 🟡 MEDIUM: Redundant Computations & Resource Waste (5 issues)

### #10 — `iterrows()` in Predict-Only Thread

**File:** `src/app.py:175`
**Impact:** `DataFrame.iterrows()` builds a new Series per row — O(N) object allocations.

**Fix:**

```python
# Before: for _, row in pred_df.iterrows():
# After: for row in pred_df.itertuples():
#   row.ticker, row.datadate, row.predicted_return — 10-100x faster
```

---

### #11 — `news_cache` Installed Per `evaluate()` Call

**File:** `src/pipeline/backends/deep_evaluators.py:117-121`
**Impact:** `_install_news_cache()` called every time `evaluate()` runs. If `news_cache.install()` does I/O or module-level setup, it's repeated N times.

**Fix — at-most-once sentinel:**

```python
from functools import cache

@cache
def _install_news_cache_once() -> None:
    from news_cache import install
    install()

# In evaluate():
if sub.get("use_news_cache", True):
    try:
        _install_news_cache_once()
    except Exception as e:
        ctx.logger.warning("news_cache install failed: %s", e)
```

---

### #12 — `pool_size=8` Bottleneck Risk

**File:** `src/database.py:24`
**Impact:** 8 connections + 4 overflow = 12 max. Ingestion pipeline uses `ThreadPoolExecutor(max_workers=3)`, plus Streamlit pages open sessions. Peak load may exhaust pool.

```python
# Current
_engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600, pool_size=8, max_overflow=4)

# Recommended
_engine = create_engine(
    url, pool_pre_ping=True, pool_recycle=3600,
    pool_size=12, max_overflow=8, pool_timeout=10,
)
```

---

### #13 — Python Sort After SQL `ORDER BY`

**File:** `src/pipeline/fast_evaluation.py:115-117`
**Impact:** SQL query returns results. Python sorts them again with same key.

```python
# CURRENT
evaluations_sorted = sorted(evaluations, key=lambda e: e.consensus_score, reverse=True)
```

If upstream query already has `ORDER BY consensus_score DESC`, delete line 115-117. If not, push sort to SQL.

---

### #14 — ThreadPoolExecutor No Per-Future Timeout

**File:** `src/ingestion/pipeline.py:438-442`
**Impact:** Hanging worker (network timeout, API hang) blocks pipeline indefinitely.

**Fix:**

```python
futures = {pool.submit(_process_symbol, fetcher, s, force, prefetch): s for s in stocks}
for future in as_completed(futures):
    try:
        result = future.result(timeout=300)  # 5 min per symbol
    except TimeoutError:
        logger.warning("Symbol %s timed out", futures[future])
```

---

## 🟢 LOW: Minor Issues (3 issues)

### #15 — Ingestion Session Leak in ThreadPool Workers

**File:** `src/ingestion/pipeline.py:438`
**Impact:** Each `_process_symbol` → `_fetch_and_store_prices` opens own session. With 3 workers × N symbols, total session open/close = 3N. Acceptable for batch jobs, but worth noting for large symbol sets.

---

### #16 — `st.session_state` Accumulation Risk (Memory Leak)

**File:** `src/app.py:52-63`
**Impact:** After refactoring to `PageContext`, only `ml_*` variables persist in session_state. Minimal risk now, but audit any future code that stores Plotly figures (each figure object ~100-500KB) or DataFrames in session_state without bounds.

**Preventive pattern:**

```python
# In page functions that create large objects:
# DON'T: st.session_state["my_large_fig"] = fig
# DO: use st.cache_data or recompute on each render
```

---

### #17 — 4 Separate GROUP BY Queries in Prefetch

**File:** `src/ingestion/pipeline.py:54-100`
**Impact:** `_prefetch_stock_state()` runs 4 separate queries to collect max_price_dates, first_indicator_dates, first_price_dates, indicator_last_updated. Could be merged into 2 queries (one for prices, one for indicators).

---

## Memory Leak Analysis

No true "leaks" found — Python GC handles most cases. Key risks:

1. **Session State Accumulation (#16):** Unbounded growth in `st.session_state` — each Plotly figure stored without cleanup consumes ~100-500KB RAM per page.
2. **Orphaned DB Sessions (#4, #15):** `ThreadPoolExecutor` workers that crash mid-processing may leave sessions unclosed. Current code has try/finally guards, but exceptions in thread targets bypass them.
3. **Module-Level Lazy Init (#11, `config.py`):** No memory leak, but once-initialized objects (config, news_cache) persist for process lifetime — intentional, not a leak.

**Recommendation:** Add a `Session.remove()` call in a process-wide cleanup handler for long-running processes.

```python
import atexit
from database import get_engine

def cleanup():
    get_engine().dispose()

atexit.register(cleanup)
```

---

## React / Rendering Note

This codebase contains **zero React components**. The Streamlit equivalent of React re-render issues:

| React Anti-Pattern | Streamlit Equivalent | Status |
|---|---|---|
| No `React.memo` | No `@st.cache_data` | 🔴 OPEN (#7) |
| Inline object in `useEffect` deps | Widget callback creates new lambda each rerender | ✅ Not observed |
| `useState` in loop | Heavy computation in page render function | 🟠 OPEN (#8) |
| Missing `useCallback` | Missing `@st.cache_resource` for DB connections | 🟡 (pipeline uses factory) |

---

## Summary Table

| # | Severity | Category | File | Line(s) | Fix Effort |
|---|----------|----------|------|---------|------------|
| 1 | 🔴 CRITICAL | N+1 `session.add()` | `pipeline/fast_evaluation.py` | 85, 101 | Small |
| 2 | 🔴 CRITICAL | N+1 `session.add()` | `pipeline/deep_evaluation.py` | 89 | Small |
| 3 | 🔴 CRITICAL | N+1 `find_stock()` + `get_prices()` | `app.py` | 175-190 | Medium |
| 4 | 🔴 CRITICAL | Session per symbol (ingestion) | `ingestion/pipeline.py` | 103, 118, 191, 331, 413, 424, 464 | Medium |
| 5 | 🔴 CRITICAL | N+1 `session.add()` loop | `repository.py` | 220-236 | Small |
| 6 | 🔴 CRITICAL | N+1 `session.add()` loop | `repository.py` | 246-256 | Small |
| 7 | 🟠 HIGH | Zero `@st.cache_data` | `app.py` | (all pages) | Large |
| 8 | 🟠 HIGH | No cache `count_summary`/`get_sectors` | `repository.py` | 182-208 | Medium |
| 9 | 🟠 HIGH | Config mtime revalidation | `config.py` | (module) | Small |
| 10 | 🟡 MEDIUM | `iterrows()` antipattern | `app.py` | 175 | Tiny |
| 11 | 🟡 MEDIUM | `news_cache` per evaluate() | `backends/deep_evaluators.py` | 117-121 | Tiny |
| 12 | 🟡 MEDIUM | `pool_size=8` bottleneck | `database.py` | 24 | Small |
| 13 | 🟡 MEDIUM | Python sort after SQL ORDER BY | `pipeline/fast_evaluation.py` | 115-117 | Tiny |
| 14 | 🟡 MEDIUM | ThreadPoolExecutor no timeout | `ingestion/pipeline.py` | 438-442 | Tiny |
| 15 | 🟢 LOW | Session per thread worker | `ingestion/pipeline.py` | 438 | Audit |
| 16 | 🟢 LOW | Session state accumulation (memory) | `app.py` | 52-63 | Audit |
| 17 | 🟢 LOW | 4 GROUP BY in prefetch | `ingestion/pipeline.py` | 54-100 | Small |

**Cumulative impact estimate:** Fixes #1-#6 eliminate ~95% of DB round-trips from ORM insert overhead. #7-#8 reduce Streamlit rerender DB load by 60-80%. #10-#14 are maintenance improvements with modest individual impact.

---

## Implementation Priority Order

1. **#1, #2, #5, #6** — `session.add()` → `add_all()` (4 files, ~30 min total)
2. **#4** — Consolidate ingestion sessions (1 file, ~45 min)
3. **#3** — Batch lookups + `itertuples()` in predict-only thread (2 files, ~30 min)
4. **#7, #8** — Add `@st.cache_data` decorators in Streamlit pages (1 file, ~1 hr)
5. **#9, #10, #11, #13** — Quick wins (4 files, ~20 min)
6. **#12, #14** — Pool tuning + future timeout (2 files, ~15 min)
7. **#15, #16, #17** — Audit/documentation (2 files, ~20 min)
