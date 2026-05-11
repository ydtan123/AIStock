# FinRL ML Stock Selection — Developer Manual

## Table of Contents

1. [Overview](#1-overview)
2. [Stock Selection Strategy](#2-stock-selection-strategy)
   - 2.1 [Target Variable: y_return](#21-target-variable-y_return)
   - 2.2 [Sector Bucketing](#22-sector-bucketing)
   - 2.3 [Feature Engineering](#23-feature-engineering)
   - 2.4 [Model Competition](#24-model-competition)
   - 2.5 [Stock Selection and Weighting](#25-stock-selection-and-weighting)
3. [Code Architecture](#3-code-architecture)
   - 3.1 [Entry Points](#31-entry-points)
   - 3.2 [Module Map](#32-module-map)
   - 3.3 [Full Pipeline Walk-through](#33-full-pipeline-walk-through)
   - 3.4 [Predict-Only Mode](#34-predict-only-mode)
   - 3.5 [sys.path Hazard](#35-syspath-hazard)
4. [Data Sources and Ingestion](#4-data-sources-and-ingestion)
5. [Database Tables](#5-database-tables)
6. [Configuration and CLI Reference](#6-configuration-and-cli-reference)
7. [Maintenance Runbook](#7-maintenance-runbook)

---

## 1. Overview

The FinRL ML pipeline selects a diversified portfolio from the AIStock universe using
quarterly fundamental data. It answers the question: **which stocks are likely to
produce the highest return over the next quarter, controlling for sector exposure?**

The pipeline has two operating modes:

| Mode | Command | When to use |
|------|---------|-------------|
| **Full train** | `python src/finrl_pipeline.py --source AISTOCK_DB` | Quarterly, after new fundamental data arrives |
| **Predict-only** | `python src/finrl_pipeline.py --predict-only` | Any time — loads saved models, no retraining |

**Outputs:**

- `data/selection_report_YYYYMMDD.csv` — selected tickers with weights
- `data/ml_weights_sector.csv` — same data, consumed by dashboard
- `data/fundamentals.csv` — raw fundamental data used for the run
- `data/backtest_result_YYYYMMDD.json` — simple buy-and-hold backtest result
- `data/models/<bucket>_<model>_<timestamp>.pkl` — serialised model artifacts
- MySQL `selected_stocks` table — predictions with predicted returns, persisted for dashboard

The pipeline is entirely CLI-driven. There is no automated scheduling — run it manually
after each quarterly earnings season (typically February, May, August, November).

---

## 2. Stock Selection Strategy

### 2.1 Target Variable: y_return

The model predicts `y_return`: the **log return** a stock produces over one quarter,
measured from trade date T to trade date T+1.

**The calculation chain:**

```
datadate → tradedate → actual_tradedate → trade_price → y_return
```

| Step | Field | Definition | Example (AMD Q3 2025) |
|------|-------|-----------|----------------------|
| 1 | `datadate` | Quarter-end date of the financial report | 2025-09-30 |
| 2 | `tradedate` | First day of the month two months after `datadate` | 2025-12-01 |
| 3 | `actual_tradedate` | First NYSE trading day on or after `tradedate` | 2025-12-01 |
| 4 | `trade_price` | Adjusted close on `actual_tradedate` | 219.76 |
| 5 | `y_return` | `ln(next_trade_price / this_trade_price)` | ln(198.62 / 219.76) = -0.1011 |

**Quarter → tradedate mapping:**

| Quarter end | tradedate | Rationale |
|-------------|-----------|-----------|
| Mar 31 | Jun 1 (same year) | Q1 report publicly available by June |
| Jun 30 | Sep 1 (same year) | Q2 report available by September |
| Sep 30 | Dec 1 (same year) | Q3 report available by December |
| Dec 31 | Mar 1 (next year) | Q4 report available by March |

This 2-month lag avoids look-ahead bias: the model only uses information that was
publicly available at trade time.

`y_return` is pre-computed and stored in `quarterly_fundamentals`. It is **not**
computed at runtime by the pipeline.

---

### 2.2 Sector Bucketing

Stocks are divided into four buckets based on their GICS sector. This ensures the
model learns sector-specific return dynamics rather than training one global model that
is dominated by the largest sectors.

| Bucket | Sectors |
|--------|---------|
| `growth_tech` | Information Technology, Technology, Communication Services |
| `cyclical` | Consumer Discretionary, Consumer Cyclical, Financials, Financial Services, Industrials |
| `real_assets` | Energy, Materials, Basic Materials, Real Estate |
| `defensive` | Health Care, Healthcare, Consumer Staples, Consumer Defensive, Utilities |

A separate model competition runs for each bucket independently. ETFs (SPY, QQQ) have
no sector and are automatically excluded from ML training.

Sector matching uses case-insensitive comparison (`gsector.str.lower().map(SECTOR_TO_BUCKET)`).
Rows with unmapped sectors are dropped with a warning.

---

### 2.3 Feature Engineering

**23 fundamental features** are used (after removing three 0%-populated columns):

| Category | Features |
|----------|---------|
| Valuation (4) | `pe`, `ps`, `pb`, `ev_multiple` |
| Profitability (4) | `EPS`, `roe`, `gross_margin`, `operating_margin` |
| Cash Flow (5) | `fcf_per_share`, `cash_per_share`, `capex_per_share`, `fcf_to_ocf`, `ocf_ratio` |
| Leverage (3) | `debt_ratio`, `debt_to_equity`, `debt_to_mktcap` |
| Liquidity (1) | `cur_ratio` |
| Efficiency (2) | `acc_rec_turnover`, `asset_turnover` |
| Coverage (1) | `interest_coverage` |
| Dividend (1) | `dividend_yield` |
| Solvency (1) | `solvency_ratio` |
| Per-Share (1) | `BPS` |

**Dropped features** (zero DB coverage, always NULL):
- `peg` — PEG ratio not ingested
- `payables_turnover` — not ingested
- `debt_service_coverage` — not ingested

**Missing value handling:**

Before training, all NaN values in `FEATURE_COLS` are filled with the **per-bucket
training-set median**. Medians are computed from the training split only (not val or
infer) to prevent data leakage. `dividend_yield` is the most commonly sparse feature
(~55% populated); median imputation is appropriate because dividend-paying behaviour
is sector-correlated, and the bucket-level median captures that.

**Outlier clipping:**

In predict-only mode, each feature is clipped to [P1, P99] of the current bucket data
before inference. This prevents extreme values in new quarters from producing out-of-
distribution predictions.

**Scaling:**

All features are standardised with `StandardScaler`. The scaler is fit on the training
split and applied to validation and inference. The final model is retrained on
train+val before inference, using a fresh scaler fit on combined data.

---

### 2.4 Model Competition

Seven models compete per bucket. The winner is chosen by lowest **validation MSE**:

| # | Model | Key Parameters |
|---|-------|---------------|
| 1 | RandomForest | n_estimators=200, max_depth=8 |
| 2 | XGBoost | n_estimators=200, max_depth=6, lr=0.05 |
| 3 | LightGBM | n_estimators=200, max_depth=6, lr=0.05 |
| 4 | HistGradientBoosting | max_iter=200, max_depth=6, lr=0.05 |
| 5 | ExtraTrees | n_estimators=200, max_depth=8 |
| 6 | Ridge | alpha=1.0 (linear baseline) |
| 7 | Stacking | Top-3 by val MSE + Ridge meta-learner, cv=3 |

**Train / Val / Infer split:**

- **Train**: all quarters with `y_return` not null, up to and including `val_cutoff` (second-to-last unique datadate), excluding validation quarters.
- **Val**: last N quarters before `val_cutoff`, controlled by `--test-quarters` (default 20 quarters = 5 years).
- **Infer**: all quarters after `val_cutoff` (the latest quarter of data — this is what gets predicted).

After the competition, all models are retrained on train+val combined (using a fresh
scaler) before running inference. This maximises the data used for the final model.

---

### 2.5 Stock Selection and Weighting

After all buckets produce predictions:

1. Predictions from all buckets are concatenated.
2. Only the **latest inference datadate** is kept (most recent quarter).
3. Within each bucket, stocks are ranked by `predicted_return` descending.
4. The top `(1 - top_quantile)` fraction is selected per bucket.
   - Default: `top_quantile=0.75` → top 25% selected per bucket.
5. Weights are assigned based on `weight_method`:

| Method | Logic |
|--------|-------|
| `equal` (default) | `1 / n_selected` uniform across all selected stocks |
| `ml_score` | Proportional to `predicted_return` (clipped to ≥0), normalised to sum 1 |
| `inverse_volatility` | Falls back to equal (not yet implemented) |

Selected stocks, weights, predicted returns, and model metadata are persisted to
the `selected_stocks` MySQL table.

---

## 3. Code Architecture

### 3.1 Entry Points

```
# Full training pipeline
PYTHONPATH=src python src/finrl_pipeline.py \
    --source AISTOCK_DB \
    --start-date 2020-01-01 \
    --end-date 2025-12-31 \
    --top-quantile 0.75 \
    --test-quarters 20

# Predict-only (load saved models, no retraining)
PYTHONPATH=src python src/finrl_pipeline.py \
    --predict-only \
    --source AISTOCK_DB

# Predict for specific symbols only
PYTHONPATH=src python src/finrl_pipeline.py \
    --predict-only \
    --symbols AAPL MSFT NVDA
```

The pipeline can also be triggered from the AIStock Streamlit dashboard via the
**ML Pipeline** page, which runs it in a background thread and streams logs to the UI.

---

### 3.2 Module Map

```
AIStock project root
├── src/
│   ├── finrl_pipeline.py          # Main orchestrator (entry point)
│   └── ml_bucket_selector.py      # MLBucketSelector wrapper class
│
external/FinRL-Trading/src/
├── strategies/
│   └── ml_bucket_selection.py     # Core ML logic: FEATURE_COLS, SECTOR_TO_BUCKET, run_bucket()
└── data/
    └── data_fetcher.py            # AIStockDBSource: reads quarterly_fundamentals & daily_prices
```

**Responsibility split:**

| File | Owns |
|------|------|
| `finrl_pipeline.py` | Orchestration, CLI, DB persistence, backtest, sys.path setup |
| `ml_bucket_selector.py` | Wrapping `run_bucket()`, sector assignment, weight calculation |
| `ml_bucket_selection.py` | Feature constants, model definitions, train/val/infer logic |
| `data_fetcher.py` | SQL queries against AIStock MySQL DB |

---

### 3.3 Full Pipeline Walk-through

**Step 0 — sys.path setup** (`finrl_pipeline.py` module level)

AIStock `src/` is inserted at `sys.path[0]`. Then `config`, `database`, and
`repository` are pre-imported to lock them in `sys.modules`. This is critical
because `data_fetcher.py` unconditionally inserts `external/FinRL-Trading/src/`
at `sys.path[0]` on import, which would otherwise cause `import config` to resolve
to FinRL's config package instead of AIStock's `src/config.py`.

See [Section 3.5](#35-syspath-hazard) for full details.

---

**Step 1 — Initialise data source**

```python
data_source = create_data_source("aistock_db")  # → AIStockDBSource
```

`AIStockDBSource` connects to the AIStock MySQL DB via `StockRepository`. If
connection fails, it marks itself unavailable and all subsequent calls return empty
DataFrames.

---

**Step 2 — Fetch S&P 500 components**

```python
tickers_df = data_source.get_sp500_components()
```

Returns all stocks in the `stocks` table where `is_active=1` as a DataFrame with
columns `tickers` and `sectors`. This is the candidate universe.

---

**Step 3 — Fetch fundamental data**

```python
fund_df = data_source.get_fundamental_data(tickers_df, start_date, end_date)
```

Executes:

```sql
SELECT
    symbol AS tic,
    symbol AS gvkey,
    datadate,
    sector AS gsector,
    adj_close_q AS adj_close,
    pe, ps, pb, ev_multiple,
    EPS, roe, gross_margin, operating_margin,
    fcf_per_share, cash_per_share, capex_per_share,
    debt_ratio, debt_to_equity, debt_to_mktcap,
    cur_ratio, acc_rec_turnover, asset_turnover,
    interest_coverage, dividend_yield, solvency_ratio, BPS,
    -- plus raw cashflow fields for derived ratio computation
    y_return
FROM quarterly_fundamentals
WHERE symbol IN (:tickers) AND datadate BETWEEN :start AND :end
ORDER BY symbol, datadate
```

Three derived ratios (`fcf_to_ocf`, `ocf_ratio`, `solvency_ratio`) are computed
on the fly if not already present in the DB row.

---

**Step 4 — ML selection**

```python
selector = MLBucketSelector(top_quantile=0.75, test_quarters=20, weight_method="equal")
weights_df = selector.fit_predict(fund_df, save_models_dir="data/models/")
```

Inside `MLBucketSelector.fit_predict()`:

1. Sector column (`gsector`) is lowercased and mapped to bucket names via `SECTOR_TO_BUCKET`.
2. Unmapped rows (ETFs, unknown sectors) are dropped.
3. `val_cutoff` is set to the second-to-last unique `datadate`. The last unique datadate
   becomes the inference target.
4. For each bucket, `run_bucket()` is called:
   - Splits data into train / val / infer sets.
   - Fills NaN with per-bucket training-set medians.
   - Scales features with `StandardScaler`.
   - Runs the 7-model competition; picks winner by val MSE.
   - Retrains winner on train+val; runs inference on the latest quarter.
   - Serialises full artifact (scaler, all fitted models, feature list, best model name)
     to `data/models/<bucket>_<model>_<YYYYMMDDHHMM>.pkl`.
5. Predictions from all buckets are merged; top 25% per bucket selected by
   `predicted_return`.
6. Selected stock metadata is stored in `selector.selected_stocks_info`.

---

**Step 5 — Persist to DB**

```python
repo.save_selected_stocks(selector.selected_stocks_info)
```

Upserts into `selected_stocks` (DELETE-then-INSERT for the current run date). Columns
written: `ticker`, `bucket`, `model_name`, `ml_score` (= predicted_return), `weight`,
`date_selected`, `predicted_return`, `pipeline_run_at`.

---

**Step 6 — Backtest**

A simple buy-and-hold backtest is run over the full date range using the selected
stock weights. Benchmark returns (SPY, QQQ) are fetched from AIStock DB (both ETFs
are stored in `daily_prices`). Results are saved to
`data/backtest_result_YYYYMMDD.json`.

---

**Step 7 — Save report**

`data/selection_report_YYYYMMDD.csv` and `data/ml_weights_sector.csv` are written
with columns `date`, `gvkey` (ticker), `weight`.

---

### 3.4 Predict-Only Mode

`--predict-only` skips training entirely. It:

1. Scans `data/models/` for `.pkl` files. Filename pattern:
   `<bucket>_<model>_<YYYYMMDDHHMM>.pkl`. The **latest file per bucket** is used.
2. Loads each artifact: `scaler_full`, `fitted` (dict of models), `feature_cols`,
   `best_name`.
3. Resolves symbol list from `--symbols` CLI arg, or falls back to tickers in
   `selected_stocks` DB table.
4. Fetches latest fundamentals for those symbols from AIStock DB.
5. Maps sectors to buckets. Stocks with no matching bucket are excluded.
6. For each stock, uses its bucket's model to predict `y_return`:
   - Features clipped to [P1, P99].
   - NaN filled with per-bucket median (computed from the current batch, not training data).
   - Scaled with the saved `scaler_full`.
   - `best_model.predict(X_s)`.
7. Actual return is computed if the prediction date is in the past (compare price
   at `tradedate` to price at `tradedate + 1 quarter`).
8. Results persisted to `selected_stocks`.

---

### 3.5 sys.path Hazard

This is the most dangerous footgun in the codebase. **Do not change import ordering
in `finrl_pipeline.py` without understanding this.**

`external/FinRL-Trading/src/data/data_fetcher.py` contains:

```python
sys.path.insert(0, str(Path(__file__).parent.parent))  # inserts FinRL-Trading/src/
```

This runs at module import time. If `data_fetcher` is imported before AIStock's
`config`, `database`, or `repository` modules, Python will resolve:

```python
import config  # → resolves to external/FinRL-Trading/src/config/ (FinRL's package)
              # instead of src/config.py (AIStock's module) — WRONG
```

**The fix applied in `finrl_pipeline.py`:**

```python
# Module-level, before any FinRL imports:
sys.path.insert(0, str(_HERE))                    # AIStock src/ first
import config      # noqa — locks AIStock config in sys.modules
import database    # noqa — locks AIStock database in sys.modules
import repository  # noqa — locks AIStock repository in sys.modules

# Only then import FinRL modules (which will pollute sys.path):
from data.data_fetcher import create_data_source
```

Once a module is in `sys.modules`, subsequent `import config` calls return the cached
version regardless of `sys.path` order. The pre-import locks in the correct modules.

---

## 4. Data Sources and Ingestion

### Quarterly Fundamentals

**Table:** `quarterly_fundamentals`
**Populated by:** `scripts/ingest_quarterly_fundamentals.py`
**Frequency:** Manual, once per quarter after earnings season

```bash
# Full refresh (all active stocks, from 2010)
PYTHONPATH=src python scripts/ingest_quarterly_fundamentals.py

# Specific symbols only
PYTHONPATH=src python scripts/ingest_quarterly_fundamentals.py --symbols AAPL,MSFT,NVDA

# From a specific date
PYTHONPATH=src python scripts/ingest_quarterly_fundamentals.py --start 2023-01-01
```

The script fetches 4 Alpha Vantage endpoints per stock (INCOME_STATEMENT, BALANCE_SHEET,
CASH_FLOW, EARNINGS), computes ~30 financial ratios, aligns fiscal dates to
Mar/Jun/Sep/Dec 1st (MJSD convention), and computes `y_return`.

Approximate runtime: 500 stocks × 4 calls = 2,000 Alpha Vantage calls ≈ 27 minutes
(at 75 calls/min rate limit).

### Daily Prices

**Table:** `daily_prices`
**Populated by:** Scheduler → `job_daily_pipeline` → `run_daily_pipeline()`
**Frequency:** Automatically, weekdays at 9:30am PST

SPY and QQQ are stored here as regular symbols with null sector, used as
benchmarks in the backtest. They are excluded from ML training because GICS sector
mapping produces no bucket match.

---

## 5. Database Tables

### `quarterly_fundamentals`

Primary input table for the ML pipeline.

| Column | Type | Description |
|--------|------|-------------|
| `symbol` | VARCHAR | Stock ticker |
| `datadate` | DATE | Quarter-end date (aligned to Mar/Jun/Sep/Dec 1) |
| `sector` | VARCHAR | GICS sector (uppercase, e.g. "TECHNOLOGY") |
| `adj_close_q` | FLOAT | Adjusted close on tradedate |
| `y_return` | FLOAT | Log return from this tradedate to next tradedate |
| `pe`, `ps`, `pb`, ... | FLOAT | 23 fundamental feature columns |

Current state: 67,563 rows, 1,698 symbols, latest quarter 2026-06-01 (Q1 2026).

### `selected_stocks`

Output table. Stores the most recent ML selection results.

| Column | Type | Description |
|--------|------|-------------|
| `ticker` | VARCHAR | Stock symbol |
| `model_name` | VARCHAR | Best model name (e.g. "LightGBM", "Stacking") |
| `ml_score` | FLOAT | Equals `predicted_return` |
| `bucket` | VARCHAR | Sector bucket (`growth_tech`, etc.) |
| `weight` | FLOAT | Portfolio weight (sums to 1.0 across all selected) |
| `date_selected` | DATE | Tradedate of the inference quarter |
| `predicted_return` | FLOAT | Model's predicted log return |
| `actual_return` | FLOAT | Realised return (filled retroactively if date is past) |
| `pipeline_run_at` | DATETIME | When the pipeline ran |

Current state: 140 stocks from 2026-03-01 run.

### `job_status`

Tracks scheduled job execution history.

| Column | Description |
|--------|-------------|
| `job_name` | `daily_pipeline` or `symbol_refresh` |
| `started_at` | Job start time (UTC) |
| `finished_at` | Job end time (UTC) |
| `stocks_updated` | Number of symbols processed |
| `status` | `running`, `completed`, or `failed` |
| `error_message` | Error details if `status=failed` |

---

## 6. Configuration and CLI Reference

### `finrl_pipeline.py` CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--source` | `AISTOCK_DB` | Data source: `AISTOCK_DB`, `FMP`, `WRDS`, `YAHOO` |
| `--start-date` | `2020-01-01` | Earliest quarter to include in training |
| `--end-date` | `2025-12-31` | Latest quarter to include in training |
| `--top-quantile` | `0.75` | Bottom fraction to exclude per bucket (0.75 = keep top 25%) |
| `--test-quarters` | `20` | Validation window size in quarters |
| `--weight-method` | `equal` | `equal`, `ml_score`, or `inverse_volatility` |
| `--benchmarks` | `SPY QQQ` | Benchmark tickers for backtest |
| `--initial-capital` | `1000000` | Starting capital for backtest ($) |
| `--predict-only` | off | Load saved models; skip training |
| `--models-dir` | `data/models/` | Directory containing `.pkl` model artifacts |
| `--symbols` | from DB | Tickers to predict (predict-only mode only) |

### `config.yaml` Pipeline Section

The dashboard uses `config.yaml` to populate default values when running the pipeline
from the UI. Example:

```yaml
finrl:
  preferred_source: AISTOCK_DB
  start_date: "2020-01-01"
  top_quantile: 0.75
  test_quarters: 20
  weight_method: equal
  benchmarks:
    - SPY
    - QQQ
```

---

## 7. Maintenance Runbook

### Quarterly: Retrain models after earnings

```bash
# 1. Ingest new quarterly fundamentals (run after earnings season ends)
PYTHONPATH=src python scripts/ingest_quarterly_fundamentals.py

# 2. Verify new rows arrived
#    SELECT MAX(datadate), COUNT(*) FROM quarterly_fundamentals;

# 3. Retrain and predict
PYTHONPATH=src python src/finrl_pipeline.py \
    --source AISTOCK_DB \
    --start-date 2020-01-01 \
    --top-quantile 0.75 \
    --test-quarters 20

# 4. Verify predictions saved
#    SELECT date_selected, COUNT(*), AVG(predicted_return) FROM selected_stocks GROUP BY date_selected;
```

### Ad-hoc: Predict without retraining

```bash
PYTHONPATH=src python src/finrl_pipeline.py --predict-only
```

### Check scheduler health

```bash
# Is it running?
launchctl list | grep aistock

# Recent job history
#  SELECT * FROM job_status ORDER BY started_at DESC LIMIT 10;

# Latest price date
#  SELECT MAX(date) FROM daily_prices;

# Logs
tail -50 logs/scheduler_stdout.log
tail -50 logs/scheduler_stderr.log
```

### Add a new feature to FEATURE_COLS

1. Verify column coverage in `quarterly_fundamentals`:
   ```sql
   SELECT COUNT(*), SUM(CASE WHEN new_col IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) pct
   FROM quarterly_fundamentals;
   ```
2. If coverage < 50%: do not add. Fix ingestion first.
3. Add to `FEATURE_COLS` list in
   `external/FinRL-Trading/src/strategies/ml_bucket_selection.py`.
4. Delete old model `.pkl` files in `data/models/` (they were trained without the new feature).
5. Retrain: `python src/finrl_pipeline.py --source AISTOCK_DB ...`.

### Diagnose empty predictions

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `No tickers returned` | `stocks` table empty or DB connection failed | Check DB URL in `config.yaml` |
| `No fundamental data returned` | `quarterly_fundamentals` empty or no overlap with date range | Run `ingest_quarterly_fundamentals.py` |
| `All buckets returned empty predictions` | All buckets have < 20 training rows or no infer rows | Extend `--start-date` further back |
| `No model files in data/models/` | Full pipeline never run, or models deleted | Run without `--predict-only` |
| `gsector column required` | `AIStockDBSource` not returning sector | Verify `stocks.sector` populated |
