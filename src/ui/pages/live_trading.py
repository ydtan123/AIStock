from __future__ import annotations

import pandas as pd


def render(ctx) -> None:
    """Live Trading page."""
    ctx.st.header("Live Trading")
    try:
        from trading.alpaca_manager import create_alpaca_account_from_env
        account = create_alpaca_account_from_env()
        ctx.st.success(f"Connected to Alpaca account (Paper: {account.is_paper})")
    except Exception as exc:
        ctx.st.error(f"Trading not configured: {exc}")
        ctx.st.info("Set APCA_API_KEY / APCA_API_SECRET in environment variables.")
        return

    tab1, tab2, tab3 = ctx.st.tabs(["Portfolio", "Order Management", "Strategy Execution"])
    with tab1:
        ctx.st.subheader("Current Portfolio")
        if ctx.st.button("Refresh Portfolio"):
            with ctx.st.spinner("Loading..."):
                try:
                    from trading.alpaca_manager import AlpacaManager
                    manager = AlpacaManager([account])
                    positions = manager.get_positions()
                    if positions:
                        ctx.st.dataframe(
                            pd.DataFrame(positions)[
                                ["symbol", "qty", "avg_entry_price", "market_value", "unrealized_pl"]
                            ],
                            width='stretch',
                        )
                    else:
                        ctx.st.info("No open positions")
                except Exception as exc:
                    ctx.st.error(f"Failed to load portfolio: {exc}")

    with tab2:
        ctx.st.subheader("Order Management")
        with ctx.st.form("place_order"):
            c1, c2, c3 = ctx.st.columns(3)
            with c1:
                symbol = ctx.st.text_input("Symbol", "AAPL").upper()
            with c2:
                quantity = ctx.st.number_input("Quantity", min_value=1, value=10)
            with c3:
                side = ctx.st.selectbox("Side", ["buy", "sell"])
            order_type = ctx.st.selectbox("Order Type", ["market", "limit"])
            limit_price = ctx.st.number_input("Limit Price", min_value=0.01, step=0.01) if order_type == "limit" else None
            if ctx.st.form_submit_button("Place Order"):
                try:
                    from trading.alpaca_manager import AlpacaManager, OrderRequest
                    manager = AlpacaManager([account])
                    order = OrderRequest(symbol=symbol, quantity=quantity, side=side,
                                         order_type=order_type, limit_price=limit_price)
                    response = manager.place_order(order)
                    ctx.st.success(f"Order placed: {response.order_id}")
                except Exception as exc:
                    ctx.st.error(f"Failed to place order: {exc}")

    with tab3:
        ctx.st.subheader("Strategy Execution")
        if ctx.st.button("Execute Sample Strategy"):
            with ctx.st.spinner("Executing..."):
                try:
                    from trading.alpaca_manager import AlpacaManager
                    from trading.trade_executor import TradeExecutor
                    from strategies.base_strategy import StrategyConfig, EqualWeightStrategy
                    manager = AlpacaManager([account])
                    executor = TradeExecutor(manager)
                    config = StrategyConfig(name="Sample Equal Weight")
                    strategy = EqualWeightStrategy(config)
                    result = executor.execute_strategy(strategy, {"fundamentals": pd.DataFrame({
                        "gvkey": ["AAPL", "MSFT", "GOOGL"], "datadate": ["2024-01-01"] * 3,
                    })})
                    ctx.st.success(f"Strategy executed: {len(result.orders_placed)} orders placed")
                except Exception as exc:
                    ctx.st.error(f"Strategy execution failed: {exc}")
