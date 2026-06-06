from __future__ import annotations

from ui.pages.stock_lookup import render as render_stock_lookup
from ui.pages.stock_technical import render as render_stock_technical
from ui.pages.stock_screener import render as render_stock_screener
from ui.pages.stock_manager import render as render_stock_manager
from ui.pages.stock_news import render as render_stock_news
from ui.pages.overview import render as render_full_pipeline
from ui.pages.live_trading import render as render_live_trading
from ui.pages.portfolio import render as render_portfolio
from ui.pages.strategy_backtest import render as render_strategy_backtest
from ui.pages.paper_trading import render as render_paper_trading
from ui.pages.settings import render as render_settings
from ui.pages.stock_detail import render as render_stock_detail
from ui.pages.job_history import render as render_job_history
from ui.pages.selected_stocks import render as render_selected_stocks
from ui.pages.fast_evaluation_page import render as render_fast_evaluation
from ui.pages.deep_evaluation_page import render as render_deep_evaluation

__all__ = [
    "render_stock_lookup",
    "render_stock_technical",
    "render_stock_screener",
    "render_stock_manager",
    "render_stock_news",
    "render_full_pipeline",
    "render_live_trading",
    "render_portfolio",
    "render_strategy_backtest",
    "render_paper_trading",
    "render_settings",
    "render_stock_detail",
    "render_job_history",
    "render_selected_stocks",
    "render_fast_evaluation",
    "render_deep_evaluation",
]
