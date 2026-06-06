"""News tab — displays stock_news cache for a selected ticker."""
from __future__ import annotations

import streamlit as st


def render(ctx) -> None:
    """Stock News tab."""
    ctx.st.markdown('<div class="tab-header">NEWS</div>', unsafe_allow_html=True)

    symbol = ctx.st.text_input(
        "Symbol", value="AAPL", max_chars=10,
        key="stock_news_symbol",
    ).upper()

    news = ctx.repo.get_news_for_ticker(symbol)
    if not news:
        ctx.st.info(f"No cached news for {symbol}.")
        return

    ctx.st.caption(f"{len(news)} news entries for {symbol}")

    for item in news:
        tool = item["tool_name"]
        fetched = item["fetched_at"].strftime("%Y-%m-%d %H:%M")
        date_range = f"{item['start_date']} → {item['end_date']}"

        with ctx.st.expander(
            f"[{tool}]  {date_range}  —  fetched {fetched}",
            expanded=False,
        ):
            ctx.st.markdown(item["result"], unsafe_allow_html=True)
