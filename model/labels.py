"""Label method definitions for sample generation.

Each LabelMethod computes a binary label from a 5-day input window
and a 5-day output window. New methods are added by subclassing and
registering in LABEL_METHODS.
"""

import pandas as pd


class LabelMethod:
    """Base class for label computation strategies.

    Attributes:
        name: Unique identifier, used as label_method column value in DB.
        version: Bumped when logic changes; triggers recompute of all labels.
    """
    name: str = ""
    version: str = "1"

    def compute(self, input_window: pd.DataFrame, output_window: pd.DataFrame) -> int | None:
        """Return 0, 1, or None (insufficient data)."""
        raise NotImplementedError


class MaxHigh5Pct(LabelMethod):
    """Label = 1 if max high in next 5 days >= +5% vs input window max high."""

    name = "max_high_5pct"
    version = "1"

    def __init__(self, threshold: float = 0.05):
        self.threshold = threshold

    def compute(self, input_window: pd.DataFrame, output_window: pd.DataFrame) -> int | None:
        input_max = float(input_window["high"].max())
        output_max = float(output_window["high"].max())
        if input_max <= 0:
            return None
        gain = output_max / input_max - 1.0
        return 1 if gain >= self.threshold else 0


LABEL_METHODS: list[LabelMethod] = [MaxHigh5Pct(threshold=0.05)]


def compute_all_labels(
    prices: pd.DataFrame,
    label_methods: list[LabelMethod],
    window_days: int,
) -> dict:
    """Compute labels for all rolling windows in a stock's price history.

    Returns {input_end_date: {method_name: label_value}}.
    Uses the same windowing logic as FeatureBuilder.build_all_windows —
    call both on the same prices DataFrame to get aligned features + labels.
    """
    if prices.empty or len(prices) < window_days * 2 + 1:
        return {}

    df = prices.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    result: dict = {}
    for i in range(len(df) - window_days * 2 + 1):
        input_window = df.iloc[i:i + window_days]
        output_window = df.iloc[i + window_days:i + window_days * 2]

        if len(output_window) < window_days:
            break

        input_end_date = input_window["date"].iloc[-1].date()
        labels = {}
        for method in label_methods:
            labels[method.name] = method.compute(input_window, output_window)

        result[input_end_date] = labels

    return result
