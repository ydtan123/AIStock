from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from ui.cached_repo import cached_find_stock, cached_get_prices


@st.cache_data(ttl=60, show_spinner=False)
def _cached_get_tech_indicators(stock_id: int, start_str: str, end_str: str) -> pd.DataFrame:
    from repository import StockRepository
    return StockRepository().get_tech_indicators(stock_id, date.fromisoformat(start_str), date.fromisoformat(end_str))


def render(ctx) -> None:
    """Technical Analysis tab."""
    ctx.st.markdown('<div class="tab-header">TECHNICAL ANALYSIS</div>', unsafe_allow_html=True)
    col_sidebar, col_main = ctx.st.columns([1, 3])

    with col_sidebar:
        symbol = ctx.st.text_input("Symbol", value="AAPL", key="ta_symbol", max_chars=10).upper()
        start_date = ctx.st.date_input("Start date", value=date.today() - timedelta(days=365), key="ta_start")
        end_date = ctx.st.date_input("End date", value=date.today(), key="ta_end")
        ctx.st.markdown("**Overlays**")
        show_sma20 = ctx.st.checkbox("SMA 20", value=True)
        show_sma50 = ctx.st.checkbox("SMA 50", value=True)
        show_sma200 = ctx.st.checkbox("SMA 200", value=False)
        show_ema = ctx.st.checkbox("EMA 12/26", value=True)
        show_bb = ctx.st.checkbox("Bollinger Bands", value=True)
        ctx.st.markdown("**Oscillators**")
        show_rsi = ctx.st.checkbox("RSI (14)", value=True)
        show_macd = ctx.st.checkbox("MACD", value=True)
        show_stoch = ctx.st.checkbox("Stochastic", value=False)
        show_atr = ctx.st.checkbox("ATR (14)", value=False)

    with col_main:
        stock = cached_find_stock(symbol)
        if not stock:
            ctx.st.warning(f"Symbol {symbol} not found.")
            return

        prices_df = cached_get_prices(stock["id"], start_date.isoformat(), end_date.isoformat())
        tech_df = _cached_get_tech_indicators(stock["id"], start_date.isoformat(), end_date.isoformat())

        if prices_df.empty:
            ctx.st.info("No price data in selected range.")
            return

        oscil_count = sum([show_rsi, show_macd, show_stoch, show_atr])
        rows = 1 + oscil_count
        row_heights = [0.6] + [0.4 / oscil_count] * oscil_count if oscil_count else [1.0]
        fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, row_heights=row_heights, vertical_spacing=0.03)

        fig.add_trace(go.Candlestick(
            x=prices_df["date"], open=prices_df["open"], high=prices_df["high"],
            low=prices_df["low"], close=prices_df["close"],
            name="OHLC", increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
        ), row=1, col=1)

        if not tech_df.empty:
            if show_sma20 and "SMA_20" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["SMA_20"], name="SMA20", line=dict(color="#f59e0b", width=1)), row=1, col=1)
            if show_sma50 and "SMA_50" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["SMA_50"], name="SMA50", line=dict(color="#8b5cf6", width=1)), row=1, col=1)
            if show_sma200 and "SMA_200" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["SMA_200"], name="SMA200", line=dict(color="#ec4899", width=1)), row=1, col=1)
            if show_ema and "EMA_12" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["EMA_12"], name="EMA12", line=dict(color="#06b6d4", width=1, dash="dot")), row=1, col=1)
            if show_ema and "EMA_26" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["EMA_26"], name="EMA26", line=dict(color="#0ea5e9", width=1, dash="dot")), row=1, col=1)
            if show_bb and "BBU_20_2.0" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["BBU_20_2.0"], name="BB Upper", line=dict(color="#94a3b8", width=1, dash="dash")), row=1, col=1)
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["BBL_20_2.0"], name="BB Lower", line=dict(color="#94a3b8", width=1, dash="dash"), fill="tonexty", fillcolor="rgba(148,163,184,0.1)"), row=1, col=1)

            oscil_row = 2
            if show_rsi and "RSI_14" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["RSI_14"], name="RSI", line=dict(color="#2563eb")), row=oscil_row, col=1)
                fig.add_hline(y=70, line_dash="dash", line_color="#dc2626", row=oscil_row, col=1)
                fig.add_hline(y=30, line_dash="dash", line_color="#16a34a", row=oscil_row, col=1)
                oscil_row += 1
            if show_macd and "MACD_12_26_9" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["MACD_12_26_9"], name="MACD", line=dict(color="#2563eb")), row=oscil_row, col=1)
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df.get("MACDs_12_26_9"), name="Signal", line=dict(color="#f59e0b")), row=oscil_row, col=1)
                if "MACDh_12_26_9" in tech_df:
                    colors = ["#16a34a" if v >= 0 else "#dc2626" for v in tech_df["MACDh_12_26_9"].fillna(0)]
                    fig.add_trace(go.Bar(x=tech_df["date"], y=tech_df["MACDh_12_26_9"], name="Histogram", marker_color=colors), row=oscil_row, col=1)
                oscil_row += 1
            if show_stoch and "STOCHk_14_3_3" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["STOCHk_14_3_3"], name="%K", line=dict(color="#7c3aed")), row=oscil_row, col=1)
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df.get("STOCHd_14_3_3"), name="%D", line=dict(color="#db2777")), row=oscil_row, col=1)
                oscil_row += 1
            if show_atr and "ATRr_14" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["ATRr_14"], name="ATR", line=dict(color="#64748b")), row=oscil_row, col=1)

        fig.update_layout(
            xaxis_rangeslider_visible=False, height=600,
            plot_bgcolor="#f8fafc", paper_bgcolor="#ffffff",
            margin=dict(l=0, r=0, t=10, b=0),
            font=dict(color="#334155"),
        )
        fig.update_xaxes(gridcolor="#f1f5f9")
        fig.update_yaxes(gridcolor="#f1f5f9")
        ctx.st.plotly_chart(fig, width='stretch')
