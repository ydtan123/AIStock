import logging
import math
from datetime import datetime

from sqlalchemy.dialects.mysql import insert

from database import get_session
from fetcher.base import FetcherBase
from models import Stock

logger = logging.getLogger(__name__)


def _clean(val):
    """Convert NaN/float NaN to None for MySQL compatibility."""
    if val is None:
        return None
    try:
        if math.isnan(float(val)):
            return None
    except (TypeError, ValueError):
        pass
    return val


def refresh_symbols(fetcher: FetcherBase) -> int:
    """Fetch active NASDAQ+NYSE listing and upsert into stocks table. Returns count of symbols."""
    logger.info("Fetching symbol listing...")
    df = fetcher.get_listing()
    logger.info("Got %d active symbols", len(df))

    BATCH_SIZE = 200
    all_values = []
    for row in df.itertuples():
        all_values.append({
            "symbol": row.symbol,
            "name": _clean(getattr(row, "name", None)),
            "asset_type": _clean(getattr(row, "asset_type", None)),
            "exchange": _clean(getattr(row, "exchange", None)),
            "is_active": False,
        })

    session = get_session()
    try:
        for i in range(0, len(all_values), BATCH_SIZE):
            batch = all_values[i:i + BATCH_SIZE]
            stmt = insert(Stock).values(batch)
            stmt = stmt.on_duplicate_key_update(
                name=stmt.inserted.name,
                asset_type=stmt.inserted.asset_type,
                exchange=stmt.inserted.exchange,
            )
            session.execute(stmt)
        session.commit()
        logger.info("Upserted %d symbols", len(all_values))
        return len(all_values)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
