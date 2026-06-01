# AIStock Performance Analysis — Comprehensive v3

**Date:** 2026-05-30  
**Scope:** Python/Streamlit/MySQL stack. All findings verified against current `main` at `0fe4a40`.  
**Methodology:** Static analysis of all source files, cross-referenced with prior audit findings.  
**Note:** This is a Streamlit project. No React components exist. "Re-render" = full-script re-execution.

---

## Summary

| Severity | Count | Categories |
|----------|-------|------------|
| 🔴 CRITICAL | 6 | N+1 queries, serial I/O |
| 🟠 HIGH | 2 | Missing caching, per-row inserts |
| 🟡 MEDIUM | 3 | Pandas antipatterns, redundant I/O |
| 🟢 LOW | 5 | Disk caching, config, DB pool, module-level side effects |

---

## 🔴 CRITICAL Issues

### #1 — Per-Row `session.add()` in FastEvaluationStep Nested Loop

**File:** `src/pipeline/fast_evaluation.py:82-113`  
**Impact:** For N tickers with M analysts each: `N + N*M` individual `session.add()` calls. With 10 tickers and 5 analysts: 60 individual INSERTs. Each triggers ORM identity-map lookup and flush overhead.

```python
# CURRENT (lines 82-113)
for ev in evaluations:
    session.add(FastEvaluationConclusion(...))   # 1 per ticker
    for op in ev.opinions:
        session.add(FastEvaluationAnalyst(...))   # 1 per analyst per ticker
session.commit()
```

**Fix — Batch `session.add_all()`:**

```python
conclusions = []
analysts = []
for ev in evaluations:
    pos, neg, neu = _count_by_opinion(ev.opinions)
    total = pos + neg + neu
    now = dt.datetime.now()
    conclusions.append(FastEvaluationConclusion(
        pipeline_run_id=ctx.run_id,
        ticker=ev.ticker,
        backend=backend_name,
        start_date=dt.date.fromisoformat(ev.start_date),
        end_date=dt.date.fromisoformat(ev.end_date),
        model_name=evaluator_cfg.get("model_name", ""),
        model_provider=evaluator_cfg.get("model_provider", ""),
        positive_count=pos,
        negative_count=neg,
        neutral_count=neu,
        total_count=total,
        consensus_score=ev.consensus_score,
    ))
    for op in ev.opinions:
        analysts.append(FastEvaluationAnalyst(
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
session.add_all(analysts)
session.commit()
```

**Expected gain:** ~5-10× faster for typical top_n=10 with 5 analysts.

---

### #2 — Per-Row `session.add()` in DeepEvaluationStep

**File:** `src/pipeline/deep_evaluation.py:71-90`  
**Impact:** Same pattern as #1. N individual `session.add()` calls.

```python
# CURRENT (lines 71-90)
with open_session(ctx) as session:
    for ev in evaluations:
        slot_kwargs = {slot: ev.agent_outputs.get(slot) for slot in _NAMED_SLOTS}
        eval_date = ...
        row = DeepEvaluationRow(...)
        session.add(row)
    session.commit()
```

**Fix — Batch `session.add_all()`:**

```python
with open_session(ctx) as session:
    rows = []
    for ev in evaluations:
        slot_kwargs = {slot: ev.agent_outputs.get(slot) for slot in _NAMED_SLOTS}
        eval_date = (
            dt.datetime.fromisoformat(ev.evaluation_date)
            if "T" in ev.evaluation_date
            else dt.datetime.strptime(ev.evaluation_date, "%Y-%m-%d")
        )
        rows.append(DeepEvaluationRow(
            pipeline_run_id=ctx.run_id,
            ticker=ev.ticker,
            evaluation_date=eval_date,
            extra_outputs=ev.extra_outputs,
            final_decision=ev.final_decision,
            model_name=evaluator_cfg.get("model_name"),
            **slot_kwargs,
        ))
    session.add_all(rows)
    session.commit()
```

**Expected gain:** ~3-5× faster for typical top_n=3.

---

### #3 — Per-Row `s.add()` in `save_selected_stocks()`

**File:** `src/repository.py:211-239`  
**Impact:** N individual ORM INSERTs. With 100-500 stocks selected: significant overhead.

```python
# CURRENT (lines 220-236)
for rec in records:
    row = SelectedStock(...)
    s.add(row)
    inserted += 1
s.commit()
```

**Fix — `bulk_insert_mappings`:**

```python
rows = []
run_at = datetime.now()
for rec in records:
    ml_score = float(rec.get("ml_score", 0))
    rows.append(dict(
        ticker=rec["ticker"],
        model_name=rec.get("model_name", ""),
        ml_score=ml_score,
        bucket=rec.get("bucket"),
        weight=float(rec["weight"]) if rec.get("weight") is not None else None,
        date_selected=rec.get("date_selected", date.today()),
        model_file=rec.get("model_file"),
        pipeline_run_at=run_at,
        predicted_return=ml_score,
        predicted_at=run_at,
        pipeline_run_id=pipeline_run_id,
    ))
s.bulk_insert_mappings(SelectedStock, rows)
s.commit()
```

**Expected gain:** ~3-8× faster for 500 stocks.

---

### #4 — Per-Row `s.add()` in `save_predict_only_results()`

**File:** `src/repository.py:241-263`  
**Impact:** Same as #3. Same fix: `bulk_insert_mappings`.

---

### #5 — Per-Ticker `find_stock()` + `get_prices()` in Predict-Only Pipeline

**File:** `src/app.py:175-190`  
**Impact:** Each ticker opens 2 separate DB sessions (each `_with_session` call opens + closes). For 100 stocks: 200 session open/close cycles + 200 queries.

```python
# CURRENT (lines 175-190)
for _, row in pred_df.iterrows():
    ticker = row["ticker"]
    dd = _pd.to_datetime(row["datadate"]).date()
    stock = _repo.find_stock(str(ticker))      # 1 session
    if stock is None:
        actual_returns.append(None)
        continue
    prices = _repo.get_prices(stock.id, dd, _date.today())  # 2nd session
    ...
```

**Fix — Add batch methods to StockRepository:**

```python
# In src/repository.py:
def find_stocks_batch(self, symbols: list[str]) -> dict[str, Stock]:
    """Return {symbol: Stock} for all given symbols in one query."""
    def _query(s):
        rows = s.query(Stock).filter(
            Stock.symbol.in_([x.upper() for x in symbols])
        ).all()
        return {r.symbol: r for r in rows}
    return self._with_session(_query)

def get_prices_batch(
    self, stock_ids: list[int], start: date, end: date
) -> dict[int, pd.DataFrame]:
    """Return {stock_id: DataFrame} for all stock_ids in one query."""
    def _query(s):
        rows = (
            s.query(DailyPrice)
            .filter(
                DailyPrice.stock_id.in_(stock_ids),
                DailyPrice.date >= start,
                DailyPrice.date <= end,
            )
            .order_by(DailyPrice.date)
            .all()
        )
        result: dict[int, list[dict]] = {}
        for r in rows:
            result.setdefault(r.stock_id, []).append({
                "date": r.date, "adj_close": r.adj_close,
            })
        return {sid: pd.DataFrame(recs) for sid, recs in result.items()}
    return self._with_session(_query)
```

Then in app.py predict-only section:

```python
_repo = StockRepository()
tickers = [str(row.ticker).upper() for row in pred_df.itertuples()]
stocks = _repo.find_stocks_batch(tickers)
stock_ids = [s.id for s in stocks.values() if s is not None]
min_date = pred_df["datadate"].min().date()
all_prices = _repo.get_prices_batch(stock_ids, min_date, _date.today())

actual_returns = []
for row in pred_df.itertuples():
    stock = stocks.get(str(row.ticker).upper())
    if stock is None:
        actual_returns.append(None)
        continue
    prices = all_prices.get(stock.id)
    if prices is None or prices.empty or len(prices) < 2:
        actual_returns.append(None)
        continue
    start_price = float(prices["adj_close"].iloc[0])
    end_price = float(prices["adj_close"].iloc[-1])
    actual_returns.append(
        float(end_price / start_price - 1) if start_price > 0 else None
    )
```

**Expected gain:** 200 DB sessions → 2 sessions. ~50-100× reduction in session overhead.

---

### #6 — Sequential LLM Calls in Deep Evaluator

**File:** `src/pipeline/backends/deep_evaluators.py:148-179`  
**Impact:** Each ticker's `graph.propagate()` is a blocking LLM call (multiple debate rounds). With 3 tickers at 60s each: 3 minutes total. Calls are independent — parallelism cuts to ~60s.

```python
# CURRENT (lines 147-179)
out: list[DeepEvaluation] = []
for ticker in tickers:
    ctx.logger.info("TradingAgents evaluating %s on %s", ticker, eval_date)
    try:
        result = graph.propagate(ticker, eval_date)
    except Exception as e:
        ctx.logger.exception("TradingAgents failed for %s: %s", ticker, e)
        continue
    ...
```

**Fix — ThreadPoolExecutor for parallel LLM calls:**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

_lock = threading.Lock()

def _eval_one(ticker: str) -> DeepEvaluation | None:
    try:
        result = graph.propagate(ticker, eval_date)
    except Exception as e:
        with _lock:
            ctx.logger.exception("TradingAgents failed for %s: %s", ticker, e)
        return None

    if isinstance(result, tuple) and len(result) == 2:
        final_state, decision = result
    else:
        final_state, decision = result, None

    agent_outputs: dict[str, str] = {}
    extras: dict[str, Any] = {}
    for src_key, value in (final_state or {}).items():
        slot = _FINAL_STATE_TO_SLOT.get(src_key)
        if slot:
            agent_outputs[slot] = value if isinstance(value, str) else str(value)
        elif src_key != "messages" and (
            isinstance(value, (str, int, float, bool)) or value is None
        ):
            extras[src_key] = value

    return DeepEvaluation(
        ticker=ticker,
        evaluation_date=eval_date,
        agent_outputs=agent_outputs,
        extra_outputs=extras,
        final_decision=_extract_decision(final_state, decision),
    )

max_workers = min(len(tickers), 3)
out: list[DeepEvaluation] = []
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(_eval_one, t): t for t in tickers}
    for future in as_completed(futures):
        result = future.result()
        if result is not None:
            out.append(result)

# Preserve original ticker order
ticker_order = {t: i for i, t in enumerate(tickers)}
out.sort(key=lambda e: ticker_order.get(e.ticker, 999))
```

**Expected gain:** ~3× speedup for 3 tickers (3 min → 1 min). Proportional to ticker count. Cap workers at 3 to respect API rate limits.

---

## 🟠 HIGH Issues

### #7 — Zero `@st.cache_data` Decorators Across All UI Pages

**Files:** `src/ui/pages/*.py` (13 files)  
**Impact:** Every DB query re-executes on every widget interaction (button click, selectbox change, tab switch). Streamlit default: full script re-execution per user event.

| Page | Function | What re-queries every interaction |
|------|----------|-----------------------------------|
| `stock_lookup.py` | Lookup dialog | `_repo.find_stock()`, `_repo.get_indicator()` |
| `stock_screener.py` | Screener filters | `_repo.screen_stocks()` |
| `stock_manager.py` | Stock list | `_repo.list_stocks()` |
| `stock_technical.py` | Technical charts | `_repo.get_prices()`, `_repo.get_tech_indicators()` |
| `overview.py` | Dashboard stats | `_repo.count_summary()`, `_repo.get_sectors()` |
| `job_history.py` | Job status | `_repo.get_job_runs()` |
| `ml_pipeline.py` | ML results | `pd.read_csv()` × 3-5, JSON load |
| `portfolio.py` | Portfolio | `_repo.get_latest_selected_stocks()` |

**Fix — add `@st.cache_data`:**

```python
import streamlit as st

# stock_lookup.py
@st.cache_data(ttl=300, show_spinner=False)
def _cached_find_stock(symbol: str) -> dict | None:
    stock = StockRepository().find_stock(symbol)
    if stock is None:
        return None
    return {
        "id": stock.id, "symbol": stock.symbol, "name": stock.name,
        "sector": stock.sector, "exchange": stock.exchange,
        "industry": stock.industry, "is_active": stock.is_active,
    }

# overview.py
@st.cache_data(ttl=60)
def _cached_count_summary() -> dict:
    return StockRepository().count_summary()

# ml_pipeline.py
@st.cache_data(ttl=300)
def _cached_read_weights() -> pd.DataFrame | None:
    for candidate in ["ml_weights_sector.csv", "ml_weights_today.csv"]:
        p = DATA_DIR / candidate
        if p.exists():
            return pd.read_csv(p)
    return None
```

**Impact:** DB queries drop from N-per-widget-interaction to 1 per TTL window. Expected query reduction: 80-95% for typical 5-minute session.

---

### #8 — Per-Row `session.execute()` in `refresh_symbols()`

**File:** `src/ingestion/symbols.py:40-59`  
**Impact:** 8000+ individual SQL INSERT ... ON DUPLICATE KEY UPDATE statements for NYSE+NASDAQ symbols.

```python
# CURRENT (lines 40-50)
for _, row in df.iterrows():
    stmt = insert(Stock).values(symbol=row["symbol"], ...).on_duplicate_key_update(...)
    session.execute(stmt)
    count += 1
session.commit()
```

**Fix — Chunked bulk insert:**

```python
CHUNK_SIZE = 500
records = []
for _, row in df.iterrows():
    records.append(dict(
        symbol=row["symbol"], name=name,
        asset_type=asset_type, exchange=exchange, is_active=False,
    ))

for i in range(0, len(records), CHUNK_SIZE):
    chunk = records[i:i + CHUNK_SIZE]
    stmt = insert(Stock).values(chunk)
    stmt = stmt.on_duplicate_key_update(
        name=stmt.inserted.name,
        asset_type=stmt.inserted.asset_type,
        exchange=stmt.inserted.exchange,
    )
    session.execute(stmt)
session.commit()
```

**Expected gain:** ~20-50× faster. 8000 individual → ~16 bulk statements.

---

## 🟡 MEDIUM Issues

### #9 — `iterrows()` in Predict-Only Pipeline

**File:** `src/app.py:175`  
**Impact:** `iterrows()` allocates a Series per row (heap allocation + dtype boxing). ~50-100ms for 500+ rows.

**Fix — `itertuples()`:**

```python
for row in pred_df.itertuples():
    ticker = str(row.ticker).upper()
    dd = row.datadate.date()  # already datetime if parsed
    # ... rest unchanged
```

Combine with batch lookup (#5) for maximum gain. `itertuples()` is 10-100× faster than `iterrows()`.

---

### #10 — `iterrows()` in Price Data Ingestion

**File:** `src/ingestion/pipeline.py:126-138`  
**Impact:** 125K Series allocations during full backfill (500 stocks × 250 days).

```python
# CURRENT
values = []
for _, row in df.iterrows():
    values.append({"stock_id": stock.id, "date": row["date"], ...})
```

**Fix — Vectorized `to_dict(orient="records")`:**

```python
COLUMNS = ["date", "open", "high", "low", "close", "adj_close",
           "volume", "dividend_amount", "split_coefficient"]
df_clean = df[COLUMNS].copy()
df_clean["stock_id"] = stock.id
df_clean = df_clean.where(df_clean.notna(), other=None)
values = df_clean.to_dict(orient="records")
```

**Expected gain:** ~10-50× faster for full backfill.

---

### #11 — Repeated CSV Reads in ML Results Display

**File:** `src/ui/pages/ml_pipeline.py`  
**Impact:** Multiple `pd.read_csv()` on same files during single page render. Each re-parses full CSV.

**Fix — Cache via `@st.cache_data`:**

```python
@st.cache_data(ttl=300)
def _load_ml_weights() -> pd.DataFrame | None:
    for candidate in ["ml_weights_sector.csv", "ml_weights_today.csv"]:
        p = DATA_DIR / candidate
        if p.exists():
            df = pd.read_csv(p)
            df.columns = [c.strip().lower() for c in df.columns]
            return df
    return None

@st.cache_data(ttl=600)
def _load_fundamentals() -> tuple[pd.DataFrame | None, str | None, str | None]:
    fund_path = DATA_DIR / "fundamentals.csv"
    if not fund_path.exists():
        return None, None, None
    fdf = pd.read_csv(fund_path)
    fdf.columns = [c.strip().lower() for c in fdf.columns]
    s_col = next((c for c in ["sector", "gsector"] if c in fdf.columns), None)
    t_col = next((c for c in ["tic", "ticker"] if c in fdf.columns), None)
    return fdf, s_col, t_col
```

---

## 🟢 LOW Issues

### #12 — Alpha Vantage Listing No Disk Cache

**File:** `src/fetcher/alpha_vantage.py`  
**Impact:** `get_listing()` re-downloads 8000+ symbol CSV on every data update. AV rate limit: 5 calls/min.

**Fix — Disk cache with 24h TTL:**

```python
import json
from pathlib import Path

_LISTING_CACHE = Path("data/av_listing_cache.json")
_LISTING_CACHE_TTL = 86400  # 24 hours

def get_listing(self, use_cache: bool = True) -> pd.DataFrame:
    if use_cache and _LISTING_CACHE.exists():
        age = time.time() - _LISTING_CACHE.stat().st_mtime
        if age < _LISTING_CACHE_TTL:
            with open(_LISTING_CACHE) as f:
                return pd.DataFrame(json.load(f))
    # ... existing download logic ...
    if use_cache:
        _LISTING_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(_LISTING_CACHE, "w") as f:
            json.dump(df.to_dict(orient="records"), f)
    return df
```

---

### #13 — Config Module Cache No Mtime Revalidation

**File:** `src/config.py:6-26`  
**Impact:** If `config.yaml` changes while process is running, cached config never refreshed.

**Fix — Add mtime check:**

```python
_config: dict | None = None
_config_mtime: float = 0.0

def load_config(force_reload: bool = False) -> dict:
    global _config, _config_mtime
    config_path = Path(__file__).parent.parent / "config.yaml"
    if not config_path.exists():
        print("config.yaml not found.", file=sys.stderr)
        sys.exit(1)
    current_mtime = config_path.stat().st_mtime
    if not force_reload and _config is not None and current_mtime == _config_mtime:
        return _config
    loader = ConfigLoader(config_path)
    _config = loader.load()
    _config_mtime = current_mtime
    return _config
```

---

### #14 — DB Pool Size May Bottleneck Under Parallelism

**File:** `src/database.py:24`  
**Current:** `pool_size=8, max_overflow=4` = 12 max connections.  
**Risk:** ThreadPoolExecutor with 3 workers (deep eval) + 5 UI page renders = potential exhaustion.

**Fix:**

```python
# From:
_engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600, pool_size=8, max_overflow=4)

# To:
_engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600, pool_size=15, max_overflow=10)
```

---

### #15 — `_with_session()` Opens/Closes Per Call

**File:** `src/repository.py:43-49`  
**Impact:** Each `find_stock()`, `get_prices()` does open → query → close. In loops: 200 session open/close cycles for 100 stocks.

**Fix — Add batch session context manager:**

```python
from contextlib import contextmanager

class StockRepository:
    @contextmanager
    def batch_session(self):
        """Reuse one session for multi-query operations."""
        session = self._get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

Usage in predict-only section:

```python
_repo = StockRepository()
with _repo.batch_session() as s:
    stocks = {r.symbol: r for r in s.query(Stock).filter(
        Stock.symbol.in_(tickers)).all()}
    # ... more queries on same session
```

---

### #16 — `sys.path` Global Mutation Per Call

**File:** `src/pipeline/backends/fast_evaluators.py:59-62`  
**Impact:** `_ensure_ai_hedge_fund_path()` does list contains + insert check on every evaluator call. Minor perf cost. Correctness hazard: path order drift over time.

**Fix — Move to module level:**

```python
# At module import time (replace _ensure function entirely):
if str(_AI_HEDGE_FUND_PATH) not in sys.path:
    sys.path.insert(0, str(_AI_HEDGE_FUND_PATH))

def _call_run_hedge_fund(**kwargs):
    from src.main import run_hedge_fund
    return run_hedge_fund(**kwargs)
```

---

## Memory Leak Analysis

No classical memory leaks found. Session lifecycle is well-managed with `try/finally` in `_with_session()`. Global state is intentional per-module singletons (config cache, engine, session factory).

**Potential concern — `messages` objects in deep evaluator:**
`src/pipeline/backends/deep_evaluators.py:168-169` explicitly discards `messages` key from LangChain graph state (`pass`). These are non-serializable message objects. They are garbage-collected after `evaluate()` returns since no reference is retained. Not a leak.

---

## Redundant Computation

| Location | Redundancy | Fix |
|----------|------------|-----|
| `app.py:175-193` | Per-ticker `_repo` calls when batch query would work | Batch methods (#5) |
| `ui/pages/ml_pipeline.py` | `pd.read_csv()` × N on same file | `@st.cache_data` (#11) |
| `ui/pages/*.py` | DB queries re-execute on every widget event | `@st.cache_data` (#7) |
| `pipeline/fast_evaluation.py` | Per-row ORM `.add()` vs `.add_all()` | Batch (#1) |
| `pipeline/deep_evaluation.py` | Per-row ORM `.add()` vs `.add_all()` | Batch (#2) |
| `ingestion/symbols.py` | 8000 individual INSERTs vs bulk | Bulk (#8) |
| `ingestion/pipeline.py` | `iterrows()` for DataFrame→dict | `to_dict(orient="records")` (#10) |

---

## Implementation Priority

| Order | Issue # | Effort | Impact | Risk |
|-------|---------|--------|--------|------|
| 1 | #7 (cache_data) | 2h | High | Low |
| 2 | #1, #2 (batch add_all) | 1h | High | Low |
| 3 | #3, #4 (bulk insert) | 30min | Medium | Low |
| 4 | #5 (batch lookup) | 1h | High | Medium |
| 5 | #10 (vectorized to_dict) | 15min | High | Low |
| 6 | #8 (batch symbol refresh) | 30min | Medium | Low |
| 7 | #6 (parallel deep eval) | 1h | High | Medium |
| 8 | #11 (cache CSV) | 30min | Medium | Low |
| 9 | #9 (itertuples) | 10min | Low | None |
| 10 | #12 (AV disk cache) | 30min | Medium | Low |
| 11 | #13 (config mtime) | 15min | Low | Low |
| 12 | #14 (DB pool) | 5min | Low | None |
| 13 | #15 (batch session) | 1h | Medium | Medium |
| 14 | #16 (sys.path cleanup) | 5min | Low | None |

**Total estimated effort:** ~9 hours for all issues.  
**Quick wins (under 1 hour):** #1, #2, #3, #4, #10, #16 deliver most impact per effort.

---

## Verification Checklist

- [ ] `PYTHONPATH=src python src/full_pipeline.py` completes without errors
- [ ] `PYTHONPATH=src pytest tests/ -v` all pass
- [ ] Streamlit app loads all pages without errors
- [ ] `@st.cache_data` prevents re-queries on widget interaction (verify via DB query log)
- [ ] Pipeline run with `--set fast_evaluation.top_n=10 --set deep_evaluation.top_n=3` produces valid report
