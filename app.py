import json
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from sqlalchemy import text

from database import get_engine, get_session
from models import Stock, DailyPrice, StockIndicator, StockSnapshot, TechnicalIndicator

st.set_page_config(page_title="StockDB", page_icon="📈", layout="wide")

st.markdown("""
<style>
.metric-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.metric-label { color: #94a3b8; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }
.metric-value { color: #0f172a; font-size: 22px; font-weight: 700; margin: 4px 0; }
.metric-sub { font-size: 11px; }
.tab-header { color: #2563eb; font-size: 11px; letter-spacing: 1px; font-weight: 600; margin-bottom: 12px; }
</style>
""", unsafe_allow_html=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmt_market_cap(val) -> str:
    if val is None:
        return "—"
    val = int(val)
    if val >= 1_000_000_000_000:
        return f"${val/1_000_000_000_000:.2f}T"
    if val >= 1_000_000_000:
        return f"${val/1_000_000_000:.2f}B"
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    return f"${val:,}"


def _get_stock(symbol: str) -> Stock | None:
    session = get_session()
    try:
        return session.query(Stock).filter_by(symbol=symbol.upper()).first()
    finally:
        session.close()


def _get_prices(stock_id: int, start: date, end: date) -> pd.DataFrame:
    session = get_session()
    try:
        rows = (
            session.query(DailyPrice)
            .filter(DailyPrice.stock_id == stock_id, DailyPrice.date >= start, DailyPrice.date <= end)
            .order_by(DailyPrice.date)
            .all()
        )
        return pd.DataFrame([{
            "date": r.date, "open": r.open, "high": r.high, "low": r.low,
            "close": r.close, "adj_close": r.adj_close, "volume": r.volume,
        } for r in rows])
    finally:
        session.close()


def _get_indicator(stock_id: int) -> StockIndicator | None:
    session = get_session()
    try:
        return session.query(StockIndicator).filter_by(stock_id=stock_id).first()
    finally:
        session.close()


def _get_tech_indicators(stock_id: int, start: date, end: date) -> pd.DataFrame:
    session = get_session()
    try:
        rows = (
            session.query(TechnicalIndicator)
            .filter(TechnicalIndicator.stock_id == stock_id,
                    TechnicalIndicator.date >= start, TechnicalIndicator.date <= end)
            .order_by(TechnicalIndicator.date)
            .all()
        )
        records = []
        for r in rows:
            d = {"date": r.date}
            if r.indicators:
                d.update(r.indicators)
            records.append(d)
        return pd.DataFrame(records)
    finally:
        session.close()


# ── tab 1: Lookup ─────────────────────────────────────────────────────────────

def tab_lookup():
    st.markdown('<div class="tab-header">LOOKUP</div>', unsafe_allow_html=True)
    col_sidebar, col_main = st.columns([1, 3])

    with col_sidebar:
        symbol = st.text_input("Symbol", value="AAPL", max_chars=10).upper()
        start_date = st.date_input("Start date", value=date.today() - timedelta(days=365))
        end_date = st.date_input("End date", value=date.today())

        stock = _get_stock(symbol)
        if stock:
            status_color = "#16a34a" if stock.is_active else "#dc2626"
            status_label = "Active" if stock.is_active else "Inactive"
            st.markdown(f"""
            <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;padding:10px;font-size:12px;color:#334155;line-height:1.7;margin-top:8px;">
              <div style="color:#0284c7;font-weight:bold;font-size:14px;">{stock.name or symbol}</div>
              <div>{stock.exchange or '—'} · {stock.sector or '—'}</div>
              <div>{stock.industry or '—'}</div>
              <div style="margin-top:6px;color:{status_color};font-weight:600;">● {status_label}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("Symbol not found.")

    with col_main:
        if not stock:
            st.warning(f"No data for {symbol}. Run bootstrap first.")
            return

        ind = _get_indicator(stock.id)
        prices_df = _get_prices(stock.id, start_date, end_date)

        # Metric cards
        last_close = float(prices_df["close"].iloc[-1]) if not prices_df.empty else None
        prev_close = float(prices_df["close"].iloc[-2]) if len(prices_df) > 1 else None
        pct_change = ((last_close - prev_close) / prev_close * 100) if last_close and prev_close else None
        volume = int(prices_df["volume"].iloc[-1]) if not prices_df.empty else None

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            chg = f"▲ +{pct_change:.2f}%" if pct_change and pct_change >= 0 else (f"▼ {pct_change:.2f}%" if pct_change else "—")
            chg_color = "#16a34a" if pct_change and pct_change >= 0 else "#dc2626"
            st.markdown(f'<div class="metric-card"><div class="metric-label">CLOSE</div><div class="metric-value" style="color:#0284c7">${last_close:.2f}</div><div class="metric-sub" style="color:{chg_color}">{chg}</div></div>', unsafe_allow_html=True)
        with c2:
            pe = f"{float(ind.pe_ratio):.1f}" if ind and ind.pe_ratio else "—"
            st.markdown(f'<div class="metric-card"><div class="metric-label">PE RATIO</div><div class="metric-value" style="color:#d97706">{pe}</div><div class="metric-sub" style="color:#94a3b8">trailing</div></div>', unsafe_allow_html=True)
        with c3:
            mc = _fmt_market_cap(ind.market_cap if ind else None)
            st.markdown(f'<div class="metric-card"><div class="metric-label">MKT CAP</div><div class="metric-value" style="color:#7c3aed">{mc}</div><div class="metric-sub" style="color:#94a3b8">USD</div></div>', unsafe_allow_html=True)
        with c4:
            vol_str = f"{volume/1_000_000:.1f}M" if volume and volume >= 1_000_000 else (f"{volume:,}" if volume else "—")
            st.markdown(f'<div class="metric-card"><div class="metric-label">VOLUME</div><div class="metric-value" style="color:#16a34a">{vol_str}</div><div class="metric-sub" style="color:#94a3b8">daily</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if prices_df.empty:
            st.info("No price data in selected range.")
            return

        # Candlestick chart
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
        st.plotly_chart(fig, use_container_width=True)

        # Recent data table
        st.markdown("**Recent Prices**")
        display_df = prices_df.tail(20).sort_values("date", ascending=False).copy()
        display_df["date"] = display_df["date"].astype(str)
        st.dataframe(display_df, use_container_width=True, hide_index=True)


# ── tab 2: Technical Analysis ─────────────────────────────────────────────────

def tab_technical():
    st.markdown('<div class="tab-header">TECHNICAL ANALYSIS</div>', unsafe_allow_html=True)
    col_sidebar, col_main = st.columns([1, 3])

    with col_sidebar:
        symbol = st.text_input("Symbol", value="AAPL", key="ta_symbol", max_chars=10).upper()
        start_date = st.date_input("Start date", value=date.today() - timedelta(days=365), key="ta_start")
        end_date = st.date_input("End date", value=date.today(), key="ta_end")
        st.markdown("**Overlays**")
        show_sma20 = st.checkbox("SMA 20", value=True)
        show_sma50 = st.checkbox("SMA 50", value=True)
        show_sma200 = st.checkbox("SMA 200", value=False)
        show_ema = st.checkbox("EMA 12/26", value=True)
        show_bb = st.checkbox("Bollinger Bands", value=True)
        st.markdown("**Oscillators**")
        show_rsi = st.checkbox("RSI (14)", value=True)
        show_macd = st.checkbox("MACD", value=True)
        show_stoch = st.checkbox("Stochastic", value=False)
        show_atr = st.checkbox("ATR (14)", value=False)

    with col_main:
        stock = _get_stock(symbol)
        if not stock:
            st.warning(f"Symbol {symbol} not found.")
            return

        prices_df = _get_prices(stock.id, start_date, end_date)
        tech_df = _get_tech_indicators(stock.id, start_date, end_date)

        if prices_df.empty:
            st.info("No price data in selected range.")
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
        st.plotly_chart(fig, use_container_width=True)


# ── tab 3: Screener ───────────────────────────────────────────────────────────

def tab_screener():
    st.markdown('<div class="tab-header">SCREENER</div>', unsafe_allow_html=True)

    with st.form("screener_form"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            min_mktcap = st.number_input("Min Market Cap ($B)", min_value=0.0, value=1.0, step=0.5)
            min_roe = st.number_input("Min ROE (%)", min_value=-100.0, value=0.0, step=5.0)
        with c2:
            min_pe = st.number_input("Min PE", min_value=0.0, value=0.0, step=1.0)
            max_pe = st.number_input("Max PE", min_value=0.0, value=100.0, step=5.0)
        with c3:
            min_rsi = st.number_input("Min RSI", min_value=0.0, value=0.0, step=5.0)
            max_rsi = st.number_input("Max RSI", min_value=0.0, value=100.0, step=5.0)
        with c4:
            max_beta = st.number_input("Max Beta", min_value=0.0, value=3.0, step=0.1)
            min_div_yield = st.number_input("Min Div Yield (%)", min_value=0.0, value=0.0, step=0.5)

        session = get_session()
        try:
            sectors = ["All"] + [r[0] for r in session.execute(text("SELECT DISTINCT sector FROM stock_snapshots WHERE sector IS NOT NULL ORDER BY sector")).fetchall()]
            exchanges = ["Both", "NASDAQ", "NYSE"]
        finally:
            session.close()

        c5, c6 = st.columns(2)
        with c5:
            sector = st.selectbox("Sector", sectors)
        with c6:
            exchange = st.selectbox("Exchange", exchanges)

        submitted = st.form_submit_button("Run Screen", type="primary")

    if submitted:
        session = get_session()
        try:
            q = """
            SELECT s.symbol, s.name, ss.market_cap, ss.pe_ratio, ss.roe_ttm,
                   ss.rsi_14, ss.beta, ss.dividend_yield, ss.sector, ss.exchange
            FROM stock_snapshots ss
            JOIN stocks s ON s.id = ss.stock_id
            WHERE ss.market_cap >= :min_mc
              AND (ss.pe_ratio IS NULL OR (ss.pe_ratio >= :min_pe AND ss.pe_ratio <= :max_pe))
              AND (ss.roe_ttm IS NULL OR ss.roe_ttm >= :min_roe)
              AND (ss.rsi_14 IS NULL OR (ss.rsi_14 >= :min_rsi AND ss.rsi_14 <= :max_rsi))
              AND (ss.beta IS NULL OR ss.beta <= :max_beta)
              AND (ss.dividend_yield IS NULL OR ss.dividend_yield >= :min_div)
            """
            params = {
                "min_mc": int(min_mktcap * 1_000_000_000),
                "min_pe": min_pe, "max_pe": max_pe,
                "min_roe": min_roe / 100,
                "min_rsi": min_rsi, "max_rsi": max_rsi,
                "max_beta": max_beta,
                "min_div": min_div_yield / 100,
            }
            if sector != "All":
                q += " AND ss.sector = :sector"
                params["sector"] = sector
            if exchange != "Both":
                q += " AND ss.exchange = :exchange"
                params["exchange"] = exchange
            q += " ORDER BY ss.market_cap DESC LIMIT 500"

            rows = session.execute(text(q), params).fetchall()
        finally:
            session.close()

        if not rows:
            st.info("No results. Try widening filters.")
            return

        df = pd.DataFrame(rows, columns=["Symbol", "Name", "Market Cap", "PE", "ROE %", "RSI", "Beta", "Div Yield %", "Sector", "Exchange"])
        df["Market Cap"] = df["Market Cap"].apply(_fmt_market_cap)
        df["ROE %"] = df["ROE %"].apply(lambda x: f"{float(x)*100:.1f}%" if x else "—")
        df["Div Yield %"] = df["Div Yield %"].apply(lambda x: f"{float(x)*100:.2f}%" if x else "—")
        for col in ["PE", "RSI", "Beta"]:
            df[col] = df[col].apply(lambda x: f"{float(x):.2f}" if x else "—")

        st.caption(f"{len(df)} results")
        col_export, _ = st.columns([1, 5])
        with col_export:
            st.download_button("Export CSV", df.to_csv(index=False), "screen_results.csv", "text/csv")
        st.dataframe(df, use_container_width=True, hide_index=True)


# ── tab 4: Manager ────────────────────────────────────────────────────────────

def tab_manager():
    st.markdown('<div class="tab-header">STOCK MANAGER</div>', unsafe_allow_html=True)

    session = get_session()
    try:
        total = session.query(Stock).count()
        active = session.query(Stock).filter_by(is_active=True).count()
        inactive = total - active
        sectors = ["All"] + [r[0] for r in session.execute(text("SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL ORDER BY sector")).fetchall()]
    finally:
        session.close()

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Listed", total)
    c2.metric("Active", active)
    c3.metric("Inactive", inactive)

    st.markdown("---")
    st.markdown("**Filter & Bulk Actions**")

    with st.form("manager_filter"):
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        with r1c1:
            f_exchange = st.selectbox("Exchange", ["Both", "NASDAQ", "NYSE"])
            f_sector = st.selectbox("Sector", sectors)
        with r1c2:
            f_min_mc = st.number_input("Min Mkt Cap ($B)", min_value=0.0, value=0.0, step=0.5)
            f_max_pe = st.number_input("Max PE", min_value=0.0, value=999.0, step=5.0)
        with r1c3:
            f_min_roe = st.number_input("Min ROE (%)", min_value=-200.0, value=-200.0, step=5.0)
            f_max_beta = st.number_input("Max Beta", min_value=0.0, value=10.0, step=0.5)
        with r1c4:
            f_status = st.selectbox("Status", ["All", "Active", "Inactive"])

        btn_apply = st.form_submit_button("Apply Filters", type="primary")

    if btn_apply or "manager_results" not in st.session_state:
        session = get_session()
        try:
            q = """
            SELECT s.id, s.symbol, s.name, si.market_cap, s.sector, si.pe_ratio,
                   si.roe_ttm, si.beta, s.is_active, s.exchange
            FROM stocks s
            LEFT JOIN stock_indicators si ON si.stock_id = s.id
            WHERE 1=1
            """
            params = {}
            if f_exchange != "Both":
                q += " AND s.exchange = :exchange"
                params["exchange"] = f_exchange
            if f_sector != "All":
                q += " AND s.sector = :sector"
                params["sector"] = f_sector
            if f_min_mc > 0:
                q += " AND si.market_cap >= :min_mc"
                params["min_mc"] = int(f_min_mc * 1_000_000_000)
            if f_max_pe < 999:
                q += " AND si.pe_ratio <= :max_pe"
                params["max_pe"] = f_max_pe
            if f_min_roe > -200:
                q += " AND si.roe_ttm >= :min_roe"
                params["min_roe"] = f_min_roe / 100
            if f_max_beta < 10:
                q += " AND si.beta <= :max_beta"
                params["max_beta"] = f_max_beta
            if f_status == "Active":
                q += " AND s.is_active = 1"
            elif f_status == "Inactive":
                q += " AND s.is_active = 0"
            q += " ORDER BY si.market_cap DESC LIMIT 500"

            rows = session.execute(text(q), params).fetchall()
            st.session_state["manager_results"] = rows
            st.session_state["manager_ids"] = [r[0] for r in rows]
        finally:
            session.close()

    rows = st.session_state.get("manager_results", [])
    ids = st.session_state.get("manager_ids", [])

    if rows:
        st.caption(f"{len(rows)} stocks match filters")
        col_act, col_deact, _ = st.columns([1, 1, 4])
        with col_act:
            if st.button("✅ Activate All Filtered"):
                _bulk_set_active(ids, True)
                st.success(f"Activated {len(ids)} stocks.")
                st.rerun()
        with col_deact:
            if st.button("❌ Deactivate All Filtered"):
                _bulk_set_active(ids, False)
                st.success(f"Deactivated {len(ids)} stocks.")
                st.rerun()

        df = pd.DataFrame(rows, columns=["id", "Symbol", "Name", "Mkt Cap", "Sector", "PE", "ROE %", "Beta", "Active", "Exchange"])
        df["Mkt Cap"] = df["Mkt Cap"].apply(_fmt_market_cap)
        df["ROE %"] = df["ROE %"].apply(lambda x: f"{float(x)*100:.1f}%" if x else "—")
        df["PE"] = df["PE"].apply(lambda x: f"{float(x):.1f}" if x else "—")
        df["Beta"] = df["Beta"].apply(lambda x: f"{float(x):.2f}" if x else "—")
        df["Active"] = df["Active"].apply(lambda x: "● Active" if x else "○ Inactive")
        st.dataframe(df.drop(columns=["id"]), use_container_width=True, hide_index=True)


def _bulk_set_active(ids: list[int], active: bool):
    if not ids:
        return
    session = get_session()
    try:
        now = datetime.utcnow() if active else None
        session.execute(
            text("UPDATE stocks SET is_active=:a, activated_at=:t WHERE id IN :ids"),
            {"a": active, "t": now, "ids": tuple(ids)},
        )
        session.commit()
    finally:
        session.close()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    st.markdown('<h2 style="color:#1e293b;margin-bottom:0">📈 StockDB</h2>', unsafe_allow_html=True)
    tab1, tab2, tab3, tab4 = st.tabs(["Lookup", "Technical Analysis", "Screener", "Manager"])
    with tab1:
        tab_lookup()
    with tab2:
        tab_technical()
    with tab3:
        tab_screener()
    with tab4:
        tab_manager()


if __name__ == "__main__":
    main()
