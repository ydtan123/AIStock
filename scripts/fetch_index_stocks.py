#!/usr/bin/env python3
"""Download stocks in a market index and store in stocks_in_index table.

Usage:
    python scripts/fetch_index_stocks.py                    # default: S&P 500
    python scripts/fetch_index_stocks.py --index "S&P 500"
    python scripts/fetch_index_stocks.py --index "NASDAQ-100"
    python scripts/fetch_index_stocks.py --index "Dow Jones"
    python scripts/fetch_index_stocks.py --dry-run

Supported indices:
    - S&P 500     (Wikipedia: List of S&P 500 companies)
    - NASDAQ-100  (Wikipedia: Nasdaq-100)
    - Dow Jones   (Wikipedia: Dow Jones Industrial Average)
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

HEADERS = {"User-Agent": "AIStock/1.0 (stock data collection; contact@example.com)"}

# -- Wikipedia URLs -----------------------------------------------------------
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
DJIA_URL = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"

# -- Column mappings: Wikipedia column -> DB column ---------------------------
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

NASDAQ100_COLUMN_MAP = {
    "Ticker": "symbol",
    "Company": "security",
    "ICB Industry": "gics_sector",
    "ICB Subsector": "gics_sub_industry",
}

DJIA_COLUMN_MAP = {
    "Symbol": "symbol",
    "Company": "security",
    "Exchange": "exchange",
    "Sector": "gics_sector",
    "Date added": "date_added",
    "Notes": "notes",
    "Index weighting": "index_weighting",
}

# -- Known stock symbols in the DB for symbol column (uppercase) --------------
# DB daily_prices table has symbols without dots (BRKB not BRK.B).
# Wikipedia S&P 500 / DJIA also use dots. Keep Wikipedia symbol as-is for
# cross-referencing; the DB lookup can strip dots when needed.


def _fetch_html(url: str) -> str:
    """Fetch a Wikipedia page and return HTML text."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def _find_table_by_columns(html: str, required_cols: list[str]) -> pd.DataFrame:
    """Find the first <table> in HTML whose header row contains all required_cols.

    Column headers are cleaned: footnote references like ``[14]`` are stripped
    so that "ICB Industry[14]" matches "ICB Industry".
    """
    import re

    tables = pd.read_html(io.StringIO(html))
    for i, df in enumerate(tables):
        headers_lower = {re.sub(r"\[.*", "", str(c).strip()).lower() for c in df.columns}
        if all(rc.lower() in headers_lower for rc in required_cols):
            logger.info("Matched table index %d (columns: %s)", i, list(df.columns))
            return _strip_footnotes(df)
    raise ValueError(
        f"No table found with required columns: {required_cols}. "
        f"Checked {len(tables)} tables."
    )


def _strip_footnotes(df: pd.DataFrame) -> pd.DataFrame:
    """Remove Wikipedia footnote references like ``[14]`` from column names."""
    import re

    df = df.rename(columns=lambda c: re.sub(r"\[.*", "", str(c)).strip())
    return df


# -- Fetcher functions --------------------------------------------------------

def fetch_sp500() -> pd.DataFrame:
    """Scrape the S&P 500 components table from Wikipedia."""
    logger.info("Fetching S&P 500 from Wikipedia...")
    html = _fetch_html(SP500_URL)
    df = _find_table_by_columns(html, ["Symbol", "Security", "GICS Sector"])
    df = df.rename(columns=SP500_COLUMN_MAP)
    df["index_name"] = "S&P 500"
    logger.info("Fetched %d stocks from S&P 500 table", len(df))
    return df


def fetch_nasdaq100() -> pd.DataFrame:
    """Scrape the NASDAQ-100 components table from Wikipedia."""
    logger.info("Fetching NASDAQ-100 from Wikipedia...")
    html = _fetch_html(NASDAQ100_URL)
    df = _find_table_by_columns(html, ["Ticker", "Company"])
    df = df.rename(columns=NASDAQ100_COLUMN_MAP)
    df["index_name"] = "NASDAQ-100"
    logger.info("Fetched %d stocks from NASDAQ-100 table", len(df))
    return df


def fetch_djia() -> pd.DataFrame:
    """Scrape the Dow Jones Industrial Average components from Wikipedia."""
    logger.info("Fetching Dow Jones from Wikipedia...")
    html = _fetch_html(DJIA_URL)
    df = _find_table_by_columns(html, ["Symbol", "Company", "Sector"])
    df = df.rename(columns=DJIA_COLUMN_MAP)
    df["index_name"] = "Dow Jones"
    logger.info("Fetched %d stocks from Dow Jones table", len(df))
    return df


# Registry of supported indices
FETCHERS = {
    "S&P 500": fetch_sp500,
    "NASDAQ-100": fetch_nasdaq100,
    "Dow Jones": fetch_djia,
}

# All known DB columns (kept in sync with DDL below)
_DB_COLUMNS = [
    "index_name", "symbol", "security", "gics_sector", "gics_sub_industry",
    "headquarters_location", "date_added", "cik", "founded",
    "exchange", "notes", "index_weighting",
]


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
            exchange VARCHAR(50),
            notes VARCHAR(255),
            index_weighting VARCHAR(20),
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


def _coerce_str(val) -> str | None:
    """Safe string coercion for a DataFrame cell value."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s if s else None


def _coerce_date(val) -> datetime | None:
    """Safe date coercion. Returns None on failure."""
    if pd.isna(val):
        return None
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None


def upsert_stocks(engine, df: pd.DataFrame) -> int:
    """Insert or update stocks in the stocks_in_index table. Returns row count.

    Only columns present in *both* the DataFrame and the DB table are touched.
    This allows different indices to contribute different subsets of fields.
    """
    now = datetime.now()
    # Only consider columns that exist in both the DataFrame and the DB schema
    cols = [c for c in _DB_COLUMNS if c in df.columns]

    with Session(engine) as session:
        inserted = 0
        updated = 0
        for _, row in df.iterrows():
            symbol = _coerce_str(row.get("symbol"))
            index_name = _coerce_str(row.get("index_name"))
            if not symbol or not index_name:
                continue

            # Build row values dict from available columns
            values: dict[str, str | datetime | None] = {}
            for col in cols:
                if col == "date_added":
                    values[col] = _coerce_date(row.get(col))
                elif col in ("symbol", "index_name"):
                    values[col] = _coerce_str(row.get(col))
                else:
                    values[col] = _coerce_str(row.get(col))

            # Check if row exists
            result = session.execute(
                text(
                    "SELECT id FROM stocks_in_index "
                    "WHERE index_name = :idx AND symbol = :sym"
                ),
                {"idx": index_name, "sym": symbol},
            ).fetchone()

            if result:
                # Build dynamic SET clause
                set_parts = [f"{c} = :{c}" for c in cols if c not in ("symbol", "index_name")]
                set_parts.append("fetched_at = :now")
                sql = f"UPDATE stocks_in_index SET {', '.join(set_parts)} WHERE id = :id"
                params = {c: values[c] for c in cols if c not in ("symbol", "index_name")}
                params["now"] = now
                params["id"] = result[0]
                session.execute(text(sql), params)
                updated += 1
            else:
                cols_with_now = cols + ["fetched_at"]
                placeholders = ", ".join(f":{c}" for c in cols_with_now)
                col_names = ", ".join(cols_with_now)
                sql = f"INSERT INTO stocks_in_index ({col_names}) VALUES ({placeholders})"
                params = {c: values[c] for c in cols}
                params["fetched_at"] = now
                session.execute(text(sql), params)
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
        "--all",
        action="store_true",
        help="Fetch all supported indices",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print table without writing to database",
    )
    args = parser.parse_args()

    cfg = load_config()
    engine = create_engine(cfg["database"]["url"])
    create_table(engine)

    if args.all:
        indices = list(FETCHERS.keys())
    else:
        indices = [args.index]

    for name in indices:
        fetch_fn = FETCHERS[name]
        logger.info("--- Processing %s ---", name)
        df = fetch_fn()

        if args.dry_run:
            print(f"\n=== {name} ===")
            print(df.to_string(index=False))
            print()
            continue

        count = upsert_stocks(engine, df)
        print(f"Done: {count} stocks for {name}")


if __name__ == "__main__":
    main()
