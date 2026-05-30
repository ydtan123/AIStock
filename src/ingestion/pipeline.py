import logging
import os
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
from models import DailyPrice, PipelineRun, Stock, StockIndicator, StockSnapshot

logger = logging.getLogger(__name__)

DEFAULT_START = date(2010, 1, 1)
MAX_WORKERS = 5
NEWS_LOOKBACK_DAYS = 7

# Export API keys from config BEFORE any tradingagents imports.
# tradingagents.dataflows.google reads os.getenv("GOOGLE_API_KEY").
_cfg = load_config()
_common = _cfg.get("common", {})
for _env_key, _cfg_key in [
    ("GOOGLE_API_KEY", "google_api_key"),
    ("DEEPSEEK_API_KEY", "deepseek_api_key"),
    ("OPENAI_API_KEY", "openai_api_key"),
    ("ANTHROPIC_API_KEY", "anthropic_api_key"),
]:
    if _common.get(_cfg_key) and _env_key not in os.environ:
        os.environ[_env_key] = _common[_cfg_key]

# Install DB-backed news cache BEFORE any tradingagents imports.
# After this, every route_to_vendor("get_news", ...) call reads/writes stock_news.
import news_cache  # noqa: E402
news_cache.install()


def _prefetch_stock_dates(stock_ids: list[int]) -> dict:
    """Batch-fetch all per-stock dates needed for skip decisions.

    Four queries in a single session replaces 4N individual queries
    when processing N stocks. Returns {stock_id: value_or_None}.
    """
    if not stock_ids:
        return {
            "max_price_dates": {},
            "first_indicator_dates": {},
            "first_price_dates": {},
            "indicator_last_updated": {},
        }
    session = get_session()
    try:
        ids = tuple(stock_ids)

        rows = session.execute(
            text("SELECT stock_id, MAX(date) FROM daily_prices WHERE stock_id IN :ids GROUP BY stock_id"),
            {"ids": ids},
        ).fetchall()
        max_price_dates = {r[0]: r[1] for r in rows}

        rows = session.execute(
            text("SELECT stock_id, MIN(date) FROM technical_indicators WHERE stock_id IN :ids GROUP BY stock_id"),
            {"ids": ids},
        ).fetchall()
        first_indicator_dates = {r[0]: r[1] for r in rows}

        rows = session.execute(
            text("SELECT stock_id, MIN(date) FROM daily_prices WHERE stock_id IN :ids GROUP BY stock_id"),
            {"ids": ids},
        ).fetchall()
        first_price_dates = {r[0]: r[1] for r in rows}

        rows = session.execute(
            text("SELECT stock_id, last_updated FROM stock_indicators WHERE stock_id IN :ids"),
            {"ids": ids},
        ).fetchall()
        indicator_last_updated = {r[0]: r[1] for r in rows}

        return {
            "max_price_dates": max_price_dates,
            "first_indicator_dates": first_indicator_dates,
            "first_price_dates": first_price_dates,
            "indicator_last_updated": indicator_last_updated,
        }
    finally:
        session.close()


def _fetch_and_store_prices(fetcher: FetcherBase, stock: Stock,
                            max_date: Optional[date] = None) -> tuple[int, Optional[date]]:
    """Fetch incremental prices for one stock. Returns (rows_inserted, new_max_date).

    When *max_date* is provided (from prefetch), skips the per-stock MAX(date)
    query and skips opening a session entirely if no fetch is needed.
    """
    start: date
    end = date.today()

    session = get_session()
    try:
        if max_date is None:
            max_date = session.execute(
                text("SELECT MAX(date) FROM daily_prices WHERE stock_id = :sid"),
                {"sid": stock.id},
            ).scalar()

        start = (max_date + timedelta(days=1)) if max_date else DEFAULT_START

        if start > end:
            return 0, max_date

        df = fetcher.get_daily(stock.symbol, start, end)
        if df.empty:
            return 0, max_date

        values = []
        for record in df.to_dict(orient="records"):
            record["stock_id"] = stock.id
            values.append(record)

        count = 0
        batch_size = 100
        for i in range(0, len(values), batch_size):
            batch = values[i:i + batch_size]
            for attempt in range(5):
                try:
                    stmt = insert(DailyPrice).values(batch)
                    stmt = stmt.on_duplicate_key_update(
                        open=stmt.inserted.open,
                        high=stmt.inserted.high,
                        low=stmt.inserted.low,
                        close=stmt.inserted.close,
                        adj_close=stmt.inserted.adj_close,
                        volume=stmt.inserted.volume,
                        dividend_amount=stmt.inserted.dividend_amount,
                        split_coefficient=stmt.inserted.split_coefficient,
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


def _upsert_fundamentals(fetcher: FetcherBase, stock: Stock, force: bool = False,
                         indicator_last_updated: Optional[datetime] = None) -> bool:
    """Fetch and upsert OVERVIEW data. Skips if last_updated < refresh_days ago.

    When *indicator_last_updated* is provided (from prefetch), the freshness check
    is in-memory — no DB query needed.
    """
    config = load_config()
    refresh_days = config.get("scheduler", {}).get("overview_refresh_days", 7)

    if not force and indicator_last_updated is not None:
        age = (datetime.utcnow() - indicator_last_updated).days
        if age < refresh_days:
            return False

    session = get_session()
    try:
        if not force and indicator_last_updated is None:
            existing = session.query(StockIndicator).filter_by(stock_id=stock.id).first()
            if existing and existing.last_updated:
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


def _batch_update_checkpoints(stock_ids: list[int]):
    """Single bulk UPDATE for all processed stock checkpoints."""
    if not stock_ids:
        return
    session = get_session()
    try:
        session.execute(
            text("UPDATE stocks SET last_price_fetch = :now WHERE id IN :ids"),
            {"now": datetime.utcnow(), "ids": tuple(stock_ids)},
        )
        session.commit()
    finally:
        session.close()


def _needs_full_backfill(first_indicator_date: Optional[date] = None,
                         first_price_date: Optional[date] = None) -> bool:
    """True if stock has no indicators or earliest indicator is far from earliest price.

    All callers provide pre-fetched dates from `_prefetch_stock_dates()`,
    so this is a pure in-memory check — no DB queries needed.
    """
    if first_indicator_date is None:
        return True
    if first_price_date is None:
        return False
    return (first_indicator_date - first_price_date).days > 365


# Module-level flag: set when Google Gemini news API returns rate-limit or quota error.
# Once set, all subsequent news fetches use Alpha Vantage instead.
_google_news_rate_limited = False

# Progress tracking for per-stock log lines.
import threading as _threading  # noqa: E402 — needs to be after import block but before functions
_progress_lock = _threading.Lock()
_progress_count = 0
_progress_total = 0


def _fetch_stock_news(symbol: str, fetcher: FetcherBase | None = None) -> int:
    """Fetch last week's news for *symbol*.

    Primary path: TradingAgents → Google Gemini (via route_to_vendor, cached).
    Fallback path: Alpha Vantage NEWS_SENTIMENT endpoint (when Google rate-limited).

    The call is intercepted by the news_cache layer, so results are automatically
    stored in the stock_news DB table with deduplication.
    Returns a rough character count if news was fetched, 0 otherwise.
    """
    global _google_news_rate_limited

    if _google_news_rate_limited and fetcher is not None:
        return _fetch_stock_news_av(symbol, fetcher)

    try:
        from tradingagents.dataflows.interface import route_to_vendor
        trade_dt = date.today()
        news_start = (trade_dt - timedelta(days=NEWS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        news_end = trade_dt.strftime("%Y-%m-%d")
        result = route_to_vendor("get_news", symbol, news_start, news_end)
        return len(str(result)) if result else 0
    except Exception as exc:
        msg = str(exc).lower()
        if any(kw in msg for kw in ("rate", "quota", "429", "limit", "exceeded", "resource", "capacity")):
            logger.warning(
                "Google news API rate-limited for %s — switching ALL remaining stocks to Alpha Vantage: %s",
                symbol, exc,
            )
            _google_news_rate_limited = True
            if fetcher is not None:
                return _fetch_stock_news_av(symbol, fetcher)
        else:
            logger.warning("news fetch failed for %s: %s", symbol, exc)
        return 0


def _fetch_stock_news_av(symbol: str, fetcher: FetcherBase) -> int:
    """Fallback: fetch news via Alpha Vantage NEWS_SENTIMENT. Returns char count."""
    try:
        items = fetcher.get_news_sentiment(symbol, days=NEWS_LOOKBACK_DAYS)
        if not items:
            return 0

        # Cache via the same news_cache mechanism
        from tradingagents.dataflows.interface import route_to_vendor
        import json as _json
        payload = _json.dumps(items, default=str)
        sd = (date.today() - timedelta(days=NEWS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        ed = date.today().strftime("%Y-%m-%d")
        route_to_vendor("get_news", symbol, sd, ed, _result_override=payload)
        return len(payload)
    except Exception as exc:
        logger.warning("AV news fallback failed for %s: %s", symbol, exc)
        return 0


def _process_symbol(fetcher: FetcherBase, stock: Stock, force: bool,
                    prefetch: Optional[dict] = None) -> dict:
    result = {"symbol": stock.symbol, "prices": 0, "fundamentals": False, "indicators": 0, "news": 0, "error": None}
    try:
        md = prefetch.get("max_price_dates", {}).get(stock.id) if prefetch else None
        fid = prefetch.get("first_indicator_dates", {}).get(stock.id) if prefetch else None
        fpd = prefetch.get("first_price_dates", {}).get(stock.id) if prefetch else None
        ilu = prefetch.get("indicator_last_updated", {}).get(stock.id) if prefetch else None

        prices_inserted, new_max_date = _fetch_and_store_prices(fetcher, stock, max_date=md)
        result["prices"] = prices_inserted

        refreshed = _upsert_fundamentals(fetcher, stock, force=force,
                                         indicator_last_updated=ilu)
        result["fundamentals"] = refreshed

        if _needs_full_backfill(first_indicator_date=fid, first_price_date=fpd):
            result["indicators"] = compute_indicators(stock.id, since_date=None)
        elif prices_inserted > 0 and new_max_date:
            result["indicators"] = compute_indicators(stock.id, since_date=new_max_date)

        if force or prices_inserted > 0:
            result["news"] = _fetch_stock_news(stock.symbol, fetcher=fetcher)

        with _progress_lock:
            _progress_count += 1
            current = _progress_count

        logger.info(
            "[%d/%d] %-6s  prices=%-4d  indicators=%-4d  overview=%-9s  news=%-5d",
            current, _progress_total,
            stock.symbol, prices_inserted, result["indicators"],
            "refreshed" if refreshed else "skipped",
            result["news"],
        )

    except Exception as e:
        result["error"] = str(e)
        logger.error("Error processing %s: %s", stock.symbol, e)
    return result


def run_daily_pipeline(fetcher: FetcherBase, force: bool = False) -> dict:
    """Run the daily pipeline: prices, fundamentals, indicators, snapshots. Returns summary dict."""
    session = get_session()
    run = PipelineRun(started_at=datetime.utcnow(), status="running")
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    summary = {"processed": 0, "errors": 0, "symbols": []}
    processed_ids: list[int] = []

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

        prefetch = _prefetch_stock_dates([s.id for s in stocks])

        global _progress_count, _progress_total
        with _progress_lock:
            _progress_count = 0
            _progress_total = len(stocks)
        total = _progress_total

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(_process_symbol, fetcher, s, force, prefetch): s
                for s in stocks
            }
            for future in as_completed(futures):
                result = future.result()
                summary["processed"] += 1
                if result["error"]:
                    summary["errors"] += 1
                else:
                    processed_ids.append(futures[future].id)
                summary["symbols"].append(result)
                if summary["processed"] % 50 == 0 or summary["processed"] == total:
                    logger.info(
                        "Progress: %d/%d  errors=%d",
                        summary["processed"], total, summary["errors"],
                    )

        _batch_update_checkpoints(processed_ids)
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
