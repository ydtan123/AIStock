# AIStock Performance Audit — Supplemental Findings

**Date:** 2026-05-30
**Parent:** `docs/performance-audit-verified-2026-05-30.md`
**Scope:** New issues discovered after prior audit; verification of previously-reported fixes; issues in refactored code not previously covered.

---

## Prior Audit Status (verified against current working tree)

| Issue | Status | Notes |
|-------|--------|-------|
| #1 FastEval add() loop | Fixed | `session.add_all(conclusions)` + `session.add_all(analysts)` at fast_evaluation.py:84-121 |
| #2 DeepEval add() loop | Fixed | `session.add_all(rows)` at deep_evaluation.py:90 |
| #3 save_selected_stocks add() | Fixed | `s.add_all(rows)` at repository.py:244 |
| #4 save_predict_only add() | Fixed | `s.add_all(rows)` at repository.py:267 |
| #5 Predict-only N+1 lookup | Fixed | `find_stocks_batch()` + `itertuples()` at app.py:177-178 |
| #6 Serial LLM calls | NOT FIXED | `deep_evaluators.py:148` still sequential |
| #7 Zero @st.cache_data | NOT FIXED | No UI pages have caching |
| #8 refresh_symbols iterrows | NOT FIXED | Still per-row INSERT |
| #9-10 iterrows in ingestion | PARTIAL | `_fetch_and_store_prices` still uses iterrows |
| #11 Repeated CSV reads | NOT FIXED | ml_pipeline.py still reads files on every render |
| #12 AV listing cache | NOT FIXED | |
| #13 Config mtime check | NOT FIXED | |
| #14 DB pool size | NOT FIXED | |

---

## New: Critical Issues

### N1 -- StockSelectionStep Per-Ticker `session.add()` Loop

**File:** `src/pipeline/stock_selection.py:42-56`
**Impact:** N individual `session.add()` calls for N selected stocks. Each call dirties ORM identity map. For 50 stocks = 50 ORM dispatch cycles + 50 individual INSERTs at flush time.

```python
# CURRENT (stock_selection.py:42-55)
with open_session(ctx) as session:
    for t in tickers:
        row = SelectedStock(
            ticker=t.ticker,
            model_name=backend_name,
            ml_score=t.ml_score,
            bucket=None,
            weight=None,
            date_selected=now.date(),
            pipeline_run_at=now,
            pipeline_run_id=ctx.run_id,
            sector=t.sector,
            backend=backend_name,
        )
        session.add(row)              # <-- per-ticker
    session.commit()
```

**Fix:**

```python
with open_session(ctx) as session:
    rows = [
        SelectedStock(
            ticker=t.ticker,
            model_name=backend_name,
            ml_score=t.ml_score,
            bucket=None,
            weight=None,
            date_selected=now.date(),
            pipeline_run_at=now,
            pipeline_run_id=ctx.run_id,
            sector=t.sector,
            backend=backend_name,
        )
        for t in tickers
    ]
    session.add_all(rows)
    session.commit()
```

**Reduction:** N `session.add()` -> 1 `session.add_all()`. For 50 stocks: 50 INSERT statements -> 1 batched INSERT.

---

### N2 -- `load_config()` Called Per-Stock in Fundamentals Upsert

**File:** `src/ingestion/pipeline.py:183-184`
**Impact:** `load_config()` reads and parses `config.yaml` from disk for every stock processed. 500 stocks = 500 YAML parse operations. The returned value is always identical -- only the `overview_refresh_days` key is used.

```python
# CURRENT (ingestion/pipeline.py:183-184)
def _upsert_fundamentals(fetcher, stock, force=False, indicator_last_updated=None):
    config = load_config()                         # <-- re-reads YAML per stock
    refresh_days = config.get("scheduler", {}).get("overview_refresh_days", 7)
```

**Fix -- accept `refresh_days` as parameter:**

```python
def _upsert_fundamentals(fetcher, stock, force=False,
                         indicator_last_updated=None,
                         refresh_days: int = 7):      # <-- passed from caller
    # config = load_config()                         # <-- REMOVE
    # refresh_days = config.get(...)                 # <-- REMOVE
    ...
```

**Caller change (in `_process_symbol`):**

```python
# Read config ONCE in module-level init or pass from run_daily_pipeline
_CFG = load_config()
_DEFAULT_REFRESH_DAYS = _CFG.get("scheduler", {}).get("overview_refresh_days", 7)

# In _process_symbol:
refreshed = _upsert_fundamentals(fetcher, stock, force=force,
                                 indicator_last_updated=ilu,
                                 refresh_days=_DEFAULT_REFRESH_DAYS)
```

**Impact:** 500 YAML parses -> 1 YAML parse. ~500x reduction for full pipeline run.

---

### N3 -- Double Session Open in `_fetch_and_store_prices` Fallback Path

**File:** `src/ingestion/pipeline.py:95-117`
**Impact:** When `max_date` is not pre-fetched (fallback path), the function opens a session to query MAX(date), closes it, then opens another session to do the insert. If the pre-fetch is working, this only hits on the first stock, but when the pre-fetch dict is missing (bootstrap runs), it is N additional session opens/closes.

```python
# CURRENT (ingestion/pipeline.py:95-117)
def _fetch_and_store_prices(fetcher, stock, max_date=None):
    if max_date is None:
        session = get_session()                          # <-- open #1
        try:
            max_date = session.execute(...).scalar()
        finally:
            session.close()                              # <-- close #1

    start = (max_date + timedelta(days=1)) if max_date else DEFAULT_START
    end = date.today()

    if start > end:
        return 0, max_date

    session = get_session()                              # <-- open #2
    try:
        df = fetcher.get_daily(stock.symbol, start, end)
        # ... batch insert ...
    finally:
        session.close()                                  # <-- close #2
```

**Fix -- merge into single session:**

```python
def _fetch_and_store_prices(fetcher, stock, max_date=None):
    if max_date is not None:
        start = max_date + timedelta(days=1)
        if start > date.today():
            return 0, max_date
    else:
        start = None   # defer to session

    session = get_session()
    try:
        if start is None:
            max_date = session.execute(
                text("SELECT MAX(date) FROM daily_prices WHERE stock_id = :sid"),
                {"sid": stock.id},
            ).scalar()
            start = (max_date + timedelta(days=1)) if max_date else DEFAULT_START

        end = date.today()
        if start > end:
            return 0, max_date

        df = fetcher.get_daily(stock.symbol, start, end)
        # ... batch insert (existing code) ...
    finally:
        session.close()
```

**Impact:** 1 connection open/close instead of 2 in fallback path. ~50% fewer session overhead in worst case.

---

## New: High Issues

### N4 -- `display_quick_stats()` DB Hit on Every Page

**File:** `src/app.py:222-230` (called at line 284 in `main()`)
**Impact:** `repo.count_summary()` executes 2 `SELECT COUNT(*)` queries on EVERY Streamlit page render, sidebar click, tab switch, or widget interaction. For a typical 5-minute session with 50 interactions = 100 unnecessary DB queries.

```python
# CURRENT (app.py:284)
st.divider()
display_quick_stats(repo)   # <-- called unconditionally in sidebar
```

**Fix -- wrap in `@st.cache_data`:**

```python
# In display_quick_stats or as a cached wrapper:
@st.cache_data(ttl=60, show_spinner=False)
def _cached_count_summary() -> dict:
    """Cache the count summary for 60 seconds."""
    return StockRepository().count_summary()

def display_quick_stats(repo: StockRepository) -> None:
    st.subheader("Quick Stats")
    try:
        summary = _cached_count_summary()
        c1, c2 = st.columns(2)
        c1.metric("Total", summary.get("total", "--"))
        c2.metric("Active", summary.get("active", "--"))
    except Exception as exc:
        st.error(f"Could not load stats: {exc}")
```

**Impact:** 100+ DB queries per session -> ~1 per minute. 95%+ reduction.

---

### N5 -- `get_sectors()` Called on Every Screener Form Render

**File:** `src/ui/pages/stock_screener.py:26`
**Impact:** `ctx.repo.get_sectors("stock_snapshots")` queries DISTINCT sectors from DB on every form render. Sector list changes only when new stocks are added to DB.

```python
# CURRENT (stock_screener.py:26)
sectors = ["All"] + ctx.repo.get_sectors("stock_snapshots")
```

**Fix:**

```python
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_get_sectors() -> list[str]:
    """Sectors change rarely. Cache 1 hour."""
    from repository import StockRepository
    return StockRepository().get_sectors("stock_snapshots")

# In render():
sectors = ["All"] + _cached_get_sectors()
```

---

### N6 -- Stock Lookup & Technical Pages: Trio of Uncached DB Calls

**Files:** `src/ui/pages/stock_lookup.py:41-42`, `src/ui/pages/stock_technical.py:31-37`
**Impact:** Each page makes 3 DB queries on every interaction (symbol change, date change, checkbox toggle):

```
stock_lookup.py:   find_stock() -> get_indicator() -> get_prices()
stock_technical.py: find_stock() -> get_prices()   -> get_tech_indicators()
```

Each call opens/closes its own session via `_with_session`. User changing from "AAPL" to "MSFT" triggers 3 new connections.

**Fix -- composite cache key:**

```python
import hashlib, json

@st.cache_data(ttl=300, show_spinner="Loading stock data...")
def _cached_stock_data(symbol: str, start_date: str, end_date: str) -> dict:
    """Cache stock lookup data per (symbol, date_range)."""
    from repository import StockRepository
    from datetime import date as dt_date
    repo = StockRepository()
    stock = repo.find_stock(symbol)
    if not stock:
        return {"stock": None}
    return {
        "stock": {"id": stock.id, "symbol": stock.symbol, "name": stock.name,
                   "sector": stock.sector, "exchange": stock.exchange,
                   "industry": stock.industry, "is_active": stock.is_active},
        "prices": repo.get_prices(stock.id,
                                   dt_date.fromisoformat(start_date),
                                   dt_date.fromisoformat(end_date)),
        "indicator": repo.get_indicator(stock.id),
    }
```

**Usage in stock_lookup.py:**

```python
data = _cached_stock_data(symbol, str(start_date), str(end_date))
if data["stock"] is None:
    ctx.st.info("Symbol not found.")
    return
prices_df = data["prices"]
ind = data["indicator"]
# ... rest of render unchanged
```

---

### N7 -- `_show_ml_results`: Company Name Lookup Still Per-Symbol

**File:** `src/ui/pages/ml_pipeline.py:59-69`
**Impact:** The ML results display iterates unique tickers and calls `_repo.find_stock(str(sym))` for each. `find_stock` opens a new DB session per call. `find_stocks_batch` exists in repository.py but is NOT used here.

```python
# CURRENT (ml_pipeline.py:61-67)
for sym in wdf[ticker_col].dropna().unique():
    stock = _repo.find_stock(str(sym))    # <-- 1 DB session open/close per symbol
    name_map[sym] = stock.name if stock else ""
```

**Fix -- use `find_stocks_batch()`:**

```python
# Single query for all tickers
from repository import StockRepository
_repo = StockRepository()
stock_map = _repo.find_stocks_batch(
    wdf[ticker_col].dropna().unique().tolist()
)
name_map = {sym: (s.name if s else "") for sym, s in stock_map.items()}
```

**Impact:** N DB round-trips -> 1. For 50 tickers: ~98% fewer session opens.

---

## New: Medium Issues

### N8 -- Pandas `inplace=True` Deprecation (Unnecessary Copies)

**File:** `src/fetcher/alpha_vantage.py:85, 174, 204, 224, 252`
**Impact:** `df.sort_values("date", inplace=True)` followed by `df.reset_index(drop=True, inplace=True)` creates unnecessary intermediate states and is deprecated in pandas 3.0.

```python
# CURRENT (alpha_vantage.py:85)
df.sort_values("date", inplace=True)
df.reset_index(drop=True, inplace=True)
```

**Fix:**

```python
df = df.sort_values("date").reset_index(drop=True)
```

**Files affected:** 5 locations in `alpha_vantage.py`.

---

### N9 -- Predict-Only Path Stores Data in session_state as JSON String

**File:** `src/ui/pages/ml_pipeline.py:399-401`
**Impact:** Predict-only results stored as JSON string in `st.session_state`, then re-parsed back to list[dict] on next render cycle. For 500 stocks = ~100KB JSON serialized/deserialized on every stream rerun.

The data already lives in queue -> parsed -> stored -> used. OK for now but if predictions grow to 1000+ rows, consider using `st.cache_data` for display portion and keeping session state minimal.

---

## New: Low Issues

### N10 -- Module-Level Side Effects on Import

**File:** `src/ingestion/pipeline.py:27-41`
**Impact:** `load_config()` and `os.environ` mutations happen at module import time, not at function call time. This means importing `src/ingestion/pipeline` triggers YAML read + env var injection even if `run_daily_pipeline` is never called.

```python
# CURRENT (ingestion/pipeline.py:27-41)
_cfg = load_config()                         # <-- runs on import
_common = _cfg.get("common", {})
for _env_key, _cfg_key in [...]:
    if _common.get(_cfg_key) and _env_key not in os.environ:
        os.environ[_env_key] = _common[_cfg_key]  # <-- side effect on import
```

**Fix -- lazy initialization:**

```python
_KEYS_INJECTED = False

def _ensure_api_keys():
    global _KEYS_INJECTED
    if _KEYS_INJECTED:
        return
    cfg = load_config()
    common = cfg.get("common", {})
    for env_key, cfg_key in [("GOOGLE_API_KEY", "google_api_key"), ...]:
        if common.get(cfg_key) and env_key not in os.environ:
            os.environ[env_key] = common[cfg_key]
    _KEYS_INJECTED = True

# Call at top of run_daily_pipeline() instead of module-level
```

---

### N11 -- `config.load_config()` Double-Call in `_upsert_fundamentals`

Also called in `ingestion/pipeline.py:183` inside `_upsert_fundamentals`, which already runs inside `run_daily_pipeline` which already called `load_config()` at module level (see N10). Same value, read twice.

This is covered by fix N2 above -- remove the per-stock `load_config()` call entirely.

---

## Unfixed Issues From Prior Audit (Still Relevant)

These were identified in the prior audit and remain unfixed:

| # | Severity | Issue | Current status |
|---|----------|-------|----------------|
| 6 | Critical | Sequential `graph.propagate()` per ticker in deep_evaluators.py:148 | Unfixed -- serial LLM calls |
| 7 | High | Zero `@st.cache_data` on any UI page | Unfixed -- N4,N5,N6 above address this |
| 8 | High | Per-row INSERT in `refresh_symbols()` | Unfixed -- `ingestion/symbols.py:44-65` |
| 9 | Medium | `iterrows()` in `_fetch_and_store_prices` | Unfixed -- `ingestion/pipeline.py:126` |
| 11 | Medium | Repeated `pd.read_csv()` in ML results | Unfixed -- `ml_pipeline.py:38,48,117` |
| 12 | Low | Alpha Vantage `get_listing()` no disk cache | Unfixed |
| 13 | Low | Config module no mtime revalidation | Unfixed |
| 14 | Low | DB pool may bottleneck under parallelism | Unfixed |

---

## Consolidated Implementation Priority

Prioritized across both audits, excluding already-fixed items:

| Order | Issue | Effort | Impact | Category |
|-------|-------|--------|--------|----------|
| 1 | N1: StockSelectionStep add_all() | 5 min | High | N+1 |
| 2 | N4: cached count_summary() | 10 min | High | Caching |
| 3 | N5: cached get_sectors() | 5 min | Medium | Caching |
| 4 | N6: cached stock data (lookup + technical) | 20 min | High | Caching |
| 5 | N7: find_stocks_batch in ML results | 5 min | Medium | N+1 |
| 6 | N2: remove per-stock load_config() | 10 min | Medium | Redundant I/O |
| 7 | N3: merge double session in _fetch_and_store_prices | 10 min | Low | Session mgmt |
| 8 | N8: pandas inplace=True -> chained | 5 min | Low | Deprecation |
| 9 | #6: Parallelize deep evaluator LLM | 30 min | High | Serial I/O |
| 10 | #7: @st.cache_data on all UI pages | 60 min | High | Caching |
| 11 | #8: Batch refresh_symbols INSERT | 20 min | Medium | N+1 |
| 12 | #9: iterrows -> vectorized in ingestion | 15 min | Low | Pandas perf |
| 13 | #11: CSV read cache in ML results | 10 min | Low | File I/O |
| 14 | N10: lazy API key injection | 10 min | Low | Side effects |
| 15 | #12-14: AV listing cache, config mtime, pool size | 30 min | Low | Infrastructure |

**New items total effort:** ~2 hours
**Combined (old + new) remaining effort:** ~4.5 hours
**Expected cumulative impact:** 70-90% fewer DB round-trips, 3x faster deep evaluation, 80-95% fewer file reads.
