"""Shared utility functions used across AIStock modules."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Optional

import pandas as pd


def safe_float(val: Any) -> Optional[float]:
    """Convert value to float; return None on failure."""
    try:
        result = float(val)
        if pd.isna(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def safe_int(val: Any) -> Optional[int]:
    """Convert value to int (via float); return None on failure."""
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def safe_date(val: Any) -> Optional[date]:
    """Parse YYYY-MM-DD string to date; return None on failure."""
    if not val or val == "None":
        return None
    try:
        return datetime.strptime(str(val), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def nan_safe(fn: Callable) -> Callable:
    """Decorator: return '—' for None/NaN/errors, else fn(x)."""
    def _f(x: Any) -> str:
        try:
            if x is None or (isinstance(x, float) and pd.isna(x)):
                return "—"
            return fn(x)
        except (TypeError, ValueError):
            return "—"
    return _f
