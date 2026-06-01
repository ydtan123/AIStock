# AIStock Performance Analysis v5 — 2026-05-30

Python/Streamlit codebase. No React — "re-render" analysis covers Streamlit reruns.

---

## Severity Legend

| Level | Meaning |
|-------|---------|
| 🔴 **Critical** | Blocks UI, user-visible latency >5s, risk of OOM |
| 🟠 **High** | Noticeable slowdown, wasted compute per re-render |
| 🟡 **Medium** | Suboptimal pattern, pays off at scale |
| 🟢 **Low** | Minor, fix opportunistically |

---

## 1. N+1 Query Patterns

### 🔴 N+1: Stock name lookup per ticker in ML results

`src/ui/pages/ml_pipeline.py:58-66` — `find_stock()` called in loop for every ticker in weights:

```python
_repo = StockRepository()
for sym in wdf[ticker_col].dropna().unique():
    stock = _repo.find_stock(str(sym))    # N+1 — one DB session per ticker
    name_map[sym] = stock.name if stock else ""
```

**Impact**: 50 selected stocks = 50 separate DB sessions (`_with_session` opens+closes per call).  
**Fix**: Add bulk query to repository.

```python
# src/repository.py — new method
def find_stocks_bulk(self, symbols: list[str]) -> dict[str, Optional[Stock]]:
    def _query(s):
        stocks = s.query(Stock).filter(
            Stock.symbol.in_([sym.upper() for sym in symbols])
        ).all()
        return {st.symbol: st for st in stocks}
    return self._with_session(_query)

# src/ui/pages/ml_pipeline.py — call once
name_map = {}
for sym in wdf[ticker_col].dropna().unique():
    name_map[sym] = bulk.get(sym.upper(), None)
```

### 🟠 N+1: benchmark price fetch in backtest

`src/finrl_runner.py:308-325` — per-benchmark `get_price_data()` in loop. Each triggers external data fetch.

```python
for bm in benchmarks:
    bm_prices = data_source.get_price_data(bm_df, start_date, end_date)
```

**Fix**: Parallelize benchmarks with `ThreadPoolExecutor` for I/O-bound fetches.

---

## 2. Missing Streamlit Cache Decorators

**Status**: Zero `@st.cache_data` or `@st.cache_resource` decorators in entire codebase (checked 17 files).

### 🔴 CSV/JSON reads on every re-render

`src/ui/pages/ml_pipeline.py:36,46,143` — `pd.read_csv()` + `json.load()` re-execute every re-render:

```python
wdf = pd.read_csv(weights_path)          # re-read every rerun
fdf = pd.read_csv(fund_path)             # re-read every rerun
bt = json.load(open(bt_files[0]))        # re-read every rerun
```

**Fix**:

```python
@st.cache_data(ttl=300)
def _read_ml_weights(weights_path: str) -> pd.DataFrame:
    wdf = pd.read_csv(weights_path)
    wdf.columns = [c.strip().lower() for c in wdf.columns]
    return wdf

@st.cache_data(ttl=300)
def _read_fundamentals(fund_path: str) -> pd.DataFrame:
    fdf = pd.read_csv(fund_path)
    fdf.columns = [c.strip().lower() for c in fdf.columns]
    return fdf

@st.cache_data(ttl=600)
def _read_backtest(bt_path: str) -> dict:
    with open(bt_path) as f:
        return json.load(f)
```

### 🟠 Repeated DB queries without caching

`src/ui/pages/stock_lookup.py:21,41-42` — `find_stock()`, `get_indicator()`, `get_prices()` on every interaction:

```python
stock = ctx.repo.find_stock(symbol)                # every keystroke
ind = ctx.repo.get_indicator(stock.id)              # every date change
prices_df = ctx.repo.get_prices(stock.id, start_date, end_date)  # every date change
```

**Fix**:

```python
@st.cache_data(ttl=300)
def _load_stock_data(symbol: str, start_date, end_date):
    repo = StockRepository()
    stock = repo.find_stock(symbol)
    if not stock:
        return None, None, None
    ind = repo.get_indicator(stock.id)
    prices_df = repo.get_prices(stock.id, start_date, end_date)
    return stock, ind, prices_df
```

### 🟡 No cache on reference data queries

Functions like `count_summary()`, `get_sectors()`, `get_job_runs()` change infrequently but hit DB every time.

---

## 3. DataFrame `iterrows()` Performance Antipattern

### 🔴 Price data insertion — hottest path

`src/ingestion/pipeline.py:126` — Row-by-row dict construction:

```python
values = []
for _, row in df.iterrows():
    values.append({
        "stock_id": stock.id,
        "date": row["date"],
        "open": row.get("open"),
        "high": row.get("high"),
        # ... 6 more fields
    })
```

**Impact**: 500 stocks × 2500 rows each = 1.25M Series objects created via iterrows.  
**Fix**: Vectorized construction:

```python
values = (
    df.assign(stock_id=stock.id)[
        ["stock_id", "date", "open", "high", "low", "close",
         "adj_close", "volume", "dividend_amount", "split_coefficient"]
    ]
    .to_dict("records")
)
```

**Estimated benefit**: ~5-10x faster for 2500-row DataFrames.

### 🟠 Technical indicator computation

`src/ingestion/indicators.py:97` — Row-by-row dict population via iterrows.

### 🟡 Paper trading weight lookup

`src/ui/pages/paper_trading.py:50` — Small DataFrame, low impact:

```python
target_weights = {str(r["gvkey"]): float(r["weight"]) for _, r in latest.iterrows()}
```

**Fix**:

```python
target_weights = dict(zip(latest["gvkey"].astype(str), latest["weight"].astype(float)))
```

### 🟡 Symbol data refresh

`src/ingestion/symbols.py:35` — iterrows() for CSV-based refresh.

---

## 4. Caching Opportunities

### 🟠 `load_config()` called 3-5 times per process

`src/ingestion/pipeline.py:27` (module level), `pipeline.py:183` (`_upsert_fundamentals`), `ml_pipeline.py:279`, `deep_evaluators.py`, `fast_evaluators.py`.

**Fix**:

```python
# src/config.py
from functools import lru_cache

@lru_cache(maxsize=1)
def get_cached_config() -> dict:
    return load_config()
```

### 🟠 No TTL on news_cache DB storage

`src/news_cache.py` — `stock_news` table grows unboundedly. No expiration.

**Impact**: With 500 stocks × 365 days × 7 days lookback, potentially millions of rows accumulating.

**Fix**: Add periodic cleanup:

```python
def prune_old_entries(max_age_days: int = 30) -> int:
    session = get_session()
    try:
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        result = session.execute(
            text("DELETE FROM stock_news WHERE fetched_at < :cutoff"),
            {"cutoff": cutoff}
        )
        session.commit()
        return result.rowcount
    finally:
        session.close()
```

### 🟡 ML model artifacts loaded eagerly

`src/finrl_runner.py:148-153` — All `.pkl` files loaded via `joblib.load()` into memory:

```python
for mp in model_files:
    artifact = joblib.load(mp)    # Loads ALL models — Ridge, RF, XGB, LGBM, HGB, ET, Stacking per sector
```

**Impact**: With 10+ sector models each containing 7 model fits + scalers, memory can spike >500MB.

**Fix**: Load only the latest model per bucket, defer full artifact load:

```python
# Track latest per bucket by mtime, load only winners
bucket_models = {}
for mp in model_files:
    bucket = _parse_bucket_from_path(mp)
    mtime = os.path.getmtime(mp)
    if bucket not in bucket_models or mtime > bucket_models[bucket][0]:
        bucket_models[bucket] = (mtime, mp)

# Load only the winners
for bucket, (_, mp) in bucket_models.items():
    artifact = joblib.load(mp)
```

---

## 5. Memory Leaks / Unbounded Growth

### 🟡 `sys.path` accumulation

Multiple locations insert paths without dedup:

- `src/finrl_runner.py:30,36` — `sys.path.insert` + `sys.path.append`
- `src/pipeline/backends/fast_evaluators.py:62` — `sys.path.insert(0, p)`
- `src/ingestion/pipeline.py` — module-level path manipulation

**Impact**: With Streamlit's re-import behavior, `sys.path` can grow duplicate entries over session lifetime.

**Fix**:

```python
def _safe_insert_path(p: str, *, position: int = 0) -> None:
    p = str(Path(p).resolve())
    if p not in sys.path:
        sys.path.insert(position, p)
```

### 🟡 `ml_log_lines` unbounded in session_state

`src/ui/pages/ml_pipeline.py:395` — Every log line appended, only tail-200 displayed:

```python
ctx.session_state.ml_log_lines.append(str(msg))
# ...
log_text = "\n".join(ctx.session_state.ml_log_lines[-200:])
```

**Impact**: 10K+ log lines held in Streamlit session_state memory across pipeline runs.

**Fix**:

```python
ctx.session_state.ml_log_lines = ctx.session_state.ml_log_lines[-1000:]
```

### 🟢 `os.environ` mutation (by design)

`_inject_api_keys()` sets env vars for subprocess/LangChain access. Not cleaned up. Intentional — low risk.

---

## 6. Redundant Computations

### 🟠 Plotly figures recreated on every interaction

`src/ui/pages/stock_lookup.py:70-93` — Full candlestick OHLC + volume subplot recreated for any sidebar change:

```python
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.02)
fig.add_trace(go.Candlestick(...))
fig.add_trace(go.Scatter(...))
fig.add_trace(go.Bar(...))
# 20+ more layout lines
ctx.st.plotly_chart(fig, width='stretch')
```

**Fix**: Cache figure creation on DataFrame hash:

```python
import hashlib

def _df_hash(df: pd.DataFrame) -> str:
    return hashlib.md5(df.to_json().encode()).hexdigest()

@st.cache_data(ttl=60, hash_funcs={pd.DataFrame: _df_hash})
def _build_candlestick_chart(prices_df: pd.DataFrame) -> go.Figure:
    # ... figure construction ...
    return fig
```

### 🟠 Feature importance CSV glob + stat on every re-render

`src/ui/pages/ml_pipeline.py:111-112`:

```python
fi_files = sorted(_glob.glob(str(DATA_DIR / "sp500_ml_feature_importance_*.csv")),
                  key=lambda f: Path(f).stat().st_mtime, reverse=True)
```

**Fix**:

```python
@st.cache_data(ttl=300)
def _latest_feature_importance(data_dir: str) -> str | None:
    fi_files = sorted(glob.glob(f"{data_dir}/sp500_ml_feature_importance_*.csv"),
                      key=os.path.getmtime, reverse=True)
    return fi_files[0] if fi_files else None
```

### 🟡 Sector aggregation recomputed on selection change

`src/ui/pages/ml_pipeline.py:94-109` — `groupby().agg()` runs every re-render even when data unchanged:

```python
agg = (sd.groupby(s_col_f)
       .agg(stock_count=(count_col, "count"), total_weight=("weight", "sum"))
       .reset_index().sort_values("total_weight", ascending=False))
```

**Fix**: Cache on input DataFrame:

```python
@st.cache_data(ttl=300)
def _build_sector_agg(wdf: pd.DataFrame, s_col_f: str) -> pd.DataFrame:
    sd = wdf.copy()
    sd["weight"] = pd.to_numeric(sd["weight"], errors="coerce").fillna(0)
    count_col = next(...)
    return sd.groupby(s_col_f).agg(...).reset_index().sort_values(...)
```

### 🟡 Three DB sessions for stock_detail dialog

`src/ui/pages/stock_detail.py:12-18` — Each page load opens 3 separate DB sessions:

```python
stock = _repo.find_stock(symbol)              # Session 1
indicator = _repo.get_indicator(stock.id)      # Session 2
snapshot = _repo.get_snapshot(stock.id)        # Session 3
```

**Fix**: Single-session bulk fetch:

```python
def get_stock_detail(self, symbol: str) -> tuple[Optional[Stock], Optional[StockIndicator], Optional[StockSnapshot]]:
    def _query(s):
        stock = s.query(Stock).filter_by(symbol=symbol.upper()).first()
        if not stock:
            return None, None, None
        ind = s.query(StockIndicator).filter_by(stock_id=stock.id).first()
        snap = s.query(StockSnapshot).filter_by(stock_id=stock.id).first()
        return stock, ind, snap
    return self._with_session(_query)
```

---

## 7. Streamlit Re-Render Issues

### 🔴 1-second polling loop: ml_pipeline.py

`src/ui/pages/ml_pipeline.py:406-409`:

```python
if status == "Running":
    import time as _time
    _time.sleep(1)
    ctx.st.rerun()
```

**Impact**: Full page re-render every second — including all cached-data recomputation above — for potentially 2-10 minutes per pipeline run.

**Fix**: Increase interval and use `st.fragment()` for the log section:

```python
if status == "Running":
    _time.sleep(3)     # 3s polling, reduces re-renders by 3x
    ctx.st.rerun()
```

### 🟡 No `st.fragment()` usage anywhere

None of the 13 page modules use `st.fragment()`. Every widget interaction triggers full page re-render.

**Fix candidates**:
- `stock_lookup.py`: Wrap chart + table in `@st.fragment(run_every=30)`
- `ml_pipeline.py`: Wrap log output in fragment

---

## 8. LLM Call Optimization

### 🟡 Sequential per-ticker LLM evaluation

`src/pipeline/backends/deep_evaluators.py:148`:

```python
for ticker in tickers:
    result = graph.propagate(ticker, eval_date)    # 8+ LLM calls per ticker
```

**Impact**: With top_n=3 and 2-5s LLM latency, that's 48-120s sequential total.

**Fix**: Parallelize with ThreadPoolExecutor:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=min(len(tickers), 3)) as pool:
    futures = {pool.submit(graph.propagate, t, eval_date): t for t in tickers}
    for future in as_completed(futures):
        # process result
```

---

## Prioritized Action Items

| # | Issue | File | Severity | Effort |
|---|-------|------|----------|--------|
| 1 | Add `@st.cache_data` to CSV/JSON reads | `ml_pipeline.py` | 🔴 Critical | S |
| 2 | Bulk stock name lookup vs N+1 | `ml_pipeline.py:63-65` | 🔴 Critical | S |
| 3 | Replace iterrows in price insertion | `ingestion/pipeline.py:126` | 🔴 Critical | M |
| 4 | Reduce polling interval 1s→3s | `ml_pipeline.py:406-409` | 🔴 Critical | S |
| 5 | Add `get_stock_detail` bulk method | `repository.py` | 🟠 High | S |
| 6 | Cache candlestick figure | `stock_lookup.py:70-93` | 🟠 High | S |
| 7 | Cache sector aggregation | `ml_pipeline.py:94-109` | 🟠 High | S |
| 8 | Cache feature importance glob | `ml_pipeline.py:111-112` | 🟠 High | S |
| 9 | `@lru_cache` on `load_config()` | `config.py` | 🟡 Medium | S |
| 10 | Dedup `sys.path` insertion | `finrl_runner.py`, `fast_evaluators.py` | 🟡 Medium | S |
| 11 | Truncate `ml_log_lines` in session | `ml_pipeline.py:395` | 🟡 Medium | S |
| 12 | Add news_cache TTL cleanup | `news_cache.py` | 🟡 Medium | M |
| 13 | Parallelize TradingAgents LLM calls | `deep_evaluators.py:148` | 🟡 Medium | M |
| 14 | Lazy model loading | `finrl_runner.py:148-153` | 🟡 Medium | M |
| 15 | Replace iterrows in indicators/symbols | `indicators.py`, `symbols.py` | 🟢 Low | M |
| 16 | Use `st.fragment()` | Multiple pages | 🟢 Low | M |
| 17 | Replace iterrows in paper_trading | `paper_trading.py:50` | 🟢 Low | S |

**Effort**: S = <1h, M = 1-4h

---

## Estimated Impact Summary

| Category | Current | Target | Improvement |
|----------|---------|--------|-------------|
| ML results page re-render | 2-3s (CSV reads) | <200ms (cached) | 10-15x |
| Stock lookup interactions | 0.5-1s (DB per keystroke) | <100ms | 5-10x |
| Price ingestion (500 stocks) | ~30s (iterrows) | ~5s (vectorized) | 6x |
| config.yaml loads per process | 3-5 loads | 1 load | 3-5x |
| DB sessions per stock_detail | 3 sessions | 1 session | 3x |
| Pipeline page idle CPU | 1 rerun/s | 0.33 rerun/s | 3x |
| Deep eval (3 tickers, sequential) | 48-120s | 16-40s (parallel) | 3x |
