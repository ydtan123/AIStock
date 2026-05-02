import logging
import random
import time
from datetime import datetime, date

import pandas as pd
import pandas_ta as ta
from sqlalchemy.dialects.mysql import insert

from database import get_session
from models import DailyPrice, Stock, TechnicalIndicator

logger = logging.getLogger(__name__)

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
    """Compute technical indicators for a stock from stored OHLCV data. Returns rows written."""
    session = get_session()
    try:
        query = (
            session.query(DailyPrice)
            .filter(DailyPrice.stock_id == stock_id)
            .order_by(DailyPrice.date)
        )
        rows = query.all()
        if not rows:
            return 0

        df = pd.DataFrame([{
            "date": r.date,
            "open": float(r.open or 0),
            "high": float(r.high or 0),
            "low": float(r.low or 0),
            "close": float(r.close or 0),
            "volume": float(r.volume or 0),
        } for r in rows])
        df.set_index("date", inplace=True)
        df.ta.study(_STRATEGY)

        if since_date:
            df = df[df.index >= since_date]

        if df.empty:
            return 0

        values = []
        for row_date, row in df.iterrows():
            indicators = {}
            for k, v in row.items():
                val = float(v)
                if pd.isna(val) or val == float('inf') or val == float('-inf'):
                    val = None
                else:
                    val = round(val, 6)
                indicators[k] = val
            values.append({
                "stock_id": stock_id,
                "date": row_date,
                "indicators": indicators,
                "computed_at": datetime.utcnow(),
            })

        count = 0
        batch_size = 100
        for i in range(0, len(values), batch_size):
            batch = values[i:i + batch_size]
            for attempt in range(5):
                try:
                    for v in batch:
                        stmt = insert(TechnicalIndicator).values(**v).on_duplicate_key_update(
                            indicators=v["indicators"],
                            computed_at=v["computed_at"],
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

        return count
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
