# AIStock Performance Analysis — v11

**Date:** 2026-05-30
**Scope:** Full codebase (45 `.py` files in `src/`)
**Methodology:** Static analysis — all files traced for query patterns, caching, session lifecycle, memory allocation.

---

## TL;DR

| Severity | Count | Category |
|----------|-------|----------|
| 🔴 Critical | 2 | 9 UI pages have zero Streamlit caching; N+1 `get_prices()` per symbol |
| 🟠 High | 4 | Per-call session lifecycle, unbounded log buffer, repeated repo instantiation, per-symbol news HTTP |
| 🟡 Medium | 5 | Double `COUNT(*)`, median-impute loop, redundant `utcnow()`, sort key per eval, os.environ injection |
| 🟢 Low | 3 | String accumulation (efficient), listing cache stat, ThreadPoolExecutor (correct) |

---

## 🔴 Critical

### 1. Nine UI Pages — Zero Streamlit Cache Decorators

**Files:** `src/app.py` (2200+ lines, 5 sub-tabs under Stock Data), `src/ui/pages/settings.py`, `src/ui/pages/portfolio.py`, `src/ui/pages/strategy_backtest.py`, `src/ui/pages/live_trading.py`, `src/ui/pages/paper_trading.py`, `src/ui/pages/stock_screener.py`, `src/ui/pages/stock_manager.py`, `src/ui/pages/job_history.py`

**Impact:** Every Streamlit rerender (widget click, timer tick, sidebar change) re-executes all DB queries. 9 uncached pages × 1-5 queries each = up to 45 DB queries per interaction cycle. With `pool_size=15`, rapid interactions could exhaust pool under concurrent users.

**Already-cached pages (good):** `overview.py` (`@st.cache_data ttl=60`), `stock_lookup.py` (3 cached functions), `ml_pipeline.py` (2 cached functions with `ttl=3600`)

**Fix — wrap DB queries in `@st.cache_data`:**

```python
# Pattern for screener / manager / job history:
import hashlib, json

@st.cache_data(ttl=300, show_spinner="Loading...")
def _cached_screen(filters_hash: str) -> pd.DataFrame:
    return StockRepository().screen_stocks(...)

# In render():
filters_hash = hashlib.md5(json.dumps(filters, sort_keys=True).encode()).hexdigest()
df = _cached_screen(filters_hash)
```

| TTL | Use case |
|-----|----------|
| 60s | Count summary, job history, active stocks |
| 300s | Screener, stock manager, portfolio |
| 3600s | Settings, backtest results |

**Estimated:** 80-95% DB query reduction.

---

### 2. N+1 `get_prices()` in Prediction Display

**File:** `src/app.py` (ML pipeline results section)

**Impact:** Computing "actual returns" calls `repo.get_prices(stock.id, ...)` for each prediction row. 20 predictions = 20 sessions = 20 DB round-trips.

```python
# app.py — prediction return calculation (existing, problematic):
for row in pred_df.itertuples():
    ticker = str(row.ticker).upper()
    stock = stock_map.get(ticker)
    if stock is None:
        actual_returns.append(None)
        continue
    prices = _repo.get_prices(stock.id, dd, _date.today())  # ← N+1
    # ... compute return
```

**Fix — add batch query to repository:**

```python
# src/repository.py — new method:
def get_prices_batch(self, stock_ids: list[int],
                     start: date, end: date) -> dict[int, pd.DataFrame]:
    """Single query for multi-stock prices. Returns {stock_id: DataFrame}."""
    def _query(s):
        rows = (
            s.query(DailyPrice)
            .filter(DailyPrice.stock_id.in_(stock_ids),
                    DailyPrice.date >= start, DailyPrice.date <= end)
            .order_by(DailyPrice.stock_id, DailyPrice.date).all()
        )
        result: dict[int, list[dict]] = {}
        for r in rows:
            result.setdefault(r.stock_id, []).append(
                {"date": r.date, "adj_close": r.adj_close})
        return {sid: pd.DataFrame(recs) for sid, recs in result.items()}
    return self._with_session(_query)
```

```python
# app.py — updated caller:
all_ids = [stock_map[t].id for t in unique_symbols if stock_map.get(t)]
prices_batch = _repo.get_prices_batch(all_ids, min_date, _date.today())

for row in pred_df.itertuples():
    stock = stock_map.get(str(row.ticker).upper())
    if stock is None:
        actual_returns.append(None)
        continue
    prices = prices_batch.get(stock.id, pd.DataFrame())
    if prices.empty or len(prices) < 2:
        actual_returns.append(None)
        continue
    start_price = float(prices["adj_close"].iloc[0])
    end_price = float(prices["adj_close"].iloc[-1])
    actual_returns.append((end_price / start_price - 1) if start_price > 0 else None)
```

**Savings:** 20× fewer DB round-trips (20 sessions → 1 session).

---

## 🟠 High

### 3. Repository — One DB Session Per Method Call

**File:** `src/repository.py`

**Impact:** `find_stock()` → `get_indicator()` → `get_prices()` = 3 separate sessions. Pool absorbs this (pool_size=15), but unnecessary checkout/checkin per call adds latency.

**Fix — add session_scope context manager:**

```python
# src/repository.py:
from contextlib import contextmanager

class StockRepository:
    @contextmanager
    def session_scope(self):
        """Single session for multiple queries."""
        session = get_session()
        try:
            self._active_session = session
            yield
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            self._active_session = None

    def _get_session(self):
        if getattr(self, '_active_session', None) is not None:
            return self._active_session
        return get_session()

# Usage:
with repo.session_scope():
    stock = repo.find_stock("AAPL")
    indicator = repo.get_indicator(stock.id)
    prices = repo.get_prices(stock.id, start, end)
```

---

### 4. Unbounded `ml_log_lines` Buffer

**File:** `src/app.py`

**Impact:** `st.session_state.ml_log_lines.append(...)` has no size cap. Cleared only on next pipeline run start.

**Fix:**

```python
from collections import deque

if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = deque(maxlen=1000)

# appending later just works:
ctx.session_state.ml_log_lines.append(str(msg))
```

---

### 5. Repeated `StockRepository()` Per Cached Function

**File:** `src/ui/pages/stock_lookup.py`, `src/ui/pages/ml_pipeline.py`

**Impact:** Each `@st.cache_data`-wrapped function creates a new `StockRepository()`. Multiple instances = redundant engine lookups.

```python
# Existing:
@st.cache_data(ttl=300)
def _cached_find_stock(symbol: str) -> dict | None:
    stock = StockRepository().find_stock(symbol)  # new instance each call
```

**Fix — use `@st.cache_resource` for singleton:**

```python
@st.cache_resource
def _get_repo() -> StockRepository:
    return StockRepository()

@st.cache_data(ttl=300)
def _cached_find_stock(symbol: str) -> dict | None:
    stock = _get_repo().find_stock(symbol)
```

---

### 6. Per-Symbol News HTTP in Pipeline

**File:** `src/ingestion/pipeline.py` → `_fetch_stock_news()`

**Impact:** Each active stock triggers TradingAgents → Google Gemini API call. DB cache deduplicates, but round-trip per symbol remains. 100 stocks = 100 API calls per run.

**Fix — batch cache-gap detection:**

```python
def _prefetch_news_gaps(symbols: list[str], session) -> set[str]:
    """Find symbols with stale/missing news in single query."""
    rows = session.execute(text(
        "SELECT symbol, MAX(fetched_at) FROM stock_news "
        "WHERE symbol IN :syms GROUP BY symbol"
    ), {"syms": tuple(symbols)}).fetchall()
    fresh = {r[0] for r in rows if r[1] and (datetime.utcnow() - r[1]).days < 7}
    return set(symbols) - fresh
```

---

## 🟡 Medium

### 7. Double `COUNT(*)` in `count_summary()`

**File:** `src/repository.py`

```python
# Existing — 2 queries:
total = s.query(Stock).count()
active = s.query(Stock).filter_by(is_active=True).count()
```

**Fix — 1 query:**
```python
row = s.execute(text(
    "SELECT COUNT(*) AS total, SUM(CASE WHEN is_active THEN 1 ELSE 0 END) AS active FROM stocks"
)).mappings().first()
total, active = row["total"], row["active"] or 0
return {"total": total, "active": active, "inactive": total - active}
```

---

### 8. Feature Column Median-Impute Loop

**File:** `src/ml_bucket_selector.py`

```python
# Existing — N passes:
for col in FEATURE_COLS:
    if df[col].isna().any():
        median = df[col].median()
        df[col] = df[col].fillna(median if pd.notna(median) else 0.0)
```

**Fix — 1 pass:**
```python
feature_df = df[FEATURE_COLS]
medians = feature_df.median()
df[FEATURE_COLS] = feature_df.fillna(medians.fillna(0.0))
```

---

### 9. Redundant `datetime.utcnow()` in Pipeline Steps

**File:** `src/pipeline/stock_selection.py`, `src/pipeline/fast_evaluation.py`

Multiple `dt.datetime.utcnow()` calls within same method = slightly different timestamps.

**Fix:** Capture once, pass to `_write_report()`:
```python
now = dt.datetime.utcnow()
_write_report(evaluations, report_dir, backend_name, timestamp=now)
```

### 10. Sort Key Dict Per Evaluation in `_write_report()`

**File:** `src/pipeline/fast_evaluation.py`

```python
# Existing — allocates new dict per opinion:
sorted_ops = sorted(ev.opinions, key=lambda o: (
    {"bullish": 0, "bearish": 1, "neutral": 2}.get(o.opinion, 3), -o.confidence))
```

**Fix:**
```python
_OPINION_ORDER = {"bullish": 0, "bearish": 1, "neutral": 2}
sorted_ops = sorted(ev.opinions, key=lambda o: (_OPINION_ORDER.get(o.opinion, 3), -o.confidence))
```

### 11. `os.environ` Global Mutation in Deep Evaluator

**File:** `src/pipeline/backends/deep_evaluators.py`

```python
# Existing — pollutes os.environ permanently:
for env_var, value in mapping.items():
    if value and not os.environ.get(env_var):
        os.environ[env_var] = value
```

**Fix — context manager that restores original values:**
```python
@contextmanager
def _temp_env(**kwargs):
    old = {k: os.environ.get(k) for k in kwargs}
    for k, v in kwargs.items():
        if v: os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
```

---

## 🟢 Already Good / Not Actionable

- **`_write_report()`** — uses `"\n".join(lines)`, O(n). ~20KB output. Already efficient.
- **`get_listing()`** — parquet cache with 6-hour TTL, single `os.stat()` check. Negligible.
- **`ThreadPoolExecutor`** — all 4 instances use `with` statement, properly scoped. No leaks.
- **Existing optimizations**: `_prefetch_stock_dates()`, `find_stocks_batch()`, `skip_stock_ids`, `_LISTING_CACHE` parquet, `news_cache.py` DB-backed dedup, `pool_pre_ping=True`/`pool_recycle=3600`.

---

## Summary

| # | Severity | Pattern | Files | Effort |
|---|----------|---------|-------|--------|
| 1 | 🔴 Critical | Zero `st.cache_data` on 9 UI pages | `app.py` + 9 page files | Medium |
| 2 | 🔴 Critical | N+1 `get_prices()` in prediction loop | `app.py`, `repository.py` | Low |
| 3 | 🟠 High | Session per method call | `repository.py` | High |
| 4 | 🟠 High | Unbounded log buffer | `app.py` | Low |
| 5 | 🟠 High | Repeated repo construction | UI pages | Low |
| 6 | 🟠 High | Per-symbol news HTTP | `ingestion/pipeline.py` | Medium |
| 7 | 🟡 Medium | Double `COUNT(*)` | `repository.py` | Low |
| 8 | 🟡 Medium | Median-impute loop | `ml_bucket_selector.py` | Low |
| 9 | 🟡 Medium | Redundant `utcnow()` | pipeline steps | Low |
| 10 | 🟡 Medium | Sort key dict per eval | `fast_evaluation.py` | Low |
| 11 | 🟡 Medium | `os.environ` injection | `deep_evaluators.py` | Medium |

## Action Sequence

**Phase 1 (~2h):** Fix #4 (deque), #7 (single COUNT), #8 (vectorize), #10 (module constant), #5 (cache_resource repo)

**Phase 2 (~3h):** Fix #1 (add `@st.cache_data` to all 9 pages), #9 (consolidate utcnow)

**Phase 3 (~5h):** Fix #2 (get_prices_batch), #3 (session_scope), #11 (temp_env context manager), #6 (news gap detection)

---

## Notes

- **Not React** — this is Streamlit (Python). "Re-render" = Streamlit widget-induced rerenders.
- **No hard memory leaks** found. `ml_log_lines` is a soft leak — unbounded within a run, cleared on restart.
- **DB pool** correctly configured. All sessions properly closed in `finally` blocks.
- **15 existing optimizations** identified and working correctly — these are strengths, not gaps.
