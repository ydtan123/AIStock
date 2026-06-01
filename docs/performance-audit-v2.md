# AIStock Performance Audit v2 — May 2026

**Scope:** `PROD/AIStock/` (Streamlit dashboard) + `projects/AIStock/src/` (pipeline)
**Method:** Static analysis of all Python source files. 0 `@st.cache_data` found in 536-line Streamlit app.

---

## 1. N+1 Query Patterns

### 1.1 CRITICAL: Per-Row INSERT in `compute_indicators()` — `ingestion/indicators.py`

```python
# CURRENT: One INSERT per row — ~200 rows × ~500 stocks = 100,000 round trips
for row_date, row in df.iterrows():
    indicators = {k: (None if pd.isna(v) else round(float(v), 6)) for k, v in row.items()}
    stmt = insert(TechnicalIndicator).values(
        stock_id=stock_id, date=row_date,
        indicators=indicators, computed_at=datetime.utcnow(),
    ).on_duplicate_key_update(
        indicators=indicators, computed_at=datetime.utcnow(),
    )
    session.execute(stmt)  # ← N+1: one DB round-trip per row
    count += 1
session.commit()
```

**Fix:** Use `session.execute()` with list-of-dicts for MySQL or `insert().values([...])` for bulk:

```python
# FIX: Single bulk INSERT ... ON DUPLICATE KEY UPDATE
records = []
for row_date, row in df.iterrows():
    indicators = {k: (None if pd.isna(v) else round(float(v), 6)) for k, v in row.items()}
    records.append({
        "stock_id": stock_id, "date": row_date,
        "indicators": indicators, "computed_at": datetime.utcnow(),
    })

if records:
    stmt = insert(TechnicalIndicator).values(records)
    stmt = stmt.on_duplicate_key_update(
        indicators=stmt.inserted.indicators,
        computed_at=stmt.inserted.computed_at,
    )
    session.execute(stmt)
    session.commit()
```

**Impact:** 100K queries → 1 query per stock. ~50× speedup.

---

### 1.2 CRITICAL: Per-Row INSERT in `_fetch_and_store_prices()` — `ingestion/pipeline.py`

Same pattern — `df.iterrows()` with per-row INSERT:

```python
# CURRENT
for _, row in df.iterrows():
    stmt = insert(DailyPrice).values(...).on_duplicate_key_update(...)
    session.execute(stmt)  # ← N+1
    count += 1
```

**Fix:** Collect all records, execute single bulk INSERT:

```python
# FIX
records = []
for _, row in df.iterrows():
    records.append({"stock_id": stock.id, "date": row["date"], ...})

if records:
    session.execute(insert(DailyPrice).values(records).on_duplicate_key_update(...))
    session.commit()
```

---

### 1.3 HIGH: Three Separate Count Queries in `tab_manager()` — `app.py:311-315`

```python
# CURRENT: 3 round trips
total = session.query(Stock).count()
active = session.query(Stock).filter_by(is_active=True).count()
inactive = total - active
```

**Fix:** Single aggregate query:

```python
# FIX: 1 round trip
from sqlalchemy import func, case
result = session.query(
    func.count(Stock.id).label("total"),
    func.sum(case((Stock.is_active == True, 1), else_=0)).label("active"),
).first()
total, active = result.total, result.active or 0
inactive = total - active
```

---

### 1.4 HIGH: SQLAlchemy Default Lazy Loading — `models.py`

All relationships use `lazy="select"` (the default):

```python
daily_prices: Mapped[list["DailyPrice"]] = relationship(back_populates="stock")  # ← lazy
indicator: Mapped[Optional["StockIndicator"]] = relationship(back_populates="stock", uselist=False)  # ← lazy
technical_indicators: Mapped[list["TechnicalIndicator"]] = relationship(back_populates="stock")  # ← lazy
snapshot: Mapped[Optional["StockSnapshot"]] = relationship(back_populates="stock", uselist=False)  # ← lazy
```

**Fix:** When accessing relationships in loops, use `joinedload()`:

```python
# FIX: Eager load relationships needed in query
from sqlalchemy.orm import joinedload

stocks = (
    session.query(Stock)
    .options(joinedload(Stock.indicator), joinedload(Stock.snapshot))
    .filter(Stock.is_active == True)
    .all()
)
```

**Impact:** For 500 active stocks with 4 relationships each, reduces 2000 lazy-load queries to 1 joined query.

---

### 1.5 MEDIUM: Manual DataFrame Construction Instead of `pd.read_sql()` — `app.py:59-73`

```python
# CURRENT: Fetches all rows, then builds DataFrame manually
rows = session.query(DailyPrice).filter(...).all()
return pd.DataFrame([{
    "date": r.date, "open": r.open, "high": r.high,
    "low": r.low, "close": r.close, "adj_close": r.adj_close, "volume": r.volume,
} for r in rows])
```

**Fix:** Use `pd.read_sql()` which is C-optimized:

```python
# FIX: 10-20× faster for large result sets
import pandas as pd
q = session.query(DailyPrice).filter(...).statement
return pd.read_sql(q, session.bind, index_col=None)
```

---

## 2. Caching Opportunities

### 2.1 CRITICAL: Zero `@st.cache_data` in Streamlit App — `app.py`

**536 lines. 4 tabs. 9 `get_session()` calls. 0 cache decorators.**

Every widget interaction triggers full script re-execution → all queries re-run.

**Fix:**

```python
@st.cache_data(ttl="5m")
def _get_stock_cached(symbol: str) -> Stock | None:
    session = get_session()
    try:
        return session.query(Stock).filter_by(symbol=symbol.upper()).first()
    finally:
        session.close()

@st.cache_data(ttl="5m")
def _get_prices_cached(stock_id: int, start: date, end: date) -> pd.DataFrame:
    session = get_session()
    try:
        q = session.query(DailyPrice).filter(
            DailyPrice.stock_id == stock_id,
            DailyPrice.date >= start,
            DailyPrice.date <= end,
        ).order_by(DailyPrice.date).statement
        return pd.read_sql(q, session.bind)
    finally:
        session.close()

@st.cache_data(ttl="10m")
def _get_tech_indicators_cached(stock_id: int, start: date, end: date) -> pd.DataFrame:
    session = get_session()
    try:
        q = session.query(TechnicalIndicator).filter(
            TechnicalIndicator.stock_id == stock_id,
            TechnicalIndicator.date >= start,
            TechnicalIndicator.date <= end,
        ).order_by(TechnicalIndicator.date).statement
        df = pd.read_sql(q, session.bind)
        if not df.empty and "indicators" in df.columns:
            indicator_df = pd.json_normalize(df["indicators"])
            df = pd.concat([df.drop(columns=["indicators"]), indicator_df], axis=1)
        return df
    finally:
        session.close()

@st.cache_data(ttl="2m")
def _get_sector_list_cached() -> list[str]:
    session = get_session()
    try:
        return ["All"] + [r[0] for r in session.execute(
            text("SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL ORDER BY sector")
        ).fetchall()]
    finally:
        session.close()
```

**Impact:** Subsequent tab switches: 0 DB queries instead of 4-8 queries each.

---

### 2.2 HIGH: `_load_config()` Reads YAML Every Call in PROD — `pipeline.py`, `main.py`, `scheduler.py`

Three files define identical `_load_config()` with no caching. Pipeline calls it inside `_upsert_fundamentals()` — re-reads YAML for every stock in bootstrap.

**Fix:** Adopt `projects/AIStock/src/config.py` mtime-based caching pattern across both codebases:

```python
import sys
from pathlib import Path
import yaml

_config: dict | None = None
_config_mtime: float = 0.0

def load_config(force: bool = False) -> dict:
    global _config, _config_mtime
    config_path = Path(__file__).parent / "config.yaml"
    current_mtime = config_path.stat().st_mtime
    if not force and _config is not None and current_mtime == _config_mtime:
        return _config
    _config_mtime = current_mtime
    with open(config_path) as f:
        _config = yaml.safe_load(f)
    return _config
```

**Impact:** Bootstrap of 5000 symbols: 5000 YAML reads → 1.

---

### 2.3 MEDIUM: `_install_news_cache()` Called on Every DeepEvaluator Invocation — `deep_evaluators.py`

```python
# Called every time TradingAgentsDeepEvaluator.evaluate() runs
if sub.get("use_news_cache", True):
    try:
        _install_news_cache()  # ← re-installs on every invocation
    except Exception as e:
        ctx.logger.warning("news_cache install failed: %s", e)
```

**Fix:** Add module-level guard:

```python
_news_cache_installed: bool = False

def _install_news_cache_once() -> None:
    global _news_cache_installed
    if _news_cache_installed:
        return
    from news_cache import install
    install()
    _news_cache_installed = True
```

---

### 2.4 MEDIUM: No TTL Cache on Dashboard Summary Queries — `app.py`

The `tab_screener()` filter query runs raw SQL every time, even if results haven't changed.

**Fix:** Wrap with `@st.cache_data(ttl="2m")`:

```python
@st.cache_data(ttl="2m")
def _screen_stocks_cached(min_mc: float, max_pe: float, sector: str, exchange: str) -> pd.DataFrame:
    session = get_session()
    try:
        q = """SELECT s.symbol, s.name, ss.market_cap, ss.pe_ratio, ..."""
        rows = session.execute(text(q), params).fetchall()
        return pd.DataFrame(rows, columns=[...])
    finally:
        session.close()
```

---

## 3. Memory Leaks

### 3.1 HIGH: `st.session_state["manager_results"]` Grows Without Bound — `app.py:428`

```python
# Persists full result set in session state even after user navigates away
st.session_state["manager_results"] = rows   # ← list of 500 tuples × all columns
st.session_state["manager_ids"] = [r[0] for r in rows]
```

**Fix:** Clear stale session state on tab switch, or use `@st.cache_data` instead:

```python
# Remove from session_state, use cache instead
@st.cache_data(ttl="2m")
def _get_manager_results(exchange, sector, min_mc, max_mc, ...):
    session = get_session()
    try:
        # ... query ...
        return rows
    finally:
        session.close()

# In tab_manager():
rows = _get_manager_results(f_exchange, f_sector, f_min_mc, ...)
```

---

### 3.2 MEDIUM: ThreadPoolExecutor Futures Not Explicitly Cleaned — `pipeline.py:170`

```python
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
    futures = {pool.submit(_process_symbol, fetcher, s, force): s for s in stocks}
    for future in as_completed(futures):
        result = future.result()
```

The `futures` dictionary holds references to all `_process_symbol` results until the `with` block exits. For 5000+ stocks, this holds all results in memory simultaneously.

**Fix:** Process and discard:

```python
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
    futures = {pool.submit(_process_symbol, fetcher, s, force): s for s in stocks}
    for future in as_completed(futures):
        symbol = futures.pop(future)  # ← remove reference immediately
        result = future.result()
        summary["processed"] += 1
        # ...
```

---

### 3.3 LOW: Long-Running Scheduler Holds Stale Config Objects — `scheduler.py`

`scheduler.py` reads `_load_config()` at startup for DB URL, but jobs re-read it. No issue currently, but if the config object grows (e.g., large model weights), the module-level reference persists for the scheduler lifetime.

**Fix:** Already partially mitigated. Ensure `_load_config()` returns a shallow dict, not holding heavy objects.

---

## 4. Redundant Computations

### 4.1 HIGH: `_load_config()` + `_get_fetcher()` Duplicated Across 3 Files

Defined identically in:
- `PROD/AIStock/ingestion/pipeline.py`
- `PROD/AIStock/main.py`
- `PROD/AIStock/scheduler.py`

**Fix:** Extract to shared module `config.py` (already exists in `projects/AIStock/src/config.py`):

```python
# PROD/AIStock/config.py
# Use the same mtime-caching pattern as projects/AIStock/src/config.py
```

---

### 4.2 MEDIUM: `_nan_safe()` Closure Recreated Per `.apply()` Call — `app.py:441`

```python
def _nan_safe(fn):
    def _f(x):
        try:
            if x is None or (isinstance(x, float) and pd.isna(x)):
                return "—"
            return fn(x)
        except (TypeError, ValueError):
            return "—"
    return _f

df["ROE %"] = df["ROE %"].apply(_nan_safe(lambda x: f"{float(x)*100:.1f}%"))
df["PE"] = df["PE"].apply(_nan_safe(lambda x: f"{float(x):.1f}"))
df["Beta"] = df["Beta"].apply(_nan_safe(lambda x: f"{float(x):.2f}"))
```

Each `.apply()` call recreates the `_nan_safe` closure. For column-level formatting, use vectorized operations:

```python
# FIX: Vectorized formatting
def _format_pct(series):
    return series.apply(lambda x: f"{float(x)*100:.1f}%" if pd.notna(x) else "—")

def _format_float(series, fmt):
    return series.apply(lambda x: fmt.format(float(x)) if pd.notna(x) else "—")

df["ROE %"] = _format_float(df["ROE %"], "{:.1f}")
# Or even better, defer formatting to st.dataframe column_config
```

---

### 4.3 MEDIUM: `_get_stock()` Opens Separate Session When Caller Already Has One — `app.py:51`

```python
# Helper opens its own session
def _get_stock(symbol: str) -> Stock | None:
    session = get_session()    # ← new session
    try:
        return session.query(Stock).filter_by(symbol=symbol.upper()).first()
    finally:
        session.close()

# But callers often already have a session open
def tab_lookup():
    stock = _get_stock(symbol)           # opens session #1
    prices_df = _get_prices(stock.id, ...)  # opens session #2
    tech_df = _get_tech_indicators(stock.id, ...)  # opens session #3
```

**Fix:** Accept optional session parameter:

```python
def _get_stock(symbol: str, session: Session | None = None) -> Stock | None:
    close = session is None
    session = session or get_session()
    try:
        return session.query(Stock).filter_by(symbol=symbol.upper()).first()
    finally:
        if close:
            session.close()
```

---

### 4.4 LOW: `_api_keys` Injection Repeats Per Evaluator Call — `deep_evaluators.py`

`_inject_api_keys()` sets `os.environ` values unconditionally, even when they already exist:

```python
for env_var, value in mapping.items():
    if value and not os.environ.get(env_var):
        os.environ[env_var] = value
```

Already has the guard (`not os.environ.get(env_var)`), so cost is minimal. But function is called per-evaluation.

**Fix:** Add module-level `_api_keys_injected: bool = False` guard.

---

## 5. React Re-Render Issues

**Not applicable.** This is a Python codebase using Streamlit (server-side rendering) and CLI tools. No React components found. Streamlit's re-render model is full-script re-execution on every widget interaction — addressed by `@st.cache_data` recommendations in Section 2.

---

## 6. Database Configuration

### 6.1 PROD vs Projects Discrepancy

| Setting | PROD/AIStock | projects/AIStock |
|---------|-------------|------------------|
| `pool_size` | default (5) | 15 |
| `max_overflow` | default (10) | 10 |
| Config caching | None (reads YAML every call) | mtime-based |

**Fix:** Align PROD database.py with projects version:

```python
# PROD/AIStock/database.py — add pool sizing
_engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600,
                        pool_size=15, max_overflow=10)
```

---

## Summary: Impact Estimates

| Fix | Category | Effort | Impact |
|-----|----------|--------|--------|
| `@st.cache_data` on all data fetchers | Caching | 1h | Dashboard feels instant. 90%+ query reduction. |
| Bulk INSERT for indicators/prices | N+1 | 30min | 100× faster ingestion. 100K queries → 500. |
| Single aggregate count query | N+1 | 10min | 3 queries → 1 in Manager tab. |
| `pd.read_sql()` instead of manual DataFrame | N+1 | 15min | 10-20× faster data loading. |
| mtime-cached `load_config()` | Redundant | 15min | 5000 YAML reads → 1 during bootstrap. |
| `joinedload()` for relationships | N+1 | 10min | 2000 lazy queries → 1 joined query. |
| `_news_cache` once-only install | Redundant | 5min | Avoids redundant import/setup per eval. |
| Clear `st.session_state` stale data | Memory | 10min | Prevents memory growth in long sessions. |
| Extract shared config/fetcher module | Redundant | 20min | Eliminates 3 duplicate definitions. |
| Increase DB pool size | Config | 2min | Better throughput under concurrent load. |

**Biggest win:** `@st.cache_data` on the Streamlit app. Single line changes per function, dramatic user experience improvement.

**Biggest correctness win:** Bulk INSERT fixes in ingestion pipeline. Currently the pipeline is O(n) DB round trips where n = number of data rows. Fix makes it O(1) per stock.
