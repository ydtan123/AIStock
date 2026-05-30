from __future__ import annotations

import time

import pandas as pd


def render(ctx) -> None:
    """Paper trading: dry-run plan + confirmation gate before order submission."""
    ctx.st.header("Paper Trading")

    if "trading_dry_run_plan" not in ctx.session_state:
        ctx.session_state.trading_dry_run_plan = None

    try:
        from trading.alpaca_manager import create_alpaca_account_from_env, AlpacaManager
        account = create_alpaca_account_from_env()
        manager = AlpacaManager([account])
    except Exception:
        ctx.st.warning("Paper trading not configured. Set APCA_API_KEY / APCA_API_SECRET and restart.")
        return

    try:
        from finrl_runner import DATA_DIR
    except ImportError:
        ctx.st.error("finrl_runner not available.")
        return

    weights_path = None
    for candidate in ["ml_weights_sector.csv", "ml_weights_today.csv"]:
        p = DATA_DIR / candidate
        if p.exists():
            weights_path = p
            break

    if weights_path is None:
        ctx.st.info("No weights file. Run the ML Pipeline first.")
        return

    mtime = weights_path.stat().st_mtime
    age_days = (time.time() - mtime) / 86400
    ctx.st.caption(f"Weights: {weights_path.name} (modified: {pd.Timestamp(mtime, unit='s').strftime('%Y-%m-%d %H:%M')})")
    if age_days > 14:
        ctx.st.warning(f"Weights are {age_days:.0f} days old. Consider re-running the pipeline.")

    try:
        wdf = pd.read_csv(weights_path)
        wdf["date"] = pd.to_datetime(wdf["date"]).dt.date
        latest = wdf[wdf["date"] == wdf["date"].max()]
        target_weights = dict(zip(latest["gvkey"].astype(str), latest["weight"].astype(float)))
    except Exception as exc:
        ctx.st.error(f"Cannot read weights: {exc}")
        return

    if not target_weights:
        ctx.st.info("No target weights in file.")
        return

    if ctx.st.button("Refresh Dry-Run Plan") or ctx.session_state.trading_dry_run_plan is None:
        with ctx.st.spinner("Generating dry-run plan..."):
            try:
                ctx.session_state.trading_dry_run_plan = manager.execute_portfolio_rebalance(
                    target_weights, dry_run=True)
            except Exception as exc:
                ctx.st.error(f"Dry-run failed: {exc}")
                return

    plan = ctx.session_state.trading_dry_run_plan
    ctx.st.subheader("Dry-Run Rebalance Plan")
    ctx.st.caption(f"Market open: {'Yes' if plan.get('market_open') else 'No'} | "
                   f"TIF: {plan.get('used_time_in_force', 'day')}")

    sells = plan.get("orders_plan", {}).get("sell", [])
    buys = plan.get("orders_plan", {}).get("buy", [])
    c1, c2 = ctx.st.columns(2)
    with c1:
        ctx.st.markdown("**Planned Sells**")
        ctx.st.dataframe(pd.DataFrame(sells), width='stretch', hide_index=True) if sells else ctx.st.info("No sells")
    with c2:
        ctx.st.markdown("**Planned Buys**")
        ctx.st.dataframe(pd.DataFrame(buys), width='stretch', hide_index=True) if buys else ctx.st.info("No buys")

    ctx.st.subheader("Submit Orders")
    with ctx.st.form("paper_trading_submit"):
        confirmed = ctx.st.checkbox("I confirm I want to submit these orders to Alpaca Paper Trading.")
        if ctx.st.form_submit_button("Submit Orders", disabled=not confirmed) and confirmed:
            with ctx.st.spinner("Submitting..."):
                try:
                    result = manager.execute_portfolio_rebalance(target_weights, dry_run=False)
                    n = result.get("orders_placed", 0)
                    if n > 0:
                        ctx.st.success(f"{n} orders submitted.")
                        ctx.session_state.trading_dry_run_plan = None
                    elif not result.get("market_open"):
                        ctx.st.info("Market closed. No orders placed.")
                    else:
                        ctx.st.info("Portfolio already at target weights.")
                except Exception as exc:
                    ctx.st.error(f"Submission failed: {exc}")
