"""Wrapper around external/FinRL-Trading ml_bucket_selection functions.

Provides the MLBucketSelector class expected by finrl_pipeline.py.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class MLBucketSelector:
    """Train per-sector ML models and return portfolio weights.

    Parameters
    ----------
    top_quantile : float
        Fraction of stocks to EXCLUDE (bottom). Top (1-top_quantile) are
        selected per bucket. e.g. 0.75 → top 25% selected.
    test_quarters : int
        Number of quarters used for validation window inside run_bucket.
    prediction_mode : str
        Ignored — always uses run_bucket regression ensemble.
    weight_method : str
        "equal" | "ml_score" | "inverse_volatility"
    """

    def __init__(
        self,
        top_quantile: float = 0.75,
        test_quarters: int = 3,
        prediction_mode: str = "regression",
        weight_method: str = "equal",
    ) -> None:
        self.top_quantile = top_quantile
        self.test_quarters = test_quarters
        self.prediction_mode = prediction_mode
        self.weight_method = weight_method

    def fit_predict(self, fund_df: pd.DataFrame, save_models_dir: str | None = None) -> pd.DataFrame:
        """Run ML selection and return weights DataFrame.

        Parameters
        ----------
        fund_df : pd.DataFrame
            Fundamentals from AIStockDBSource.get_fundamental_data().
            Must have columns: tic, datadate, gsector, y_return, + FEATURE_COLS.
        save_models_dir : str or None
            If set, serialise fitted models per bucket with joblib.

        Returns
        -------
        pd.DataFrame with columns: date, gvkey, weight
        DataFrame.attrs['saved_models'] = list of saved model file paths (if save_models_dir set).
        """
        from strategies.ml_bucket_selection import (
            FEATURE_COLS,
            SECTOR_TO_BUCKET,
            run_bucket,
        )

        df = fund_df.copy()

        # Normalise datadate to "YYYY-MM-DD" strings (run_bucket uses string comparison)
        df["datadate"] = pd.to_datetime(df["datadate"]).dt.strftime("%Y-%m-%d")

        # Derive computable columns before falling back to NaN
        if "fcf_to_ocf" not in df.columns:
            ocf = df.get("operating_cashflow", pd.Series(dtype=float))
            fcf = df.get("free_cash_flow", pd.Series(dtype=float))
            df["fcf_to_ocf"] = fcf / ocf.replace(0, float("nan"))

        if "ocf_ratio" not in df.columns:
            # OCF / total_revenue — common definition
            rev = df.get("total_revenue", pd.Series(dtype=float))
            ocf = df.get("operating_cashflow", pd.Series(dtype=float))
            df["ocf_ratio"] = ocf / rev.replace(0, float("nan"))

        if "solvency_ratio" not in df.columns:
            # net_income / total_assets — Altman-style proxy
            ni = df.get("net_income", pd.Series(dtype=float))
            ta = df.get("total_assets", pd.Series(dtype=float))
            df["solvency_ratio"] = ni / ta.replace(0, float("nan"))

        # Add still-missing FEATURE_COLS as NaN (will be median-imputed below)
        available_features = [c for c in FEATURE_COLS if c in df.columns]
        for col in FEATURE_COLS:
            if col not in df.columns:
                df[col] = float("nan")

        missing = set(FEATURE_COLS) - set(available_features)
        if missing:
            logger.warning("Missing %d feature cols (median-imputed): %s", len(missing), missing)

        # Median-impute all NaN in FEATURE_COLS — Ridge and Stacking cannot handle NaN
        for col in FEATURE_COLS:
            if df[col].isna().any():
                median = df[col].median()
                df[col] = df[col].fillna(median if pd.notna(median) else 0.0)

        # Assign sector buckets
        df["bucket"] = df["gsector"].str.lower().map(SECTOR_TO_BUCKET)
        n_unmapped = df["bucket"].isna().sum()
        if n_unmapped:
            logger.warning("%d rows have unmapped gsector → dropped", n_unmapped)
        df = df[df["bucket"].notna()].copy()

        if df.empty:
            raise ValueError("No rows remain after bucket assignment — check gsector values")

        # Determine val_cutoff: second-to-last unique datadate so there is at
        # least one future quarter for inference.
        unique_dates = sorted(df["datadate"].unique())
        if len(unique_dates) < 2:
            raise ValueError(f"Need ≥2 distinct datadates, got {len(unique_dates)}")
        val_cutoff = unique_dates[-2]
        logger.info("val_cutoff=%s, inference target=%s", val_cutoff, unique_dates[-1])

        # Run per-bucket ML
        all_preds: list[pd.DataFrame] = []
        saved_models: list[str] = []
        for bucket in df["bucket"].unique():
            bdf = df[df["bucket"] == bucket].copy()
            try:
                infer_b, _, _ = run_bucket(
                    bucket, bdf, FEATURE_COLS,
                    val_cutoff=val_cutoff,
                    val_quarters=self.test_quarters,
                    save_models_dir=save_models_dir,
                )
                if not infer_b.empty:
                    all_preds.append(infer_b)
                    sm = infer_b.attrs.get("saved_models", [])
                    saved_models.extend(sm)
            except Exception as exc:
                logger.warning("run_bucket failed for bucket '%s': %s", bucket, exc)

        if not all_preds:
            raise RuntimeError("All buckets returned empty predictions")

        preds = pd.concat(all_preds, ignore_index=True)

        # Keep only the latest inference date
        latest_date = preds["datadate"].max()
        preds = preds[preds["datadate"] == latest_date].copy()

        # Select top (1 - top_quantile) fraction per bucket by predicted_return
        selected_parts: list[pd.DataFrame] = []
        for bucket in preds["bucket"].unique():
            bp = preds[preds["bucket"] == bucket].sort_values(
                "predicted_return", ascending=False
            )
            n_select = max(1, int(len(bp) * (1.0 - self.top_quantile)))
            selected_parts.append(bp.head(n_select))

        selected = pd.concat(selected_parts, ignore_index=True)

        # Compute weights
        if self.weight_method == "ml_score":
            scores = selected["predicted_return"].clip(lower=0)
            total = scores.sum()
            selected = selected.copy()
            selected["weight"] = (scores / total).values if total > 0 else 1.0 / len(selected)
        else:  # equal or inverse_volatility (volatility data not available here)
            selected = selected.copy()
            selected["weight"] = 1.0 / len(selected)

        result = pd.DataFrame({
            "date": str(latest_date),
            "gvkey": selected["tic"].values,
            "weight": selected["weight"].values,
        })

        # Store metadata for external callers
        self.saved_models = saved_models
        selected_records = selected[["tic", "bucket", "predicted_return", "best_model"]].copy()
        selected_records.columns = ["ticker", "bucket", "ml_score", "model_name"]
        from datetime import date as _date
        selected_records["date_selected"] = _date.fromisoformat(latest_date)
        selected_records["weight"] = result["weight"].values
        self.selected_stocks_info = selected_records.to_dict("records")

        logger.info(
            "MLBucketSelector: %d stocks selected (latest=%s, method=%s)",
            len(result), latest_date, self.weight_method,
        )
        return result
