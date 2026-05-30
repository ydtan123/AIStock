from __future__ import annotations

import pandas as pd
import streamlit as st

from display import fmt_market_cap, nan_safe


@st.cache_data(ttl=300, show_spinner=False)
def _cached_screen_stocks(min_market_cap: float, min_pe: float, max_pe: float,
                          min_roe: float, min_rsi: float, max_rsi: float,
                          max_beta: float, min_div_yield: float,
                          sector: str, exchange: str) -> pd.DataFrame:
    from repository import ScreenCriteria, StockRepository
    criteria = ScreenCriteria(
        min_market_cap=int(min_market_cap),
        min_pe=min_pe, max_pe=max_pe,
        min_roe=min_roe / 100 if min_roe else None,
        min_rsi=min_rsi if min_rsi else None,
        max_rsi=max_rsi if max_rsi else None,
        max_beta=max_beta if max_beta else None,
        min_div_yield=min_div_yield / 100 if min_div_yield else None,
        sector=sector if sector else None,
        exchange=exchange if exchange else None,
    )
    return StockRepository().screen_stocks(criteria)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_get_sectors_screener(table: str) -> list[str]:
    from repository import StockRepository
    return StockRepository().get_sectors(table)


def render(ctx) -> None:
    """Stock Screener tab."""
    ctx.st.markdown('<div class="tab-header">SCREENER</div>', unsafe_allow_html=True)

    with ctx.st.form("screener_form"):
        c1, c2, c3, c4 = ctx.st.columns(4)
        with c1:
            min_mktcap = ctx.st.number_input("Min Market Cap ($B)", min_value=0.0, value=1.0, step=0.5)
            min_roe = ctx.st.number_input("Min ROE (%)", min_value=-100.0, value=0.0, step=5.0)
        with c2:
            min_pe = ctx.st.number_input("Min PE", min_value=0.0, value=0.0, step=1.0)
            max_pe = ctx.st.number_input("Max PE", min_value=0.0, value=100.0, step=5.0)
        with c3:
            min_rsi = ctx.st.number_input("Min RSI", min_value=0.0, value=0.0, step=5.0)
            max_rsi = ctx.st.number_input("Max RSI", min_value=0.0, value=100.0, step=5.0)
        with c4:
            max_beta = ctx.st.number_input("Max Beta", min_value=0.0, value=3.0, step=0.1)
            min_div_yield = ctx.st.number_input("Min Div Yield (%)", min_value=0.0, value=0.0, step=0.5)

        sectors = ["All"] + _cached_get_sectors_screener("stock_snapshots")
        c5, c6 = ctx.st.columns(2)
        with c5:
            sector = ctx.st.selectbox("Sector", sectors)
        with c6:
            exchange = ctx.st.selectbox("Exchange", ["Both", "NASDAQ", "NYSE"])

        submitted = ctx.st.form_submit_button("Run Screen", type="primary")

    if submitted:
        df = _cached_screen_stocks(
            min_market_cap=min_mktcap * 1_000_000_000,
            min_pe=min_pe, max_pe=max_pe,
            min_roe=min_roe,
            min_rsi=min_rsi or 0.0,
            max_rsi=max_rsi or 100.0,
            max_beta=max_beta or 10.0,
            min_div_yield=min_div_yield,
            sector=sector if sector != "All" else "",
            exchange=exchange if exchange != "Both" else "",
        )
        if df.empty:
            ctx.st.info("No results. Try widening filters.")
            return
        df["Market Cap"] = df["Market Cap"].apply(fmt_market_cap)
        df["ROE %"] = df["ROE %"].apply(nan_safe(lambda x: f"{float(x)*100:.1f}%"))
        df["Div Yield %"] = df["Div Yield %"].apply(nan_safe(lambda x: f"{float(x)*100:.2f}%"))
        for col in ["PE", "RSI", "Beta"]:
            df[col] = df[col].apply(nan_safe(lambda x: f"{float(x):.2f}"))
        ctx.st.caption(f"{len(df)} results")
        col_export, _ = ctx.st.columns([1, 5])
        with col_export:
            ctx.st.download_button("Export CSV", df.to_csv(index=False), "screen_results.csv", "text/csv")
        ctx.st.dataframe(df, width='stretch', hide_index=True)
