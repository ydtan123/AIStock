"""Stock growth probability inference.

Provides two entry points:
- predict_stocks(symbols): score specific symbols with SHAP feature attribution
- run_batch_inference(): score all active stocks, persist to DB
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import xgboost as xgb
from sqlalchemy import text
from sqlalchemy.dialects.mysql import insert

from database import get_session
from model.feature_builder import FeatureBuilder, WINDOW_DAYS
from model.train import load_feature_columns, load_model
from models import Stock, StockPrediction

logger = logging.getLogger(__name__)


def _build_inference_features(stock_id: int, symbol: str) -> Optional[dict]:
    """Build feature vector for one stock from most recent 5 trading days."""
    session = get_session()
    try:
        prices = pd.read_sql(
            text(
                "SELECT date, open, high, low, close, volume "
                "FROM daily_prices WHERE stock_id = :sid ORDER BY date DESC LIMIT :n"
            ),
            session.bind,
            params={"sid": stock_id, "n": WINDOW_DAYS},
        )

        tech_rows = session.execute(
            text(
                "SELECT date, indicators FROM technical_indicators "
                "WHERE stock_id = :sid ORDER BY date DESC LIMIT :n"
            ),
            {"sid": stock_id, "n": WINDOW_DAYS},
        ).fetchall()

        stock = session.query(Stock).filter_by(id=stock_id).first()
        sector = stock.sector if stock else None
    finally:
        session.close()

    if len(prices) < WINDOW_DAYS:
        return None

    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values("date").reset_index(drop=True)

    first_close = float(prices["close"].iloc[0])
    if first_close <= 0:
        return None

    builder = FeatureBuilder.default()
    tech_lookup = builder.parse_tech_rows(tech_rows)
    input_end_date = prices["date"].iloc[-1].date()
    features = builder.build_window(prices, tech_lookup, sector)

    return {"features": features, "input_end_date": input_end_date, "symbol": symbol}


def _align_features(feature_dict: dict, feature_cols: list[str]) -> xgb.DMatrix:
    """One-hot encode sector, align to training columns, return DMatrix."""
    X = pd.DataFrame([feature_dict])
    X = pd.get_dummies(X, columns=["sector"], prefix="sector")
    X = X.reindex(columns=feature_cols, fill_value=0.0)
    return xgb.DMatrix(X)


def predict_stocks(symbols: list[str], top_n: int = 5) -> list[dict]:
    """Score specific stocks and return SHAP feature attribution per prediction.

    Returns list of result dicts, one per symbol:
      - probability: float [0, 1]
      - input_end_date: date of most recent price row used
      - top_positive: top_n features pushing prediction up (SHAP > 0)
      - top_negative: top_n features pulling prediction down (SHAP < 0)
      - error: str (only present on failure)
    """
    booster = load_model()
    if booster is None:
        raise RuntimeError("No trained model found. Run `python main.py train` first.")

    feature_cols = load_feature_columns()
    if not feature_cols:
        raise RuntimeError("No feature columns file. Run `python main.py train` first.")

    symbols_upper = [s.upper() for s in symbols]
    session = get_session()
    stock_map = {
        s.symbol: s
        for s in session.query(Stock).filter(Stock.symbol.in_(symbols_upper)).all()
    }
    session.close()

    results = []
    for sym in symbols_upper:
        stock = stock_map.get(sym)
        if not stock:
            results.append({"symbol": sym, "error": "symbol not found in DB"})
            continue

        feat_result = _build_inference_features(stock.id, sym)
        if feat_result is None:
            results.append({"symbol": sym, "error": "insufficient price data (need 5 trading days)"})
            continue

        dmatrix = _align_features(feat_result["features"], feature_cols)
        probability = float(booster.predict(dmatrix)[0])

        # SHAP contributions: shape (1, n_features + 1), last col = bias term
        contribs = booster.predict(dmatrix, pred_contribs=True)[0]
        bias = float(contribs[-1])
        feature_contribs = sorted(
            zip(feature_cols, contribs[:-1].tolist()),
            key=lambda x: x[1],
            reverse=True,
        )

        top_positive = [
            {"feature": f, "contribution": round(c, 4)}
            for f, c in feature_contribs[:top_n]
            if c > 0
        ]
        top_negative = [
            {"feature": f, "contribution": round(c, 4)}
            for f, c in reversed(feature_contribs[-top_n:])
            if c < 0
        ]

        results.append({
            "symbol": sym,
            "probability": probability,
            "input_end_date": feat_result["input_end_date"],
            "bias": round(bias, 4),
            "top_positive": top_positive,
            "top_negative": top_negative,
        })

    return results


def run_batch_inference() -> dict:
    """Score all active stocks and persist results to stock_predictions table."""
    booster = load_model()
    if booster is None:
        logger.error("No trained model found. Run model.train.train() first.")
        return {"error": "no model"}

    feature_cols = load_feature_columns()
    if not feature_cols:
        logger.error("No feature columns file found.")
        return {"error": "no feature columns"}

    session = get_session()
    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    session.close()

    logger.info("Running inference for %d active stocks...", len(stocks))

    rows = []
    skipped = 0

    for stock in stocks:
        result = _build_inference_features(stock.id, stock.symbol)
        if result is None:
            skipped += 1
            continue

        dmatrix = _align_features(result["features"], feature_cols)
        prob = float(booster.predict(dmatrix)[0])

        rows.append({
            "stock_id": stock.id,
            "probability": round(prob, 6),
            "input_end_date": result["input_end_date"],
            "predicted_at": datetime.now(timezone.utc),
        })

    session = get_session()
    try:
        for row in rows:
            stmt = insert(StockPrediction).values(**row).on_duplicate_key_update(
                probability=row["probability"],
                input_end_date=row["input_end_date"],
                predicted_at=row["predicted_at"],
            )
            session.execute(stmt)
        session.commit()
    finally:
        session.close()

    summary = {"predicted": len(rows), "skipped": skipped, "failed": 0}
    logger.info("Inference complete: %d predicted, %d skipped", len(rows), skipped)
    return summary
