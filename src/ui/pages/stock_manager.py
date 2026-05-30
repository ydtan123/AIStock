from __future__ import annotations

import pandas as pd
import streamlit as st

from display import fmt_market_cap, nan_safe
from repository import StockFilters


@st.cache_data(ttl=60, show_spinner=False)
def _cached_count_summary() -> dict:
    from repository import StockRepository
    return StockRepository().count_summary()


@st.cache_data(ttl=300, show_spinner=False)
def _cached_get_sectors_mgr(table: str) -> list[str]:
    from repository import StockRepository
    return StockRepository().get_sectors(table)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_list_stocks(exchange: str, sector: str, min_market_cap: float,
                        max_pe: float, min_roe: float, max_beta: float,
                        status: str) -> pd.DataFrame:
    from repository import StockRepository
    filters = StockFilters(
        exchange=exchange if exchange else None,
        sector=sector if sector else None,
        min_market_cap=min_market_cap,
        max_pe=max_pe,
        min_roe=min_roe,
        max_beta=max_beta,
        status=status,
    )
    return StockRepository().list_stocks(filters)


def render(ctx) -> None:
    """Stock Manager tab."""
    ctx.st.markdown('<div class="tab-header">STOCK MANAGER</div>', unsafe_allow_html=True)

    summary = _cached_count_summary()
    sectors = ["All"] + _cached_get_sectors_mgr("stocks")

    c1, c2, c3 = ctx.st.columns(3)
    c1.metric("Total Listed", summary["total"])
    c2.metric("Active", summary["active"])
    c3.metric("Inactive", summary["inactive"])

    ctx.st.markdown("---")
    ctx.st.markdown("**Filter & Bulk Actions**")

    with ctx.st.form("manager_filter"):
        r1c1, r1c2, r1c3, r1c4 = ctx.st.columns(4)
        with r1c1:
            f_exchange = ctx.st.selectbox("Exchange", ["Both", "NASDAQ", "NYSE"])
            f_sector = ctx.st.selectbox("Sector", sectors)
        with r1c2:
            f_min_mc = ctx.st.number_input("Min Mkt Cap ($B)", min_value=0.0, value=0.0, step=0.5)
            f_max_pe = ctx.st.number_input("Max PE", min_value=0.0, value=999.0, step=5.0)
        with r1c3:
            f_min_roe = ctx.st.number_input("Min ROE (%)", min_value=-200.0, value=-200.0, step=5.0)
            f_max_beta = ctx.st.number_input("Max Beta", min_value=0.0, value=10.0, step=0.5)
        with r1c4:
            f_status = ctx.st.selectbox("Status", ["All", "Active", "Inactive"])
        btn_apply = ctx.st.form_submit_button("Apply Filters", type="primary")

    if btn_apply or "manager_results" not in ctx.session_state:
        df = _cached_list_stocks(
            exchange=f_exchange if f_exchange != "Both" else "",
            sector=f_sector if f_sector != "All" else "",
            min_market_cap=f_min_mc,
            max_pe=f_max_pe,
            min_roe=f_min_roe,
            max_beta=f_max_beta,
            status=f_status,
        )
        ctx.session_state["manager_results"] = df
        ctx.session_state["manager_ids"] = df["id"].tolist()

    df = ctx.session_state.get("manager_results", pd.DataFrame())
    ids = ctx.session_state.get("manager_ids", [])

    if not df.empty:
        ctx.st.caption(f"{len(df)} stocks match filters")
        col_act, col_deact, _ = ctx.st.columns([1, 1, 4])
        with col_act:
            if ctx.st.button("✅ Activate All Filtered"):
                ctx.repo.bulk_set_active(ids, True)
                ctx.st.success(f"Activated {len(ids)} stocks.")
                ctx.st.rerun()
        with col_deact:
            if ctx.st.button("❌ Deactivate All Filtered"):
                ctx.repo.bulk_set_active(ids, False)
                ctx.st.success(f"Deactivated {len(ids)} stocks.")
                ctx.st.rerun()
        df["Mkt Cap"] = df["Mkt Cap"].apply(fmt_market_cap)
        df["ROE %"] = df["ROE %"].apply(nan_safe(lambda x: f"{float(x)*100:.1f}%"))
        df["PE"] = df["PE"].apply(nan_safe(lambda x: f"{float(x):.1f}"))
        df["Beta"] = df["Beta"].apply(nan_safe(lambda x: f"{float(x):.2f}"))
        df["Active"] = df["Active"].apply(lambda x: "● Active" if x else "○ Inactive")
        ctx.st.dataframe(df.drop(columns=["id"]), width='stretch', hide_index=True)
