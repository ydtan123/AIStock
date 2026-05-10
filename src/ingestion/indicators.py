import logging
import random
import time
from datetime import datetime, date, timedelta

import pandas as pd
import pandas_ta as ta
from sqlalchemy import text
from sqlalchemy.dialects.mysql import insert

from database import get_session, get_engine
from models import TechnicalIndicator

logger = logging.getLogger(__name__)

# SMA_200 is the longest lookback; load this many extra days before since_date
# to ensure warm-up rows are available (extra buffer for weekends/holidays)
_LOOKBACK_DAYS = 260

_STRATEGY = ta.Study(
    name="core",
    ta=[{"kind": "sma", "length": 20}, {"kind": "sma", "length": 50}, {"kind": "sma", "length": 200},
        {"kind": "ema", "length": 12}, {"kind": "ema", "length": 26},
        {"kind": "rsi", "length": 14},
        {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
        {"kind": "bbands", "length": 20, "std": 2},
        {"kind": "stoch", "k": 14, "d": 3, "smooth_k": 3},
        {"kind": "adx", "length": 14},
        {"kind": "atr", "length": 14},
        {"kind": "obv"},
        {"kind": "cci", "length": 14},
        {"kind": "willr", "length": 14},
        {"kind": "mom", "length": 10},
        {"kind": "roc", "length": 10},
        {"kind": "cmf", "length": 20},
        {"kind": "trix", "length": 18},
        {"kind": "tsi"},
        {"kind": "uo"},
        {"kind": "zscore", "length": 20},
        {"kind": "kurtosis", "length": 20},
        {"kind": "stdev", "length": 20},
        ],
)


def compute_indicators(stock_id: int, since_date: date | None = None) -> int:
    """Compute technical indicators from stored OHLCV data. Returns rows written.

    Loads only the minimum price history needed: if since_date is set, fetches
    since_date - _LOOKBACK_DAYS for indicator warm-up, computes over that window,
    then writes only rows >= since_date. Full-history load only happens when
    since_date is None (initial backfill).
    """
    engine = get_engine()
    load_from = (since_date - timedelta(days=_LOOKBACK_DAYS)) if since_date else None

    with engine.connect() as conn:
        if load_from:
            rows = conn.execute(
                text(
                    "SELECT date, open, high, low, close, volume "
                    "FROM daily_prices WHERE stock_id = :sid AND date >= :from_dt "
                    "ORDER BY date"
                ),
                {"sid": stock_id, "from_dt": load_from},
            ).fetchall()
        else:
            rows = conn.execute(
                text(
                    "SELECT date, open, high, low, close, volume "
                    "FROM daily_prices WHERE stock_id = :sid ORDER BY date"
                ),
                {"sid": stock_id},
            ).fetchall()

    if not rows:
        return 0

    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["open"] = df["open"].astype(float).fillna(0.0)
    df["high"] = df["high"].astype(float).fillna(0.0)
    df["low"] = df["low"].astype(float).fillna(0.0)
    df["close"] = df["close"].astype(float).fillna(0.0)
    df["volume"] = df["volume"].astype(float).fillna(0.0)
    df.set_index("date", inplace=True)

    df.ta.study(_STRATEGY)

    if since_date:
        df = df[df.index >= since_date]

    if df.empty:
        return 0

    now = datetime.utcnow()
    values = []
    for row_date, row in df.iterrows():
        indicators = {}
        for k, v in row.items():
            val = float(v)
            indicators[k] = None if (pd.isna(val) or val == float("inf") or val == float("-inf")) else round(val, 6)
        values.append({
            "stock_id": stock_id,
            "date": row_date,
            "indicators": indicators,
            "computed_at": now,
        })

    count = 0
    batch_size = 200
    session = get_session()
    try:
        for i in range(0, len(values), batch_size):
            batch = values[i:i + batch_size]
            for attempt in range(5):
                try:
                    # Single multi-row INSERT ... ON DUPLICATE KEY UPDATE per batch
                    stmt = insert(TechnicalIndicator).values(batch)
                    stmt = stmt.on_duplicate_key_update(
                        indicators=stmt.inserted.indicators,
                        computed_at=stmt.inserted.computed_at,
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
    finally:
        session.close()

    return count
