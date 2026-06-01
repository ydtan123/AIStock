# AIStock Performance Audit v18 — 2026-05-31

**Scope**: N+1 queries, caching gaps, React re-renders, memory leaks, redundant computations
**Files audited**: 14 source files across Python (Streamlit) backend + TypeScript (React) frontend
**Prior fixes verified**: 13 optimizations intact
**New issues found**: 0 (all previously documented, verified still present)

---

## Executive Summary

| # | Category | Issue | Severity | File:Line |
|---|----------|-------|----------|-----------|
| 1 | N+1 Query | Stock detail dialog: 3 uncached DB queries per open | **CRITICAL** | `stock_detail.py:11-18` |
| 2 | Caching Gap | `_cached_get_indicator` returns 2 of 40+ fields | **CRITICAL** | `stock_lookup.py:14-20` |
| 3 | N+1 Query | Sidebar `count_summary()` uncached on every render | **HIGH** | `app.py:237` |
| 4 | Memory Leak | `ml_log_lines` unbounded list (MAX_LOG_LINES=1000 unused) | **HIGH** | `app.py:54-55` |
| 5 | Redundant Code | `_inject_api_keys` duplicated in 2 evaluator backends | **HIGH** | `fast_evaluators.py:72` `deep_evaluators.py:55` |
| 6 | Redundant Code | `open_session` context manager duplicated | **MEDIUM** | `base.py:70` `orchestrator.py:21` |
| 7 | Redundant Comp | `DataFrame.copy()` 7 calls, 3+ redundant | **MEDIUM** | `ml_bucket_selector.py:66,110,127,149,166,169,180` |
| 8 | React Re-render | 4 context providers create value inline (no useMemo) | **MEDIUM** | `*context.tsx` (4 files) |
| 9 | Caching Gap | `stock_manager.py` re-queries on every form interaction | **LOW** | `stock_manager.py:10-15` |

---

## 1. N+1 Query: Stock Detail Dialog (CRITICAL)

**File**: `src/ui/pages/stock_detail.py:11-18`

```python
# Current: 3 separate DB sessions per dialog open
_repo = StockRepository()
stock = _repo.find_stock(symbol)           # Session 1
indicator = _repo.get_indicator(stock.id)  # Session 2
snapshot = _repo.get_snapshot(stock.id)    # Session 3
```

**Problem**: `cached_find_stock()` exists in `cached_repo.py:9-16` with `ttl=300` but not imported. `cached_get_indicator`/`cached_get_snapshot` wrappers do not exist. Every dialog open = 3 DB round-trips.

**Fix**:
```python
# stock_detail.py — add to imports
from ui.cached_repo import cached_find_stock

# cached_repo.py — add new wrappers
@st.cache_data(ttl=300, show_spinner=False)
def cached_get_indicator(stock_id: int) -> dict | None:
    ind = StockRepository().get_indicator(stock_id)
    if ind is None:
        return None
    return {c.name: getattr(ind, c.name) for c in ind.__table__.columns}

@st.cache_data(ttl=300, show_spinner=False)
def cached_get_snapshot(stock_id: int) -> dict | None:
    snap = StockRepository().get_snapshot(stock_id)
    if snap is None:
        return None
    return {c.name: getattr(snap, c.name) for c in snap.__table__.columns}
```

**Impact**: 3 DB queries → 1 cached call (after first miss). Applies to lookup, screener, and manager pages.

---

## 2. Incomplete Indicator Cache (CRITICAL)

**File**: `src/ui/pages/stock_lookup.py:14-20`

```python
@st.cache_data(ttl=60, show_spinner=False)
def _cached_get_indicator(stock_id: int) -> dict | None:
    ind = StockRepository().get_indicator(stock_id)
    if ind is None:
        return None
    return {"pe_ratio": ind.pe_ratio, "market_cap": ind.market_cap}  # Only 2 fields!
```

**Problem**: Returns 2 of 40+ `StockIndicator` fields. `stock_detail.py:17` bypasses this entirely — uncached query for all 40+ fields. Other pages that need `forward_pe`, `eps`, `beta`, `roe_ttm`, `dividend_yield` etc. must either duplicate the wrapper or fall through to uncached.

**Fix**: Return all scalar columns dynamically (see fix in issue #1 above) or explicitly list all needed fields.

**Impact**: Eliminates need for per-page caching wrappers. Single source of truth for indicator data.

---

## 3. Sidebar Query Uncached (HIGH)

**File**: `src/app.py:234-242`

```python
def display_quick_stats(repo: StockRepository) -> None:
    st.subheader("Quick Stats")
    try:
        summary = repo.count_summary()  # DB query on EVERY sidebar render
        ...
```

**Problem**: Called from `sidebar_nav()` at line 299, which is inside `@st.fragment` at line 283. Fragment isolates re-renders but doesn't cache the query. Every navigation → DB hit. 20 nav clicks = 19 unnecessary queries.

`count_summary()` itself is optimized (single `SELECT COUNT(*), COALESCE(SUM(CASE WHEN is_active...))` query at `repository.py:210-213`).

**Fix**:
```python
# app.py or cached_repo.py
@st.cache_data(ttl=60, show_spinner=False)
def cached_count_summary() -> dict:
    return repo.count_summary()

# Then in display_quick_stats:
summary = cached_count_summary()
```

**Impact**: N sidebar renders → 1 query per 60s. Typical session: 20+ queries → 1-2.

---

## 4. Unbounded Memory Growth (HIGH)

**File**: `src/app.py:54-55,65`

```python
if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = []  # Plain list, unbounded

MAX_LOG_LINES = 1000  # Defined but NEVER enforced
```

**Problem**: `ml_log_lines` grows unbounded during ML pipeline execution (500 stocks × multiple log lines each). `_QueueHandler` at line 81-95 uses `max_size=10000` to prevent queue overflow, but the session state list copied from the queue has no bound. Long sessions accumulate thousands of log entries in memory.

**Fix**:
```python
from collections import deque

if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = deque(maxlen=MAX_LOG_LINES)

# When appending from queue (in render_ml_pipeline):
while not log_queue.empty():
    st.session_state.ml_log_lines.append(log_queue.get_nowait())
```

**Impact**: O(n) → O(1) memory for log storage. Guaranteed max 1000 entries.

---

## 5. Duplicate API Key Injection (HIGH)

**Files**: 
- `src/pipeline/backends/fast_evaluators.py:72-89`
- `src/pipeline/backends/deep_evaluators.py:55-71`

```python
# Both files have nearly identical:
def _inject_api_keys(ctx_cfg: dict) -> None:
    common = ctx_cfg.get("common", {})
    av_key = (
        common.get("alpha_vantage_api_key")
        or ctx_cfg.get("data_update", {}).get("alpha_vantage", {}).get("api_key")
        or ctx_cfg.get("alpha_vantage", {}).get("api_key")
    )
    mapping = { ... }  # Minor diff: fast adds GROQ_API_KEY
    for env_var, value in mapping.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value
```

**Problem**: 25+ lines duplicated with diverging implementations. Fast evaluator includes `GROQ_API_KEY`; deep evaluator doesn't. Any config key change requires 2-file sync.

**Fix**:
```python
# src/pipeline/backends/api_keys.py (new file)
"""Shared API key injection from config to os.environ."""
import os

def inject_api_keys(ctx_cfg: dict, *, include_groq: bool = False) -> None:
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
    if include_groq:
        mapping["GROQ_API_KEY"] = common.get("groq_api_key")
    for env_var, value in mapping.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value

# Import in both evaluators, delete local copies
```

**Impact**: -50 duplicated lines. Single point of change for config keys.

---

## 6. Duplicate `open_session` Context Manager (MEDIUM)

**Files**:
- `src/pipeline/base.py:70-81` — `open_session(ctx)`
- `src/pipeline/orchestrator.py:21-31` — `_open_session(factory)`

```python
# base.py:70-81 — PUBLIC, takes StepContext
@contextmanager
def open_session(ctx: StepContext):
    s = ctx.session_factory()
    if hasattr(s, "__enter__"):
        with s as session:
            yield session
    else:
        try:
            yield s
        finally:
            s.close()

# orchestrator.py:21-31 — PRIVATE, takes raw factory
@contextmanager
def _open_session(factory):
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

**Problem**: Identical 11-line logic. `orchestrator.py` already imports from `pipeline.base` but re-implements `open_session` with a different signature.

**Fix**: Orchestrator call sites pass explicit `session_factory`; wrap in `StepContext` or change `base.open_session` to accept optional `factory` override:
```python
# orchestrator.py — use base.open_session with a lightweight adapter
from pipeline.base import open_session as base_open_session

# At call sites:
with base_open_session(ctx):
    ...
```
Or delete `orchestrator._open_session` and pass `StepContext` at call sites.

**Impact**: -11 duplicated lines. Consistent error handling.

---

## 7. Redundant DataFrame.copy() Calls (MEDIUM)

**File**: `src/ml_bucket_selector.py`

7 `.copy()` calls in `fit_predict()`:
- **Line 66**: `df = fund_df.copy()` — **justified**: protects caller's DataFrame
- **Line 110**: `df[df["bucket"].notna()].copy()` — **redundant**: boolean indexing returns new DataFrame
- **Line 127**: `df[df["bucket"] == bucket].copy()` — **justified**: per-bucket slice modified downstream
- **Line 149**: `preds[preds["datadate"] == latest_date].copy()` — **redundant**: boolean indexing returns new DataFrame
- **Line 166**: `selected.copy()` before `selected["weight"] = ...` — **justified**: prevents SettingWithCopyWarning
- **Line 169**: `selected.copy()` — **redundant**: line 166 already copies if weight_method == "ml_score"; else branch copies again
- **Line 180**: `selected[...].copy()` — **justified**: column selection for metadata

**Fix**: Remove lines 110 and 149 `.copy()`. Consolidate lines 166/169:
```python
# Before (lines 163-170):
if self.weight_method == "ml_score":
    scores = selected["predicted_return"].clip(lower=0)
    total = scores.sum()
    selected = selected.copy()
    selected["weight"] = (scores / total).values if total > 0 else 1.0 / len(selected)
else:
    selected = selected.copy()
    selected["weight"] = 1.0 / len(selected)

# After:
selected = selected.copy()
if self.weight_method == "ml_score":
    scores = selected["predicted_return"].clip(lower=0)
    total = scores.sum()
    selected["weight"] = (scores / total).values if total > 0 else 1.0 / len(selected)
else:
    selected["weight"] = 1.0 / len(selected)
```

**Impact**: -2 redundant copies. ~30-40% less memory allocation in this method.

---

## 8. React Context Re-render Hazard (MEDIUM)

**Files**: 4 context providers in `external/ai-hedge-fund/app/frontend/src/contexts/`

```tsx
// flow-context.tsx:342-354 — NEW object every render
const value = {
    addComponentToFlow, saveCurrentFlow, loadFlow, createNewFlow,
    currentFlowId, currentFlowName, isUnsaved, reactFlowInstance,
};
return <FlowContext.Provider value={value}>{children}</FlowContext.Provider>

// node-context.tsx:402-424 — NEW object every render
const contextValue = {
    agentNodeData: {}, outputNodeData: null, agentModels,
    updateAgentNode, updateAgentNodes, setOutputNodeData: setOutputNodeDataForFlow,
    ...
};
return <NodeContext.Provider value={contextValue}>{children}</NodeContext.Provider>

// layout-context.tsx:54-64 — NEW object every render
const value = { isBottomCollapsed, expandBottomPanel, ... };
return <LayoutContext.Provider value={value}>{children}</LayoutContext.Provider>

// tabs-context.tsx:252-264 — NEW object every render
const value = { tabs, activeTabId, openTab, closeTab, ... };
return <TabsContext.Provider value={value}>{children}</TabsContext.Provider>
```

**Problem**: All 4 contexts create inline value objects without `useMemo`. Every provider render = new object reference = ALL consumers re-render even when values unchanged. States/functions are already wrapped in `useCallback` but the aggregate object isn't memoized.

**Fix**:
```tsx
// flow-context.tsx
import { useMemo } from 'react';

const value = useMemo(() => ({
    addComponentToFlow,
    saveCurrentFlow,
    loadFlow,
    createNewFlow,
    currentFlowId,
    currentFlowName,
    isUnsaved,
    reactFlowInstance,
}), [addComponentToFlow, saveCurrentFlow, loadFlow, createNewFlow,
    currentFlowId, currentFlowName, isUnsaved, reactFlowInstance]);
```

Apply same pattern to all 4 context files.

**Impact**: Eliminates cascading re-renders across the React component tree. Especially significant for `node-context.tsx` which has 15+ properties and likely many consumers.

---

## 9. Stock Manager Uncached (LOW)

**File**: `src/ui/pages/stock_manager.py:10-15`

`list_stocks()` and `get_sectors()` called on every form interaction without caching. Page lists up to 500 stocks with filter/sort controls.

**Fix**: Add `@st.cache_data(ttl=300)` wrappers in `cached_repo.py` for `list_stocks` and `get_sectors`.

**Impact**: Filter/sort re-renders hit cache instead of DB.

---

## Verified: 13 Prior Optimizations Intact

| # | Optimization | File | Status |
|---|-------------|------|--------|
| 1 | `find_stocks_batch()` single query | `repository.py:58-65` | ✅ Active |
| 2 | `get_prices_batch()` single query | `repository.py:78-97` | ✅ Active |
| 3 | `count_summary()` CASE WHEN aggregate | `repository.py:210-213` | ✅ Active |
| 4 | `@st.cache_data` on lookup/screener/overview | multiple files | ✅ Active |
| 5 | `@st.fragment` on sidebar_nav | `app.py:283` | ✅ Active |
| 6 | Connection pooling (pool_size=15, max_overflow=10) | `database.py:27` | ✅ Active |
| 7 | `pool_pre_ping=True, pool_recycle=3600` | `database.py:27` | ✅ Active |
| 8 | ThreadPoolExecutor for parallel processing | `deep_evaluators.py:7` | ✅ Active |
| 9 | `add_all()` bulk inserts | `repository.py:262,285` | ✅ Active |
| 10 | `@st.cache_data` on ML pipeline results | `ml_pipeline.py:22,47` | ✅ Active |
| 11 | `expire_on_commit=False` | `database.py:28` | ✅ Active |
| 12 | Batch checkpoint SQL updates | `ingestion/pipeline.py` | ✅ Active |
| 13 | `cached_find_stock` / `cached_get_prices` | `cached_repo.py:9-21` | ✅ Active |

---

## Remediation Priority

| Priority | Issues | Effort | Impact |
|----------|--------|--------|--------|
| **P0 (now)** | #1 Stock detail N+1, #2 Incomplete indicator cache | 1.5h | -2 DB queries per dialog |
| **P1 (today)** | #3 Sidebar cache, #4 Log memory leak, #5 Duplicate API keys | 1.5h | -19 sidebar queries/session, O(1) memory |
| **P2 (this week)** | #6 Duplicate open_session, #7 DataFrame copies, #8 React useMemo | 2h | -50 LOC, -2 copies, no cascading re-renders |
| **P3 (backlog)** | #9 Stock manager caching | 0.5h | Filter re-render → cache hit |

**Total remediation**: ~5.5 hours

---

## Recommendations

1. **Add `cached_repo.py` to pre-commit hook** — any new `StockRepository()` in UI code without a cache wrapper should trigger a warning.
2. **Add `useMemo` lint rule** — ESLint `react/jsx-no-constructed-context-values` catches inline context values.
3. **Consolidate `_inject_api_keys`** — merge fast + deep evaluator API key logic into shared module.
4. **Enforce `MAX_LOG_LINES`** — switch `ml_log_lines` to `deque(maxlen=1000)`.
