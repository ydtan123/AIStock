"""Deep Evaluation results page."""
from __future__ import annotations

import streamlit as st


_DECISION_STYLE = {
    "BUY":  ("#1a4a1a", "#7fff7f", "🟢 BUY"),
    "SELL": ("#4a1a1a", "#ff9999", "🔴 SELL"),
    "HOLD": ("#3a3a1a", "#ffff99", "🟡 HOLD"),
}
_DECISION_ORDER = {"BUY": 0, "HOLD": 1, "SELL": 2}


def render(ctx) -> None:
    ctx.st.header("Deep Evaluation")

    # ── Run selector ──────────────────────────────────────────────────────────
    runs = ctx.repo.get_recent_pipeline_runs(limit=20)
    if not runs:
        ctx.st.info("No pipeline runs found. Run the Full Pipeline first.")
        return

    run_labels = {
        r["id"]: f"Run #{r['id']}  {r['started_at'].strftime('%Y-%m-%d %H:%M')}  [{r['status']}]"
        for r in runs
    }
    col1, col2 = ctx.st.columns([2, 2])
    with col1:
        run_id = ctx.st.selectbox(
            "Pipeline run",
            options=list(run_labels.keys()),
            format_func=lambda rid: run_labels[rid],
            key="de_run_id",
        )

    # ── Stock selector ────────────────────────────────────────────────────────
    deep_eval = ctx.repo.get_deep_eval_for_run(run_id)
    if not deep_eval:
        ctx.st.info("No deep evaluation data for this run.")
        return

    tickers_ordered = sorted(
        deep_eval.keys(),
        key=lambda t: _DECISION_ORDER.get(
            (deep_eval[t]["final_decision"] or "").upper(), 3
        ),
    )
    with col2:
        ticker = ctx.st.selectbox("Stock", tickers_ordered, key="de_ticker")

    de = deep_eval[ticker]
    decision = (de["final_decision"] or "").upper()
    bg, fg, label = _DECISION_STYLE.get(
        decision, ("#2a2a2a", "#cccccc", f"⚪ {de['final_decision'] or '—'}")
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    ctx.st.divider()
    ctx.st.subheader(f"{ticker} — Summary")
    ctx.st.markdown(
        f'<div style="background:{bg};padding:16px;border-radius:8px;'
        f'text-align:center;font-size:26px;font-weight:700;color:{fg};">'
        f'{label}</div>',
        unsafe_allow_html=True,
    )
    ctx.st.write("")

    # ── Detail sections ───────────────────────────────────────────────────────
    ctx.st.divider()
    for title, content, expanded in [
        ("📋 Research Manager Decision", de["research_manager_decision"], True),
        ("📈 Trader Plan",               de["trader_plan"],               True),
        ("📊 Market Report",             de["market_report"],             False),
        ("🐂 Bull Argument",             de["bull_argument"],             False),
        ("🐻 Bear Argument",             de["bear_argument"],             False),
    ]:
        if not content:
            continue
        with ctx.st.expander(title, expanded=expanded):
            ctx.st.markdown(content)
