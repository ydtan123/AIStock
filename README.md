# StockDB

Stock data management system for NASDAQ and NYSE. Fetches OHLCV + fundamental data from Alpha Vantage, computes technical indicators locally, stores in MySQL, and exposes a Streamlit dashboard.

---

## Prerequisites

- macOS (Mac Mini or similar always-on machine)
- [Homebrew](https://brew.sh)
- Alpha Vantage API key (premium plan, 75 req/min)

---

## Bootstrap (First Time Setup)

### 1. Install system dependencies

```bash
brew install mysql python@3.12
brew services start mysql
```

### 2. Create MySQL database and user

```bash
mysql -u root -e "
  CREATE DATABASE stockdb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  CREATE USER 'stockdb'@'localhost' IDENTIFIED BY 'your_password';
  GRANT ALL PRIVILEGES ON stockdb.* TO 'stockdb'@'localhost';
  FLUSH PRIVILEGES;
"
```

### 3. Deploy code

```bash
mkdir -p ~/PROD && cd ~/PROD
git clone <repo_url> AIStock
cd AIStock
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# pandas-ta is installed separately without numba (numba doesn't support Python 3.14)
pip install pandas-ta==0.4.71b0 --no-deps
mkdir -p logs

# Create numba stub so pandas-ta imports work on Python 3.14
python3 - << 'STUB'
import site, os
stub_dir = os.path.join(site.getsitepackages()[0], "numba")
os.makedirs(stub_dir, exist_ok=True)
with open(os.path.join(stub_dir, "__init__.py"), "w") as f:
    f.write("""def njit(*a,**kw):\n    return a[0] if a and callable(a[0]) else (lambda fn: fn)\njit=njit\nprange=range\n""")
STUB
```

### 4. Configure

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml`:
- Set `alpha_vantage.api_key` to your real API key
- Set `database.url` with your MySQL password
- Set `scheduler.timezone` to match your Mac Mini's timezone (recommend `America/New_York`)
- Optionally set `default_activation_criteria` to auto-activate stocks on bootstrap

**Set Mac Mini timezone:** System Settings → General → Date & Time → `America/New_York`

### 5. Initialize database tables

```bash
python main.py init-db
```

### 6. Run bootstrap (~84 minutes)

Fetches OVERVIEW for all ~6,300 NASDAQ+NYSE symbols to populate fundamentals.

```bash
python main.py bootstrap
```

If `default_activation_criteria` is set in `config.yaml`, matching stocks are automatically activated. Otherwise, use the Manager tab (step 7) to activate manually.

### 7. Activate stocks via Manager tab

```bash
streamlit run app.py &
```

Open [http://localhost:8501](http://localhost:8501) → **Manager** tab → set filter criteria → **Activate All Filtered**.

Stop the temporary Streamlit instance: `kill %1`

### 8. Install launchd agent (production)

```bash
cp com.aistock.scheduler.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.aistock.scheduler.plist
```

The scheduler runs the daily pipeline at 9:30 AM Pacific (Mon–Fri) and weekly symbol refresh on Sundays at 2:00 AM Pacific.

Start the dashboard manually or via launchd:

```bash
PYTHONPATH=src streamlit run src/app.py &
```

---

## Testing with AAPL (Smoke Test)

After code is complete and `init-db` / `bootstrap` have run, verify every step works:

```bash
cd ~/PROD/AIStock && source venv/bin/activate
python main.py run --symbol AAPL --force
```

Then verify in MySQL:

```sql
-- 1. Symbol loaded
SELECT symbol, exchange, is_active FROM stocks WHERE symbol = 'AAPL';

-- 2. Prices fetched
SELECT COUNT(*), MIN(date), MAX(date) FROM daily_prices dp
JOIN stocks s ON s.id = dp.stock_id WHERE s.symbol = 'AAPL';

-- 3. Fundamentals populated
SELECT pe_ratio, market_cap, roe_ttm FROM stock_indicators si
JOIN stocks s ON s.id = si.stock_id WHERE s.symbol = 'AAPL';

-- 4. Technical indicators computed
SELECT JSON_LENGTH(indicators), computed_at FROM technical_indicators ti
JOIN stocks s ON s.id = ti.stock_id WHERE s.symbol = 'AAPL'
ORDER BY date DESC LIMIT 1;

-- 5. Snapshots refreshed
SELECT rsi_14, sma_20, close FROM stock_snapshots ss
JOIN stocks s ON s.id = ss.stock_id WHERE s.symbol = 'AAPL';
```

Then open [http://localhost:8501](http://localhost:8501) and verify:
- **Lookup tab**: AAPL candlestick chart renders, metric cards populated
- **Technical Analysis tab**: RSI and MACD panels display correctly
- **Screener tab**: AAPL appears in results with no filters
- **Manager tab**: AAPL row visible, toggle active/inactive works

All checks must pass before enabling the production scheduler.

---

## Running the CLI

```bash
cd ~/PROD/AIStock && source venv/bin/activate

# Initialize database tables
python main.py init-db

# Full bootstrap (first time only)
python main.py bootstrap

# Run daily pipeline for all active stocks
python main.py run

# Run for a single symbol (bypass is_active check)
python main.py run --symbol AAPL --force

# Run with custom date range
python main.py run --symbol AAPL --start 2020-01-01 --end 2024-12-31
```

---

## Managing the Production Services

### Scheduler Daemon

```bash
# Check if scheduler is running (PID and exit code)
launchctl list | grep aistock
# Example output:  44333  0  com.aistock.scheduler
#                   ^^^^^  ^
#                   PID    exit code (0 = running OK)

# View scheduler logs
tail -f logs/scheduler_stdout.log
cat logs/scheduler_stderr.log

# Restart scheduler
launchctl unload ~/Library/LaunchAgents/com.aistock.scheduler.plist
launchctl load ~/Library/LaunchAgents/com.aistock.scheduler.plist

# Stop scheduler
launchctl unload ~/Library/LaunchAgents/com.aistock.scheduler.plist
```

### Check Scheduled Jobs (Next Run Times)

Query the APScheduler job store directly from MySQL:

```bash
cd ~/PROD/AIStock && source venv/bin/activate
.venv/bin/python -c "
import sys; sys.path.insert(0, 'src')
from datetime import datetime, timezone
from database import get_session
from sqlalchemy import text
s = get_session()
rows = s.execute(text('SELECT id, next_run_time FROM apscheduler_jobs ORDER BY next_run_time')).fetchall()
for r in rows:
    ts = datetime.fromtimestamp(r[1], tz=timezone.utc).astimezone()
    print(f'  {r[0]:30s}  next: {ts}')
s.close()
"
```

Example output:
```
  daily_pipeline                  next: 2026-05-12 00:30:00 CST
  weekly_symbols                  next: 2026-05-17 17:00:00 CST
```

### Job Run History (Web App)

Open the dashboard at [http://localhost:8501](http://localhost:8501) → **Navigation → Job History**.

Shows each scheduled job execution with job name, start time, end time, stocks updated, status, and error messages. Data comes from the `scheduled_job_runs` table.

### Dashboard (Streamlit)

```bash
# Check if dashboard is running
launchctl list | grep stockdb

# View dashboard logs
tail -f logs/app.log

# Restart dashboard
launchctl unload ~/Library/LaunchAgents/com.stockdb.app.plist
launchctl load ~/Library/LaunchAgents/com.stockdb.app.plist
```

---

## Running the Web App

```bash
cd ~/PROD/AIStock && source venv/bin/activate
PYTHONPATH=src streamlit run src/app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

> **Note:** If you cloned the repo and are running locally (not via launchd), use the command above. The `PYTHONPATH=src` prefix is required so Streamlit can resolve the `src/` imports correctly.

---

## Using the Web App

Open [http://localhost:8501](http://localhost:8501)

### Lookup Tab
Search for a stock by symbol. View candlestick chart with volume, metric cards (close price, PE ratio, market cap, volume), and a recent price table. Adjust date range in the sidebar.

### Technical Analysis Tab
Enter a symbol and select overlays (SMA, EMA, Bollinger Bands) and oscillators (RSI, MACD, Stochastic, ATR). Overlays appear on the price chart; oscillators display in separate sub-panels below.

### Screener Tab
Filter all active stocks by market cap, PE ratio, ROE, RSI range, beta, dividend yield, sector, and exchange. Click **Run Screen** to query the pre-computed `stock_snapshots` table. Export results to CSV.

### Manager Tab
View all stocks with their fundamental data. Filter by any criteria and use **Activate All Filtered** / **Deactivate All Filtered** to control which stocks are included in the daily pipeline. Only active stocks receive daily price and indicator updates.

---

## Architecture

See `docs/superpowers/specs/2026-04-26-stock-system-design.md` for the full design spec.
