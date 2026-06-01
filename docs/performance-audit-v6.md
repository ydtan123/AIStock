# AIStock Performance Audit v6

**Date:** 2026-05-30
**Scope:** Full codebase — `src/` directory
**Categories:** N+1 queries, Streamlit re-renders, caching gaps, memory leaks, redundant computation

---

## Severity Legend

| Level | Meaning | Action |
|-------|---------|--------|
| **CRITICAL** | Causes significant latency or resource waste on every page load | Fix immediately |
| **HIGH** | Causes measurable slowdown in common operations | Fix this sprint |
| **MEDIUM** | Degrades performance under load or at scale | Fix next sprint |
| **LOW** | Minor inefficiency, low impact | Backlog |

---

## 1. N+1 Query Patterns

### CRITICAL-1: `count_summary()` — 3 separate COUNT queries

**File:** `src/repository.py:191-196`
**Impact:** Every page render calls this. 3 round-trips to DB when 1 suffices.

**Current code:**
```python
def count_summary(self) -> dict:
    def _query(s):
        total = s.query(Stock).count()
        active = s.query(Stock).filter_by(is_active=True).count()
        return {"total": total, "active": active, "inactive": total - active}
    return self._with_session(_query)
```

**Fix:**
```python
def count_summary(self) -> dict:
    def _query(s):
        row = s.execute(
            text("SELECT COUNT(*), SUM(CASE WHEN is_active THEN 1 ELSE 0 END) FROM stocks")
        ).first()
        total, active = row[0], row[1] or 0
        return {"total": total, "active": active, "inactive": total - active}
    return self._with_session(_query)
```

---

### CRITICAL-2: `StockSelectionStep.run()` — Per-row `session.add()` loop

**File:** `src/pipeline/stock_selection.py:41-56`
**Impact:** For N selected stocks, N individual INSERTs. The `FastEvaluationStep` (line 119-120 of fast_evaluation.py) already uses `session.add_all()` correctly.

**Current code:**
```python
with open_session(ctx) as session:
    for t in tickers:
        row = SelectedStock(ticker=t.ticker, model_name=backend_name,
                           ml_score=t.ml_score, ...)
        session.add(row)           # N individual INSERTs
    session.commit()
```

**Fix:**
```python
with open_session(ctx) as session:
    rows = [
        SelectedStock(ticker=t.ticker, model_name=backend_name,
                      ml_score=t.ml_score, bucket=None, weight=None,
                      date_selected=now.date(), pipeline_run_at=now,
                      pipeline_run_id=ctx.run_id, sector=t.sector,
                      backend=backend_name)
        for t in tickers
    ]
    session.add_all(rows)          # Single multi-row INSERT
    session.commit()
```

---

### HIGH-3: `_show_ml_results()` — N+1 ticker name lookups

**File:** `src/ui/pages/ml_pipeline.py:63-67`
**Impact:** For each stock, a separate DB query. `StockRepository.find_stocks_batch()` already exists but is unused here.

**Current code:**
```python
name_map: dict = {}
for sym in wdf[ticker_col].dropna().unique():
    stock = _repo.find_stock(str(sym))     # 1 query per ticker
    name_map[sym] = stock.name if stock else ""
```

**Fix:**
```python
symbols = [str(s) for s in wdf[ticker_col].dropna().unique()]
stock_map = _repo.find_stocks_batch(symbols)   # Single IN(...) query
name_map = {sym: stock_map[sym].name for sym in symbols if sym in stock_map}
```

---

### HIGH-4: `get_prices()` — Manual DataFrame from ORM loop

**File:** `src/repository.py:67-78`
**Impact:** Each row constructs a dict via list comprehension, then `pd.DataFrame()` iterates again. `pd.read_sql()` does this vectorized in C.

**Fix:**
```python
def get_prices(self, stock_id: int, start: date, end: date) -> pd.DataFrame:
    import pandas as pd
    def _query(s):
        query = text("""
            SELECT date, open, high, low, close, adj_close, volume
            FROM daily_prices
            WHERE stock_id = :sid AND date >= :start AND date <= :end
            ORDER BY date
        """)
        return pd.read_sql(
            query, s.get_bind(),
            params={"sid": stock_id, "start": start, "end": end},
        )
    return self._with_session(_query)
```

---

### MEDIUM-5: `get_tech_indicators()` — Manual dict construction per row

**File:** `src/repository.py:90-107`
**Impact:** Same pattern as get_prices — loop-based dict construction.

**Fix:**
```python
def get_tech_indicators(self, stock_id: int, start: date, end: date) -> pd.DataFrame:
    def _query(s):
        query = text("""
            SELECT date, indicators FROM technical_indicators
            WHERE stock_id = :sid AND date >= :start AND date <= :end
            ORDER BY date
        """)
        df = pd.read_sql(query, s.get_bind(),
                        params={"sid": stock_id, "start": start, "end": end})
        if df.empty:
            return df
        ind_df = pd.json_normalize(df["indicators"].dropna())
        ind_df["date"] = df.loc[ind_df.index, "date"].values
        return ind_df
    return self._with_session(_query)
```

---

### MEDIUM-6: `_upsert_fundamentals()` — Duplicate session open when prefetch missing

**File:** `src/ingestion/pipeline.py:191-198`
**Impact:** When `indicator_last_updated` is None, opens a fresh session just to check freshness. `_prefetch_stock_dates()` already fetches this for all stocks (line 79-83). Remove the fallback query path.

**Fix:** Remove lines 191-198 (`if not force and indicator_last_updated is None:` block). Always pass `indicator_last_updated` from prefetch.

---

## 2. Unnecessary Re-renders (Streamlit)

### CRITICAL-7: Busy loop polling during ML pipeline — `st.rerun()` every 1 second

**File:** `src/ui/pages/ml_pipeline.py:422-425`
**Impact:** While ML pipeline runs (minutes), the entire Streamlit script re-executes every 1 second. All page functions re-query the database every second — the single biggest performance drain in the app.

**Current code:**
```python
if status == "Running":
    import time as _time
    _time.sleep(1)
    ctx.st.rerun()
```

**Fix — use `st.fragment` for log-only auto-refresh (Streamlit 1.33+):**
```python
@ctx.st.fragment(run_every=2)
def _show_pipeline_logs():
    while True:
        try:
            msg = ctx.session_state.ml_log_queue.get_nowait()
        except queue.Empty:
            break
        ctx.session_state.ml_log_lines.append(str(msg))
        if len(ctx.session_state.ml_log_lines) > MAX_LOG_LINES:
            ctx.session_state.ml_log_lines = \
                ctx.session_state.ml_log_lines[-MAX_LOG_LINES:]
    log_text = "\n".join(ctx.session_state.ml_log_lines[-200:])
    ctx.st.code(log_text, language=None)
```

---

### HIGH-8: `st.rerun()` after bulk activate/deactivate

**File:** `src/ui/pages/stock_manager.py:63,68`
**Impact:** After bulk operations, full page re-execution. Filtered results are already in session_state.

**Fix:**
```python
if ctx.st.button("✅ Activate All Filtered"):
    ctx.repo.bulk_set_active(ids, True)
    ctx.st.success(f"Activated {len(ids)} stocks.")
    # Invalidate cached results — next render re-queries
    ctx.session_state.pop("manager_results", None)
    ctx.session_state.pop("manager_ids", None)
    ctx.st.rerun()
```

---

### MEDIUM-9: `st.rerun()` after pipeline submission

**File:** `src/ui/pages/ml_pipeline.py:371,392`
**Impact:** Both Run Pipeline and Predict Only trigger immediate st.rerun() to show "Running" status. This re-executes all pages unnecessarily.

---

## 3. Caching Opportunities

### CRITICAL-10: Zero `@st.cache_data` decorators anywhere in the app

**Impact:** Every Streamlit page render re-executes ALL database queries. Price data, indicators, stock lists, sector lists — all re-fetched on every interaction.

**Fix — add caching wrappers:**
```python
# In a shared module (e.g., src/ui/cache.py) or at top of app.py:
import streamlit as st
from datetime import date

@st.cache_data(ttl=60)
def _cached_count_summary():
    from repository import StockRepository
    return StockRepository().count_summary()

@st.cache_data(ttl=300)
def _cached_get_sectors(table: str = "stock_snapshots"):
    from repository import StockRepository
    return StockRepository().get_sectors(table)

@st.cache_data(ttl=300)
def _cached_get_prices(stock_id: int, start: date, end: date):
    from repository import StockRepository
    return StockRepository().get_prices(stock_id, start, end)

@st.cache_data(ttl=300)
def _cached_get_indicator(stock_id: int):
    from repository import StockRepository
    return StockRepository().get_indicator(stock_id)

@st.cache_data(ttl=60)
def _cached_list_stocks(filters):
    from repository import StockFilters, StockRepository
    return StockRepository().list_stocks(filters)
```

---

### HIGH-11: `load_config()` inside hot per-stock `_upsert_fundamentals()`

**File:** `src/ingestion/pipeline.py:183`
**Impact:** Config reloaded for every stock during ingestion. Config rarely changes. `src/config.py` already caches, but the hot-path call is unnecessary.

**Fix:** Lift `refresh_days` to parameter:
```python
def _upsert_fundamentals(fetcher, stock, force=False,
                         indicator_last_updated=None,
                         refresh_days=7):  # Pass from run_daily_pipeline
    if not force and indicator_last_updated is not None:
        age = (datetime.utcnow() - indicator_last_updated).days
        if age < refresh_days:
            return False
    # Remove the `load_config()` call and fallback session open
```

---

### MEDIUM-12: `_show_ml_results()` re-reads CSV files on every render

**File:** `src/ui/pages/ml_pipeline.py:37-55`
**Impact:** `ml_weights_sector.csv`, `fundamentals.csv`, feature importance CSVs re-parsed every render. Static within a session.

**Fix:**
```python
@st.cache_data(ttl="30m")
def _load_ml_weights(data_dir: str) -> pd.DataFrame | None:
    for candidate in ["ml_weights_sector.csv", "ml_weights_today.csv"]:
        p = Path(data_dir) / candidate
        if p.exists():
            df = pd.read_csv(p)
            df.columns = [c.strip().lower() for c in df.columns]
            return df
    return None
```

---

### MEDIUM-13: `news_cache.py` — Session open/close per tool call

**File:** `src/news_cache.py:50-61,74-91`
**Impact:** Each TradingAgents tool call opens/closes a DB session. Deep evaluation makes many tool calls.

**Fix — use thread-local session:**
```python
import threading

_local = threading.local()

def _get_session():
    if not hasattr(_local, "session") or _local.session is None:
        from database import get_session
        _local.session = get_session()
    return _local.session

def close_thread_session():
    if hasattr(_local, "session") and _local.session is not None:
        _local.session.close()
        _local.session = None
```

---

## 4. Memory Leaks & Resource Issues

### MEDIUM-14: `ml_log_lines` grows unbounded in edge cases

**File:** `src/ui/pages/ml_pipeline.py:409-411`
**Fix:** Use `collections.deque` with `maxlen`:
```python
from collections import deque
# At initialization:
ctx.session_state.ml_log_lines = deque(maxlen=MAX_LOG_LINES)
```

---

### MEDIUM-15: Stale `queue.Queue` objects from old runs

**File:** `src/ui/pages/ml_pipeline.py:349-354`
**Fix:** Signal old queue consumers before replacing:
```python
old = ctx.session_state.get("ml_log_queue")
if old:
    try:
        old.put("__SHUTDOWN__")
    except Exception:
        pass
ctx.session_state.ml_log_queue = queue.Queue()
```

---

## 5. Redundant Computations

### HIGH-16: Duplicate queue-clearing code pattern

**File:** `src/ui/pages/ml_pipeline.py:345-353` and `379-387`
**Fix:** Extract shared helper:
```python
def _reset_ml_state(ctx):
    """Reset ML pipeline state for a new run."""
    ctx.session_state.ml_log_lines = deque(maxlen=MAX_LOG_LINES)
    ctx.session_state.ml_error = None
    ctx.session_state.ml_report_path = None
    ctx.session_state.ml_predict_only_df = None
    old = ctx.session_state.get("ml_log_queue")
    if old:
        while True:
            try:
                old.get_nowait()
            except queue.Empty:
                break
    ctx.session_state.ml_log_queue = queue.Queue()
    ctx.session_state.ml_status = "Running"
    ctx.session_state.ml_start_time = time.time()
```

---

### MEDIUM-17: `_show_ml_backtest()` re-parses backtest JSON every render

**File:** `src/ui/pages/ml_pipeline.py:143-147`
**Fix:**
```python
@st.cache_data(ttl="30m")
def _load_backtest_json(data_dir: str) -> dict | None:
    bt_files = sorted(Path(data_dir).glob("backtest_result_*.json"), reverse=True)
    if not bt_files:
        return None
    with open(bt_files[0]) as f:
        return json.load(f)
```

---

### MEDIUM-18: `load_config()` on every ML pipeline page render

**File:** `src/ui/pages/ml_pipeline.py:280-284`
**Impact:** Config dictionary accessed on every page render. `config.py` already caches after first load, but the call is unnecessary.

**Fix:** Pass config through `AppContext` from app.py entry point.

---

## 6. ORM / Database Configuration Issues

### HIGH-19: All relationships use default lazy loading (N+1 accident risk)

**File:** `src/models.py:38-41`
**Impact:** If any code accesses `stock.daily_prices`, `stock.indicator`, `stock.technical_indicators`, or `stock.snapshot`, SQLAlchemy issues a separate SELECT per access.

**Fix:**
```python
daily_prices: Mapped[list["DailyPrice"]] = relationship(
    back_populates="stock", lazy="raise"
)
indicator: Mapped[Optional["StockIndicator"]] = relationship(
    back_populates="stock", uselist=False, lazy="raise"
)
technical_indicators: Mapped[list["TechnicalIndicator"]] = relationship(
    back_populates="stock", lazy="raise"
)
snapshot: Mapped[Optional["StockSnapshot"]] = relationship(
    back_populates="stock", uselist=False, lazy="raise"
)
```

When eager loading is needed:
```python
from sqlalchemy.orm import joinedload
stock = session.query(Stock).options(
    joinedload(Stock.indicator)
).filter_by(symbol=symbol).first()
```

---

### MEDIUM-20: `pool_pre_ping=True` redundant with `pool_recycle=3600`

**File:** `src/database.py:24`
**Impact:** `pool_pre_ping=True` issues `SELECT 1` before every connection checkout. With `pool_recycle=3600` already handling stale connections, this is redundant overhead.

**Fix:**
```python
_engine = create_engine(url, pool_recycle=3600, pool_size=8, max_overflow=4)
```

---

### LOW-21: `_run_simple_backtest()` — Sequential benchmark price fetches

**File:** `src/finrl_runner.py:308-325`
**Impact:** Each benchmark ticker fetches prices sequentially. For 5 benchmarks, 5 sequential API/DB calls.

**Fix:** Use `ThreadPoolExecutor` for parallel benchmark fetches:
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _fetch_one_benchmark(bm, data_source, start_date, end_date, initial_capital):
    bm_df = pd.DataFrame({"tickers": [bm]})
    bm_prices = data_source.get_price_data(bm_df, start_date, end_date)
    # ... compute cumulative return and metrics ...
    return bm, (benchmark_values, benchmark_metrics)

with ThreadPoolExecutor(max_workers=5) as pool:
    futures = [pool.submit(_fetch_one_benchmark, bm, data_source,
                          start_date, end_date, initial_capital)
               for bm in benchmarks]
    for future in as_completed(futures):
        bm, result = future.result()
        if result:
            benchmark_values[bm], benchmark_metrics[bm] = result
```

---

## Summary: Fix Priority Order

| Priority | ID | Issue | File | Effort |
|----------|----|-------|------|--------|
| **P0** | CRITICAL-7 | st.rerun() polling every 1s during ML pipeline | `ml_pipeline.py:422` | Medium |
| **P0** | CRITICAL-10 | Zero @st.cache_data decorators | All UI pages | Low |
| **P0** | CRITICAL-1 | 3 separate COUNT(*) queries | `repository.py:191` | Low |
| **P1** | CRITICAL-2 | Per-row session.add() in StockSelectionStep | `stock_selection.py:41` | Low |
| **P1** | HIGH-3 | N+1 ticker name lookups in ML results | `ml_pipeline.py:63` | Low |
| **P1** | HIGH-4 | Manual DataFrame from ORM in get_prices() | `repository.py:67` | Low |
| **P1** | HIGH-11 | load_config() inside hot per-stock loop | `ingestion/pipeline.py:183` | Low |
| **P1** | HIGH-19 | All relationships use default lazy loading | `models.py:38-41` | Medium |
| **P2** | HIGH-8 | st.rerun() after bulk ops | `stock_manager.py:63` | Low |
| **P2** | MEDIUM-12 | CSV re-parsing on every render | `ml_pipeline.py:37` | Low |
| **P2** | MEDIUM-20 | pool_pre_ping=True redundancy | `database.py:24` | Low |
| **P3** | MEDIUM-5,6,9,13-18,21 | Various medium/low issues | Multiple files | Low-Medium |

**Estimated total effort:** ~1 day for P0-P1, ~1 day for P2-P3.

**Expected impact:** P0+P1 fixes reduce average page load time by 60-80% and eliminate the 1-second polling drain during ML pipeline execution.
