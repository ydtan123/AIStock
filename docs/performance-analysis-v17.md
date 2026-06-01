# AIStock Performance Analysis v17

**Date:** 2026-05-31
**Scope:** Full codebase scan — N+1 queries, caching gaps, memory leaks, redundant computations
**Framework:** Streamlit (not React — "unnecessary re-renders" adapted to Streamlit equivalents)

---

## Executive Summary

**12 prior fixes confirmed operational.** 6 remaining issues (4 MEDIUM, 2 LOW). 1 prior issue (`count_summary`) now resolved.

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | `stock_detail.py` — 3 uncached DB queries per dialog | MEDIUM | Unfixed |
| 2 | `display_quick_stats()` — uncached sidebar query | MEDIUM | Unfixed |
| 3 | `cached_repo.py` — missing `cached_get_indicator`/`cached_get_snapshot` | MEDIUM | Unfixed |
| 4 | `ml_log_lines` — plain list instead of bounded deque | MEDIUM | Unfixed |
| 5 | `_inject_api_keys` — near-duplicate across 2 backends | LOW | Unfixed |
| 6 | `_open_session` — duplicate logic in `base.py` + `orchestrator.py` | LOW | Unfixed |

**Resolved since v16:** `count_summary` now uses single `SELECT COUNT(*), COALESCE(SUM(CASE WHEN is_active...))` — was 3 separate COUNT queries.

---

## 1. N+1 Query Patterns

### 1.1 `stock_detail.py` — 3 Uncached DB Queries Per Dialog (MEDIUM)

**File:** `src/ui/pages/stock_detail.py:9-18`

Every dialog open creates a fresh `StockRepository()` and fires 3 queries:

```python
_repo = StockRepository()
stock = _repo.find_stock(symbol)           # Query 1 — uncached
indicator = _repo.get_indicator(stock.id)  # Query 2 — uncached
snapshot = _repo.get_snapshot(stock.id)    # Query 3 — uncached
```

`cached_find_stock()` exists in `src/ui/cached_repo.py` but not imported here. No `cached_get_indicator` or `cached_get_snapshot` wrappers exist.

**Fix — Add to `src/ui/cached_repo.py`:**

```python
@st.cache_data(ttl=300, show_spinner=False)
def cached_get_indicator(stock_id: int) -> dict | None:
    ind = StockRepository().get_indicator(stock_id)
    if ind is None:
        return None
    return {
        "market_cap": ind.market_cap, "pe_ratio": ind.pe_ratio,
        "forward_pe": ind.forward_pe, "peg_ratio": ind.peg_ratio,
        "price_to_book": ind.price_to_book,
        "price_to_sales_ttm": ind.price_to_sales_ttm,
        "ev_to_ebitda": ind.ev_to_ebitda, "eps": ind.eps,
        "roe_ttm": ind.roe_ttm, "roa_ttm": ind.roa_ttm,
        "profit_margin": ind.profit_margin,
        "operating_margin_ttm": ind.operating_margin_ttm,
        "revenue_ttm": ind.revenue_ttm,
        "gross_profit_ttm": ind.gross_profit_ttm,
        "ebitda": ind.ebitda, "book_value": ind.book_value,
        "revenue_per_share_ttm": ind.revenue_per_share_ttm,
        "dividend_per_share": ind.dividend_per_share,
        "dividend_yield": ind.dividend_yield,
        "qtr_earnings_growth_yoy": ind.qtr_earnings_growth_yoy,
        "qtr_revenue_growth_yoy": ind.qtr_revenue_growth_yoy,
        "beta": ind.beta, "pct_insiders": ind.pct_insiders,
        "pct_institutions": ind.pct_institutions,
        "analyst_target_price": ind.analyst_target_price,
        "analyst_strong_buy": ind.analyst_strong_buy,
        "analyst_buy": ind.analyst_buy, "analyst_hold": ind.analyst_hold,
        "analyst_sell": ind.analyst_sell, "analyst_strong_sell": ind.analyst_strong_sell,
        "week_52_high": ind.week_52_high, "week_52_low": ind.week_52_low,
        "ma_50_day": ind.ma_50_day, "ma_200_day": ind.ma_200_day,
        "last_updated": str(ind.last_updated) if ind.last_updated else None,
    }

@st.cache_data(ttl=300, show_spinner=False)
def cached_get_snapshot(stock_id: int) -> dict | None:
    snap = StockRepository().get_snapshot(stock_id)
    if snap is None:
        return None
    return {
        "market_cap": snap.market_cap, "pe_ratio": snap.pe_ratio,
        "roe_ttm": snap.roe_ttm, "rsi_14": snap.rsi_14,
        "beta": snap.beta, "dividend_yield": snap.dividend_yield,
        "sector": snap.sector, "exchange": snap.exchange,
        "last_updated": str(snap.last_updated) if snap.last_updated else None,
    }
```

**Fix — Rewrite `stock_detail.py`:**

```python
from ui.cached_repo import cached_find_stock, cached_get_indicator, cached_get_snapshot

@st.dialog("Stock Details", width="large")
def render(ctx, symbol: str):
    stock = cached_find_stock(symbol)
    if not stock:
        st.warning(f"Stock **{symbol}** not found in database.")
        return

    indicator = cached_get_indicator(stock["id"])
    snapshot = cached_get_snapshot(stock["id"])
    # ... rest uses stock dict instead of ORM object attributes
```

**Impact:** 3 DB queries → 0 (after first cache warm). TTL=300 caches each stock for 5 minutes.

---

### 1.2 `display_quick_stats()` — Uncached Sidebar Query on Every Nav (MEDIUM)

**File:** `src/app.py` (sidebar helpers section)

```python
def display_quick_stats(repo: StockRepository) -> None:
    st.subheader("Quick Stats")
    try:
        summary = repo.count_summary()  # <-- DB query every sidebar render
        c1, c2 = st.columns(2)
        c1.metric("Total", summary.get("total", "—"))
        c2.metric("Active", summary.get("active", "—"))
```

Called from `sidebar_nav()` (`@st.fragment`) — reruns on every page switch. `stock_manager.py` already has `_cached_count_summary()` with `@st.cache_data(ttl=60)` but `app.py` doesn't use it.

**Fix:**

```python
@st.cache_data(ttl=120, show_spinner=False)
def _cached_quick_stats() -> dict:
    from repository import StockRepository
    return StockRepository().count_summary()

def display_quick_stats(repo: StockRepository) -> None:
    st.subheader("Quick Stats")
    try:
        summary = _cached_quick_stats()
        c1, c2 = st.columns(2)
        c1.metric("Total", summary.get("total", "—"))
        c2.metric("Active", summary.get("active", "—"))
```

**Impact:** Sidebar query drops from every navigation to once per 120s. 8 tab clicks = 8→1 query.

---

## 2. Unnecessary Re-renders (Streamlit, not React)

> AIStock is a Streamlit app. No React/JSX/Virtual DOM. Streamlit's full-page rerun model requires `@st.cache_data` and `@st.fragment` for isolation — both already deployed except gaps below.

### 2.1 Sidebar Fragment Reruns on Every Navigation

`sidebar_nav()` uses `@st.fragment` correctly, but `display_quick_stats()` inside it hits the DB each time. Fix: §1.2.

### 2.2 Dialog Creates Fresh `StockRepository` Instance

`stock_detail.py` instantiates `StockRepository()` on every open. Fix: §1.1 (switch to cached wrappers).

---

## 3. Caching Opportunities

### 3.1 `cached_repo.py` Gaps (MEDIUM)

Current state — only 2 functions:

```python
@st.cache_data(ttl=300) def cached_find_stock(...)
@st.cache_data(ttl=60)  def cached_get_prices(...)
```

Missing: `cached_get_indicator`, `cached_get_snapshot`. Full fix in §1.1.

### 3.2 TTL Inconsistency

| Function | TTL | Recommendation |
|----------|-----|----------------|
| `cached_find_stock` | 300s | ✅ Correct — metadata rarely changes |
| `cached_get_prices` | 60s | ✅ Correct — price data updates frequently |
| `_cached_get_indicator` (stock_lookup) | 60s | Change to 300s — fundamentals don't change intraday |
| `_cached_count_summary` (stock_manager) | 60s | Change to 300s — stock count changes rarely |

---

## 4. Memory Leaks / Unbounded Growth

### 4.1 `ml_log_lines` — Plain List Without Bounds (MEDIUM)

**File:** `src/app.py:54-55`

```python
if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = []
```

Grows without bound during ML pipeline runs. 500-stock run = thousands of entries persisting for entire browser session.

**Fix:**

```python
from collections import deque

if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = deque(maxlen=1000)
```

**Impact:** Memory capped at 1,000 entries. `deque.append()` same API as `list.append()` — no downstream changes needed.

### 4.2 `_QueueHandler` max_size 10× Display Buffer (LOW)

**File:** `src/app.py` (`_QueueHandler.__init__`)

```python
class _QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue, max_size: int = 10000) -> None:
```

Queue buffers 10,000 entries; display shows ~1,000. Extra 9,000 slots waste memory.

**Fix:**

```python
def __init__(self, log_queue: queue.Queue, max_size: int = 2000) -> None:
```

**Impact:** 5× memory reduction. 2,000 is 2× display buffer — enough burst headroom.

---

## 5. Redundant Computations

### 5.1 `DataFrame.copy()` — 7 Calls, 3 Redundant (LOW)

**File:** `src/ml_bucket_selector.py`

```python
66:  df = fund_df.copy()                                          # KEEP — downstream mutation
110: df = df[df["bucket"].notna()].copy()                        # REMOVE — filter returns new df, no mutation
127: bdf = df[df["bucket"] == bucket].copy()                     # KEEP — bdf gets fillna/clip
149: preds = preds[preds["datadate"] == latest_date].copy()      # KEEP — downstream mutation
166: selected = selected.copy()                                   # REMOVE — overwritten by line 169
169: selected = selected.copy()                                   # KEEP
180: selected_records = selected[["tic",...]].copy()             # REMOVE — filter+select = new df, no mutation
```

Line 166 is wasted — immediately overwritten by 169. Lines 110/180: boolean indexing + column selection already return new DataFrames in modern pandas.

**Impact:** 3 fewer allocations per `fit_predict` call. For 500-stock DataFrames, meaningful memory savings.

---

### 5.2 `_inject_api_keys` Near-Duplicate (LOW)

**Files:** `src/pipeline/backends/fast_evaluators.py:72`, `deep_evaluators.py:55`

Identical logic except `fast_evaluators.py` adds `GROQ_API_KEY`. 25 duplicated lines.

**Fix — extract to `src/pipeline/backends/_shared.py`:**

```python
"""Shared utilities for pipeline evaluator backends."""
import os

def inject_api_keys(ctx_cfg: dict, extra_keys: dict[str, str] | None = None) -> None:
    common = ctx_cfg.get("common", {})
    av_key = (
        common.get("alpha_vantage_api_key")
        or ctx_cfg.get("data_update", {}).get("alpha_vantage", {}).get("api_key")
        or ctx_cfg.get("alpha_vantage", {}).get("api_key")
    )
    mapping = {
        "DEEPSEEK_API_KEY": common.get("deepseek_api_key"),
        "OPENAI_API_KEY": common.get("openai_api_key"),
        "ANTHROPIC_API_KEY": common.get("anthropic_api_key"),
        "GOOGLE_API_KEY": common.get("google_api_key"),
        "ALPHA_VANTAGE_API_KEY": av_key,
    }
    if extra_keys:
        mapping.update(extra_keys)
    for env_var, value in mapping.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value
```

Usage in `fast_evaluators.py`:
```python
from pipeline.backends._shared import inject_api_keys
inject_api_keys(ctx.cfg, extra_keys={"GROQ_API_KEY": ctx.cfg.get("common", {}).get("groq_api_key")})
```

Usage in `deep_evaluators.py`:
```python
from pipeline.backends._shared import inject_api_keys
inject_api_keys(ctx.cfg)
```

**Impact:** Single source of truth. 25 duplicated lines eliminated.

---

### 5.3 `_open_session` / `open_session` — Duplicate Logic (LOW)

**Files:** `src/pipeline/base.py:71`, `src/pipeline/orchestrator.py:22`

Both implement identical context manager. Only difference: `open_session` takes `StepContext`, `_open_session` takes factory directly.

**Fix — unify in `pipeline/base.py`:**

```python
from contextlib import contextmanager
from typing import Callable, Any

@contextmanager
def open_session(source: StepContext | Callable[[], Any]):
    """Wrap a session factory or StepContext's session_factory."""
    factory = source.session_factory if isinstance(source, StepContext) else source
    s = factory()
    if hasattr(s, "__enter__"):
        with s as session:
            yield session
    else:
        try:
            yield s
        finally:
            s.close()
```

Then in `orchestrator.py`: replace `_open_session(factory)` with `open_session(factory)`.

**Impact:** Single implementation, consistent error handling.

---

## 6. Verified Optimizations (Already Operational)

| Optimization | File | Status |
|-------------|------|--------|
| `count_summary` single query with CASE WHEN | `repository.py:207` | ✅ Fixed since v16 |
| `find_stocks_batch` bulk lookup | `repository.py` | ✅ Operational |
| `get_prices_batch` bulk price fetch | `repository.py` | ✅ Operational |
| `@st.cache_data` on screener/manager | `stock_screener.py`, `stock_manager.py` | ✅ Operational |
| `@st.fragment` sidebar isolation | `app.py` | ✅ Operational |
| `news_cache.install()` idempotency guard | `news_cache.py` | ✅ Operational |
| `ThreadPoolExecutor` with adaptive `MAX_WORKERS` | `ingestion/pipeline.py` | ✅ Operational |
| Bulk insert with deadlock retry | `ingestion/pipeline.py` | ✅ Operational |
| `@lru_cache` on `_last_trading_date` | `ingestion/pipeline.py` | ✅ Operational |
| `_prefetch_stock_dates` batch prefetch | `finrl_runner.py` | ✅ Operational |
| `open_session` defined in `pipeline/base.py` | `pipeline/base.py` | ✅ Centralized |
| Config file mtime-based cache invalidation | `config.py` | ✅ Operational |

---

## 7. Priority Order

| Rank | Issue | Effort | Impact |
|------|-------|--------|--------|
| 1 | Add `cached_get_indicator`/`cached_get_snapshot` to `cached_repo.py` | 15 min | -2 DB queries per dialog |
| 2 | Rewire `stock_detail.py` to use cached wrappers | 10 min | -3 DB queries per dialog |
| 3 | Add `_cached_quick_stats` to `app.py` sidebar | 5 min | -1 DB query per nav |
| 4 | Replace `ml_log_lines` list → `deque(maxlen=1000)` | 2 min | Caps memory growth |
| 5 | Reduce `_QueueHandler max_size` 10000 → 2000 | 1 min | 5× memory reduction |
| 6 | Extract `_inject_api_keys` to `_shared.py` | 20 min | -25 duplicated lines |
| 7 | Unify `_open_session`/`open_session` | 15 min | Single implementation |
| 8 | Remove redundant `.copy()` in `ml_bucket_selector` | 10 min | -3 allocations |

---

## 8. Not Applicable

- **React re-renders:** AIStock is a Streamlit app — no React, JSX, or Virtual DOM. Streamlit uses full-page reruns; `@st.fragment` and `@st.cache_data` are the correct tools and are deployed where needed except gaps above.
- **SQL injection:** Not a performance concern; covered in prior security audit.
- **DB connection pooling:** SQLAlchemy defaults appropriate for single-user Streamlit app.
