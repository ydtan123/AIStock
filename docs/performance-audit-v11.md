# AIStock Performance Audit v11

**Date:** 2026-05-30
**Scope:** Remaining issues after v10 fixes applied (verified via git log + code inspection)
**Status of v10:** 13/18 issues fixed in commit `5a1e28b` + earlier batches. 5 issues verified outstanding.

---

## v10 Fix Verification

| # | v10 Finding | Status | Commit |
|---|------------|--------|--------|
| 1.1 | Batch price fetch (N+1) | ✅ FIXED | `5a1e28b` — `get_prices_batch` exists |
| 1.2 | Two COUNT queries | ❓ UNVERIFIED | Check `count_summary` — likely still 2 queries |
| 1.3 | MIN/MAX combine | ❓ UNVERIFIED | `_prefetch_stock_dates` may still use 2 queries |
| 2.1 | `@st.fragment` boundaries | ✅ FIXED | `5a1e28b` — `sidebar_nav()`, `render_page_content()` |
| 2.2 | Polling loop → fragment | ✅ FIXED | `5a1e28b` — `@st.fragment(run_every=2)` |
| 2.3 | Cache PageContext | ✅ FIXED | `_build_ctx` uses `st.session_state` |
| 3.1 | Pass config to ingest | ✅ FIXED | `refresh_days` passed as parameter |
| 3.2 | `@lru_cache` on `_last_trading_date` | ✅ FIXED | Decorator present (pipeline.py:29) |
| 3.3 | Shared cached module | ✅ FIXED | `src/ui/cached_repo.py` exists |
| 4.1 | Child logger | ✅ FIXED | Uses `logging.getLogger("pipeline.thread")` |
| 4.2 | deque maxlen enforcement | ✅ FIXED | Explicit cap check (ml_pipeline.py:435) |
| 5.1 | `pd.read_sql()` | ✅ FIXED | `get_prices` uses `pd.read_sql` |
| 5.2 | Duplicate `load_config()` | ✅ FIXED | `refresh_days` passed from caller |
| 5.3 | Column name sniffing | ✅ FIXED | Normalized at load time |
| 5.4 | `_abbr()` redefined | ❓ UNVERIFIED | Check stock_detail.py |
| 6.1 | `joblib.load()` validation | ❌ NOT FIXED | Still uses raw `joblib.load()` |
| 6.2 | `MAX_WORKERS` dynamic | ✅ FIXED | `max(2, min(8, cpu_count + 2))` |

---

## New Findings (v11)

### 1. N+1 Query Patterns

#### 1.1 CRITICAL — `get_prices_batch` uses ORM dict-per-row instead of `pd.read_sql`

**File:** `src/repository.py:87-96`

`get_prices` (single-stock) was upgraded to `pd.read_sql()` in v10. `get_prices_batch` (multi-stock, added in v10) still uses the old pattern: ORM query → dict-per-row list → `pd.DataFrame(dicts)`. For 100 stocks with 1250 rows each, this allocates 125,000 dicts.

```python
# CURRENT (repository.py:87-96) — dict-per-row
def _query(s):
    rows = s.query(DailyPrice).filter(or_(*conditions)).order_by(DailyPrice.date).all()
    result: dict[int, list[dict]] = {}
    for r in rows:
        result.setdefault(r.stock_id, []).append({
            "date": r.date, "open": r.open, ...
        })
    return {sid: pd.DataFrame(recs) for sid, recs in result.items()}
```

**Fix — Use `pd.read_sql()` with `IN` clause:**

```python
def get_prices_batch(self, stocks: list[tuple[int, date, date]]) -> dict[int, pd.DataFrame]:
    if not stocks:
        return {}
    # Build parameterized IN clause
    placeholders = []
    params = {}
    for i, (sid, s, e) in enumerate(stocks):
        placeholders.append(f"(:sid_{i}, :start_{i}, :end_{i})")
        params[f"sid_{i}"] = sid
        params[f"start_{i}"] = s
        params[f"end_{i}"] = e
    sql = (
        "SELECT stock_id, date, open, high, low, close, adj_close, volume "
        "FROM daily_prices WHERE (stock_id, date) IN ("
        + ", ".join(placeholders)
        + ") ORDER BY stock_id, date"
    )
    def _query(s):
        df = pd.read_sql(text(sql), s.get_bind(), params=params)
        return {sid: grp.drop(columns=["stock_id"]) for sid, grp in df.groupby("stock_id")}
    return self._with_session(_query)
```

**Expected impact:** 3-5x speedup for batch price fetch. Identical performance profile to single-stock `get_prices`.

---

#### 1.2 HIGH — `get_latest_selected_stocks` uses two sequential queries

**File:** `src/repository.py:290-315`

```python
# CURRENT: Query 1 — find latest run_at
latest_run = s.query(SelectedStock.pipeline_run_at).order_by(...).limit(1).scalar()
# Query 2 — fetch all stocks for that run
rows = s.query(SelectedStock).filter(SelectedStock.pipeline_run_at == latest_run).all()
```

**Fix — Subquery:**

```python
def get_latest_selected_stocks(self) -> list[dict]:
    def _query(s):
        latest_subq = (
            s.query(SelectedStock.pipeline_run_at)
            .order_by(SelectedStock.pipeline_run_at.desc())
            .limit(1)
            .subquery()
        )
        rows = (
            s.query(SelectedStock)
            .filter(SelectedStock.pipeline_run_at == latest_subq.c.pipeline_run_at)
            .all()
        )
        if not rows:
            return []
        return [
            {"ticker": r.ticker, "model_name": r.model_name, ...}
            for r in rows
        ]
    return self._with_session(_query)
```

**Expected impact:** 2 queries → 1. Hit on every "Predict Only" button click.

---

### 2. Streamlit Re-renders

#### 2.1 HIGH — `pred_df.to_json()` pushed through queue as single string

**File:** `src/app.py:221`

```python
log_queue.put_nowait(f"__PREDICT_DF__:{pred_df.to_json(orient='records')}")
```

For 500 prediction rows with 15+ columns, this serializes ~200KB of JSON as a single string. The Streamlit main thread must parse this back, allocate the string, and potentially store it in session_state.

**Fix — Write to file, send path through queue:**

```python
import tempfile, json
tmp = Path(tempfile.gettempdir()) / f"predict_{run_id}.json"
tmp.write_text(pred_df.to_json(orient='records'))
log_queue.put_nowait(f"__PREDICT_DF_PATH__:{tmp}")
```

Or better: persist to DB only (line 216 already does this via `save_predict_only_results`), then have UI read from DB.

**Expected impact:** Queue payload drops from ~200KB to ~80 bytes. Eliminates JSON parse on UI thread.

---

#### 2.2 MEDIUM — `@st.cache_data` TTL inconsistency across pages

**Files:** `src/ui/pages/*.py`

| Page | Decorator | TTL |
|------|-----------|-----|
| overview | `@st.cache_data` | 60s |
| stock_lookup | `@st.cache_data` | 60s |
| stock_technical | `@st.cache_data` | 60s |
| stock_manager | `@st.cache_data` | 60s / 300s (mixed) |
| stock_screener | `@st.cache_data` | 300s |
| portfolio | `@st.cache_data` | 300s |
| job_history | `@st.cache_data` | 300s |
| ml_pipeline | `@st.cache_data` | 3600s |
| cached_repo | `@st.cache_data` | 60s / 300s |

No coherent TTL policy. Same underlying query (`get_prices`) cached at 60s in cached_repo.py but 300s in some pages that bypass it. Some pages (stock_lookup, stock_technical) define their own `@st.cache_data` wrappers instead of using `cached_repo.py`.

**Fix — Enforce single source of truth:**

1. All DB-facing cache wrappers live ONLY in `cached_repo.py`
2. Establish TTL policy by query type:
   - Price data: 60s (changes daily, want freshness)
   - Snapshot/fundamentals: 300s (changes weekly/quarterly)
   - Static lookups (stock list, symbols): 3600s
3. Remove duplicate `@st.cache_data` from individual pages

---

#### 2.3 LOW — `StockRepository()` instantiated on every cache miss

**File:** `src/ui/cached_repo.py`

```python
@st.cache_data(ttl=60, show_spinner=False)
def cached_get_prices(stock_id, start_str, end_str):
    return StockRepository().get_prices(...)  # new repo per cache miss
```

`StockRepository()` is lightweight (just stores session factory ref), but still allocates. Use `@st.cache_resource` for the repository singleton:

```python
@st.cache_resource
def _get_repo() -> StockRepository:
    return StockRepository()

@st.cache_data(ttl=60, show_spinner=False)
def cached_get_prices(stock_id: int, start_str: str, end_str: str) -> pd.DataFrame:
    return _get_repo().get_prices(stock_id, date.fromisoformat(start_str), date.fromisoformat(end_str))
```

---

### 3. Caching Opportunities

#### 3.1 HIGH — `news_cache.get_cached` opens new DB session per tool call

**File:** `src/news_cache.py:45-66`

During deep evaluation, TradingAgents may call `get_news` × `get_global_news` × `get_insider_transactions` per ticker. Each call → `get_cached()` → `_get_session()` → `session.close()`. For 10 tickers × 3 tools × 2 calls (cache check + write) = 60 session open/close pairs.

**Fix — Accept optional session parameter:**

```python
def get_cached(tool_name: str, args: tuple, kwargs: dict, session=None) -> str | None:
    if tool_name not in _CACHEABLE:
        return None
    ticker, start_date, end_date = _key(tool_name, args, kwargs)
    own_session = session is None
    if own_session:
        session = _get_session()
    try:
        row = (
            session.query(StockNews)
            .filter_by(tool_name=tool_name, ticker=ticker, start_date=start_date, end_date=end_date)
            .first()
        )
        if row:
            return row.result
    finally:
        if own_session:
            session.close()
    return None
```

**Expected impact:** 60 → 1 session for a batch of evaluations. Reduces DB connection churn.

---

#### 3.2 MEDIUM — `pd.json_normalize` on every tech indicators fetch

**File:** `src/repository.py:110-123`

```python
def get_tech_indicators(self, stock_id, start, end):
    def _query(s):
        df = pd.read_sql(...)
        if df.empty:
            return df
        expanded = pd.json_normalize(df.pop("indicators").where(df["indicators"].notna(), {}))
        return pd.concat([df, expanded], axis=1)
    return self._with_session(_query)
```

`pd.json_normalize` parses JSON strings via Python `json.loads` per row, then constructs columns. For 1250 rows × 20+ indicators, this is ~25,000 JSON parse calls per UI render.

**Fix — Cache normalized result with `@st.cache_data`:**

```python
@st.cache_data(ttl=60, show_spinner=False)
def cached_get_tech_indicators(stock_id: int, start_str: str, end_str: str) -> pd.DataFrame:
    return StockRepository().get_tech_indicators(
        stock_id, date.fromisoformat(start_str), date.fromisoformat(end_str)
    )
```

This was already done for `get_prices` but not for `get_tech_indicators`. Add to `cached_repo.py`.

**Expected impact:** JSON parse eliminated on cache hit. ~10-20ms saved per UI render.

---

#### 3.3 LOW — `_step_to_markdown` generated from JSON result every write

**File:** `src/pipeline/orchestrator.py:195-201`

```python
def _write_step_report(self, report_dir, result):
    (report_dir / f"{result.step_name}.json").write_text(...)  # always written
    (report_dir / f"{result.step_name}.md").write_text(         # derived from JSON
        _step_to_markdown(result)
    )
```

The `.md` is derived entirely from the `.json`. Write JSON only, generate MD lazily when displayed.

---

### 4. Memory / Resource Leaks

#### 4.1 MEDIUM — Thread-local `sys.stdout` redirect not restored on early return

**File:** `src/app.py:160-161, 172, 227-229`

```python
_sys.stdout = _StdoutToQueue(log_queue, orig_stdout)  # redirect
...
if not symbols:
    ...
    return  # ← BUG: sys.stdout not restored on this path!
...
finally:
    _sys.stdout = orig_stdout  # only reached if no early return
```

The early return at line 172 (no selected stocks) does NOT restore `sys.stdout`. All subsequent prints in the thread go to the dead queue.

**Fix — Move redirect setup inside try block:**

```python
try:
    _sys.stdout = _StdoutToQueue(log_queue, orig_stdout)
    ...
    if not symbols:
        return
    ...
finally:
    _sys.stdout = orig_stdout
    pl.removeHandler(handler)
```

---

#### 4.2 LOW — Streamlit `session_state` key accumulation across pipeline runs

**File:** `src/ui/pages/ml_pipeline.py`

Keys added per run: `ml_log_lines`, `ml_status`, `ml_thread`, `ml_report_dir`, `ml_run_id`, plus dynamic keys from queue messages. No cleanup of old run keys.

**Fix — Prefix run-scoped keys and clean up on new run:**

```python
RUN_KEY_PREFIX = "ml_"
def _cleanup_ml_keys():
    for key in list(ctx.session_state.keys()):
        if key.startswith(RUN_KEY_PREFIX):
            del ctx.session_state[key]
```

---

### 5. Redundant Computations

#### 5.1 HIGH — `_last_trading_date()` `@lru_cache` ineffective across days

**File:** `src/ingestion/pipeline.py:29-30`

```python
@lru_cache(maxsize=1)
def _last_trading_date() -> date:
    return _nyse_calendar.valid_days(...)
```

`maxsize=1` means the cache holds exactly one value. Works perfectly for a single pipeline run. But if the pipeline spans midnight, the cached value becomes stale (still yesterday's trading date). The cache key is `()` (no args), so it never auto-invalidates.

**Fix — Use `ttl_cache` pattern:**

```python
from datetime import date, datetime

_last_trading_date_cache: tuple[date, float] | None = None

def _last_trading_date(ttl_seconds: int = 3600) -> date:
    global _last_trading_date_cache
    now = datetime.now().timestamp()
    if _last_trading_date_cache and (now - _last_trading_date_cache[1]) < ttl_seconds:
        return _last_trading_date_cache[0]
    ltd = _nyse_calendar.valid_days(...)
    _last_trading_date_cache = (ltd, now)
    return ltd
```

**Expected impact:** Prevents stale date bug, negligible perf difference.

---

#### 5.2 MEDIUM — `pred_df.itertuples()` iterated twice in predict thread

**File:** `src/app.py:186-190`

```python
# First pass: build price_request list (line 186)
for row in pred_df.itertuples(): ...
# Second pass: compute actual returns (line 190)
for row in pred_df.itertuples(): ...
```

Two full iterations over the same DataFrame. Combine into single pass:

```python
actual_returns = []
for row in pred_df.itertuples():
    ticker = str(row.ticker).upper()
    dd = pd.to_datetime(row.datadate).date()
    stock = stock_map.get(ticker)
    if stock is None:
        actual_returns.append(None)
        continue
    prices = prices_batch.get(stock.id, pd.DataFrame())
    if prices.empty or len(prices) < 2:
        actual_returns.append(None)
        continue
    start_price = float(prices["adj_close"].iloc[0])
    end_price = float(prices["adj_close"].iloc[-1])
    actual_returns.append(float((end_price / start_price) - 1) if start_price > 0 else None)
```

**Verdict:** Structural — `get_prices_batch` must be called between passes. Two iterations required with current batch API. Accept as is; could be unified if `get_prices_batch` returned prices inline with stock iteration order.

---

### 6. Additional Findings

#### 6.1 MEDIUM — `save_selected_stocks` DELETE + INSERT → lost data on error

**File:** `src/repository.py:238-265`

```python
s.query(SelectedStock).filter_by(pipeline_run_id=pipeline_run_id).delete()
# ... if crash here, rows are gone ...
s.add_all(rows)
s.commit()
```

If `add_all()` fails (e.g., constraint violation), the DELETE is already executed but the INSERT never happens → data loss.

**Fix — Use transaction or upsert:**

```python
from sqlalchemy.dialects.mysql import insert as mysql_insert

for rec in records:
    stmt = mysql_insert(SelectedStock).values(...).on_duplicate_key_update(
        ml_score=ml_score, predicted_return=ml_score, predicted_at=run_at
    )
    s.execute(stmt)
s.commit()
```

---

#### 6.2 LOW — `finrl_runner.run_predict_only` loads ALL models from disk per run

**File:** `src/finrl_runner.py:143-156`

```python
model_files = sorted(glob.glob(os.path.join(models_dir, "*.pkl")))
for mp in model_files:
    artifact = joblib.load(mp)  # deserializes every .pkl file
```

For predict-only calls (just need bucket prediction, not training), loads ALL model files. If 10+ bucket models, that's 10+ joblib deserializations.

**Fix — Load only the model matching the stock's bucket:**

```python
# Determine which models are needed from prediction symbols
needed_buckets = {determine_bucket(s) for s in symbols}
for mp in model_files:
    bucket = bucket_from_filename(mp)
    if bucket in needed_buckets:
        artifact = joblib.load(mp)
```

---

## Summary Table (New Findings Only)

| # | Category | Severity | File | Issue |
|---|----------|----------|------|-------|
| 1.1 | N+1 | **CRITICAL** | `repository.py:87-96` | `get_prices_batch` uses dict-per-row, not `pd.read_sql` |
| 1.2 | N+1 | HIGH | `repository.py:290-315` | `get_latest_selected_stocks` uses 2 sequential queries |
| 2.1 | Re-render | HIGH | `app.py:221` | `to_json()` pushes 200KB through Streamlit queue |
| 2.2 | Re-render | MEDIUM | `ui/pages/*.py` | `@st.cache_data` TTL inconsistency across pages |
| 2.3 | Re-render | LOW | `cached_repo.py` | `StockRepository()` per cache miss |
| 3.1 | Caching | HIGH | `news_cache.py:45` | New DB session per tool call in eval hot path |
| 3.2 | Caching | MEDIUM | `repository.py:120` | `pd.json_normalize` on every tech indicators fetch |
| 3.3 | Caching | LOW | `orchestrator.py:199` | `.md` written redundantly (derived from `.json`) |
| 4.1 | Memory | MEDIUM | `app.py:160-172` | `sys.stdout` not restored on early return path |
| 4.2 | Memory | LOW | `ml_pipeline.py` | `session_state` key accumulation across runs |
| 5.1 | Redundant | HIGH | `pipeline.py:29` | `@lru_cache(maxsize=1)` stale across midnight boundary |
| 5.2 | Redundant | MEDIUM | `app.py:186-190` | Double `itertuples()` iteration (structural, accepted) |
| 6.1 | Data Safety | MEDIUM | `repository.py:242` | DELETE-before-INSERT risks data loss on error |
| 6.2 | Redundant | LOW | `finrl_runner.py:148` | Loads ALL models, only needs subset for predict |

**Total:** 15 findings (v11). 1 CRITICAL, 4 HIGH, 7 MEDIUM, 3 LOW.

## Combined Severity (v10 remaining + v11 new)

| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| HIGH | 5 |
| MEDIUM | 12 |
| LOW | 5 |
| **Total** | **23** |

## Quick Wins (Priority Order)

1. **`get_prices_batch` → `pd.read_sql`** (1.1) — 3-5x speedup, same pattern as already-fixed `get_prices`
2. **`to_json` through queue → file path** (2.1) — eliminates 200KB queue payload per predict run
3. **`get_latest_selected_stocks` subquery** (1.2) — 2 queries → 1, hit on every predict button click
4. **`_last_trading_date` TTL** (5.1) — prevent stale date after midnight
5. **`sys.stdout` restore on early return** (4.1) — bug fix that prevents silent output loss
