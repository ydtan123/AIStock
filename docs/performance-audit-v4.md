# AIStock Performance Audit v4 — Consolidated Findings

**Date:** 2026-05-30
**Scope:** Cross-referenced against 6 prior audits (v1-v3 + supplement + comprehensive + analysis)
**Approach:** Read every source file; classified ALL findings by severity & fix effort; prior findings status-checked against current code

---

## Prior Audit Coverage Status

| Source | Issues | Still Open | Key Themes |
|--------|--------|-----------|------------|
| `performance-audit.md` | 17 | 14 | N+1, `@st.cache`, delete-reinsert, per-row inserts |
| `performance-audit-supplement.md` | 7 | 6 | `iterrows`, session-per-symbol, async gaps |
| `performance-audit-supplement-v3.md` | 8 | 6 | Session fragmentation, cache TTL, monkey-patching, race condition |
| `performance-analysis.md` | 11 | 9 | DB session patterns, DataFrame inefficiency, redundant reads |
| `performance-audit-comprehensive-v2.md` | 5 | 4 | Cross-cutting: caching, logging, N+1 variants |
| `performance-analysis-comprehensive.md` | 8 | 7 | Streamlit state reinit, CSV re-reads, DB index gaps |
| **Total ~unique** | **~25** | **~22** | |

---

## 🔴 CRITICAL (Fix Immediately — Minutes Per Run Saved)

### C1. Deep Evaluation: Sequential Per-Ticker LLM Calls

**File:** `src/pipeline/backends/deep_evaluators.py:148`
**Severity:** CRITICAL — **Wall-clock multiplier on most expensive pipeline step**
**Prior audit coverage:** Mentioned as "Sequential LLM per ticker" but no config fix proposed

```python
# CURRENT: line 148 — sequential, serial per-ticker
for ticker in tickers:
    result = graph.propagate(ticker, eval_date)  # 30-90s per ticker
```

**Impact:** 10 tickers × 60s = **10 minutes** wall-clock. With 3 workers → **~4 minutes**.
**Fix effort:** Low — add ThreadPoolExecutor with config knob

**Fix:**

```python
# src/pipeline/backends/deep_evaluators.py
from concurrent.futures import ThreadPoolExecutor, as_completed

class TradingAgentsDeepEvaluator(DeepEvaluator):
    name = "trading_agents"

    def evaluate(self, tickers: list[str], ctx: StepContext) -> list[DeepEvaluation]:
        # ... existing setup ...
        max_workers = sub.get("max_parallel", 3)  # configurable
        graph = _build_graph(selected_analysts=analysts, debug=sub.get("debug", False), config=ta_cfg)

        out: list[DeepEvaluation] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._evaluate_one, graph, ticker, eval_date, sub): ticker
                for ticker in tickers
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    out.append(result)
        return out

    def _evaluate_one(self, graph, ticker: str, eval_date: str, sub: dict) -> DeepEvaluation | None:
        """Isolated per-ticker evaluation — thread-safe via separate graph instance or lock."""
        try:
            result = graph.propagate(ticker, eval_date)
            # ... extract decision same as current lines 156-181 ...
            return DeepEvaluation(ticker=ticker, ...)
        except Exception as e:
            logger.exception("TradingAgents failed for %s: %s", ticker, e)
            return None
```

**Estimated impact:** 60-70% reduction in deep evaluation wall-clock time for N ≥ 3 tickers.
**Risk:** Ensure `TradingAgentsGraph` is thread-safe. If not, create a fresh graph per thread (add `debug=False` guard).

---

### C2. Fast Evaluation: Delete-Then-Per-Row INSERT (Revisiting Audit #1.4)

**File:** `src/pipeline/fast_evaluation.py:76-113`
**Severity:** CRITICAL — Still OPEN from prior audits
**Prior audit coverage:** Audit #1.4 ("Delete-then-reinsert fast evaluation")

```python
# CURRENT: 2 DELETEs + N×(2 INSERTs) in single transaction
session.query(FastEvaluationAnalyst).filter_by(pipeline_run_id=ctx.run_id).delete()
session.query(FastEvaluationConclusion).filter_by(pipeline_run_id=ctx.run_id).delete()
for ev in evaluations:
    session.add(FastEvaluationConclusion(...))       # #1 per ticker
    for op in ev.opinions:
        session.add(FastEvaluationAnalyst(...))       # #2 per analyst
```

**Impact:** 10 tickers × ~5 analysts = 50+ `session.add()` calls + 10+ separate INSERT roundtrips.
**Fix:** Use MySQL's `ON DUPLICATE KEY UPDATE` with bulk `session.execute()`.

```python
# Replace lines 76-113 with:
from sqlalchemy.dialects.mysql import insert as mysql_insert

# Batch insert conclusions
conclusion_values = [{
    "pipeline_run_id": ctx.run_id,
    "ticker": ev.ticker,
    "backend": backend_name,
    "start_date": dt.date.fromisoformat(ev.start_date),
    "end_date": dt.date.fromisoformat(ev.end_date),
    "evaluation_date": now,
    "positive_count": sum(1 for o in ev.opinions if o.opinion == "bullish"),
    "negative_count": sum(1 for o in ev.opinions if o.opinion == "bearish"),
    "neutral_count": sum(1 for o in ev.opinions if o.opinion == "neutral"),
    "total_count": len(ev.opinions),
    "consensus_score": ev.consensus_score,
    "model_name": evaluator_cfg.get("model_name", ""),
    "model_provider": evaluator_cfg.get("model_provider", ""),
} for ev in evaluations]

stmt = mysql_insert(FastEvaluationConclusion).values(conclusion_values)
stmt = stmt.on_duplicate_key_update(
    consensus_score=stmt.inserted.consensus_score,
    positive_count=stmt.inserted.positive_count,
    negative_count=stmt.inserted.negative_count,
    neutral_count=stmt.inserted.neutral_count,
    total_count=stmt.inserted.total_count,
    evaluation_date=stmt.inserted.evaluation_date,
)
session.execute(stmt)

# Batch insert analysts
analyst_values = [{
    "pipeline_run_id": ctx.run_id,
    "ticker": ev.ticker,
    "backend": backend_name,
    "analyst_name": op.analyst_name,
    "opinion": op.opinion,
    "confidence": op.confidence,
    "reasoning": op.reasoning,
    "start_date": dt.date.fromisoformat(ev.start_date),
    "end_date": dt.date.fromisoformat(ev.end_date),
    "evaluation_date": now,
} for ev in evaluations for op in ev.opinions]

if analyst_values:
    stmt = mysql_insert(FastEvaluationAnalyst).values(analyst_values)
    stmt = stmt.on_duplicate_key_update(
        opinion=stmt.inserted.opinion,
        confidence=stmt.inserted.confidence,
        reasoning=stmt.inserted.reasoning,
    )
    session.execute(stmt)

session.commit()
```

**Estimated impact:** 50+ DB roundtrips → 2. 90%+ reduction in INSERT overhead.

---

## 🟠 HIGH (Fix Soon — Substantial Impact)

### H1. `iterrows()` Antipattern in Two Hot Paths

**Files:** `src/app.py:175`, `src/ingestion/pipeline.py:126`
**Severity:** HIGH — Still OPEN from prior audits (Audit #9, v3 #1-2)
**Prior audit coverage:** Identified in all prior audits; no fix applied

```python
# app.py:175 — predict-only path
for _, row in pred_df.iterrows():
    ticker = row["ticker"]
    stock = _repo.find_stock(str(ticker))  # N+1 DB call
    prices = _repo.get_prices(stock.id, ...)  # N+1 DB call

# ingestion/pipeline.py:126 — _fetch_and_store_prices
for _, row in df.iterrows():
    date_val = row["date"]
    open_val = _safe_float(row.get("1. open", 0))  # dict access per cell
```

**Fix — app.py:**

```python
# Add to repository.py:
def find_stocks_batch(self, symbols: list[str]) -> dict[str, Stock]:
    def _query(s):
        rows = s.query(Stock).filter(Stock.symbol.in_([s.upper() for s in symbols])).all()
        return {r.symbol: r for r in rows}
    return self._with_session(_query)

def get_prices_batch(self, stock_ids: list[int], start: date, end: date) -> dict[int, pd.DataFrame]:
    """Single query for all stock_ids. Returns {stock_id: DataFrame}."""
    def _query(s):
        rows = (
            s.query(DailyPrice)
            .filter(DailyPrice.stock_id.in_(stock_ids),
                    DailyPrice.date >= start, DailyPrice.date <= end)
            .order_by(DailyPrice.date)
            .all()
        )
        from collections import defaultdict
        groups = defaultdict(list)
        for r in rows:
            groups[r.stock_id].append({
                "date": r.date, "open": r.open, "high": r.high,
                "low": r.low, "close": r.close, "adj_close": r.adj_close, "volume": r.volume,
            })
        return {sid: pd.DataFrame(recs) for sid, recs in groups.items()}
    return self._with_session(_query)

# In app.py — replace 2N DB calls with 2:
stocks_map = _repo.find_stocks_batch(tickers_list)  # 1 query
stock_ids = [s.id for s in stocks_map.values()]
prices_map = _repo.get_prices_batch(stock_ids, start, end)  # 1 query

for ticker in tickers_list:
    stock = stocks_map.get(ticker.upper())
    if not stock:
        actual_returns.append(None)
        continue
    prices_df = prices_map.get(stock.id, pd.DataFrame())
    # ... compute return from prices_df ...
```

**Fix — ingestion/pipeline.py:**

```python
# Replace iterrows() with vectorized construction:
records = df.rename(columns={
    "1. open": "open", "2. high": "high", "3. low": "low",
    "4. close": "close", "5. volume": "volume",
}).to_dict("records")

# Or use pd.to_numeric globally:
cols = ["1. open", "2. high", "3. low", "4. close", "5. volume"]
for col in cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")
values = list(zip(df["date"], df["1. open"], df["2. high"],
                   df["3. low"], df["4. close"], df["5. volume"]))
```

**Estimated impact:** 100 DB calls → 2 for 50 tickers. 98% reduction. `iterrows` → vectorized: 10-100× speedup.

---

### H2. `news_cache.py`: Unbounded Growth, No Size/Time Limit

**File:** `src/news_cache.py:67-93`
**Severity:** HIGH — Still OPEN from Audit v3 #3 ("Cache grows without bounds")
**Prior audit coverage:** v3 Supplement identified; no fix applied

```python
# CURRENT: set_cached() writes to DB unconditionally — table grows forever
# No max size, no TTL, no eviction. Every unique (ticker, start, end) lives forever.
```

**Impact:** After 6 months daily runs: ~500 tickers × 180 days × 3 tool types = 270K rows. Each row ≈ 2-5KB. Total DB bloat ≈ 500MB-1.5GB with no utility for expired news.

**Fix:**

```python
# Add to news_cache.py:
import os, time as _time

_CACHE_MAX_DAYS = int(os.environ.get("NEWS_CACHE_MAX_DAYS", "30"))
_LAST_CLEANUP = 0.0

def _cleanup_old_entries(session) -> int:
    """Delete cached news older than _CACHE_MAX_DAYS."""
    from datetime import timedelta
    from sqlalchemy import text
    cutoff = datetime.now() - timedelta(days=_CACHE_MAX_DAYS)
    result = session.execute(
        text("DELETE FROM stock_news WHERE fetched_at < :cutoff"),
        {"cutoff": cutoff},
    )
    session.commit()
    return result.rowcount

def set_cached(tool_name, args, kwargs, result):
    global _LAST_CLEANUP
    # ... existing cache-write logic ...
    # Run cleanup every 60 min to avoid checking on every write
    now = _time.monotonic()
    if now - _LAST_CLEANUP > 3600:
        try:
            deleted = _cleanup_old_entries(session)
            logger.info("[CACHE] cleaned up %d expired entries", deleted)
        except Exception:
            pass
        _LAST_CLEANUP = now

# Add index for efficient cleanup:
# ALTER TABLE stock_news ADD INDEX idx_fetched_at (fetched_at);
```

**Estimated impact:** Prevents unbounded storage growth. Stale data auto-purged.

---

### H3. Redundant `load_config()` Calls

**File:** `src/ingestion/pipeline.py:27,183` + scattered across codebase
**Severity:** HIGH — Config loaded from YAML disk multiple times

`config.py` has caching (`_config` global), but each process/module entry point triggers first load. Plus `_upsert_fundamentals` at line 183 calls `load_config()` inside the function body (not cached by module-level load at line 27):

```python
# ingestion/pipeline.py
_cfg = load_config()           # line 27 — module level, cached

def _upsert_fundamentals(...):
    ...
    config = load_config()      # line 183 — redundant (already cached, but $ lookups)
    alpha_key = config["alpha_vantage"]["api_key"]
```

**Fix:**

```python
# Already mostly harmless since config.py caches. But avoid calling inside hot functions.
# Replace line 183:
-    config = load_config()
-    alpha_key = config["alpha_vantage"]["api_key"]
+    alpha_key = _cfg["alpha_vantage"]["api_key"]   # use module-level cached _cfg
```

Also: `scheduler.py:56,75,88` calls `load_config()` in 3 separate functions. Cache at module level.

---

## 🟡 MEDIUM (Good Improvement, Lower Urgency)

### M1. `_compute_consensus` — Double Iteration of Opinions

**File:** `src/pipeline/backends/fast_evaluators.py:114-121`
**Severity:** MEDIUM — Micro-optimization, but runs in hot path

```python
def _compute_consensus(opinions):
    total_conf = sum(o.confidence for o in opinions if o.confidence > 0)  # pass 1
    weighted = sum(                                   # pass 2
        _SIGN_BY_OPINION.get(o.opinion, 0) * o.confidence
        for o in opinions
    )
    return weighted / total_conf if total_conf else 0.0
```

**Fix:** Single pass:

```python
def _compute_consensus(opinions):
    total_conf = 0.0
    weighted = 0.0
    for o in opinions:
        if o.confidence > 0:
            total_conf += o.confidence
            weighted += _SIGN_BY_OPINION.get(o.opinion, 0) * o.confidence
    return weighted / total_conf if total_conf else 0.0
```

**Impact:** Negligible single-run (microseconds). Matters at scale (hundreds of evaluations).

---

### M2. `_count_by_opinion` Called Twice Per Evaluation

**File:** `src/pipeline/fast_evaluation.py:83,119`
**Severity:** MEDIUM — Redundant O(N) passes

```python
# Line 83: for DB insert
pos, neg, neu = _count_by_opinion(ev.opinions)

# Line 119: for report payload — SAME opinions list!
pos, neg, neu = _count_by_opinion(ev.opinions)
```

**Fix:** Compute once, reuse:

```python
for ev in evaluations:
    counts = _count_by_opinion(ev.opinions)  # compute once
    session.add(FastEvaluationConclusion(
        positive_count=counts[0], negative_count=counts[1], neutral_count=counts[2], ...
    ))
    # ... later ...
    ranked.append({
        "ticker": ev.ticker,
        "positive": counts[0], "negative": counts[1], "neutral": counts[2],
    })
```

---

### M3. `save_selected_stocks` / `save_predict_only_results` — Per-Row Session.add()

**File:** `src/repository.py:220-236, 245-262`
**Severity:** MEDIUM — Still OPEN from Audit #1.1

Each record gets `session.add()` individually. SQLAlchemy tracks each in identity map. For 50 stocks, 50 tracked objects.

**Fix:**

```python
# Use session.bulk_insert_mappings() or session.execute() with INSERT VALUES
def save_selected_stocks(self, records: list[dict], pipeline_run_id: int | None = None):
    def _query(s):
        if pipeline_run_id is not None:
            s.query(SelectedStock).filter_by(pipeline_run_id=pipeline_run_id).delete()
        run_at = datetime.now()
        mappings = [{
            "ticker": r["ticker"],
            "model_name": r.get("model_name", ""),
            "ml_score": float(r.get("ml_score", 0)),
            "bucket": r.get("bucket"),
            "weight": float(r["weight"]) if r.get("weight") is not None else None,
            "date_selected": r.get("date_selected", date.today()),
            "model_file": r.get("model_file"),
            "pipeline_run_at": run_at,
            "predicted_return": float(r.get("ml_score", 0)),
            "predicted_at": run_at,
            "pipeline_run_id": pipeline_run_id,
        } for r in records]
        s.bulk_insert_mappings(SelectedStock, mappings)
        s.commit()
        return len(mappings)
    return self._with_session(_query)
```

---

### M4. `Database` Module-Level Mutable Global State

**File:** `src/database.py:7-9`
**Severity:** MEDIUM — Still OPEN from Audit v3 #6 ("Race condition on configure()+get_engine()")

```python
_url: str | None = None
_engine = None        # mutable singleton
_SessionFactory = None  # mutable singleton
```

**Impact:** `configure(url)` resets globals. Race if called concurrently. Tests that call `configure()` can pollute other tests.

**Fix:**

```python
import threading

_lock = threading.Lock()

def get_engine():
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:  # double-checked locking
                url = _url or load_config()["database"]["url"]
                _engine = create_engine(url, ...)
    return _engine
```

---

### M5. Fetcher TokenBucket Spin-Waits

**File:** `src/fetcher/rate_limiter.py:28-38`
**Severity:** MEDIUM — Burns CPU while waiting

```python
def acquire(self, tokens: int = 1):
    while True:
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        now = time.monotonic()
        ...
        time.sleep(0.05)  # spin-wait: 20 wakeups/second
```

**Fix:**

```python
def acquire(self, tokens: int = 1, timeout: float = 120.0):
    deadline = time.monotonic() + timeout
    while True:
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
        # Calculate exact wait time instead of fixed 0.05s
        wait = max(0.1, (tokens - self._tokens) / self._refill_rate)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Rate limiter: could not acquire {tokens} tokens in {timeout}s")
        time.sleep(min(wait, remaining, 1.0))
```

Add `threading.Lock` for thread safety (currently `_refill` read-modify-write is racy).

---

## 🔵 LOW (Nice to Have)

### L1. Streamlit: Zero `@st.cache_data` Decorators

**File:** `src/app.py` (throughout)
**Severity:** LOW (but cumulative impact high) — Still OPEN from Audit #2.1

Every Streamlit rerender triggers fresh DB queries for overview stats, stock lists, and screener results.

**Fix:**

```python
@st.cache_data(ttl=300)  # 5 min cache
def _load_overview_stats():
    repo = StockRepository()
    return repo.count_summary()

@st.cache_data(ttl=600)
def _load_stock_list():
    repo = StockRepository()
    filters = StockFilters()
    return repo.list_stocks(filters)

# In page functions:
overview = _load_overview_stats()
stocks_df = _load_stock_list()
```

Add to: `show_overview()`, `page_stock_data()` screener tab, `get_sectors()` calls.

---

### L2. Redundant `_calculate_return()` in Multiple File Reads

**File:** `src/app.py:` (ML pipeline results display)
**Severity:** LOW — Still OPEN from Audit #10

ML pipeline results CSV is read, parsed, iterated every Streamlit rerender cycle.

**Fix:** Cache with `@st.cache_data` or precompute at pipeline completion.

---

### L3. `get_prices()` — Per-Row Dict Build → DataFrame

**File:** `src/repository.py:58-69`
**Severity:** LOW — Noticeable for larger date ranges

```python
# CURRENT: list comprehension → DataFrame
return pd.DataFrame([{
    "date": r.date, "open": r.open, ...
} for r in rows])
```

**Fix:** Use SQLAlchemy `read_sql` or structured numpy arrays:

```python
from sqlalchemy import select

def get_prices(self, stock_id, start, end):
    def _query(s):
        stmt = (
            select(DailyPrice.date, DailyPrice.open, DailyPrice.high,
                   DailyPrice.low, DailyPrice.close, DailyPrice.adj_close, DailyPrice.volume)
            .where(DailyPrice.stock_id == stock_id,
                   DailyPrice.date >= start, DailyPrice.date <= end)
            .order_by(DailyPrice.date)
        )
        return pd.read_sql(stmt, s.bind)
    return self._with_session(_query)
```

---

### L4. `_FINAL_STATE_TO_SLOT` Tuple Iteration in Deep Evaluation Constructor

**File:** `src/pipeline/backends/deep_evaluators.py:38-51`
**Severity:** LOW — Already identified in v3 Supplement #8

`_FINAL_STATE_TO_SLOT` dict is iterated over `final_state.items()` for EVERY evaluation (line 164). The dict lookup is O(1), but for dozens of evaluations, predefine a set of known keys.

**Fix:**

```python
_SLOT_KEYS = frozenset(_FINAL_STATE_TO_SLOT.keys())

for src_key, value in final_state.items():
    if src_key in _SLOT_KEYS:
        agent_outputs[_FINAL_STATE_TO_SLOT[src_key]] = ...
```

---

## Note on React Re-renders

**This is a Python/Streamlit codebase, not React.** The "React re-renders" question does not apply. The Streamlit equivalent is unnecessary reruns — see L1 (missing `@st.cache_data`) and L2 (redundant file reads).

---

## Note on Memory Leaks

No classic unbounded-reference-graph memory leaks found. However:

1. **news_cache unbounded growth** (H2) — rows accumulate forever in MySQL. While not a Python heap leak, it is a persistent storage leak with identical operational impact.

2. **Module-level monkey-patching** (`news_cache.py:install()`) creates persistent closure references (`_original`, `_cached_route`). These are intentional and bounded — one per patched module — but prevent GC of the original `route_to_vendor` function. Acceptable given the trade-off.

3. **Streamlit session_state** (`app.py:52-63`) — `ml_log_lines` list grows unbounded during an ML pipeline run. Consider capping at the latest 500 lines.

---

## Priority Fix Order

| # | Issue | Severity | Effort | Impact |
|---|-------|---------|--------|--------|
| 1 | C1: Deep eval parallelism | CRITICAL | 2h | 60-70% wall-clock reduction |
| 2 | H1: `iterrows` + N+1 in app.py | HIGH | 3h | 98% DB call reduction |
| 3 | C2: Fast eval bulk INSERT | CRITICAL | 1.5h | 90% DB roundtrip reduction |
| 4 | H2: news_cache TTL eviction | HIGH | 1h | Prevent unbounded storage |
| 5 | H3: Redundant load_config | HIGH | 0.5h | Cleaner, fewer YAML parses |
| 6 | M1-M3: Redundant iterations | MEDIUM | 1h | Cumulative CPU saving |
| 7 | M3: Bulk insert in repository | MEDIUM | 1h | 50× fewer session.add() calls |
| 8 | M4: database.py thread safety | MEDIUM | 0.5h | Test reliability |
| 9 | M5: Rate limiter efficiency | MEDIUM | 0.5h | Reduce CPU spin |
| 10 | L1-L4: Low-priority cleanups | LOW | 2h | Overall polish |

**Total fix effort:** ~13 hours for CRITICAL + HIGH + MEDIUM.
**Estimated cumulative speedup:** 3-5× on pipeline runtime, 10× on UI responsiveness.

---

## Verification Checklist

- [ ] Deep eval: run with `max_parallel=3`, verify identical outputs to sequential
- [ ] Fast eval: run with bulk INSERT, verify no duplicate key errors, row counts match
- [ ] app.py: run predict-only path, verify actual returns match pre-fix values
- [ ] news_cache: add fake old entries, verify cleanup deletes them
- [ ] database.py: run concurrent test with `configure()`, verify no race
- [ ] All changes: `PYTHONPATH=src pytest tests/ -v` passes
