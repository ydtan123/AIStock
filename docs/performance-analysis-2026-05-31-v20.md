# AIStock Performance Analysis — v20

**Date:** 2026-05-31  
**Codebase:** `/Users/yudongtan/projects/AIStock/external/ai-hedge-fund`  
**Stack:** FastAPI + SQLAlchemy (SQLite) + LangGraph + LLM agents  
**Note:** No React/Streamlit rendering found. This is a FastAPI backend — frontend rendering analysis not applicable.

---

## Summary

| Severity | Count | Category |
|----------|-------|----------|
| CRITICAL | 4 | N+1 data fetches, cache disconnected, redundant DB queries |
| HIGH | 3 | Progress handler memory leak, unbounded cache growth, SQLite contention |
| MEDIUM | 3 | Individual bulk ops, deprecated UTC, repeated DataFrame conversions |
| LOW | 1 | No HTTP caching headers |

---

## CRITICAL-1: Mass N+1 Data Fetch — Every Analyst Fetches Per Ticker

**Impact:** With 10 analysts x N tickers, the same financial data is fetched 10 x N times from external APIs. For 5 tickers: 50+ redundant API calls per run cycle.

**File:** `src/agents/warren_buffett.py`, `src/agents/bill_ackman.py`, and ALL other analyst agents

**Pattern found in every analyst agent:**
```python
# warren_buffett.py:24-85 — Same pattern in bill_ackman, cathie_wood, etc.
for ticker in tickers:
    metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=10, api_key=api_key)
    financial_line_items = search_line_items(ticker, [...], end_date, period="ttm", limit=10, api_key=api_key)
    market_cap = get_market_cap(ticker, end_date, api_key=api_key)
```

**Why this is N+1:** Each of the 10+ analyst agents runs this identical loop independently. No data sharing between agents. Each agent calls the same `get_financial_metrics("AAPL", ...)` and `get_prices("AAPL", ...)` for every ticker.

**Fix — Prefetch data once, share across agents:**

```python
# New module: src/data/prefetcher.py
from src.data.cache import get_cache
from src.tools.api import get_prices, get_financial_metrics, search_line_items, get_market_cap

def prefetch_all_ticker_data(tickers: list[str], start_date: str, end_date: str, api_key: str | None) -> dict:
    """Fetch all ticker data ONCE before any analyst runs. Cache it."""
    cache = get_cache()
    result = {}
    for ticker in tickers:
        if cache.get_prices(ticker) is None:
            cache.set_prices(ticker, get_prices(ticker, start_date, end_date, api_key))
        if cache.get_financial_metrics(ticker) is None:
            cache.set_financial_metrics(ticker, get_financial_metrics(ticker, end_date, period="ttm", limit=10, api_key=api_key))
        result[ticker] = {
            "prices": cache.get_prices(ticker),
            "metrics": cache.get_financial_metrics(ticker),
        }
    return result

# In run_hedge_fund() — call BEFORE creating workflow:
prefetch_all_ticker_data(tickers, start_date, end_date, api_key)

# In each analyst agent — check cache first:
def warren_buffett_agent(state: AgentState, agent_id: str = "warren_buffett_agent"):
    cache = get_cache()
    for ticker in tickers:
        metrics = cache.get_financial_metrics(ticker)  # Already prefetched
        if metrics is None:
            metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=10, api_key=api_key)
            cache.set_financial_metrics(ticker, metrics)
```

**Estimated savings:** ~90% reduction in API calls per run (10+ agents sharing 1 prefetch).

---

## CRITICAL-2: Cache Singleton Exists But Completely Unused

**Impact:** The `Cache` class in `src/data/cache.py` is fully implemented, well-tested (see `tests/test_cache.py`), but the production API tools in `src/tools/api.py` NEVER call it.

**File:** `src/tools/api.py:48-85`

```python
# Current code — bypasses cache entirely
def get_prices(ticker, start_date, end_date, api_key=None):
    return _get_provider(_cfg.PRICES_SOURCE).get_prices(ticker, start_date, end_date, api_key)

def get_financial_metrics(ticker, end_date, period="ttm", limit=10, api_key=None):
    return _get_provider(_cfg.FINANCIAL_METRICS_SOURCE).get_financial_metrics(...)
```

**Fix — Wire cache into API tools:**

```python
# src/tools/api.py
from src.data.cache import get_cache

def get_prices(ticker: str, start_date: str, end_date: str, api_key: str | None = None) -> list[Price]:
    cache = get_cache()
    cached = cache.get_prices(ticker)
    if cached is not None:
        return cached
    data = _get_provider(_cfg.PRICES_SOURCE).get_prices(ticker, start_date, end_date, api_key)
    cache.set_prices(ticker, data)
    return data

def get_financial_metrics(ticker: str, end_date: str, period: str = "ttm", limit: int = 10,
                          api_key: str | None = None) -> list[FinancialMetrics]:
    cache = get_cache()
    cached = cache.get_financial_metrics(ticker)
    if cached is not None:
        return cached
    data = _get_provider(_cfg.FINANCIAL_METRICS_SOURCE).get_financial_metrics(ticker, end_date, period, limit, api_key)
    cache.set_financial_metrics(ticker, data)
    return data

# Same pattern for: get_insider_trades, get_company_news, get_market_cap
```

---

## CRITICAL-3: Route Handlers — Unnecessary "Verify Flow Exists" Query

**Impact:** Every flow-runs endpoint does 2 sequential DB queries: one to verify the flow exists, then one for the actual data. The "verify" query is wasteful.

**File:** `app/backend/routes/flow_runs.py:38-54`

```python
async def get_flow_runs(flow_id: int, db: Session = Depends(get_db)):
    # Query 1: verify flow exists
    flow_repo = FlowRepository(db)
    flow = flow_repo.get_flow_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    # Query 2: get actual runs
    run_repo = FlowRunRepository(db)
    flow_runs = run_repo.get_flow_runs_by_flow_id(flow_id, limit=limit, offset=offset)
```

This pattern repeats in: `get_flow_run_count()`, `get_active_flow_run()`, `delete_all_flow_runs()`.

**Fix — Single EXISTS check:**

```python
from sqlalchemy import exists

async def get_flow_runs(flow_id: int, db: Session = Depends(get_db)):
    flow_exists = db.query(exists().where(HedgeFundFlow.id == flow_id)).scalar()
    if not flow_exists:
        raise HTTPException(status_code=404, detail="Flow not found")

    run_repo = FlowRunRepository(db)
    flow_runs = run_repo.get_flow_runs_by_flow_id(flow_id, limit=limit, offset=offset)
    return [FlowRunSummaryResponse.from_orm(run) for run in flow_runs]
```

---

## CRITICAL-4: `_get_next_run_number` — Extra Query Per New Run

**File:** `app/backend/repositories/flow_run_repository.py`

```python
def _get_next_run_number(self, flow_id: int) -> int:
    max_run = (
        self.db.query(func.max(HedgeFundFlowRun.run_number))
        .filter(HedgeFundFlowRun.flow_id == flow_id)
        .scalar()
    )
    return (max_run or 0) + 1
```

Extra COUNT/MAX query on every `create_flow_run()`. Combined with route-level "verify flow exists", creating a run costs 3 queries minimum.

**Fix — Use auto-increment ID instead:**

```python
def create_flow_run(self, flow_id: int, request_data=None) -> HedgeFundFlowRun:
    flow_run = HedgeFundFlowRun(
        flow_id=flow_id,
        status=FlowRunStatus.IDLE.value,
        request_data=json.dumps(request_data) if request_data else None,
    )
    self.db.add(flow_run)
    self.db.flush()
    flow_run.run_number = flow_run.id  # ID is always sequential
    self.db.commit()
    self.db.refresh(flow_run)
    return flow_run
```

---

## HIGH-1: Progress Handler Memory Leak in SSE Endpoints

**Impact:** Each `/run` or `/backtest` request registers a handler via `progress.register_handler(handler)` but NEVER unregisters it. The `update_handlers` list grows unbounded. After 1000 requests, every status update iterates 1000 stale handlers.

**File:** `app/backend/routes/hedge_fund.py` (both `/run` and `/backtest` endpoints)
**File:** `src/utils/progress.py:24-26`

```python
def register_handler(self, handler):
    self.update_handlers.append(handler)  # Appends forever, never pruned
```

**Fix — Always unregister in finally block:**

```python
# hedge_fund.py, inside event_generator()
progress.register_handler(progress_handler)
try:
    # ... task execution ...
finally:
    progress.unregister_handler(progress_handler)  # Cleanup MUST happen here
```

Better — context manager:

```python
# src/utils/progress.py
from contextlib import contextmanager

@contextmanager
def registered_handler(self, handler):
    self.register_handler(handler)
    try:
        yield
    finally:
        self.unregister_handler(handler)

# hedge_fund.py
with progress.registered_handler(progress_handler):
    # ... task ...
```

---

## HIGH-2: Cache Grows Unbounded — No TTL, No Eviction

**Impact:** `Cache` stores all data forever. In continuous trading mode, memory grows without bound.

**File:** `src/data/cache.py:6-14`

```python
class Cache:
    def __init__(self):
        self._prices_cache: dict[str, list[dict[str, any]]] = {}
        # no size limits, no TTL, no eviction
```

**Fix — TTL + LRU eviction:**

```python
import time

class Cache:
    MAX_ENTRIES = 100
    TTL = 3600  # 1 hour

    def __init__(self):
        self._prices_cache: dict[str, tuple[float, list[dict]]] = {}

    def _is_fresh(self, ticker: str, store: dict) -> bool:
        if ticker not in store:
            return False
        return (time.time() - store[ticker][0]) < self.TTL

    def get_prices(self, ticker: str) -> list[dict] | None:
        if not self._is_fresh(ticker, self._prices_cache):
            self._prices_cache.pop(ticker, None)
            return None
        return self._prices_cache[ticker][1]

    def set_prices(self, ticker: str, data: list[dict]):
        if len(self._prices_cache) >= self.MAX_ENTRIES:
            oldest = min(self._prices_cache, key=lambda k: self._prices_cache[k][0])
            del self._prices_cache[oldest]
        self._prices_cache[ticker] = (time.time(), data)
```

---

## HIGH-3: SQLite + Async FastAPI — Connection Contention

**Impact:** SQLite serializes writes. Multiple `async def` endpoints sharing SQLite connection bottleneck under load.

**File:** `app/backend/database/connection.py:15-19`

```python
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # No pool config, no WAL
)
```

**Fix — WAL mode + connection pool:**

```python
from sqlalchemy import event

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,
    pool_pre_ping=True,
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()
```

---

## MEDIUM-1: Bulk API Key Operations — Individual DB Queries

**File:** `app/backend/routes/api_keys.py` (bulk endpoint)

Each key creates a separate `SELECT + INSERT/UPDATE + COMMIT`.

**Fix — Single SELECT + single COMMIT:**

```python
def bulk_create_or_update(self, api_keys_data: list[dict]) -> list[ApiKey]:
    providers = [d['provider'] for d in api_keys_data]
    existing = {
        k.provider: k
        for k in self.db.query(ApiKey).filter(ApiKey.provider.in_(providers)).all()
    }
    results = []
    for data in api_keys_data:
        if data['provider'] in existing:
            key = existing[data['provider']]
            key.key_value = data['key_value']
        else:
            key = ApiKey(**data)
            self.db.add(key)
        results.append(key)
    self.db.commit()  # Single COMMIT
    return results
```

---

## MEDIUM-2: `datetime.utcnow()` Deprecated

**File:** `app/backend/repositories/flow_run_repository.py`

```python
flow_run.started_at = datetime.utcnow()  # Deprecated in Python 3.12+
```

**Fix:**

```python
from datetime import datetime, timezone
flow_run.started_at = datetime.now(timezone.utc)
```

---

## MEDIUM-3: `prices_to_df()` Repeated on Same Data

**File:** `src/tools/api.py:85-88`

Every agent calling `get_price_data()` reconverts raw prices to DataFrame even if already converted.

**Fix — Cache the DataFrame:**

```python
# cache.py
def get_price_df(self, ticker: str) -> pd.DataFrame | None:
    return self._price_df_cache.get(ticker)

def set_price_df(self, ticker: str, df: pd.DataFrame):
    self._price_df_cache[ticker] = df
```

---

## LOW-1: No HTTP Caching Headers

All API responses lack `Cache-Control` headers. Repeated browser requests hit database.

**Fix:**

```python
@router.get("/{flow_id}")
async def get_flow(flow_id: int, response: Response, db: Session = Depends(get_db)):
    flow = repo.get_flow_by_id(flow_id)
    response.headers["Cache-Control"] = "private, max-age=30"
    return FlowResponse.from_orm(flow)
```

---

## Priority Fix Order

| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 1 | Wire cache into `src/tools/api.py` (C-2) | 30 min | 90% fewer API calls |
| 2 | Prefetch data before agents (C-1) | 1 hr | Eliminates agent N+1 |
| 3 | Fix progress handler leak (H-1) | 15 min | Prevents OOM |
| 4 | Add cache TTL + eviction (H-2) | 30 min | Capped memory |
| 5 | Remove redundant flow-exists queries (C-3) | 30 min | 50% fewer DB queries |
| 6 | Batch bulk API key ops (M-1) | 20 min | Lower latency |
| 7 | SQLite WAL + pool config (H-3) | 15 min | Better concurrency |
| 8 | Fix deprecated utcnow() (M-2) | 5 min | Forward compat |
| 9 | Cache DataFrame conversions (M-3) | 15 min | Less CPU |
| 10 | HTTP cache headers (L-1) | 10 min | Better client perf |

**Total estimated effort:** ~3.5 hours for all fixes.

---

## What's NOT an Issue

- **No React re-renders:** FastAPI backend. No frontend rendering found.
- **No unnecessary DataFrame copies:** `_merge_data` in `cache.py` correctly copies only when building merged list.
- **No duplicate `_load_config()`:** Config centralized in `src/data/config.py`.
- **No `ThreadPoolExecutor` misuse:** Threading minimal and appropriate for blocking I/O in async.
