from __future__ import annotations

import json

import numpy as np
import pandas as pd
import plotly.express as px


def render(ctx) -> None:
    """Read real backtest JSON files from DATA_DIR and display comparison."""
    ctx.st.header("Strategy Backtesting")

    try:
        from finrl_runner import DATA_DIR
    except ImportError:
        ctx.st.info("finrl_runner module not available.")
        return

    bt_files = sorted(DATA_DIR.glob("backtest_result_*.json"), reverse=True)
    if not bt_files:
        ctx.st.info("No backtest result files found. Run the ML Pipeline to generate results.")
        return

    file_names = [f.name for f in bt_files]
    selected_name = ctx.st.selectbox("Select Backtest Result", file_names)
    selected_path = DATA_DIR / selected_name

    try:
        with open(selected_path) as f:
            bt = json.load(f)
    except Exception:
        ctx.st.warning(f"Could not load {selected_name}.")
        return

    all_m = {"Portfolio": bt.get("metrics", {})}
    all_m.update(bt.get("benchmark_metrics", {}))
    rows = []
    for name, m in all_m.items():
        if not m:
            continue
        rows.append({
            "Strategy": name,
            "Annual Return": f"{m.get('annual_return', 0):.2%}" if m.get("annual_return") is not None else "N/A",
            "Sharpe": f"{m.get('sharpe_ratio', 0):.2f}" if m.get("sharpe_ratio") is not None else "N/A",
            "Max Drawdown": f"{m.get('max_drawdown', 0):.2%}" if m.get("max_drawdown") is not None else "N/A",
            "Calmar": f"{m.get('calmar_ratio', 0):.2f}" if m.get("calmar_ratio") is not None else "N/A",
            "Volatility": f"{m.get('annual_volatility', 0):.2%}" if m.get("annual_volatility") is not None else "N/A",
        })
    if rows:
        ctx.st.subheader("Performance Metrics")
        ctx.st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

    pv = bt.get("portfolio_values", {})
    if pv:
        dates = list(pv.keys())
        values = np.array(list(pv.values()), dtype=float)
        cum = values / values[0]
        fig = px.line(x=dates, y=cum, labels={"x": "Date", "y": "Cumulative Return"})
        fig.update_traces(name="Portfolio", line=dict(color="#1f77b4"))
        for bm_name, bm_s in bt.get("benchmark_values", {}).items():
            if bm_s:
                bm_v = np.array(list(bm_s.values()), dtype=float)
                if len(bm_v) > 0:
                    fig.add_scatter(x=list(bm_s.keys()), y=bm_v / bm_v[0], mode="lines",
                                    name=f"Benchmark ({bm_name})", line=dict(color="#808080", dash="dash"))
        fig.update_layout(yaxis_tickformat=".1%", hovermode="x unified", xaxis_tickangle=-45)
        ctx.st.subheader("Cumulative Return")
        ctx.st.plotly_chart(fig, width='stretch')
    else:
        ctx.st.info("No portfolio value data in this result.")
