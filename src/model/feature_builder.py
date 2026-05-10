"""FeatureBuilder: constructs feature dicts from rolling price + indicator windows.

Single source of truth for feature construction — used by both training
(all windows over full price history) and inference (single live window).
INDICATOR_NAMES, WINDOW_DAYS, PRICE_COLS are the authoritative constants;
import them from here, not from model.train.
"""

import json
from datetime import date

import pandas as pd


INDICATOR_NAMES = [
    "SMA_20", "SMA_50", "SMA_200",
    "EMA_12", "EMA_26",
    "RSI_14",
    "MACD_12_26_9", "MACDs_12_26_9", "MACDh_12_26_9",
    "BBL_20_2.0", "BBU_20_2.0",
    "STOCHk_14_3_3", "STOCHd_14_3_3",
    "ADX_14", "ATRr_14",
    "OBV",
    "CCI_14", "WILLR_14", "MOM_10", "ROC_10",
    "CMF_20", "TRIX_18", "TSI", "UO",
    "ZSCORE_20", "KURTOSIS_20", "STDEV_20",
]

PRICE_COLS = ["open", "high", "low", "close", "volume"]
WINDOW_DAYS = 5


class FeatureBuilder:
    """Builds feature dicts from OHLCV + technical indicator windows.

    Config (indicator list, window size, price columns) is injected at
    construction. FeatureBuilder.default() returns an instance using the
    project-wide constants above — use this for all production code.
    Tests can construct minimal instances (e.g. two indicators, 3-day window)
    to isolate feature logic without full indicator sets.
    """

    def __init__(
        self,
        indicator_names: list[str],
        window_days: int,
        price_cols: list[str],
    ) -> None:
        self.indicator_names = indicator_names
        self.window_days = window_days
        self.price_cols = price_cols

    @classmethod
    def default(cls) -> "FeatureBuilder":
        return cls(INDICATOR_NAMES, WINDOW_DAYS, PRICE_COLS)

    def parse_tech_rows(self, tech_rows: list) -> dict[date, dict]:
        """Parse raw DB tech rows → {date: {indicator_name: value}}.

        Each tech_row is a (date, indicators_json) tuple from technical_indicators.
        Price columns stripped — features normalise prices separately.
        """
        lookup: dict[date, dict] = {}
        for row in tech_rows:
            raw = row[1]
            if raw is None:
                ind: dict = {}
            elif isinstance(raw, dict):
                ind = dict(raw)
            elif isinstance(raw, str):
                try:
                    ind = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    ind = {}
            else:
                ind = {}
            for col in self.price_cols:
                ind.pop(col, None)
            lookup[row[0]] = ind
        return lookup

    def build_window(
        self,
        input_window: pd.DataFrame,
        tech_lookup: dict,
        sector: str | None,
    ) -> dict:
        """Build a feature dict for one window.

        input_window: DataFrame with [date, open, high, low, close, volume],
                      sorted chronologically, exactly window_days rows.
        tech_lookup: {date: {indicator_name: value}} from parse_tech_rows.
        sector: sector string or None.

        All price features are normalised relative to the first row's close/volume.
        """
        first_close = float(input_window["close"].iloc[0])
        first_volume = float(input_window["volume"].iloc[0])
        features: dict = {}

        for day_idx in range(self.window_days):
            row = input_window.iloc[day_idx]
            prefix = f"d{day_idx + 1}"

            for col in self.price_cols:
                val = float(row[col]) if row[col] and not pd.isna(row[col]) else 0.0
                if col == "volume":
                    features[f"{prefix}_{col}"] = (val / first_volume - 1.0) * 100 if first_volume else 0.0
                else:
                    features[f"{prefix}_{col}"] = (val / first_close - 1.0) * 100

            raw_date = row["date"]
            row_date: date = raw_date.date() if hasattr(raw_date, "date") else raw_date
            day_tech = tech_lookup.get(row_date, {})
            for ind_name in self.indicator_names:
                val = day_tech.get(ind_name)
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    val = 0.0
                features[f"{prefix}_{ind_name}"] = float(val)

        features["sector"] = sector or "Unknown"
        return features

    def build_all_windows(
        self,
        prices: pd.DataFrame,
        tech_rows: list,
        sector: str | None,
        symbol: str,
    ) -> list[dict]:
        """Build feature dicts for all valid rolling windows in a stock's price history.

        Returns list of {"features": dict, "input_end_date": date, "symbol": str}.
        Label computation is separate — see model.labels.compute_all_labels.
        """
        if prices.empty or len(prices) < self.window_days * 2 + 1:
            return []

        df = prices.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        tech_lookup = self.parse_tech_rows(tech_rows)
        results: list[dict] = []

        for i in range(len(df) - self.window_days * 2 + 1):
            input_window = df.iloc[i:i + self.window_days]
            if i + self.window_days * 2 > len(df):
                break

            first_close = float(input_window["close"].iloc[0])
            first_volume = float(input_window["volume"].iloc[0])
            if first_close <= 0 or first_volume <= 0:
                continue

            input_end_date = input_window["date"].iloc[-1].date()
            features = self.build_window(input_window, tech_lookup, sector)
            results.append({
                "features": features,
                "input_end_date": input_end_date,
                "symbol": symbol,
            })

        return results
