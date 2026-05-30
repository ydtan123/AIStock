from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


@st.cache_data(ttl=300, show_spinner=False)
def _cached_get_latest_selected_stocks() -> list[dict]:
    from repository import StockRepository
    return StockRepository().get_latest_selected_stocks()


def render(ctx) -> None:
    """Portfolio Analysis page."""
    ctx.st.header("Portfolio Analysis")
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    portfolio_values = 1_000_000 + np.cumsum(np.random.normal(2000, 8000, 100))

    tab1, tab2, tab3, tab4 = ctx.st.tabs(["Performance", "Risk Analysis", "Attribution", "Benchmarking"])
    with tab1:
        ctx.st.subheader("Performance Analysis")
        ctx.st.plotly_chart(px.line(x=dates, y=portfolio_values, title="Portfolio Performance"),
                            width='stretch')
        returns = pd.Series(portfolio_values).pct_change().dropna()
        ann_ret = returns.mean() * 252
        vol = returns.std() * np.sqrt(252)
        c1, c2, c3, c4 = ctx.st.columns(4)
        c1.metric("Total Return", f"{(portfolio_values[-1]/portfolio_values[0]-1):.2%}")
        c2.metric("Annual Return", f"{ann_ret:.2%}")
        c3.metric("Volatility", f"{vol:.2%}")
        c4.metric("Sharpe Ratio", f"{ann_ret/vol:.2f}" if vol > 0 else "—")

    with tab2:
        ctx.st.subheader("Risk Analysis")
        returns_s = pd.Series(portfolio_values).pct_change().dropna()
        cum = (1 + returns_s).cumprod()
        dd = (cum - cum.expanding().max()) / cum.expanding().max()
        fig = px.line(x=dates[1:], y=dd, title="Portfolio Drawdown")
        fig.update_layout(yaxis_tickformat=".2%")
        ctx.st.plotly_chart(fig, width='stretch')
        var_95 = float(np.percentile(returns_s, 5))
        c1, c2, c3 = ctx.st.columns(3)
        c1.metric("Max Drawdown", f"{dd.min():.2%}")
        c2.metric("VaR (95%)", f"{var_95:.2%}")
        c3.metric("CVaR (95%)", f"{float(returns_s[returns_s <= var_95].mean()):.2%}")

    with tab3:
        ctx.st.subheader("Attribution Analysis")
        attr = pd.DataFrame({
            "Asset": ["AAPL", "MSFT", "GOOGL", "Bonds", "Cash"],
            "Weight": [0.30, 0.25, 0.20, 0.15, 0.10],
            "Return": [0.15, 0.12, 0.18, 0.03, 0.02],
            "Contribution": [0.045, 0.030, 0.036, 0.0045, 0.002],
        })
        ctx.st.plotly_chart(px.bar(attr, x="Asset", y="Contribution", title="Return Attribution"),
                            width='stretch')
        ctx.st.dataframe(attr, width='stretch')

    with tab4:
        ctx.st.subheader("Benchmarking")
        bench = pd.DataFrame({
            "Date": dates,
            "Portfolio": portfolio_values,
            "SPY": 1_000_000 + np.cumsum(np.random.normal(1500, 6000, 100)),
            "QQQ": 1_000_000 + np.cumsum(np.random.normal(1800, 7000, 100)),
        })
        ctx.st.plotly_chart(px.line(bench, x="Date", y=["Portfolio", "SPY", "QQQ"],
                                    title="Portfolio vs Benchmarks"), width='stretch')
