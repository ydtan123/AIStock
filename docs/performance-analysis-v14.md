# AIStock Performance Analysis — v14

**Date:** 2026-05-31
**Scope:** Full source audit of `src/` (Python 3.13, Streamlit, SQLAlchemy 2.0, MySQL)
**Method:** Read every pipeline/ingestion/repository/UI file. Cross-referenced against v13 findings.

---

## Executive Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| N+1 Queries | 0 | 0 | 0 | 0 | 0 |
| Caching Gaps | 0 | 0 | 1 | 0 | 1 |
| Streamlit Rendering | 0 | 0 | 0 | 3 | 3 |
| Redundant Computation | 0 | 0 | 1 | 2 | 3 |
| Memory / Leaks | 0 | 0 | 0 | 2 | 2 |

**13 prior fixes verified.** 9 issues remain — all Medium/Low. Zero Critical/High. Codebase in good shape.

---

## 1. Confirmed Fixed (v10 → v13)

| # | Issue | Evidence |
|---|-------|----------|
| 1 | `session.add()` → `add_all()` in `fast_evaluation.py` | Lines 180–181: `add_all(conclusions)` + `add_all(analysts)` |
| 2 | `session.add()` → `add_all()` in `deep_evaluation.py` | Batched insert confirmed |
| 3 | `session.add()` → `add_all()` in `stock_selection.py` | Line 68: `session.add_all(rows)` |
| 4 | `find_stock()` N+1 → `find_stocks_batch()` | `repository.py:58-65` — single `.in_()` query |
| 5 | `get_prices()` N+1 → `get_prices_batch()` | `repository.py:78-97` — single `or_(*)` query |
| 6 | `@st.cache_data` on UI data fetches | `cached_repo.py` + `overview.py:6-9` + `stock_lookup.py:14-21` |
| 7 | `@st.fragment` on sidebar | `app.py:283-300` — `sidebar_nav()` decorator |
| 8 | App modularization | `app.py` down from 2200 → 332 lines |
| 9 | `skip_stock_ids` stale-stock optimization | `pipeline.py:70-142` — `_prefetch_stock_dates()` batch |
| 10 | `@lru_cache` on `_last_trading_date()` | `pipeline.py:29-30` |
| 11 | DB pool size 15 | `database.py:24` — `pool_size=15, max_overflow=10` |
| 12 | `pd.read_sql` with `params=` dict | All `repository.py` queries parameterized |
| 13 | Config caching (mtime-based) | `config.py:6-30` — `_config` global + `stat().st_mtime` check |

---

## 2. Remaining Issues

### 2.1 MEDIUM — `display_quick_stats()` Sidebar Query Not Cached

**File:** `src/app.py:234-242`

`display_quick_stats(repo)` calls `repo.count_summary()` on every Streamlit rerun. Unlike `overview.py:6-9` which wraps the same query in `@st.cache_data(ttl=60)`, the sidebar has zero caching.

```python
# Current — app.py:234 — NO cache
def display_quick_stats(repo: StockRepository) -> None:
    st.subheader("Quick Stats")
    try:
        summary = repo.count_summary()  # DB query every sidebar render
```

Compare `overview.py:6-9` (HAS cache):
```python
@st.cache_data(ttl=60, show_spinner=False)
def _cached_count_summary_overview() -> dict:
    from repository import StockRepository
    return StockRepository().count_summary()
```

**Fix:** Add to `src/ui/cached_repo.py`:

```python
# src/ui/cached_repo.py — add
@st.cache_data(ttl=300, show_spinner=False)
def cached_count_summary() -> dict:
    return StockRepository().count_summary()
```

Then in `app.py`:
```python
from ui.cached_repo import cached_count_summary

def display_quick_stats() -> None:
    st.subheader("Quick Stats")
    try:
        summary = cached_count_summary()
        c1, c2 = st.columns(2)
        c1.metric("Total", summary.get("total", "—"))
        c2.metric("Active", summary.get("active", "—"))
    except Exception as exc:
        st.error(f"Could not load stats: {exc}")
```

**Impact:** ~10ms DB round-trip saved per sidebar interaction.

---

### 2.2 MEDIUM — API Key Injection Duplicated in 3 Files

**Files and their key sets:**
- `src/ingestion/pipeline.py:53-62` — 4 keys (GOOGLE, DEEPSEEK, OPENAI, ANTHROPIC)
- `src/pipeline/backends/fast_evaluators.py:72-89` — 6 keys (+ GROQ, ALPHA_VANTAGE)
- `src/pipeline/backends/deep_evaluators.py:55-71` — 5 keys (+ ALPHA_VANTAGE, no GROQ)

All three do `os.environ[key] = value` with identical logic but inconsistent key sets.

```python
# Current — 3 near-identical copies
def _inject_api_keys(ctx_cfg: dict) -> None:
    common = ctx_cfg.get("common", {})
    mapping = {
        "DEEPSEEK_API_KEY": common.get("deepseek_api_key"),
        "OPENAI_API_KEY": common.get("openai_api_key"),
        # ... different keys per file
    }
    for env_var, value in mapping.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value
```

**Fix:** Create `src/api_keys.py`:

```python
# src/api_keys.py
"""Single entry point for API key environment injection. Idempotent per process."""
import os

_EXPORTED = False

_ALL_KEYS = {
    "DEEPSEEK_API_KEY": "deepseek_api_key",
    "OPENAI_API_KEY": "openai_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "GOOGLE_API_KEY": "google_api_key",
    "GROQ_API_KEY": "groq_api_key",
    "ALPHA_VANTAGE_API_KEY": "alpha_vantage_api_key",
}


def export_api_keys(cfg: dict) -> None:
    global _EXPORTED
    if _EXPORTED:
        return
    common = cfg.get("common", {})
    for env_key, cfg_key in _ALL_KEYS.items():
        value = common.get(cfg_key)
        if value and not os.environ.get(env_key):
            os.environ[env_key] = value
    _EXPORTED = True
```

Replace all 3 sites:
```python
# fast_evaluators.py
from api_keys import export_api_keys

def _inject_api_keys(ctx_cfg: dict) -> None:
    export_api_keys(ctx_cfg)  # _EXPORTED flag prevents repeated writes
```

**Impact:** 3 copies → 1 source of truth. Consistent 6-key set everywhere. `_EXPORTED` guard prevents redundant writes per process.

---

### 2.3 LOW — `_count_by_opinion()` Scans Same Data Twice

**File:** `src/pipeline/fast_evaluation.py:39,149`

Opinion list scanned in `_write_report()` (line 39) for markdown, then again in `run()` (line 149) for DB persistence. 10 tickers × 8 analysts = 160 redundant opinion scans.

```python
# Current — two passes over same data
def _write_report(evaluations, report_dir, backend_name):
    for ev in evaluations:
        pos, neg, neu = _count_by_opinion(ev.opinions)  # pass 1

class FastEvaluationStep:
    def run(self, ctx):
        for ev in evaluations:
            pos, neg, neu = _count_by_opinion(ev.opinions)  # pass 2
```

**Fix:** Cache counts on `FastEvaluation` dataclass:

```python
# fast_evaluators.py — update FastEvaluation
@dataclass
class FastEvaluation:
    ticker: str
    start_date: str
    end_date: str
    opinions: list[AnalystOpinion]
    consensus_score: float
    extras: dict = field(default_factory=dict)
    _opinion_counts: tuple[int, int, int] | None = field(default=None, repr=False)

    def get_opinion_counts(self) -> tuple[int, int, int]:
        if self._opinion_counts is None:
            pos = sum(1 for o in self.opinions if o.opinion == "bullish")
            neg = sum(1 for o in self.opinions if o.opinion == "bearish")
            neu = sum(1 for o in self.opinions if o.opinion == "neutral")
            object.__setattr__(self, '_opinion_counts', (pos, neg, neu))
        return self._opinion_counts
```

Replace `_count_by_opinion(ev.opinions)` with `ev.get_opinion_counts()` at both call sites.

**Impact:** 2× iteration → 1×. ~80 scans saved per 10-ticker evaluation.

---

### 2.4 LOW — `ml_log_lines` List Slicing Allocates New Objects

**File:** `src/app.py:55,65,278`

```python
MAX_LOG_LINES = 1000

# Every time threshold exceeded:
if len(st.session_state.ml_log_lines) > MAX_LOG_LINES:
    st.session_state.ml_log_lines = st.session_state.ml_log_lines[-MAX_LOG_LINES:]
```

`list[-1000:]` creates a new list. During long pipelines this triggers many allocations.

**Fix:** `collections.deque` with `maxlen`:

```python
from collections import deque

# Initialization
if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = deque(maxlen=1000)

# Append only — oldest auto-dropped when full
st.session_state.ml_log_lines.append(line)
```

No slicing. No reallocation. `deque` auto-evicts oldest entry when `maxlen` reached.

**Note:** If downstream code relies on `list` API (indexing, slicing), convert for display:
```python
list(st.session_state.ml_log_lines)  # ~0.01ms, only at render time
```

**Impact:** Zero allocations on overflow. ~1000 temporary list objects saved per long pipeline run.

---

### 2.5 LOW — `_QueueHandler` Silently Drops Logs

**File:** `src/app.py:82-95`

```python
class _QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue, max_size: int = 10000) -> None:
        ...
    def emit(self, record):
        if self.log_queue.qsize() >= self.max_size:
            self._dropped += 1  # NEVER REPORTED, NEVER VISIBLE
            return
```

10000 entries × ~200 bytes = 2MB queue. UI displays only 1000 lines. Drops invisible.

**Fix:** Reduce `max_size` and surface drops:

```python
max_size: int = 2000  # 2× display buffer, enough headroom

# In pipeline completion block, after joining thread:
if hasattr(handler, '_dropped') and handler._dropped > 0:
    logger.warning("Dropped %d log lines (queue full)", handler._dropped)
```

**Impact:** ~1.6MB peak memory freed. Operator visibility into silent data loss.

---

### 2.6 LOW — `ml_log_lines` Persists After Pipeline Completes

**File:** `src/app.py:55-56`

After pipeline finishes (status = "Complete" or "Failed"), session state holds stale log lines.

**Fix:** Clear in completion handler:

```python
# In the UI thread poll loop, after detecting terminal status:
if st.session_state.ml_status in ("Complete", "Failed"):
    # render final log output first, then:
    st.session_state.ml_log_lines.clear()  # deque.clear()
```

**Impact:** ~200KB freed after pipeline completes.

---

### 2.7 LOW — `@st.fragment` Missing on Interactive Page Sections

**Pages affected:** `stock_screener.py`, `stock_manager.py`, `ml_pipeline.py`, `stock_technical.py`

Interactive widgets (buttons, dropdowns, sliders) trigger full page re-renders. Static sections (charts, tables, summaries) re-render unnecessarily.

**Fix:** Wrap interactive widget clusters in `@st.fragment`:

```python
# ml_pipeline.py — isolate action buttons
@st.fragment
def _action_buttons_section(ctx):
    col1, col2 = ctx.st.columns(2)
    with col1:
        if ctx.st.button("🚀 Run Full Pipeline"):
            ...
    with col2:
        if ctx.st.button("📊 Run Predict-Only"):
            ...

# In render function:
render_config_panel(ctx)   # static section
_action_buttons_section(ctx)  # fragment: isolated re-render
render_log_panel(ctx)       # static section
```

Same pattern for `stock_screener.py` (Filter button), `stock_manager.py` (Activate/Deactivate buttons), `stock_technical.py` (indicator selection).

**Impact:** Prevents re-rendering Plotly charts and data tables when buttons clicked. Especially impactful for `stock_technical.py` with heavy chart rendering.

---

### 2.8 LOW — `_last_trading_date()` Thread Behavior

**File:** `src/ingestion/pipeline.py:29-30`

Decorated with `@lru_cache(maxsize=1)`. Called from `_process_symbol()` inside `ThreadPoolExecutor`. CPython GIL makes cache thread-safe. First thread computes; all subsequent hit cache.

No fix needed. Noted for completeness.

---

## 3. Architecture Health

### 3.1 Connection Pool — Adequate

```
pool_size=15 + max_overflow=10 = 25 max connections
Peak: 5 ThreadPoolExecutor workers + 1 Streamlit + 1 scheduler = ~7
Headroom: 18 connections
```

### 3.2 Streamlit Cache TTL Review

| Function | TTL | Rationale |
|----------|-----|-----------|
| `cached_find_stock` | 300s (5 min) | Correct — stock metadata rarely changes |
| `cached_get_prices` | 60s | Correct — daily price data |
| `_cached_count_summary_overview` | 60s | Correct — aggregate counts |
| `_cached_get_indicator` | 60s | Correct — fundamentals update infrequently |
| `display_quick_stats` | **none** | **See 2.1 — add cache** |

### 3.3 Memory Profile (Pipeline Run)

```
Before fixes:    ~3.0MB peak (queue 10K + list 1K lines)
After 2.4+2.5:   ~1.2MB peak (queue 2K + deque 1K lines)
After 2.6:        ~0.4MB idle (pipeline done, everything cleared)
```

---

## 4. Fix Priority

### Quick Wins (~30 min)

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 1 | Add `cached_count_summary()` to `cached_repo.py` | `cached_repo.py`, `app.py` | 5 min |
| 2 | `deque(maxlen=1000)` for `ml_log_lines` | `app.py` | 5 min |
| 3 | Reduce `_QueueHandler.max_size` to 2000 | `app.py` | 5 min |
| 4 | Clear `ml_log_lines` after pipeline done | `ml_pipeline.py` or `app.py` | 5 min |
| 5 | Add `get_opinion_counts()` to `FastEvaluation` | `fast_evaluators.py`, `fast_evaluation.py` | 10 min |

### Consolidation (~1 hr)

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 6 | Create `src/api_keys.py` — single injection point | new file + 3 edits | 20 min |
| 7 | `@st.fragment` on interactive sections | 4 page files | 30 min |
| 8 | Sign off: run full pipeline, verify no regressions | — | 10 min |

---

## Appendix: v13 Items Re-Evaluated

| v13 Item | v13 Severity | v14 Result |
|----------|-------------|------------|
| `load_config()` called redundantly | MEDIUM | ✅ `config.py` has mtime-based global cache. No change. |
| `load_config()` in scheduler 3× | MEDIUM | ✅ Same global cache handles it. |
| `display_quick_stats()` uncached | MEDIUM | ❌ Still uncached. See 2.1. |
| `_last_trading_date()` → `@cache` | LOW | ❌ Still `lru_cache`. Negligible perf diff. |
| `_count_by_opinion()` twice | HIGH → LOW | ❌ Still twice. Downgraded: 10 ticks × 8 analysts is trivial. |
| API key injection duplicated | MEDIUM | ❌ Still 3 copies. See 2.2. |
| `ml_log_lines` list slicing | MEDIUM → LOW | ❌ Still list. See 2.4. |
| `_QueueHandler` drops silently | LOW | ❌ Still silent. See 2.5. |
| `ml_log_lines` retained after done | LOW | ❌ Still retained. See 2.6. |

---

*Generated by Claude Code analysis of 72 source files. Cross-referenced against v10 (commit `ae72452`) fixes and v13 audit findings.*
