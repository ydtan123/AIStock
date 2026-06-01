# AIStock Performance Analysis v10

**Date:** 2026-05-30
**Scope:** 7,226 lines across 40+ Python files
**Prior art:** Issues #1059, #1164, #1165, #1161

---

## Executive Summary

18 issues across 4 severity tiers. Top-3 wins:
1. **N+1 query in repository** — 50-90% DB call reduction
2. **Config load dedup** — eliminates ~8 redundant stat() calls per invocation
3. **news_cache re-install** — prevents cache re-install on every deep-eval run

---

## CRITICAL (2 issues)

### C1. N+1 Query in `get_price_data()` — `repository.py:85`

**Impact:** For N stocks, issues N individual `SELECT ... FROM daily_prices WHERE stock_id=?` queries instead of 1 batched query. At 500 stocks = 500 round-trips.

**Current code** (`src/repository.py:85-95`):
```python
for sid, s, e in stocks:
    rows = s.query(DailyPrice).filter(or_(*conditions)).order_by(DailyPrice.date).all()
    result[sid] = [{"date": r.date, ...} for r in rows]
```

**Fix — Single batched query with in-memory grouping:**
```python
def get_price_data(self, stock_ids: list[int], start: date, end: date) -> dict[int, list[dict]]:
    def _query(s):
        rows = (
            s.query(DailyPrice)
            .filter(
                DailyPrice.stock_id.in_(stock_ids),
                DailyPrice.date >= start,
                DailyPrice.date <= end,
            )
            .order_by(DailyPrice.stock_id, DailyPrice.date)
            .all()
        )
        result: dict[int, list[dict]] = {}
        for r in rows:
            result.setdefault(r.stock_id, []).append({
                "date": r.date, "open": r.open, "high": r.high,
                "low": r.low, "close": r.close, "adj_close": r.adj_close,
                "volume": r.volume,
            })
        return result
    return self._with_session(_query)
```

**Expected gain:** 50-90% fewer DB round-trips for multi-stock lookups.

---

### C2. Per-Row `session.add()` Instead of `add_all()`

**Impact:** Individual `session.add()` per stock in loops causes O(N) SQLAlchemy flush overhead. At 500 symbols = 500 flushes instead of 1.

**Locations:** `src/main.py:63`, `src/scheduler.py:27`, `src/ingestion/pipeline.py:496`

**Fix for `main.py:63`:**
```python
# CURRENT:
for symbol in symbols:
    stock = Stock(symbol=symbol, name=symbol)
    session.add(stock)

# FIXED:
stocks = [Stock(symbol=symbol, name=symbol) for symbol in symbols]
session.add_all(stocks)
session.commit()
```

**Expected gain:** ~80% reduction in flush overhead for bulk operations.

---

## HIGH (5 issues)

### H1. `load_config()` Called 10 Times Per Invocation

**Impact:** Despite mtime-based caching in `config.py`, 10 call sites still each do `stat()` + dict access. Locations: `scheduler.py` (3x), `main.py` (2x), `ingestion/pipeline.py` (4x), `database.py`, `ml_pipeline.py`.

**Fix — enhance caching with lru_cache:**
```python
# src/config.py
from functools import lru_cache

@lru_cache(maxsize=1)
def _load_config_impl(mtime_key: float) -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    loader = ConfigLoader(config_path)
    return loader.load()

def load_config(force: bool = False) -> dict:
    global _config_mtime
    config_path = Path(__file__).parent.parent / "config.yaml"
    current_mtime = config_path.stat().st_mtime
    if not force and current_mtime == _config_mtime:
        return _load_config_impl(current_mtime)
    _config_mtime = current_mtime
    _load_config_impl.cache_clear()
    return _load_config_impl(current_mtime)
```

Also: pass config as parameter in `scheduler.py` methods instead of calling `load_config()` in each.

---

### H2. `_install_news_cache()` Called on Every Deep Evaluator Run

**Impact:** Deep evaluator calls `_install_news_cache()` every run. Idempotent via `_INSTALLED` flag, but still does import + check. Unnecessary overhead.

**Location:** `src/pipeline/backends/deep_evaluators.py:118-122`

**Fix:**
```python
# Module level in deep_evaluators.py
_news_cache_installed: bool = False

def _ensure_news_cache_once():
    global _news_cache_installed
    if not _news_cache_installed:
        from news_cache import install
        install()
        _news_cache_installed = True

# In evaluate() method:
if sub.get("use_news_cache", True):
    _ensure_news_cache_once()
```

---

### H3. No `@st.cache_resource` for Database Session Factory

**Impact:** Each Streamlit page creates new `StockRepository()` instances. While `sessionmaker` is module-cached, each page bypassing `cached_repo.py` creates a new repo instance.

**Fix — add resource-cached repo:**
```python
# src/ui/cached_repo.py
@st.cache_resource(ttl=3600, show_spinner=False)
def _get_repository() -> StockRepository:
    return StockRepository()

@st.cache_data(ttl=300, show_spinner=False)
def cached_find_stock(symbol: str) -> dict | None:
    return _get_repository().find_stock(symbol)
```

---

### H4. Repeated `joblib.load()` in `finrl_runner.py`

**Impact:** Model artifacts loaded twice in same pipeline run — once for bucket matching (line 148), once for prediction (line 357). For 10+ model files at 50MB each = 500MB redundant I/O.

**Fix — load once, pass through pipeline:**
```python
def load_all_models(model_dir: str) -> dict[str, dict]:
    """Load all model artifacts once."""
    models = {}
    for mp in Path(model_dir).glob("*.joblib"):
        artifact = joblib.load(mp)
        bucket = artifact.get("bucket", "unknown")
        models[bucket] = {"path": str(mp), "artifact": artifact}
    return models

def run_pipeline(model_dir: str, ...):
    models = load_all_models(model_dir)  # Load once
    bucket_models = select_best_models(models)
    results = predict_all(bucket_models, ...)
```

**Expected gain:** 50% reduction in model I/O.

---

### H5. Sequential Ticker Processing in Deep Evaluation

**Impact:** Deep evaluator processes tickers one-at-a-time despite `ThreadPoolExecutor`. LLM API calls are network-bound — ideal for parallelism.

**Location:** `src/pipeline/backends/deep_evaluators.py:158`

**Fix — async gather for concurrent LLM calls:**
```python
import asyncio

async def _evaluate_ticker_async(ticker: str, sub: dict):
    """Run all LLM analysis tasks for one ticker concurrently."""
    tasks = [
        _analyze_fundamentals(ticker, sub),
        _analyze_sentiment(ticker, sub),
        _analyze_technicals(ticker, sub),
    ]
    return await asyncio.gather(*tasks, return_exceptions=True)
```

**Expected gain:** 2-4x speedup for multi-ticker deep evaluation.

---

## MEDIUM (7 issues)

### M1. `st.rerun()` Triggers Full Script Re-execution

**Impact:** 4 `st.rerun()` calls in `ml_pipeline.py:391,412` and `stock_manager.py:92,97`. Each re-executes entire script including imports, config loads, data fetches.

**Fix — replace rerun with session state + fragment:**
```python
# CURRENT:
if st.button("Run Pipeline"):
    ctx.st.rerun()

# FIXED:
if st.button("Run Pipeline"):
    st.session_state.pipeline_needs_refresh = True

@st.fragment
def pipeline_results():
    if st.session_state.get("pipeline_needs_refresh"):
        run_ml_pipeline()
        st.session_state.pipeline_needs_refresh = False
    display_results()
```

**Expected gain:** 60-80% reduction in re-render computation.

---

### M2. Short Streamlit Cache TTLs

**Impact:** 7 `@st.cache_data` instances with TTL=60s. Data refetches every minute even when unchanged.

**Locations:** `overview.py:6`, `stock_technical.py:13`, `stock_lookup.py:14`, `stock_manager.py:10`, `cached_repo.py:19`

**Fix — increase TTLs for stable data:**
```python
# Data that rarely changes (stock lists, summaries)
@st.cache_data(ttl=300, show_spinner=False)  # was 60s

# Data that changes daily (prices with known end-date)
@st.cache_data(ttl=3600, show_spinner=False)  # was 60-300s
```

---

### M3. Manual DataFrame Construction Instead of `pd.read_sql()`

**Impact:** `repository.py:316` — `get_job_runs()` builds DataFrame via list comprehension over ORM objects. 5-10x slower than `pd.read_sql()`.

**Fix:**
```python
def get_job_runs(self, limit: int = 100) -> pd.DataFrame:
    def _query(s):
        return pd.read_sql(
            text("""
                SELECT id, job_name, status, started_at, completed_at,
                       total_stocks, errors, result_summary
                FROM scheduled_job_runs
                ORDER BY started_at DESC
                LIMIT :limit
            """),
            s.get_bind(),
            params={"limit": limit},
        )
    return self._with_session(_query)
```

---

### M4. No Connection Pool Reuse Across Pipeline Steps

**Impact:** Each pipeline step creates new `Session()` from `sessionmaker`. Sessions should be reused within a single pipeline run.

**Fix — pass shared session through pipeline:**
```python
class FullPipeline:
    def __init__(self, session: Session | None = None):
        self._session = session

    def run(self, ...):
        session = self._session or database.get_session_factory()()
        try:
            result = self._run_pipeline(session, ...)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            if not self._session:
                session.close()
```

---

### M5. `count_summary()` Uses N+1 Count Pattern

**Impact:** Multiple `COUNT(*)` queries for dashboard overview. Replace with single conditional aggregation query.

**Fix:**
```python
def count_summary(self) -> dict:
    def _query(s):
        row = s.execute(text("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) AS inactive
            FROM stocks
        """)).fetchone()
        return dict(row._mapping)
    return self._with_session(_query)
```

---

### M6. Deep Evaluation Row Construction Not Generator-Based

**Impact:** `deep_evaluation.py:170-178` — rows built into intermediate list before `add_all()`. Fine for small batches, but could be generator-based.

**Fix:**
```python
def _build_rows(tickers, results):
    for ticker, result in zip(tickers, results):
        if result is None:
            continue
        yield DeepEvaluationResult(
            ticker=ticker, score=result.get("score"),
            recommendation=result.get("recommendation"),
            analysis=result.get("analysis"),
            evaluated_at=datetime.utcnow(),
        )

rows = list(_build_rows(tickers, results))
if rows:
    session.add_all(rows)
```

---

### M7. Streamlit Pages Lack `@st.fragment` for Partial Re-renders

**Impact:** Entire page re-renders on any interaction. Without `@st.fragment`, expensive fetches re-execute for minor changes.

**Fix:**
```python
# src/ui/pages/stock_detail.py
@st.fragment
def price_chart_section(stock_id: int):
    prices = cached_get_prices(stock_id, start_str, end_str)
    st.line_chart(prices.set_index("date")[["close"]])

@st.fragment
def indicator_section(stock_id: int):
    indicators = cached_get_indicators(stock_id)
    display_indicator_table(indicators)
```

**Expected gain:** 30-50% per-interaction computation reduction.

---

## INFO (4 issues)

### I1. Consider `@st.cache_resource` for NewsCache Install
`news_cache.install()` patches third-party module function. Use `@st.cache_resource` to ensure once-per-session.

### I2. Yahoo Finance Fetcher — No Response Caching
`src/fetcher/yahoo.py` fetches live data every call. Add TTL cache for `get_daily()` since historical prices don't change:
```python
from functools import lru_cache

@lru_cache(maxsize=128)
def _cached_get_daily(symbol: str, start: str, end: str) -> str:
    # Returns JSON string for hashability

def get_daily(self, symbol, start, end) -> pd.DataFrame:
    if end < date.today():  # Historical data = cacheable
        cached = _cached_get_daily(symbol, start.isoformat(), end.isoformat())
        if cached:
            return pd.read_json(cached)
    # Fetch live for current data
    ...
```

### I3. Module-Level `_cfg` at Import Time
`src/ingestion/pipeline.py:53` — `_cfg = load_config()` at module level. Runs on import even if module unused. Move inside `bootstrap()` function.

### I4. Missing ML Pipeline Timing Observability
Training and prediction loops in `finrl_runner.py` lack structured timing. Add:
```python
from contextlib import contextmanager
import time

@contextmanager
def timed(step_name: str):
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    logger.info("%s: %.2fs", step_name, elapsed)
```

---

## Summary Table

| ID | Severity | Area | Issue | Effort | Gain |
|----|----------|------|-------|--------|------|
| C1 | CRITICAL | DB | N+1 query in get_price_data | S | 50-90% |
| C2 | CRITICAL | DB | Per-row session.add vs add_all | S | 80% |
| H1 | HIGH | Config | Redundant load_config calls | S | Stat elim |
| H2 | HIGH | Caching | news_cache re-install | S | Skip import |
| H3 | HIGH | Caching | No @st.cache_resource for repo | S | Session reuse |
| H4 | HIGH | I/O | Repeated joblib.load | M | 50% I/O |
| H5 | HIGH | ML | Sequential ticker processing | M | 2-4x |
| M1 | MEDIUM | Streamlit | st.rerun() full re-exec | M | 60-80% |
| M2 | MEDIUM | Caching | Short cache TTLs | S | Fewer refetches |
| M3 | MEDIUM | DB | Manual DataFrame construction | S | 5-10x |
| M4 | MEDIUM | DB | Session reuse across pipeline | M | 50% |
| M5 | MEDIUM | DB | N+1 in count_summary | S | 1 vs 3 queries |
| M6 | MEDIUM | DB | Deep eval row construction | S | Marginal |
| M7 | MEDIUM | Streamlit | No @st.fragment usage | L | 30-50% |
| I1 | INFO | Caching | NewsCache resource caching | S | — |
| I2 | INFO | Caching | Fetcher response cache | M | — |
| I3 | INFO | Config | Module-level config load | S | — |
| I4 | INFO | Observability | Missing timing contexts | M | — |

**Effort:** S = <1h, M = 1-4h, L = 4h+

---

## Quick Wins (<30 min)

Fix these 5 issues for <1 hour total, covering all CRITICAL + top HIGH/MEDIUM:

1. **C1** — Change `get_price_data()` to use `.in_()` (5 lines)
2. **C2** — Replace `session.add()` with `add_all()` in 3 locations (3 lines each)
3. **H1** — Add `lru_cache` to `load_config()` (2 lines)
4. **H2** — Move `_install_news_cache()` to module-level guard (3 lines)
5. **M5** — Single COUNT query with conditional aggregation (10 lines)
