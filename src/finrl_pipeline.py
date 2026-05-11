"""
ML pipeline runner for the AIStock dashboard.

Wraps external/FinRL-Trading components to run the full ML stock selection
pipeline (fetch fundamentals → ML competition → backtest → save results).

All output files are saved to DATA_DIR (AIStock project root / data/).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Directories
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
DATA_DIR = _PROJECT_ROOT / "data"
MODELS_DIR = DATA_DIR / "models"

# AIStock src must be first so its config/database modules shadow FinRL's.
_aistock_src = str(_HERE)
if _aistock_src not in sys.path:
    sys.path.insert(0, _aistock_src)

# FinRL-Trading src appended after — must NOT precede AIStock src.
_finrl_src = str(_PROJECT_ROOT / "external" / "FinRL-Trading" / "src")
if _finrl_src not in sys.path:
    sys.path.append(_finrl_src)

# Pre-cache AIStock modules before data_fetcher.py pollutes sys.path at import time.
# data_fetcher.py inserts external/FinRL-Trading/src/ at position 0 unconditionally,
# which would make 'config' resolve to the FinRL config package instead of src/config.py.
# Pre-importing here ensures sys.modules caches the correct AIStock versions.
import config  # noqa: F401
import database  # noqa: F401
import repository  # noqa: F401


def run_pipeline_and_save_report(cfg_overrides: dict[str, Any]) -> str:
    """Run the ML stock selection pipeline and save results to DATA_DIR.

    Parameters
    ----------
    cfg_overrides:
        Pipeline configuration. Recognised keys:
        - preferred_source: str       (AISTOCK_DB | FMP | WRDS | YAHOO)
        - start_date: str             (YYYY-MM-DD)
        - end_date: str               (YYYY-MM-DD)
        - top_quantile: float         (0–1)
        - test_quarters: int
        - prediction_mode: str
        - weight_method: str
        - rebalance_freq: str         (Q | M | A)
        - initial_capital: float
        - benchmarks: list[str]       (default ["SPY", "QQQ"])

    Returns
    -------
    str
        Absolute path to the selection report CSV.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    preferred_source = cfg_overrides.get("preferred_source", "AISTOCK_DB")
    start_date = cfg_overrides.get("start_date", "2020-01-01")
    end_date = cfg_overrides.get("end_date", "2025-12-31")
    top_quantile = float(cfg_overrides.get("top_quantile", 0.75))
    test_quarters = int(cfg_overrides.get("test_quarters", 20))
    prediction_mode = cfg_overrides.get("prediction_mode", "regression")
    weight_method = cfg_overrides.get("weight_method", "equal")
    rebalance_freq = cfg_overrides.get("rebalance_freq", "Q")
    initial_capital = float(cfg_overrides.get("initial_capital", 1_000_000))
    benchmarks = list(cfg_overrides.get("benchmarks", ["SPY", "QQQ"]))

    logger.info("Step 1/4: Initialising data source (%s)...", preferred_source)
    from data.data_fetcher import create_data_source
    data_source = create_data_source(preferred_source.lower())

    logger.info("Step 2/4: Fetching S&P 500 components...")
    tickers_df = data_source.get_sp500_components()
    if tickers_df.empty:
        raise RuntimeError("No tickers returned from data source.")
    logger.info("  %d tickers loaded.", len(tickers_df))

    logger.info("Step 3/4: Fetching fundamental data (%s → %s)...", start_date, end_date)
    fund_df = data_source.get_fundamental_data(tickers_df, start_date, end_date)
    if fund_df.empty:
        raise RuntimeError("No fundamental data returned.")
    logger.info("  %d rows of fundamental data.", len(fund_df))

    # Save fundamentals
    fund_path = DATA_DIR / "fundamentals.csv"
    fund_df.to_csv(fund_path, index=False)
    logger.info("  Saved fundamentals → %s", fund_path)

    logger.info("Step 4/4: Running ML selection (top_quantile=%.2f, mode=%s)...",
                top_quantile, prediction_mode)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    selected_stocks_saved = 0
    try:
        from ml_bucket_selector import MLBucketSelector
        selector = MLBucketSelector(
            top_quantile=top_quantile,
            test_quarters=test_quarters,
            prediction_mode=prediction_mode,
            weight_method=weight_method,
        )
        weights_df = selector.fit_predict(fund_df, save_models_dir=str(MODELS_DIR))
        # Persist selected stocks to DB
        if hasattr(selector, "selected_stocks_info") and selector.selected_stocks_info:
            try:
                from repository import StockRepository
                repo = StockRepository()
                # Attach model file paths
                sm_by_bucket: dict[str, str] = {}
                for mp in selector.saved_models:
                    # Filename: <bucket>_<model>_YYYYMMDDHHMM.pkl
                    # Bucket may contain underscores (e.g. growth_tech).
                    parts = Path(mp).stem.rsplit("_", 2)  # bucket_parts, model, ts
                    bn = parts[0] if len(parts) == 3 else Path(mp).stem
                    sm_by_bucket[bn] = mp
                for rec in selector.selected_stocks_info:
                    b = rec.get("bucket", "")
                    rec["model_file"] = sm_by_bucket.get(b, "")
                selected_stocks_saved = repo.save_selected_stocks(selector.selected_stocks_info)
                logger.info("  Saved %d selected stocks to DB", selected_stocks_saved)
            except Exception as exc:
                logger.warning("Failed to save selected stocks to DB: %s", exc)
    except Exception as exc:
        logger.warning("ml_bucket_selection failed (%s); falling back to equal-weight.", exc)
        weights_df = _equal_weight_fallback(fund_df, tickers_df, top_quantile)

    # Save weights
    weights_path = DATA_DIR / "ml_weights_sector.csv"
    weights_df.to_csv(weights_path, index=False)
    logger.info("  Saved weights → %s", weights_path)

    # Run simple backtest
    logger.info("  Running backtest (benchmarks: %s)...", benchmarks)
    try:
        bt_result = _run_simple_backtest(
            data_source, tickers_df, weights_df,
            start_date, end_date, initial_capital, rebalance_freq,
            benchmarks=benchmarks,
        )
        bt_path = DATA_DIR / f"backtest_result_{date.today():%Y%m%d}.json"
        with open(bt_path, "w") as f:
            json.dump(bt_result, f, default=str)
        logger.info("  Saved backtest → %s", bt_path)
    except Exception as exc:
        logger.warning("Backtest failed: %s", exc)

    # Save selection report
    report_path = DATA_DIR / f"selection_report_{date.today():%Y%m%d}.csv"
    weights_df.to_csv(report_path, index=False)
    logger.info("Pipeline complete. Report: %s", report_path)
    return str(report_path)


def _equal_weight_fallback(fund_df, tickers_df, top_quantile: float):
    """Return a simple equal-weight DataFrame when ML selector is unavailable."""
    import pandas as pd

    tickers = tickers_df["tickers"].dropna().unique()
    n_select = max(1, int(len(tickers) * (1 - top_quantile)))
    selected = tickers[:n_select]
    weight = 1.0 / max(len(selected), 1)
    today = str(date.today())
    return pd.DataFrame({
        "date": today,
        "gvkey": selected,
        "weight": weight,
    })


def _run_simple_backtest(
    data_source,
    tickers_df,
    weights_df,
    start_date: str,
    end_date: str,
    initial_capital: float,
    rebalance_freq: str,
    benchmarks: list[str] | None = None,
) -> dict:
    """Minimal backtest: buy-and-hold selected stocks at equal weight."""
    import numpy as np
    import pandas as pd

    if benchmarks is None:
        benchmarks = ["SPY", "QQQ"]

    empty = {"portfolio_values": {}, "metrics": {}, "benchmark_values": {}, "benchmark_metrics": {}}

    gvkeys = weights_df["gvkey"].dropna().unique().tolist()
    if not gvkeys:
        return empty

    # Fetch portfolio price data
    try:
        subset = tickers_df[tickers_df["tickers"].isin(gvkeys)]
        prices = data_source.get_price_data(subset, start_date, end_date)
    except Exception:
        return empty

    if prices.empty or "adj_close" not in prices.columns:
        return empty

    # Pivot to wide, fill forward, compute equal-weight portfolio
    pivot = prices.pivot_table(index="datadate", columns="tic", values="adj_close")
    pivot = pivot.ffill().dropna(how="all")
    if pivot.empty:
        return empty

    returns = pivot.pct_change().fillna(0)
    port_returns = returns.mean(axis=1)
    cum = (1 + port_returns).cumprod()
    portfolio_values = (cum * initial_capital).round(2)
    pv_dict = {str(k): float(v) for k, v in portfolio_values.items()}
    metrics = _compute_metrics(port_returns)

    # Fetch benchmark price data
    benchmark_values: dict = {}
    benchmark_metrics: dict = {}
    for bm in benchmarks:
        try:
            bm_df = pd.DataFrame({"tickers": [bm]})
            bm_prices = data_source.get_price_data(bm_df, start_date, end_date)
            if bm_prices.empty or "adj_close" not in bm_prices.columns:
                logger.warning("No price data for benchmark %s", bm)
                continue
            bm_pivot = bm_prices.pivot_table(index="datadate", columns="tic", values="adj_close")
            bm_pivot = bm_pivot.ffill().dropna(how="all")
            if bm_pivot.empty:
                continue
            bm_returns = bm_pivot.pct_change().fillna(0).mean(axis=1)
            bm_cum = (1 + bm_returns).cumprod()
            bm_vals = (bm_cum * initial_capital).round(2)
            benchmark_values[bm] = {str(k): float(v) for k, v in bm_vals.items()}
            benchmark_metrics[bm] = _compute_metrics(bm_returns)
            logger.info("  Benchmark %s: %.2f%% annual return", bm,
                        benchmark_metrics[bm].get("annual_return", 0) * 100)
        except Exception as exc:
            logger.warning("Benchmark %s failed: %s", bm, exc)

    return {
        "portfolio_values": pv_dict,
        "metrics": metrics,
        "benchmark_values": benchmark_values,
        "benchmark_metrics": benchmark_metrics,
    }


def run_predict_only(symbols: list[str] | None = None,
                     source: str = "AISTOCK_DB",
                     models_dir: str | None = None) -> pd.DataFrame:
    """Load latest model per bucket and predict each stock with its sector's model.

    Parameters
    ----------
    symbols : list[str] or None
        Tickers to predict. If None, loads from selected_stocks DB table.
    source : str
        Data source identifier.
    models_dir : str or None
        Directory of joblib model files. Default: data/models/

    Returns
    -------
    pd.DataFrame with columns: ticker, predicted_return, model_name, bucket
    """
    import glob
    import joblib

    if models_dir is None:
        models_dir = str(MODELS_DIR)

    # Discover latest model per bucket
    model_files = sorted(glob.glob(os.path.join(models_dir, "*.pkl")))
    if not model_files:
        raise FileNotFoundError(f"No model files in {models_dir}")

    bucket_models: dict[str, dict] = {}
    for mp in model_files:
        artifact = joblib.load(mp)
        b = artifact.get("bucket", "unknown")
        mtime = os.path.getmtime(mp)
        if b not in bucket_models or mtime > os.path.getmtime(bucket_models[b]["path"]):
            bucket_models[b] = {"path": mp, "artifact": artifact}

    logger.info("Loaded %d bucket models from %s: %s",
                len(bucket_models), models_dir,
                [(b, m["artifact"]["best_name"]) for b, m in bucket_models.items()])

    # Resolve symbols
    if not symbols:
        from repository import StockRepository
        repo = StockRepository()
        rows = repo.get_latest_selected_stocks()
        symbols = [r["ticker"] for r in rows]
        if not symbols:
            raise ValueError("No symbols found in selected_stocks table. "
                             "Run the full pipeline first or specify --symbols.")
    logger.info("Predicting for %d symbols", len(symbols))

    # Fetch fundamentals (must include gsector for bucket mapping)
    from data.data_fetcher import create_data_source
    import pandas as pd
    data_source = create_data_source(source.lower())
    tickers_df = pd.DataFrame({"tickers": symbols})
    end_date_str = date.today().strftime("%Y-%m-%d")
    fund_df = data_source.get_fundamental_data(tickers_df, "2020-01-01", end_date_str)
    if fund_df.empty:
        raise RuntimeError(f"No fundamental data returned for {len(symbols)} symbols")

    # Preprocess
    df = fund_df.copy()
    df["datadate"] = pd.to_datetime(df["datadate"]).dt.strftime("%Y-%m-%d")

    tic_col = next((c for c in ["tic", "ticker"] if c in df.columns), None)
    if tic_col and tic_col != "tic":
        df["tic"] = df[tic_col]

    # Derive missing columns (needed by all models)
    if "fcf_to_ocf" not in df.columns:
        ocf = df.get("operating_cashflow", pd.Series(dtype=float))
        fcf = df.get("free_cash_flow", pd.Series(dtype=float))
        df["fcf_to_ocf"] = fcf / ocf.replace(0, float("nan"))
    if "ocf_ratio" not in df.columns:
        rev = df.get("total_revenue", pd.Series(dtype=float))
        ocf = df.get("operating_cashflow", pd.Series(dtype=float))
        df["ocf_ratio"] = ocf / rev.replace(0, float("nan"))
    if "solvency_ratio" not in df.columns:
        ni = df.get("net_income", pd.Series(dtype=float))
        ta = df.get("total_assets", pd.Series(dtype=float))
        df["solvency_ratio"] = ni / ta.replace(0, float("nan"))

    # Map sectors to buckets
    from strategies.ml_bucket_selection import SECTOR_TO_BUCKET
    if "gsector" not in df.columns:
        raise RuntimeError("gsector column required for bucket mapping but not in fundamentals")
    df["bucket"] = df["gsector"].str.lower().map(SECTOR_TO_BUCKET)
    n_unmapped = df["bucket"].isna().sum()
    if n_unmapped:
        logger.warning("%d rows with unmapped gsector — excluded from prediction", n_unmapped)
    df = df[df["bucket"].notna()]
    if df.empty:
        raise RuntimeError("No stocks mapped to any bucket after sector mapping")

    # Keep latest datadate per symbol
    df = df.sort_values(["tic", "datadate"]).drop_duplicates(subset="tic", keep="last")

    # Union of all feature columns across models
    first_artifact = next(iter(bucket_models.values()))["artifact"]
    all_feature_cols = first_artifact["feature_cols"]

    for col in all_feature_cols:
        if col not in df.columns:
            df[col] = float("nan")
        if df[col].isna().any():
            median = df[col].median()
            df[col] = df[col].fillna(median if pd.notna(median) else 0.0)

    # Predict per bucket with matching model
    all_results: list[pd.DataFrame] = []
    for bucket_key, bm in bucket_models.items():
        bdf = df[df["bucket"] == bucket_key]
        if bdf.empty:
            logger.info("Bucket '%s': no stocks to predict", bucket_key)
            continue

        artifact = bm["artifact"]
        feature_cols = artifact["feature_cols"]
        scaler_full = artifact["scaler_full"]
        fitted = artifact["fitted"]
        best_name = artifact["best_name"]
        best_model = fitted[best_name]

        # Clip features for this bucket
        for col in feature_cols:
            if col in bdf.columns:
                p01, p99 = bdf[col].quantile(0.01), bdf[col].quantile(0.99)
                bdf[col] = bdf[col].clip(lower=p01, upper=p99)
        bdf[feature_cols] = bdf[feature_cols].fillna(0).replace([np.inf, -np.inf], 0)

        X = bdf[feature_cols]
        X_s = pd.DataFrame(scaler_full.transform(X), columns=feature_cols, index=X.index)
        predictions = best_model.predict(X_s)

        result = pd.DataFrame({
            "ticker": bdf["tic"].values,
            "predicted_return": predictions,
            "model_name": best_name,
            "bucket": bucket_key,
            "datadate": bdf["datadate"].values,
        })
        all_results.append(result)
        logger.info("Bucket '%s': predicted %d stocks with %s", bucket_key, len(result), best_name)

    if not all_results:
        raise RuntimeError("No stocks could be predicted — all buckets empty")

    result = pd.concat(all_results, ignore_index=True)
    result = result.sort_values("predicted_return", ascending=False)
    logger.info("Predicted %d stocks across %d buckets", len(result), len(all_results))
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="AIStock ML pipeline runner")
    parser.add_argument("--source", default="AISTOCK_DB",
                        choices=["AISTOCK_DB", "FMP", "WRDS", "YAHOO"],
                        help="Data source (default: AISTOCK_DB)")
    parser.add_argument("--start-date", default="2020-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", default="2025-12-31", help="End date YYYY-MM-DD")
    parser.add_argument("--top-quantile", type=float, default=0.75,
                        help="Top fraction to select per sector bucket (default: 0.75)")
    parser.add_argument("--test-quarters", type=int, default=20,
                        help="Walk-forward validation window in quarters (default: 20)")
    parser.add_argument("--prediction-mode", default="regression",
                        choices=["regression", "classification", "ensemble", "rolling", "single"])
    parser.add_argument("--weight-method", default="equal",
                        choices=["equal", "inverse_volatility", "ml_score"])
    parser.add_argument("--rebalance-freq", default="Q", choices=["Q", "M", "A"])
    parser.add_argument("--initial-capital", type=float, default=1_000_000,
                        help="Initial portfolio value for backtest (default: 1000000)")
    parser.add_argument("--benchmarks", nargs="+", default=["SPY", "QQQ"],
                        metavar="TICKER", help="Benchmark tickers (default: SPY QQQ)")
    parser.add_argument("--predict-only", action="store_true",
                        help="Load saved model and predict without training")
    parser.add_argument("--model", default=None,
                        help="(deprecated) Use --models-dir instead")
    parser.add_argument("--models-dir", default=None,
                        help="Directory of model .pkl files (default: data/models/)")
    parser.add_argument("--symbols", nargs="*", default=None,
                        metavar="TICKER",
                        help="Tickers to predict (default: from selected_stocks DB table)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.predict_only:
        symbols = args.symbols if args.symbols else None
        models_dir = args.models_dir or args.model  # --model still works for single file
        pred_df = run_predict_only(symbols=symbols, source=args.source, models_dir=models_dir)
        print(f"\nPredictions ({len(pred_df)} stocks, {pred_df['bucket'].nunique()} buckets):")
        print(pred_df.to_string(index=False))
        # Save to data/
        out_path = DATA_DIR / f"predict_only_{date.today():%Y%m%d}.csv"
        pred_df.to_csv(out_path, index=False)
        print(f"\nSaved: {out_path}")
        # Compute actual returns from prediction date to today
        from datetime import date as _date, datetime as _datetime
        from repository import StockRepository
        repo = StockRepository()
        actual_returns: list = []
        for _, row in pred_df.iterrows():
            ticker = str(row["ticker"])
            ds = str(row["datadate"])
            dd = _datetime.strptime(ds[:10], "%Y-%m-%d").date()
            stock = repo.find_stock(ticker)
            if stock is None:
                actual_returns.append(None)
                continue
            prices = repo.get_prices(stock.id, dd, _date.today())
            if prices.empty or len(prices) < 2:
                actual_returns.append(None)
                continue
            sp = float(prices["adj_close"].iloc[0])
            ep = float(prices["adj_close"].iloc[-1])
            actual_returns.append(float((ep / sp) - 1) if sp > 0 else None)
        pred_df["actual_return"] = actual_returns
        n_actual = sum(1 for a in actual_returns if a is not None)
        print(f"Actual returns computed for {n_actual}/{len(pred_df)} stocks")
        # Persist to DB
        try:
            records = pred_df.assign(
                model_file=str(MODELS_DIR),
                ml_score=lambda d: d["predicted_return"],
            ).to_dict("records")
            n = repo.save_predict_only_results(records)
            print(f"Saved {n} predictions to selected_stocks table")
        except Exception as exc:
            logger.warning("Failed to save predictions to DB: %s", exc)
        return

    cfg = {
        "preferred_source": args.source,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "top_quantile": args.top_quantile,
        "test_quarters": args.test_quarters,
        "prediction_mode": args.prediction_mode,
        "weight_method": args.weight_method,
        "rebalance_freq": args.rebalance_freq,
        "initial_capital": args.initial_capital,
        "benchmarks": args.benchmarks,
    }

    report_path = run_pipeline_and_save_report(cfg)
    print(f"Report: {report_path}")


def _compute_metrics(returns) -> dict:
    import numpy as np

    if len(returns) < 2:
        return {}
    ann = float(returns.mean() * 252)
    vol = float(returns.std() * np.sqrt(252))
    sharpe = ann / vol if vol > 0 else 0.0
    cum = (1 + returns).cumprod()
    running_max = cum.expanding().max()
    dd = (cum - running_max) / running_max
    max_dd = float(dd.min())
    calmar = ann / abs(max_dd) if max_dd < 0 else 0.0
    return {
        "annual_return": ann,
        "annual_volatility": vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
    }


if __name__ == "__main__":
    main()
