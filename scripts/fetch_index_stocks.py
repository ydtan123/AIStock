#!/usr/bin/env python3
"""Download stocks in a market index (e.g. S&P 500) and store in stocks_in_index table.

Usage:
    python scripts/fetch_index_stocks.py                    # default: S&P 500
    python scripts/fetch_index_stocks.py --index "S&P 500"
    python scripts/fetch_index_stocks.py --index "NASDAQ-100"

The S&P 500 list is scraped from Wikipedia.
Other indices can be added by implementing their fetch functions.
"""

import argparse
import io
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fetch_index_stocks")

# -- Wikipedia URL for S&P 500 ------------------------------------------------
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Column mapping: Wikipedia table column -> DB column
SP500_COLUMN_MAP = {
    "Symbol": "symbol",
    "Security": "security",
    "GICS Sector": "gics_sector",
    "GICS Sub-Industry": "gics_sub_industry",
    "Headquarters Location": "headquarters_location",
    "Date added": "date_added",
    "CIK": "cik",
    "Founded": "founded",
}


HEADERS = {"User-Agent": "AIStock/1.0 (stock data collection; contact@example.com)"}


def fetch_sp500() -> pd.DataFrame:
    """Scrape the S&P 500 components table from Wikipedia."""
    logger.info("Fetching S&P 500 from Wikipedia...")
    resp = requests.get(SP500_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    # The first table (index 0) is the S&P 500 components table
    df = tables[0]
    df = df.rename(columns=SP500_COLUMN_MAP)
    df["index_name"] = "S&P 500"
    logger.info("Fetched %d stocks from S&P 500 table", len(df))
    return df


# Registry of supported indices
FETCHERS = {
    "S&P 500": fetch_sp500,
}


def create_table(engine) -> None:
    """Create stocks_in_index table if it doesn't exist."""
    ddl = text("""
        CREATE TABLE IF NOT EXISTS stocks_in_index (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            index_name VARCHAR(100) NOT NULL,
            symbol VARCHAR(10) NOT NULL,
            security VARCHAR(255),
            gics_sector VARCHAR(100),
            gics_sub_industry VARCHAR(255),
            headquarters_location VARCHAR(255),
            date_added DATE,
            cik VARCHAR(20),
            founded VARCHAR(255),
            fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_index_symbol (index_name, symbol),
            INDEX ix_index_name (index_name),
            INDEX ix_symbol (symbol)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    with engine.connect() as conn:
        conn.execute(ddl)
        conn.commit()
    logger.info("Table stocks_in_index ready.")


def upsert_stocks(engine, df: pd.DataFrame) -> int:
    """Insert or update stocks in the stocks_in_index table. Returns row count."""
    now = datetime.now()

    with Session(engine) as session:
        inserted = 0
        updated = 0
        for _, row in df.iterrows():
            symbol = str(row["symbol"]).strip()
            index_name = str(row["index_name"]).strip()
            security = str(row.get("security", "")).strip() if pd.notna(row.get("security")) else None
            gics_sector = str(row.get("gics_sector", "")).strip() if pd.notna(row.get("gics_sector")) else None
            gics_sub_industry = str(row.get("gics_sub_industry", "")).strip() if pd.notna(row.get("gics_sub_industry")) else None
            headquarters_location = str(row.get("headquarters_location", "")).strip() if pd.notna(row.get("headquarters_location")) else None
            cik = str(row.get("cik", "")).strip() if pd.notna(row.get("cik")) else None
            founded = str(row.get("founded", "")).strip() if pd.notna(row.get("founded")) else None

            # Parse date_added (format: YYYY-MM-DD)
            date_added = None
            raw_date = row.get("date_added")
            if pd.notna(raw_date):
                try:
                    date_added = pd.Timestamp(raw_date).date()
                except Exception:
                    pass

            # Check if row exists
            result = session.execute(
                text(
                    "SELECT id FROM stocks_in_index WHERE index_name = :idx AND symbol = :sym"
                ),
                {"idx": index_name, "sym": symbol},
            ).fetchone()

            if result:
                session.execute(
                    text(
                        """UPDATE stocks_in_index
                           SET security = :sec, gics_sector = :gs, gics_sub_industry = :gsi,
                               headquarters_location = :hl, date_added = :da, cik = :cik,
                               founded = :fnd, fetched_at = :now
                           WHERE id = :id"""
                    ),
                    {
                        "sec": security,
                        "gs": gics_sector,
                        "gsi": gics_sub_industry,
                        "hl": headquarters_location,
                        "da": date_added,
                        "cik": cik,
                        "fnd": founded,
                        "now": now,
                        "id": result[0],
                    },
                )
                updated += 1
            else:
                session.execute(
                    text(
                        """INSERT INTO stocks_in_index
                           (index_name, symbol, security, gics_sector, gics_sub_industry,
                            headquarters_location, date_added, cik, founded, fetched_at)
                           VALUES (:idx, :sym, :sec, :gs, :gsi, :hl, :da, :cik, :fnd, :now)"""
                    ),
                    {
                        "idx": index_name,
                        "sym": symbol,
                        "sec": security,
                        "gs": gics_sector,
                        "gsi": gics_sub_industry,
                        "hl": headquarters_location,
                        "da": date_added,
                        "cik": cik,
                        "fnd": founded,
                        "now": now,
                    },
                )
                inserted += 1

        session.commit()

    logger.info("Inserted %d, updated %d rows.", inserted, updated)
    return inserted + updated


def main():
    parser = argparse.ArgumentParser(
        description="Download index constituents and store in stocks_in_index table."
    )
    parser.add_argument(
        "--index",
        default="S&P 500",
        choices=list(FETCHERS.keys()),
        help="Index to fetch (default: S&P 500)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print table without writing to database",
    )
    args = parser.parse_args()

    fetch_fn = FETCHERS[args.index]
    df = fetch_fn()

    if args.dry_run:
        print(df.to_string(index=False))
        return

    cfg = load_config()
    engine = create_engine(cfg["database"]["url"])

    create_table(engine)
    count = upsert_stocks(engine, df)
    print(f"Done: {count} stocks for {args.index}")


if __name__ == "__main__":
    main()
