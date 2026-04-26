# Stock Data Management System — Design Spec
**Date:** 2026-04-26  
**Status:** Approved

---

## 1. Overview

A personal stock data platform running on a Mac Mini (always-on). Fetches OHLCV + fundamental data from Alpha Vantage for all NASDAQ and NYSE listed stocks (~6,300 symbols), stores in MySQL, computes technical indicators locally, and exposes a Streamlit web dashboard with four tabs: Lookup, Technical Analysis, Screener, and Manager.

**Key constraints:**
- Alpha Vantage premium: 75 req/min, 15-min delayed US market data
- All NASDAQ + NYSE symbols (~6,300)
- Automated daily refresh after market close
- Single user, Mac Mini server, `~/PROD` deployment

---

## 2. Architecture

Five subsystems:

```
┌─────────────────────┐     ┌──────────────────────────────────────────┐
│   DATA SOURCES      │     │           INGESTION ENGINE               │
│  Alpha Vantage API  │────▶│  Symbol Loader → Rate-limited Fetcher    │
│  · TIME_SERIES_     │     │  → Pipeline Orchestrator (5 steps)       │
│    DAILY_ADJUSTED   │     │  ThreadPoolExecutor + TokenBucket 75/min │
│  · OVERVIEW         │     │  Checkpoint/resume on crash              │
│  · LISTING_STATUS   │     └──────────────────┬───────────────────────┘
│  yfinance (fallback)│                        │ fetch & store
└─────────────────────┘                        ▼
                              ┌────────────────────────────────┐
                              │         MYSQL DATABASE         │
                              │  stocks · daily_prices         │
                              │  stock_indicators              │
                              │  technical_indicators (JSON)   │
                              │  stock_snapshots · pipeline_runs│
                              └───────────────┬────────────────┘
                                              │ read
┌─────────────────────┐                       ▼
│     SCHEDULER       │     ┌────────────────────────────────┐
│  launchd (macOS)    │────▶│      WEB DASHBOARD             │
│  Weekdays 18:00 ET  │     │  Streamlit + Plotly            │
│  APScheduler inside │     │  4 tabs: Lookup / TA /         │
│  SQLAlchemyJobStore │     │  Screener / Manager            │
└─────────────────────┘     └────────────────────────────────┘
```

pandas-ta indicator computation runs in-process after each price fetch batch.

---

## 3. Database Schema

### 3.1 `stocks`
Static metadata. Refreshed weekly from `LISTING_STATUS`.

| Column | Type | Source |
|--------|------|--------|
| id | BIGINT PK AI | — |
| symbol | VARCHAR(10) UNIQUE | Symbol |
| name | VARCHAR(255) | Name |
| asset_type | VARCHAR(50) | AssetType |
| exchange | VARCHAR(20) | Exchange |
| currency | VARCHAR(10) | Currency |
| country | VARCHAR(50) | Country |
| sector | VARCHAR(100) | Sector |
| industry | VARCHAR(100) | Industry |
| description | TEXT | Description |
| cik | VARCHAR(20) | CIK |
| official_site | VARCHAR(255) | OfficialSite |
| address | VARCHAR(255) | Address |
| fiscal_year_end | VARCHAR(20) | FiscalYearEnd |
| shares_outstanding | BIGINT | SharesOutstanding |
| shares_float | BIGINT | SharesFloat |
| **is_active** | **BOOLEAN DEFAULT FALSE** | — |
| **activated_at** | **DATETIME NULL** | — |
| last_price_fetch | DATETIME NULL | — (checkpoint) |

INDEX: `(is_active)`, `(symbol)`

### 3.2 `daily_prices`
OHLCV per trading day. Source: `TIME_SERIES_DAILY_ADJUSTED`.

| Column | Type | Source |
|--------|------|--------|
| id | BIGINT PK AI | — |
| stock_id | BIGINT FK→stocks | — |
| date | DATE | date key |
| open | DECIMAL(14,4) | 1. open |
| high | DECIMAL(14,4) | 2. high |
| low | DECIMAL(14,4) | 3. low |
| close | DECIMAL(14,4) | 4. close |
| adj_close | DECIMAL(14,4) | 5. adjusted close |
| volume | BIGINT | 6. volume |
| dividend_amount | DECIMAL(10,4) | 7. dividend amount |
| split_coefficient | DECIMAL(10,4) | 8. split coefficient |

UNIQUE INDEX: `(stock_id, date)`

### 3.3 `stock_indicators`
All changing financial metrics from `OVERVIEW`. One row per stock, upserted on update.

| Column | Type | Source |
|--------|------|--------|
| id | BIGINT PK AI | — |
| stock_id | BIGINT FK UNIQUE | — |
| latest_quarter | DATE | LatestQuarter |
| market_cap | BIGINT | MarketCapitalization |
| ebitda | BIGINT | EBITDA |
| pe_ratio | DECIMAL(10,4) | PERatio |
| peg_ratio | DECIMAL(10,4) | PEGRatio |
| book_value | DECIMAL(10,4) | BookValue |
| dividend_per_share | DECIMAL(10,4) | DividendPerShare |
| dividend_yield | DECIMAL(10,6) | DividendYield |
| eps | DECIMAL(10,4) | EPS |
| diluted_eps_ttm | DECIMAL(10,4) | DilutedEPSTTM |
| revenue_per_share_ttm | DECIMAL(10,4) | RevenuePerShareTTM |
| profit_margin | DECIMAL(10,6) | ProfitMargin |
| operating_margin_ttm | DECIMAL(10,6) | OperatingMarginTTM |
| roa_ttm | DECIMAL(10,6) | ReturnOnAssetsTTM |
| roe_ttm | DECIMAL(10,6) | ReturnOnEquityTTM |
| revenue_ttm | BIGINT | RevenueTTM |
| gross_profit_ttm | BIGINT | GrossProfitTTM |
| qtr_earnings_growth_yoy | DECIMAL(10,6) | QuarterlyEarningsGrowthYOY |
| qtr_revenue_growth_yoy | DECIMAL(10,6) | QuarterlyRevenueGrowthYOY |
| analyst_target_price | DECIMAL(10,4) | AnalystTargetPrice |
| analyst_strong_buy | SMALLINT | AnalystRatingStrongBuy |
| analyst_buy | SMALLINT | AnalystRatingBuy |
| analyst_hold | SMALLINT | AnalystRatingHold |
| analyst_sell | SMALLINT | AnalystRatingSell |
| analyst_strong_sell | SMALLINT | AnalystRatingStrongSell |
| trailing_pe | DECIMAL(10,4) | TrailingPE |
| forward_pe | DECIMAL(10,4) | ForwardPE |
| price_to_sales_ttm | DECIMAL(10,4) | PriceToSalesRatioTTM |
| price_to_book | DECIMAL(10,4) | PriceToBookRatio |
| ev_to_revenue | DECIMAL(10,4) | EVToRevenue |
| ev_to_ebitda | DECIMAL(10,4) | EVToEBITDA |
| beta | DECIMAL(8,4) | Beta |
| week_52_high | DECIMAL(14,4) | 52WeekHigh |
| week_52_low | DECIMAL(14,4) | 52WeekLow |
| ma_50_day | DECIMAL(14,4) | 50DayMovingAverage |
| ma_200_day | DECIMAL(14,4) | 200DayMovingAverage |
| pct_insiders | DECIMAL(8,4) | PercentInsiders |
| pct_institutions | DECIMAL(8,4) | PercentInstitutions |
| dividend_date | DATE | DividendDate |
| ex_dividend_date | DATE | ExDividendDate |
| last_updated | DATETIME | — |

UNIQUE INDEX: `(stock_id)`

### 3.4 `technical_indicators`
Full pandas-ta output stored as JSON. All 130+ indicators computed from OHLCV — zero schema migration when indicator params change. Hot fields indexed via MySQL generated virtual columns for screener performance.

| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT PK AI | — |
| stock_id | BIGINT FK→stocks | — |
| date | DATE | — |
| indicators | JSON | Full `df.ta.strategy("all")` output dict |
| computed_at | DATETIME | — |

UNIQUE INDEX: `(stock_id, date)`  
Generated virtual columns (indexed): `rsi_14`, `macd`, `sma_20`, `sma_50`, `atr_14`

### 3.5 `stock_snapshots`
Denormalized latest values per stock. Refreshed after every pipeline run. All screener filter columns are indexed. Used exclusively by Screener tab — never updated during normal queries.

| Column | Type | Source |
|--------|------|--------|
| stock_id | BIGINT PK FK→stocks | — |
| latest_date | DATE | daily_prices MAX(date) |
| close | DECIMAL(14,4) | daily_prices |
| volume | BIGINT | daily_prices |
| pe_ratio | DECIMAL(10,4) | stock_indicators |
| market_cap | BIGINT | stock_indicators |
| roe_ttm | DECIMAL(10,6) | stock_indicators |
| dividend_yield | DECIMAL(10,6) | stock_indicators |
| beta | DECIMAL(8,4) | stock_indicators |
| rsi_14 | DECIMAL(8,4) | technical_indicators |
| macd | DECIMAL(10,6) | technical_indicators |
| sma_20 | DECIMAL(14,4) | technical_indicators |
| sma_50 | DECIMAL(14,4) | technical_indicators |
| sector | VARCHAR(100) | stocks |
| exchange | VARCHAR(20) | stocks |
| updated_at | DATETIME | — |

### 3.6 `pipeline_runs`
Observability log — one row per pipeline execution.

| Column | Type |
|--------|------|
| id | BIGINT PK AI |
| started_at | DATETIME |
| finished_at | DATETIME NULL |
| symbols_processed | INT |
| errors_count | INT |
| status | VARCHAR(20) |

---

## 4. Ingestion Engine

### 4.1 Five-step daily pipeline (`ingestion/pipeline.py`)

**Step 1 — Load symbols** (weekly, Sunday 02:00)  
`symbols.py` calls AV `LISTING_STATUS` → upserts `stocks` table. New symbols default `is_active=FALSE`.

**Step 2 — Fetch prices** (daily, active stocks only)  
`ThreadPoolExecutor(workers=10)` + `TokenBucket(75/min)`.  
Per symbol: query `MAX(date)` from `daily_prices` → fetch from `max_date+1` to today → bulk insert.  
Skips symbol if already up to date. Updates `stocks.last_price_fetch` after each success (resume checkpoint).  
Estimated ~17 min for 6,300 active symbols at full rate.

**Step 3 — Fetch fundamentals** (weekly cadence, amortized daily)  
Same thread pool. Skips if `stock_indicators.last_updated < 7 days ago`.  
Calls AV `OVERVIEW` endpoint → upserts `stock_indicators`.  
~900 symbols refreshed per day (1/7 of 6,300), ~200 AV calls/day amortized.

**Step 4 — Compute technical indicators**  
Per symbol with new price data: load full `daily_prices` into pandas DataFrame → `df.ta.strategy("all")` → serialize output dict to JSON → upsert `technical_indicators` for new dates only.

**Step 5 — Refresh snapshots**  
Single bulk `REPLACE INTO stock_snapshots` joining latest rows from `daily_prices`, `stock_indicators`, `technical_indicators`, and `stocks`. Runs once after all symbols processed.

### 4.2 Rate limiter (`fetcher/rate_limiter.py`)

Token bucket: capacity=75, refill=75 tokens/60s. Thread-safe `acquire()` context manager blocks until token available. No sleep loops.

```python
with rate_limiter.acquire():
    response = av_client.get_daily(symbol)
```

### 4.3 Error handling

- Per-symbol: 3× exponential backoff on HTTP 5xx / timeout
- Skip on 4xx (delisted/bad symbol): log + continue
- Checkpoint: `stocks.last_price_fetch` written after each successful symbol — crash recovery resumes mid-run
- All runs logged to `pipeline_runs` table

### 4.4 Fetcher abstraction (`fetcher/base.py`)

Abstract `FetcherBase` with methods: `get_daily(symbol, start, end)`, `get_overview(symbol)`, `get_listing()`. `alpha_vantage.py` and `yahoo.py` implement this interface. `config.yaml` `source` key selects the active backend. yfinance is used only when `source: yahoo` is set in config — it is not an automatic fallback during AV failures.

---

## 5. Technical Indicator Computation (`ingestion/indicators.py`)

Uses `pandas-ta`. Runs `df.ta.strategy("all")` on the full OHLCV DataFrame for each symbol. Output is a dict of all computed columns (130+ indicators, 200+ values) stored as JSON in `technical_indicators.indicators`.

Only rows with dates newer than the latest `technical_indicators.date` are inserted — existing history is not recomputed.

---

## 6. Web Dashboard (`app.py`)

Streamlit application. Light theme. Port `8501`. Four tabs.

### Tab 1 — Lookup
- Sidebar: symbol search input, date range pickers, stock metadata card (name, exchange, sector, active status)
- Metric cards: latest close (% change), PE ratio, market cap, daily volume
- Plotly candlestick chart with adj_close overlay and volume bar sub-chart
- Recent prices table (date, open, high, low, close, adj_close, volume)

### Tab 2 — Technical Analysis
- Sidebar: symbol input, overlay checkboxes (SMA 20/50/200, EMA 12/26, Bollinger Bands), oscillator checkboxes (RSI, MACD, Stochastic, ATR)
- Main chart: candlestick + selected overlays
- Oscillator sub-panels below chart (RSI 0–100 with overbought/oversold lines, MACD + signal + histogram)
- All indicator values read from `technical_indicators.indicators` JSON

### Tab 3 — Screener
- Filter inputs: market cap (min), PE ratio (range), ROE (min), RSI (range), dividend yield (min), beta (range), sector (dropdown), exchange (dropdown)
- "Run Screen" button → queries `stock_snapshots` table
- Results table: symbol (clickable → opens Lookup tab), name, market cap, PE, ROE, RSI, beta, yield
- "Export CSV" button
- Result count displayed

### Tab 4 — Manager
- Summary stats: total listed, active count, inactive count
- Filter panel: exchange, sector, market cap range, PE range, ROE min, dividend yield, beta range, status (all/active/inactive)
- "Apply Filters" → filtered results table
- "Activate All Filtered" / "Deactivate All Filtered" bulk action buttons
- Per-row toggle to activate/deactivate individual stocks
- Results table: symbol, name, market cap, sector, PE, ROE, beta, active status indicator

---

## 7. File Structure

```
AIStock/
├── README.md                    # bootstrap, testing, production, usage guide
├── CLAUDE.md                    # Claude Code guidance
├── config.yaml                  # API key, DB URL, scheduler config, activation criteria
├── requirements.txt
├── config.yaml.example          # template config with all keys documented
├── main.py                      # CLI: --init-db, --bootstrap, --symbol, --start, --end, --force
├── scheduler.py                 # APScheduler entry point (production daemon)
├── models.py                    # SQLAlchemy 2.0 models for all 6 tables
├── database.py                  # engine, session factory, get_session()
├── fetcher/
│   ├── __init__.py
│   ├── base.py                  # abstract FetcherBase
│   ├── alpha_vantage.py         # AV: TIME_SERIES_DAILY_ADJUSTED, OVERVIEW, LISTING_STATUS
│   ├── yahoo.py                 # yfinance fallback
│   └── rate_limiter.py          # TokenBucket, thread-safe acquire()
├── ingestion/
│   ├── __init__.py
│   ├── pipeline.py              # 5-step orchestrator
│   ├── symbols.py               # LISTING_STATUS → stocks table
│   └── indicators.py            # pandas-ta computation → JSON
└── app.py                       # Streamlit dashboard
```

---

## 8. Deployment (Mac Mini, macOS)

### 8.1 Production directory

```
~/PROD/
├── AIStock/
│   ├── config.yaml              # production config (real API key, DB credentials)
│   ├── venv/                    # Python virtualenv
│   └── logs/
│       ├── scheduler.log
│       └── app.log
```

### 8.2 `config.yaml` (production)

```yaml
source: alpha_vantage
alpha_vantage:
  api_key: "YOUR_KEY"
database:
  url: "mysql+pymysql://user:pass@localhost/stockdb"
scheduler:
  daily_run_time: "18:00"
  overview_refresh_days: 7
  timezone: "America/New_York"
default_activation_criteria:
  min_market_cap: 500000000       # $500M+
  exchanges: [NASDAQ, NYSE]
log_dir: "~/PROD/AIStock/logs"
```

### 8.3 launchd agents

Two plist files in `~/Library/LaunchAgents/`:

- `com.stockdb.scheduler.plist` — runs `scheduler.py`, `StartCalendarInterval` weekdays 18:00, `KeepAlive=false`
- `com.stockdb.app.plist` — runs `streamlit run app.py`, `KeepAlive=true`, starts on login

### 8.4 Bootstrap sequence (first time only)

```bash
# 1. Prerequisites
brew install mysql python@3.12
brew services start mysql
mysql -u root -e "CREATE DATABASE stockdb; CREATE USER 'stockdb'@'localhost' IDENTIFIED BY 'pass'; GRANT ALL ON stockdb.* TO 'stockdb'@'localhost';"

# 2. Deploy code
cd ~/PROD
git clone <repo> AIStock && cd AIStock
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp config.yaml.example config.yaml
# Edit config.yaml — set API key and DB URL

# 4. Initialize database
python main.py --init-db

# 5. Fetch all fundamentals (bootstrap, ~84 min)
python main.py --bootstrap

# 6. Activate stocks via Manager tab
streamlit run app.py &
# Open http://localhost:8501 → Manager tab → set criteria → Activate

# 7. Register launchd agents
launchctl load ~/Library/LaunchAgents/com.stockdb.scheduler.plist
launchctl load ~/Library/LaunchAgents/com.stockdb.app.plist
```

**Mac Mini timezone:** Set System Settings → General → Date & Time → Time Zone to `America/New_York` so 18:00 local = after US market close.

---

## 9. AAPL Smoke Test

Run after all code is implemented. Validates every pipeline step before enabling full production run.

```bash
cd ~/PROD/AIStock && source venv/bin/activate
python main.py --symbol AAPL --force
```

`--force` bypasses `is_active` check, runs full pipeline for one symbol.

### Verification checklist

| Step | Command | Expected |
|------|---------|----------|
| Symbol loaded | `SELECT * FROM stocks WHERE symbol='AAPL'` | 1 row, exchange=NASDAQ |
| Prices fetched | `SELECT COUNT(*), MIN(date), MAX(date) FROM daily_prices dp JOIN stocks s ON s.id=dp.stock_id WHERE s.symbol='AAPL'` | >6,000 rows, min≈2000-01-03, max=today |
| Fundamentals | `SELECT pe_ratio, market_cap, roe_ttm FROM stock_indicators si JOIN stocks s ON s.id=si.stock_id WHERE s.symbol='AAPL'` | pe_ratio≈34.4, market_cap>0, roe_ttm>0 |
| Tech indicators | `SELECT JSON_LENGTH(indicators), computed_at FROM technical_indicators ti JOIN stocks s ON s.id=ti.stock_id WHERE s.symbol='AAPL' ORDER BY date DESC LIMIT 1` | JSON_LENGTH>100, computed_at=today |
| Snapshots | `SELECT rsi_14, sma_20, close FROM stock_snapshots ss JOIN stocks s ON s.id=ss.stock_id WHERE s.symbol='AAPL'` | All non-null |
| Lookup tab | Open http://localhost:8501 → search AAPL | Candlestick renders, metric cards populated |
| TA tab | Select AAPL, enable RSI + MACD | Oscillator panels render below chart |
| Screener | Run screen with no filters | AAPL appears in results |
| Manager | View Manager tab | AAPL row visible, toggle works |

All 9 checks must pass before enabling the production scheduler.

---

## 10. Deliverables

| File | Purpose |
|------|---------|
| `README.md` | Bootstrap steps, testing guide, production setup, web app usage |
| `config.yaml.example` | Template config with all keys documented |
| `models.py` | All 6 SQLAlchemy models |
| `database.py` | Engine + session management |
| `fetcher/` | Rate-limited AV + yfinance fetchers |
| `ingestion/` | Pipeline, symbol loader, indicator computation |
| `main.py` | CLI with `--init-db`, `--bootstrap`, `--symbol`, `--force` |
| `scheduler.py` | Production APScheduler daemon |
| `app.py` | Streamlit dashboard (4 tabs, light theme) |
| `~/Library/LaunchAgents/*.plist` | macOS launchd service definitions |
