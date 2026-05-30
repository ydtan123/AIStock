from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from display import fmt_market_cap


@st.cache_data(ttl=300, show_spinner=False)
def _cached_find_stock(symbol: str) -> dict | None:
    from repository import StockRepository
    stock = StockRepository().find_stock(symbol)
    if stock is None:
        return None
    return {"id": stock.id, "symbol": stock.symbol, "name": stock.name,
            "exchange": stock.exchange, "sector": stock.sector,
            "industry": stock.industry, "is_active": stock.is_active}


@st.cache_data(ttl=60, show_spinner=False)
def _cached_get_indicator(stock_id: int) -> dict | None:
    from repository import StockRepository
    ind = StockRepository().get_indicator(stock_id)
    if ind is None:
        return None
    return {"pe_ratio": ind.pe_ratio, "market_cap": ind.market_cap}


@st.cache_data(ttl=60, show_spinner=False)
def _cached_get_prices(stock_id: int, start_str: str, end_str: str) -> pd.DataFrame:
    from repository import StockRepository
    return StockRepository().get_prices(stock_id, date.fromisoformat(start_str), date.fromisoformat(end_str))


def render(ctx) -> None:
    """Stock Lookup tab."""
    ctx.st.markdown('<div class="tab-header">LOOKUP</div>', unsafe_allow_html=True)
    col_sidebar, col_main = ctx.st.columns([1, 3])

    with col_sidebar:
        symbol = ctx.st.text_input("Symbol", value="AAPL", max_chars=10).upper()
        start_date = ctx.st.date_input("Start date", value=date.today() - timedelta(days=365))
        end_date = ctx.st.date_input("End date", value=date.today())

        stock = _cached_find_stock(symbol)
        if stock:
            status_color = "#16a34a" if stock["is_active"] else "#dc2626"
            status_label = "Active" if stock["is_active"] else "Inactive"
            ctx.st.markdown(f"""
            <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;padding:10px;font-size:12px;color:#334155;line-height:1.7;margin-top:8px;">
              <div style="color:#0284c7;font-weight:bold;font-size:14px;">{stock.get("name") or symbol}</div>
              <div>{stock.get("exchange") or '—'} · {stock.get("sector") or '—'}</div>
              <div>{stock.get("industry") or '—'}</div>
              <div style="margin-top:6px;color:{status_color};font-weight:600;">● {status_label}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            ctx.st.info("Symbol not found.")

    with col_main:
        if not stock:
            ctx.st.warning(f"No data for {symbol}. Run bootstrap first.")
            return

        ind = _cached_get_indicator(stock["id"])
        prices_df = _cached_get_prices(stock["id"], start_date.isoformat(), end_date.isoformat())

        last_close = float(prices_df["close"].iloc[-1]) if not prices_df.empty else None
        prev_close = float(prices_df["close"].iloc[-2]) if len(prices_df) > 1 else None
        pct_change = ((last_close - prev_close) / prev_close * 100) if last_close and prev_close else None
        volume = int(prices_df["volume"].iloc[-1]) if not prices_df.empty else None

        c1, c2, c3, c4 = ctx.st.columns(4)
        with c1:
            chg = f"▲ +{pct_change:.2f}%" if pct_change and pct_change >= 0 else (f"▼ {pct_change:.2f}%" if pct_change else "—")
            chg_color = "#16a34a" if pct_change and pct_change >= 0 else "#dc2626"
            ctx.st.markdown(f'<div class="metric-card"><div class="metric-label">CLOSE</div><div class="metric-value" style="color:#0284c7">${last_close:.2f}</div><div class="metric-sub" style="color:{chg_color}">{chg}</div></div>', unsafe_allow_html=True)
        with c2:
            pe = f"{float(ind['pe_ratio']):.1f}" if ind and ind.get("pe_ratio") else "—"
            ctx.st.markdown(f'<div class="metric-card"><div class="metric-label">PE RATIO</div><div class="metric-value" style="color:#d97706">{pe}</div><div class="metric-sub" style="color:#94a3b8">trailing</div></div>', unsafe_allow_html=True)
        with c3:
            mc = fmt_market_cap(ind.get("market_cap") if ind else None)
            ctx.st.markdown(f'<div class="metric-card"><div class="metric-label">MKT CAP</div><div class="metric-value" style="color:#7c3aed">{mc}</div><div class="metric-sub" style="color:#94a3b8">USD</div></div>', unsafe_allow_html=True)
        with c4:
            vol_str = f"{volume/1_000_000:.1f}M" if volume and volume >= 1_000_000 else (f"{volume:,}" if volume else "—")
            ctx.st.markdown(f'<div class="metric-card"><div class="metric-label">VOLUME</div><div class="metric-value" style="color:#16a34a">{vol_str}</div><div class="metric-sub" style="color:#94a3b8">daily</div></div>', unsafe_allow_html=True)

        ctx.st.markdown("<br>", unsafe_allow_html=True)

        if prices_df.empty:
            ctx.st.info("No price data in selected range.")
            return

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.02)
        fig.add_trace(go.Candlestick(
            x=prices_df["date"], open=prices_df["open"], high=prices_df["high"],
            low=prices_df["low"], close=prices_df["close"],
            name="OHLC", increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=prices_df["date"], y=prices_df["adj_close"],
            name="Adj Close", line=dict(color="#2563eb", width=1, dash="dot"),
        ), row=1, col=1)
        fig.add_trace(go.Bar(
            x=prices_df["date"], y=prices_df["volume"],
            name="Volume", marker_color="#cbd5e1",
        ), row=2, col=1)
        fig.update_layout(
            xaxis_rangeslider_visible=False, height=480,
            plot_bgcolor="#f8fafc", paper_bgcolor="#ffffff",
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", y=1.05),
            font=dict(color="#334155"),
        )
        fig.update_xaxes(gridcolor="#f1f5f9")
        fig.update_yaxes(gridcolor="#f1f5f9")
        ctx.st.plotly_chart(fig, width='stretch')

        ctx.st.markdown("**Recent Prices**")
        display_df = prices_df.tail(20).sort_values("date", ascending=False).copy()
        display_df["date"] = display_df["date"].astype(str)
        ctx.st.dataframe(display_df, width='stretch', hide_index=True)
