from __future__ import annotations

import glob as _glob
import json
import queue
import time
import threading as _threading
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import deque

import streamlit as st

from ui.pages.stock_detail import render as render_stock_detail



@st.cache_data(ttl=3600, show_spinner="Loading ML results...")
def _load_ml_results(data_dir_str: str) -> dict | None:
    """Read and return cached ML result CSVs. Returns None if no weights file."""
    data_dir = Path(data_dir_str)
    weights_path = None
    for candidate in ["ml_weights_sector.csv", "ml_weights_today.csv"]:
        p = data_dir / candidate
        if p.exists():
            weights_path = p
            break
    if weights_path is None:
        return None
    result: dict = {}
    result["weights_path"] = str(weights_path)
    result["weights_df"] = pd.read_csv(weights_path)
    fund_path = data_dir / "fundamentals.csv"
    if fund_path.exists():
        result["fundamentals_df"] = pd.read_csv(fund_path)
    fi_files = sorted(_glob.glob(str(data_dir / "sp500_ml_feature_importance_*.csv")),
                      key=lambda f: Path(f).stat().st_mtime, reverse=True)
    if fi_files:
        result["feature_importance_df"] = pd.read_csv(fi_files[0])
    return result


@st.cache_data(ttl=3600, show_spinner="Loading backtest results...")
def _load_ml_backtest(data_dir_str: str) -> dict | None:
    """Read and return cached backtest JSON. Returns the latest backtest dict."""
    data_dir = Path(data_dir_str)
    bt_files = sorted(data_dir.glob("backtest_result_*.json"), reverse=True)
    if not bt_files:
        return None
    with open(bt_files[0]) as f:
        return json.load(f)


def _show_ml_results(ctx) -> None:
    try:
        from finrl_runner import DATA_DIR
    except ImportError:
        return

    ctx.st.header("Results")
    cached = _load_ml_results(str(DATA_DIR))
    if cached is None:
        ctx.st.info("No weights file. Run the pipeline first.")
        return

    wdf = cached["weights_df"].copy()
    wdf.columns = [c.strip().lower() for c in wdf.columns]

    s_col = None
    if "fundamentals_df" in cached:
        try:
            fdf = cached["fundamentals_df"].copy()
            fdf.columns = [c.strip().lower() for c in fdf.columns]
            s_col = next((c for c in ["sector", "gsector"] if c in fdf.columns), None)
            t_col = next((c for c in ["tic", "ticker"] if c in fdf.columns), None)
            merge_cols = list({"gvkey"} | ({s_col} if s_col else set()) | ({t_col} if t_col else set()))
            mdf = fdf[merge_cols].drop_duplicates(subset="gvkey")
            wdf = wdf.merge(mdf, on="gvkey", how="left")
        except Exception:
            pass

    # Look up company names from StockRepository
    try:
        from repository import StockRepository
        _repo = StockRepository()
        ticker_col = next((c for c in ["tic", "ticker", "gvkey"] if c in wdf.columns), None)
        if ticker_col:
            syms = wdf[ticker_col].dropna().unique().tolist()
            stock_map = _repo.find_stocks_batch(syms)
            name_map = {sym: (stock_map.get(str(sym).upper()).name
                              if stock_map.get(str(sym).upper()) else "")
                        for sym in syms}
            wdf["company"] = wdf[ticker_col].map(name_map)
    except Exception:
        pass

    # Build display column order: ticker → company → sector → weight (no gvkey)
    ticker_display = next((c for c in ["tic", "ticker", "gvkey"] if c in wdf.columns), None)
    ordered: list[str] = []
    if ticker_display:
        ordered.append(ticker_display)
    if "company" in wdf.columns:
        ordered.append("company")
    if s_col and s_col in wdf.columns:
        ordered.append(s_col)
    ordered.append("weight")
    display_cols = [c for c in ordered if c in wdf.columns]

    ctx.st.subheader("Selected Stocks")
    tdf = wdf[display_cols].copy()
    if "weight" in tdf.columns:
        tdf["weight"] = tdf["weight"].apply(lambda x: f"{float(x):.4f}" if pd.notna(x) else "")
    event = ctx.st.dataframe(tdf, selection_mode="single-row", on_select="rerun", width='stretch', key="ml_selected_stocks")
    if ticker_display and event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_ticker = str(tdf.iloc[selected_idx][ticker_display])
        render_stock_detail(ctx, selected_ticker)

    s_col_f = next((c for c in ["sector", "gsector"] if c in wdf.columns), None)
    if s_col_f:
        try:
            sd = wdf.copy()
            sd["weight"] = pd.to_numeric(sd["weight"], errors="coerce").fillna(0)
            count_col = next((c for c in ["tic", "ticker", "gvkey"] if c in sd.columns), "weight")
            agg = (sd.groupby(s_col_f)
                   .agg(stock_count=(count_col, "count"), total_weight=("weight", "sum"))
                   .reset_index().sort_values("total_weight", ascending=False))
            ca, cb = ctx.st.columns(2)
            with ca:
                ctx.st.plotly_chart(px.bar(agg, x=s_col_f, y="stock_count", title="Stock Count per Sector")
                                    .update_layout(xaxis_tickangle=-45), width='stretch')
            with cb:
                ctx.st.plotly_chart(px.bar(agg, x=s_col_f, y="total_weight", title="Total Weight per Sector")
                                    .update_layout(xaxis_tickangle=-45), width='stretch')
        except Exception:
            pass

    if "feature_importance_df" in cached:
        try:
            fi = cached["feature_importance_df"].copy()
            fi.columns = [c.strip().lower() for c in fi.columns]
            fc = next((c for c in fi.columns if c in ("feature", "feature_name")), fi.columns[0])
            ic = next((c for c in fi.columns if c in ("importance", "importance_score")),
                      fi.columns[1] if len(fi.columns) > 1 else fi.columns[0])
            fi_p = fi[[fc, ic]].copy()
            fi_p[ic] = pd.to_numeric(fi_p[ic], errors="coerce").fillna(0)
            fi_p = fi_p.sort_values(ic, ascending=False).head(20)
            ctx.st.subheader("Feature Importance")
            ctx.st.plotly_chart(px.bar(fi_p, x=fc, y=ic, title="Top 20 Feature Importance")
                                .update_layout(xaxis_tickangle=-45), width='stretch')
        except Exception:
            pass


def _show_ml_backtest(ctx) -> None:
    try:
        from finrl_runner import DATA_DIR
    except ImportError:
        return

    bt = _load_ml_backtest(str(DATA_DIR))
    if bt is None:
        ctx.st.info("No backtest results. Run the pipeline to generate one.")
        return

    if "portfolio_values" not in bt or "metrics" not in bt:
        ctx.st.warning("Backtest result is incomplete. Re-run the pipeline.")
        return

    ctx.st.header("Backtest Results")
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
        })
    if rows:
        ctx.st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

    pv = bt["portfolio_values"]
    if pv:
        dates = list(pv.keys())
        values = np.array(list(pv.values()), dtype=float)
        cum = values / values[0]

        _bm_colors = ["#ff7f0e", "#2ca02c", "#9467bd", "#8c564b", "#e377c2"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dates, y=cum, name="Portfolio",
                                 line=dict(color="#1f77b4", width=2)))

        bm_cums: dict = {}
        for i, (bm_name, bm_pv) in enumerate(bt.get("benchmark_values", {}).items()):
            if not bm_pv:
                continue
            bm_vals = np.array(list(bm_pv.values()), dtype=float)
            bm_cum = bm_vals / bm_vals[0]
            bm_dates = list(bm_pv.keys())
            color = _bm_colors[i % len(_bm_colors)]
            fig.add_trace(go.Scatter(x=bm_dates, y=bm_cum, name=bm_name,
                                     line=dict(color=color, width=1.5, dash="dash")))
            bm_cums[bm_name] = (bm_dates, bm_cum)

        fig.update_layout(
            yaxis_tickformat=".1%", hovermode="x unified", xaxis_tickangle=-45,
            yaxis_title="Cumulative Return", xaxis_title="Date",
        )
        ctx.st.plotly_chart(fig, width='stretch')

        # Drawdown — portfolio only
        running_max = np.maximum.accumulate(cum)
        dd = (cum - running_max) / running_max
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(x=dates, y=dd, name="Portfolio",
                                    fill="tozeroy", line=dict(color="#d62728"),
                                    fillcolor="rgba(220,50,50,0.15)"))
        for i, (bm_name, (bm_dates, bm_cum)) in enumerate(bm_cums.items()):
            bm_max = np.maximum.accumulate(bm_cum)
            bm_dd = (bm_cum - bm_max) / bm_max
            color = _bm_colors[i % len(_bm_colors)]
            fig_dd.add_trace(go.Scatter(x=bm_dates, y=bm_dd, name=bm_name,
                                        line=dict(color=color, width=1.5, dash="dash")))
        fig_dd.update_layout(yaxis_tickformat=".1%", xaxis_tickangle=-45,
                             yaxis_title="Drawdown", hovermode="x unified")
        if len(dd) > 0:
            fig_dd.update_yaxes(range=[float(np.min(dd)) * 1.1, 0.02])
        ctx.st.plotly_chart(fig_dd, width='stretch')


def _show_predict_only_results(ctx, pred_data: list[dict]) -> None:
    import pandas as _pd
    import plotly.express as _px

    ctx.st.header("Predict-Only Results")
    df = _pd.DataFrame(pred_data)
    if df.empty:
        ctx.st.info("No predictions.")
        return

    df = df.sort_values("predicted_return", ascending=False)
    df["rank"] = range(1, len(df) + 1)
    cols = ["rank", "ticker", "predicted_return", "actual_return", "model_name", "bucket"]
    has_pred_date = "datadate" in df.columns
    has_actual = "actual_return" in df.columns
    if has_pred_date:
        cols.insert(2, "datadate")
    display = df[[c for c in cols if c in df.columns]].copy()
    display["predicted_return"] = display["predicted_return"].apply(
        lambda x: f"{float(x) * 100:+.2f}%")
    if has_actual:
        display["actual_return"] = display["actual_return"].apply(
            lambda x: f"{float(x) * 100:+.2f}%" if x is not None and _pd.notna(x) else "—")
    col_labels = {
        "rank": "Rank", "ticker": "Ticker", "predicted_return": "Predicted Return",
        "actual_return": "Actual Return", "model_name": "Model", "bucket": "Bucket",
        "datadate": "Prediction Date",
    }
    display.columns = [col_labels.get(c, c) for c in display.columns]

    ctx.st.subheader(f"Top Stocks by Predicted Return ({len(df)} stocks)")
    ctx.st.dataframe(display, width='stretch')

    if len(df) > 5:
        top_n = df.head(20)
        fig = _px.bar(top_n, x="ticker", y="predicted_return",
                      title="Top 20 Predicted Returns",
                      labels={"ticker": "Ticker", "predicted_return": "Predicted Return"})
        fig.update_traces(marker_color="green",
                          marker=dict(line=dict(color="darkgreen", width=1)))
        fig.update_layout(xaxis_tickangle=-45)
        ctx.st.plotly_chart(fig, width='stretch')


def render(ctx) -> None:
    """ML Pipeline page."""
    ctx.st.header("ML Pipeline")

    with ctx.st.expander("How stocks are selected", expanded=False):
        ctx.st.markdown("""
**4-stage pipeline:**

1. **Universe** — Active stocks from the selected data source (AISTOCK_DB = local MySQL).
2. **Fundamentals** — 52 quarterly factors: valuation, profitability, liquidity, leverage, momentum.
3. **ML competition** — 7 models per sector bucket (RF, XGB, LGBM, HGB, ET, Ridge, Stacking).
   Best chosen by validation MSE; score = inverse-MSE weighted ensemble.
4. **Selection** — Stocks ranked by predicted return. Top quantile selected; weights by Weight Method.
""")

    # Load config.yaml defaults via project config module
    try:
        from config import load_config
        yaml_cfg = load_config()
    except Exception:
        yaml_cfg = {}
    data_cfg = yaml_cfg.get("data", {})
    pipe_cfg = yaml_cfg.get("pipeline", {})
    strat_cfg = yaml_cfg.get("strategy", {})
    backt_cfg = yaml_cfg.get("backtest", {})

    with ctx.st.form("ml_pipeline_form"):
        ctx.st.subheader("Configuration")
        c1, c2, c3 = ctx.st.columns(3)
        _src_opts = ["AISTOCK_DB", "FMP", "WRDS", "YAHOO"]
        _src_val = data_cfg.get("preferred_source", "AISTOCK_DB")
        with c1:
            preferred_source = ctx.st.selectbox(
                "Data Source", _src_opts,
                index=_src_opts.index(_src_val) if _src_val in _src_opts else 0,
            )
        with c2:
            start_date = ctx.st.text_input("Start Date", value=str(pipe_cfg.get("start_date", "2020-01-01")))
        with c3:
            end_date = ctx.st.text_input("End Date", value=str(pipe_cfg.get("end_date", "2025-12-31")))

        c4, c5, c6 = ctx.st.columns(3)
        with c4:
            top_quantile = ctx.st.slider("Top Quantile", 0.0, 1.0, float(strat_cfg.get("top_quantile", 0.75)), 0.05)
        with c5:
            test_quarters = ctx.st.number_input("Test Quarters", min_value=1, max_value=40,
                                                value=int(strat_cfg.get("test_quarters", 20)))
        with c6:
            _pm_opts = ["regression", "classification", "ensemble", "rolling", "single"]
            _pm_val = strat_cfg.get("prediction_mode", "regression")
            prediction_mode = ctx.st.selectbox("Prediction Mode", _pm_opts,
                                               index=_pm_opts.index(_pm_val) if _pm_val in _pm_opts else 0)

        c7, c8, c9 = ctx.st.columns(3)
        with c7:
            _wm_opts = ["equal", "inverse_volatility", "ml_score"]
            weight_method = ctx.st.selectbox("Weight Method", _wm_opts,
                                             index=_wm_opts.index(strat_cfg.get("weight_method", "equal")))
        with c8:
            rebalance_freq = ctx.st.selectbox("Rebalance Freq", ["Q", "M", "A"],
                                              index=["Q", "M", "A"].index(backt_cfg.get("rebalance_freq", "Q")))
        with c9:
            initial_capital = ctx.st.number_input("Initial Capital ($)", min_value=10_000, step=10_000,
                                                  value=int(backt_cfg.get("initial_capital", 1_000_000)))

        _default_bms = backt_cfg.get("benchmarks", ["SPY", "QQQ"])
        benchmarks = ctx.st.multiselect(
            "Benchmarks",
            options=["SPY", "QQQ", "DIA", "IWM", "VTI"],
            default=_default_bms,
            help="Benchmark tickers to compare portfolio against",
        )

        run_clicked = ctx.st.form_submit_button("Run Pipeline")
        predict_only_clicked = ctx.st.form_submit_button("Predict Only")

    status = ctx.session_state.get("ml_status", "Idle")
    elapsed = time.time() - ctx.session_state.get("ml_start_time", 0.0) if ctx.session_state.get("ml_start_time", 0) > 0 else 0.0
    color = {"Idle": "gray", "Running": "blue", "Complete": "green", "Error": "red"}.get(status, "gray")
    ctx.st.markdown(f"**Status:** :{color}[{status}]  |  Elapsed: {elapsed:.0f}s")

    if run_clicked and status != "Running":
        ctx.session_state.ml_log_lines = deque(maxlen=1000)
        ctx.session_state.ml_error = None
        ctx.session_state.ml_report_path = None
        # Clear stale sentinels from previous run
        while not ctx.session_state.ml_log_queue.empty():
            try:
                ctx.session_state.ml_log_queue.get_nowait()
            except queue.Empty:
                break
        ctx.session_state.ml_log_queue = queue.Queue()
        ctx.session_state.ml_status = "Running"
        ctx.session_state.ml_start_time = time.time()
        cfg = {
            "preferred_source": preferred_source,
            "start_date": start_date,
            "end_date": end_date,
            "top_quantile": top_quantile,
            "test_quarters": int(test_quarters),
            "prediction_mode": prediction_mode,
            "weight_method": weight_method,
            "rebalance_freq": rebalance_freq,
            "initial_capital": float(initial_capital),
            "benchmarks": benchmarks or ["SPY", "QQQ"],
        }
        _threading.Thread(target=ctx.pipeline_thread_target,
                          args=(cfg, ctx.session_state.ml_log_queue), daemon=True).start()
        ctx.st.rerun()

    if predict_only_clicked and status != "Running":
        ctx.session_state.ml_log_lines = deque(maxlen=1000)
        ctx.session_state.ml_error = None
        ctx.session_state.ml_report_path = None
        ctx.session_state.ml_predict_only_df = None
        # Clear stale sentinels from previous run
        while not ctx.session_state.ml_log_queue.empty():
            try:
                ctx.session_state.ml_log_queue.get_nowait()
            except queue.Empty:
                break
        ctx.session_state.ml_log_queue = queue.Queue()
        ctx.session_state.ml_status = "Running"
        ctx.session_state.ml_start_time = time.time()
        cfg = {
            "source": preferred_source,
        }
        _threading.Thread(target=ctx.predict_only_thread_target,
                          args=(cfg, ctx.session_state.ml_log_queue), daemon=True).start()
        ctx.st.rerun()

    @st.fragment(run_every=2)
    def _show_pipeline_logs():
        """Auto-refreshing log display fragment."""
        # Drain queue in the fragment
        while True:
            try:
                msg = ctx.session_state.ml_log_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(msg, str) and msg.startswith("__PREDICT_DF__:"):
                import json as _json
                ctx.session_state.ml_predict_only_df = _json.loads(msg[len("__PREDICT_DF__:"):])
            elif isinstance(msg, str) and msg.startswith("__REPORT__:"):
                ctx.session_state.ml_report_path = msg[len("__REPORT__:"):]
                ctx.session_state.ml_status = "Complete"
            elif isinstance(msg, str) and msg.startswith("__ERROR__:"):
                ctx.session_state.ml_error = msg[len("__ERROR__:"):]
                ctx.session_state.ml_status = "Error"
            else:
                items = ctx.session_state.ml_log_lines
                items.append(str(msg))
                if not hasattr(items, 'maxlen') and len(items) > 1000:
                    ctx.session_state.ml_log_lines = deque(list(items)[-1000:], maxlen=1000)

        status = ctx.session_state.get("ml_status", "Idle")
        ctx.st.subheader("Log Output")
        if ctx.session_state.ml_log_lines:
            log_text = "\n".join(list(ctx.session_state.ml_log_lines)[-200:])
        elif status == "Running":
            log_text = "Pipeline starting..."
        else:
            log_text = "No runs yet. Configure and click Run Pipeline."
        ctx.st.code(log_text, language=None)

        if ctx.session_state.get("ml_status") == "Error" and ctx.session_state.get("ml_error"):
            ctx.st.error(f"Pipeline failed: {ctx.session_state.ml_error}")

        if ctx.session_state.get("ml_report_path"):
            ctx.st.success(f"Complete. Report: `{ctx.session_state.ml_report_path}`")
            # Check if this is predict-only or full pipeline
            if ctx.session_state.get("ml_predict_only_df"):
                _show_predict_only_results(ctx, ctx.session_state.ml_predict_only_df)
            else:
                _show_ml_results(ctx)
                _show_ml_backtest(ctx)

    _show_pipeline_logs()
