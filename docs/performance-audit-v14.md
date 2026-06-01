# AIStock Performance Audit v14

> **Date**: 2026-05-30  
> **Scope**: N+1 queries, caching gaps, memory leaks, redundant computation, Streamlit rendering  
> **Framework**: Python/Streamlit (no React — re-render analysis replaced with Streamlit caching patterns)  
> **Severity**: 🔴 Critical · 🟠 High · 🟡 Medium · ⚪ Low

---

## Summary Table

| Category | 🔴 | 🟠 | 🟡 | ⚪ | Total |
|----------|----|----|----|----|-------|
| N+1 Query Patterns | 2 | 2 | 2 | 0 | 6 |
| Caching Gaps | 1 | 2 | 2 | 1 | 6 |
| Memory Leaks | 1 | 1 | 1 | 0 | 3 |
| Redundant Computation | 0 | 2 | 1 | 1 | 4 |
| Streamlit Rendering | 0 | 1 | 1 | 2 | 4 |
| **Totals** | **4** | **8** | **7** | **4** | **23** |

---

## 1. N+1 Query Patterns

### 🔴 1.1 Per-Stock `compute_indicators` Called in ThreadPoolExecutor

**File**: `src/ingestion/indicators.py:compute_indicators()`  
**File**: `src/ingestion/pipeline.py:_process_symbol()`

Every stock processed via `run_daily_pipeline()` calls `compute_indicators(stock_id)` individually inside ThreadPoolExecutor workers. Each call:

1. Opens DB connection → queries `daily_prices` for that single stock
2. Runs 30+ `pandas_ta` indicators
3. Upserts into `technical_indicators`

With 500 active stocks: 500 separate DB queries + 500 indicator computations.

**Fix** — Add batch method:

```python
# src/ingestion/indicators.py
def compute_indicators_batch(stock_ids: list[int],
                             since_date: date | None = None) -> int:
    """Single-pass indicator computation for multiple stocks."""
    engine = get_engine()
    load_from = (since_date - timedelta(days=_LOOKBACK_DAYS)) if since_date else None
    total_written = 0

    with engine.connect() as conn:
        if load_from:
            rows = conn.execute(
                text("SELECT stock_id, date, open, high, low, close, volume "
                     "FROM daily_prices WHERE stock_id IN :ids AND date >= :from_dt "
                     "ORDER BY stock_id, date"),
                {"ids": tuple(stock_ids), "from_dt": load_from},
            ).fetchall()
        else:
            rows = conn.execute(
                text("SELECT stock_id, date, open, high, low, close, volume "
                     "FROM daily_prices WHERE stock_id IN :ids ORDER BY stock_id, date"),
                {"ids": tuple(stock_ids)},
            ).fetchall()

    # Group by stock_id, compute, bulk insert
    df = pd.DataFrame(rows, columns=["stock_id", "date", "open", "high", "low", "close", "volume"])
    for sid, group in df.groupby("stock_id"):
        total_written += _compute_and_store(sid, group)
    return total_written
```

---

### 🔴 1.2 Per-Ticker LLM Agent Graph Propagation

**File**: `src/pipeline/backends/deep_evaluators.py:TradingAgentsDeepEvaluator._evaluate_one()`

Each ticker spins up a full LangGraph pipeline with 5+ analyst sub-agents, each making LLM API calls. The `_evaluate_one` function runs per ticker inside `ThreadPoolExecutor(max_workers=3)`.

```
20 tickers × (market + social + news + fundamentals + bull/bear debate
+ research manager + risk manager + trader) ≈ 140–200 LLM API calls
```

Some calls fetch overlapping data (same sector news, same fundamental metrics).

**Fix** — Add cross-ticker caching and DB-backed result cache:

```python
# In TradingAgentsDeepEvaluator.run_batch():
from models import DeepEvaluation as DeepEvalModel

def _evaluate_one(tkr: str):
    # 1. Check DB for prior evaluation at same date
    session = get_session()
    try:
        existing = session.query(DeepEvalModel).filter_by(
            ticker=tkr, evaluation_date=eval_date
        ).first()
        if existing and existing.agent_outputs:
            session.close()
            return tkr, _model_to_deep_evaluation(existing), None
    finally:
        session.close()

    # 2. Proceed with LLM evaluation
    try:
        result = graph.propagate(tkr, eval_date)
        return tkr, result, None
    except Exception as e:
        return tkr, None, str(e)

# 3. Pre-fetch shared data once for all tickers
sector_news = _fetch_sector_news(all_tickers, eval_date)  # one call, not N
macro_data = _fetch_macro_context(eval_date)                # one call, not N
```

---

### 🟠 1.3 Missing Batch Versions for Per-Stock Queries

**File**: `src/repository.py`

`get_indicator()` and `get_snapshot()` have no batch counterparts. When the UI or pipeline iterates over stocks, each calls the DB individually.

**Fix**:

```python
# src/repository.py — add batch methods
def get_indicators_batch(self, stock_ids: list[int]) -> dict[int, StockIndicator]:
    if not stock_ids:
        return {}
    def _query(s):
        rows = s.query(StockIndicator).filter(
            StockIndicator.stock_id.in_(stock_ids)
        ).all()
        return {r.stock_id: r for r in rows}
    return self._with_session(_query)

def get_snapshots_batch(self, stock_ids: list[int]) -> dict[int, StockSnapshot]:
    if not stock_ids:
        return {}
    def _query(s):
        rows = s.query(StockSnapshot).filter(
            StockSnapshot.stock_id.in_(stock_ids)
        ).all()
        return {r.stock_id: r for r in rows}
    return self._with_session(_query)
```

---

### 🟠 1.4 Per-Stock News API Call in Pipeline

**File**: `src/ingestion/pipeline.py:_fetch_stock_news()`

`_process_symbol` calls `_fetch_stock_news(stock.symbol)` per stock. Already mitigated by `news_cache.install()` intercepting `route_to_vendor` and checking `stock_news` DB table. However, the Alpha Vantage fallback path (`_fetch_stock_news_av`) does NOT go through the cache layer.

**Fix**:

```python
# src/ingestion/pipeline.py
from news_cache import get_cached, set_cached

def _fetch_stock_news_av(symbol: str, fetcher) -> int:
    # Check cache first (same pattern as news_cache layer)
    today = _last_trading_date()
    lookback = today - timedelta(days=NEWS_LOOKBACK_DAYS)
    cached = get_cached("get_news", (symbol, str(lookback), str(today)), {})
    if cached is not None:
        return len(cached)
    # ... fetch and cache
```

Added benefit: this uses the same `stock_news` table as the Gemini path.

---

### 🟡 1.5 ORM Default Lazy Loading

**File**: `src/models.py`

All `relationship()` definitions use default `lazy="select"`. Accessing `stock.indicator` or `stock.daily_prices` after a query triggers a separate SELECT per access.

**Fix**:

```python
# src/models.py — set explicit lazy strategy
daily_prices = relationship("DailyPrice", back_populates="stock", lazy="raise")
indicator = relationship("StockIndicator", back_populates="stock", uselist=False, lazy="raise")

# Query with explicit eager loading where needed:
from sqlalchemy.orm import joinedload
stocks = session.query(Stock).options(joinedload(Stock.indicator)).all()
```

`lazy="raise"` surfaces accidental N+1 queries immediately instead of silently degrading performance.

---

### 🟡 1.6 `run_daily_pipeline` Opens Multiple Sessions

**File**: `src/ingestion/pipeline.py:run_daily_pipeline()`

Function opens: (1) session for PipelineRun insert, (2) session for stock query, (3+) per-worker sessions in downstream functions. Each `_process_symbol` worker opens its own session — with 500 stocks that is 500+ `get_session()`/`close()` cycles.

**Verdict**: Near-optimal for concurrent processing. Each ThreadPoolExecutor worker must own its session (SQLAlchemy sessions are not thread-safe). The `_prefetch_stock_dates` optimization already batches pre-flight queries. ✅ No action needed.

---

## 2. Caching Gaps

### 🔴 2.1 `load_config()` Called Without Module-Level Cache

**Files**: `src/config.py`, `src/ingestion/pipeline.py`, `src/database.py`

`config.yaml` changes rarely. YAML read + parse on every function invocation wastes I/O. Within a single pipeline run, `load_config()` is called up to ~1000 times (once in `run_daily_pipeline` + once per stock in downstream functions).

**Fix** — `src/config.py`:

```python
from functools import lru_cache

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

@lru_cache(maxsize=1)
def load_config(config_path: str | None = None) -> dict:
    path = Path(config_path) if config_path else _CONFIG_PATH
    with open(path) as f:
        return yaml.safe_load(f)

def clear_config_cache() -> None:
    """Invalidate cache (call after config file changes)."""
    load_config.cache_clear()
```

---

### 🟠 2.2 Deep Evaluation LLM Results Not Cached Across Runs

**File**: `src/pipeline/backends/deep_evaluators.py`

Re-running deep evaluation on the same ticker + same date makes fresh LLM API calls. Each ticker evaluation costs approximately $0.10–0.50 in API tokens.

**Fix** — Check DB for existing evaluation before calling LLM:

```python
# In TradingAgentsDeepEvaluator._evaluate_one():
def _evaluate_one(tkr: str):
    # Check DB cache
    session = get_session()
    try:
        existing = session.query(DeepEvalModel).filter_by(
            ticker=tkr,
            evaluation_date=eval_date
        ).first()
        if existing and existing.agent_outputs:
            return tkr, _model_to_deep_evaluation(existing), None
    finally:
        session.close()

    # LLM evaluation
    result = graph.propagate(tkr, eval_date)
    ...
```

---

### 🟠 2.3 Missing `@st.cache_resource` for Database Objects in Streamlit

**File**: `src/ui/cached_repo.py`

Every `@st.cache_data` function creates `StockRepository()` — a new SQLAlchemy session per call. A page with 3 cached data fetches creates 3 separate sessions per render.

**Fix**:

```python
# src/ui/cached_repo.py
import streamlit as st
from repository import StockRepository

@st.cache_resource
def _get_repo() -> StockRepository:
    """Singleton repository — one session factory reused across UI."""
    return StockRepository()

@st.cache_data(ttl=300, show_spinner=False)
def cached_find_stock(symbol: str) -> dict | None:
    stock = _get_repo().find_stock(symbol)
    ...
```

---

### 🟡 2.4 Inconsistent Cache TTLs in Streamlit

| Function | TTL | Function | TTL |
|----------|-----|----------|-----|
| `_cached_count_summary_overview` | 60s | `_cached_get_sectors_mgr` | 300s |
| `cached_get_prices` | 60s | `_cached_screen_stocks` | 300s |
| `_cached_get_indicator` | 60s | `_load_ml_results` | 3600s |

Count summary (60s) refreshes 5× more often than sector list (300s) — both hit the `stocks` table.

**Fix** — Define and apply consistent tiers:

```python
# src/ui/cache_tiers.py
CACHE_FAST   = 60    # overview stats, prices (during market hours)
CACHE_NORMAL = 300   # screeners, sectors, fundamentals
CACHE_SLOW   = 3600  # ML results, backtests

# Apply consistently across all pages
@st.cache_data(ttl=CACHE_FAST, show_spinner=False)
def _cached_count_summary() -> dict: ...
```

---

### 🟡 2.5 `compute_indicators` No Pre-Check for Existing Data

**File**: `src/ingestion/indicators.py`

No query to check whether indicators for `since_date` are already computed. When called with the same `since_date` repeatedly, it recomputes and upserts identical data.

**Fix**:

```python
def compute_indicators(stock_id: int, since_date: date | None = None) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        if since_date:
            latest = conn.execute(
                text("SELECT MAX(date) FROM technical_indicators WHERE stock_id = :sid"),
                {"sid": stock_id},
            ).scalar()
            if latest and latest >= _last_trading_date():
                return 0  # Already up to date
    # ... rest of computation
```

---

### ⚪ 2.6 `_inject_api_keys` Already Has Guard

**File**: `src/pipeline/backends/deep_evaluators.py`

```python
if value and not os.environ.get(env_var):
    os.environ[env_var] = value
```

Already checks `os.getenv` before writing — no redundant writes occur. ✅ No action needed.

---

## 3. Memory Leaks

### 🔴 3.1 `ml_log_lines` Accumulation in Session State

**File**: `src/app.py`

```python
if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = []   # ← unbounded list
MAX_LOG_LINES = 1000                      # ← defined but not enforced on write
```

The cap is only applied at display time via `deque(log_lines, maxlen=300)`. The underlying list grows unbounded. A long-running session with multiple ML pipeline runs eventually holds tens of thousands of log lines in memory.

**Fix**:

```python
from collections import deque

if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = deque(maxlen=MAX_LOG_LINES)

# In append path — deque with maxlen auto-trims:
st.session_state.ml_log_lines.append(line)
```

Or, if list must be kept for other consumers, trim eagerly:

```python
# In the log polling loop:
if len(st.session_state.ml_log_lines) > MAX_LOG_LINES:
    st.session_state.ml_log_lines = st.session_state.ml_log_lines[-MAX_LOG_LINES:]
```

---

### 🟠 3.2 Global Mutable Progress Counters

**File**: `src/ingestion/pipeline.py`

```python
_progress_count = 0
_progress_total = 0
_progress_lock = threading.Lock()
```

Module-level globals shared across pipeline runs. If two runs overlap (scheduled job + manual trigger), they corrupt each other. A failed run leaves stale values visible to the next run.

**Fix** — Replace with a context object:

```python
from dataclasses import dataclass, field
from threading import Lock

@dataclass
class PipelineProgress:
    count: int = 0
    total: int = 0
    lock: Lock = field(default_factory=Lock)

# Pass into run_daily_pipeline() instead of globals
def run_daily_pipeline(fetcher, force=False,
                       symbols=None, progress=None):
    progress = progress or PipelineProgress()
    ...
    with progress.lock:
        progress.count = 0
        progress.total = len(stocks_to_process)
```

---

### 🟡 3.3 `PageContext` Self-Referential Session State

**File**: `src/app.py:_build_ctx()`

```python
st.session_state.ctx = PageContext(
    st=st,
    repo=repo,
    session_state=st.session_state,  # ← self-referential
    ...
)
```

Storing `session_state` inside a dataclass that lives inside `session_state` creates a reference cycle. Streamlit clears session state on browser disconnect, so this is not a true leak. However, `repo` and function references (`pipeline_thread_target`) prevent garbage collection of objects that could otherwise be freed.

**Verdict**: Low impact. Matching known Streamlit pattern. ✅ No action needed unless memory profiling shows issues.

---

## 4. Redundant Computation

### 🟠 4.1 `load_config()` Called Multiple Times Per Pipeline Run

**Files**: `src/ingestion/pipeline.py`, `src/database.py`

Within a single `run_daily_pipeline()` call:
- Called in `run_daily_pipeline` (for `refresh_days`)
- Called per-stock in `_upsert_fundamentals`

With 500 stocks: ~501 YAML reads + parses.

**Fix**: See §2.1 — add `@lru_cache(maxsize=1)`.

---

### 🟠 4.2 `compute_indicators` Full History Backfill

**File**: `src/ingestion/indicators.py`

When `since_date=None` (full backfill), ALL historical prices (potentially 10+ years) are fetched. Only the last `_LOOKBACK_DAYS=200` rows are needed for indicator warm-up.

**Fix** — Cap backfill range:

```python
MAX_BACKFILL_DAYS = 365 * 5  # 5 years maximum

def compute_indicators(stock_id: int, since_date: date | None = None) -> int:
    if since_date is None:
        since_date = date.today() - timedelta(days=MAX_BACKFILL_DAYS)
    # ... existing logic uses since_date for load_from
```

---

### 🟡 4.3 `_FINAL_STATE_TO_SLOT` Dict Lookup Per Ticker

**File**: `src/pipeline/backends/deep_evaluators.py`

```python
for src_key, value in final_state.items():
    slot = _FINAL_STATE_TO_SLOT.get(src_key)
```

Iterates all ~15 keys per ticker. Micro-optimization — negligible CPU savings.

**Fix** (optional):

```python
_KNOWN_SLOTS = set(_FINAL_STATE_TO_SLOT)
for src_key, value in final_state.items():
    if src_key in _KNOWN_SLOTS:
        agent_outputs[_FINAL_STATE_TO_SLOT[src_key]] = str(value)
```

---

### ⚪ 4.4 `_last_trading_date` `lru_cache(maxsize=1)` Staleness

**File**: `src/ingestion/pipeline.py`

```python
@lru_cache(maxsize=1)
def _last_trading_date() -> date:
```

If a pipeline runs across midnight UTC, cached value is stale. Unlikely in practice — `maxsize=1` evicts on next call with different arguments, but no arguments exist, so cache persists until cache_clear.

**Fix** (optional):

```python
@lru_cache(maxsize=2)
def _last_trading_date(for_date: date | None = None) -> date:
    ref = for_date or date.today()
    ...
```

---

## 5. Streamlit Rendering Performance

### 🟠 5.1 `display_quick_stats` Uncached DB Query

**File**: `src/app.py:display_quick_stats()`

Called on every sidebar render — triggers `COUNT(*)` on `stocks` table every rerun.

```python
def display_quick_stats(repo: StockRepository) -> None:
    summary = repo.count_summary()  # ← DB query every rerender
```

**Fix**:

```python
from ui.pages.overview import _cached_count_summary_overview

def display_quick_stats(repo: StockRepository) -> None:
    summary = _cached_count_summary_overview()  # ← 60s TTL cache
```

---

### 🟡 5.2 `StockRepository` Instantiated Per Cached Function

**File**: `src/ui/cached_repo.py`

```python
@st.cache_data(ttl=300, show_spinner=False)
def cached_find_stock(symbol: str) -> dict | None:
    stock = StockRepository().find_stock(symbol)  # New instance every call
```

`StockRepository()` is cheap but creates a session per `_with_session`. Better to share via singleton.

**Fix**: See §2.3 — wrap in `@st.cache_resource`.

---

### 🟡 5.3 Inconsistent `plotly_chart` Width API

**File**: Various `src/ui/pages/*.py`

Mixed usage: `width='stretch'` (deprecated in Streamlit ≥1.28) and `use_container_width=True` (current API).

**Fix** — Normalize:

```python
# Before:
ctx.st.plotly_chart(fig, width='stretch')

# After:
ctx.st.plotly_chart(fig, use_container_width=True)
```

---

### ⚪ 5.4 Tab Content Eager Rendering

**File**: Multiple tab-based pages

Streamlit renders all tabs when the page loads. `render_ml_pipeline` with charts and data tables is computed even when the user never clicks the ML Pipeline tab.

**Verdict**: Streamlit architectural limitation. No clean fix without major page restructuring. ⚪ Low priority.

---

### ⚪ 5.5 `st.dataframe` Triggers Full Rerender on Selection

**File**: `src/ui/pages/ml_pipeline.py`

```python
event = ctx.st.dataframe(tdf, selection_mode="single-row",
                         on_select="rerun", ...)
```

Each row click triggers a full script rerun. Required for the stock detail panel to update, but could be optimized with `st.fragment` (Streamlit ≥1.33).

**Fix** (requires Streamlit ≥1.33):

```python
@st.fragment
def _render_stock_table(tdf, display_cols):
    event = st.dataframe(tdf, selection_mode="single-row",
                         on_select="rerun", key="ml_selected_stocks")
    ...
```

---

## 6. Verified Optimizations (No Action Needed)

| Optimization | Location | Note |
|-------------|----------|------|
| `@lru_cache(maxsize=1)` on `_last_trading_date()` | `ingestion/pipeline.py` | ✅ Correct |
| `_prefetch_stock_dates()` 4-for-4N batch | `ingestion/pipeline.py` | ✅ Good |
| `get_prices_batch()` + `find_stocks_batch()` | `repository.py` | ✅ Used in predict pipeline |
| `news_cache.install()` intercepts `route_to_vendor` | `news_cache.py` | ✅ DB-backed cache |
| `@st.cache_data` on data-fetching functions | `ui/pages/*.py` | ✅ Prevents rerender DB queries |
| DB pool: `pool_size=15, pool_recycle=3600, pool_pre_ping=True` | `database.py` | ✅ Good config |
| `on_duplicate_key_update` for upserts | `ingestion/pipeline.py` | ✅ No SELECT-before-INSERT |
| `_batch_update_checkpoints()` single UPDATE | `ingestion/pipeline.py` | ✅ Correct |
| `skip_stock_ids` filtering pre-processing | `ingestion/pipeline.py` | ✅ Avoids redundant work |
| `ThreadPoolExecutor(max_workers=8)` | `ingestion/pipeline.py` | ✅ Parallel processing |
| Deadlock retry (5× prices, 3× fundamentals) | `ingestion/pipeline.py` | ✅ Handles MySQL 1213 |

---

## 7. Remediation Plan

### Phase 1 — Quick Wins (1–2 hours, 8 issues)

| # | Issue | Severity | Effort |
|---|-------|----------|--------|
| 1 | Add `@lru_cache` to `load_config()` | 🔴 | 5 min |
| 2 | Replace `ml_log_lines` list with `deque(maxlen=...)` | 🔴 | 5 min |
| 3 | Use cached count summary in `display_quick_stats` | 🟠 | 5 min |
| 4 | Add `@st.cache_resource` for `StockRepository` | 🟠 | 10 min |
| 5 | Add `get_indicators_batch()` to repository | 🟠 | 15 min |
| 6 | Add `get_snapshots_batch()` to repository | 🟠 | 15 min |
| 7 | Normalize Streamlit cache TTLs | 🟡 | 10 min |
| 8 | Add pre-check in `compute_indicators` | 🟡 | 15 min |

### Phase 2 — Structural (3–5 hours, 4 issues)

| # | Issue | Severity | Effort |
|---|-------|----------|--------|
| 9 | `compute_indicators_batch()` batch computation | 🔴 | 2 hr |
| 10 | Deep evaluation result caching in DB | 🟠 | 1 hr |
| 11 | Replace globals with `PipelineProgress` dataclass | 🟠 | 1 hr |
| 12 | Cap full-backfill price history to 5 years | 🟠 | 30 min |

### Phase 3 — Strategic (when needed, 5 issues)

| # | Issue | Severity | Effort |
|---|-------|----------|--------|
| 13 | Cross-ticker LLM call dedup | 🔴 | 4 hr |
| 14 | ORM eager loading audit with `lazy="raise"` | 🟡 | 2 hr |
| 15 | `deque` from start for `ml_log_lines` | 🟡 | 15 min |
| 16 | Normalize `plotly_chart` width API | 🟡 | 20 min |
| 17 | `_last_trading_date` cache robustness | ⚪ | 10 min |

---

## Appendix: Detection Commands

```bash
# Find load_config() without lru_cache
grep -rn "load_config()" src/ --include="*.py" | grep -v "def load_config\|import\|\.cache"

# Find individual DB queries inside loops
grep -n "session.execute\|session.query" src/ingestion/pipeline.py

# Session open/close balance check
echo "get_session: $(grep -c 'get_session()' src/repository.py)"
echo "close:       $(grep -c '\.close()' src/repository.py)"

# Streamlit cache usage audit
grep -rn "@st.cache" src/ui/ --include="*.py"

# Global mutable state patterns
grep -rn "^_progress_\|^_[a-z]* = \[\]\|^_[a-z]* = {}" src/ingestion/ --include="*.py"
```
