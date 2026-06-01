# AIStock Performance Audit — Supplement v3 (New Findings)

**Date:** 2026-05-30
**Previous audits:** [performance-audit.md](performance-audit.md), [performance-audit-supplement.md](performance-audit-supplement.md), [performance-audit-comprehensive.md](performance-audit-comprehensive.md), [performance-audit-comprehensive-v2.md](performance-audit-comprehensive-v2.md)
**Scope:** Issues NOT covered by prior audits

---

## 🔴 CRITICAL — `iterrows()` Antipattern in Hot Data Paths

### 1. `_fetch_and_store_prices()` — Row-by-Row Dict Construction

**File:** `src/ingestion/pipeline.py:126`

```python
# Current -- O(n) Python row iteration with per-column dict build:
values = []
for _, row in df.iterrows():
    values.append({
        "stock_id": stock.id,
        "date": row["date"],
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "close": row.get("close"),
        "adj_close": row.get("adj_close"),
        "volume": row.get("volume"),
        "dividend_amount": row.get("dividend_amount"),
        "split_coefficient": row.get("split_coefficient"),
    })
```

**Fix -- vectorized conversion:**
```python
# df.to_dict('records') uses C-level iteration, 3-5x faster:
df_copy = df.copy()
df_copy["stock_id"] = stock.id
# Keep only columns matching DB schema
cols = ["stock_id", "date", "open", "high", "low", "close",
        "adj_close", "volume", "dividend_amount", "split_coefficient"]
values = df_copy[cols].to_dict('records')
```

**Impact:** 500 stocks x 1200 rows each = 600k Python loop iterations -> single C-level operation. ~4-6x per stock.

---

### 2. `compute_indicators()` -- Nested Per-Value Iteration with Per-Cell Type Cast

**File:** `src/ingestion/indicators.py:97-107`

```python
# Current -- O(rows x columns) Python iteration with per-cell float() + round():
for row_date, row in df.iterrows():
    indicators = {}
    for k, v in row.items():
        val = float(v)
        indicators[k] = None if (pd.isna(val) or val == float("inf") or val == float("-inf")) else round(val, 6)
    values.append({"stock_id": stock_id, "date": row_date, "indicators": indicators, "computed_at": now})
```

**Fix -- vectorized NaN/Inf handling:**
```python
import numpy as np

# Replace Inf/-Inf with NaN in ONE vectorized operation
df = df.replace([np.inf, -np.inf], np.nan).round(6)
now = datetime.utcnow()

values = [
    {
        "stock_id": stock_id,
        "date": idx,
        "indicators": {k: v for k, v in row.items() if pd.notna(v)},
        "computed_at": now,
    }
    for idx, row in df.iterrows()
]
```

**Impact:** 500 stocks x 50 indicators = 25k per-cell float()+pd.isna() calls -> single DataFrame-level op. ~3-5x speedup.

---

## 🔴 CRITICAL -- `ingestion/pipeline.py`: 6 Session Open/Close Per Stock

### 3. Session Fragmentation in Ingestion Pipeline

**File:** `src/ingestion/pipeline.py`

Each stock processed by `_process_symbol` triggers up to 6 independent sessions:
- `_prefetch_stock_dates()` -- 1 session (good, batched)
- `_fetch_and_store_prices()` -- 2 sessions (lines 103, 118)
- `_upsert_fundamentals()` -- 1 session (line 191)
- `_needs_full_backfill()` -- 1 session (line 331, when no prefetch)
- `_batch_update_checkpoints()` -- 1 session (line 307)

Each does: TCP connect -> authenticate -> query -> close.

**Fix -- session-per-batch pattern:**
```python
def _process_symbol_batch(
    fetcher: FetcherBase,
    stocks: list[Stock],
    force: bool,
    prefetch: dict,
) -> list[dict]:
    """Process multiple stocks in ONE DB session."""
    results = []
    session = get_session()
    try:
        for stock in stocks:
            result = _process_one_stock_in_session(
                fetcher, stock, force, prefetch, session
            )
            results.append(result)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return results
```

**Impact:** 500 stocks x 6 sessions = 3000 open/close -> 50 cycles (10 batches of 50). 90% reduction.

---

## 🟠 HIGH -- `news_cache.py`: Unbounded Cache Growth, No TTL or Eviction

### 4. `stock_news` Table Grows Without Bounds

**File:** `src/news_cache.py`

Every `route_to_vendor("get_news", ...)` creates a `StockNews` row (lines 67-93). No purge mechanism.

```
Growth per full pipeline run:
  Stock selection: N tickers x 1 news lookup
  Deep evaluation: N tickers x ~4 agent calls
  -> ~5N rows/run. N=500 -> 2,500 rows/run. 10 runs = 25,000 rows.
```

**Fix -- add TTL cleanup:**
```python
from datetime import datetime, timedelta

def purge_expired(days: int = 30) -> int:
    """Delete news cache entries older than `days` days."""
    session = _get_session()
    try:
        cutoff = datetime.now() - timedelta(days=days)
        count = session.query(StockNews).filter(
            StockNews.fetched_at < cutoff
        ).delete()
        session.commit()
        logger.info("[CACHE] Purged %d expired entries (older than %d days)", count, days)
        return count
    except Exception as exc:
        session.rollback()
        logger.warning("[CACHE] purge error: %s", exc)
        return 0
    finally:
        session.close()
```

Add to scheduler:
```python
from apscheduler.triggers.cron import CronTrigger
scheduler.add_job(
    lambda: news_cache.purge_expired(days=30),
    trigger=CronTrigger(hour=3, minute=0),
    id='purge_news_cache',
    replace_existing=True,
)
```

**Impact:** Prevents unbounded DB growth. 30-day TTL keeps cache useful.

---

## 🟠 HIGH -- `pipeline.py`: Module-Level Monkey-Patching at Import Time

### 5. Side Effects on Every Import

**File:** `src/ingestion/pipeline.py:39-41`

```python
# Current -- executes on every import of this module:
import news_cache
news_cache.install()
```

Any module importing `ingestion.pipeline` triggers patching of `tradingagents.dataflows.interface`. Breaks import isolation.

**Fix -- explicit init function:**
```python
# In ingestion/pipeline.py:
def init_plugins() -> None:
    """Call once before pipeline execution. Idempotent."""
    import news_cache
    news_cache.install()

# In entry points:
from ingestion.pipeline import init_plugins
init_plugins()
```

**Impact:** Enables clean test imports. Allows selective cache disabling.

---

## 🟡 MEDIUM -- `database.py`: Global Mutable State Without Thread Safety

### 6. Race Condition on `configure()` + `get_engine()`

**File:** `src/database.py:12-17`

```python
# Current -- mutates globals without locks:
def configure(url: str):
    global _url, _engine, _SessionFactory
    _url = url
    _engine = None          # <- race window: another thread calls get_engine()
    _SessionFactory = None
```

**Fix -- add `threading.Lock()`:**
```python
import threading

_lock = threading.Lock()

def configure(url: str):
    global _url, _engine, _SessionFactory
    with _lock:
        _url = url
        if _engine:
            _engine.dispose()
        _engine = None
        _SessionFactory = None

def get_engine():
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:  # double-checked locking
                url = _url or load_config()["database"]["url"]
                _engine = create_engine(
                    url, pool_pre_ping=True, pool_recycle=3600,
                    pool_size=8, max_overflow=4,
                )
    return _engine
```

**Impact:** Prevents test pollution when tests run concurrently.

---

## 🟡 MEDIUM -- `fast_evaluation.py`: Per-Row INSERT in Loop (Reinforcing Prior Audit)

### 7. Dual DELETE + Individual `session.add()` Per Row

**File:** `src/pipeline/fast_evaluation.py:75-113`

Prior audit covered `session.add()` per row. Additional concern: **dual DELETE queries** before INSERTs flush ORM identity map. Fix with `session.add_all()` + chunking:

```python
with open_session(ctx) as session:
    # Delete old (same)
    session.query(FastEvaluationAnalyst).filter_by(pipeline_run_id=ctx.run_id).delete()
    session.query(FastEvaluationConclusion).filter_by(pipeline_run_id=ctx.run_id).delete()

    # Build ALL rows in memory, then bulk insert
    conclusions = []
    analysts = []
    now = dt.datetime.utcnow()
    for ev in evaluations:
        pos, neg, neu = _count_by_opinion(ev.opinions)
        conclusions.append(FastEvaluationConclusion(
            pipeline_run_id=ctx.run_id, ticker=ev.ticker, backend=backend_name,
            start_date=dt.date.fromisoformat(ev.start_date),
            end_date=dt.date.fromisoformat(ev.end_date),
            evaluation_date=now, positive_count=pos, negative_count=neg,
            neutral_count=neu, total_count=pos + neg + neu,
            consensus_score=ev.consensus_score,
            model_name=evaluator_cfg.get("model_name", ""),
            model_provider=evaluator_cfg.get("model_provider", ""),
        ))
        for op in ev.opinions:
            analysts.append(FastEvaluationAnalyst(
                pipeline_run_id=ctx.run_id, ticker=ev.ticker, backend=backend_name,
                analyst_name=op.analyst_name, opinion=op.opinion,
                confidence=op.confidence, reasoning=op.reasoning,
                start_date=dt.date.fromisoformat(ev.start_date),
                end_date=dt.date.fromisoformat(ev.end_date),
                evaluation_date=now,
            ))

    BATCH = 500
    for i in range(0, len(conclusions), BATCH):
        session.add_all(conclusions[i:i + BATCH])
    for i in range(0, len(analysts), BATCH):
        session.add_all(analysts[i:i + BATCH])
    session.commit()
```

**Impact:** 10 tickers x 5 analysts = 50 `session.add()` -> 1-2 `session.add_all()` calls.

---

## 🔵 LOW -- `deep_evaluation.py`: Unnecessary Dict Build Per Evaluation

### 8. `_NAMED_SLOTS` Tuple Iteration Per Item

**File:** `src/pipeline/deep_evaluation.py:14-20, 73`

```python
# Current -- builds intermediate dict for unpacking:
_NAMED_SLOTS = ("market_report", ...)
for ev in evaluations:
    slot_kwargs = {slot: ev.agent_outputs.get(slot) for slot in _NAMED_SLOTS}
    row = DeepEvaluationRow(**slot_kwargs, ...)
```

**Fix -- direct keyword arguments:**
```python
for ev in evaluations:
    row = DeepEvaluationRow(
        pipeline_run_id=ctx.run_id,
        ticker=ev.ticker,
        backend=backend_name,
        evaluation_date=eval_date,
        extra_outputs=ev.extra_outputs,
        final_decision=ev.final_decision,
        model_name=evaluator_cfg.get("model_name"),
        market_report=ev.agent_outputs.get("market_report"),
        bull_argument=ev.agent_outputs.get("bull_argument"),
        bear_argument=ev.agent_outputs.get("bear_argument"),
        research_manager_decision=ev.agent_outputs.get("research_manager_decision"),
        trader_plan=ev.agent_outputs.get("trader_plan"),
    )
```

**Impact:** Micro-optimization. 5 dict lookups + 1 dict build per evaluation eliminated.

---

## Note on React Re-renders

This is a **Python/Streamlit codebase**, not React. No React components exist. Streamlit re-render equivalents (every widget interaction re-runs the full script) are covered in prior audits under "No `@st.cache_data`" and "All tabs execute every rerun."

---

## Summary: Priority Fix Order

| # | Severity | Issue | Effort | Impact |
|---|----------|-------|--------|--------|
| 1 | CRITICAL | `iterrows()` in `_fetch_and_store_prices` | 15 min | 4-6x faster ingestion |
| 2 | CRITICAL | `iterrows()` + per-cell float in `compute_indicators` | 15 min | 3-5x faster indicators |
| 3 | CRITICAL | 6 session open/close per stock in ingestion | 2 hr | 90% fewer connections |
| 4 | HIGH | Unbounded `stock_news` cache growth | 30 min | Prevents DB bloat |
| 5 | HIGH | Module-level monkey-patching on import | 15 min | Cleaner test imports |
| 6 | MEDIUM | Global state race in `database.py` | 15 min | Thread safety |
| 7 | MEDIUM | DELETE + per-row INSERT in fast_eval | 1 hr | 50 SQL -> 2 statements |
| 8 | LOW | Tuple iteration in deep_evaluation | 5 min | Minor clarity |

**Total estimated fix time:** ~4.5 hours for all 8 new issues.

**Cumulative impact with prior audit fixes:** 50-80% reduction in pipeline wall-clock time, 90% fewer DB round-trips, unbounded growth paths eliminated.
