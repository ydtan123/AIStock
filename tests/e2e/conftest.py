"""Shared fixtures and helpers for Streamlit E2E tests.

Run with:
    pytest tests/e2e/ -m e2e --base-url http://localhost:8501

Requires:
    - pip install pytest-playwright
    - playwright install chromium
    - Streamlit app running: PYTHONPATH=src streamlit run src/app.py
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

BASE_URL = "http://localhost:8501"

PAGES = [
    "Full Pipeline",
    "Selected Stocks",
    "Fast Evaluation",
    "Deep Evaluation",
    "Stock Data",
    "ML Pipeline",
    "Strategy Backtesting",
    "Live Trading",
    "Paper Trading",
    "Portfolio Analysis",
    "Settings",
    "Job History",
]

PAGE_HEADERS = {
    "Full Pipeline": "Full Pipeline",
    "Selected Stocks": "Selected Stocks",
    "Fast Evaluation": "Fast Evaluation",
    "Deep Evaluation": "Deep Evaluation",
    "ML Pipeline": "ML Pipeline",
    "Settings": "Settings",
    "Job History": "Job History",
}


def wait_for_streamlit(page: Page, timeout: int = 15_000) -> None:
    """Wait for Streamlit to finish rendering — spinner gone, app visible."""
    page.wait_for_selector('[data-testid="stApp"]', timeout=timeout)
    page.wait_for_function(
        "!document.querySelector('[data-testid=\"stStatusWidget\"]') || "
        "document.querySelector('[data-testid=\"stStatusWidget\"]').style.display === 'none'",
        timeout=timeout,
    )


def navigate_to(page: Page, page_name: str, timeout: int = 10_000) -> None:
    """Click the sidebar nav selectbox and choose page_name."""
    sidebar = page.locator('[data-testid="stSidebar"]')
    selectbox = sidebar.locator('[data-testid="stSelectbox"]').first
    selectbox.click()
    option = page.locator('[data-baseweb="popover"] li', has_text=page_name).first
    option.wait_for(timeout=timeout)
    option.click()
    wait_for_streamlit(page)


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture
def app(page: Page, base_url: str) -> Page:
    """Load the app and wait for it to be ready."""
    page.goto(base_url)
    wait_for_streamlit(page)
    return page
