from __future__ import annotations

import logging
import os
import queue
import sys
import threading
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

# Pre-import AIStock config module before ANY FinRL imports can shadow it.
# database.py already imports config, but an explicit import here guarantees
# sys.modules['config'] = AIStock's config.py regardless of import order edge cases.
import config  # noqa: E402,F811

# Pipeline imports at module level
from database import get_session
from pipeline.base import PipelineStopped
from pipeline.config import ConfigLoader
from pipeline.data_update import DataUpdateStep
from pipeline.deep_evaluation import DeepEvaluationStep
from pipeline.fast_evaluation import FastEvaluationStep
from pipeline.logging_utils import attach_queue_logging, detach_queue_logging
from pipeline.orchestrator import FullPipeline
from pipeline.stock_selection import StockSelectionStep

_STEP_CLASSES: dict[str, type] = {
    "data_update": DataUpdateStep,
    "stock_selection": StockSelectionStep,
    "fast_evaluation": FastEvaluationStep,
    "deep_evaluation": DeepEvaluationStep,
}

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
MAX_LOG_LINES = 1000

# ── PageContext ───────────────────────────────────────────────────────────────

@dataclass
class PageContext:
    """Dependency injection container for page render functions."""
    st: Any  # streamlit module
    repo: StockRepository
    session_state: Any  # st.session_state
    full_pipeline_thread_target: Callable[..., None] = field(default=lambda *_: None)


def _full_pipeline_thread_target(
    cfg_overrides: dict,
    selected_steps: list[str],
    log_queue: queue.Queue,
    stop_event: threading.Event | None = None,
) -> None:
    """Run the OOP full pipeline in a background thread, streaming logs to the UI."""
    from pathlib import Path as _Path

    handler, orig_stdout = attach_queue_logging(log_queue)
    pl = logging.getLogger("pipeline.thread")
    pl.info("=== Full Pipeline thread started ===")
    pl.info("Steps: %s", selected_steps)
    if stop_event is not None and stop_event.is_set():
        pl.info("Stop requested before pipeline started — exiting.")
        log_queue.put_nowait("__STOP__:Cancelled before start")
        detach_queue_logging(handler, orig_stdout)
        return
    try:
        steps = [_STEP_CLASSES[name]() for name in selected_steps if name in _STEP_CLASSES]
        if not steps:
            pl.error("No valid steps selected.")
            log_queue.put_nowait("__ERROR__:No valid steps selected")
            return

        loader = ConfigLoader("config.yaml")
        cfg = loader.load()
        for key_path, value in cfg_overrides.items():
            cfg_part = cfg
            parts = key_path.split(".")
            for part in parts[:-1]:
                cfg_part = cfg_part.setdefault(part, {})
            cfg_part[parts[-1]] = value

        report_root = _Path("reports/full_pipeline")
        report_root.mkdir(parents=True, exist_ok=True)

        pipeline = FullPipeline(
            steps=steps,
            cfg=cfg,
            session_factory=get_session,
            report_root=report_root,
            logger=pl,
            stop_event=stop_event,
        )
        run_id = pipeline.run()
        loader.write_effective(report_root / str(run_id) / "effective_config.yaml")
        pl.info("=== Full Pipeline complete. Run ID: %d ===", run_id)
        log_queue.put_nowait(f"__REPORT__:{report_root / str(run_id)}")
    except PipelineStopped:
        pl.info("=== Pipeline stopped by user ===")
        log_queue.put_nowait("__STOP__:Stopped by user")
    except Exception as exc:
        pl.error("Full Pipeline failed: %s", exc, exc_info=True)
        log_queue.put_nowait(f"__ERROR__:{exc}")
    finally:
        detach_queue_logging(handler, orig_stdout)


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
    render_job_history, render_live_trading,
    render_full_pipeline, render_paper_trading, render_portfolio,
    render_deep_evaluation, render_fast_evaluation, render_selected_stocks,
    render_settings, render_stock_lookup,
    render_stock_manager, render_stock_screener, render_stock_technical,
    render_strategy_backtest,
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
    if "ctx" not in st.session_state:
        st.session_state.ctx = PageContext(
            st=st,
            repo=repo,
            session_state=st.session_state,
            full_pipeline_thread_target=_full_pipeline_thread_target,
        )
    return st.session_state.ctx


# ── Main ──────────────────────────────────────────────────────────────────────

def sidebar_nav():
    page = st.selectbox(
        "Navigation",
        ["Full Pipeline", "Selected Stocks", "Fast Evaluation", "Deep Evaluation", "Stock Data",
         "Strategy Backtesting", "Live Trading", "Paper Trading",
         "Portfolio Analysis", "Settings", "Job History"],
        label_visibility="collapsed",
        key="nav_selectbox",
    )
    return page


def render_page_content(page, ctx):
    if page == "Full Pipeline":
        render_full_pipeline(ctx)
    elif page == "Selected Stocks":
        render_selected_stocks(ctx)
    elif page == "Fast Evaluation":
        render_fast_evaluation(ctx)
    elif page == "Deep Evaluation":
        render_deep_evaluation(ctx)
    elif page == "Stock Data":
        page_stock_data(ctx)
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


def main() -> None:
    with st.sidebar:
        st.markdown('<h2 style="color:#1e293b;margin:0 0 4px">📈 AIStock</h2>', unsafe_allow_html=True)
        st.markdown('<p style="color:#64748b;font-size:12px;margin:0 0 16px">Trading Platform</p>', unsafe_allow_html=True)
        st.divider()
        page = sidebar_nav()
        st.divider()
        display_quick_stats(repo)
    ctx = _build_ctx()
    render_page_content(page, ctx)


if __name__ == "__main__":
    main()
