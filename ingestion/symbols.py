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

    session = get_session()
    try:
        count = 0
        for _, row in df.iterrows():
            name = _clean(row.get("name"))
            asset_type = _clean(row.get("asset_type"))
            exchange = _clean(row.get("exchange"))
            stmt = insert(Stock).values(
                symbol=row["symbol"],
                name=name,
                asset_type=asset_type,
                exchange=exchange,
                is_active=False,
            ).on_duplicate_key_update(
                name=name,
                asset_type=asset_type,
                exchange=exchange,
            )
            session.execute(stmt)
            count += 1
        session.commit()
        logger.info("Upserted %d symbols", count)
        return count
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
