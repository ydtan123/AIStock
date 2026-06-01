# AIStock Performance Audit v5

**Date:** 2026-05-30  
**Scope:** Full codebase — verified against live working tree  
**Methodology:** Source inspection across `src/`, `src/pipeline/`, `src/ingestion/`  

---

## Severity Summary

| Tier | Count | Issues |
|------|-------|--------|
| 🔴 CRITICAL | 4 | N+1 session.add() loops, missing Streamlit caching, sequential LLM calls |
| 🟠 HIGH | 5 | Per-call session open (news_cache), redundant env mutation, iterrows antipatterns, ORM bloated UPDATE, double _count_by_opinion |
| 🟡 MEDIUM | 4 | Config cache staleness, thread-pool vs DB pool mismatch, module-level side effects, fetch_and_store_prices dict-building |
| 🟢 LOW | 2 | create_engine defaults, datetime.utcnow() deprecation |

---

## 🔴 CRITICAL

### 1. N+1 `session.add()` in `save_selected_stocks()` + `save_predict_only_results()`

**File:** `src/repository.py:220-236`, `src/repository.py:246-261`

Each `session.add()` dirties ORM identity map, flushed individually at `commit()`. 50 records = 50 INSERT statements.

```python
# CURRENT (repository.py:220)
for rec in records:
    row = SelectedStock(ticker=rec["ticker"], ...)
    s.add(row)       # ← 1 INSERT per iteration
    inserted += 1
s.commit()
```

**Fix — `add_all()`:**

```python
def save_selected_stocks(self, records: list[dict], pipeline_run_id: int | None = None) -> int:
    def _query(s):
        if pipeline_run_id is not None:
            s.query(SelectedStock).filter_by(pipeline_run_id=pipeline_run_id).delete()
        else:
            s.query(SelectedStock).delete()
        run_at = datetime.now()
        rows = [
            SelectedStock(
                ticker=rec["ticker"], model_name=rec.get("model_name", ""),
                ml_score=float(rec.get("ml_score", 0)), bucket=rec.get("bucket"),
                weight=float(rec["weight"]) if rec.get("weight") is not None else None,
                date_selected=rec.get("date_selected", date.today()),
                model_file=rec.get("model_file"), pipeline_run_at=run_at,
                predicted_return=float(rec.get("ml_score", 0)),
                predicted_at=run_at, pipeline_run_id=pipeline_run_id,
            )
            for rec in records
        ]
        s.add_all(rows)   # ← single flush
        s.commit()
        return len(rows)
    return self._with_session(_query)
```

**Expected:** 50 INSERTs → 1 batch. ~50x faster. Same pattern applies to `save_predict_only_results()`.

---

### 2. N+1 `session.add()` in `FastEvaluationStep`

**File:** `src/pipeline/fast_evaluation.py:82-112`

Nested loop: 10 tickers × 5 analysts = 60 `session.add()` calls.

```python
# CURRENT (fast_evaluation.py:82-112)
for ev in evaluations:                       # 10 tickers
    session.add(FastEvaluationConclusion(...))  # 10 adds
    for op in ev.opinions:                   # 5 analysts each
        session.add(FastEvaluationAnalyst(...)) # 50 adds
session.commit()
```

**Fix — collect into lists, `add_all()`:**

```python
conclusions = []
analysts = []
now = dt.datetime.utcnow()
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)
    conclusions.append(FastEvaluationConclusion(
        pipeline_run_id=ctx.run_id, ticker=ev.ticker, backend=backend_name,
        start_date=dt.date.fromisoformat(ev.start_date),
        end_date=dt.date.fromisoformat(ev.end_date), evaluation_date=now,
        positive_count=pos, negative_count=neg, neutral_count=neu,
        total_count=pos + neg + neu, consensus_score=ev.consensus_score,
        model_name=evaluator_cfg.get("model_name", ""),
        model_provider=evaluator_cfg.get("model_provider", ""),
    ))
    for op in ev.opinions:
        analysts.append(FastEvaluationAnalyst(
            pipeline_run_id=ctx.run_id, ticker=ev.ticker, backend=backend_name,
            analyst_name=op.analyst_name, opinion=op.opinion,
            confidence=op.confidence, reasoning=op.reasoning,
            start_date=dt.date.fromisoformat(ev.start_date),
            end_date=dt.date.fromisoformat(ev.end_date), evaluation_date=now,
        ))

session.add_all(conclusions)
session.add_all(analysts)
session.commit()
```

**Expected:** 60 INSERTs → 1 bulk. ~60x faster.

---

### 3. Missing `@st.cache_data` — Dashboard Re-Runs Every Query

**File:** `src/app.py` (all page functions)  
**Impact:** Zero caching decorators. Every Streamlit rerun (widget click) hits DB. App ~2200 lines; all data display functions re-execute on every interaction.

**Functions needing `@st.cache_data(ttl=...)`:**

| Function | TTL | Rationale |
|----------|-----|-----------|
| `repo.count_summary()` | 300s | Rarely changes |
| `repo.get_sectors()` | 600s | Static-ish |
| `repo.get_job_runs(100)` | 300s | New runs infrequent |
| `repo.get_latest_selected_stocks()` | 300s | Changes per pipeline run |
| `repo.screen_stocks(criteria)` | 120s | Param-dependent |

**Fix — wrapper module `src/ui/cache.py`:**

```python
"""Streamlit cache wrappers for repository queries."""
import streamlit as st
from repository import StockRepository, ScreenCriteria

@st.cache_data(ttl=300)
def cached_count_summary() -> dict:
    return StockRepository().count_summary()

@st.cache_data(ttl=600)
def cached_sectors(table: str = "stock_snapshots") -> list[str]:
    return StockRepository().get_sectors(table)

@st.cache_data(ttl=300)
def cached_job_runs(limit: int = 100):
    return StockRepository().get_job_runs(limit)

@st.cache_data(ttl=300)
def cached_latest_selected_stocks() -> list[dict]:
    return StockRepository().get_latest_selected_stocks()

def invalidate_all() -> None:
    """Call after pipeline runs to bust caches."""
    for fn in [cached_count_summary, cached_sectors,
                cached_job_runs, cached_latest_selected_stocks]:
        fn.clear()
```

**Expected:** Near-instant rerenders for cached queries.

---

### 4. Sequential LLM Calls in `TradingAgentsDeepEvaluator`

**File:** `src/pipeline/backends/deep_evaluators.py:148`

Each `graph.propagate(ticker, date)` makes 8+ LLM API calls, all sequential. 3 tickers = 24+ sequential API calls = 3-6 min wall-clock.

```python
# CURRENT (deep_evaluators.py:148)
for ticker in tickers:
    result = graph.propagate(ticker, eval_date)   # blocks
```

**Fix — ThreadPoolExecutor for I/O-bound parallelism:**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def evaluate(self, tickers: list[str], ctx: StepContext) -> list[DeepEvaluation]:
    # ... setup (api keys, graph config, analysts) ...

    out: list[DeepEvaluation] = []
    with ThreadPoolExecutor(max_workers=min(len(tickers), 3)) as pool:
        futures = {
            pool.submit(self._evaluate_one, t, eval_date, graph, ctx): t
            for t in tickers
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result = future.result(timeout=600)
                if result:
                    out.append(result)
            except Exception as e:
                ctx.logger.exception("Failed %s: %s", ticker, e)
    return out

def _evaluate_one(self, ticker, eval_date, graph, ctx):
    ctx.logger.info("TradingAgents evaluating %s on %s", ticker, eval_date)
    return parse_result(graph.propagate(ticker, eval_date))
```

**⚠️ Caution:** Verify TradingAgents internals are thread-safe. If not, use `ProcessPoolExecutor`.

**Expected:** 3 tickers eval in parallel → wall-clock ≈ longest single ticker (1-2 min vs 3-6).

---

## 🟠 HIGH

### 5. Per-Call Session Open in `news_cache.py`

**File:** `src/news_cache.py:44-93`

Every `get_cached()` and `set_cached()` opens a fresh SQLAlchemy session. Deep eval: 3 tickers × 4 tools = 24 session open/close cycles. With parallelization (fix #4), DB pool exhaustion risk.

```python
# CURRENT — per-call session
def get_cached(tool_name, args, kwargs):
    session = _get_session()   # ← new session every call
    try:
        row = session.query(StockNews).filter_by(...).first()
    finally:
        session.close()
```

**Fix — thread-local session reuse:**

```python
import threading

_local = threading.local()

def _get_thread_session():
    if not hasattr(_local, 'session') or _local.session is None:
        from database import get_session
        _local.session = get_session()
    return _local.session

def get_cached(tool_name, args, kwargs):
    if tool_name not in _CACHEABLE:
        return None
    try:
        from models import StockNews
        session = _get_thread_session()
        row = session.query(StockNews).filter_by(
            tool_name=tool_name, ticker=ticker, start_date=start_date,
            end_date=end_date
        ).first()
        if row:
            return row.result
    except Exception as exc:
        logger.warning("[CACHE] read error: %s", exc)
    return None

def release_thread_session():
    if hasattr(_local, 'session') and _local.session is not None:
        _local.session.close()
        _local.session = None
```

**Expected:** 24 sessions → 1 per thread.

---

### 6. Redundant `os.environ` Mutation

**Files:** `fast_evaluators.py:72-89`, `deep_evaluators.py:54-70`, `ingestion/pipeline.py:28-36`

API keys injected into global `os.environ` at module level AND per evaluation call. Visible to all subprocesses — API key leak in tracebacks.

**Fix — context manager (see `src/config.py`):**

```python
from contextlib import contextmanager
import os

_API_KEY_ENV_MAP = [
    ("DEEPSEEK_API_KEY", "deepseek_api_key"),
    ("OPENAI_API_KEY", "openai_api_key"),
    ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    ("GOOGLE_API_KEY", "google_api_key"),
    ("GROQ_API_KEY", "groq_api_key"),
    ("ALPHA_VANTAGE_API_KEY", "alpha_vantage_api_key"),
]

@contextmanager
def api_keys_from_config(cfg):
    """Temporarily set API keys from config. Restores original on exit."""
    common = cfg.get("common", {})
    av = (common.get("alpha_vantage_api_key")
          or cfg.get("data_update", {}).get("alpha_vantage", {}).get("api_key")
          or cfg.get("alpha_vantage", {}).get("api_key"))
    saved, injected = {}, []
    for env_key, cfg_key in _API_KEY_ENV_MAP:
        val = av if env_key == "ALPHA_VANTAGE_API_KEY" else common.get(cfg_key)
        saved[env_key] = os.environ.get(env_key)
        if val and env_key not in os.environ:
            os.environ[env_key] = val
            injected.append(env_key)
    try:
        yield
    finally:
        for k in injected:
            if saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]
```

---

### 7. `iterrows()` Antipattern in `refresh_symbols()`

**File:** `src/ingestion/symbols.py:35`

`df.iterrows()` for ~8,000 stock symbols. Creates Series per row. 10-100x slower than vectorized.

**Fix — batch insert:**

```python
def refresh_symbols(fetcher):
    df = fetcher.get_listing()
    session = get_session()
    try:
        count = 0
        batch_size = 500
        records = df.to_dict('records')
        for i in range(0, len(records), batch_size):
            for rec in records[i:i + batch_size]:
                stmt = insert(Stock).values(
                    symbol=rec["symbol"], name=_clean(rec.get("name")),
                    asset_type=_clean(rec.get("asset_type")),
                    exchange=_clean(rec.get("exchange")), is_active=False,
                ).on_duplicate_key_update(
                    name=_clean(rec.get("name")),
                    asset_type=_clean(rec.get("asset_type")),
                    exchange=_clean(rec.get("exchange")),
                )
                session.execute(stmt)
            session.commit()
            count += batch_size
    finally:
        session.close()
    return count
```

**Expected:** 8,000 individual commits → ~16 batch commits. ~100x faster.

---

### 8. `_auto_activate()` ORM Bloat

**File:** `src/ingestion/pipeline.py:506-522`

ORM tracks attribute changes per object → N individual UPDATEs at commit.

```python
# CURRENT — N UPDATEs
for s in stocks:
    s.is_active = True       # dirties object
    s.activated_at = now
session.commit()             # N UPDATE statements
```

**Fix — bulk UPDATE:**

```python
def _auto_activate(criteria):
    session = get_session()
    try:
        # ... query to get stock_ids ...
        if stock_ids:
            now = datetime.utcnow()
            session.execute(
                text("UPDATE stocks SET is_active=:a, activated_at=:t WHERE id IN :ids"),
                {"a": True, "t": now, "ids": tuple(stock_ids)},
            )
            session.commit()
    finally:
        session.close()
```

**Expected:** N UPDATEs → 1 UPDATE. ~200x faster.

---

### 9. Redundant `_count_by_opinion()` in `FastEvaluationStep`

**File:** `src/pipeline/fast_evaluation.py:83, 119`

Same opinions counted twice: once for DB insert, once for report ranking.

**Fix — store counts on evaluation instance:**

```python
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)
    # Store for reuse
    ev._pos, ev._neg, ev._neu = pos, neg, neu
    # ... build conclusions ...

# Later (line 119):
for ev in evaluations_sorted:
    ranked.append({
        "ticker": ev.ticker,
        "positive": ev._pos, "negative": ev._neg, "neutral": ev._neu,
        "consensus_score": ev.consensus_score,
    })
```

---

## 🟡 MEDIUM

### 10. Config Cache Staleness

**File:** `src/config.py:11-24`  
Never re-reads `config.yaml` after first load. Requires Streamlit restart to pick up changes.

**Fix:** Store mtime alongside cached config. Re-read on change.

### 11. DB Pool Size vs Thread Workers

**File:** `src/database.py:24`  
`pool_size=8, max_overflow=4` with `MAX_WORKERS=5` ingestion threads + potential parallel deep eval. Risk of pool exhaustion.

**Fix:** `pool_size=16, max_overflow=8, pool_timeout=30`.

### 12. Module-Level Side Effects

**File:** `src/ingestion/pipeline.py:27-41`  
`load_config()`, `os.environ` mutation, `news_cache.install()` at import time. Tests cannot isolate.

**Fix:** Lazy `_ensure_initialized()` gate called at `run_daily_pipeline()` / `run_bootstrap()` entry.

### 13. `iterrows()` to Build Dict List in `_fetch_and_store_prices()`

**File:** `src/ingestion/pipeline.py:126-138`  
`df.assign(stock_id=stock.id).to_dict('records')` is 3-5x faster than `iterrows()` + list append.

Also: retry backoff uses `random.uniform()` jitter. Switch to exponential backoff: `time.sleep(2**attempt * 0.1)`.

---

## 🟢 LOW

### 14. `create_engine` Defaults + `datetime.utcnow()` Deprecation

- Add `pool_timeout=30`, `echo_pool="debug"` (env-gated)
- Replace all `datetime.utcnow()` → `datetime.now(datetime.UTC)` (~15 occurrences)

---

## Quick Wins (1-2 Line Changes)

| # | File | Line | Change |
|---|------|------|--------|
| Q1 | `repository.py:235` | `s.add(row)` in loop | `s.add_all(rows)` |
| Q2 | `repository.py:259` | Same pattern | `s.add_all(rows)` |
| Q3 | `fast_evaluation.py:85,101` | Nested adds | `session.add_all()` |
| Q4 | `deep_evaluation.py:89` | Per-row add | `session.add_all(rows)` |
| Q5 | `ingestion/pipeline.py:516` | ORM attr loop | `session.execute(text(...))` |
| Q6 | `ingestion/symbols.py:35` | `iterrows()` | `to_dict('records')` |
| Q7 | `fast_evaluation.py:83,119` | Double count | Store on instance |

---

## React/JS Note

This is a **Python/Streamlit** codebase — no React. The equivalent Streamlit concern is `@st.cache_data` (Issue #3). SQLAlchemy session management (Issue #5) is the equivalent of browser memory leak concern.

## Already Well-Designed

1. **`_prefetch_stock_dates()`** (pipeline.py:44): 4 batch queries replace 4N. Excellent.
2. **`_with_session()`** (repository.py:43): Consistent try/finally lifecycle.
3. **`_batch_update_checkpoints()`** (pipeline.py:303): Single bulk UPDATE.
4. **`news_cache.install()`**: DB-backed LLM call cache. Eliminates duplicate API costs.
5. **`_ensure_table()`**: `checkfirst=True` avoids migration errors.
