# Stock Selection ML — Model Training & Architecture

## Overview

The stock selection stage (Step 2 of the 4-step pipeline) uses sector-based machine learning to rank stocks by predicted forward return. It runs per-sector-bucket models, selects the top quantile, and produces a weighted portfolio.

---

## Models

Every sector bucket trains all of these models, then selects the best:

| Model | Type | Notes |
|-------|------|-------|
| RandomForest | Tree ensemble | Bagging of decision trees |
| XGBoost | Gradient boosting | Regularized boosting with early stopping |
| LightGBM | Gradient boosting | Leaf-wise tree growth, fast |
| HistGradientBoosting | Gradient boosting | Histogram-based, sklearn native |
| ExtraTrees | Tree ensemble | Randomized splits, lower variance |
| Ridge | Linear | L2-regularized linear regression |
| Stacking | Ensemble | Combines best 3 base models via a meta-learner (Ridge) |

The **Stacking ensemble** uses the 3 best-performing base models (by validation MSE) as inputs to a Ridge meta-learner. The best model across all 7 is selected and **retrained on train+val** before making final predictions.

---

## Train / Validation / Test Split

Uses **walk-forward (rolling-origin) validation** with a configurable window:

```
config: test_quarters=20

|←—— train ——→| val |   slide 1Q → repeat 19 more times
Q1..QN-1       QN
```

For each quarter from `(latest - test_quarters)` to `(latest - 1)`:
1. **Train** on all prior quarters
2. **Validate** on the current quarter
3. Compute MSE for each model

This simulates real-world trading — only past data is available at decision time. After finding the best model, it is **retrained on the full train+val set** and used to predict on the **inference quarter** (e.g., 2026Q1).

Example from a recent run:
```
DEFENSIVE:   Train: 208 | Val: 1079 (20Q: 2021-03-01 ~ 2025-12-01) | Infer: 55
GROWTH_TECH: Train: 176 | Val: 899  (20Q: 2021-03-01 ~ 2025-12-01) | Infer: 45
CYCLICAL:    Train: 297 | Val: 1564 (20Q: 2021-03-01 ~ 2025-12-01) | Infer: 79
REAL_ASSETS: Train: 100 | Val: 500  (20Q: 2021-03-01 ~ 2025-12-01) | Infer: 25
```

---

## Features (~70 Financial Metrics)

Features are extracted from `quarterly_fundamentals` and `stock_indicators` tables. Key categories:

| Category | Example Features |
|----------|-----------------|
| Valuation | `pe`, `pb`, `ps`, `ev_multiple`, `peg_ratio` |
| Profitability | `roe`, `roa`, `gross_margin`, `operating_margin`, `net_margin` |
| Growth | `revenue_growth`, `earnings_growth`, `bps`, `fcf_per_share` |
| Leverage | `debt_to_equity`, `debt_ratio`, `debt_to_mktcap`, `cur_ratio` |
| Cash Flow | `ocf_ratio`, `fcf_to_ocf`, `asset_turnover` |
| Earnings Quality | `accruals_ratio`, `asset_turnover` |

Top features vary by bucket. Example from a recent run:

| Bucket | Top Feature | Importance |
|--------|------------|------------|
| DEFENSIVE | `asset_turnover` | 0.080 |
| GROWTH_TECH | `fcf_to_ocf` | 0.093 |
| CYCLICAL | `debt_to_mktcap` | 0.110 |
| REAL_ASSETS | `debt_to_mktcap` | 0.180 |

---

## Prediction Target

**Forward 1-quarter return** — the model predicts the % price return over the next quarter.

```
target = (price[t+1Q] - price[t]) / price[t]
```

Configuration:
```yaml
stock_selection:
  finrl:
    prediction_mode: "regression"   # regression | classification | ensemble | rolling | single
    top_quantile: 0.1              # top 10% per bucket selected
    test_quarters: 20              # walk-forward validation window
    weight_method: "equal"         # equal | inverse_volatility | ml_score
```

---

## Sector Buckets

Stocks are partitioned into 4 buckets via `SECTOR_TO_BUCKET` mapping (`external/FinRL-Trading/src/strategies/ml_bucket_selection.py`):

| Bucket | Sectors |
|--------|---------|
| **DEFENSIVE** | Healthcare, Utilities, Consumer Staples |
| **GROWTH_TECH** | Technology, Communication Services |
| **CYCLICAL** | Financials, Consumer Discretionary, Industrials |
| **REAL_ASSETS** | Energy, Materials, Real Estate |

Each bucket trains **independent models** — stocks are only compared against peers in the same sector group.

---

## Portfolio Construction

After scoring all stocks:
1. Top `top_quantile` (e.g., 10%) from each bucket are selected
2. Equal weight assigned to each selected stock
3. Selected stocks are persisted to `selected_stocks` table with `pipeline_run_id`, `ml_score`, `sector`, `bucket`, `weight`

The selected stocks feed into Step 3 (Fast Evaluation) and Step 4 (Deep Evaluation).

---

## Output Files

| File | Content |
|------|---------|
| `data/fundamentals.csv` | Raw fundamental data fetched for the run |
| `data/selection_report_*.csv` | Full stock rankings with scores |
| `data/selection_summary_*.json` | Summary of selected tickers |
| `data/ml_weights_sector.csv` | Portfolio weights per ticker |
| `data/backtest_result_*.json` | Backtest vs SPY/QQQ benchmarks |
| `data/models/<bucket>_<model>_*.pkl` | Serialized trained models |

---

## Backtesting

After selection, a simple backtest is run with benchmarks (default: SPY, QQQ):
- Rebalancing frequency: quarterly (`rebalance_freq: "Q"`)
- Initial capital: $1,000,000
- Compares strategy cumulative returns against benchmarks

---

## Related Files

| File | Role |
|------|------|
| `src/finrl_runner.py` | Orchestrates the ML pipeline (data → train → select → backtest) |
| `src/ml_bucket_selector.py` | `MLBucketSelector` class wrapping FinRL's `run_bucket()` |
| `src/pipeline/stock_selection.py` | `StockSelectionStep` — pipeline step calling the selector |
| `src/pipeline/backends/selectors.py` | `FinrlStockSelector` — reads universe config, calls finrl_runner |
| `external/FinRL-Trading/src/strategies/ml_bucket_selection.py` | Core ML: feature engineering, walk-forward CV, per-bucket models |
| `external/FinRL-Trading/src/data/data_fetcher.py` | Data source abstraction (AIStock DB, FMP, Yahoo, WRDS) |
