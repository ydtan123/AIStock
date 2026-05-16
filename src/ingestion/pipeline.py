import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.dialects.mysql import insert

from config import load_config
from database import get_session, get_engine
from fetcher.base import FetcherBase
from ingestion.indicators import compute_indicators
from ingestion.symbols import refresh_symbols
from models import DailyPrice, PipelineRun, Stock, StockIndicator, StockPrediction, StockSnapshot

logger = logging.getLogger(__name__)

DEFAULT_START = date(2010, 1, 1)
MAX_WORKERS = 5


def _get_max_price_date(session, stock_id: int) -> Optional[date]:
    result = session.execute(
        text("SELECT MAX(date) FROM daily_prices WHERE stock_id = :sid"),
        {"sid": stock_id},
    ).scalar()
    return result


def _fetch_and_store_prices(fetcher: FetcherBase, stock: Stock) -> tuple[int, Optional[date]]:
    """Fetch incremental prices for one stock. Returns (rows_inserted, new_max_date)."""
    session = get_session()
    try:
        max_date = _get_max_price_date(session, stock.id)
        start = (max_date + timedelta(days=1)) if max_date else DEFAULT_START
        end = date.today()

        if start > end:
            return 0, max_date

        df = fetcher.get_daily(stock.symbol, start, end)
        if df.empty:
            return 0, max_date

        values = []
        for _, row in df.iterrows():
            values.append({
                "stock_id": stock.id,
                "date": row["date"],
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "adj_close": row.get("adj_close"),
                "volume": row.get("volume"),
                "dividend_amount": row.get("dividend_amount"),
                "split_coefficient": row.get("split_coefficient"),
            })

        count = 0
        batch_size = 100
        for i in range(0, len(values), batch_size):
            batch = values[i:i + batch_size]
            for attempt in range(5):
                try:
                    for v in batch:
                        stmt = insert(DailyPrice).values(**v).on_duplicate_key_update(
                            open=v["open"],
                            high=v["high"],
                            low=v["low"],
                            close=v["close"],
                            adj_close=v["adj_close"],
                            volume=v["volume"],
                            dividend_amount=v["dividend_amount"],
                            split_coefficient=v["split_coefficient"],
                        )
                        session.execute(stmt)
                    session.commit()
                    count += len(batch)
                    break
                except Exception as e:
                    session.rollback()
                    if attempt < 4 and "1213" in str(e):
                        time.sleep(0.1 * (attempt + 1) + random.uniform(0, 0.1))
                        continue
                    raise

        return count, df["date"].max()
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()


def _upsert_fundamentals(fetcher: FetcherBase, stock: Stock, force: bool = False) -> bool:
    """Fetch and upsert OVERVIEW data. Skips if last_updated < refresh_days ago."""
    config = load_config()
    refresh_days = config.get("scheduler", {}).get("overview_refresh_days", 7)

    session = get_session()
    try:
        existing = session.query(StockIndicator).filter_by(stock_id=stock.id).first()
        if not force and existing and existing.last_updated:
            age = (datetime.utcnow() - existing.last_updated).days
            if age < refresh_days:
                return False

        data = fetcher.get_overview(stock.symbol)
        if not data:
            return False

        # Update stock metadata fields
        session.query(Stock).filter_by(id=stock.id).update({
            "name": data.get("name") or stock.name,
            "asset_type": data.get("asset_type") or stock.asset_type,
            "exchange": data.get("exchange") or stock.exchange,
            "currency": data.get("currency") or stock.currency,
            "country": data.get("country") or stock.country,
            "sector": data.get("sector") or stock.sector,
            "industry": data.get("industry") or stock.industry,
            "description": data.get("description") or stock.description,
            "cik": data.get("cik") or stock.cik,
            "official_site": data.get("official_site") or stock.official_site,
            "address": data.get("address") or stock.address,
            "fiscal_year_end": data.get("fiscal_year_end") or stock.fiscal_year_end,
            "shares_outstanding": data.get("shares_outstanding") or stock.shares_outstanding,
            "shares_float": data.get("shares_float") or stock.shares_float,
        })

        indicator_fields = {
            k: v for k, v in data.items()
            if k not in {"symbol", "name", "asset_type", "exchange", "currency", "country",
                         "sector", "industry", "description", "cik", "official_site",
                         "address", "fiscal_year_end", "shares_outstanding", "shares_float"}
        }
        indicator_fields["stock_id"] = stock.id
        indicator_fields["last_updated"] = datetime.utcnow()

        stmt = insert(StockIndicator).values(**indicator_fields).on_duplicate_key_update(
            **{k: v for k, v in indicator_fields.items() if k != "stock_id"}
        )
        # Retry on deadlock (1213) — common with concurrent upserts
        for attempt in range(3):
            try:
                session.execute(stmt)
                session.commit()
                break
            except Exception as e:
                session.rollback()
                if attempt < 2 and "1213" in str(e):
                    time.sleep(0.1 * (attempt + 1) + random.uniform(0, 0.05))
                    continue
                raise
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _refresh_snapshots():
    """Bulk refresh stock_snapshots from latest values across all active stocks."""
    engine = get_engine()
    sql = """
    REPLACE INTO stock_snapshots (
        stock_id, latest_date, close, volume,
        pe_ratio, market_cap, roe_ttm, dividend_yield, beta,
        rsi_14, macd, sma_20, sma_50,
        sector, exchange, updated_at
    )
    SELECT
        s.id,
        dp.date,
        dp.close,
        dp.volume,
        si.pe_ratio,
        si.market_cap,
        si.roe_ttm,
        si.dividend_yield,
        si.beta,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(ti.indicators, '$.RSI_14')), 'null') + 0,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(ti.indicators, '$.MACD_12_26_9')), 'null') + 0,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(ti.indicators, '$.SMA_20')), 'null') + 0,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(ti.indicators, '$.SMA_50')), 'null') + 0,
        s.sector,
        s.exchange,
        NOW()
    FROM stocks s
    JOIN (
        SELECT stock_id, MAX(date) AS max_date
        FROM daily_prices
        GROUP BY stock_id
    ) latest ON latest.stock_id = s.id
    JOIN daily_prices dp ON dp.stock_id = s.id AND dp.date = latest.max_date
    LEFT JOIN stock_indicators si ON si.stock_id = s.id
    LEFT JOIN (
        SELECT stock_id, MAX(date) AS max_date
        FROM technical_indicators
        GROUP BY stock_id
    ) latest_ti ON latest_ti.stock_id = s.id
    LEFT JOIN technical_indicators ti ON ti.stock_id = s.id AND ti.date = latest_ti.max_date
    WHERE s.is_active = 1
    """
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
    logger.info("Snapshots refreshed.")


def _update_checkpoint(stock_id: int):
    session = get_session()
    try:
        session.query(Stock).filter_by(id=stock_id).update({"last_price_fetch": datetime.utcnow()})
        session.commit()
    finally:
        session.close()


def _needs_full_backfill(stock_id: int) -> bool:
    """True if stock has no indicators or earliest indicator is far from earliest price."""
    session = get_session()
    try:
        row = session.execute(text("""
            SELECT MIN(ti.date)
            FROM technical_indicators ti
            WHERE ti.stock_id = :sid
        """), {"sid": stock_id}).first()
        first_ind = row[0] if row else None

        if first_ind is None:
            return True

        first_px = session.execute(text("""
            SELECT MIN(date) FROM daily_prices WHERE stock_id = :sid
        """), {"sid": stock_id}).scalar()

        if first_px is None:
            return False

        return (first_ind - first_px).days > 365
    finally:
        session.close()


def _upsert_prediction(stock_id: int, probability: float, input_end_date,
                      label_method: str = "max_high_5pct") -> None:
    row = {
        "stock_id": stock_id,
        "label_method": label_method,
        "probability": round(probability, 6),
        "input_end_date": input_end_date,
        "predicted_at": datetime.utcnow(),
    }
    session = get_session()
    try:
        stmt = insert(StockPrediction).values(**row).on_duplicate_key_update(
            probability=row["probability"],
            input_end_date=row["input_end_date"],
            predicted_at=row["predicted_at"],
        )
        session.execute(stmt)
        session.commit()
    finally:
        session.close()


def _process_symbol(fetcher: FetcherBase, stock: Stock, force: bool,
                    models: list | None = None) -> dict:
    """Process one symbol through the daily pipeline.

    models: list of (booster, feature_cols, label_method) tuples.
    """
    result = {"symbol": stock.symbol, "prices": 0, "fundamentals": False, "indicators": 0, "error": None}
    try:
        prices_inserted, new_max_date = _fetch_and_store_prices(fetcher, stock)
        result["prices"] = prices_inserted

        refreshed = _upsert_fundamentals(fetcher, stock, force=force)
        result["fundamentals"] = refreshed

        if _needs_full_backfill(stock.id):
            result["indicators"] = compute_indicators(stock.id, since_date=None)
        elif prices_inserted > 0 and new_max_date:
            result["indicators"] = compute_indicators(stock.id, since_date=new_max_date)

        # Predict with all available models
        if models:
            from model.inference import _build_inference_features, _align_features
            feat = _build_inference_features(stock.id, stock.symbol)
            if feat is not None:
                probs = {}
                for booster, feature_cols, label_method in models:
                    dmatrix = _align_features(feat["features"], feature_cols)
                    prob = float(booster.predict(dmatrix)[0])
                    _upsert_prediction(stock.id, prob, feat["input_end_date"], label_method)
                    probs[label_method] = round(prob, 4)
                result["probabilities"] = probs

        _update_checkpoint(stock.id)
        prob_str = ", ".join(f"{k}={v:.4f}" for k, v in result.get("probabilities", {}).items()) if "probabilities" in result else "-"
        logger.info(
            "%-6s  prices=%-4d  indicators=%-4d  overview=%-9s  probs=%s",
            stock.symbol, prices_inserted, result["indicators"],
            "refreshed" if refreshed else "skipped", prob_str,
        )

    except Exception as e:
        result["error"] = str(e)
        logger.error("Error processing %s: %s", stock.symbol, e)
    return result


def run_daily_pipeline(fetcher: FetcherBase, force: bool = False) -> dict:
    """Run the 5-step daily pipeline. Returns summary dict."""
    session = get_session()
    run = PipelineRun(started_at=datetime.utcnow(), status="running")
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    summary = {"processed": 0, "errors": 0, "symbols": []}

    try:
        session = get_session()
        stocks = (
            session.query(Stock)
            .outerjoin(StockIndicator, Stock.id == StockIndicator.stock_id)
            .filter(Stock.is_active == True)
            .order_by(StockIndicator.market_cap.desc())
            .all()
        )
        session.close()
        logger.info("Pipeline starting: %d active symbols", len(stocks))

        # Load all available models; workers share read-only boosters (thread-safe)
        from model.train import load_model, load_feature_columns
        from model.labels import LABEL_METHODS
        models = []
        for method in LABEL_METHODS:
            b = load_model(method.name)
            fc = load_feature_columns(method.name) if b is not None else None
            if b is not None and fc:
                models.append((b, fc, method.name))
            else:
                logger.warning("No trained model for %s — skipping", method.name)

        if not models:
            logger.warning("No trained models found — predict step will be skipped")

        total = len(stocks)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(_process_symbol, fetcher, s, force, models if models else None): s
                for s in stocks
            }
            for future in as_completed(futures):
                result = future.result()
                summary["processed"] += 1
                if result["error"]:
                    summary["errors"] += 1
                summary["symbols"].append(result)
                if summary["processed"] % 50 == 0 or summary["processed"] == total:
                    logger.info(
                        "Progress: %d/%d  errors=%d",
                        summary["processed"], total, summary["errors"],
                    )

        _refresh_snapshots()

    except Exception as e:
        logger.error("Pipeline failed: %s", e)
        summary["errors"] += 1
    finally:
        session = get_session()
        try:
            session.query(PipelineRun).filter_by(id=run_id).update({
                "finished_at": datetime.utcnow(),
                "symbols_processed": summary["processed"],
                "errors_count": summary["errors"],
                "status": "completed" if summary["errors"] == 0 else "completed_with_errors",
            })
            session.commit()
        finally:
            session.close()

    logger.info("Pipeline done. Processed=%d Errors=%d", summary["processed"], summary["errors"])
    return summary


def run_bootstrap(fetcher: FetcherBase, auto_activate_criteria: Optional[dict] = None):
    """First-time setup: fetch OVERVIEW for all symbols, optionally auto-activate."""
    session = get_session()
    stocks = session.query(Stock).all()
    session.close()

    logger.info("Bootstrap: fetching OVERVIEW for %d symbols", len(stocks))
    errors = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_upsert_fundamentals, fetcher, s, True): s for s in stocks}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                future.result()
            except Exception as e:
                logger.error("Bootstrap error: %s", e)
                errors += 1
            if i % 100 == 0:
                logger.info("Bootstrap progress: %d/%d", i, len(stocks))

    logger.info("Bootstrap complete. Errors=%d", errors)

    if auto_activate_criteria:
        _auto_activate(auto_activate_criteria)


def _auto_activate(criteria: dict):
    session = get_session()
    try:
        q = session.query(Stock).join(StockIndicator, Stock.id == StockIndicator.stock_id)
        if "min_market_cap" in criteria:
            q = q.filter(StockIndicator.market_cap >= criteria["min_market_cap"])
        if "exchanges" in criteria:
            q = q.filter(Stock.exchange.in_(criteria["exchanges"]))
        stocks = q.all()
        now = datetime.utcnow()
        for s in stocks:
            s.is_active = True
            s.activated_at = now
        session.commit()
        logger.info("Auto-activated %d stocks", len(stocks))
    finally:
        session.close()
