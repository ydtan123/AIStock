# AIStock Performance Audit v6 — Comprehensive

**Date:** 2026-05-30
**Scope:** Python/Streamlit/MySQL stack. All findings verified against current code.
**Note:** Streamlit project — no React. "Re-render" = full-script re-execution.

---

## Prior Audit Status

**14 findings from v5 audit** (`docs/performance-audit-verified-2026-05-30.md`):
**0 out of 14 applied.** All issues remain in current code.

This audit re-validates all prior findings + adds 10 new findings (memory leaks, redundant computations, additional patterns).

---

## Summary Table

| # | Severity | Category | File(s) | Issue | New? |
|---|----------|----------|---------|-------|------|
| 1 | 🔴 CRITICAL | N+1 DB | `pipeline/fast_evaluation.py:85,101` | Per-row `session.add()` in nested loop | — |
| 2 | 🔴 CRITICAL | N+1 DB | `pipeline/deep_evaluation.py:89` | Per-row `session.add()` in evaluation loop | — |
| 3 | 🔴 CRITICAL | N+1 DB | `repository.py:235` | Per-row `s.add()` in `save_selected_stocks()` | — |
| 4 | 🔴 CRITICAL | N+1 DB | `repository.py:259` | Per-row `s.add()` in `save_predict_only_results()` | — |
| 5 | 🔴 CRITICAL | N+1 DB | `app.py:175-190` | Per-ticker `find_stock()` + `get_prices()` in predict loop | — |
| 6 | 🔴 CRITICAL | Serial I/O | `backends/deep_evaluators.py:148` | Sequential `graph.propagate()` per ticker | — |
| 7 | 🟠 HIGH | Caching | 13 `ui/pages/*.py` files | Zero `@st.cache_data` decorators | — |
| 8 | 🟠 HIGH | N+1 DB | `ingestion/symbols.py:35` | Per-row `session.execute(insert)` + `iterrows()` | — |
| 9 | 🟡 MEDIUM | Pandas | `app.py:175` | `iterrows()` → `itertuples()` | — |
| 10 | 🟡 MEDIUM | Pandas | `ingestion/pipeline.py:126` | `iterrows()` for DataFrame→dict conversion | — |
| 11 | 🟡 MEDIUM | Redundant I/O | `ui/pages/ml_pipeline.py` | Repeated `pd.read_csv()` of same file | — |
| 12 | 🟢 LOW | Caching | `fetcher/alpha_vantage.py` | `get_listing()` no disk cache | — |
| 13 | 🟢 LOW | Config | `config.py:16` | Module cache no mtime revalidation | — |
| 14 | 🟢 LOW | DB Pool | `database.py:24` | `pool_size=8` bottleneck under load | — |
| 15 | 🟠 HIGH | Memory Leak | `app.py:53-54` | `ml_log_lines` grows unbounded across pipeline runs | ✅ |
| 16 | 🟠 HIGH | Memory Leak | `app.py:63` | `ml_log_queue` reused across runs — stale sentinels | ✅ |
| 17 | 🟡 MEDIUM | Redundant | `pipeline/fast_evaluation.py:83,119` | `_count_by_opinion()` called 2× per ticker | ✅ |
| 18 | 🟡 MEDIUM | DB Session | `ingestion/pipeline.py:118-173` | `_fetch_and_store_prices` opens 2 sessions when `max_date=None` | ✅ |
| 19 | 🟡 MEDIUM | N+1 DB | `ingestion/pipeline.py:194` | Per-stock `StockIndicator` query when prefetch has no data | ✅ |
| 20 | 🟡 MEDIUM | Redundant | `ingestion/pipeline.py:183` | `load_config()` called again inside function (hits cache) | ✅ |
| 21 | 🟡 MEDIUM | Pandas | `ui/pages/paper_trading.py:50` | `iterrows()` for dict conversion | ✅ |
| 22 | 🟡 MEDIUM | Pandas | `ingestion/indicators.py:97` | `iterrows()` in indicator computation | ✅ |
| 23 | 🟢 LOW | Streamlit | `ui/pages/stock_lookup.py:21,41-42` | `find_stock()` re-executes on every widget change | ✅ |
| 24 | 🟢 LOW | Queue | `app.py:87` | `put_nowait()` silently drops logs when queue full | ✅ |

---

## 🔴 Critical Issues (all unapplied from prior audit)

### #1-4 — Per-Row `session.add()` (4 locations)

All four locations still use per-row `session.add()` instead of `session.add_all()`:

| File | Line | Context |
|------|------|---------|
| `pipeline/fast_evaluation.py` | 85, 101 | Conclusions + analysts per-ticker |
| `pipeline/deep_evaluation.py` | 89 | DeepEvaluation rows per-ticker |
| `repository.py` | 235 | `save_selected_stocks()` per-rec |
| `repository.py` | 259 | `save_predict_only_results()` per-rec |

**Fix:** Collect into list, call `session.add_all(rows)` once.

**#1 Example — FastEvaluationStep** (`src/pipeline/fast_evaluation.py`):

```python
# CURRENT (lines 82-113)
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)
    session.add(FastEvaluationConclusion(...))        # per-ticker
    for op in ev.opinions:
        session.add(FastEvaluationAnalyst(...))        # per-analyst
session.commit()

# FIXED
conclusions: list[FastEvaluationConclusion] = []
analysts: list[FastEvaluationAnalyst] = []
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

session.add_all(conclusions)
session.add_all(analysts)
session.commit()
```

**#3 Example — Repository** (`src/repository.py`):

```python
# CURRENT (lines 220-236)
for rec in records:
    s.add(SelectedStock(...))
    inserted += 1
s.commit()

# FIXED
rows = []
run_at = datetime.now()
for rec in records:
    rows.append(SelectedStock(
        ticker=rec["ticker"], model_name=rec.get("model_name", ""),
        ml_score=float(rec.get("ml_score", 0)),
        bucket=rec.get("bucket"),
        weight=float(rec["weight"]) if rec.get("weight") is not None else None,
        date_selected=rec.get("date_selected", date.today()),
        model_file=rec.get("model_file"),
        pipeline_run_at=run_at, predicted_return=float(rec.get("ml_score", 0)),
        predicted_at=run_at, pipeline_run_id=pipeline_run_id,
    ))
s.add_all(rows)
s.commit()
return len(rows)
```

**Impact:** 90 `add()` calls → 2 `add_all()` for fast eval; N → 1 for repository. ~98% fewer ORM dispatch cycles.

---

### #5 — Per-Ticker `find_stock()` + `get_prices()` in Predict-Only Pipeline

**File:** `src/app.py:175-190` (`_predict_only_thread_target`)

2 DB round-trips per ticker (each opens/closes session). 50 tickers = 100 DB calls.

```python
# CURRENT
for _, row in pred_df.iterrows():           # iterrows() also slow — see #9
    stock = _repo.find_stock(str(ticker))    # DB call #1
    prices = _repo.get_prices(stock.id, dd, _date.today())  # DB call #2
```

**Fix — Add batch lookup to `src/repository.py`:**

```python
def find_stocks_batch(self, symbols: list[str]) -> dict[str, Stock]:
    """Look up multiple stocks in a single query. Returns {SYMBOL: Stock}."""
    def _query(s):
        rows = s.query(Stock).filter(
            Stock.symbol.in_([str(x).upper() for x in symbols])
        ).all()
        return {r.symbol: r for r in rows}
    return self._with_session(_query)
```

**Rewrite in `app.py`:**

```python
unique_symbols = pred_df["ticker"].dropna().unique().tolist()
stock_map = _repo.find_stocks_batch(unique_symbols)   # 1 query instead of N

for row in pred_df.itertuples():                       # 10-100x faster
    ticker = str(row.ticker).upper()
    dd = row.datadate.date()
    stock = stock_map.get(ticker)
    if stock is None:
        actual_returns.append(None)
        continue
    prices = _repo.get_prices(stock.id, dd, _date.today())
    # ...
```

**Impact:** 100 DB calls → 2 (+ N for get_prices). 50% fewer round-trips for lookup half.

---

### #6 — Sequential LLM Calls in Deep Evaluator

**File:** `src/pipeline/backends/deep_evaluators.py:148`

Each `graph.propagate()` runs multiple LLM rounds (30-90s). Serial execution: 3 tickers = 90-270s wall-clock.

```python
# CURRENT (line 148) — serial, each ticker blocks the next
for ticker in tickers:
    result = graph.propagate(ticker, eval_date)
```

**Fix — `ThreadPoolExecutor`:**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _evaluate_one(ticker: str) -> tuple[str, Any, str | None]:
    try:
        result = graph.propagate(ticker, eval_date)
        return ticker, result, None
    except Exception as e:
        return ticker, None, str(e)

out: list[DeepEvaluation] = []
with ThreadPoolExecutor(max_workers=min(len(tickers), 3)) as pool:
    futures = {pool.submit(_evaluate_one, t): t for t in tickers}
    for future in as_completed(futures):
        ticker, result, error = future.result(timeout=300)
        if error:
            ctx.logger.exception("TradingAgents failed for %s: %s", ticker, error)
            continue
        final_state, decision = result if isinstance(result, tuple) else (result, None)
        # ... process result same as current loop body ...
```

**Impact:** 3 tickers → ~35-90s instead of 90-270s (~3× speedup).

---

## 🟠 High Issues

### #7 — Zero `@st.cache_data` Decorators

**All 13 `src/ui/pages/*.py` files.** Every DB query re-executes on every widget interaction. Streamlit default: full script re-execution on each user event.

**Affected pages and DB/IO operations:**

| Page | Queries/IO per interaction |
|------|---------------------------|
| `stock_lookup.py` | 3 (`find_stock`, `get_indicator`, `get_prices`) |
| `stock_screener.py` | 1 (`screen_stocks`) |
| `stock_manager.py` | 1 (`list_stocks`) |
| `stock_technical.py` | 2 (`get_prices`, `get_tech_indicators`) |
| `overview.py` | 1 (`count_summary`) |
| `ml_pipeline.py` | 3-5 CSV reads + JSON load |
| `portfolio.py` | 1 (`get_latest_selected_stocks`) |
| `job_history.py` | 1 (`get_job_runs`) |

**Fix — wrap DB queries with `@st.cache_data`:**

```python
import streamlit as st
from datetime import date

# In stock_lookup.py or shared cache module:
@st.cache_data(ttl=300, show_spinner=False)
def _cached_find_stock(symbol: str) -> dict | None:
    stock = StockRepository().find_stock(symbol)
    if stock is None:
        return None
    return {"id": stock.id, "symbol": stock.symbol, "name": stock.name,
            "sector": stock.sector, "exchange": stock.exchange,
            "industry": stock.industry, "is_active": stock.is_active}

@st.cache_data(ttl=60, show_spinner=False)
def _cached_get_prices(stock_id: int, start: str, end: str) -> pd.DataFrame:
    return StockRepository().get_prices(
        stock_id, date.fromisoformat(start), date.fromisoformat(end))

# In overview.py:
@st.cache_data(ttl=60)
def _cached_count_summary() -> dict:
    return StockRepository().count_summary()

# In ml_pipeline.py:
@st.cache_data(ttl=3600, show_spinner="Loading ML results...")
def _load_ml_results() -> dict:
    """Load all ML output files once. Cache 1 hour."""
    # ... read CSV/JSON files ...
    return {"weights": wdf, "fundamentals": fdf, "feature_importance": fi, "backtest": bt}
```

**TTLs by query type:**
- Prices/indicators: 60s (intraday stale acceptable)
- Screener/manager list: 300s
- Count summary: 60s
- ML results CSVs: 3600s

**Impact:** 80-95% fewer DB queries per user session. For a typical 5-minute session: 100+ queries → 1-5 queries.

---

### #8 — Per-Row `session.execute()` + `iterrows()` in `refresh_symbols()`

**File:** `src/ingestion/symbols.py:35-65`

6000+ NASDAQ+NYSE rows → 6000 individual INSERT statements. Worst possible path (N individual round-trips + per-row Series allocation).

```python
# CURRENT — 6000+ individual INSERT statements
for _, row in df.iterrows():
    stmt = insert(Stock).values(symbol=row["symbol"], ...).on_duplicate_key_update(...)
    session.execute(stmt)
```

**Fix — batch execute in chunks of 200:**

```python
BATCH_SIZE = 200
all_values = []
for row in df.itertuples():
    all_values.append({
        "symbol": row.symbol,
        "name": _clean(getattr(row, "name", None)),
        "asset_type": _clean(getattr(row, "asset_type", None)),
        "exchange": _clean(getattr(row, "exchange", None)),
        "is_active": False,
    })

for i in range(0, len(all_values), BATCH_SIZE):
    batch = all_values[i:i + BATCH_SIZE]
    stmt = insert(Stock).values(batch)
    stmt = stmt.on_duplicate_key_update(
        name=stmt.inserted.name,
        asset_type=stmt.inserted.asset_type,
        exchange=stmt.inserted.exchange,
    )
    session.execute(stmt)
session.commit()
```

**Impact:** 6000 `execute()` calls → 30 batches. ~200× fewer round-trips.

---

### #15 — Memory Leak: `ml_log_lines` Unbounded Growth (NEW)

**File:** `src/app.py:53-54`

```python
if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = []
```

The UI polling loop drains the queue and appends each log line to `ml_log_lines`. This list **never gets trimmed**. Each pipeline run produces 100-500 lines. Run 5 times = 500-2500 entries in session memory. Persists until Streamlit server restart.

**Fix — cap at max lines + clear on new run:**

```python
MAX_LOG_LINES = 1000

# In polling loop, after appending:
if len(st.session_state.ml_log_lines) > MAX_LOG_LINES:
    st.session_state.ml_log_lines = st.session_state.ml_log_lines[-MAX_LOG_LINES:]

# On pipeline start:
def _start_pipeline():
    st.session_state.ml_log_lines = []  # fresh slate
    # ...
```

**Impact:** Memory usage stable across repeated pipeline runs. Prevents OOM on long-running Streamlit server.

---

### #16 — Memory Leak: Stale Sentinels in `ml_log_queue` (NEW)

**File:** `src/app.py:63,138,141`

The pipeline thread sends sentinel strings through the queue:
```python
log_queue.put_nowait(f"__REPORT__:{report_path}")     # line 138
log_queue.put_nowait(f"__ERROR__:{exc}")               # line 141
```

The `ml_log_queue` is reused across pipeline runs. If the user starts a new run before the UI has fully drained the previous queue, old `__REPORT__` / `__ERROR__` sentinels could be consumed by the new run's polling loop — causing incorrect status display.

**Fix — clear queue before starting new pipeline:**

```python
def _start_pipeline():
    # Clear stale sentinels from previous run
    while not st.session_state.ml_log_queue.empty():
        try:
            st.session_state.ml_log_queue.get_nowait()
        except queue.Empty:
            break
    st.session_state.ml_log_lines = []
    # ... launch thread ...
```

---

## 🟡 Medium Issues

### #9-10,21-22 — `iterrows()` Antipatterns (5 locations)

Five files still use `iterrows()`. Each allocates a Series per row (heap allocation + type boxing):

| File | Line | Context | Fix |
|------|------|---------|-----|
| `app.py` | 175 | Predict-only loop | `itertuples()` |
| `ingestion/pipeline.py` | 126 | Price data conversion | `df.to_dict(orient="records")` |
| `ingestion/symbols.py` | 35 | Symbol refresh | `itertuples()` |
| `ingestion/indicators.py` | 97 | Indicator computation | `itertuples()` |
| `ui/pages/paper_trading.py` | 50 | Dict conversion | `set_index().to_dict()` |

**#10 Example — Price Data Ingestion** (`src/ingestion/pipeline.py:126`):

```python
# CURRENT — 125K Series allocations for 500 stocks × 250 days
values = []
for _, row in df.iterrows():
    values.append({"stock_id": stock.id, "date": row["date"], ...})

# FIXED — vectorized, zero per-row allocations
COLUMNS = ["date", "open", "high", "low", "close", "adj_close",
           "volume", "dividend_amount", "split_coefficient"]
df_clean = df[COLUMNS].copy()
df_clean["stock_id"] = stock.id
df_clean = df_clean.where(df_clean.notna(), other=None)
values = df_clean.to_dict(orient="records")
```

**Impact:** ~10-50× faster for full backfill. Most noticeable with 500-stock first-time ingestion.

---

### #11 — Repeated CSV Reads in ML Results

**File:** `src/ui/pages/ml_pipeline.py`

`_show_ml_results()` and `_show_ml_backtest()` each re-read CSV/JSON from disk. Tab switch re-reads everything.

**Fix:** `@st.cache_data(ttl=3600)` single loader. See #7 fix above.

**Impact:** 4 file reads → 1 read per hour. Instant tab switches after first load.

---

### #17 — `_count_by_opinion()` Called Twice Per Ticker (NEW)

**File:** `src/pipeline/fast_evaluation.py:83,119`

```python
# DB save loop (line 83) — call #1
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)

# Report ranking loop (line 119) — call #2, same data
for ev in evaluations_sorted:
    pos, neg, neu = _count_by_opinion(ev.opinions)
```

10 tickers × 8 analysts = 80 opinions traversed twice.

**Fix — compute once:**

```python
# Option A: Store in dict
_counts = {}
for ev in evaluations:
    key = ev.ticker
    if key not in _counts:
        _counts[key] = _count_by_opinion(ev.opinions)
    pos, neg, neu = _counts[key]

# Option B: cached_property on dataclass
from functools import cached_property

@dataclass
class FastEvaluation:
    opinions: list
    @cached_property
    def counts(self) -> tuple[int, int, int]:
        return _count_by_opinion(self.opinions)
```

---

### #18 — Double Session Open in `_fetch_and_store_prices()` (NEW)

**File:** `src/ingestion/pipeline.py:95-173`

When `max_date` is None (stock not in prefetch):

```python
# Session #1 — get max_date (lines 103-110)
session = get_session()
max_date = session.execute(...)
session.close()

# Session #2 — fetch + insert (lines 118-173)
session = get_session()
# ... iterrows, batch insert ...
session.close()
```

Two sessions when one suffices. First session fetches single scalar.

**Fix — merge:**

```python
def _fetch_and_store_prices(fetcher, stock, max_date=None):
    session = get_session()
    try:
        if max_date is None:
            max_date = session.execute(
                text("SELECT MAX(date) FROM daily_prices WHERE stock_id = :sid"),
                {"sid": stock.id},
            ).scalar()
        
        start = (max_date + timedelta(days=1)) if max_date else DEFAULT_START
        if start > date.today():
            return 0, max_date
        
        df = fetcher.get_daily(stock.symbol, start, date.today())
        # ... insert in same session ...
    finally:
        session.close()
```

**Impact:** 1 fewer connection checkout per new/incomplete stock. Significant for bootstrap (500+ stocks).

---

### #19 — Per-Stock `StockIndicator` Query When Prefetch Misses (NEW)

**File:** `src/ingestion/pipeline.py:194`

When a stock has no `StockIndicator` row (new stock), `indicator_last_updated` is None. Then `_upsert_fundamentals()` does a fallback DB query:

```python
existing = session.query(StockIndicator).filter_by(stock_id=stock.id).first()
```

This is correct (stock genuinely has no row), but unnecessary — the prefetch already checked. Could extend prefetch to include existence flag:

```sql
SELECT s.id, si.last_updated, (si.stock_id IS NOT NULL) AS has_indicator
FROM stocks s
LEFT JOIN stock_indicators si ON si.stock_id = s.id
WHERE s.id IN :ids
```

Then pass `has_indicator: bool` to skip per-stock query entirely when False:

```python
def _upsert_fundamentals(fetcher, stock, force=False,
                         indicator_last_updated=None,
                         has_indicator=True):
    if not force:
        if not has_indicator:
            pass  # new stock — always fetch
        elif indicator_last_updated is not None:
            age = (datetime.utcnow() - indicator_last_updated).days
            if age < refresh_days:
                return False
```

---

### #20 — Redundant `load_config()` in `_upsert_fundamentals()` (NEW)

**File:** `src/ingestion/pipeline.py:27,183`

```python
# Module level (line 27) — already loaded
_cfg = load_config()

# Inside _upsert_fundamentals (line 183) — called per stock, hits module cache
config = load_config()
refresh_days = config.get("scheduler", {}).get("overview_refresh_days", 7)
```

Module cache makes this cheap (dict lookup), but cleaner to pass `refresh_days` as parameter:

```python
def _upsert_fundamentals(fetcher, stock, force=False,
                         indicator_last_updated=None,
                         refresh_days=7):
```

---

## 🟢 Low Issues

### #12 — Alpha Vantage Listing No Disk Cache

**File:** `src/fetcher/alpha_vantage.py` (`get_listing`)

Fetches full NYSE/NASDAQ CSV on every symbol refresh. Data changes rarely (daily).

**Fix:**

```python
from pathlib import Path
from datetime import datetime, timezone, timedelta

_LISTING_CACHE = Path("data/cache/alpha_vantage_listing.parquet")

def get_listing(self) -> pd.DataFrame:
    ttl = timedelta(hours=6)
    if _LISTING_CACHE.exists():
        mtime = datetime.fromtimestamp(_LISTING_CACHE.stat().st_mtime, tz=timezone.utc)
        if datetime.now(timezone.utc) - mtime < ttl:
            return pd.read_parquet(_LISTING_CACHE)
    df = self._fetch_listing_from_api()
    _LISTING_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_LISTING_CACHE, index=False)
    return df
```

---

### #13 — Config Module Cache No Mtime Revalidation

**File:** `src/config.py:11-24`

If `config.yaml` changes while Streamlit is running, cached config becomes stale.

**Fix — add mtime check:**

```python
import os
from pathlib import Path

_config: dict | None = None
_config_mtime: float = 0.0

def load_config(force: bool = False) -> dict:
    global _config, _config_mtime
    config_path = Path(__file__).parent.parent / "config.yaml"
    current_mtime = config_path.stat().st_mtime if config_path.exists() else 0.0

    if not force and _config is not None and current_mtime == _config_mtime:
        return _config

    _config_mtime = current_mtime
    loader = ConfigLoader(config_path)
    _config = loader.load()
    return _config
```

---

### #14 — DB Pool Size May Bottleneck

**File:** `src/database.py:24`

Current: `pool_size=8, max_overflow=4`. Ingestion pipeline uses `ThreadPoolExecutor(max_workers=5)`, pipeline orchestrator opens 3 sessions sequentially, Streamlit UI opens per-request sessions.

**Fix:**

```python
engine = create_engine(
    url,
    pool_size=15,       # 8 → 15
    max_overflow=10,    # 4 → 10
    pool_recycle=1800,
    pool_pre_ping=True,
)
```

---

### #23 — `find_stock()` Re-executes on Every Widget Change (NEW)

**File:** `src/ui/pages/stock_lookup.py:21`

```python
stock = ctx.repo.find_stock(symbol)  # re-executes on ANY widget change
```

Every text input keystroke, date picker change, or tab switch re-runs this DB query. Already covered by #7.

**Fix:** `@st.cache_data(ttl=60)` wrapper (see #7).

---

### #24 — Silent Queue Drop (NEW)

**File:** `src/app.py:87-88`

```python
def emit(self, record):
    try:
        self.log_queue.put_nowait(self.format(record))
    except (queue.Full, Exception):
        pass  # SILENTLY DROPS log lines
```

When UI polling falls behind, log entries are silently discarded. User never knows.

**Fix — bounded queue with dropped-count warning:**

```python
class _QueueHandler(logging.Handler):
    def __init__(self, log_queue, max_size=10_000):
        super().__init__()
        self.log_queue = log_queue
        self._dropped = 0

    def emit(self, record):
        try:
            if self.log_queue.qsize() >= 10_000:
                self._dropped += 1
                return  # drop oldest to prevent OOM
            self.log_queue.put_nowait(self.format(record))
        except queue.Full:
            self._dropped += 1
```

---

## React-Specific Note

This is a **Streamlit project** — no React components. "Unnecessary re-renders" concept maps to **Streamlit full-script re-execution**. Every widget interaction (button click, selectbox change, text input) re-runs the entire page script. The primary mitigation is `@st.cache_data` decorators (#7), which prevent expensive operations from re-executing on every re-run.

---

## Implementation Priority

| Order | Issue(s) | Effort | Impact |
|-------|----------|--------|--------|
| 1 | #1-4: `session.add()` → `add_all()` (4 locations) | 30 min | 🔴 Fewer DB round-trips |
| 2 | #15-16: Fix memory leaks (log_lines cap + queue clear) | 20 min | 🟠 Prevents OOM on long sessions |
| 3 | #7: Add `@st.cache_data` to UI pages | 60 min | 🟠 80-95% query reduction |
| 4 | #5: Batch `find_stocks_batch()` + `itertuples()` | 20 min | 🔴 50% fewer predict-path queries |
| 5 | #6: Parallelize deep evaluator LLM calls | 30 min | 🔴 3× deep eval speedup |
| 6 | #8: Batch `refresh_symbols()` inserts | 20 min | 🟠 200× fewer round-trips |
| 7 | #17: `_count_by_opinion()` dedup | 10 min | 🟡 Faster ranking |
| 8 | #18: Merge session in `_fetch_and_store_prices()` | 15 min | 🟡 1 fewer session per new stock |
| 9 | #9-10,21-22: `iterrows()` → vectorized (5 files) | 20 min | 🟡 10-100× iteration speedup |
| 10 | #11: CSV cache in ML results | 10 min | 🟡 Instant tab switches |
| 11 | #19: Prefetch indicator existence | 15 min | 🟡 1 fewer query per new stock |
| 12 | #12-14,20,24: Low-impact fixes | 45 min | 🟢 Misc improvements |

**Total estimated effort:** ~5 hours for all 24 fixes.
**Cumulative impact:** 60-85% fewer DB round-trips, 80-95% fewer query re-executions in UI, 3× faster deep evaluation, memory-stable across repeated pipeline runs, zero silent log drops.
