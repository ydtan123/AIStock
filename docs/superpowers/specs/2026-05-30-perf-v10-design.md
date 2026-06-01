# Performance Optimization v10 — Quick Wins + HIGH

**Date:** 2026-05-30
**Source:** docs/performance-audit-v10.md
**Scope:** 13 fixes — 5 Quick Wins + 8 HIGH items

## Batch 1: Quick Wins

### 1.1 — Batch price fetch (CRITICAL)
- **Files:** `repository.py` (new `get_prices_batch()`), `app.py:183-198`
- Add `get_prices_batch(stocks: list[tuple[int, date, date]]) -> dict[int, pd.DataFrame]` using `or_(*conditions)` for single-query multi-stock fetch
- Update predict-only loop to use batch fetch
- **Impact:** N queries → 1 per predict run

### 3.2 — lru_cache on _last_trading_date
- **File:** `ingestion/pipeline.py`
- `@lru_cache(maxsize=1)` decorator
- **Impact:** ~1500 calendar parses → 1 per pipeline run

### 5.1 — pd.read_sql() in get_prices/get_tech_indicators
- **File:** `repository.py:67-78, 100-106`
- Replace dict-per-row comprehension with `pd.read_sql()`
- **Impact:** 3-5x faster DataFrame construction

### 3.1 — Pass refresh_days to _upsert_fundamentals
- **File:** `ingestion/pipeline.py:194`
- Accept `refresh_days` parameter; caller passes from config
- Remove redundant `load_config()` inside function

### 4.1 — Child logger in thread targets
- **File:** `app.py:81-150`
- Use `pipeline.thread` child logger with `propagate=False` instead of mutating root logger

## Batch 2: HIGH Items

### 1.2 — Single COUNT query
- **File:** `repository.py:191-196`
- Replace 2 queries with single aggregation query

### 1.3 — Combine MIN+MAX daily_prices
- **File:** `ingestion/pipeline.py:85-103`
- Single `SELECT stock_id, MAX(date), MIN(date)` query

### 2.1-2.3 — Streamlit fragments + ctx caching
- **Files:** `app.py`, `ml_pipeline.py`
- `@st.fragment` for sidebar, page content, and log area
- Cache `PageContext` in `session_state`

### 3.3 — Shared cached repo module
- **New file:** `ui/cached_repo.py`
- Extract duplicate `@st.cache_data` wrappers

### 4.2 — Enforce deque maxlen
- **File:** `ml_pipeline.py:365,429`

### 6.2 — Adaptive MAX_WORKERS
- **File:** `ingestion/pipeline.py:25`
- `max(2, min(8, (os.cpu_count() or 4) + 2))`

## Deferred
- #5.2-5.4: Low-impact cleanup
- #6.1: Security — separate audit
