# Performance Audit Report v7 — AIStock Codebase

**Date:** 2026-05-30
**Severity Scale:** 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low

---

## 1. N+1 Query Patterns

### 🔴 N+1: `get_prices()` Called Per Stock in Predict Thread

**File:** `src/app.py` (predict-only thread)

Each stock triggers a separate `SELECT * FROM daily_prices WHERE stock_id=?` query. For 100 stocks = 100 individual queries, each opening/closing a DB session.

**Fix — batch query in repository.py:**
```python
def get_prices_batch(
    self, stock_ids: list[int], start: date, end: date
) -> dict[int, pd.DataFrame]:
    """Single query for multiple stocks."""
    def _query(s):
        rows = (
            s.query(DailyPrice)
            .filter(
                DailyPrice.stock_id.in_(stock_ids),
                DailyPrice.date >= start,
                DailyPrice.date <= end,
            )
            .order_by(DailyPrice.stock_id, DailyPrice.date)
            .all()
        )
        result: dict[int, list[dict]] = {sid: [] for sid in stock_ids}
        for r in rows:
            result[r.stock_id].append({"date": r.date, "adj_close": r.adj_close})
        return {sid: pd.DataFrame(recs) for sid, recs in result.items() if recs}
    return self._with_session(_query)
```

**Impact:** Eliminates ~99 queries for 100-stock run; ~100x reduction.

---

### 🟠 Repository `_with_session()` Opens New Session Per Method Call

**File:** `src/repository.py`

Each call creates a new session + connection from pool. Ad-hoc UI code often chains 3+ repo calls serially (find → prices → indicator) — 3 session open/close cycles instead of 1.

**Fix — add context manager:**
```python
from contextlib import contextmanager

class StockRepository:
    @contextmanager
    def session_scope(self):
        session = self._get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

Pipeline steps already use `open_session(ctx)` for this. Fix targets ad-hoc UI callers.

---

### 🟢 Prefetch Pattern Already in Ingestion Pipeline

**File:** `src/ingestion/pipeline.py` — `_prefetch_stock_dates()`

Batch-fetches max_price_dates, first_indicator_dates, first_price_dates, indicator_last_updated in 4 queries for ALL stocks. Per-stock processing reads from dict. **Good pattern — extend to other multi-stock paths.**

---

## 2. Caching Gaps

### 🔴 Missing `@st.cache_data` on Most Streamlit Pages

**Files:** `stock_lookup.py`, `stock_technical.py`, `stock_screener.py`, `stock_manager.py`, `portfolio.py`, `strategy_backtest.py`, `job_history.py`

Only `overview.py` and `ml_pipeline.py` use caching. Every widget interaction on other pages triggers fresh DB queries.

**Fix for stock screener (`stock_screener.py`):**
```python
@st.cache_data(ttl=300, show_spinner="Loading screener...")
def _cached_screener_data(
    exchange: str, sector: str, min_cap: float, max_pe: float,
    min_roe: float, max_beta: float
) -> pd.DataFrame:
    from repository import StockRepository
    criteria = ScreenCriteria(
        exchange=exchange if exchange != "All" else None,
        sector=sector if sector != "All" else None,
        min_market_cap=min_cap, max_pe=max_pe,
        min_roe=min_roe, max_beta=max_beta,
    )
    return StockRepository().screen(criteria)
```

**Fix for technical analysis (`stock_technical.py`):**
```python
@st.cache_data(ttl=3600, show_spinner="Loading technical data...")
def _cached_tech_data(symbol: str, start: date, end: date) -> pd.DataFrame:
    repo = StockRepository()
    stock = repo.find_stock(symbol)
    if not stock:
        return pd.DataFrame()
    return repo.get_tech_indicators(stock.id, start, end)
```

**Impact:** 80-95% reduction in DB queries during interactive UI usage. Largest single win.

---

### 🟠 Sidebar Stats Called Every Render Without Caching

**File:** `src/app.py` — `display_quick_stats()`

```python
def display_quick_stats(repo):
    summary = repo.count_summary()  # runs EVERY page navigation
```

**Fix:**
```python
@st.cache_data(ttl=60, show_spinner=False)
def _quick_stats() -> dict:
    from repository import StockRepository
    return StockRepository().count_summary()
```

This hits every page navigation. Cache = instant sidebar.

---

### 🟡 `_build_ctx()` Creates Lambda Closures Every Render

**File:** `src/app.py` — `main()`

```python
ctx = _build_ctx()  # new PageContext + lambda closures every render
```

`PageContext` is cheap but `pipeline_thread_target` lambdas are recreated. Repo could be a `@st.cache_resource` singleton.

---

### 🟢 Config `load_config()` Has mtime-Based Cache

**File:** `src/config.py`

```python
if not force and _config is not None and current_mtime == _config_mtime:
    return _config  # skips re-parse on unchanged file
```

**Good.** Pipeline `ConfigLoader` also caches via `self._cfg`.

---

## 3. Streamlit Rendering Issues

### 🟠 `on_select="rerun"` Triggers Full Page Reload

**File:** `src/ui/pages/ml_pipeline.py`

```python
event = ctx.st.dataframe(tdf, selection_mode="single-row", on_select="rerun", key="...")
```

Single-row click → full `st.rerun()` → re-executes ALL cached calls + re-renders all charts.

**Fix:**
```python
def _on_select():
    idx = st.session_state.ml_selected_stocks.selection.rows[0]
    st.session_state.selected_ticker = tdf.iloc[idx][ticker_display]

event = ctx.st.dataframe(tdf, selection_mode="single-row", on_select=_on_select, key="...")
```

---

### 🟡 `plotly_chart` Serializes Full Figure JSON on Every Render

Each chart call serializes entire figure to JSON for Plotly.js. Pages with 3-4 charts add significant latency.

**Mitigation:** Cache figure objects with `@st.cache_resource` for stable data, or use `@st.cache_data` for the underlying DataFrames so re-renders skip data fetch + figure build.

---

### 🟢 `MAX_LOG_LINES = 1000` Guard Prevents Unbounded Log Growth

**File:** `src/app.py`

```python
if len(st.session_state.ml_log_lines) >= MAX_LOG_LINES:
    st.session_state.ml_log_lines.pop(0)
```

**Good.** Log lines won't grow unbounded.

---

## 4. Memory Leaks / Resource Management

### 🟠 Global `_google_news_rate_limited` Flag Never Resets

**File:** `src/pipeline/data_update.py`

Once Google API rate-limits, flag stays `True` forever. Even after rate-limit window resets, Alpha Vantage is used for all remaining stocks in the run.

**Fix:**
```python
_google_rate_limit_at: float = 0.0
_RATE_LIMIT_TTL = 3600

def _fetch_stock_news(symbol, fetcher=None):
    global _google_news_rate_limited, _google_rate_limit_at
    if _google_news_rate_limited:
        if time.time() - _google_rate_limit_at > _RATE_LIMIT_TTL:
            _google_news_rate_limited = False
        elif fetcher is not None:
            return _fetch_stock_news_av(symbol, fetcher)
```

---

### 🟢 DB Connection Pool Properly Configured

**File:** `src/database.py`

```python
create_engine(url, pool_pre_ping=True, pool_recycle=3600, pool_size=15, max_overflow=10)
```

`pool_pre_ping` prevents stale connections. `pool_recycle` prevents MySQL timeout. **Good.**

---

### 🟢 `news_cache` DB-Backed, Not In-Memory

**File:** `src/news_cache.py`

Results stored in `stock_news` table with `on_duplicate_key_update`. No unbounded memory growth. **Good.**

---

## 5. Redundant Computations

### 🟠 `_count_by_opinion()` Called Twice Per Ticker

**File:** `src/pipeline/fast_evaluation.py`

```python
# In FastEvaluationStep.run():
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)  # 1st call

# Then _write_report() loops again:
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)  # 2nd call — same opinions!
```

**Fix:** Compute once, attach to object:
```python
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)
    ev._counts = (pos, neg, neu)
```

Then `_write_report` reads `ev._counts` instead of recounting.

---

### 🟡 Redundant YAML Parse: `ConfigLoader` + `load_config()`

**Files:** `src/pipeline/config.py`, `src/config.py`

Both parse `config.yaml` independently. `ConfigLoader` is used by orchestrator; `load_config()` by ingestion/database modules.

**Fix:** Pass pre-loaded dict to `ConfigLoader`:
```python
class ConfigLoader:
    def __init__(self, config_path=None, raw_config=None):
        if raw_config is not None:
            self._raw = raw_config
        else:
            self._config_path = Path(config_path or "config.yaml")
```

Orchestrator can then: `ConfigLoader(raw_config=load_config())`.

---

### 🟡 Fixed ThreadPool Workers at 5

**File:** `src/ingestion/pipeline.py`

```python
MAX_WORKERS = 5
```

For I/O-bound API+DB work, 5 workers underutilizes available parallelism. 10-15 would speed the daily pipeline.

**Fix:** Make configurable via `config.yaml`:
```yaml
data_update:
  max_workers: 10
```

---

### 🟡 `run_predict_only` Deserializes All Models Sequentially

**File:** `src/finrl_runner.py`

```python
for mp in model_files:
    artifact = joblib.load(mp)  # serial, 11 files
```

Could lazy-load only models for sectors that appear in the symbol list.

---

### 🟢 `find_stocks_batch()` Exists and Is Used

**File:** `src/repository.py`

Batch lookup pattern exists and is used in `FinrlStockSelector` and predict thread. **Extend to more callers** (stock_detail, technical analysis pages).

---

## Summary Table

| Category | 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low |
|----------|------------|---------|-----------|--------|
| N+1 Queries | 1 | 1 | 0 | 1 |
| Caching Gaps | 1 | 1 | 1 | 1 |
| Streamlit Rendering | 0 | 1 | 1 | 1 |
| Memory/Resource | 0 | 1 | 0 | 0 |
| Redundant Computation | 0 | 1 | 3 | 1 |
| **Total** | **2** | **5** | **5** | **4** |

## Priority Fix Order

| # | Fix | Impact | Effort |
|---|-----|--------|--------|
| 1 | Add `@st.cache_data` on UI data pages | 80-95% fewer DB queries | Low |
| 2 | Batch `get_prices` in predict thread | ~99 fewer queries/run | Medium |
| 3 | Cache sidebar quick stats | Hits every page render | Low |
| 4 | Replace `on_select="rerun"` with callback | Smoother ML pipeline UX | Low |
| 5 | Add `session_scope` context manager | Cleaner session lifecycle | Medium |
| 6 | Deduplicate `_count_by_opinion` calls | Simple 2-line fix | Low |
| 7 | Make worker count configurable | Faster daily pipeline | Low |
| 8 | Add TTL reset to news rate-limit flag | Better fallback behavior | Low |
| 9 | Unify config loading paths | Single parse point | Medium |
| 10 | Precompute chart data in `@st.cache_data` | Faster chart rendering | Low |
