"""Compute technical indicators for all active stocks from earliest date."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s"
)
logger = logging.getLogger("indicator_batch")

from database import get_session
from ingestion.indicators import compute_indicators
from models import Stock

session = get_session()
stocks = session.query(Stock).filter(Stock.is_active == True).all()
session.close()

total = len(stocks)
logger.info("Computing indicators for %d active stocks from earliest date", total)

done = 0
errors = 0
total_rows = 0
start_time = time.time()


def process(s):
    try:
        count = compute_indicators(s.id, since_date=None)
        return s.symbol, count, None
    except Exception as e:
        return s.symbol, 0, str(e)


with ThreadPoolExecutor(max_workers=3) as pool:
    futures = {pool.submit(process, s): s for s in stocks}
    for f in as_completed(futures):
        symbol, count, err = f.result()
        done += 1
        if err:
            errors += 1
            logger.error("[%d/%d] %s FAILED: %s", done, total, symbol, err[:120])
        else:
            total_rows += count
            elapsed = time.time() - start_time
            rate = done / (elapsed / 60) if elapsed > 0 else 0
            logger.info("[%d/%d] %s: %d rows (%.1f/min, ETA %.0f min)",
                        done, total, symbol, count, rate,
                        (total - done) / rate if rate > 0 else 0)

elapsed = time.time() - start_time
logger.info("Done. %d stocks, %d rows, %d errors, %.0f min total",
            done, total_rows, errors, elapsed / 60)
