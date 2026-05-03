"""Feature engineering and XGBoost training for stock growth prediction.

Generates rolling 5-day window samples from daily_prices + technical_indicators.
Persists features and labels to sample_features / sample_labels tables.
"""

import json
import logging
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score
from sqlalchemy import text
from sqlalchemy.dialects.mysql import insert as mysql_insert

from database import get_session
from model.feature_builder import FeatureBuilder
from model.labels import LABEL_METHODS, LabelMethod, compute_all_labels
from models import SampleFeature, SampleLabel, Stock

logger = logging.getLogger(__name__)

# --- config ---

MODEL_DIR = Path(__file__).parent / "artifacts"
FEATURE_COLS_FILE = MODEL_DIR / "feature_columns.json"
MODEL_FILE = MODEL_DIR / "xgb_model.pkl"
BATCH_SIZE = 500
MAX_WORKERS = 4

TRAIN_CUTOFF = date(2025, 1, 1)
VAL_CUTOFF = date(2026, 1, 1)



def _persist_stock_samples(
    stock_id: int,
    symbol: str,
    all_samples: list[dict],
    label_methods: list[LabelMethod],
) -> dict:
    """Persist computed samples to sample_features and sample_labels.

    - Features: INSERT IGNORE (skip if (stock_id, input_end_date) exists).
    - Labels: UPSERT per method, skipping rows already at current version.
    """
    if not all_samples:
        return {"symbol": symbol, "new_features": 0, "labels_updated": 0}

    session = get_session()
    try:
        existing_dates = set(
            r[0] for r in session.execute(
                text("SELECT input_end_date FROM sample_features WHERE stock_id = :sid"),
                {"sid": stock_id},
            ).fetchall()
        )

        new_samples = [s for s in all_samples if s["input_end_date"] not in existing_dates]

        if new_samples:
            feature_rows = [{
                "stock_id": stock_id,
                "input_end_date": s["input_end_date"],
                "features": s["features"],
                "sector": s["features"].get("sector", ""),
                "symbol": symbol,
                "computed_at": datetime.now(timezone.utc),
            } for s in new_samples]
            session.execute(
                mysql_insert(SampleFeature).values(feature_rows).prefix_with("IGNORE")
            )

        labels_updated = 0
        for method in label_methods:
            current_label_dates = set(
                r[0] for r in session.execute(
                    text(
                        "SELECT input_end_date FROM sample_labels "
                        "WHERE stock_id = :sid AND label_method = :m "
                        "AND label_version = :v AND label IS NOT NULL"
                    ),
                    {"sid": stock_id, "m": method.name, "v": method.version},
                ).fetchall()
            )

            label_rows = []
            for s in all_samples:
                label_val = s["labels"].get(method.name)
                if label_val is None:
                    continue
                if s["input_end_date"] in current_label_dates:
                    continue
                label_rows.append({
                    "stock_id": stock_id,
                    "input_end_date": s["input_end_date"],
                    "label_method": method.name,
                    "label": label_val,
                    "label_version": method.version,
                    "computed_at": datetime.now(timezone.utc),
                })

            if label_rows:
                for row in label_rows:
                    stmt = mysql_insert(SampleLabel).values(**row).on_duplicate_key_update(
                        label=row["label"],
                        label_version=row["label_version"],
                        computed_at=row["computed_at"],
                    )
                    session.execute(stmt)
                labels_updated += len(label_rows)

        session.commit()
        return {
            "symbol": symbol,
            "new_features": len(new_samples),
            "labels_updated": labels_updated,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def generate_and_persist_samples(label_methods: list[LabelMethod] | None = None) -> dict:
    """Generate feature+label samples for all active stocks, persist to DB.

    Processes stocks in batches to limit peak memory. Skips features
    already in sample_features. Updates labels when version changes.
    """
    from collections import defaultdict

    if label_methods is None:
        label_methods = LABEL_METHODS

    session = get_session()
    try:
        stocks = session.query(Stock).filter(Stock.is_active == True).all()
    finally:
        session.close()

    n = len(stocks)
    batches = [stocks[i:i + BATCH_SIZE] for i in range(0, n, BATCH_SIZE)]
    logger.info("Processing %d active stocks in %d batches of %d (workers=%d)",
                n, len(batches), BATCH_SIZE, MAX_WORKERS)

    total_new_features = 0
    total_labels_updated = 0

    for bi, batch_stocks in enumerate(batches):
        batch_ids = [s.id for s in batch_stocks]
        bid_tuple = tuple(batch_ids)
        logger.info("Batch %d/%d: %d stocks", bi + 1, len(batches), len(batch_stocks))

        session = get_session()
        try:
            batch_prices = pd.read_sql(
                text(
                    "SELECT stock_id, date, open, high, low, close, volume "
                    "FROM daily_prices WHERE stock_id IN :sids ORDER BY stock_id, date"
                ),
                session.bind,
                params={"sids": bid_tuple},
            )

            tech_rows = session.execute(
                text(
                    "SELECT stock_id, date, indicators "
                    "FROM technical_indicators WHERE stock_id IN :sids ORDER BY stock_id, date"
                ),
                {"sids": bid_tuple},
            ).fetchall()
        finally:
            session.close()

        tech_by_stock = defaultdict(list)
        for row in tech_rows:
            tech_by_stock[row[0]].append((row[1], row[2]))

        done = 0

        builder = FeatureBuilder.default()

        def _process_one(stock):
            sid = stock.id
            prices = batch_prices[batch_prices["stock_id"] == sid].drop(columns=["stock_id"])
            tech_data = tech_by_stock.get(sid, [])
            try:
                windows = builder.build_all_windows(prices, tech_data, stock.sector, stock.symbol)
                label_map = compute_all_labels(prices, label_methods, builder.window_days)
                samples = [{**w, "labels": label_map.get(w["input_end_date"], {})} for w in windows]
                return _persist_stock_samples(stock.id, stock.symbol, samples, label_methods)
            except Exception as e:
                logger.error("Sample generation failed for %s: %s", stock.symbol, e)
                return {"symbol": stock.symbol, "new_features": 0, "labels_updated": 0, "error": str(e)}

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_process_one, s): s for s in batch_stocks}
            for future in as_completed(futures):
                result = future.result()
                total_new_features += result["new_features"]
                total_labels_updated += result["labels_updated"]
                done += 1
                if done % 100 == 0:
                    logger.info("  %d/%d stocks, %d new features, %d labels updated",
                                done, len(batch_stocks), total_new_features, total_labels_updated)

        del batch_prices
        del tech_rows
        del tech_by_stock

    summary = {
        "stocks_processed": n,
        "new_features": total_new_features,
        "labels_updated": total_labels_updated,
    }
    logger.info("Sample generation complete: %d new features, %d labels updated",
                total_new_features, total_labels_updated)
    return summary


def _read_samples_from_db(label_method: str, max_rows: int | None = None) -> tuple[Path, Path, Path, Path, int]:
    """Stream samples from DB via SSCursor, split by date into 3 directories.

    Returns (train_dir, val_dir, test_dir, tmpdir, total_rows).
    Each directory contains parquet files with only that split's rows.
    Caller deletes tmpdir when done.
    """
    import tempfile

    session = get_session()
    conn = session.connection()
    conn.rollback()
    result = conn.execution_options(
        stream_results=True,
        max_row_buffer=30_000,
    ).execute(
        text(
            "SELECT sf.features, sl.label, sf.input_end_date, sf.symbol "
            "FROM sample_features sf "
            "JOIN sample_labels sl ON sl.stock_id = sf.stock_id "
            "AND sl.input_end_date = sf.input_end_date "
            "WHERE sl.label_method = :method AND sl.label IS NOT NULL"
        ),
        {"method": label_method},
    )

    tmpdir = Path(tempfile.mkdtemp(prefix="aistock_read_"))
    train_dir = tmpdir / "train"
    val_dir = tmpdir / "val"
    test_dir = tmpdir / "test"
    train_dir.mkdir(exist_ok=True)
    val_dir.mkdir(exist_ok=True)
    test_dir.mkdir(exist_ok=True)

    train_chunk: list[dict] = []
    val_chunk: list[dict] = []
    test_chunk: list[dict] = []
    chunk_size = 300_000
    train_idx = val_idx = test_idx = 0
    total = 0

    def _flush(chunk: list[dict], directory: Path, idx: int) -> int:
        if not chunk:
            return idx
        pdf = pd.DataFrame(chunk)
        pdf.to_parquet(directory / f"chunk_{idx:04d}.parquet", index=False)
        return idx + 1

    try:
        for row in result:
            features_raw = row[0]
            if isinstance(features_raw, str):
                features_raw = json.loads(features_raw)
            sample = features_raw if isinstance(features_raw, dict) else dict(features_raw)
            sample["label"] = row[1]
            sample["input_end_date"] = row[2]
            sample["symbol"] = row[3]
            total += 1

            inp_date = sample["input_end_date"]
            if inp_date < TRAIN_CUTOFF:
                train_chunk.append(sample)
            elif inp_date < VAL_CUTOFF:
                val_chunk.append(sample)
            else:
                test_chunk.append(sample)

            if max_rows is not None and total >= max_rows:
                break

            if len(train_chunk) >= chunk_size:
                train_idx = _flush(train_chunk, train_dir, train_idx)
                train_chunk = []
                if len(val_chunk) >= chunk_size // 2:
                    val_idx = _flush(val_chunk, val_dir, val_idx)
                    val_chunk = []
                if len(test_chunk) >= chunk_size // 2:
                    test_idx = _flush(test_chunk, test_dir, test_idx)
                    test_chunk = []
                logger.info("  Read %d samples (train:%d val:%d test:%d)",
                            total, train_idx, val_idx, test_idx)

        train_idx = _flush(train_chunk, train_dir, train_idx)
        val_idx = _flush(val_chunk, val_dir, val_idx)
        test_idx = _flush(test_chunk, test_dir, test_idx)

        logger.info("Streamed %d samples — train:%d files, val:%d files, test:%d files",
                    total, train_idx, val_idx, test_idx)
    finally:
        conn.close()
        session.close()

    return train_dir, val_dir, test_dir, tmpdir, total


def _get_canonical_feature_cols(train_dir: Path) -> list[str]:
    """Determine canonical feature columns from first train chunk + all sectors in DB."""
    first_file = next(iter(sorted(train_dir.glob("chunk_*.parquet"))), None)
    if first_file is None:
        raise RuntimeError("No parquet files in train_dir")

    df = pd.read_parquet(first_file)
    meta_cols = {"label", "input_end_date", "symbol", "sector"}
    numeric_cols = sorted(c for c in df.columns if c not in meta_cols)

    session = get_session()
    try:
        rows = session.execute(
            text("SELECT DISTINCT sector FROM sample_features WHERE sector IS NOT NULL AND sector != ''")
        ).fetchall()
    finally:
        session.close()

    sector_cols = sorted(f"sector_{row[0]}" for row in rows)
    return numeric_cols + sector_cols


def _process_chunk(fpath: Path, feature_cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Read one parquet file → (X: float32, y: int8) aligned to feature_cols."""
    df = pd.read_parquet(fpath)
    y = df["label"].astype(np.int8).to_numpy()

    meta_cols = ["label", "input_end_date", "symbol"]
    feat = df.drop(columns=[c for c in meta_cols if c in df.columns])
    feat = pd.get_dummies(feat, columns=["sector"], prefix="sector")
    feat = feat.fillna(0.0)

    for col in feature_cols:
        if col not in feat.columns:
            feat[col] = 0.0

    return feat[feature_cols].to_numpy(dtype=np.float32), y


class ParquetDataIter(xgb.DataIter):
    """XGBoost DataIter that reads train parquet chunks one at a time.

    XGBoost calls reset() + iterates twice when building QuantileDMatrix —
    parquet files must persist on disk until QuantileDMatrix construction completes.
    """

    def __init__(self, files: list[Path], feature_cols: list[str]) -> None:
        self._files = files
        self._feature_cols = feature_cols
        self._it = 0
        super().__init__()

    def next(self, input_data) -> int:
        if self._it >= len(self._files):
            return 0
        X, y = _process_chunk(self._files[self._it], self._feature_cols)
        input_data(data=X, label=y)
        self._it += 1
        return 1

    def reset(self) -> None:
        self._it = 0


def _count_labels_in_dir(directory: Path) -> tuple[int, int]:
    """Count (neg, pos) label totals. Reads label column only — fast."""
    neg = pos = 0
    for fpath in sorted(directory.glob("chunk_*.parquet")):
        labels = pd.read_parquet(fpath, columns=["label"])["label"].to_numpy()
        neg += int((labels == 0).sum())
        pos += int((labels == 1).sum())
    return neg, pos


def _load_split_to_arrays(
    directory: Path, feature_cols: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    """Load all parquet files in directory into (X: float32, y: int8) arrays."""
    files = sorted(directory.glob("chunk_*.parquet"))
    if not files:
        return np.empty((0, 0), dtype=np.float32), np.empty(0, dtype=np.int8)

    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    for fpath in files:
        X_chunk, y_chunk = _process_chunk(fpath, feature_cols)
        xs.append(X_chunk)
        ys.append(y_chunk)

    X = np.concatenate(xs) if len(xs) > 1 else xs[0]
    y = np.concatenate(ys) if len(ys) > 1 else ys[0]
    return X, y


def data_quality_report() -> dict:
    """Report data quality metrics for active stocks.

    Returns dict with: active/inactive counts, price coverage from 2010,
    indicator coverage vs earliest price.
    """
    from datetime import date as dt_date

    session = get_session()
    try:
        active = session.query(Stock).filter(Stock.is_active == True).count()
        inactive = session.query(Stock).filter(Stock.is_active == False).count()

        px_stats = session.execute(text("""
            SELECT
                COUNT(*) AS total_with_prices,
                MIN(earliest) AS min_earliest,
                SUM(earliest <= :cutoff) AS on_or_before_2010,
                SUM(earliest > :cutoff) AS after_2010
            FROM (
                SELECT s.id, MIN(dp.date) AS earliest
                FROM stocks s
                JOIN daily_prices dp ON dp.stock_id = s.id
                WHERE s.is_active = 1
                GROUP BY s.id
            ) t
        """), {"cutoff": dt_date(2010, 1, 2)}).fetchone()

        no_prices = session.execute(text("""
            SELECT COUNT(*) FROM stocks s
            WHERE s.is_active = 1
            AND NOT EXISTS (
                SELECT 1 FROM daily_prices dp WHERE dp.stock_id = s.id
            )
        """)).scalar()

        ind_stats = session.execute(text("""
            WITH price_min AS (
                SELECT s.id, s.symbol, MIN(dp.date) AS first_px
                FROM stocks s
                JOIN daily_prices dp ON dp.stock_id = s.id
                WHERE s.is_active = 1
                GROUP BY s.id
            ),
            ind_min AS (
                SELECT s.id, MIN(ti.date) AS first_ind
                FROM stocks s
                JOIN technical_indicators ti ON ti.stock_id = s.id
                WHERE s.is_active = 1
                GROUP BY s.id
            )
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN im.first_ind IS NULL THEN 1 ELSE 0 END) AS no_indicators,
                SUM(CASE WHEN im.first_ind IS NOT NULL
                    AND im.first_ind <= DATE_ADD(pm.first_px, INTERVAL 7 DAY)
                    THEN 1 ELSE 0 END) AS covered,
                SUM(CASE WHEN im.first_ind IS NOT NULL
                    AND im.first_ind > DATE_ADD(pm.first_px, INTERVAL 7 DAY)
                    THEN 1 ELSE 0 END) AS gap
            FROM price_min pm
            LEFT JOIN ind_min im ON im.id = pm.id
        """)).fetchone()

        worst_gaps = session.execute(text("""
            WITH price_min AS (
                SELECT s.id, s.symbol, MIN(dp.date) AS first_px
                FROM stocks s
                JOIN daily_prices dp ON dp.stock_id = s.id
                WHERE s.is_active = 1
                GROUP BY s.id
            ),
            ind_min AS (
                SELECT s.id, MIN(ti.date) AS first_ind
                FROM stocks s
                JOIN technical_indicators ti ON ti.stock_id = s.id
                WHERE s.is_active = 1
                GROUP BY s.id
            )
            SELECT pm.symbol, pm.first_px, im.first_ind,
                   DATEDIFF(im.first_ind, pm.first_px) AS gap_days
            FROM price_min pm
            JOIN ind_min im ON im.id = pm.id
            WHERE im.first_ind > DATE_ADD(pm.first_px, INTERVAL 7 DAY)
            ORDER BY gap_days DESC
            LIMIT 10
        """)).fetchall()

    finally:
        session.close()

    report = {
        "active_stocks": active,
        "inactive_stocks": inactive,
        "active_with_prices": px_stats[0],
        "active_no_prices": no_prices,
        "prices_earliest_date": str(px_stats[1]),
        "prices_from_2010_or_earlier": px_stats[2],
        "prices_after_2010": px_stats[3],
        "indicators_covered": ind_stats[2],
        "indicators_gap": ind_stats[3],
        "indicators_missing": ind_stats[1],
        "worst_gaps": [
            {"symbol": row[0], "first_price": str(row[1]), "first_indicator": str(row[2]), "gap_days": row[3]}
            for row in worst_gaps
        ],
    }

    logger.info("=== Data Quality Report ===")
    logger.info("Active stocks: %d  Inactive: %d  Total: %d",
                active, inactive, active + inactive)
    logger.info("Active with prices: %d  without prices: %d",
                px_stats[0], no_prices)
    logger.info("Prices from <=2010: %d  after 2010: %d  (earliest: %s)",
                px_stats[2], px_stats[3], px_stats[1])
    logger.info("Indicators: %d covering prices, %d with gap >7d, %d missing entirely",
                ind_stats[2], ind_stats[3], ind_stats[1])
    if worst_gaps:
        logger.info("Worst indicator gaps (days behind first price):")
        for row in worst_gaps:
            logger.info("  %s: %d days", row[0], row[3])

    return report


def _samples_up_to_date(label_method: str, label_version: str) -> bool:
    """Check whether sample_features and sample_labels are already populated."""
    session = get_session()
    try:
        feature_count = session.execute(
            text("SELECT COUNT(*) FROM sample_features")
        ).scalar()
        if feature_count == 0:
            return False
        label_count = session.execute(
            text(
                "SELECT COUNT(*) FROM sample_labels "
                "WHERE label_method = :method AND label_version = :version AND label IS NOT NULL"
            ),
            {"method": label_method, "version": label_version},
        ).scalar()
        return label_count > 0
    finally:
        session.close()


def train(
    label_method: str = "max_high_5pct",
    save: bool = True,
    skip_generate: bool = True,
    smoke_test: bool = False,
) -> dict:
    """Generate/persist samples, then train XGBoost. Returns metrics dict."""
    import shutil

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    method = next((m for m in LABEL_METHODS if m.name == label_method), None)
    if method is None:
        raise ValueError(f"Unknown label_method: {label_method}")

    if skip_generate and _samples_up_to_date(label_method, method.version):
        logger.info("Samples up to date, skipping generation")
    else:
        generate_and_persist_samples()

    max_rows = 10_000 if smoke_test else None
    train_dir, val_dir, test_dir, tmpdir, _ = _read_samples_from_db(label_method, max_rows=max_rows)

    try:
        feature_cols = _get_canonical_feature_cols(train_dir)
        logger.info("Feature columns: %d", len(feature_cols))

        train_files = sorted(train_dir.glob("chunk_*.parquet"))
        neg_count, pos_count = _count_labels_in_dir(train_dir)
        logger.info("Train label counts — neg: %d  pos: %d", neg_count, pos_count)

        # QuantileDMatrix reads each chunk via DataIter — never loads full train set.
        # XGBoost calls reset() + iterates twice internally; parquet files must
        # persist on disk until this call returns.
        dtrain = xgb.QuantileDMatrix(ParquetDataIter(train_files, feature_cols))

        X_val, y_val = _load_split_to_arrays(val_dir, feature_cols)
        X_test, y_test = _load_split_to_arrays(test_dir, feature_cols)
        logger.info("Val: %d  Test: %d  Features: %d", len(y_val), len(y_test), len(feature_cols))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0
    logger.info("scale_pos_weight: %.2f (neg=%d pos=%d)", scale_pos_weight, neg_count, pos_count)

    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "scale_pos_weight": scale_pos_weight,
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "seed": 42,
        "nthread": -1,
    }

    dval = xgb.DMatrix(X_val, label=y_val)
    booster = xgb.train(
        params,
        dtrain,
        num_boost_round=200,
        evals=[(dval, "val")],
        verbose_eval=50,
    )

    val_proba = booster.predict(dval)
    dtest = xgb.DMatrix(X_test, label=y_test)
    test_proba = booster.predict(dtest)

    val_auc = roc_auc_score(y_val, val_proba)
    test_auc = roc_auc_score(y_test, test_proba)

    train_total = neg_count + pos_count
    metrics = {
        "val_auc": float(val_auc),
        "test_auc": float(test_auc),
        "train_samples": train_total,
        "val_samples": int(len(X_val)),
        "test_samples": int(len(X_test)),
        "features": len(feature_cols),
        "pos_rate_train": float(pos_count / train_total) if train_total > 0 else 0.0,
        "pos_rate_val": float((y_val == 1).sum() / len(y_val)) if len(y_val) > 0 else 0.0,
        "pos_rate_test": float((y_test == 1).sum() / len(y_test)) if len(y_test) > 0 else 0.0,
    }

    logger.info("Val AUC: %.4f  Test AUC: %.4f", val_auc, test_auc)
    logger.info("Pos rate -- Train: %.3f  Val: %.3f  Test: %.3f",
                metrics["pos_rate_train"], metrics["pos_rate_val"], metrics["pos_rate_test"])

    if save:
        with open(FEATURE_COLS_FILE, "w") as f:
            json.dump({"columns": feature_cols}, f)
        with open(MODEL_FILE, "wb") as f:
            pickle.dump(booster, f)
        logger.info("Model saved to %s", MODEL_DIR)

    scores = booster.get_score(importance_type="weight")
    importances = pd.Series(scores).reindex(feature_cols, fill_value=0).sort_values(ascending=False)
    logger.info("Top 15 features:\n%s", importances.head(15).to_string())

    return metrics


def load_model() -> Optional[xgb.Booster]:
    """Load trained model from disk."""
    if not MODEL_FILE.exists():
        return None
    with open(MODEL_FILE, "rb") as f:
        return pickle.load(f)


def load_feature_columns() -> list[str]:
    """Load feature column names for inference alignment."""
    if not FEATURE_COLS_FILE.exists():
        return []
    with open(FEATURE_COLS_FILE) as f:
        return json.load(f)["columns"]
