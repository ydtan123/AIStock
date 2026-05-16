"""DB-backed cache for TradingAgents news tool calls via the stock_news table.

Intercepts route_to_vendor() for cacheable tools by monkey-patching
tradingagents.dataflows.interface before TradingAgents modules are imported,
so all @tool wrappers receive the cached version at first import.

Call install() once in main() before any tradingagents import.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

logger = logging.getLogger("news_cache")

_CACHEABLE = frozenset({"get_news", "get_global_news", "get_insider_transactions"})
_INSTALLED = False


def _key(tool_name: str, args: tuple, kwargs: dict) -> tuple[str, str, str]:
    """Return (ticker, start_date, end_date) cache key fields from call args."""
    if tool_name == "get_news":
        ticker = str(args[0]) if args else kwargs.get("ticker", "")
        start = str(args[1]) if len(args) > 1 else kwargs.get("start_date", "")
        end = str(args[2]) if len(args) > 2 else kwargs.get("end_date", "")
        return ticker, start, end
    if tool_name == "get_global_news":
        curr_date = str(args[0]) if args else kwargs.get("curr_date", "")
        look_back = args[1] if len(args) > 1 else kwargs.get("look_back_days", 7)
        limit = args[2] if len(args) > 2 else kwargs.get("limit", 5)
        return "__global__", curr_date, f"{look_back}:{limit}"
    if tool_name == "get_insider_transactions":
        ticker = str(args[0]) if args else kwargs.get("ticker", "")
        return ticker, "", ""
    return "__unknown__", "", ""


def _get_session():
    from database import get_session
    return get_session()


def get_cached(tool_name: str, args: tuple, kwargs: dict) -> str | None:
    if tool_name not in _CACHEABLE:
        return None
    ticker, start_date, end_date = _key(tool_name, args, kwargs)
    try:
        from models import StockNews
        session = _get_session()
        try:
            row = (
                session.query(StockNews)
                .filter_by(tool_name=tool_name, ticker=ticker, start_date=start_date, end_date=end_date)
                .first()
            )
            if row:
                logger.info("[CACHE] HIT  %-30s  %s  %s→%s", tool_name, ticker, start_date, end_date)
                return row.result
        finally:
            session.close()
    except Exception as exc:
        logger.warning("[CACHE] read error: %s", exc)
    return None


def set_cached(tool_name: str, args: tuple, kwargs: dict, result: str) -> None:
    if tool_name not in _CACHEABLE or not (result and result.strip()):
        return
    ticker, start_date, end_date = _key(tool_name, args, kwargs)
    try:
        from models import StockNews
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        session = _get_session()
        try:
            stmt = mysql_insert(StockNews).values(
                tool_name=tool_name,
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                result=result,
                fetched_at=datetime.now(),
            ).on_duplicate_key_update(result=result, fetched_at=datetime.now())
            session.execute(stmt)
            session.commit()
            logger.info(
                "[CACHE] SET   %-30s  %s  %s→%s  (%d chars)",
                tool_name, ticker, start_date, end_date, len(result),
            )
        finally:
            session.close()
    except Exception as exc:
        logger.warning("[CACHE] write error: %s", exc)


def _ensure_table() -> None:
    try:
        from models import StockNews
        from database import get_engine
        StockNews.__table__.create(bind=get_engine(), checkfirst=True)
        logger.info("[CACHE] stock_news table ready")
    except Exception as exc:
        logger.warning("[CACHE] ensure_table error: %s", exc)


def install() -> None:
    """Patch tradingagents.dataflows.interface.route_to_vendor with DB cache. Idempotent."""
    global _INSTALLED
    if _INSTALLED:
        return

    _ensure_table()

    try:
        import tradingagents.dataflows.interface as _iface
    except ImportError:
        logger.warning("[CACHE] tradingagents not importable — cache not installed")
        return

    _original = _iface.route_to_vendor

    def _cached_route(method: str, *args, **kwargs):
        if method in _CACHEABLE:
            hit = get_cached(method, args, kwargs)
            if hit is not None:
                return hit
        result = _original(method, *args, **kwargs)
        if method in _CACHEABLE:
            set_cached(method, args, kwargs, str(result))
        return result

    _iface.route_to_vendor = _cached_route

    # Patch any tool modules already loaded that captured route_to_vendor by name
    for mod_name in [
        "tradingagents.agents.utils.news_data_tools",
        "tradingagents.agents.utils.agent_utils",
        "tradingagents.agents.utils.fundamental_data_tools",
        "tradingagents.agents.utils.technical_indicators_tools",
        "tradingagents.agents.utils.core_stock_tools",
    ]:
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "route_to_vendor"):
            setattr(mod, "route_to_vendor", _cached_route)

    _INSTALLED = True
    logger.info("[CACHE] route_to_vendor patched — news calls cached in stock_news")
