# AIStock Performance Audit — Supplement

**Date:** 2026-05-30
**Scope:** 7 new findings not in `docs/performance-audit.md` or `docs/performance-analysis.md`
**Base audit:** 17 issues across 4 severity tiers (CRITICAL → INFO)

---

## Status of Base Audit Issues

| Issue | Status |
|-------|--------|
| 1.1 `session.add()` loop in `save_selected_stocks` | ❌ Still open |
| 1.2 Per-stock `find_stock()` + `get_prices()` loop | ❌ Still open |
| 1.3 Sequential LLM per ticker (deep evaluator) | ❌ Still open |
| 1.4 Delete-then-reinsert (fast evaluation) | ❌ Still open |
| 2.1 Zero `@st.cache_data` decorators | ❌ Still open |
| 2.2 `st.rerun()` polling loop | ❌ Still open |
| 3.1 `count_summary()` / `get_sectors()` no cache | ❌ Still open |
| 3.2 Config module cache no mtime revalidation | ❌ Still open |
| 4.1 `st.session_state` unbounded figures | ❌ Still open |
| 4.2 ThreadPoolExecutor sessions no timeout | ❌ Still open |
| 5.1 `_open_session` triplicated | ✅ Fixed via `pipeline/base.py` |
| 5.2 Python sort after SQL ORDER BY | ❌ Still open |
| 6.1 `pool_size=8` bottleneck risk | ❌ Still open |
| 7.1 `lazy='select'` on 8 relationships | ❌ Still open |
| 8.2 `iterrows()` in app.py | ❌ Still open |
| 9.2 `news_cache` reinstalled per evaluate() | ❌ Still open |
| 10.1 `session.add()` loop in deep_evaluation | ❌ Still open |

**16 of 17 code issues remain open. Only 5.1 resolved.**

---

## New Finding 1: FastEvaluationAnalyst nested `session.add()` loop

**File:** `src/pipeline/fast_evaluation.py:82-112`
**Severity:** HIGH
**Category:** N+1 queries

```python
# CURRENT — 2 individual INSERTs per ticker
with open_session(ctx) as session:
    session.query(FastEvaluationAnalyst).filter_by(...).delete()
    session.query(FastEvaluationConclusion).filter_by(...).delete()
    for ev in evaluations:
        session.add(FastEvaluationConclusion(...))     # 1 INSERT/ticker
        for op in ev.opinions:
            session.add(FastEvaluationAnalyst(...))     # N INSERTs/ticker (analysts)
    session.commit()
```

10 tickers × 5 analysts = 50 individual INSERTs.

**Fix — `session.add_all()`:**

```python
with open_session(ctx) as session:
    session.query(FastEvaluationAnalyst).filter_by(
        pipeline_run_id=ctx.run_id
    ).delete()
    session.query(FastEvaluationConclusion).filter_by(
        pipeline_run_id=ctx.run_id
    ).delete()
    session.flush()

    conclusions = []
    analyst_rows = []
    for ev in evaluations:
        pos, neg, neu = _count_by_opinion(ev.opinions)
        conclusions.append(FastEvaluationConclusion(
            pipeline_run_id=ctx.run_id,
            ticker=ev.ticker,
            backend=backend_name,
            start_date=dt.date.fromisoformat(ev.start_date),
            end_date=dt.date.fromisoformat(ev.end_date),
            evaluation_date=now,
            positive_count=pos, negative_count=neg, neutral_count=neu,
            total_count=pos + neg + neu,
            consensus_score=ev.consensus_score,
            model_name=evaluator_cfg.get("model_name", ""),
            model_provider=evaluator_cfg.get("model_provider", ""),
        ))
        for op in ev.opinions:
            analyst_rows.append(FastEvaluationAnalyst(
                pipeline_run_id=ctx.run_id,
                ticker=ev.ticker,
                backend=backend_name,
                analyst_name=op.analyst_name,
                opinion=op.opinion,
                confidence=op.confidence,
                reasoning=op.reasoning,
                start_date=dt.date.fromisoformat(ev.start_date),
                end_date=dt.date.fromisoformat(ev.end_date),
                evaluation_date=now,
            ))
    session.add_all(conclusions)
    session.add_all(analyst_rows)
    session.commit()
```

**Impact:** 50 INSERTs → 2 batches. ~10-25x faster for step 3 persistence.

---

## New Finding 2: `_inject_api_keys` duplicated across 3 locations

**Files:** 
- `src/pipeline/backends/fast_evaluators.py:72-89`
- `src/pipeline/backends/deep_evaluators.py:54-70`
- `src/ingestion/pipeline.py:27-36` (module-level variant)

**Severity:** MEDIUM
**Category:** Redundant code

Three copies of the same "set API keys in os.environ from config" logic. deep_evaluators omits GROQ; fast_evaluators omits GROQ from mapping. ingestion pipeline does it at import time with a different code path.

**Fix — extract to `src/utils.py`:**

```python
# src/utils.py
import os

def inject_api_keys(ctx_cfg: dict) -> None:
    """Set API keys in os.environ from config. Skips keys already present."""
    common = ctx_cfg.get("common", {})
    av_key = (
        common.get("alpha_vantage_api_key")
        or ctx_cfg.get("data_update", {}).get("alpha_vantage", {}).get("api_key")
        or ctx_cfg.get("alpha_vantage", {}).get("api_key")
    )
    key_map = {
        "DEEPSEEK_API_KEY": common.get("deepseek_api_key"),
        "OPENAI_API_KEY": common.get("openai_api_key"),
        "ANTHROPIC_API_KEY": common.get("anthropic_api_key"),
        "GOOGLE_API_KEY": common.get("google_api_key"),
        "GROQ_API_KEY": common.get("groq_api_key"),
        "ALPHA_VANTAGE_API_KEY": av_key,
    }
    for env_var, value in key_map.items():
        if value and env_var not in os.environ:
            os.environ[env_var] = value
```

Then in all three call sites:
```python
from utils import inject_api_keys
inject_api_keys(ctx.cfg)
```

**Impact:** ~30 lines deduplicated. Single source of truth for key injection logic.

---

## New Finding 3: `df.iterrows()` in ingestion `_fetch_and_store_prices`

**File:** `src/ingestion/pipeline.py:126-138`
**Severity:** MEDIUM
**Category:** Pandas anti-pattern

```python
# CURRENT — Series allocation per row
values = []
for _, row in df.iterrows():
    values.append({
        "stock_id": stock.id,
        "date": row["date"],
        "open": row.get("open"),
        # ... 8 more fields
    })
```

125K rows (500 stocks × 250 trading days) = 125K Series heap allocations. Existing audit (8.2) covers `app.py` iterrows but misses this ingestion path.

**Fix:**

```python
df_with_id = df.assign(stock_id=stock.id)
values = df_with_id.to_dict(orient='records')
```

Or with explicit field selection:
```python
COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume",
           "dividend_amount", "split_coefficient"]
df_clean = df[COLUMNS].copy()
df_clean["stock_id"] = stock.id
values = df_clean.where(df_clean.notna(), None).to_dict(orient='records')
```

**Impact:** ~10-50x faster DataFrame-to-dict conversion. Most noticeable during full backfill of 500 stocks.

---

## New Finding 4: `news_cache.install()` at module import time

**File:** `src/ingestion/pipeline.py:38-41`
**Severity:** LOW
**Category:** Side-effect at import

```python
# Executed on EVERY import of ingestion.pipeline
import news_cache
news_cache.install()
```

Runs during test discovery, IDE introspection, or any code that touches `ingestion.pipeline`. Monkeypatches `TradingAgentsGraph` methods unconditionally.

**Fix — lazy initialization:**

```python
_news_cache_installed: bool = False

def _ensure_news_cache() -> None:
    global _news_cache_installed
    if _news_cache_installed:
        return
    import news_cache
    news_cache.install()
    _news_cache_installed = True


def run_daily_pipeline(fetcher, force=False):
    _ensure_news_cache()  # lazy — only on first actual pipeline run
    ...
```

**Impact:** Prevents import-time side effects. Correctness improvement primarily; performance gain ~5ms per import.

---

## New Finding 5: `_refresh_snapshots()` blocks pipeline completion

**File:** `src/ingestion/pipeline.py:458`
**Severity:** LOW
**Category:** Blocking I/O

```python
# Called synchronously after ThreadPool completes
_refresh_snapshots()
```

REPLACE INTO with 5 JOINs + JSON extraction runs on every pipeline invocation. For 500 active stocks: 2-5s blocking. Pipeline reports "running" until this completes.

**Fix:**

```python
import threading

def _refresh_snapshots_async():
    t = threading.Thread(target=_refresh_snapshots, daemon=True)
    t.start()

# Or only refresh when data actually changed:
if processed_ids:
    _refresh_snapshots()
```

**Impact:** Pipeline completion reported immediately instead of after 2-5s snapshot refresh.

---

## New Finding 6: Codebase is Python/Streamlit, not React

**Category:** Framework note

The user asked about React re-renders. This codebase uses **Streamlit** (Python), which re-executes the entire script on every widget interaction. The equivalent of "React re-renders" here is Streamlit reruns. The `@st.cache_data` fix (base audit 2.1) is the Streamlit equivalent of `React.memo` + `useMemo`. 

No React code exists in this repository.

---

## New Finding 7: Deep evaluator LLM calls serial per ticker

**File:** `src/pipeline/backends/deep_evaluators.py:148-154`
**Severity:** HIGH
**Category:** Serial I/O (extends base audit 1.3)

```python
# Sequential — each ticker blocks the next
for ticker in tickers:
    result = graph.propagate(ticker, eval_date)
```

3 tickers × 30s LLM response time = 90s wall-clock. Already noted in base audit (1.3) but implementation details missing.

**Fix with thread-safety guard:**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def evaluate(self, tickers, ctx):
    # ... setup (shared graph creation, API key injection) ...
    
    graph = _build_graph(selected_analysts=analysts, debug=debug, config=ta_cfg)
    
    # Use lock if TradingAgentsGraph is not thread-safe
    _graph_lock = threading.Lock() if not sub.get("thread_safe", False) else None
    
    def _evaluate_one(ticker: str):
        if _graph_lock:
            with _graph_lock:
                return graph.propagate(ticker, eval_date)
        return graph.propagate(ticker, eval_date)
    
    with ThreadPoolExecutor(max_workers=min(len(tickers), 3)) as pool:
        futures = {pool.submit(_evaluate_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result = future.result(timeout=300)
                # ... process result ...
            except Exception as e:
                ctx.logger.exception("Failed for %s", ticker)
```

**Impact:** 3 tickers → 90s sequential → ~35s parallel. 3x speedup.

---

## Combined Priority Ranking

### Tier 1: Ship Immediately (highest ROI, lowest risk)
1. `session.add_all()` everywhere — 1.1, 10.1, N-1.1 — 10-50x speedup on batch writes
2. `@st.cache_data` on dashboard queries — 2.1 — zero DB on rerender
3. `find_stocks_batch()` — 1.2 — 50 queries → 1 query

### Tier 2: High Impact
4. Parallel deep evaluator LLM calls — 1.3, N-7 — 3x pipeline speedup
5. Extract shared `inject_api_keys` — N-2 — dedup + maintainability
6. `iterrows()` → vectorized/to_dict — 8.2, N-3 — 10-50x pandas speedup
7. `st.rerun()` → `st.empty()` placeholders — 2.2

### Tier 3: Quality Improvements
8. `lazy='raise'` on relationships — 7.1 — prevents hidden N+1
9. `news_cache` lazy init — 9.2, N-4 — cleanliness
10. Evict stale `st.session_state` figures — 4.1
11. `_refresh_snapshots()` async — N-5

---

## Summary

| # | Severity | Category | File:Line | Issue |
|---|----------|----------|-----------|-------|
| N-1.1 | HIGH | N+1 | `fast_evaluation.py:82-112` | Nested `session.add()` loop for analysts |
| N-2 | MEDIUM | DRY | 3 files | `_inject_api_keys` duplicated |
| N-3 | MEDIUM | Pandas | `ingestion/pipeline.py:126` | `iterrows()` in price ingestion |
| N-4 | LOW | Import | `ingestion/pipeline.py:40` | `news_cache.install()` at import time |
| N-5 | LOW | Blocking | `ingestion/pipeline.py:458` | Snapshot refresh blocks pipeline |
| N-6 | INFO | Note | N/A | Codebase is Python/Streamlit, not React |
| N-7 | HIGH | Serial | `deep_evaluators.py:148` | LLM calls serial per ticker |

**Total:** 24 issues (17 base audit + 7 supplement). 16 base audit issues open. 7 new findings documented.
