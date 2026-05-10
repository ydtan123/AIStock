from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from display import fmt_market_cap, nan_safe
from repository import ScreenCriteria, StockFilters, StockRepository


@st.cache_resource
def _load_model_cached():
    from model.train import load_model, load_feature_columns
    from model.labels import LABEL_METHODS
    models = {}
    for method in LABEL_METHODS:
        b = load_model(method.name)
        fc = load_feature_columns(method.name) if b is not None else None
        if b is not None and fc:
            models[method.name] = (b, fc)
    return models


@st.cache_data(ttl=300, show_spinner=False)
def _get_shap(symbol: str, _input_end_date, label_method: str = "max_high_5pct") -> dict | None:
    from model.inference import predict_stocks
    results = predict_stocks([symbol], top_n=8, label_method=label_method)
    return results[0] if results and "error" not in results[0] else None


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


repo = StockRepository()


# ── tab 1: Lookup ─────────────────────────────────────────────────────────────

def tab_lookup():
    st.markdown('<div class="tab-header">LOOKUP</div>', unsafe_allow_html=True)
    col_sidebar, col_main = st.columns([1, 3])

    with col_sidebar:
        symbol = st.text_input("Symbol", value="AAPL", max_chars=10).upper()
        start_date = st.date_input("Start date", value=date.today() - timedelta(days=365))
        end_date = st.date_input("End date", value=date.today())

        stock = repo.find_stock(symbol)
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

        ind = repo.get_indicator(stock.id)
        prices_df = repo.get_prices(stock.id, start_date, end_date)

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
            mc = fmt_market_cap(ind.market_cap if ind else None)
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
        stock = repo.find_stock(symbol)
        if not stock:
            st.warning(f"Symbol {symbol} not found.")
            return

        prices_df = repo.get_prices(stock.id, start_date, end_date)
        tech_df = repo.get_tech_indicators(stock.id, start_date, end_date)

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

        sectors = ["All"] + repo.get_sectors("stock_snapshots")
        exchanges = ["Both", "NASDAQ", "NYSE"]

        c5, c6 = st.columns(2)
        with c5:
            sector = st.selectbox("Sector", sectors)
        with c6:
            exchange = st.selectbox("Exchange", exchanges)

        submitted = st.form_submit_button("Run Screen", type="primary")

    if submitted:
        criteria = ScreenCriteria(
            min_market_cap=int(min_mktcap * 1_000_000_000),
            min_pe=min_pe,
            max_pe=max_pe,
            min_roe=min_roe / 100 if min_roe else None,
            min_rsi=min_rsi if min_rsi else None,
            max_rsi=max_rsi if max_rsi else None,
            max_beta=max_beta if max_beta else None,
            min_div_yield=min_div_yield / 100 if min_div_yield else None,
            sector=sector if sector != "All" else None,
            exchange=exchange if exchange != "Both" else None,
        )
        df = repo.screen_stocks(criteria)

        if df.empty:
            st.info("No results. Try widening filters.")
            return
        df["Market Cap"] = df["Market Cap"].apply(fmt_market_cap)
        df["ROE %"] = df["ROE %"].apply(nan_safe(lambda x: f"{float(x)*100:.1f}%"))
        df["Div Yield %"] = df["Div Yield %"].apply(nan_safe(lambda x: f"{float(x)*100:.2f}%"))
        for col in ["PE", "RSI", "Beta"]:
            df[col] = df[col].apply(nan_safe(lambda x: f"{float(x):.2f}"))

        st.caption(f"{len(df)} results")
        col_export, _ = st.columns([1, 5])
        with col_export:
            st.download_button("Export CSV", df.to_csv(index=False), "screen_results.csv", "text/csv")
        st.dataframe(df, use_container_width=True, hide_index=True)


# ── tab 4: Manager ────────────────────────────────────────────────────────────

def tab_manager():
    st.markdown('<div class="tab-header">STOCK MANAGER</div>', unsafe_allow_html=True)

    summary = repo.count_summary()
    sectors = ["All"] + repo.get_sectors("stocks")

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Listed", summary["total"])
    c2.metric("Active", summary["active"])
    c3.metric("Inactive", summary["inactive"])

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
        filters = StockFilters(
            exchange=f_exchange if f_exchange != "Both" else None,
            sector=f_sector if f_sector != "All" else None,
            min_market_cap=f_min_mc,
            max_pe=f_max_pe,
            min_roe=f_min_roe,
            max_beta=f_max_beta,
            status=f_status,
        )
        df = repo.list_stocks(filters)
        st.session_state["manager_results"] = df
        st.session_state["manager_ids"] = df["id"].tolist()

    df = st.session_state.get("manager_results", pd.DataFrame())
    ids = st.session_state.get("manager_ids", [])

    if not df.empty:
        st.caption(f"{len(df)} stocks match filters")
        col_act, col_deact, _ = st.columns([1, 1, 4])
        with col_act:
            if st.button("✅ Activate All Filtered"):
                repo.bulk_set_active(ids, True)
                st.success(f"Activated {len(ids)} stocks.")
                st.rerun()
        with col_deact:
            if st.button("❌ Deactivate All Filtered"):
                repo.bulk_set_active(ids, False)
                st.success(f"Deactivated {len(ids)} stocks.")
                st.rerun()
        df["Mkt Cap"] = df["Mkt Cap"].apply(fmt_market_cap)
        df["ROE %"] = df["ROE %"].apply(nan_safe(lambda x: f"{float(x)*100:.1f}%"))
        df["PE"] = df["PE"].apply(nan_safe(lambda x: f"{float(x):.1f}"))
        df["Beta"] = df["Beta"].apply(nan_safe(lambda x: f"{float(x):.2f}"))
        df["Active"] = df["Active"].apply(lambda x: "● Active" if x else "○ Inactive")
        st.dataframe(df.drop(columns=["id"]), use_container_width=True, hide_index=True)


# ── tab 5: Predictions ────────────────────────────────────────────────────────

def _shap_chart(items: list[dict], color: str, title: str):
    if not items:
        return
    labels = [i["feature"] for i in items]
    values = [abs(i["contribution"]) for i in items]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker_color=color,
        text=[f"{'+' if color=='#16a34a' else '-'}{v:.4f}" for v in values],
        textposition="outside",
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color="#334155")),
        height=max(180, len(items) * 32 + 60),
        margin=dict(l=0, r=60, t=36, b=0),
        plot_bgcolor="#f8fafc", paper_bgcolor="#ffffff",
        xaxis=dict(visible=False), yaxis=dict(tickfont=dict(size=11)),
        font=dict(color="#334155"),
    )
    st.plotly_chart(fig, use_container_width=True)


@st.dialog("📊 Signal Attribution", width="large")
def _show_attribution_dialog(symbol: str, input_end, p_high=None, p_spy=None):
    # ── stock profile ─────────────────────────────────────────────────────────
    stock = repo.find_stock(symbol)
    ind = repo.get_indicator(stock.id) if stock else None

    if stock:
        st.markdown(f"""
        <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;
                    padding:12px 16px;margin-bottom:12px">
          <div style="font-size:16px;font-weight:700;color:#0f172a">{stock.name or symbol}
            <span style="font-size:12px;font-weight:400;color:#64748b;margin-left:8px">
              {stock.exchange or ''} · {stock.sector or '—'}</span>
          </div>
          <div style="font-size:11px;color:#64748b;margin-top:2px">{stock.industry or ''}</div>
        </div>
        """, unsafe_allow_html=True)

    if ind:
        def _f(val, fmt=".2f", suffix=""):
            return f"{float(val):{fmt}}{suffix}" if val is not None else "—"

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Mkt Cap", fmt_market_cap(ind.market_cap))
        m2.metric("PE", _f(ind.pe_ratio, ".1f"))
        m3.metric("ROE", _f(ind.roe_ttm * 100 if ind.roe_ttm else None, ".1f", "%"))
        m4.metric("Beta", _f(ind.beta, ".2f"))
        m5.metric("Div Yield", _f(ind.dividend_yield * 100 if ind.dividend_yield else None, ".2f", "%"))
        m6.metric("EPS", _f(ind.eps, ".2f"))

        if ind.week_52_high or ind.week_52_low:
            st.caption(f"52W Range: ${_f(ind.week_52_low)} – ${_f(ind.week_52_high)}  ·  "
                       f"Analyst Target: ${_f(ind.analyst_target_price)}")

    st.markdown("---")

    # ── probability summary ───────────────────────────────────────────────────
    def _prob_card(label: str, prob_val, color_hex: str):
        if prob_val is None or prob_val != prob_val:
            st.metric(label, "—")
            return
        p = float(prob_val)
        filled = int(p * 20)
        bar = "█" * filled + "░" * (20 - filled)
        st.markdown(f"""
        <div class="metric-card" style="text-align:left;padding:12px">
          <div class="metric-label">{label}</div>
          <div class="metric-value" style="color:{color_hex}">{p*100:.1f}%</div>
          <div style="font-family:monospace;font-size:13px;color:{color_hex}">{bar}</div>
        </div>
        """, unsafe_allow_html=True)

    available_models = []
    if p_high is not None and p_high == p_high:
        available_models.append(("max_high_5pct", "P(5% high)", p_high))
    if p_spy is not None and p_spy == p_spy:
        available_models.append(("beats_spy", "P(beats SPY)", p_spy))

    if not available_models:
        st.warning("No prediction data available.")
        return

    if len(available_models) == 1:
        selected_model = available_models[0][0]
        pc1, pc2 = st.columns(2)
        with pc1:
            _prob_card(available_models[0][1], available_models[0][2], "#2563eb")
    else:
        options = {f"{label}  {float(p)*100:.1f}%": name for name, label, p in available_models}
        selected_label = st.radio("Attribution model", list(options.keys()), horizontal=True)
        selected_model = options[selected_label]
        pc1, pc2 = st.columns(2)
        with pc1:
            _prob_card(available_models[0][1], available_models[0][2], "#2563eb")
        with pc2:
            _prob_card(available_models[1][1], available_models[1][2], "#7c3aed")

    st.markdown("---")

    # ── attribution ───────────────────────────────────────────────────────────
    with st.spinner(f"Computing {selected_model} attribution for {symbol}..."):
        shap_result = _get_shap(symbol, input_end, label_method=selected_model)

    if shap_result is None:
        st.warning(f"No attribution data for {symbol} ({selected_model}).")
        return

    prob = float(shap_result["probability"])
    color = "#16a34a" if prob >= 0.65 else ("#d97706" if prob >= 0.45 else "#dc2626")

    st.caption(f"SHAP attribution for **{selected_model}** (bias: {shap_result.get('bias', 0):.4f})")

    ac1, ac2 = st.columns(2)
    with ac1:
        _shap_chart(shap_result.get("top_positive", []), "#16a34a", "▲ Bullish Signals")
    with ac2:
        _shap_chart(shap_result.get("top_negative", []), "#dc2626", "▼ Bearish Signals")


def tab_predictions():
    st.markdown('<div class="tab-header">PREDICTIONS</div>', unsafe_allow_html=True)

    if "pred_attr_shown_for" not in st.session_state:
        st.session_state.pred_attr_shown_for = None

    # ── filters ──────────────────────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns([1, 1, 1])
    with fc1:
        sectors = ["All"] + repo.get_sectors("stock_snapshots")
        sector_filter = st.selectbox("Sector", sectors, key="pred_sector")
    with fc2:
        search = st.text_input("Search symbol / name", key="pred_search")
    with fc3:
        _MC_OPTIONS = {
            "All": 0,
            "> $100M": 100_000_000,
            "> $1B": 1_000_000_000,
            "> $10B": 10_000_000_000,
            "> $100B": 100_000_000_000,
        }
        mc_label = st.selectbox("Market Cap", list(_MC_OPTIONS.keys()), key="pred_mc")
        min_mc = _MC_OPTIONS[mc_label]

    df = repo.get_all_predictions(
        sector=sector_filter if sector_filter != "All" else None,
        search=search,
    )

    if min_mc > 0:
        df = df[df["Market Cap"].apply(lambda x: x is not None and x == x and float(x) >= min_mc)]

    if df.empty:
        st.info("No predictions yet. Run `python main.py run` first.")
        return

    # ── summary stats ────────────────────────────────────────────────────────
    primary_col = "P(5% high)" if "P(5% high)" in df.columns else df.columns[2]
    n_bullish = (df[primary_col] >= 0.65).sum()
    n_bearish = (df[primary_col] < 0.35).sum()
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Total", len(df))
    sc2.metric("Bullish (≥65%)", int(n_bullish))
    sc3.metric("Bearish (<35%)", int(n_bearish))
    sc4.metric("Last updated", str(df["Predicted At"].max())[:16] if not df.empty else "—")

    st.markdown("---")

    # ── main table ───────────────────────────────────────────────────────────
    display_df = df.copy()

    def _fmt_prob(x):
        return f"{float(x)*100:.1f}%" if x is not None and x == x else "—"

    if "P(5% high)" in display_df.columns:
        display_df["P(5% high)"] = display_df["P(5% high)"].apply(_fmt_prob)
    if "P(beats SPY)" in display_df.columns:
        display_df["P(beats SPY)"] = display_df["P(beats SPY)"].apply(_fmt_prob)

    display_df["Market Cap"] = display_df["Market Cap"].apply(fmt_market_cap)
    display_df["Close"] = display_df["Close"].apply(nan_safe(lambda x: f"${float(x):.2f}"))
    display_df["RSI"] = display_df["RSI"].apply(nan_safe(lambda x: f"{float(x):.1f}"))
    display_df["As of"] = display_df["Input End"].astype(str)

    show_cols = ["Symbol", "Name", "Sector", "Close", "Market Cap", "RSI"]
    if "P(5% high)" in display_df.columns:
        show_cols.append("P(5% high)")
    if "P(beats SPY)" in display_df.columns:
        show_cols.append("P(beats SPY)")
    show_cols.append("As of")

    col_export, _ = st.columns([1, 5])
    with col_export:
        st.download_button("Export CSV", df.to_csv(index=False), "predictions.csv", "text/csv")

    st.caption("💡 Click any row to view signal attribution.")

    event = st.dataframe(
        display_df[show_cols].head(100),
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        height=600,
    )

    # Open attribution dialog on new row selection
    sel_rows = event.selection.rows
    new_idx = sel_rows[0] if sel_rows else None
    if new_idx is not None and new_idx != st.session_state.pred_attr_shown_for:
        st.session_state.pred_attr_shown_for = new_idx
        row = df.iloc[new_idx]
        p_high = row.get("P(5% high)")
        p_spy = row.get("P(beats SPY)")
        _show_attribution_dialog(row["Symbol"], row["Input End"], p_high, p_spy)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    st.markdown('<h2 style="color:#1e293b;margin-bottom:0">📈 StockDB</h2>', unsafe_allow_html=True)
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Lookup", "Technical Analysis", "Screener", "Manager", "Predictions",
    ])
    with tab1:
        tab_lookup()
    with tab2:
        tab_technical()
    with tab3:
        tab_screener()
    with tab4:
        tab_manager()
    with tab5:
        tab_predictions()


if __name__ == "__main__":
    main()
