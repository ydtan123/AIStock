"""
ML pipeline runner — wraps external/FinRL-Trading for stock selection + backtest.

Extracted from the former finrl_pipeline.py entry point. Used by:
- app.py (ML Pipeline page via Full Pipeline)
- pipeline/backends/selectors.py (FinrlStockSelector)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime as dt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

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
import config  # noqa: F401
import database  # noqa: F401
import repository  # noqa: F401


def run_pipeline_and_save_report(cfg_overrides: dict[str, Any],
                                 universe_index: str | None = None) -> tuple[str, list[dict]]:
    """Run the ML stock selection pipeline and save results to DATA_DIR.

    Returns (report_csv_path, selected_stocks_info) where selected_stocks_info
    is a list of dicts: {ticker, bucket, ml_score, model_name, weight}.
    Empty list on fallback/error.

    Args:
        cfg_overrides: ML pipeline configuration overrides.
        universe_index: If set, restrict the stock universe to symbols in
            *universe_index* from the ``stocks_in_index`` table (e.g. "S&P 500").
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

    if universe_index:
        repo = repository.StockRepository()
        index_syms = set(repo.list_stocks_in_index(universe_index))
        if index_syms:
            before = len(tickers_df)
            tickers_df = tickers_df[tickers_df["tickers"].isin(index_syms)]
            logger.info(
                "  Universe '%s': filtered %d → %d tickers (%d in index, %d active)",
                universe_index, before, len(tickers_df),
                len(index_syms), len(tickers_df),
            )
        else:
            logger.warning(
                "  Universe '%s' returned 0 active symbols. "
                "Index may be empty or not yet populated. Proceeding unfiltered.",
                universe_index,
            )

    logger.info("Step 3/4: Fetching fundamental data (%s → %s)...", start_date, end_date)
    fund_df = data_source.get_fundamental_data(tickers_df, start_date, end_date)
    if fund_df.empty:
        raise RuntimeError("No fundamental data returned.")
    logger.info("  %d rows of fundamental data.", len(fund_df))

    fund_path = DATA_DIR / "fundamentals.csv"
    fund_df.to_csv(fund_path, index=False)
    logger.info("  Saved fundamentals → %s", fund_path)

    logger.info("Step 4/4: Running ML selection (top_quantile=%.2f, mode=%s)...",
                top_quantile, prediction_mode)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    selected_stocks_info: list[dict] = []
    try:
        from ml_bucket_selector import MLBucketSelector
        selector = MLBucketSelector(
            top_quantile=top_quantile,
            test_quarters=test_quarters,
            prediction_mode=prediction_mode,
            weight_method=weight_method,
        )
        weights_df = selector.fit_predict(fund_df, save_models_dir=str(MODELS_DIR))
        selected_stocks_info = list(getattr(selector, "selected_stocks_info", None) or [])
        if selected_stocks_info:
            try:
                saved_paths = getattr(selector, "saved_models", [])
                _summary = _build_selection_summary(selected_stocks_info, saved_paths)
                _sum_path = DATA_DIR / f"selection_summary_{date.today():%Y%m%d}.json"
                with open(_sum_path, "w") as _sf:
                    json.dump(_summary, _sf, default=str)
                logger.info("  Saved selection summary → %s", _sum_path)
            except Exception as exc:
                logger.warning("Failed to build selection summary: %s", exc)
    except Exception as exc:
        logger.warning("ml_bucket_selection failed (%s); falling back to equal-weight.", exc)
        weights_df = _equal_weight_fallback(fund_df, tickers_df, top_quantile)

    weights_path = DATA_DIR / "ml_weights_sector.csv"
    weights_df.to_csv(weights_path, index=False)
    logger.info("  Saved weights → %s", weights_path)

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

    report_path = DATA_DIR / f"selection_report_{date.today():%Y%m%d}.csv"
    weights_df.to_csv(report_path, index=False)
    logger.info("Pipeline complete. Report: %s", report_path)
    return str(report_path), selected_stocks_info


def run_predict_only(symbols: list[str] | None = None,
                     source: str = "AISTOCK_DB",
                     models_dir: str | None = None) -> pd.DataFrame:
    """Load latest model per bucket and predict each stock with its sector's model."""
    import glob
    import joblib

    if models_dir is None:
        models_dir = str(MODELS_DIR)

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

    if not symbols:
        from repository import StockRepository
        repo = StockRepository()
        rows = repo.get_latest_selected_stocks()
        symbols = [r["ticker"] for r in rows]
        if not symbols:
            raise ValueError("No symbols found in selected_stocks table.")

    logger.info("Predicting for %d symbols", len(symbols))

    from data.data_fetcher import create_data_source
    data_source = create_data_source(source.lower())
    tickers_df = pd.DataFrame({"tickers": symbols})
    end_date_str = date.today().strftime("%Y-%m-%d")
    fund_df = data_source.get_fundamental_data(tickers_df, "2020-01-01", end_date_str)
    if fund_df.empty:
        raise RuntimeError(f"No fundamental data returned for {len(symbols)} symbols")

    df = fund_df.copy()
    df["datadate"] = pd.to_datetime(df["datadate"]).dt.strftime("%Y-%m-%d")
    tic_col = next((c for c in ["tic", "ticker"] if c in df.columns), None)
    if tic_col and tic_col != "tic":
        df["tic"] = df[tic_col]

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

    df = df.sort_values(["tic", "datadate"]).drop_duplicates(subset="tic", keep="last")

    first_artifact = next(iter(bucket_models.values()))["artifact"]
    all_feature_cols = first_artifact["feature_cols"]
    for col in all_feature_cols:
        if col not in df.columns:
            df[col] = float("nan")
        if df[col].isna().any():
            median = df[col].median()
            df[col] = df[col].fillna(median if pd.notna(median) else 0.0)

    all_results: list[pd.DataFrame] = []
    for bucket_key, bm in bucket_models.items():
        bdf = df[df["bucket"] == bucket_key]
        if bdf.empty:
            logger.info("Bucket '%s': no stocks to predict", bucket_key)
            continue

        artifact = bm["artifact"]
        feature_cols = artifact["feature_cols"]
        scaler_full = artifact["scaler_full"]
        best_name = artifact["best_name"]
        best_model = artifact["fitted"][best_name]

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


# -- private helpers ------------------------------------------------------------

def _equal_weight_fallback(fund_df, tickers_df, top_quantile: float) -> pd.DataFrame:
    tickers = tickers_df["tickers"].dropna().unique()
    n_select = max(1, int(len(tickers) * (1 - top_quantile)))
    selected = tickers[:n_select]
    weight = 1.0 / max(len(selected), 1)
    today = str(date.today())
    return pd.DataFrame({"date": today, "gvkey": selected, "weight": weight})


def _run_simple_backtest(
    data_source, tickers_df, weights_df,
    start_date: str, end_date: str,
    initial_capital: float, rebalance_freq: str,
    benchmarks: list[str] | None = None,
) -> dict:
    if benchmarks is None:
        benchmarks = ["SPY", "QQQ"]

    empty = {"portfolio_values": {}, "metrics": {}, "benchmark_values": {}, "benchmark_metrics": {}}
    gvkeys = weights_df["gvkey"].dropna().unique().tolist()
    if not gvkeys:
        return empty

    try:
        subset = tickers_df[tickers_df["tickers"].isin(gvkeys)]
        prices = data_source.get_price_data(subset, start_date, end_date)
    except Exception:
        return empty

    if prices.empty or "adj_close" not in prices.columns:
        return empty

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
        except Exception as exc:
            logger.warning("Benchmark %s failed: %s", bm, exc)

    return {
        "portfolio_values": pv_dict,
        "metrics": metrics,
        "benchmark_values": benchmark_values,
        "benchmark_metrics": benchmark_metrics,
    }


def _compute_metrics(returns) -> dict:
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
        "annual_return": ann, "annual_volatility": vol,
        "sharpe_ratio": sharpe, "max_drawdown": max_dd,
        "calmar_ratio": calmar,
    }


def _build_selection_summary(selected_stocks_info: list, saved_model_paths: list) -> dict:
    import joblib

    bucket_top_feature: dict[str, str] = {}
    for mp in saved_model_paths:
        try:
            artifact = joblib.load(mp)
            bucket = artifact.get("bucket", "")
            feature_cols = artifact.get("feature_cols", [])
            best_name = artifact.get("best_name", "")
            model = artifact.get("fitted", {}).get(best_name)
            if model is None or not feature_cols:
                continue
            if hasattr(model, "feature_importances_"):
                importances = model.feature_importances_
            elif hasattr(model, "coef_"):
                c = model.coef_
                importances = np.abs(c[0] if c.ndim > 1 else c)
            else:
                continue
            if len(importances) == len(feature_cols):
                top_idx = int(np.argmax(importances))
                bucket_top_feature[bucket] = feature_cols[top_idx]
        except Exception:
            pass

    stocks = []
    for rec in selected_stocks_info:
        ticker = str(rec.get("ticker") or rec.get("tic") or rec.get("gvkey", ""))
        ml_score = float(rec.get("ml_score") or rec.get("predicted_return") or 0.0)
        bucket = rec.get("bucket", "")
        stocks.append({
            "ticker": ticker, "ml_score": ml_score, "bucket": bucket,
            "top_feature": bucket_top_feature.get(bucket, "N/A"),
        })

    stocks.sort(key=lambda x: x["ml_score"], reverse=True)
    return {"total": len(stocks), "stocks": stocks}
