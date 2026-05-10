"""One-shot: backfill full technical indicator history for all active stocks.

Skips API calls — only recomputes indicators from existing OHLCV data.
Uses the same _needs_full_backfill check as the daily pipeline.
"""

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database import get_session
from ingestion.indicators import compute_indicators
from ingestion.pipeline import _needs_full_backfill
from models import Stock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

MAX_WORKERS = 5


def _backfill_one(stock_id: int, symbol: str) -> dict:
    try:
        written = compute_indicators(stock_id, since_date=None)
        return {"symbol": symbol, "rows": written, "error": None}
    except Exception as e:
        logger.error("Backfill failed for %s: %s", symbol, e)
        return {"symbol": symbol, "rows": 0, "error": str(e)}


def main():
    session = get_session()
    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    session.close()

    logger.info("Checking %d active stocks for backfill need...", len(stocks))
    needs_backfill = []
    for s in stocks:
        if _needs_full_backfill(s.id):
            needs_backfill.append(s)
    logger.info("%d stocks need full backfill, %d already covered",
                len(needs_backfill), len(stocks) - len(needs_backfill))

    if not needs_backfill:
        logger.info("Nothing to do.")
        return

    ok = 0
    fail = 0
    total_rows = 0
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_backfill_one, s.id, s.symbol): s for s in needs_backfill}
        for future in as_completed(futures):
            result = future.result()
            done += 1
            if result["error"]:
                fail += 1
            else:
                ok += 1
                total_rows += result["rows"]
            if done % 100 == 0:
                logger.info("Progress: %d/%d (ok=%d fail=%d rows=%d)",
                            done, len(needs_backfill), ok, fail, total_rows)

    logger.info("Backfill complete. ok=%d fail=%d total_rows=%d", ok, fail, total_rows)


if __name__ == "__main__":
    main()
