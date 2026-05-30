from __future__ import annotations

import logging
import os
import queue
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

import streamlit as st

from repository import StockRepository

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


# ── PageContext ───────────────────────────────────────────────────────────────

@dataclass
class PageContext:
    """Dependency injection container for page render functions."""
    st: Any  # streamlit module
    repo: StockRepository
    session_state: Any  # st.session_state
    pipeline_thread_target: Callable[..., None] = field(default=lambda *_: None)
    predict_only_thread_target: Callable[..., None] = field(default=lambda *_: None)


# ── ML Pipeline Thread Infrastructure ─────────────────────────────────────────

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
        from finrl_runner import run_pipeline_and_save_report
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
        from finrl_runner import run_predict_only, MODELS_DIR
        from repository import StockRepository
        _repo = StockRepository()
        rows = _repo.get_latest_selected_stocks()
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
        unique_symbols = pred_df["ticker"].dropna().unique().tolist()
        stock_map = _repo.find_stocks_batch(unique_symbols)
        for row in pred_df.itertuples():
            ticker = str(row.ticker).upper()
            dd = _pd.to_datetime(row.datadate).date()
            stock = stock_map.get(ticker)
            if stock is None:
                actual_returns.append(None)
                continue
            prices = _repo.get_prices(stock.id, dd, _date.today())
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
            n = _repo.save_predict_only_results(records)
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


# ── Sidebar helpers ──────────────────────────────────────────────────────────

def display_quick_stats(repo: StockRepository) -> None:
    st.subheader("Quick Stats")
    try:
        summary = repo.count_summary()
        c1, c2 = st.columns(2)
        c1.metric("Total", summary.get("total", "—"))
        c2.metric("Active", summary.get("active", "—"))
    except Exception as exc:
        st.error(f"Could not load stats: {exc}")


from ui.pages import (  # noqa: E402 — imports after sys.path setup
    render_job_history, render_live_trading, render_ml_pipeline,
    render_overview, render_paper_trading, render_portfolio,
    render_settings, render_stock_lookup, render_stock_manager,
    render_stock_screener, render_stock_technical, render_strategy_backtest,
)


def page_stock_data(ctx: PageContext) -> None:
    """Stock Data page: tab routing to individual stock sub-pages."""
    ctx.st.header("Stock Data")
    t1, t2, t3, t4 = ctx.st.tabs([
        "Lookup", "Technical Analysis", "Screener", "Manager"
    ])
    with t1:
        render_stock_lookup(ctx)
    with t2:
        render_stock_technical(ctx)
    with t3:
        render_stock_screener(ctx)
    with t4:
        render_stock_manager(ctx)


def _build_ctx() -> PageContext:
    return PageContext(
        st=st,
        repo=repo,
        session_state=st.session_state,
        pipeline_thread_target=_pipeline_thread_target,
        predict_only_thread_target=_predict_only_thread_target,
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
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

    ctx = _build_ctx()

    if page == "Overview":
        render_overview(ctx)
    elif page == "Stock Data":
        page_stock_data(ctx)
    elif page == "ML Pipeline":
        render_ml_pipeline(ctx)
    elif page == "Strategy Backtesting":
        render_strategy_backtest(ctx)
    elif page == "Live Trading":
        render_live_trading(ctx)
    elif page == "Paper Trading":
        render_paper_trading(ctx)
    elif page == "Portfolio Analysis":
        render_portfolio(ctx)
    elif page == "Settings":
        render_settings(ctx)
    elif page == "Job History":
        render_job_history(ctx)


if __name__ == "__main__":
    main()
