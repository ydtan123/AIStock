from __future__ import annotations

import streamlit as st


@st.cache_data(ttl=60, show_spinner=False)
def _cached_count_summary_overview() -> dict:
    from repository import StockRepository
    return StockRepository().count_summary()


def render(ctx) -> None:
    """Platform Overview page."""
    ctx.st.header("Platform Overview")
    try:
        summary = _cached_count_summary_overview()
    except Exception as exc:
        ctx.st.error(f"Failed to load data: {exc}")
        return

    c1, c2 = ctx.st.columns(2)
    c1.metric("Total Stocks", summary.get("total", "—"))
    c2.metric("Active Stocks", summary.get("active", "—"))
