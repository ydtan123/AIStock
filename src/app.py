from datetime import date, timedelta
import logging
import os
import queue
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from display import fmt_market_cap, nan_safe
from repository import ScreenCriteria, StockFilters, StockRepository

# Ensure AIStock src/ is FIRST in sys.path so its config.py shadows FinRL's
# config package. FinRL src/ appended after — must NOT precede AIStock src.
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

_finrl_src = os.path.abspath(os.path.join(_src_dir, "..", "external", "FinRL-Trading", "src"))
if _finrl_src not in sys.path:
    sys.path.append(_finrl_src)

# ── Page config (exactly once) ────────────────────────────────────────────────
st.set_page_config(
    page_title="AIStock Trading Platform",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.metric-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.metric-label { color: #94a3b8; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }
.metric-value { color: #0f172a; font-size: 22px; font-weight: 700; margin: 4px 0; }
.metric-sub { font-size: 11px; }
.tab-header { color: #2563eb; font-size: 11px; letter-spacing: 1px; font-weight: 600; margin-bottom: 12px; }
</style>
""", unsafe_allow_html=True)

repo = StockRepository()

# ML pipeline session state
if "ml_status" not in st.session_state:
    st.session_state.ml_status = "Idle"
if "ml_log_lines" not in st.session_state:
    st.session_state.ml_log_lines = []
if "ml_report_path" not in st.session_state:
    st.session_state.ml_report_path = None
if "ml_error" not in st.session_state:
    st.session_state.ml_error = None
if "ml_start_time" not in st.session_state:
    st.session_state.ml_start_time = 0.0
if "ml_log_queue" not in st.session_state:
    st.session_state.ml_log_queue = queue.Queue()


# ── ML Pipeline ──────────────────────────────────────────────────────────────


class _QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_queue.put_nowait(self.format(record))
        except (queue.Full, Exception):
            pass


class _StdoutToQueue:
    """Redirect sys.stdout writes to the log queue so print() appears in UI."""

    def __init__(self, log_queue: queue.Queue, original) -> None:
        self._q = log_queue
        self._orig = original
        self._buf = ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                try:
                    self._q.put_nowait(line)
                except Exception:
                    pass
        return len(text)

    def flush(self) -> None:
        if self._buf:
            try:
                self._q.put_nowait(self._buf)
            except Exception:
                pass
            self._buf = ""

    def __getattr__(self, name):
        return getattr(self._orig, name)


def _pipeline_thread_target(cfg_overrides: dict, log_queue: queue.Queue) -> None:
    import sys as _sys
    handler = _QueueHandler(log_queue)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    orig_stdout = _sys.stdout
    _sys.stdout = _StdoutToQueue(log_queue, orig_stdout)
    pl = logging.getLogger("pipeline.thread")
    pl.info("=== Pipeline thread started ===")
    pl.info("Config: %s", cfg_overrides)
    try:
        from finrl_pipeline import run_pipeline_and_save_report
        report_path = run_pipeline_and_save_report(cfg_overrides)
        pl.info("=== Pipeline complete. Report: %s ===", report_path)
        log_queue.put_nowait(f"__REPORT__:{report_path}")
    except Exception as exc:
        pl.error("Pipeline failed: %s", exc, exc_info=True)
        log_queue.put_nowait(f"__ERROR__:{exc}")
    finally:
        _sys.stdout = orig_stdout
        root.removeHandler(handler)


def _predict_only_thread_target(cfg_overrides: dict, log_queue: queue.Queue) -> None:
    import sys as _sys
    handler = _QueueHandler(log_queue)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    orig_stdout = _sys.stdout
    _sys.stdout = _StdoutToQueue(log_queue, orig_stdout)
    pl = logging.getLogger("predict.thread")
    pl.info("=== Predict-only thread started ===")
    try:
        from finrl_pipeline import run_predict_only, MODELS_DIR
        from repository import StockRepository
        repo = StockRepository()
        rows = repo.get_latest_selected_stocks()
        symbols = [r["ticker"] for r in rows] if rows else None
        if not symbols:
            pl.warning("No selected stocks in DB — run full pipeline first.")
            log_queue.put_nowait("__ERROR__:No selected stocks in DB. Run the pipeline first.")
            return
        source = cfg_overrides.get("source", "AISTOCK_DB")
        pl.info("Predicting %d stocks from selected_stocks table", len(symbols))
        pred_df = run_predict_only(symbols=symbols, source=source)

        # Compute actual returns from prediction date to today
        import pandas as _pd
        from datetime import date as _date
        actual_returns: list = []
        for _, row in pred_df.iterrows():
            ticker = row["ticker"]
            dd = _pd.to_datetime(row["datadate"]).date()
            stock = repo.find_stock(str(ticker))
            if stock is None:
                actual_returns.append(None)
                continue
            prices = repo.get_prices(stock.id, dd, _date.today())
            if prices.empty or len(prices) < 2:
                actual_returns.append(None)
                continue
            start_price = float(prices["adj_close"].iloc[0])
            end_price = float(prices["adj_close"].iloc[-1])
            actual_returns.append(
                float((end_price / start_price) - 1) if start_price > 0 else None
            )
        pred_df["actual_return"] = actual_returns
        n_actual = sum(1 for a in actual_returns if a is not None)
        pl.info("Computed actual returns for %d/%d stocks", n_actual, len(pred_df))

        # Persist to DB
        try:
            records = pred_df.assign(
                model_file=str(MODELS_DIR),
                ml_score=lambda d: d["predicted_return"],
            ).to_dict("records")
            n = repo.save_predict_only_results(records)
            pl.info("Saved %d predictions to selected_stocks table", n)
        except Exception as exc:
            pl.warning("Failed to save predictions to DB: %s", exc)

        log_queue.put_nowait(f"__PREDICT_DF__:{pred_df.to_json(orient='records')}")
        log_queue.put_nowait(f"__REPORT__:{MODELS_DIR}")
        pl.info("=== Predict-only complete. %d predictions ===", len(pred_df))
    except Exception as exc:
        pl.error("Predict-only failed: %s", exc, exc_info=True)
        log_queue.put_nowait(f"__ERROR__:{exc}")
    finally:
        _sys.stdout = orig_stdout
        root.removeHandler(handler)


def show_ml_pipeline() -> None:
    import time
    import yaml
    from pathlib import Path

    st.header("ML Pipeline")

    with st.expander("How stocks are selected", expanded=False):
        st.markdown("""
**4-stage pipeline:**

1. **Universe** — Active stocks from the selected data source (AISTOCK_DB = local MySQL).
2. **Fundamentals** — 52 quarterly factors: valuation, profitability, liquidity, leverage, momentum.
3. **ML competition** — 7 models per sector bucket (RF, XGB, LGBM, HGB, ET, Ridge, Stacking).
   Best chosen by validation MSE; score = inverse-MSE weighted ensemble.
4. **Selection** — Stocks ranked by predicted return. Top quantile selected; weights by Weight Method.
""")

    # Load config.yaml for defaults
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    try:
        with open(cfg_path) as fh:
            yaml_cfg = yaml.safe_load(fh) or {}
    except Exception:
        yaml_cfg = {}
    data_cfg = yaml_cfg.get("data", {})
    pipe_cfg = yaml_cfg.get("pipeline", {})
    strat_cfg = yaml_cfg.get("strategy", {})
    backt_cfg = yaml_cfg.get("backtest", {})

    with st.form("ml_pipeline_form"):
        st.subheader("Configuration")
        c1, c2, c3 = st.columns(3)
        _src_opts = ["AISTOCK_DB", "FMP", "WRDS", "YAHOO"]
        _src_val = data_cfg.get("preferred_source", "AISTOCK_DB")
        with c1:
            preferred_source = st.selectbox(
                "Data Source", _src_opts,
                index=_src_opts.index(_src_val) if _src_val in _src_opts else 0,
            )
        with c2:
            start_date = st.text_input("Start Date", value=str(pipe_cfg.get("start_date", "2020-01-01")))
        with c3:
            end_date = st.text_input("End Date", value=str(pipe_cfg.get("end_date", "2025-12-31")))

        c4, c5, c6 = st.columns(3)
        with c4:
            top_quantile = st.slider("Top Quantile", 0.0, 1.0, float(strat_cfg.get("top_quantile", 0.75)), 0.05)
        with c5:
            test_quarters = st.number_input("Test Quarters", min_value=1, max_value=40,
                                            value=int(strat_cfg.get("test_quarters", 20)))
        with c6:
            _pm_opts = ["regression", "classification", "ensemble", "rolling", "single"]
            _pm_val = strat_cfg.get("prediction_mode", "regression")
            prediction_mode = st.selectbox("Prediction Mode", _pm_opts,
                                           index=_pm_opts.index(_pm_val) if _pm_val in _pm_opts else 0)

        c7, c8, c9 = st.columns(3)
        with c7:
            _wm_opts = ["equal", "inverse_volatility", "ml_score"]
            weight_method = st.selectbox("Weight Method", _wm_opts,
                                         index=_wm_opts.index(strat_cfg.get("weight_method", "equal")))
        with c8:
            rebalance_freq = st.selectbox("Rebalance Freq", ["Q", "M", "A"],
                                          index=["Q", "M", "A"].index(backt_cfg.get("rebalance_freq", "Q")))
        with c9:
            initial_capital = st.number_input("Initial Capital ($)", min_value=10_000, step=10_000,
                                              value=int(backt_cfg.get("initial_capital", 1_000_000)))

        _default_bms = backt_cfg.get("benchmarks", ["SPY", "QQQ"])
        benchmarks = st.multiselect(
            "Benchmarks",
            options=["SPY", "QQQ", "DIA", "IWM", "VTI"],
            default=_default_bms,
            help="Benchmark tickers to compare portfolio against",
        )

        run_clicked = st.form_submit_button("Run Pipeline")
        predict_only_clicked = st.form_submit_button("Predict Only")

    status = st.session_state.ml_status
    elapsed = time.time() - st.session_state.ml_start_time if st.session_state.ml_start_time > 0 else 0.0
    color = {"Idle": "gray", "Running": "blue", "Complete": "green", "Error": "red"}.get(status, "gray")
    st.markdown(f"**Status:** :{color}[{status}]  |  Elapsed: {elapsed:.0f}s")

    if run_clicked and status != "Running":
        st.session_state.ml_log_lines = []
        st.session_state.ml_error = None
        st.session_state.ml_report_path = None
        st.session_state.ml_log_queue = queue.Queue()
        st.session_state.ml_status = "Running"
        st.session_state.ml_start_time = time.time()
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
        import threading as _threading
        _threading.Thread(target=_pipeline_thread_target,
                          args=(cfg, st.session_state.ml_log_queue), daemon=True).start()
        st.rerun()

    if predict_only_clicked and status != "Running":
        st.session_state.ml_log_lines = []
        st.session_state.ml_error = None
        st.session_state.ml_report_path = None
        st.session_state.ml_predict_only_df = None
        st.session_state.ml_log_queue = queue.Queue()
        st.session_state.ml_status = "Running"
        st.session_state.ml_start_time = time.time()
        cfg = {
            "source": preferred_source,
        }
        import threading as _threading
        _threading.Thread(target=_predict_only_thread_target,
                          args=(cfg, st.session_state.ml_log_queue), daemon=True).start()
        st.rerun()

    while True:
        try:
            msg = st.session_state.ml_log_queue.get_nowait()
        except queue.Empty:
            break
        if isinstance(msg, str) and msg.startswith("__PREDICT_DF__:"):
            import json as _json
            st.session_state.ml_predict_only_df = _json.loads(msg[len("__PREDICT_DF__:"):])
        elif isinstance(msg, str) and msg.startswith("__REPORT__:"):
            st.session_state.ml_report_path = msg[len("__REPORT__:"):]
            st.session_state.ml_status = "Complete"
        elif isinstance(msg, str) and msg.startswith("__ERROR__:"):
            st.session_state.ml_error = msg[len("__ERROR__:"):]
            st.session_state.ml_status = "Error"
        else:
            st.session_state.ml_log_lines.append(str(msg))

    st.subheader("Log Output")
    if st.session_state.ml_log_lines:
        log_text = "\n".join(st.session_state.ml_log_lines[-200:])
    elif status == "Running":
        log_text = "Pipeline starting..."
    else:
        log_text = "No runs yet. Configure and click Run Pipeline."
    st.code(log_text, language=None)

    if status == "Running":
        import time as _time
        _time.sleep(1)
        st.rerun()

    if st.session_state.ml_status == "Error" and st.session_state.ml_error:
        st.error(f"Pipeline failed: {st.session_state.ml_error}")

    if st.session_state.ml_report_path:
        st.success(f"Complete. Report: `{st.session_state.ml_report_path}`")
        # Check if this is predict-only or full pipeline
        if st.session_state.get("ml_predict_only_df"):
            _show_predict_only_results(st.session_state.ml_predict_only_df)
        else:
            _show_ml_results()
            _show_ml_backtest()


@st.dialog("Stock Details", width="large")
def _stock_detail_dialog(symbol: str):
    """Dialog showing basic info, fundamentals, and technical indicators for a stock."""
    from repository import StockRepository

    repo = StockRepository()
    stock = repo.find_stock(symbol)
    if not stock:
        st.warning(f"Stock **{symbol}** not found in database.")
        return

    indicator = repo.get_indicator(stock.id)
    snapshot = repo.get_snapshot(stock.id)

    def _abbr(v):
        """Abbreviate large numbers: 1.5B, 300M, 50K."""
        if v is None:
            return "N/A"
        v = float(v)
        sign = "-" if v < 0 else ""
        v = abs(v)
        if v >= 1e12:
            return f"{sign}${v/1e12:.2f}T"
        if v >= 1e9:
            return f"{sign}${v/1e9:.2f}B"
        if v >= 1e6:
            return f"{sign}${v/1e6:.0f}M"
        if v >= 1e3:
            return f"{sign}${v/1e3:.0f}K"
        return f"{sign}${v:,.0f}"

    # ── Header ──
    st.markdown(f"## {symbol} — {stock.name or 'N/A'}")
    st.caption(f"Exchange: {stock.exchange or 'N/A'}  |  Sector: {stock.sector or 'N/A'}  |  Industry: {stock.industry or 'N/A'}")

    st.divider()

    t1, t2, t3 = st.tabs(["Company", "Fundamentals", "Technical"])

    # ── Tab 1: Company Info ──
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**General**")
            rows = [
                ("Country", stock.country),
                ("Currency", stock.currency),
                ("CIK", stock.cik),
                ("Fiscal Year End", stock.fiscal_year_end),
            ]
            for label, val in rows:
                st.caption(f"{label}: {val or 'N/A'}")

        with c2:
            st.markdown("**Shares**")
            shares_rows = [
                ("Outstanding", f"{stock.shares_outstanding:,}" if stock.shares_outstanding else None),
                ("Float", f"{stock.shares_float:,}" if stock.shares_float else None),
                ("Insiders %", f"{indicator.pct_insiders:.2f}%" if indicator and indicator.pct_insiders else None),
                ("Institutions %", f"{indicator.pct_institutions:.2f}%" if indicator and indicator.pct_institutions else None),
            ]
            for label, val in shares_rows:
                st.caption(f"{label}: {val or 'N/A'}")

        if stock.description:
            with st.expander("Description", expanded=False):
                st.markdown(stock.description or "")

    # ── Tab 2: Fundamentals ──
    with t2:
        if indicator is None:
            st.info("No fundamental data available.")
        else:
            _fmt_num = lambda v, decimals=2: f"{v:,.{decimals}f}" if v is not None else "N/A"
            _fmt_pct = lambda v: f"{v:.2f}%" if v is not None else "N/A"
            # ── number formatting inline ──

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Valuation**")
                val_fields = [
                    ("Market Cap", _abbr(indicator.market_cap) if indicator.market_cap else "N/A"),
                    ("PE Ratio", _fmt_num(indicator.pe_ratio)),
                    ("Forward PE", _fmt_num(indicator.forward_pe)),
                    ("PEG Ratio", _fmt_num(indicator.peg_ratio)),
                    ("Price/Book", _fmt_num(indicator.price_to_book)),
                    ("Price/Sales", _fmt_num(indicator.price_to_sales_ttm)),
                    ("EV/EBITDA", _fmt_num(indicator.ev_to_ebitda)),
                    ("Dividend Yield", _fmt_pct(indicator.dividend_yield)),
                ]
                for label, val in val_fields:
                    st.caption(f"{label}: {val}")

                st.markdown("**Profitability**")
                prof_fields = [
                    ("EPS", _fmt_num(indicator.eps)),
                    ("ROE", _fmt_pct(indicator.roe_ttm)),
                    ("ROA", _fmt_pct(indicator.roa_ttm)),
                    ("Profit Margin", _fmt_pct(indicator.profit_margin)),
                    ("Operating Margin", _fmt_pct(indicator.operating_margin_ttm)),
                ]
                for label, val in prof_fields:
                    st.caption(f"{label}: {val}")

            with c2:
                st.markdown("**Financials**")
                fin_fields = [
                    ("Revenue (TTM)", _abbr(indicator.revenue_ttm) if indicator.revenue_ttm else "N/A"),
                    ("Gross Profit (TTM)", _abbr(indicator.gross_profit_ttm) if indicator.gross_profit_ttm else "N/A"),
                    ("EBITDA", _abbr(indicator.ebitda) if indicator.ebitda else "N/A"),
                    ("Book Value/Share", _fmt_num(indicator.book_value)),
                    ("Rev/Share (TTM)", _fmt_num(indicator.revenue_per_share_ttm)),
                    ("DPS", _fmt_num(indicator.dividend_per_share)),
                ]
                for label, val in fin_fields:
                    st.caption(f"{label}: {val}")

                st.markdown("**Growth**")
                growth_fields = [
                    ("Earnings Growth YoY", _fmt_pct(indicator.qtr_earnings_growth_yoy)),
                    ("Revenue Growth YoY", _fmt_pct(indicator.qtr_revenue_growth_yoy)),
                ]
                for label, val in growth_fields:
                    st.caption(f"{label}: {val}")

                st.markdown("**Analyst Consensus**")
                if indicator.analyst_target_price:
                    buys = (indicator.analyst_strong_buy or 0) + (indicator.analyst_buy or 0)
                    total = buys + (indicator.analyst_hold or 0) + (indicator.analyst_sell or 0) + (indicator.analyst_strong_sell or 0)
                    consensus = (
                        f"{buys} Buy / "
                        f"{indicator.analyst_hold or 0} Hold / "
                        f"{(indicator.analyst_sell or 0) + (indicator.analyst_strong_sell or 0)} Sell"
                        if total > 0 else "N/A"
                    )
                    st.caption(f"Target Price: ${_fmt_num(indicator.analyst_target_price)}")
                    st.caption(f"Consensus: {consensus}")
                else:
                    st.caption("No analyst data")

    # ── Tab 3: Technical Indicators ──
    with t3:
        if snapshot is None:
            st.info("No snapshot data available. Run the daily pipeline first.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Price**")
                price_fields = [
                    ("Latest Close", _fmt_num(snapshot.close) if snapshot.close else "N/A"),
                    ("Latest Date", str(snapshot.latest_date) if snapshot.latest_date else "N/A"),
                    ("Volume", f"{snapshot.volume:,}" if snapshot.volume else "N/A"),
                ]
                for label, val in price_fields:
                    st.caption(f"{label}: {val}")

                st.markdown("**Momentum**")
                mom_fields = [
                    ("RSI (14)", _fmt_num(snapshot.rsi_14)),
                    ("MACD", _fmt_num(snapshot.macd, 4) if snapshot.macd else "N/A"),
                    ("SMA 20", _fmt_num(snapshot.sma_20)),
                    ("SMA 50", _fmt_num(snapshot.sma_50)),
                ]
                for label, val in mom_fields:
                    st.caption(f"{label}: {val}")

            with c2:
                st.markdown("**Risk & Valuation**")
                risk_fields = [
                    ("Beta", _fmt_num(snapshot.beta)),
                    ("PE Ratio", _fmt_num(snapshot.pe_ratio)),
                    ("ROE", _fmt_pct(snapshot.roe_ttm) if snapshot.roe_ttm else "N/A"),
                    ("Dividend Yield", _fmt_pct(snapshot.dividend_yield) if snapshot.dividend_yield else "N/A"),
                ]
                for label, val in risk_fields:
                    st.caption(f"{label}: {val}")

                if indicator:
                    st.markdown("**52-Week Range**")
                    st.caption(f"High: ${_fmt_num(indicator.week_52_high) if indicator.week_52_high else 'N/A'}")
                    st.caption(f"Low: ${_fmt_num(indicator.week_52_low) if indicator.week_52_low else 'N/A'}")
                    st.caption(f"MA 50: ${_fmt_num(indicator.ma_50_day) if indicator.ma_50_day else 'N/A'}")
                    st.caption(f"MA 200: ${_fmt_num(indicator.ma_200_day) if indicator.ma_200_day else 'N/A'}")


def _show_ml_results() -> None:
    import glob as _glob
    from pathlib import Path
    import plotly.express as px

    try:
        from finrl_pipeline import DATA_DIR
    except ImportError:
        return

    st.header("Results")
    weights_path = None
    for candidate in ["ml_weights_sector.csv", "ml_weights_today.csv"]:
        p = DATA_DIR / candidate
        if p.exists():
            weights_path = p
            break
    if weights_path is None:
        st.info("No weights file. Run the pipeline first.")
        return

    try:
        wdf = pd.read_csv(weights_path)
        wdf.columns = [c.strip().lower() for c in wdf.columns]
    except Exception as exc:
        st.warning(f"Cannot read weights: {exc}")
        return

    fund_path = DATA_DIR / "fundamentals.csv"
    s_col = None
    if fund_path.exists():
        try:
            fdf = pd.read_csv(fund_path)
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
            name_map: dict = {}
            for sym in wdf[ticker_col].dropna().unique():
                stock = _repo.find_stock(str(sym))
                name_map[sym] = stock.name if stock else ""
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

    st.subheader("Selected Stocks")
    tdf = wdf[display_cols].copy()
    if "weight" in tdf.columns:
        tdf["weight"] = tdf["weight"].apply(lambda x: f"{float(x):.4f}" if pd.notna(x) else "")
    event = st.dataframe(tdf, selection_mode="single-row", on_select="rerun", width='stretch', key="ml_selected_stocks")
    if ticker_display and event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_ticker = str(tdf.iloc[selected_idx][ticker_display])
        _stock_detail_dialog(selected_ticker)

    s_col_f = next((c for c in ["sector", "gsector"] if c in wdf.columns), None)
    if s_col_f:
        try:
            sd = wdf.copy()
            sd["weight"] = pd.to_numeric(sd["weight"], errors="coerce").fillna(0)
            count_col = next((c for c in ["tic", "ticker", "gvkey"] if c in sd.columns), "weight")
            agg = (sd.groupby(s_col_f)
                   .agg(stock_count=(count_col, "count"), total_weight=("weight", "sum"))
                   .reset_index().sort_values("total_weight", ascending=False))
            ca, cb = st.columns(2)
            with ca:
                st.plotly_chart(px.bar(agg, x=s_col_f, y="stock_count", title="Stock Count per Sector")
                                .update_layout(xaxis_tickangle=-45), width='stretch')
            with cb:
                st.plotly_chart(px.bar(agg, x=s_col_f, y="total_weight", title="Total Weight per Sector")
                                .update_layout(xaxis_tickangle=-45), width='stretch')
        except Exception:
            pass

    fi_files = sorted(_glob.glob(str(DATA_DIR / "sp500_ml_feature_importance_*.csv")),
                      key=lambda f: Path(f).stat().st_mtime, reverse=True)
    if fi_files:
        try:
            fi = pd.read_csv(fi_files[0])
            fi.columns = [c.strip().lower() for c in fi.columns]
            fc = next((c for c in fi.columns if c in ("feature", "feature_name")), fi.columns[0])
            ic = next((c for c in fi.columns if c in ("importance", "importance_score")),
                      fi.columns[1] if len(fi.columns) > 1 else fi.columns[0])
            fi_p = fi[[fc, ic]].copy()
            fi_p[ic] = pd.to_numeric(fi_p[ic], errors="coerce").fillna(0)
            fi_p = fi_p.sort_values(ic, ascending=False).head(20)
            st.subheader("Feature Importance")
            st.plotly_chart(px.bar(fi_p, x=fc, y=ic, title="Top 20 Feature Importance")
                            .update_layout(xaxis_tickangle=-45), width='stretch')
        except Exception:
            pass


def _show_ml_backtest() -> None:
    import json
    import numpy as np
    import plotly.express as px
    from pathlib import Path

    try:
        from finrl_pipeline import DATA_DIR
    except ImportError:
        return

    bt_files = sorted(DATA_DIR.glob("backtest_result_*.json"), reverse=True)
    if not bt_files:
        st.info("No backtest results. Run the pipeline to generate one.")
        return

    try:
        with open(bt_files[0]) as f:
            bt = json.load(f)
    except Exception:
        st.warning("Could not read backtest results.")
        return

    if "portfolio_values" not in bt or "metrics" not in bt:
        st.warning("Backtest result is incomplete. Re-run the pipeline.")
        return

    st.header("Backtest Results")
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
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

    pv = bt["portfolio_values"]
    if pv:
        import plotly.graph_objects as go

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
        st.plotly_chart(fig, width='stretch')

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
        st.plotly_chart(fig_dd, width='stretch')


# ── FinRL pages (reimplemented, no external import) ───────────────────────────

def display_quick_stats(repo) -> None:
    st.subheader("Quick Stats")
    try:
        summary = repo.count_summary()
        c1, c2 = st.columns(2)
        c1.metric("Total", summary.get("total", "—"))
        c2.metric("Active", summary.get("active", "—"))
    except Exception as exc:
        st.error(f"Could not load stats: {exc}")


def _show_predict_only_results(pred_data: list[dict]) -> None:
    import pandas as _pd
    import plotly.express as _px

    st.header("Predict-Only Results")
    df = _pd.DataFrame(pred_data)
    if df.empty:
        st.info("No predictions.")
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

    st.subheader(f"Top Stocks by Predicted Return ({len(df)} stocks)")
    st.dataframe(display, width='stretch')

    if len(df) > 5:
        top_n = df.head(20)
        fig = _px.bar(top_n, x="ticker", y="predicted_return",
                      title="Top 20 Predicted Returns",
                      labels={"ticker": "Ticker", "predicted_return": "Predicted Return"})
        fig.update_traces(marker_color="green",
                          marker=dict(line=dict(color="darkgreen", width=1)))
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, width='stretch')


def show_overview(repo) -> None:
    st.header("Platform Overview")
    try:
        summary = repo.count_summary()
    except Exception as exc:
        st.error(f"Failed to load data: {exc}")
        return

    c1, c2 = st.columns(2)
    c1.metric("Total Stocks", summary.get("total", "—"))
    c2.metric("Active Stocks", summary.get("active", "—"))


def show_live_trading() -> None:
    st.header("Live Trading")
    try:
        from trading.alpaca_manager import create_alpaca_account_from_env
        account = create_alpaca_account_from_env()
        st.success(f"Connected to Alpaca account (Paper: {account.is_paper})")
    except Exception as exc:
        st.error(f"Trading not configured: {exc}")
        st.info("Set APCA_API_KEY / APCA_API_SECRET in environment variables.")
        return

    tab1, tab2, tab3 = st.tabs(["Portfolio", "Order Management", "Strategy Execution"])
    with tab1:
        st.subheader("Current Portfolio")
        if st.button("Refresh Portfolio"):
            with st.spinner("Loading..."):
                try:
                    from trading.alpaca_manager import AlpacaManager
                    manager = AlpacaManager([account])
                    positions = manager.get_positions()
                    if positions:
                        st.dataframe(
                            pd.DataFrame(positions)[
                                ["symbol", "qty", "avg_entry_price", "market_value", "unrealized_pl"]
                            ],
                            width='stretch',
                        )
                    else:
                        st.info("No open positions")
                except Exception as exc:
                    st.error(f"Failed to load portfolio: {exc}")

    with tab2:
        st.subheader("Order Management")
        with st.form("place_order"):
            c1, c2, c3 = st.columns(3)
            with c1:
                symbol = st.text_input("Symbol", "AAPL").upper()
            with c2:
                quantity = st.number_input("Quantity", min_value=1, value=10)
            with c3:
                side = st.selectbox("Side", ["buy", "sell"])
            order_type = st.selectbox("Order Type", ["market", "limit"])
            limit_price = st.number_input("Limit Price", min_value=0.01, step=0.01) if order_type == "limit" else None
            if st.form_submit_button("Place Order"):
                try:
                    from trading.alpaca_manager import AlpacaManager, OrderRequest
                    manager = AlpacaManager([account])
                    order = OrderRequest(symbol=symbol, quantity=quantity, side=side,
                                        order_type=order_type, limit_price=limit_price)
                    response = manager.place_order(order)
                    st.success(f"Order placed: {response.order_id}")
                except Exception as exc:
                    st.error(f"Failed to place order: {exc}")

    with tab3:
        st.subheader("Strategy Execution")
        if st.button("Execute Sample Strategy"):
            with st.spinner("Executing..."):
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
                    st.success(f"Strategy executed: {len(result.orders_placed)} orders placed")
                except Exception as exc:
                    st.error(f"Strategy execution failed: {exc}")


def show_portfolio_analysis() -> None:
    st.header("Portfolio Analysis")
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    portfolio_values = 1_000_000 + np.cumsum(np.random.normal(2000, 8000, 100))

    tab1, tab2, tab3, tab4 = st.tabs(["Performance", "Risk Analysis", "Attribution", "Benchmarking"])
    with tab1:
        st.subheader("Performance Analysis")
        st.plotly_chart(px.line(x=dates, y=portfolio_values, title="Portfolio Performance"),
                        width='stretch')
        returns = pd.Series(portfolio_values).pct_change().dropna()
        ann_ret = returns.mean() * 252
        vol = returns.std() * np.sqrt(252)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Return", f"{(portfolio_values[-1]/portfolio_values[0]-1):.2%}")
        c2.metric("Annual Return", f"{ann_ret:.2%}")
        c3.metric("Volatility", f"{vol:.2%}")
        c4.metric("Sharpe Ratio", f"{ann_ret/vol:.2f}" if vol > 0 else "—")

    with tab2:
        st.subheader("Risk Analysis")
        returns_s = pd.Series(portfolio_values).pct_change().dropna()
        cum = (1 + returns_s).cumprod()
        dd = (cum - cum.expanding().max()) / cum.expanding().max()
        fig = px.line(x=dates[1:], y=dd, title="Portfolio Drawdown")
        fig.update_layout(yaxis_tickformat=".2%")
        st.plotly_chart(fig, width='stretch')
        var_95 = float(np.percentile(returns_s, 5))
        c1, c2, c3 = st.columns(3)
        c1.metric("Max Drawdown", f"{dd.min():.2%}")
        c2.metric("VaR (95%)", f"{var_95:.2%}")
        c3.metric("CVaR (95%)", f"{float(returns_s[returns_s <= var_95].mean()):.2%}")

    with tab3:
        st.subheader("Attribution Analysis")
        attr = pd.DataFrame({
            "Asset": ["AAPL", "MSFT", "GOOGL", "Bonds", "Cash"],
            "Weight": [0.30, 0.25, 0.20, 0.15, 0.10],
            "Return": [0.15, 0.12, 0.18, 0.03, 0.02],
            "Contribution": [0.045, 0.030, 0.036, 0.0045, 0.002],
        })
        st.plotly_chart(px.bar(attr, x="Asset", y="Contribution", title="Return Attribution"),
                        width='stretch')
        st.dataframe(attr, width='stretch')

    with tab4:
        st.subheader("Benchmarking")
        bench = pd.DataFrame({
            "Date": dates,
            "Portfolio": portfolio_values,
            "SPY": 1_000_000 + np.cumsum(np.random.normal(1500, 6000, 100)),
            "QQQ": 1_000_000 + np.cumsum(np.random.normal(1800, 7000, 100)),
        })
        st.plotly_chart(px.line(bench, x="Date", y=["Portfolio", "SPY", "QQQ"],
                                title="Portfolio vs Benchmarks"), width='stretch')


def show_settings() -> None:
    st.header("Settings")
    tab1, tab2, tab3 = st.tabs(["General", "Trading", "Data"])

    with tab1:
        st.subheader("General Settings")
        log_level = st.selectbox("Logging Level", ["DEBUG", "INFO", "WARNING", "ERROR"])
        if st.button("Apply Logging Level"):
            logging.getLogger().setLevel(getattr(logging, log_level))
            st.success(f"Logging level set to {log_level}")

    with tab2:
        st.subheader("Trading Settings")
        st.number_input("Max Order Value ($)", value=100_000, step=10_000)
        st.slider("Max Portfolio Turnover (%)", 0.0, 1.0, 0.5, 0.05)
        if st.button("Save Trading Settings"):
            st.success("Trading settings saved")
        st.subheader("API Configuration")
        st.text_input("Alpaca API Key", type="password")
        st.text_input("Alpaca API Secret", type="password")
        st.checkbox("Use Paper Trading", value=True)
        if st.button("Save API Settings"):
            st.success("API settings saved")

    with tab3:
        st.subheader("Data Settings")
        st.text_input("Data Directory", value="./data")
        st.text_input("Cache Directory", value="./data/cache")
        if st.button("Save Data Settings"):
            st.success("Data settings saved")
        st.subheader("Data Sources")
        st.checkbox("Enable WRDS", value=True)
        st.checkbox("Enable Alpha Vantage", value=False)
        st.checkbox("Enable AIStock DB", value=True)
        if st.button("Save Data Source Settings"):
            st.success("Data source settings saved")


def show_strategy_backtesting() -> None:
    """Read real backtest JSON files from DATA_DIR and display comparison."""
    import json
    import numpy as np
    import plotly.express as px

    st.header("Strategy Backtesting")

    try:
        from finrl_pipeline import DATA_DIR
    except ImportError:
        st.info("finrl_pipeline module not available.")
        return

    bt_files = sorted(DATA_DIR.glob("backtest_result_*.json"), reverse=True)
    if not bt_files:
        st.info("No backtest result files found. Run the ML Pipeline to generate results.")
        return

    file_names = [f.name for f in bt_files]
    selected_name = st.selectbox("Select Backtest Result", file_names)
    selected_path = DATA_DIR / selected_name

    try:
        with open(selected_path) as f:
            bt = json.load(f)
    except Exception:
        st.warning(f"Could not load {selected_name}.")
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
        st.subheader("Performance Metrics")
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

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
        st.subheader("Cumulative Return")
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("No portfolio value data in this result.")


def show_paper_trading() -> None:
    """Paper trading: dry-run plan + confirmation gate before order submission."""
    import time
    from pathlib import Path

    st.header("Paper Trading")

    if "trading_dry_run_plan" not in st.session_state:
        st.session_state.trading_dry_run_plan = None

    try:
        from trading.alpaca_manager import create_alpaca_account_from_env, AlpacaManager
        account = create_alpaca_account_from_env()
        manager = AlpacaManager([account])
    except Exception:
        st.warning("Paper trading not configured. Set APCA_API_KEY / APCA_API_SECRET and restart.")
        return

    try:
        from finrl_pipeline import DATA_DIR
    except ImportError:
        st.error("finrl_pipeline not available.")
        return

    weights_path = None
    for candidate in ["ml_weights_sector.csv", "ml_weights_today.csv"]:
        p = DATA_DIR / candidate
        if p.exists():
            weights_path = p
            break

    if weights_path is None:
        st.info("No weights file. Run the ML Pipeline first.")
        return

    mtime = weights_path.stat().st_mtime
    age_days = (time.time() - mtime) / 86400
    st.caption(f"Weights: {weights_path.name} (modified: {pd.Timestamp(mtime, unit='s').strftime('%Y-%m-%d %H:%M')})")
    if age_days > 14:
        st.warning(f"Weights are {age_days:.0f} days old. Consider re-running the pipeline.")

    try:
        wdf = pd.read_csv(weights_path)
        wdf["date"] = pd.to_datetime(wdf["date"]).dt.date
        latest = wdf[wdf["date"] == wdf["date"].max()]
        target_weights = {str(r["gvkey"]): float(r["weight"]) for _, r in latest.iterrows()}
    except Exception as exc:
        st.error(f"Cannot read weights: {exc}")
        return

    if not target_weights:
        st.info("No target weights in file.")
        return

    if st.button("Refresh Dry-Run Plan") or st.session_state.trading_dry_run_plan is None:
        with st.spinner("Generating dry-run plan..."):
            try:
                st.session_state.trading_dry_run_plan = manager.execute_portfolio_rebalance(
                    target_weights, dry_run=True)
            except Exception as exc:
                st.error(f"Dry-run failed: {exc}")
                return

    plan = st.session_state.trading_dry_run_plan
    st.subheader("Dry-Run Rebalance Plan")
    st.caption(f"Market open: {'Yes' if plan.get('market_open') else 'No'} | "
               f"TIF: {plan.get('used_time_in_force', 'day')}")

    sells = plan.get("orders_plan", {}).get("sell", [])
    buys = plan.get("orders_plan", {}).get("buy", [])
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Planned Sells**")
        st.dataframe(pd.DataFrame(sells), width='stretch', hide_index=True) if sells else st.info("No sells")
    with c2:
        st.markdown("**Planned Buys**")
        st.dataframe(pd.DataFrame(buys), width='stretch', hide_index=True) if buys else st.info("No buys")

    st.subheader("Submit Orders")
    with st.form("paper_trading_submit"):
        confirmed = st.checkbox("I confirm I want to submit these orders to Alpaca Paper Trading.")
        if st.form_submit_button("Submit Orders", disabled=not confirmed) and confirmed:
            with st.spinner("Submitting..."):
                try:
                    result = manager.execute_portfolio_rebalance(target_weights, dry_run=False)
                    n = result.get("orders_placed", 0)
                    if n > 0:
                        st.success(f"{n} orders submitted.")
                        st.session_state.trading_dry_run_plan = None
                    elif not result.get("market_open"):
                        st.info("Market closed. No orders placed.")
                    else:
                        st.info("Portfolio already at target weights.")
                except Exception as exc:
                    st.error(f"Submission failed: {exc}")


# ── Stock Data sub-pages ──────────────────────────────────────────────────────

def tab_lookup():
    st.markdown('<div class="tab-header">LOOKUP</div>', unsafe_allow_html=True)
    col_sidebar, col_main = st.columns([1, 3])

    with col_sidebar:
        symbol = st.text_input("Symbol", value="AAPL", max_chars=10).upper()
        start_date = st.date_input("Start date", value=date.today() - timedelta(days=365))
        end_date = st.date_input("End date", value=date.today())

        stock = repo.find_stock(symbol)
        if stock:
            status_color = "#16a34a" if stock.is_active else "#dc2626"
            status_label = "Active" if stock.is_active else "Inactive"
            st.markdown(f"""
            <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;padding:10px;font-size:12px;color:#334155;line-height:1.7;margin-top:8px;">
              <div style="color:#0284c7;font-weight:bold;font-size:14px;">{stock.name or symbol}</div>
              <div>{stock.exchange or '—'} · {stock.sector or '—'}</div>
              <div>{stock.industry or '—'}</div>
              <div style="margin-top:6px;color:{status_color};font-weight:600;">● {status_label}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("Symbol not found.")

    with col_main:
        if not stock:
            st.warning(f"No data for {symbol}. Run bootstrap first.")
            return

        ind = repo.get_indicator(stock.id)
        prices_df = repo.get_prices(stock.id, start_date, end_date)

        last_close = float(prices_df["close"].iloc[-1]) if not prices_df.empty else None
        prev_close = float(prices_df["close"].iloc[-2]) if len(prices_df) > 1 else None
        pct_change = ((last_close - prev_close) / prev_close * 100) if last_close and prev_close else None
        volume = int(prices_df["volume"].iloc[-1]) if not prices_df.empty else None

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            chg = f"▲ +{pct_change:.2f}%" if pct_change and pct_change >= 0 else (f"▼ {pct_change:.2f}%" if pct_change else "—")
            chg_color = "#16a34a" if pct_change and pct_change >= 0 else "#dc2626"
            st.markdown(f'<div class="metric-card"><div class="metric-label">CLOSE</div><div class="metric-value" style="color:#0284c7">${last_close:.2f}</div><div class="metric-sub" style="color:{chg_color}">{chg}</div></div>', unsafe_allow_html=True)
        with c2:
            pe = f"{float(ind.pe_ratio):.1f}" if ind and ind.pe_ratio else "—"
            st.markdown(f'<div class="metric-card"><div class="metric-label">PE RATIO</div><div class="metric-value" style="color:#d97706">{pe}</div><div class="metric-sub" style="color:#94a3b8">trailing</div></div>', unsafe_allow_html=True)
        with c3:
            mc = fmt_market_cap(ind.market_cap if ind else None)
            st.markdown(f'<div class="metric-card"><div class="metric-label">MKT CAP</div><div class="metric-value" style="color:#7c3aed">{mc}</div><div class="metric-sub" style="color:#94a3b8">USD</div></div>', unsafe_allow_html=True)
        with c4:
            vol_str = f"{volume/1_000_000:.1f}M" if volume and volume >= 1_000_000 else (f"{volume:,}" if volume else "—")
            st.markdown(f'<div class="metric-card"><div class="metric-label">VOLUME</div><div class="metric-value" style="color:#16a34a">{vol_str}</div><div class="metric-sub" style="color:#94a3b8">daily</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if prices_df.empty:
            st.info("No price data in selected range.")
            return

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.02)
        fig.add_trace(go.Candlestick(
            x=prices_df["date"], open=prices_df["open"], high=prices_df["high"],
            low=prices_df["low"], close=prices_df["close"],
            name="OHLC", increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=prices_df["date"], y=prices_df["adj_close"],
            name="Adj Close", line=dict(color="#2563eb", width=1, dash="dot"),
        ), row=1, col=1)
        fig.add_trace(go.Bar(
            x=prices_df["date"], y=prices_df["volume"],
            name="Volume", marker_color="#cbd5e1",
        ), row=2, col=1)
        fig.update_layout(
            xaxis_rangeslider_visible=False, height=480,
            plot_bgcolor="#f8fafc", paper_bgcolor="#ffffff",
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", y=1.05),
            font=dict(color="#334155"),
        )
        fig.update_xaxes(gridcolor="#f1f5f9")
        fig.update_yaxes(gridcolor="#f1f5f9")
        st.plotly_chart(fig, width='stretch')

        st.markdown("**Recent Prices**")
        display_df = prices_df.tail(20).sort_values("date", ascending=False).copy()
        display_df["date"] = display_df["date"].astype(str)
        st.dataframe(display_df, width='stretch', hide_index=True)


def tab_technical():
    st.markdown('<div class="tab-header">TECHNICAL ANALYSIS</div>', unsafe_allow_html=True)
    col_sidebar, col_main = st.columns([1, 3])

    with col_sidebar:
        symbol = st.text_input("Symbol", value="AAPL", key="ta_symbol", max_chars=10).upper()
        start_date = st.date_input("Start date", value=date.today() - timedelta(days=365), key="ta_start")
        end_date = st.date_input("End date", value=date.today(), key="ta_end")
        st.markdown("**Overlays**")
        show_sma20 = st.checkbox("SMA 20", value=True)
        show_sma50 = st.checkbox("SMA 50", value=True)
        show_sma200 = st.checkbox("SMA 200", value=False)
        show_ema = st.checkbox("EMA 12/26", value=True)
        show_bb = st.checkbox("Bollinger Bands", value=True)
        st.markdown("**Oscillators**")
        show_rsi = st.checkbox("RSI (14)", value=True)
        show_macd = st.checkbox("MACD", value=True)
        show_stoch = st.checkbox("Stochastic", value=False)
        show_atr = st.checkbox("ATR (14)", value=False)

    with col_main:
        stock = repo.find_stock(symbol)
        if not stock:
            st.warning(f"Symbol {symbol} not found.")
            return

        prices_df = repo.get_prices(stock.id, start_date, end_date)
        tech_df = repo.get_tech_indicators(stock.id, start_date, end_date)

        if prices_df.empty:
            st.info("No price data in selected range.")
            return

        oscil_count = sum([show_rsi, show_macd, show_stoch, show_atr])
        rows = 1 + oscil_count
        row_heights = [0.6] + [0.4 / oscil_count] * oscil_count if oscil_count else [1.0]
        fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, row_heights=row_heights, vertical_spacing=0.03)

        fig.add_trace(go.Candlestick(
            x=prices_df["date"], open=prices_df["open"], high=prices_df["high"],
            low=prices_df["low"], close=prices_df["close"],
            name="OHLC", increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
        ), row=1, col=1)

        if not tech_df.empty:
            if show_sma20 and "SMA_20" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["SMA_20"], name="SMA20", line=dict(color="#f59e0b", width=1)), row=1, col=1)
            if show_sma50 and "SMA_50" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["SMA_50"], name="SMA50", line=dict(color="#8b5cf6", width=1)), row=1, col=1)
            if show_sma200 and "SMA_200" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["SMA_200"], name="SMA200", line=dict(color="#ec4899", width=1)), row=1, col=1)
            if show_ema and "EMA_12" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["EMA_12"], name="EMA12", line=dict(color="#06b6d4", width=1, dash="dot")), row=1, col=1)
            if show_ema and "EMA_26" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["EMA_26"], name="EMA26", line=dict(color="#0ea5e9", width=1, dash="dot")), row=1, col=1)
            if show_bb and "BBU_20_2.0" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["BBU_20_2.0"], name="BB Upper", line=dict(color="#94a3b8", width=1, dash="dash")), row=1, col=1)
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["BBL_20_2.0"], name="BB Lower", line=dict(color="#94a3b8", width=1, dash="dash"), fill="tonexty", fillcolor="rgba(148,163,184,0.1)"), row=1, col=1)

            oscil_row = 2
            if show_rsi and "RSI_14" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["RSI_14"], name="RSI", line=dict(color="#2563eb")), row=oscil_row, col=1)
                fig.add_hline(y=70, line_dash="dash", line_color="#dc2626", row=oscil_row, col=1)
                fig.add_hline(y=30, line_dash="dash", line_color="#16a34a", row=oscil_row, col=1)
                oscil_row += 1
            if show_macd and "MACD_12_26_9" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["MACD_12_26_9"], name="MACD", line=dict(color="#2563eb")), row=oscil_row, col=1)
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df.get("MACDs_12_26_9"), name="Signal", line=dict(color="#f59e0b")), row=oscil_row, col=1)
                if "MACDh_12_26_9" in tech_df:
                    colors = ["#16a34a" if v >= 0 else "#dc2626" for v in tech_df["MACDh_12_26_9"].fillna(0)]
                    fig.add_trace(go.Bar(x=tech_df["date"], y=tech_df["MACDh_12_26_9"], name="Histogram", marker_color=colors), row=oscil_row, col=1)
                oscil_row += 1
            if show_stoch and "STOCHk_14_3_3" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["STOCHk_14_3_3"], name="%K", line=dict(color="#7c3aed")), row=oscil_row, col=1)
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df.get("STOCHd_14_3_3"), name="%D", line=dict(color="#db2777")), row=oscil_row, col=1)
                oscil_row += 1
            if show_atr and "ATRr_14" in tech_df:
                fig.add_trace(go.Scatter(x=tech_df["date"], y=tech_df["ATRr_14"], name="ATR", line=dict(color="#64748b")), row=oscil_row, col=1)

        fig.update_layout(
            xaxis_rangeslider_visible=False, height=600,
            plot_bgcolor="#f8fafc", paper_bgcolor="#ffffff",
            margin=dict(l=0, r=0, t=10, b=0),
            font=dict(color="#334155"),
        )
        fig.update_xaxes(gridcolor="#f1f5f9")
        fig.update_yaxes(gridcolor="#f1f5f9")
        st.plotly_chart(fig, width='stretch')


def tab_screener():
    st.markdown('<div class="tab-header">SCREENER</div>', unsafe_allow_html=True)

    with st.form("screener_form"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            min_mktcap = st.number_input("Min Market Cap ($B)", min_value=0.0, value=1.0, step=0.5)
            min_roe = st.number_input("Min ROE (%)", min_value=-100.0, value=0.0, step=5.0)
        with c2:
            min_pe = st.number_input("Min PE", min_value=0.0, value=0.0, step=1.0)
            max_pe = st.number_input("Max PE", min_value=0.0, value=100.0, step=5.0)
        with c3:
            min_rsi = st.number_input("Min RSI", min_value=0.0, value=0.0, step=5.0)
            max_rsi = st.number_input("Max RSI", min_value=0.0, value=100.0, step=5.0)
        with c4:
            max_beta = st.number_input("Max Beta", min_value=0.0, value=3.0, step=0.1)
            min_div_yield = st.number_input("Min Div Yield (%)", min_value=0.0, value=0.0, step=0.5)

        sectors = ["All"] + repo.get_sectors("stock_snapshots")
        c5, c6 = st.columns(2)
        with c5:
            sector = st.selectbox("Sector", sectors)
        with c6:
            exchange = st.selectbox("Exchange", ["Both", "NASDAQ", "NYSE"])

        submitted = st.form_submit_button("Run Screen", type="primary")

    if submitted:
        criteria = ScreenCriteria(
            min_market_cap=int(min_mktcap * 1_000_000_000),
            min_pe=min_pe, max_pe=max_pe,
            min_roe=min_roe / 100 if min_roe else None,
            min_rsi=min_rsi if min_rsi else None,
            max_rsi=max_rsi if max_rsi else None,
            max_beta=max_beta if max_beta else None,
            min_div_yield=min_div_yield / 100 if min_div_yield else None,
            sector=sector if sector != "All" else None,
            exchange=exchange if exchange != "Both" else None,
        )
        df = repo.screen_stocks(criteria)
        if df.empty:
            st.info("No results. Try widening filters.")
            return
        df["Market Cap"] = df["Market Cap"].apply(fmt_market_cap)
        df["ROE %"] = df["ROE %"].apply(nan_safe(lambda x: f"{float(x)*100:.1f}%"))
        df["Div Yield %"] = df["Div Yield %"].apply(nan_safe(lambda x: f"{float(x)*100:.2f}%"))
        for col in ["PE", "RSI", "Beta"]:
            df[col] = df[col].apply(nan_safe(lambda x: f"{float(x):.2f}"))
        st.caption(f"{len(df)} results")
        col_export, _ = st.columns([1, 5])
        with col_export:
            st.download_button("Export CSV", df.to_csv(index=False), "screen_results.csv", "text/csv")
        st.dataframe(df, width='stretch', hide_index=True)


def tab_manager():
    st.markdown('<div class="tab-header">STOCK MANAGER</div>', unsafe_allow_html=True)

    summary = repo.count_summary()
    sectors = ["All"] + repo.get_sectors("stocks")

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Listed", summary["total"])
    c2.metric("Active", summary["active"])
    c3.metric("Inactive", summary["inactive"])

    st.markdown("---")
    st.markdown("**Filter & Bulk Actions**")

    with st.form("manager_filter"):
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        with r1c1:
            f_exchange = st.selectbox("Exchange", ["Both", "NASDAQ", "NYSE"])
            f_sector = st.selectbox("Sector", sectors)
        with r1c2:
            f_min_mc = st.number_input("Min Mkt Cap ($B)", min_value=0.0, value=0.0, step=0.5)
            f_max_pe = st.number_input("Max PE", min_value=0.0, value=999.0, step=5.0)
        with r1c3:
            f_min_roe = st.number_input("Min ROE (%)", min_value=-200.0, value=-200.0, step=5.0)
            f_max_beta = st.number_input("Max Beta", min_value=0.0, value=10.0, step=0.5)
        with r1c4:
            f_status = st.selectbox("Status", ["All", "Active", "Inactive"])
        btn_apply = st.form_submit_button("Apply Filters", type="primary")

    if btn_apply or "manager_results" not in st.session_state:
        filters = StockFilters(
            exchange=f_exchange if f_exchange != "Both" else None,
            sector=f_sector if f_sector != "All" else None,
            min_market_cap=f_min_mc,
            max_pe=f_max_pe,
            min_roe=f_min_roe,
            max_beta=f_max_beta,
            status=f_status,
        )
        df = repo.list_stocks(filters)
        st.session_state["manager_results"] = df
        st.session_state["manager_ids"] = df["id"].tolist()

    df = st.session_state.get("manager_results", pd.DataFrame())
    ids = st.session_state.get("manager_ids", [])

    if not df.empty:
        st.caption(f"{len(df)} stocks match filters")
        col_act, col_deact, _ = st.columns([1, 1, 4])
        with col_act:
            if st.button("✅ Activate All Filtered"):
                repo.bulk_set_active(ids, True)
                st.success(f"Activated {len(ids)} stocks.")
                st.rerun()
        with col_deact:
            if st.button("❌ Deactivate All Filtered"):
                repo.bulk_set_active(ids, False)
                st.success(f"Deactivated {len(ids)} stocks.")
                st.rerun()
        df["Mkt Cap"] = df["Mkt Cap"].apply(fmt_market_cap)
        df["ROE %"] = df["ROE %"].apply(nan_safe(lambda x: f"{float(x)*100:.1f}%"))
        df["PE"] = df["PE"].apply(nan_safe(lambda x: f"{float(x):.1f}"))
        df["Beta"] = df["Beta"].apply(nan_safe(lambda x: f"{float(x):.2f}"))
        df["Active"] = df["Active"].apply(lambda x: "● Active" if x else "○ Inactive")
        st.dataframe(df.drop(columns=["id"]), width='stretch', hide_index=True)

def page_stock_data():
    st.header("Stock Data")
    t1, t2, t3, t4 = st.tabs([
        "Lookup", "Technical Analysis", "Screener", "Manager"
    ])
    with t1:
        tab_lookup()
    with t2:
        tab_technical()
    with t3:
        tab_screener()
    with t4:
        tab_manager()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    with st.sidebar:
        st.markdown('<h2 style="color:#1e293b;margin:0 0 4px">📈 AIStock</h2>', unsafe_allow_html=True)
        st.markdown('<p style="color:#64748b;font-size:12px;margin:0 0 16px">Trading Platform</p>', unsafe_allow_html=True)
        st.divider()

        page = st.selectbox(
            "Navigation",
            ["Overview", "Stock Data", "ML Pipeline", "Strategy Backtesting",
             "Live Trading", "Paper Trading", "Portfolio Analysis", "Settings",
             "Job History"],
            label_visibility="collapsed",
        )

        st.divider()
        display_quick_stats(repo)

    if page == "Overview":
        show_overview(repo)
    elif page == "Stock Data":
        page_stock_data()
    elif page == "ML Pipeline":
        show_ml_pipeline()
    elif page == "Strategy Backtesting":
        show_strategy_backtesting()
    elif page == "Live Trading":
        show_live_trading()
    elif page == "Paper Trading":
        show_paper_trading()
    elif page == "Portfolio Analysis":
        show_portfolio_analysis()
    elif page == "Settings":
        show_settings()
    elif page == "Job History":
        show_job_history(repo)


def show_job_history(repo: StockRepository) -> None:
    st.markdown('<p class="tab-header">JOB HISTORY</p>', unsafe_allow_html=True)
    st.title("Scheduled Job History")

    df = repo.get_job_runs(limit=200)
    if df.empty:
        st.info("No scheduled jobs have run yet.")
        return

    st.dataframe(
        df.drop(columns=["id"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Job Name": st.column_config.TextColumn(width="small"),
            "Start Time": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
            "End Time": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
            "Stocks Updated": st.column_config.NumberColumn(width="small"),
            "Status": st.column_config.TextColumn(width="small"),
            "Error": st.column_config.TextColumn(width="medium"),
        },
    )


if __name__ == "__main__":
    main()
