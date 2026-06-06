"""Selected Stocks page — table of ML-selected stocks with evaluation details."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ── helpers ───────────────────────────────────────────────────────────────────

def _decision_emoji(decision: str | None) -> str:
    mapping = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD"}
    return mapping.get((decision or "").upper(), f"⚪ {decision or '—'}")


def _consensus_label(score: float) -> str:
    if score > 0.1:
        return f"🟢 {score:+.3f}"
    if score < -0.1:
        return f"🔴 {score:+.3f}"
    return f"🟡 {score:+.3f}"


def _pct(v) -> str:
    if v is None:
        return "—"
    return f"{v * 100:+.1f}%"


# ── stock detail dialog ───────────────────────────────────────────────────────

@st.dialog("Stock Detail", width="large")
def _show_stock_detail(ticker: str, run_id: int, repo) -> None:
    st.subheader(ticker)

    # Price chart (60 days)
    stock = repo.find_stock(ticker)
    if stock:
        end = date.today()
        start = end - timedelta(days=60)
        prices = repo.get_prices(stock.id, start, end)
        if not prices.empty:
            fig = go.Figure(go.Candlestick(
                x=prices.index,
                open=prices["open"], high=prices["high"],
                low=prices["low"], close=prices["adj_close"],
                name=ticker,
            ))
            fig.update_layout(
                height=280, margin=dict(l=0, r=0, t=24, b=0),
                xaxis_rangeslider_visible=False,
                title_text="60-day price",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No recent price data.")
    else:
        st.caption("Stock not found in DB.")

    # Fast evaluation
    st.divider()
    st.markdown("**Fast Evaluation**")
    fast_data = repo.get_fast_eval_for_run(run_id)
    fe = fast_data.get(ticker)
    if fe:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Consensus", f"{fe['consensus_score']:+.3f}")
        c2.metric("🟢 Bullish", fe["positive"])
        c3.metric("🔴 Bearish", fe["negative"])
        c4.metric("🟡 Neutral", fe["neutral"])
        analysts = repo.get_fast_eval_analysts_for_ticker(run_id, ticker)
        if analysts:
            with st.expander("Analyst opinions"):
                for a in analysts[:12]:
                    emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(a["opinion"], "⚪")
                    st.markdown(
                        f"{emoji} **{a['analyst']}** — {a['opinion'].upper()} "
                        f"(conf: {a['confidence']:.0f}%)"
                    )
                    if a["reasoning"]:
                        st.caption(a["reasoning"][:300])
    else:
        st.caption("No fast evaluation data for this run.")

    # Deep evaluation
    st.divider()
    st.markdown("**Deep Evaluation**")
    deep_data = repo.get_deep_eval_for_run(run_id)
    de = deep_data.get(ticker)
    if de:
        st.markdown(f"**Final Decision:** {_decision_emoji(de['final_decision'])}")
        if de["research_manager_decision"]:
            with st.expander("Research Manager Decision", expanded=True):
                st.markdown(de["research_manager_decision"][:1200])
        if de["trader_plan"]:
            with st.expander("Trader Plan"):
                st.markdown(de["trader_plan"][:1000])
        c1, c2 = st.columns(2)
        with c1:
            if de["bull_argument"]:
                with st.expander("Bull Argument"):
                    st.markdown(de["bull_argument"][:600])
        with c2:
            if de["bear_argument"]:
                with st.expander("Bear Argument"):
                    st.markdown(de["bear_argument"][:600])
    else:
        st.caption("No deep evaluation data for this run.")


# ── main render ───────────────────────────────────────────────────────────────

def render(ctx) -> None:
    ctx.st.header("Selected Stocks")

    # Run selector
    runs = ctx.repo.get_recent_pipeline_runs(limit=20)
    if not runs:
        ctx.st.info("No pipeline runs found. Run the Full Pipeline first.")
        return

    run_labels = {
        r["id"]: (
            f"Run #{r['id']}  {r['started_at'].strftime('%Y-%m-%d %H:%M')}  "
            f"[{r.get('stock_selection_status') or '—'}/{r['status']}]"
        )
        for r in runs
    }
    selected_run_id = ctx.st.selectbox(
        "Pipeline run",
        options=list(run_labels.keys()),
        format_func=lambda rid: run_labels[rid],
        key="ss_run_id",
    )

    # Top-N highlight config (pre-fill from config.yaml)
    try:
        import os as _os
        import yaml as _yaml
        _cfg_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "config.yaml",
        )
        _cfg_path = os.path.abspath(_cfg_path)
        if os.path.exists(_cfg_path):
            with open(_cfg_path) as _f:
                _cfg = _yaml.safe_load(_f) or {}
            default_top_n = int(_cfg.get("fast_evaluation", {}).get("top_n", 3))
        else:
            default_top_n = 3
    except Exception:
        default_top_n = 3

    top_n = ctx.st.number_input(
        "Highlight top N for fast evaluation",
        min_value=1, max_value=50, value=default_top_n, step=1,
        key="ss_top_n",
    )

    # Fetch data
    stocks = ctx.repo.get_selected_stocks_for_run(selected_run_id)
    if not stocks:
        ctx.st.info("No selected stocks for this run.")
        return

    fast_eval = ctx.repo.get_fast_eval_for_run(selected_run_id)
    deep_eval = ctx.repo.get_deep_eval_for_run(selected_run_id)

    # Build display DataFrame
    rows = []
    for i, s in enumerate(stocks):
        ticker = s["ticker"]
        fe = fast_eval.get(ticker, {})
        de = deep_eval.get(ticker, {})
        rows.append({
            "#": i + 1,
            "Ticker": ticker,
            "ML Score": s["ml_score"],
            "Pred Return": _pct(s["predicted_return"]),
            "Sector": s["sector"] or s["bucket"] or "—",
            "Consensus": _consensus_label(fe["consensus_score"]) if fe else "—",
            "🟢/🔴/🟡": f"{fe['positive']}/{fe['negative']}/{fe['neutral']}" if fe else "—",
            "Decision": _decision_emoji(de.get("final_decision")) if de else "—",
            "⭐": "⭐" if i < top_n else "",
        })

    df = pd.DataFrame(rows)

    def _highlight(row):
        if row["#"] <= top_n:
            return ["background-color:#1a3a1a; color:#7fff7f"] * len(row)
        return [""] * len(row)

    styled = (
        df.style
        .apply(_highlight, axis=1)
        .format({"ML Score": "{:.4f}"}, na_rep="—")
    )

    ctx.st.dataframe(styled, use_container_width=True, hide_index=True)
    ctx.st.caption(f"⭐ Top {int(top_n)} rows highlighted — candidates for fast evaluation")

    # Ticker selector → popup
    ctx.st.divider()
    tickers = [s["ticker"] for s in stocks]
    col1, col2 = ctx.st.columns([3, 1])
    with col1:
        selected_ticker = ctx.st.selectbox("View stock detail", tickers, key="ss_ticker")
    with col2:
        ctx.st.write("")
        ctx.st.write("")
        if ctx.st.button("View Details", key="ss_view_btn", type="primary"):
            _show_stock_detail(selected_ticker, selected_run_id, ctx.repo)
