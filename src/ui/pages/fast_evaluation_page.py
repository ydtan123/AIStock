"""Fast Evaluation results page."""
from __future__ import annotations

import streamlit as st


_OPINION_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}


def render(ctx) -> None:
    ctx.st.header("Fast Evaluation")

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
            key="fe_run_id",
        )

    # ── Stock selector ────────────────────────────────────────────────────────
    fast_eval = ctx.repo.get_fast_eval_for_run(run_id)
    if not fast_eval:
        ctx.st.info("No fast evaluation data for this run.")
        return

    tickers_ordered = sorted(
        fast_eval.keys(),
        key=lambda t: fast_eval[t]["consensus_score"],
        reverse=True,
    )
    with col2:
        ticker = ctx.st.selectbox("Stock", tickers_ordered, key="fe_ticker")

    fe = fast_eval[ticker]

    # ── Summary ───────────────────────────────────────────────────────────────
    ctx.st.divider()
    ctx.st.subheader(f"{ticker} — Summary")

    consensus = fe["consensus_score"]
    if consensus > 0.1:
        direction, color, text_color = "🟢 Bullish", "#1a4a1a", "#7fff7f"
    elif consensus < -0.1:
        direction, color, text_color = "🔴 Bearish", "#4a1a1a", "#ff9999"
    else:
        direction, color, text_color = "🟡 Neutral", "#3a3a1a", "#ffff99"

    ctx.st.markdown(
        f'<div style="background:{color};padding:16px;border-radius:8px;'
        f'text-align:center;font-size:22px;font-weight:700;color:{text_color};">'
        f'{direction}&nbsp;&nbsp;{consensus:+.4f}</div>',
        unsafe_allow_html=True,
    )
    ctx.st.write("")

    total = fe["total"] or 1
    c1, c2, c3, c4 = ctx.st.columns(4)
    c1.metric("🟢 Bullish", fe["positive"], f"{fe['positive']/total*100:.0f}%")
    c2.metric("🔴 Bearish", fe["negative"], f"{fe['negative']/total*100:.0f}%")
    c3.metric("🟡 Neutral", fe["neutral"], f"{fe['neutral']/total*100:.0f}%")
    c4.metric("Total Analysts", fe["total"])

    # ── Per-analyst analysis ──────────────────────────────────────────────────
    ctx.st.divider()
    ctx.st.subheader("Analyst Opinions")

    analysts = ctx.repo.get_fast_eval_analysts_for_ticker(run_id, ticker)
    if not analysts:
        ctx.st.info("No analyst data.")
        return

    groups: dict[str, list] = {"bullish": [], "bearish": [], "neutral": []}
    for a in analysts:
        groups.get(a["opinion"], groups["neutral"]).append(a)

    for opinion in ("bullish", "bearish", "neutral"):
        group = groups[opinion]
        if not group:
            continue
        emoji = _OPINION_EMOJI[opinion]
        ctx.st.markdown(f"### {emoji} {opinion.capitalize()} ({len(group)})")
        for a in group:
            with ctx.st.expander(
                f"{emoji} **{a['analyst']}** — conf: {a['confidence']:.0f}%",
                expanded=(opinion == "bullish" and a["confidence"] >= 70),
            ):
                if a["reasoning"]:
                    ctx.st.markdown(a["reasoning"])
                else:
                    ctx.st.caption("No reasoning provided.")
