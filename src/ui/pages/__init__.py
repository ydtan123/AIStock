from __future__ import annotations

from ui.pages.stock_lookup import render as render_stock_lookup
from ui.pages.stock_technical import render as render_stock_technical
from ui.pages.stock_screener import render as render_stock_screener
from ui.pages.stock_manager import render as render_stock_manager
from ui.pages.overview import render as render_overview
from ui.pages.ml_pipeline import render as render_ml_pipeline
from ui.pages.live_trading import render as render_live_trading
from ui.pages.portfolio import render as render_portfolio
from ui.pages.strategy_backtest import render as render_strategy_backtest
from ui.pages.paper_trading import render as render_paper_trading
from ui.pages.settings import render as render_settings
from ui.pages.stock_detail import render as render_stock_detail
from ui.pages.job_history import render as render_job_history

__all__ = [
    "render_stock_lookup",
    "render_stock_technical",
    "render_stock_screener",
    "render_stock_manager",
    "render_overview",
    "render_ml_pipeline",
    "render_live_trading",
    "render_portfolio",
    "render_strategy_backtest",
    "render_paper_trading",
    "render_settings",
    "render_stock_detail",
    "render_job_history",
]
