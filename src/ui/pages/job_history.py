from __future__ import annotations

import pandas as pd
import streamlit as st


@st.cache_data(ttl=300, show_spinner=False)
def _cached_get_job_runs(limit: int) -> pd.DataFrame:
    from repository import StockRepository
    return StockRepository().get_job_runs(limit=limit)


def render(ctx) -> None:
    """Job History page."""
    ctx.st.markdown('<p class="tab-header">JOB HISTORY</p>', unsafe_allow_html=True)
    ctx.st.title("Scheduled Job History")

    df = _cached_get_job_runs(200)
    if df.empty:
        ctx.st.info("No scheduled jobs have run yet.")
        return

    ctx.st.dataframe(
        df.drop(columns=["id"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Job Name": st.column_config.TextColumn(width="small"),
            "Start Time": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
            "End Time": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
            "Stocks Updated": st.column_config.NumberColumn(width="small"),
            "Status": st.column_config.TextColumn(width="small"),
            "Error": st.column_config.TextColumn(width="medium"),
        },
    )
