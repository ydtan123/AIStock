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

    def compute(self, input_window: pd.DataFrame, output_window: pd.DataFrame,
                context: dict | None = None) -> int | None:
        """Return 0, 1, or None (insufficient data)."""
        raise NotImplementedError


class MaxHigh5Pct(LabelMethod):
    """Label = 1 if max high in next 5 days >= +5% vs input window max high."""

    name = "max_high_5pct"
    version = "1"

    def __init__(self, threshold: float = 0.05):
        self.threshold = threshold

    def compute(self, input_window: pd.DataFrame, output_window: pd.DataFrame,
                context: dict | None = None) -> int | None:
        input_max = float(input_window["high"].max())
        output_max = float(output_window["high"].max())
        if input_max <= 0:
            return None
        gain = output_max / input_max - 1.0
        return 1 if gain >= self.threshold else 0


class BeatsSpy(LabelMethod):
    """Label = 1 if stock's 5-day close-to-close return >= SPY's return + 5%.

    Requires context={"spy": spy_df} where spy_df has columns [date, close],
    sorted ascending by date. SPY dates are matched on-or-before the window
    boundary dates to handle market holiday misalignment.

    For performance, pre-compute spy_dates_ord (int array) and spy_closes (float
    array) in the context dict so binary search is used instead of per-window
    boolean indexing.
    """

    name = "beats_spy"
    version = "2"

    def __init__(self, margin: float = 0.05):
        self.margin = margin

    def compute(self, input_window: pd.DataFrame, output_window: pd.DataFrame,
                context: dict | None = None) -> int | None:
        ctx = context or {}
        spy_dates_ord = ctx.get("spy_dates_ord")
        spy_closes = ctx.get("spy_closes")

        if spy_dates_ord is None or spy_closes is None:
            spy_df = ctx.get("spy")
            if spy_df is None or spy_df.empty:
                return None
            spy_dates_ord = spy_df["date"].apply(lambda d: d.toordinal()).to_numpy()
            spy_closes = spy_df["close"].to_numpy(dtype=float)
            if ctx is not None:
                ctx["spy_dates_ord"] = spy_dates_ord
                ctx["spy_closes"] = spy_closes

        input_last_close = float(input_window["close"].iloc[-1])
        output_last_close = float(output_window["close"].iloc[-1])
        if input_last_close <= 0:
            return None
        stock_return = output_last_close / input_last_close - 1.0

        input_ord = input_window["date"].iloc[-1].toordinal()
        output_ord = output_window["date"].iloc[-1].toordinal()

        import numpy as np
        idx_in = np.searchsorted(spy_dates_ord, input_ord, side="right") - 1
        idx_out = np.searchsorted(spy_dates_ord, output_ord, side="right") - 1

        if idx_in < 0 or idx_out < 0:
            return None

        spy_input_close = spy_closes[idx_in]
        spy_output_close = spy_closes[idx_out]
        if spy_input_close <= 0:
            return None

        spy_return = spy_output_close / spy_input_close - 1.0
        return 1 if stock_return >= spy_return + self.margin else 0


LABEL_METHODS: list[LabelMethod] = [MaxHigh5Pct(threshold=0.05), BeatsSpy(margin=0.05)]


def compute_all_labels(
    prices: pd.DataFrame,
    label_methods: list[LabelMethod],
    window_days: int,
    context: dict | None = None,
) -> dict:
    """Compute labels for all rolling windows in a stock's price history.

    Returns {input_end_date: {method_name: label_value}}.
    context is passed through to each LabelMethod.compute() call.
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
            labels[method.name] = method.compute(input_window, output_window, context)

        result[input_end_date] = labels

    return result
