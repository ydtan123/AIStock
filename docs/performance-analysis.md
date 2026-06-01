# AIStock Performance Analysis

**Date:** 2026-05-30
**Analyzed:** `src/` — Streamlit app, SQLAlchemy ORM, Alpha Vantage fetcher, ML pipeline

---

## 1. N+1 Query Patterns

### 1.1 Stock Name Lookup in `_show_ml_results()` — CRITICAL

**File:** `src/app.py`
**Issue:** After ML pipeline runs, display code loops over unique tickers and calls `repo.find_stock(sym)` once per ticker. Each call opens a new DB session, executes a query, and closes the session.

```python
# Current (N+1):
for sym in wdf[ticker_col].dropna().unique():
    stock = _repo.find_stock(str(sym))
    name_map[sym] = stock.name if stock else ""
```

**Fix:** Batch-fetch all names in a single query:

```python
# Add to repository.py:
def find_stocks_batch(self, symbols: list[str]) -> dict[str, str]:
    session = self._get_session()
    try:
        rows = (
            session.query(Stock.symbol, Stock.name)
            .filter(Stock.symbol.in_([s.upper() for s in symbols]))
            .all()
        )
        return {r.symbol: r.name for r in rows}
    finally:
        session.close()

# In app.py:
repo = StockRepository()
name_map = repo.find_stocks_batch(wdf[ticker_col].dropna().unique().tolist())
```

**Impact:** For 50 stocks, 50 queries become 1 query. ~50x reduction.

---

### 1.2 `_stock_detail_dialog()` Makes Multiple Independent Queries

**File:** `src/app.py`
**Issue:** Dialog fetches `find_stock()`, `get_indicator()`, and `get_snapshot()` in three separate sessions.

```python
# Current (3 sessions, 3 round trips):
stock = repo.find_stock(symbol)
indicator = repo.get_indicator(stock.id)
snapshot = repo.get_snapshot(stock.id)
```

**Fix:** Add a combined fetch method:

```python
# Add to repository.py:
def get_stock_detail(self, symbol: str) -> dict:
    session = self._get_session()
    try:
        stock = session.query(Stock).filter_by(symbol=symbol.upper()).first()
        if not stock:
            return {}
        indicator = session.query(StockIndicator).filter_by(stock_id=stock.id).first()
        snapshot = session.query(StockSnapshot).filter_by(stock_id=stock.id).first()
        return {"stock": stock, "indicator": indicator, "snapshot": snapshot}
    finally:
        session.close()
```

**Impact:** 3 sessions → 1 session. 3x fewer round trips.

---

## 2. Missing Streamlit `@st.cache_data` — CRITICAL

### 2.1 Every Page Load Re-Runs All Queries

**File:** `src/app.py`
**Issue:** Zero `@st.cache_data` decorators exist. Every rerun, all database queries re-execute. Streamlit reruns on *any* widget interaction — selectbox change, slider move, button click.

```python
# Current: runs query every rerun
st.dataframe(repo.get_job_runs(100), width='stretch')
```

**Fix:** Cache expensive query results:

```python
@st.cache_data(ttl=300)  # 5-min cache
def _cached_job_runs(limit: int = 100) -> pd.DataFrame:
    return StockRepository().get_job_runs(limit)

@st.cache_data(ttl=600)  # 10-min cache
def _cached_count_summary() -> dict:
    return StockRepository().count_summary()

@st.cache_data(ttl=300)
def _cached_latest_selected_stocks() -> list[dict]:
    return StockRepository().get_latest_selected_stocks()

@st.cache_data(ttl=600)
def _cached_sectors(table: str = "stock_snapshots") -> list[str]:
    return StockRepository().get_sectors(table)
```

**Impact:** Queries cached across Streamlit reruns. Dashboard goes from query-every-click to memory-only for cached data.

---

## 3. Database Session & Query Optimization

### 3.1 `count_summary()` — Two Queries Where One Suffices

**File:** `src/repository.py`

```python
# Current (2 queries):
total = session.query(Stock).count()
active = session.query(Stock).filter_by(is_active=True).count()

# Fix (1 query):
from sqlalchemy import func, case
result = session.query(
    func.count().label("total"),
    func.sum(case((Stock.is_active == True, 1), else_=0)).label("active"),
).first()
total, active = result.total, result.active
```

**Impact:** 1 DB round-trip instead of 2.

---

### 3.2 `save_selected_stocks()` — Row-by-Row Insert Instead of Bulk

**File:** `src/repository.py`

```python
# Current (1 DELETE + N individual INSERTs):
session.query(SelectedStock).delete()
for rec in records:
    row = SelectedStock(...)
    session.add(row)
session.commit()
```

**Fix:** Use `bulk_insert_mappings`:

```python
# Fix (1 DELETE + 1 bulk INSERT):
session.query(SelectedStock).delete()
rows = [{
    "ticker": rec["ticker"],
    "model_name": rec.get("model_name", ""),
    "ml_score": float(rec.get("ml_score", 0)),
    "bucket": rec.get("bucket"),
    "weight": float(rec.get("weight", 0)),
    "date_selected": rec.get("date_selected"),
    "model_file": rec.get("model_file", ""),
    "pipeline_run_at": run_at,
} for rec in records]
session.bulk_insert_mappings(SelectedStock, rows)
session.commit()
```

**Impact:** For 50 stocks, 50 individual INSERTs → 1 bulk INSERT. ~10-50x faster.

---

### 3.3 `get_latest_selected_stocks()` — Two Queries Can Be One

**File:** `src/repository.py`

```python
# Current (2 queries):
latest_run = session.query(SelectedStock.pipeline_run_at).order_by(...).limit(1).scalar()
rows = session.query(SelectedStock).filter(SelectedStock.pipeline_run_at == latest_run).all()

# Fix (1 query with subquery):
from sqlalchemy import func
subq = session.query(func.max(SelectedStock.pipeline_run_at)).scalar_subquery()
rows = session.query(SelectedStock).filter(
    SelectedStock.pipeline_run_at == subq
).all()
```

**Impact:** 2 queries → 1 query.

---

### 3.4 `datetime.utcnow()` Deprecated — Uses System Clock

**File:** `src/repository.py`, `src/news_cache.py`, `src/pipeline/fast_evaluation.py`
**Issue:** Multiple calls to `datetime.utcnow()` throughout codebase. Python 3.12+ deprecates this.

**Fix:**
```python
# Replace all instances:
# datetime.utcnow() → datetime.now(datetime.UTC)
from datetime import datetime, UTC
```

---

## 4. Streaming/Iterator Opportunity (Memory)

### 4.1 `get_prices()` and `get_tech_indicators()` Load Full Result Sets

**File:** `src/repository.py`
**Issue:** For stocks with 20+ years of daily data, `.all()` loads 5000+ ORM objects into memory before converting to DataFrame.

```python
# Current:
rows = session.query(DailyPrice).filter(...).all()
return pd.DataFrame([{...} for r in rows])
```

**Fix:** Use SQLAlchemy statement with `pd.read_sql`:

```python
def get_prices(self, stock_id: int, start: date, end: date) -> pd.DataFrame:
    session = self._get_session()
    try:
        query = (
            session.query(DailyPrice)
            .filter(DailyPrice.stock_id == stock_id,
                    DailyPrice.date >= start,
                    DailyPrice.date <= end)
            .order_by(DailyPrice.date)
            .statement
        )
        return pd.read_sql(query, session.bind, index_col="date")
    finally:
        session.close()
```

**Impact:** Skips ORM object creation for every row. Memory ~50% reduction for large datasets.

---

## 5. Caching Opportunities

### 5.1 No In-Memory Cache Layer Between DB and UI

**Issue:** Repository methods always hit the database. Many queries return identical results across short time windows (sector lists, stock list, job runs).

**Fix:** Add a simple TTL cache wrapper:

```python
# src/cache.py
import time

class TTLCache:
    """Simple in-process TTL cache."""
    def __init__(self, ttl_seconds: int = 300):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, any]] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry and time.time() - entry[0] < self._ttl:
            return entry[1]
        return None

    def set(self, key: str, value):
        self._store[key] = (time.time(), value)

    def invalidate(self, prefix: str = ""):
        if prefix:
            self._store = {k: v for k, v in self._store.items()
                           if not k.startswith(prefix)}

_repo_cache = TTLCache(ttl=300)

# Use in repository:
def count_summary(self) -> dict:
    cached = _repo_cache.get("count_summary")
    if cached:
        return cached
    # ... execute query ...
    _repo_cache.set("count_summary", result)
    return result
```

---

### 5.2 `get_listing()` in Alpha Vantage — No Local Cache

**File:** `src/fetcher/alpha_vantage.py`
**Issue:** `get_listing()` fetches the full NYSE/NASDAQ listing CSV from Alpha Vantage every call. This data changes rarely (daily at most).

**Fix:** Cache the CSV response to disk:

```python
import json
from pathlib import Path

_CACHE_DIR = Path("data/cache")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def get_listing(self) -> pd.DataFrame:
    cache_file = _CACHE_DIR / "alpha_vantage_listing.parquet"
    if cache_file.exists():
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=UTC)
        if datetime.now(UTC) - mtime < timedelta(hours=12):
            return pd.read_parquet(cache_file)

    # ... fetch from API ...
    df.to_parquet(cache_file, index=False)
    return df
```

**Impact:** Save 1 API call and full CSV parse on most calls.

---

## 6. TokenBucket Rate Limiter — Busy-Wait

### 6.1 Sleep-Based Polling Wastes CPU

**File:** `src/fetcher/rate_limiter.py`

```python
# Current: busy-wait with sleep(0.05)
while True:
    with self._lock:
        self._refill()
        if self._tokens >= tokens and spacing_ok:
            ...
    time.sleep(0.05)
```

**Fix:** Compute exact wait time instead of polling:

```python
def acquire(self, tokens: int = 1):
    while True:
        with self._lock:
            self._refill()
            now = time.monotonic()
            spacing_ok = (now - self._last_release) >= self._min_spacing
            if self._tokens >= tokens and spacing_ok:
                self._tokens -= tokens
                self._last_release = now
                return
            # Calculate exact wait time
            wait = self._min_spacing - (now - self._last_release)
            if self._tokens < tokens:
                wait = max(wait, (tokens - self._tokens) / self._refill_rate)
        if wait > 0:
            time.sleep(wait)
        else:
            time.sleep(0.01)
```

**Impact:** Fewer wake cycles, lower CPU usage during rate-limited bursts.

---

## 7. Redundant Computations

### 7.1 `_count_by_opinion()` Called Twice Per Evaluation

**File:** `src/pipeline/fast_evaluation.py`

```python
# Called first for DB persistence:
pos, neg, neu = _count_by_opinion(ev.opinions)
# ... store ...

# Called again for ranking output:
for ev in evaluations_sorted:
    pos, neg, neu = _count_by_opinion(ev.opinions)  # DUPLICATE
```

**Fix:** Cache counts, compute once:

```python
# Compute once, reuse:
opinion_counts = {
    ev.ticker: _count_by_opinion(ev.opinions) for ev in evaluations
}

for ev in evaluations:
    pos, neg, neu = opinion_counts[ev.ticker]
    # ... store ...

for ev in evaluations_sorted:
    pos, neg, neu = opinion_counts[ev.ticker]
    # ... build ranked output ...
```

---

### 7.2 Inline `import` Statements in Hot Paths

**Files:** `src/repository.py`, `src/app.py`, `src/news_cache.py`

```python
# Inside get_stock_news():
from datetime import timedelta  # Should be at module level

# Inside _show_ml_results():
import json as _json  # Should be at module level
```

**Fix:** Move all imports to module level. Inline imports have measurable overhead in hot paths.

---

### 7.3 DataFrame Copy Chains in Display Code

**File:** `src/app.py` (`_show_predict_only_results`)

```python
display = df[[c for c in cols if c in df.columns]].copy()
display["predicted_return"] = display["predicted_return"].apply(lambda x: ...)
display["actual_return"] = display["actual_return"].apply(lambda x: ...)
display.columns = [...]
```

`.copy()` creates full memory copy. Use `assign` for chained operations:

```python
display = (
    df[[c for c in cols if c in df.columns]]
    .assign(
        predicted_return=lambda d: d["predicted_return"].apply(
            lambda x: f"{float(x)*100:+.2f}%"),
        actual_return=lambda d: d["actual_return"].apply(
            lambda x: f"{float(x)*100:+.2f}%" if pd.notna(x) else "—"
        ) if "actual_return" in d.columns else None,
    )
)
```

---

## 8. Missing Database Indexes

Based on query patterns observed:

```sql
-- For get_latest_selected_stocks frequent filter + sort
CREATE INDEX IF NOT EXISTS ix_selected_stocks_run_at
    ON selected_stocks(pipeline_run_at);

-- For news cache lookups (get_stock_news, get_insider_transactions)
CREATE INDEX IF NOT EXISTS ix_stock_news_lookup
    ON stock_news(ticker, tool_name, fetched_at);

-- For FastEvaluation per-run lookups
CREATE INDEX IF NOT EXISTS ix_fast_eval_conclusion_run
    ON fast_evaluation_conclusions(pipeline_run_id, ticker);
```

---

## 9. React/Streamlit Rendering

**Note:** This project uses Streamlit (Python), not React. Streamlit rendering analysis:

- **No `@st.cache_data`**: Every widget interaction triggers full script rerun including all DB queries. This is the single largest performance issue.
- **`st.rerun()` in ML pipeline loop**: The polling pattern `while True: ... sleep(1); st.rerun()` is correct for long-running pipelines but re-executes the entire page body each second. Wrap the rest of the page in cache functions to minimize recomputation.
- **`st.dataframe` with `width='stretch'`**: Acceptable. Static tables, not virtual scrolling.

---

## 10. Memory Leak Risk

### 10.1 Session State Accumulation

**File:** `src/app.py`

```python
st.session_state.ml_log_lines.append(str(msg))
```

`ml_log_lines` grows unbounded during pipeline runs. Only the last 200 lines are displayed:

```python
st.code("\n".join(st.session_state.ml_log_lines[-200:]), language=None)
```

**Fix:** Cap the list:

```python
MAX_LOG_LINES = 500
st.session_state.ml_log_lines = (st.session_state.ml_log_lines + [str(msg)])[-MAX_LOG_LINES:]
```

---

### 10.2 SQLAlchemy Session Not Closed on Exception

**File:** `src/repository.py`
**Issue:** All repository methods use `try/finally: session.close()`, which is correct. No leaks found in repository layer.

However, `news_cache.py` uses a helper that could leak:

```python
def _get_session():
    from database import get_session
    return get_session()
```

The `get_cached` function opens a session for every cache lookup. Under high TradingAgents activity, this creates many short-lived sessions. Consider passing a session from a context manager for batch operations.

---

## Summary Table

| # | Issue | Severity | File | Effort |
|---|-------|----------|------|--------|
| 1.1 | N+1 name lookup in ML results | **CRITICAL** | `app.py` | Low |
| 2.1 | No `@st.cache_data` anywhere | **CRITICAL** | `app.py` | Medium |
| 3.2 | Row-by-row insert in save | **HIGH** | `repository.py` | Low |
| 1.2 | Multiple sessions in stock dialog | **HIGH** | `app.py` | Low |
| 5.1 | No in-memory cache layer | **HIGH** | Multiple | Medium |
| 10.1 | Unbounded log_lines list | **HIGH** | `app.py` | Low |
| 3.1 | `count_summary` 2 queries | MEDIUM | `repository.py` | Low |
| 3.3 | `get_latest_selected_stocks` 2 queries | MEDIUM | `repository.py` | Low |
| 4.1 | Full ORM load for large datasets | MEDIUM | `repository.py` | Medium |
| 5.2 | Listing API not cached locally | MEDIUM | `fetcher/` | Low |
| 8.1 | Missing query indexes | MEDIUM | `models.py` | Low |
| 6.1 | Busy-wait rate limiter | LOW | `rate_limiter.py` | Medium |
| 7.1 | `_count_by_opinion` called twice | LOW | `fast_evaluation.py` | Low |
| 7.2 | Inline imports in hot paths | LOW | Multiple | Low |
| 7.3 | DataFrame copy chains | LOW | `app.py` | Low |
| 3.4 | Deprecated `utcnow()` | LOW | Multiple | Low |

**Top 3 quick wins (highest impact, lowest effort):**
1. Add `@st.cache_data` to expensive query functions in `app.py`
2. Batch the N+1 stock name lookup with `find_stocks_batch()`
3. Add bulk insert to `save_selected_stocks()` and cap `ml_log_lines`
