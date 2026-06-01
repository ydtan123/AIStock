# AIStock Performance Audit — 2026-05-30

Tech stack: Python 3.13, Streamlit 1.40.2, SQLAlchemy 2.0, MySQL/pymysql, Plotly 5.24

---

## 1. N+1 Query Patterns

### 1.1 CRITICAL — `_predict_only_thread_target` loops DB per row

**File:** `src/app.py:167-176`

Each iteration calls `repo.find_stock()` + `repo.get_prices()` individually:

```python
for _, row in pred_df.iterrows():
    ticker = row["ticker"]
    dd = _pd.to_datetime(row["datadate"]).date()
    stock = repo.find_stock(str(ticker))      # N queries
    if stock is None: continue
    prices = repo.get_prices(stock.id, dd, _date.today())  # N more queries
```

**Fix:** Batch lookup all tickers at once, then batch price query:

```python
# Add to StockRepository:
def find_stocks_by_symbols(self, symbols: list[str]) -> dict[str, Stock]:
    session = self._get_session()
    try:
        stocks = session.query(Stock).filter(
            Stock.symbol.in_([s.upper() for s in symbols])
        ).all()
        return {s.symbol: s for s in stocks}
    finally:
        session.close()

def get_prices_multi(self, stock_ids: list[int], start: date, end: date) -> dict[int, pd.DataFrame]:
    session = self._get_session()
    try:
        rows = session.query(DailyPrice).filter(
            DailyPrice.stock_id.in_(stock_ids),
            DailyPrice.date >= start,
            DailyPrice.date <= end,
        ).order_by(DailyPrice.date).all()
        result = {}
        for r in rows:
            result.setdefault(r.stock_id, []).append({
                "date": r.date, "open": r.open, "high": r.high, "low": r.low,
                "close": r.close, "adj_close": r.adj_close, "volume": r.volume,
            })
        return {sid: pd.DataFrame(recs) for sid, recs in result.items()}
    finally:
        session.close()

# Usage — 2 queries total instead of 2N:
stock_map = repo.find_stocks_by_symbols(tickers)
price_map = repo.get_prices_multi([s.id for s in stock_map.values()], min_date, today)
```

### 1.2 HIGH — `_show_ml_results` loops DB per ticker

**File:** `src/app.py:612-613`

```python
for sym in wdf[ticker_col].dropna().unique():
    stock = _repo.find_stock(str(sym))  # N queries
    name_map[sym] = stock.name if stock else ""
```

**Fix:** Use `find_stocks_by_symbols` (above) — single query.

### 1.3 MEDIUM — 3 separate queries for same stock in detail dialog

**File:** `src/app.py:383-390`

```python
stock = repo.find_stock(symbol)           # Query 1
indicator = repo.get_indicator(stock.id)   # Query 2
snapshot = repo.get_snapshot(stock.id)     # Query 3
```

**Fix:** Add `session` parameter to repository methods to share one session across related calls.

```python
def find_stock(self, symbol: str, session=None) -> Optional[Stock]:
    own = session is None
    s = session or self._get_session()
    try:
        return s.query(Stock).filter_by(symbol=symbol.upper()).first()
    finally:
        if own: s.close()
```

---

## 2. No Streamlit Caching — Major Gap

`@st.cache_data` and `@st.cache_resource` are **never used** in the 1560-line app. Every interaction reruns all queries.

### 2.1 CRITICAL — `repo.count_summary()` called every rerun

**File:** `src/app.py:1512` → `display_quick_stats()` → `src/app.py:778`

Every keystroke in sidebar triggers this query. Same query also runs in `show_overview` (line 833).

```python
@st.cache_data(ttl=30)
def _cached_count_summary() -> dict:
    repo = StockRepository()
    return repo.count_summary()
```

### 2.2 HIGH — `repo.get_sectors()` called on every form render

**File:** `src/app.py:1377` (screener), `src/app.py:1418` (manager)

```python
@st.cache_data(ttl=300)
def _cached_sectors(table: str = "stock_snapshots") -> list[str]:
    repo = StockRepository()
    return repo.get_sectors(table)
```

### 2.3 HIGH — Config YAML read from disk on every render

**File:** `src/app.py:228-234`

```python
@st.cache_data(ttl=60)
def _load_pipeline_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    with open(cfg_path) as fh:
        return yaml.safe_load(fh) or {}
```

### 2.4 MEDIUM — Backtest JSON reread on every interaction

**File:** `src/app.py:1036-1041`, `src/app.py:695-698`

```python
@st.cache_data(ttl=60)
def _load_backtest(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
```

---

## 3. Polling Loop

### 3.1 HIGH — `time.sleep(1)` + `st.rerun()` polling

**File:** `src/app.py:360-363`

```python
if status == "Running":
    time.sleep(1)
    st.rerun()
```

Full page rerun every 1 second while pipeline runs. Each rerun executes all widgets, uncached queries, renders.

**Fix:** Remove the sleep — `st.rerun()` already batches. Or reduce:

```python
if status == "Running":
    if time.time() - st.session_state.get("_last_poll", 0) > 5:
        st.session_state["_last_poll"] = time.time()
        time.sleep(0.5)
        st.rerun()
```

---

## 4. Redundant Computations

### 4.1 MEDIUM — Lambda closures re-created every render

**File:** `src/app.py:1403-1406, 1474-1476`

```python
df["ROE %"] = df["ROE %"].apply(nan_safe(lambda x: f"{float(x)*100:.1f}%"))
```

Define at module level to avoid re-creating function objects:

```python
_fmt_pct1 = nan_safe(lambda x: f"{float(x)*100:.1f}%")
_fmt_pct2 = nan_safe(lambda x: f"{float(x)*100:.2f}%")
_fmt_dec1 = nan_safe(lambda x: f"{float(x):.2f}")
```

### 4.2 MEDIUM — Drawdown recomputed every view

**File:** `src/app.py:753-770`

`np.maximum.accumulate(cum)` + drawdown calc runs on every render. With `@st.cache_data` on backtest loader, becomes free.

---

## 5. Memory/Resource Issues

### 5.1 LOW — TokenBucket tight polling loop

**File:** `src/fetcher/rate_limiter.py:28-38`

```python
while True:
    with self._lock:
        if self._tokens >= tokens and spacing_ok:
            return
    time.sleep(0.05)  # 50ms poll, up to 200 wakeups/sec when depleted
```

**Fix:** Use `threading.Condition.wait(timeout)` instead of spinloop.

### 5.2 MEDIUM — `ml_log_lines` unbounded growth

**File:** `src/app.py:349`

Log lines appended infinitely during pipeline runs. Display truncates to 200 lines but list grows boundlessly.

```python
st.session_state.ml_log_lines.append(msg)
if len(st.session_state.ml_log_lines) > 1000:
    st.session_state.ml_log_lines = st.session_state.ml_log_lines[-500:]
```

### 5.3 OK — Connection pool well-configured

**File:** `src/database.py:24`

```python
_engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600, pool_size=8, max_overflow=4)
```

Good. No event listener leaks. `daemon=True` threads. Session cleanup consistent.

---

## 6. Database Index Opportunities

```sql
-- daily_prices range queries (get_prices)
CREATE INDEX idx_daily_prices_stock_date ON daily_prices(stock_id, date);

-- stock_news cache lookups (get_cached)
CREATE INDEX idx_stock_news_lookup ON stock_news(tool_name, ticker, fetched_at);

-- selected_stocks latest run (get_latest_selected_stocks)
CREATE INDEX idx_selected_stocks_run_at ON selected_stocks(pipeline_run_at DESC);
```

---

## 7. Summary — Priority Table

| Priority | Issue | Location | Savings |
|----------|-------|----------|---------|
| **P0** | Add `@st.cache_data` to DB queries | `app.py` multiple | 5-50x fewer queries |
| **P0** | Batch N+1 in `_predict_only_thread_target` | `app.py:167` | N to 2 queries |
| **P1** | Batch N+1 in `_show_ml_results` | `app.py:612` | N to 1 query |
| **P1** | Remove/reduce polling sleep | `app.py:360` | 5x fewer page reruns |
| **P1** | Cache config.yaml read | `app.py:228` | Skip I/O per render |
| **P2** | Cache backtest JSON reads | `app.py:1036` | Skip I/O per render |
| **P2** | Module-level lambda formatters | `app.py:1402-1406` | Avoid re-creating closures |
| **P2** | TokenBucket Condition over spinloop | `rate_limiter.py:29` | Lower CPU waste |
| **P2** | Cap log_line list size | `app.py:349` | Prevent memory growth |
| **P3** | DB indexes for hot query paths | SQL migrations | 2-10x query speedup |

**No React in this codebase** — it's Streamlit (Python). Equivalent concern: every widget interaction triggers full script rerun. Caching is the fix for both.

**Estimated total query reduction:** 80-95% fewer DB calls per interaction.

**Estimated render time improvement:** 2-5x faster page loads after Streamlit caching.
