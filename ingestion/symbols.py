import logging
from datetime import datetime

from sqlalchemy.dialects.mysql import insert

from database import get_session
from fetcher.base import FetcherBase
from models import Stock

logger = logging.getLogger(__name__)


def refresh_symbols(fetcher: FetcherBase) -> int:
    """Fetch active NASDAQ+NYSE listing and upsert into stocks table. Returns count of symbols."""
    logger.info("Fetching symbol listing...")
    df = fetcher.get_listing()
    logger.info("Got %d active symbols", len(df))

    session = get_session()
    try:
        count = 0
        for _, row in df.iterrows():
            stmt = insert(Stock).values(
                symbol=row["symbol"],
                name=row.get("name"),
                asset_type=row.get("asset_type"),
                exchange=row.get("exchange"),
                is_active=False,
            ).on_duplicate_key_update(
                name=row.get("name"),
                asset_type=row.get("asset_type"),
                exchange=row.get("exchange"),
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
