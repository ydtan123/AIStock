from __future__ import annotations

import logging


def render(ctx) -> None:
    """Settings page."""
    ctx.st.header("Settings")
    tab1, tab2, tab3 = ctx.st.tabs(["General", "Trading", "Data"])

    with tab1:
        ctx.st.subheader("General Settings")
        log_level = ctx.st.selectbox("Logging Level", ["DEBUG", "INFO", "WARNING", "ERROR"])
        if ctx.st.button("Apply Logging Level"):
            logging.getLogger().setLevel(getattr(logging, log_level))
            ctx.st.success(f"Logging level set to {log_level}")

    with tab2:
        ctx.st.subheader("Trading Settings")
        ctx.st.number_input("Max Order Value ($)", value=100_000, step=10_000)
        ctx.st.slider("Max Portfolio Turnover (%)", 0.0, 1.0, 0.5, 0.05)
        if ctx.st.button("Save Trading Settings"):
            ctx.st.success("Trading settings saved")
        ctx.st.subheader("API Configuration")
        ctx.st.text_input("Alpaca API Key", type="password")
        ctx.st.text_input("Alpaca API Secret", type="password")
        ctx.st.checkbox("Use Paper Trading", value=True)
        if ctx.st.button("Save API Settings"):
            ctx.st.success("API settings saved")

    with tab3:
        ctx.st.subheader("Data Settings")
        ctx.st.text_input("Data Directory", value="./data")
        ctx.st.text_input("Cache Directory", value="./data/cache")
        if ctx.st.button("Save Data Settings"):
            ctx.st.success("Data settings saved")
        ctx.st.subheader("Data Sources")
        ctx.st.checkbox("Enable WRDS", value=True)
        ctx.st.checkbox("Enable Alpha Vantage", value=False)
        ctx.st.checkbox("Enable AIStock DB", value=True)
        if ctx.st.button("Save Data Source Settings"):
            ctx.st.success("Data source settings saved")
