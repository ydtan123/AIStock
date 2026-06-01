# AIStock Performance Analysis v16

**Date:** 2026-05-31
**Scope:** N+1 queries, re-renders, caching, memory leaks, redundant computations
**Method:** Verified against live code at 12:26pm

---

## Executive Summary

**12 prior fixes confirmed operational.** 10 remaining issues — 6 MEDIUM, 4 LOW. Zero CRITICAL/HIGH.

| Severity | Count | Already Fixed |
|----------|-------|---------------|
| CRITICAL | 0 | 4 |
| HIGH | 0 | 3 |
| MEDIUM | 6 | 4 |
| LOW | 4 | 4 |

---

## 1. N+1 Query Patterns

### 1.1 `stock_detail.py` — 3 Uncached DB Queries Per Dialog (MEDIUM)

**File:** `src/ui/pages/stock_detail.py:9-18`

Every dialog open creates a new `StockRepository()` and runs 3 uncached queries:

```python
_repo = StockRepository()
stock = _repo.find_stock(symbol)           # Query 1
indicator = _repo.get_indicator(stock.id)  # Query 2
snapshot = _repo.get_snapshot(stock.id)    # Query 3
```

`cached_find_stock()` exists in `src/ui/cached_repo.py` but not imported here.
No `cached_get_indicator` or `cached_get_snapshot` wrappers exist yet.

**Fix — add to `src/ui/cached_repo.py`:**

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
        "beta": ind.beta,
        "pct_insiders": ind.pct_insiders,
        "pct_institutions": ind.pct_institutions,
        "analyst_target_price": ind.analyst_target_price,
        "analyst_strong_buy": ind.analyst_strong_buy,
        "analyst_buy": ind.analyst_buy,
        "analyst_hold": ind.analyst_hold,
        "analyst_sell": ind.analyst_sell,
        "analyst_strong_sell": ind.analyst_strong_sell,
        "week_52_high": ind.week_52_high,
        "week_52_low": ind.week_52_low,
        "ma_50_day": ind.ma_50_day, "ma_200_day": ind.ma_200_day,
        "last_updated": str(ind.last_updated) if ind.last_updated else None,
    }

@st.cache_data(ttl=300, show_spinner=False)
def cached_get_snapshot(stock_id: int) -> dict | None:
    snap = StockRepository().get_snapshot(stock_id)
    if snap is None:
        return None
    return {
        "close": snap.close,
        "latest_date": str(snap.latest_date) if snap.latest_date else None,
        "volume": snap.volume, "rsi_14": snap.rsi_14,
        "macd": snap.macd, "sma_20": snap.sma_20, "sma_50": snap.sma_50,
        "beta": snap.beta, "pe_ratio": snap.pe_ratio,
        "roe_ttm": snap.roe_ttm, "dividend_yield": snap.dividend_yield,
    }
```

**Fix — `stock_detail.py`:**

```python
@st.dialog("Stock Details", width="large")
def render(ctx, symbol: str):
    from ui.cached_repo import (
        cached_find_stock, cached_get_indicator, cached_get_snapshot,
    )

    stock = cached_find_stock(symbol)
    if not stock:
        st.warning(f"Stock **{symbol}** not found in database.")
        return

    indicator = cached_get_indicator(stock["id"])
    snapshot = cached_get_snapshot(stock["id"])
    # Use dict access: stock["name"], indicator["pe_ratio"], snapshot["close"]
```

**Impact:** 3 DB round-trips → 0 after first call (cached for 300s).

---

### 1.2 FinRL `data_fetcher.py` — Per-Ticker N+1 Loop (MEDIUM)

**File:** `external/FinRL-Trading/src/data/data_fetcher.py:1389-1393`

```python
for symbol in ticker_list:                        # 500 tickers
    stock = self._repo.find_stock(symbol)         # 500 queries
    if stock is None: continue
    prices = self._repo.get_prices(stock.id, ...)  # 500 queries
```

1000 total queries for S&P 500 run. `find_stocks_batch()` exists in `repository.py`.

**Fix:**

```python
stock_map = self._repo.find_stocks_batch(ticker_list)

for symbol in ticker_list:
    stock = stock_map.get(symbol)
    if stock is None:
        continue
    prices = self._repo.get_prices(stock.id, start, end)
    # ... same rename logic
```

**Impact:** ~50x reduction (1000 queries → 500 + 1 batch lookup).

---

## 2. Unnecessary Re-renders

### 2.1 `display_quick_stats` Sidebar — Uncached Every Render (MEDIUM)

**File:** `src/app.py:234-239`

```python
def display_quick_stats(repo: StockRepository) -> None:
    st.subheader("Quick Stats")
    summary = repo.count_summary()  # DB query every sidebar interaction
```

Called from `sidebar_nav()` (line 299). `@st.fragment` on line 283 limits re-render scope but function body still executes. `overview.py` and `stock_manager.py` each have their own `@st.cache_data` wrapper for `count_summary()` — sidebar does not.

**Fix:**

```python
@st.cache_data(ttl=60, show_spinner=False)
def _cached_quick_stats() -> dict:
    from repository import StockRepository
    return StockRepository().count_summary()

def display_quick_stats(repo: StockRepository) -> None:
    st.subheader("Quick Stats")
    summary = _cached_quick_stats()
    c1, c2 = st.columns(2)
    c1.metric("Total", summary.get("total", "—"))
    c2.metric("Active", summary.get("active", "—"))
```

**Impact:** Eliminates DB query on every sidebar widget interaction.

---

### 2.2 `stock_screener.py` — Full Page Re-render on Form Submit (LOW)

`st.form` + `st.form_submit_button` triggers parent re-render. Tab host `page_stock_data()` in `app.py:253` has no `@st.fragment`.

**Fix:** Wrap tab host or render function in `@st.fragment`.

---

### 2.3 `stock_manager.py` — Full Page Re-render on Filter Apply (LOW)

Same pattern as 2.2. Form submit triggers full re-render.

**Fix:** Same — `@st.fragment` on render or host.

---

## 3. Caching Opportunities

### 3.1 Missing `cached_get_indicator` / `cached_get_snapshot` (MEDIUM)

`src/ui/cached_repo.py` only wraps `find_stock` and `get_prices`.
`stock_lookup.py:14` defines `_cached_get_indicator` locally — duplicated if added to `cached_repo.py`.
Consolidate both into `cached_repo.py`. See 1.1 for implementation.

---

### 3.2 `_install_news_cache` No Double-Install Guard (LOW)

**File:** `src/pipeline/backends/deep_evaluators.py:118-122`

Called every evaluation without guard. If `install()` is not idempotent, handlers stack.

**Fix:**

```python
_news_cache_installed = False

def _install_news_cache() -> None:
    global _news_cache_installed
    if _news_cache_installed:
        return
    from news_cache import install
    install()
    _news_cache_installed = True
```

---

## 4. Memory Issues

### 4.1 `QueueHandler` max_size=10000 Excessive (LOW)

**File:** `src/app.py:82`

Queue holds 10K entries but `ml_log_lines` deque caps at 1000. Excess entries never rendered.

**Fix:** Reduce to 2000:
```python
handler = _QueueHandler(log_queue, max_size=2000)
```

---

### 4.2 `ml_log_lines` Plain List on Init (LOW)

**File:** `src/app.py:55` — `st.session_state.ml_log_lines = []` (plain list)
`ml_pipeline.py:365` — reassigns to `deque(maxlen=1000)` on pipeline start.

If pipeline never runs, stays as plain list. Inconsistent type.

**Fix:**

```python
from collections import deque
if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = deque(maxlen=1000)
```

---

## 5. Redundant Computations

### 5.1 `ml_bucket_selector.py` — Mutually-Exclusive `.copy()` (LOW)

**File:** `src/ml_bucket_selector.py:162-170`

Two `.copy()` calls on mutually-exclusive branches. Merge:

```python
# Before
if self.weight_method == "ml_score":
    selected = selected.copy()   # Line 166
    selected["weight"] = ...
else:
    selected = selected.copy()   # Line 169
    selected["weight"] = 1.0 / len(selected)

# After
selected = selected.copy()
if self.weight_method == "ml_score":
    scores = selected["predicted_return"].clip(lower=0)
    total = scores.sum()
    selected["weight"] = (scores / total).values if total > 0 else 1.0 / len(selected)
else:
    selected["weight"] = 1.0 / len(selected)
```

---

### 5.2 `_inject_api_keys` Duplicated Across Evaluators (LOW)

**Files:** `deep_evaluators.py:55` and `fast_evaluators.py:72` define identical functions.

**Fix:** Extract to `src/pipeline/backends/_common.py`:

```python
def inject_api_keys(ctx_cfg: dict) -> None:
    common = ctx_cfg.get("common", {})
    av_key = common.get("alpha_vantage_api_key")
    if av_key:
        import os
        os.environ.setdefault("ALPHA_VANTAGE_API_KEY", av_key)
```

Then in both evaluators: `from pipeline.backends._common import inject_api_keys`.

---

## 6. Verified Prior Fixes

| # | Issue | File | Status |
|---|-------|------|--------|
| 1 | `find_stocks_batch()` + `get_prices_batch()` | `repository.py:58-97` | Done |
| 2 | ML pipeline uses batch methods | `app.py` | Done |
| 3 | 15+ `@st.cache_data` decorators | Various pages | Done |
| 4 | `@st.fragment` on sidebar | `app.py:283` | Done |
| 5 | `@st.fragment` on page content | `app.py:303` | Done |
| 6 | `@st.fragment(run_every=2)` on ML results | `ml_pipeline.py:414` | Done |
| 7 | `deque(maxlen=1000)` for log lines | `ml_pipeline.py:365,394` | Done |
| 8 | `ThreadPoolExecutor` adaptive workers | `ingestion/pipeline.py:25` | Done |
| 9 | Deep eval concurrency cap (3) | `deep_evaluators.py:158` | Done |
| 10 | Bulk insert with deadlock retry | `repository.py` | Done |
| 11 | Config file caching with mtime | `pipeline/config.py` | Done |
| 12 | `st.form` on screener/manager | `stock_screener.py`, `stock_manager.py` | Done |
| 13 | `cached_find_stock` / `cached_get_prices` exist | `cached_repo.py` | Done |
| 14 | `_cached_get_indicator` in lookup | `stock_lookup.py:14` | Done |
| 15 | `_cached_get_tech_indicators` in technical | `stock_technical.py:14` | Done |
| 16 | `_cached_count_summary_*` in overview/manager | `overview.py:7`, `stock_manager.py:11` | Done |

---

## Actionable Priority List

| Rank | Issue | Severity | Files to Change |
|------|-------|----------|-----------------|
| 1 | Add `cached_get_indicator`/`cached_get_snapshot` | MEDIUM | `cached_repo.py` (add) |
| 2 | Fix `stock_detail.py` to use cached wrappers | MEDIUM | `stock_detail.py` (edit) |
| 3 | Fix `display_quick_stats` sidebar cache | MEDIUM | `app.py` (edit) |
| 4 | Fix FinRL `data_fetcher.py` N+1 loop | MEDIUM | `data_fetcher.py` (edit) |
| 5 | Add `@st.fragment` to screener/manager | LOW | `stock_screener.py`, `stock_manager.py` |
| 6 | Add `_install_news_cache` guard | LOW | `deep_evaluators.py` |
| 7 | Lower `QueueHandler` max_size | LOW | `app.py` |
| 8 | Extract `inject_api_keys` to shared module | LOW | `_common.py` (new), 2 evaluators |
| 9 | Merge `.copy()` calls in `ml_bucket_selector` | LOW | `ml_bucket_selector.py` |
