# AIStock Performance Analysis v8

**Date:** 2026-05-30
**Scope:** Full codebase (71 files)
**Categories:** N+1 queries, caching gaps, memory leaks, redundant computations

---

## CRITICAL

### 1. Alpha Vantage API calls have no application-level cache

**File:** `src/fetcher/alpha_vantage.py:27-56`
**Type:** Caching gap

Every `_get()` call hits the Alpha Vantage API directly. Free tier: 5 calls/min, 500/day. With 5,000+ active stocks, rate limits are the primary ingestion bottleneck.

**Fix:** Add TTL-based in-memory cache keyed on (function, symbol, params_hash):

```python
# In alpha_vantage.py AlphaVantageFetcher class
def _cached_get(self, params: dict, retries: int = 3) -> dict | str:
    import hashlib
    raw = f"{params.get('function')}:{params.get('symbol')}:{params.get('outputsize', 'compact')}"
    key = hashlib.md5(raw.encode()).hexdigest()
    if key in self._cache:
        cached_time, cached_data = self._cache[key]
        if time.time() - cached_time < 300:
            return cached_data
    result = self._get(params, retries)
    self._cache[key] = (time.time(), result)
    return result
```

**Estimated savings:** 50-70% reduction in redundant API calls within a single pipeline run.

---

## HIGH

### 2. N+1 stock name lookup in ML Pipeline results page

**File:** `src/ui/pages/ml_pipeline.py:86-95`
**Type:** N+1 query + missing caching

Iterates over every unique ticker and calls `_repo.find_stock(str(sym))` one at a time. Each call opens/closes a session. For 200 stocks: 200 queries.

**Fix already exists** — replace loop with single `find_stocks_batch()` call:

```python
# Replace lines 88-95
ticker_col = next((c for c in ["tic", "ticker", "gvkey"] if c in wdf.columns), None)
if ticker_col:
    syms = wdf[ticker_col].dropna().unique().tolist()
    stock_map = _repo.find_stocks_batch(syms)
    name_map = {sym: (stock_map.get(sym.upper()).name
                      if stock_map.get(sym.upper()) else "")
                for sym in syms}
    wdf["company"] = wdf[ticker_col].map(name_map)
```

**Estimated savings:** N queries → 1 query. For 200 stocks: 199 queries eliminated.

### 3. N+1 per-ticker `get_prices()` in predict-only thread

**File:** `src/app.py:183-190`
**Type:** N+1 query

For each prediction row, calls `_repo.get_prices(stock.id, dd, today)` which opens a session and runs `SELECT ... FROM daily_prices WHERE stock_id = ?`.

**Fix:** Add batch price fetch to repository:

```python
# src/repository.py — add to StockRepository
def get_prices_batch(self, stock_ids: list[int],
                     start_date: date, end_date: date) -> dict[int, pd.DataFrame]:
    def _query(s):
        rows = (
            s.query(DailyPrice)
            .filter(DailyPrice.stock_id.in_(stock_ids),
                    DailyPrice.date >= start_date,
                    DailyPrice.date <= end_date)
            .order_by(DailyPrice.stock_id, DailyPrice.date)
            .all()
        )
        result: dict[int, list] = {}
        for r in rows:
            result.setdefault(r.stock_id, []).append({
                "date": r.date, "open": r.open, "high": r.high,
                "low": r.low, "close": r.close, "adj_close": r.adj_close,
                "volume": r.volume,
            })
        return {sid: pd.DataFrame(recs) for sid, recs in result.items()}
    return self._with_session(_query)
```

Then in `app.py`, replace the `for row in pred_df.itertuples():` + `_repo.get_prices()` loop with a single batched call.

**Estimated savings:** N queries → 1 query.

### 4. Streamlit sidebar stats uncached

**File:** `src/app.py:227-235`
**Type:** Missing caching

`repo.count_summary()` fires two `SELECT COUNT(*)` queries on every page render and widget interaction. The sidebar renders on all 9 pages.

**Fix:**

```python
@st.cache_data(ttl=60, show_spinner=False)
def _cached_count_summary() -> dict:
    from repository import StockRepository
    return StockRepository().count_summary()
```

**Estimated savings:** ~18 queries/min → ~1 query/min.

### 5. Yahoo Finance fetcher has no cache

**File:** `src/fetcher/yahoo.py:10-57`
**Type:** Missing API cache

`yf.Ticker(symbol).history()` and `yf.Ticker(symbol).info` create new HTTP requests per call.

**Fix:** Add `lru_cache`:

```python
from functools import lru_cache

class YahooFetcher(FetcherBase):
    @lru_cache(maxsize=256)
    def _cached_info(self, symbol: str) -> dict:
        return yf.Ticker(symbol).info

    @lru_cache(maxsize=128)
    def _cached_history(self, symbol: str, start_str: str, end_str: str):
        df = yf.Ticker(symbol).history(start=start_str, end=end_str, auto_adjust=False)
        return df if not df.empty else None
```

### 6. Duplicated financial ratio computation

**Files:** `src/finrl_runner.py:183-194`, `src/ml_bucket_selector.py:72-87`
**Type:** Redundant code

Identical 12-line block computing `fcf_to_ocf`, `ocf_ratio`, `solvency_ratio` in both modules.

**Fix:** Extract to shared utility:

```python
# src/utils.py
def add_derived_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived financial ratios in place. Idempotent (checks column existence)."""
    if "fcf_to_ocf" not in df.columns:
        df["fcf_to_ocf"] = df["free_cash_flow"] / df["operating_cashflow"].replace(0, float("nan"))
    if "ocf_ratio" not in df.columns:
        df["ocf_ratio"] = df["operating_cashflow"] / df["total_revenue"].replace(0, float("nan"))
    if "solvency_ratio" not in df.columns:
        df["solvency_ratio"] = df["net_income"] / df["total_assets"].replace(0, float("nan"))
    return df
```

### 7. Duplicated `_inject_api_keys` function

**Files:** `src/pipeline/backends/fast_evaluators.py:72-89`, `src/pipeline/backends/deep_evaluators.py:55-71`
**Type:** Redundant code

Identical 18-line API key injection logic duplicated across two backend modules.

**Fix:** Extract to `src/utils.py` and import from both backends.

### 8. Indicator full-recompute on unchanged data

**File:** `src/ingestion/indicators.py:46-138`
**Type:** Redundant computation

`_needs_full_backfill()` triggers full recomputation (260 days, 20+ TA indicators) even when only most recent day changed.

**Fix:** Use incremental recompute:

```python
# In ingestion/pipeline.py _process_symbol()
if _needs_full_backfill(first_indicator_date=fid, first_price_date=fpd):
    since = fid if fid else None  # start from last indicator date, not epoch
    result["indicators"] = compute_indicators(stock.id, since_date=since)
```

---

## MEDIUM

### 9. `load_config()` called per-stock in hot path

**File:** `src/ingestion/pipeline.py:170`
**Type:** Redundant computation

`_upsert_fundamentals()` calls `load_config()` for every stock. Each call stats the config file. With 300 active stocks: 300 stat() syscalls per run.

**Fix:** Reuse module-level `_cfg`:

```python
# At top of ingestion/pipeline.py, after _cfg = load_config()
_REFRESH_DAYS = _cfg.get("scheduler", {}).get("overview_refresh_days", 7)

# In _upsert_fundamentals(): replace config.get(...) with _REFRESH_DAYS
```

### 10. Streamlit `stock_detail.py` dialog uncached per-stock DB calls

**File:** `src/ui/pages/stock_detail.py:11-18`
**Type:** Missing caching

Every time a user clicks a stock row: `find_stock()`, `get_indicator()`, `get_snapshot()` — 3 SQL queries per click.

**Fix:**

```python
@st.cache_data(ttl=60, show_spinner=False)
def _cached_stock_detail(symbol: str) -> dict | None:
    from repository import StockRepository
    _repo = StockRepository()
    stock = _repo.find_stock(symbol)
    if not stock:
        return None
    return {
        "stock": stock,
        "indicator": _repo.get_indicator(stock.id),
        "snapshot": _repo.get_snapshot(stock.id),
    }
```

### 11. `session.add()` in loop in stock_selection step

**File:** `src/pipeline/stock_selection.py:42-56`
**Type:** Write anti-pattern

Calls `session.add(row)` inside a loop instead of `session.add_all(rows)` (all other pipeline steps use `add_all`).

**Fix:**

```python
rows = [SelectedStock(
    ticker=t.ticker, model_name=backend_name, ml_score=t.ml_score,
    bucket=None, weight=None, date_selected=now.date(),
    pipeline_run_at=now, pipeline_run_id=ctx.run_id,
    sector=t.sector, backend=backend_name,
) for t in tickers]
session.add_all(rows)
session.commit()
```

### 12. `ml_log_lines` capped with O(n) slice-copy

**File:** `src/ui/pages/ml_pipeline.py:427-429`
**Type:** Performance anti-pattern

After 1000 entries, every append triggers a copy of the entire list.

**Fix:** Use `collections.deque(maxlen=1000)`:

```python
from collections import deque
# Init: ctx.session_state.ml_log_lines = deque(maxlen=1000)
# Append: ctx.session_state.ml_log_lines.append(str(msg))
# Render: "\n".join(ctx.session_state.ml_log_lines)
```

### 13-20. Additional Medium/Low findings

| # | File | Line | Issue | Fix |
|---|------|------|-------|-----|
| 13 | `paper_trading.py` | 29-51 | CSV re-read on every render | `@st.cache_data(ttl=3600)` |
| 14 | `strategy_backtest.py` | 20-34 | JSON re-read on every render | `@st.cache_data(ttl=3600)` |
| 15 | `ml_bucket_selector.py` | 110,127,149 | Redundant `.copy()` after boolean indexing | Remove `.copy()` calls |
| 16 | `ml_pipeline.py` | 89,100,121 | Repeated column-name detection | Detect once at function top |
| 17 | `app.py`, `finrl_runner.py`, `full_pipeline.py` | 17,31,13 | Duplicated `sys.path` setup | Extract to `src/_path_setup.py` |
| 18 | `models.py` | 38-41 | No `selectinload`/`joinedload` strategies | Add when relationship navigation introduced |
| 19 | `indicators.py` | 97 | `itertuples()._asdict()` per-row allocation | Access columns directly on named tuple |
| 20 | `repository.py` | 272-300 | `get_latest_selected_stocks` 2-query pattern | Combine with subquery |
| 21 | `main.py` | 93-95 | Per-symbol `_ensure_stock()` in CLI batch | Use `find_stocks_batch()` |

---

## Memory Leaks: NONE FOUND

All resources properly managed:
- SQLAlchemy sessions: `try/finally` + `.close()` everywhere
- ThreadPoolExecutors: `with` blocks (context managers)
- File handles: `with open(...)` throughout
- Streamlit session state: bounded (1000-line cap on logs, queue replaced per run)
- No matplotlib figure leaks (matplotlib not used)
- No global accumulators beyond TTL config cache

**One concern:** `TradingAgentsGraph` instance shared across threads in `src/pipeline/backends/deep_evaluators.py:142-158`. If `graph.propagate()` modifies internal state, this could cause data races. Verify thread safety.

---

## Summary

| Severity | Count | Key Items |
|----------|-------|-----------|
| **Critical** | 1 | AV API cache missing |
| **High** | 7 | N+1 stock lookups (2x), uncached sidebar/API, duplicated code (2x), indicator recompute |
| **Medium** | 7 | config per-stock, session.add loop, uncached UI pages (3x), deque for logs, redundant .copy(), column detection |
| **Low** | 6 | itertuples allocations, 2-query pattern, CLI batch N+1, eager-loading gap, sys.path duplication |

**Top 5 highest impact quick wins:**
1. Fix N+1 in `ml_pipeline.py:92-94` — replace `find_stock()` loop with `find_stocks_batch()` (1-line change)
2. Cache sidebar stats in `app.py` with `@st.cache_data(ttl=60)` (3-line change)
3. Extract duplicated `_inject_api_keys` and `add_derived_ratios` to `src/utils.py`
4. Fix `session.add()` loop in `stock_selection.py:42-56` → `session.add_all()`
5. Add `deque(maxlen=1000)` for log lines in `ml_pipeline.py`
