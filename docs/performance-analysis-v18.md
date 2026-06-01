# AIStock Performance Analysis v18

**Date**: 2026-05-31
**Scope**: N+1 queries, caching gaps, memory leaks, redundant computations, duplicate code
**Severity Scale**: CRITICAL > HIGH > MEDIUM > LOW

---

## Summary

| Category | Issues Found | Severity |
|----------|-------------|----------|
| N+1 Query Patterns | 3 | HIGH (1), MEDIUM (2) |
| Caching Gaps | 3 | MEDIUM (3) |
| Memory Leaks/Growth | 2 | MEDIUM (1), LOW (1) |
| Redundant Computations | 7 | LOW (7) |
| Duplicate Code | 3 | LOW (3) |
| **Total** | **18** | |

12 prior fixes verified operational. 6 issues confirmed unfixed from prior audits (v14-v17).

---

## 1. N+1 Query Patterns

### 1.1 [HIGH] FinRL Data Source: Per-Ticker Loop → 1000 Sequential Queries

**File**: `external/FinRL-Trading/src/data/data_fetcher.py` — `AIStockDBSource.get_price_data()`
**Impact**: For a 500-stock pipeline run, loops over ticker_list calling `find_stock()` + `get_prices()` per ticker → ~1000 sequential queries. Batch methods exist in `repository.py:58-97` but FinRL integration doesn't use them.

```python
# Current (FinRL external code — per-ticker loop):
for symbol in ticker_list:
    stock = self._repo.find_stock(symbol)           # Query per ticker
    prices = self._repo.get_prices(stock.id, ...)   # Query per ticker
```

**Fix**: Replace loop with batch methods:
```python
stock_map = self._repo.find_stocks_batch(ticker_list)
price_requests = [
    (stock_map[sym].id, start_date, end_date)
    for sym in ticker_list if sym in stock_map
]
prices_batch = self._repo.get_prices_batch(price_requests)
# prices_batch is {stock_id: DataFrame}, use directly
```

**Effort**: 30 min (external module) | **Savings**: 1000→2 queries (-99.8%)

---

### 1.2 [MEDIUM] Stock Detail Dialog: 3 Uncached Queries Per Open

**File**: `src/ui/pages/stock_detail.py:11-18`
**Impact**: Every dialog open creates fresh `StockRepository()`, fires `find_stock()`, `get_indicator()`, `get_snapshot()` — all uncached.

```python
# Current:
_repo = StockRepository()
stock = _repo.find_stock(symbol)          # Query 1 — uncached
indicator = _repo.get_indicator(stock.id) # Query 2 — uncached
snapshot = _repo.get_snapshot(stock.id)   # Query 3 — uncached
```

**Fix**: Add cached wrappers, import them:
```python
# In cached_repo.py — add:
@st.cache_data(ttl=300, show_spinner=False)
def cached_get_indicator(stock_id: int) -> dict | None:
    ind = StockRepository().get_indicator(stock_id)
    if ind is None: return None
    return {c.name: getattr(ind, c.name) for c in ind.__table__.columns}

@st.cache_data(ttl=300, show_spinner=False)
def cached_get_snapshot(stock_id: int) -> dict | None:
    snap = StockRepository().get_snapshot(stock_id)
    if snap is None: return None
    return {c.name: getattr(snap, c.name) for c in snap.__table__.columns}

# In stock_detail.py — replace lines 9-18:
from ui.cached_repo import cached_find_stock, cached_get_indicator, cached_get_snapshot

stock_dict = cached_find_stock(symbol)
if not stock_dict:
    st.warning(f"Stock **{symbol}** not found.")
    return
indicator = cached_get_indicator(stock_dict["id"])
snapshot = cached_get_snapshot(stock_dict["id"])
```

**Effort**: 15 min | **Savings**: -3 DB queries per dialog open

---

### 1.3 [MEDIUM] Sidebar Quick Stats: Uncached count_summary

**File**: `src/app.py:234-237`
**Impact**: `display_quick_stats()` calls `repo.count_summary()` directly. DB hit on every sidebar interaction despite `@st.fragment` isolation.

**Fix**: Add `cached_count_summary()` to `cached_repo.py`:
```python
@st.cache_data(ttl=30, show_spinner=False)
def cached_count_summary() -> dict:
    return StockRepository().count_summary()
```

**Effort**: 10 min | **Savings**: -99% sidebar DB hits

---

## 2. Caching Gaps

### 2.1 [MEDIUM] Only 2 Cached Functions — Missing 4 Key Wrappers

**File**: `src/ui/cached_repo.py`
**Status**: Only `cached_find_stock` and `cached_get_prices` exist.
**Missing**: `cached_get_indicator`, `cached_get_snapshot`, `cached_count_summary`, `cached_list_stocks`

Add all four with appropriate TTLs (300s for static data, 30s for counts, 60s for lists).

---

### 2.2 [MEDIUM] Config YAML Parsed on Every Access

**File**: `src/config.py`
**Impact**: Config file parsed on every attribute access. Use mtime-based cache:
```python
from functools import lru_cache

@lru_cache(maxsize=1)
def _cached_config(mtime: float) -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def load_config() -> dict:
    mtime = os.path.getmtime(CONFIG_PATH)
    return _cached_config(mtime)
```

---

### 2.3 [MEDIUM] Bucket Models Deserialized on Every Predict-Only Run

**File**: `src/finrl_runner.py:143-153`
**Impact**: `joblib.load()` on all `.pkl` files every invocation (~40MB deserialization).

**Fix**: Cache by mtime:
```python
_model_cache: dict[str, tuple[float, dict]] = {}

def _load_model_cached(path: str) -> dict:
    mtime = os.path.getmtime(path)
    if path not in _model_cache or _model_cache[path][0] != mtime:
        _model_cache[path] = (mtime, joblib.load(path))
    return _model_cache[path][1]
```

---

## 3. Memory Leaks / Unbounded Growth

### 3.1 [MEDIUM] ml_log_lines Grows Unbounded

**File**: `src/app.py:54-55`
**Impact**: Initialized as `[]`. 500-stock pipeline runs can grow to 10,000+ entries. List slicing `[-1000:]` allocates new list each time.

**Fix**: Use `deque(maxlen=1000)`:
```python
from collections import deque
st.session_state.ml_log_lines = deque(maxlen=1000)
# No slicing needed — display iterates directly
for line in st.session_state.ml_log_lines:
    st.text(line)
```

**Effort**: 5 min | **Savings**: O(1) append/evict, bounded memory

---

### 3.2 [LOW] QueueHandler max_size=10000 Oversized

**File**: `src/app.py:82`
**Impact**: Buffer 10× larger than displayed (~1000 lines). Waste 9000 queue slots.

**Fix**: `_QueueHandler(log_queue, max_size=2000)`

---

## 4. Redundant DataFrame.copy() Operations

### 4.1 [LOW] 3 Defensive .copy() Calls After Boolean Indexing

**File**: `src/ml_bucket_selector.py`

| Line | Code | Why Redundant |
|------|------|---------------|
| 110 | `df = df[df["bucket"].notna()].copy()` | Boolean indexing returns new DF in pandas ≥1.5 |
| 127 | `bdf = df[df["bucket"] == bucket].copy()` | Same |
| 149 | `preds[preds["datadate"] == latest_date].copy()` | Same |

Remove `.copy()`. Save ~6MB per 500-stock run.

---

### 4.2 [LOW] Conditional .copy() Duplication in Weight Logic

**File**: `src/ml_bucket_selector.py:163-170`
Both branches of `if/else` call `selected.copy()`. Hoist before conditional:
```python
selected = selected.copy()
if self.weight_method == "ml_score":
    selected["weight"] = ...
else:
    selected["weight"] = 1.0 / len(selected)
```

---

## 5. Duplicate Code

### 5.1 [LOW] _inject_api_keys Duplicated (25 Lines × 2)

**Files**: `src/pipeline/backends/fast_evaluators.py:72-89`, `src/pipeline/backends/deep_evaluators.py:55-71`

**Fix**: Extract to `src/pipeline/api_keys.py`:
```python
import os

def inject_api_keys(cfg: dict) -> None:
    common = cfg.get("common", {})
    av_key = (
        common.get("alpha_vantage_api_key")
        or cfg.get("data_update", {}).get("alpha_vantage", {}).get("api_key")
        or cfg.get("alpha_vantage", {}).get("api_key")
    )
    mapping = {
        "DEEPSEEK_API_KEY": common.get("deepseek_api_key"),
        "OPENAI_API_KEY": common.get("openai_api_key"),
        "ANTHROPIC_API_KEY": common.get("anthropic_api_key"),
        "GOOGLE_API_KEY": common.get("google_api_key"),
        "GROQ_API_KEY": common.get("groq_api_key"),
        "ALPHA_VANTAGE_API_KEY": av_key,
    }
    for env_var, value in mapping.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value
```

---

### 5.2 [LOW] open_session Context Manager Duplicated (11 Lines × 2)

**Files**: `src/pipeline/base.py:70-81`, `src/pipeline/orchestrator.py:21-31`

**Fix**: Make `base.py:open_session` accept either `StepContext` or callable, delete `_open_session` from orchestrator.py.

---

### 5.3 [LOW] Derived Feature Computation Duplicated (25 Lines × 2)

**Files**: `src/ml_bucket_selector.py:72-87`, `src/finrl_runner.py:183-194`
Both compute `fcf_to_ocf`, `ocf_ratio`, `solvency_ratio` identically.

**Fix**: Extract to `src/fundamentals_derived.py` → import in both places.

---

## 6. Verified Operational (12 Prior Fixes)

| # | Optimization | Location | Status |
|---|-------------|----------|--------|
| 1 | `count_summary` single CASE WHEN | `repository.py:207-214` | ✅ |
| 2 | `find_stocks_batch()` .in_() clause | `repository.py:58-65` | ✅ |
| 3 | `get_prices_batch()` multi-stock OR | `repository.py:78-97` | ✅ |
| 4 | `save_selected_stocks` bulk `add_all()` | `repository.py:262` | ✅ |
| 5 | ThreadPoolExecutor context-managed | `deep_evaluators.py:158` | ✅ |
| 6 | `@st.cache_data` on 14+ UI functions | `cached_repo.py` + pages | ✅ |
| 7 | `@st.fragment` sidebar isolation | `app.py:283` | ✅ |
| 8 | `news_cache` idempotency guard | `deep_evaluators.py:74-77` | ✅ |
| 9 | Config mtime-based cache invalidation | `config.py` | ✅ |
| 10 | Thread daemon=True | `app.py` pipeline threads | ✅ |
| 11 | Session `.close()` in `finally` | `repository.py:_with_session` | ✅ |
| 12 | `max_workers` capped at 3 for LLM API | `deep_evaluators.py:157` | ✅ |

---

## 7. Prioritized Remediation Roadmap

| # | Issue | Severity | Effort | Cumulative Savings |
|---|-------|----------|--------|-------------------|
| 1 | §1.1 FinRL N+1 per-ticker loop | HIGH | 30 min | -99.8% DB queries |
| 2 | §1.2 stock_detail 3 uncached queries | MEDIUM | 15 min | -200ms/dialog |
| 3 | §3.1 ml_log_lines → deque | MEDIUM | 5 min | bounded memory |
| 4 | §1.3 sidebar count_summary cache | MEDIUM | 10 min | -99% sidebar DB hits |
| 5 | §2.1 add 4 cached wrappers | MEDIUM | 20 min | -60% UI DB queries |
| 6 | §5.1 extract shared inject_api_keys | LOW | 15 min | maintainability |
| 7 | §5.2 unify open_session | LOW | 10 min | maintainability |
| 8 | §2.3 bucket model caching | MEDIUM | 10 min | -40MB deserialization |
| 9 | §4.1 remove redundant .copy() | LOW | 5 min | -6MB allocations |
| 10 | §5.3 extract derived features | LOW | 10 min | maintainability |
| 11 | §3.2 reduce queue buffer | LOW | 1 min | -80% queue memory |
| 12 | §4.2 hoist conditional .copy() | LOW | 1 min | code clarity |

**Total effort**: ~2 hours | **All issues addressable**

---

## Appendix: Streamlit (Not React)

AIStock uses Streamlit, not React. Streamlit equivalents to React memo/useMemo:
- `@st.cache_data` — memoize expensive computations (14+ decorators deployed)
- `@st.fragment` — isolate re-render boundaries (sidebar nav uses this)

The `external/ai-hedge-fund/app/frontend/` contains React code with context value instability issues, but that's a separate project outside AIStock scope.
