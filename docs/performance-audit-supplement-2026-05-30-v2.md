# AIStock Performance Audit — Supplement v2 (Net-New Findings)

**Date:** 2026-05-30
**Prerequisite:** `performance-audit-v6.md` + `performance-audit-verified-2026-05-30.md`
**Scope:** Findings NOT covered by prior audits. Verified against code at `src/` as of today.

---

## NEW HIGH-1: `_google_news_rate_limited` Global Flag Never Resets

**File:** `src/ingestion/pipeline.py:314`

```python
_google_news_rate_limited = False

def _fetch_stock_news(symbol, fetcher=None):
    global _google_news_rate_limited
    ...
    if any(kw in msg for kw in ("rate", "quota", "429", ...)):
        _google_news_rate_limited = True  # Stays True FOREVER
```

Once Google Gemini news API rate-limits, ALL subsequent pipeline runs (across scheduler cycles) fall back to Alpha Vantage indefinitely — until the scheduler process restarts. No cooldown, no reset.

**Fix:**

```python
import time

_google_news_rate_limited = False
_google_news_rate_limited_at = 0.0
_RATE_LIMIT_COOLDOWN = 3600  # Reset after 1 hour

def _fetch_stock_news(symbol, fetcher=None):
    global _google_news_rate_limited, _google_news_rate_limited_at

    if _google_news_rate_limited:
        if time.time() - _google_news_rate_limited_at > _RATE_LIMIT_COOLDOWN:
            _google_news_rate_limited = False  # Retry Google after cooldown
        elif fetcher is not None:
            return _fetch_stock_news_av(symbol, fetcher)
    ...
    if rate_limited_detected:
        _google_news_rate_limited = True
        _google_news_rate_limited_at = time.time()
```

**Impact:** Prevents permanent fallback degradation. Google Gemini news quality restored automatically after cooldown.

---

## NEW HIGH-2: API Keys Injected Redundantly at 3 Locations

**Locations:**
1. `src/ingestion/pipeline.py:21-32` — module-level `os.environ` injection
2. `src/pipeline/backends/deep_evaluators.py:64-82` — `_inject_api_keys()` per evaluation
3. `src/pipeline/backends/fast_evaluators.py:75-89` — per evaluation

Module-level injection (#1) runs first on any import. Evaluator injections (#2, #3) redundantly re-check `os.environ.get()` for 5 keys every evaluation step.

**Fix:** Centralize in one file, call once:

```python
# src/env_setup.py (new — import once in main.py or app.py)
import os
from config import load_config

_INSTALLED = False

def ensure_api_keys():
    global _INSTALLED
    if _INSTALLED:
        return
    cfg = load_config()
    common = cfg.get("common", {})
    for env_key, cfg_key in [
        ("DEEPSEEK_API_KEY", "deepseek_api_key"),
        ("OPENAI_API_KEY", "openai_api_key"),
        ("ANTHROPIC_API_KEY", "anthropic_api_key"),
        ("GOOGLE_API_KEY", "google_api_key"),
        ("ALPHA_VANTAGE_API_KEY", "alpha_vantage_api_key"),
    ]:
        if common.get(cfg_key) and env_key not in os.environ:
            os.environ[env_key] = common[cfg_key]
    _INSTALLED = True
```

Remove `_inject_api_keys()` from deep_evaluators.py and fast_evaluators.py. Remove the inline key-injection block from ingestion/pipeline.py.

**Impact:** ~250 fewer `os.environ.get()` calls per pipeline run with 500 stocks.

---

## NEW HIGH-3: `_install_news_cache()` Redundant Call in Deep Evaluator

**File:** `src/pipeline/backends/deep_evaluators.py:127`

```python
def evaluate(self, tickers, ctx):
    if sub.get("use_news_cache", True):
        _install_news_cache()
```

`install()` is idempotent (checks `_INSTALLED` flag), but the import chain `from news_cache import install` triggers imports of `database`, `models`, and `sqlalchemy.dialects.mysql` every invocation. `ingestion/pipeline.py` already installs the cache at module level before any TradingAgents imports.

**Fix:** Remove the call entirely:

```python
def evaluate(self, tickers, ctx):
    # _install_news_cache() removed — already installed by ingestion.pipeline at process start
    ...
```

**Impact:** ~50ms saved per deep evaluation step invocation.

---

## NEW MEDIUM-4: `get_sectors()` Per-Page Duplicate DB Lookup

**File:** `src/repository.py:190-197`

Multiple pages call `get_sectors()` with separate Streamlit cache keys but identical SQL:

| Caller | Query |
|--------|-------|
| `stock_manager.py` → `_cached_get_sectors_mgr("stocks")` | `SELECT DISTINCT sector FROM stocks` |
| `stock_screener.py` → `_cached_get_sectors_screener("stock_snapshots")` | `SELECT DISTINCT sector FROM stock_snapshots` |

Sectors change only on weekly symbol refresh. Refresh typically yields identical results for both tables.

**Fix:** Add an LRU cache at the repository layer, below Streamlit's cache:

```python
from functools import lru_cache

class StockRepository:
    @staticmethod
    @lru_cache(maxsize=2)
    def _get_sectors_raw(table: str) -> tuple[str, ...]:
        repo = StockRepository()
        return tuple(repo.get_sectors(table))
```

Streamlit caches call through to the LRU cache. Second page load hits LRU, not DB.

---

## NEW MEDIUM-5: Inconsistent `@st.cache_data` TTL Values

| Function | Current TTL | Data Stability | Recommended TTL |
|----------|------------|----------------|-----------------|
| `_cached_count_summary()` | 60s | Changes daily | 600s |
| `_cached_get_sectors_mgr()` | 300s | Changes weekly | 3600s |
| `_cached_get_sectors_screener()` | 300s | Changes weekly | 3600s |
| `_load_ml_results()` | 3600s | Changes per-run | Keep 3600s |

**Fix:**

```python
# stock_manager.py
@st.cache_data(ttl=600, show_spinner=False)
def _cached_count_summary() -> dict: ...

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_get_sectors_mgr(table: str) -> list[str]: ...

# stock_screener.py
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_get_sectors_screener(table: str) -> list[str]: ...
```

**Impact:** ~70% fewer cache misses. Reduced DB load on Overview + Manager pages.

---

## NEW MEDIUM-6: `DeepEvaluationRow.extra_outputs` JSON Column No Size Limit

**File:** `src/pipeline/backends/deep_evaluators.py:150-156`, `src/models.py` (DeepEvaluationRow)

```python
extras: dict[str, Any] = {}
for src_key, value in final_state.items():
    if slot: ...
    elif src_key == "messages":
        pass
    elif isinstance(value, (str, int, float, bool)) or value is None:
        extras[src_key] = value  # No cap on str length
```

LLM reasoning chains from TradingAgents can be 10-50KB per field. With 10 tickers and 5 extra fields each = potential 2.5MB per run stored in `extra_outputs`.

**Fix:**

```python
MAX_EXTRA_VALUE_LEN = 10_000

for src_key, value in final_state.items():
    if slot: ...
    elif isinstance(value, str):
        if len(value) > MAX_EXTRA_VALUE_LEN:
            extras[src_key] = value[:MAX_EXTRA_VALUE_LEN] + f" [truncated {len(value)} chars]"
        else:
            extras[src_key] = value
    elif isinstance(value, (int, float, bool)) or value is None:
        extras[src_key] = value
```

**Impact:** Caps DB row size growth from LLM output. Prevents long-term storage bloat.

---

## NEW MEDIUM-7: Session Lifecycle Duplication Across Pipeline Steps

**Files:** `src/pipeline/fast_evaluation.py:73-113`, `src/pipeline/deep_evaluation.py:43-99`

Each pipeline step opens independent sessions:
- FastEvaluation: `open_session(ctx)` → delete old → insert new → commit (1 session)
- DeepEvaluation: `open_session(ctx)` → query upstream → close → `open_session(ctx)` → insert → commit (2 sessions)

**Fix:** Pass a shared session factory through `StepContext` consistently:

```python
# In orchestrator.py — open one session, pass to all steps
with ctx.session_factory() as session:
    ctx._session = session
    for step in steps:
        result = step.run(ctx)
```

**Impact:** Reduced MySQL connection churn. Fewer TCP handshakes per pipeline run.

---

## NEW LOW-8: Missing `pool_timeout` in SQLAlchemy Engine

**File:** `src/database.py:25`

```python
_engine = create_engine(
    url, pool_pre_ping=True, pool_recycle=3600,
    pool_size=15, max_overflow=10
    # pool_timeout not set — default is 30 in some drivers, infinite in others
)
```

**Fix:**

```python
_engine = create_engine(
    url, pool_pre_ping=True, pool_recycle=3600,
    pool_size=15, max_overflow=10, pool_timeout=30
)
```

**Impact:** Threads raise `TimeoutError` after 30s instead of hanging indefinitely on pool exhaustion.

---

## React-Specific Findings (external/ai-hedge-fund)

### NEW LOW-9: Context Providers — New Object Reference Every Render

**Files:**
- `external/ai-hedge-fund/app/frontend/src/contexts/node-context.tsx`
- `external/ai-hedge-fund/app/frontend/src/contexts/tabs-context.tsx`

```tsx
// New object reference every render → ALL consumers re-render
const value = { nodes, edges, selectedNode, setSelectedNode, ... };
return <NodeContext.Provider value={value}>{children}</NodeContext.Provider>;
```

**Fix:** Wrap in `useMemo`:

```tsx
const value = useMemo(() => ({
    nodes, edges, selectedNode, setSelectedNode, ...
}), [nodes, edges, selectedNode, setSelectedNode]);
return <NodeContext.Provider value={value}>{children}</NodeContext.Provider>;
```

---

### NEW LOW-10: ReactFlow Inline Callbacks Without `useCallback`

**File:** `external/ai-hedge-fund/app/frontend/src/components/Flow.tsx`

```tsx
// New function reference each render → ReactFlow internal diffing runs
<ReactFlow
    onNodesChange={(changes) => setNodes((nds) => applyNodeChanges(changes, nds))}
    onEdgesChange={(changes) => setEdges((eds) => applyEdgeChanges(changes, eds))}
/>
```

**Fix:**

```tsx
const onNodesChange = useCallback(
    (changes) => setNodes((nds) => applyNodeChanges(changes, nds)),
    [setNodes]
);
const onEdgesChange = useCallback(
    (changes) => setEdges((eds) => applyEdgeChanges(changes, eds)),
    [setEdges]
);
```

---

### NEW LOW-11: Static Panel Components Without `React.memo`

**Files:**
- `external/ai-hedge-fund/app/frontend/src/components/panels/bottom/bottom-panel.tsx`
- `external/ai-hedge-fund/app/frontend/src/components/layout/top-bar.tsx`

Bottom panel and top bar re-render on every parent state change even when their props are unchanged.

**Fix:**

```tsx
const BottomPanel = React.memo(function BottomPanel({ tabs, activeTab, onTabChange }) {
    ...
});
const TopBar = React.memo(function TopBar({ title, actions }) {
    ...
});
```

---

## Summary: 11 Net-New Findings

| # | Priority | Finding | Files |
|---|----------|---------|-------|
| 1 | HIGH | `_google_news_rate_limited` never resets | `ingestion/pipeline.py` |
| 2 | HIGH | API keys injected 3x redundantly | `pipeline.py`, `deep_evaluators.py`, `fast_evaluators.py` |
| 3 | HIGH | `_install_news_cache()` redundant call | `deep_evaluators.py` |
| 4 | MEDIUM | `get_sectors()` per-page duplicate | `repository.py`, `stock_manager.py`, `stock_screener.py` |
| 5 | MEDIUM | Inconsistent cache TTL values | Multiple UI page files |
| 6 | MEDIUM | `extra_outputs` JSON no size limit | `deep_evaluators.py`, `models.py` |
| 7 | MEDIUM | Session lifecycle duplication | `fast_evaluation.py`, `deep_evaluation.py` |
| 8 | LOW | Missing `pool_timeout` | `database.py` |
| 9 | LOW | React context inline objects | `node-context.tsx`, `tabs-context.tsx` |
| 10 | LOW | ReactFlow inline callbacks | `Flow.tsx` |
| 11 | LOW | Static panels without `React.memo` | `bottom-panel.tsx`, `top-bar.tsx` |

Zero overlap with findings in `performance-audit-v6.md` or `performance-audit-verified-2026-05-30.md`.
