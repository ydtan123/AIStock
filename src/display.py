import pandas as pd

from utils import nan_safe  # noqa: F401 — re-exported for backward compat


def fmt_market_cap(val) -> str:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return "—"
        val = int(val)
    except (TypeError, ValueError):
        return "—"
    if val >= 1_000_000_000_000:
        return f"${val/1_000_000_000_000:.2f}T"
    if val >= 1_000_000_000:
        return f"${val/1_000_000_000:.2f}B"
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    return f"${val:,}"
