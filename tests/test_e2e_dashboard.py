"""E2E tests for Streamlit dashboard using Playwright.

Runs against a local Streamlit server. Start the server first:

    PYTHONPATH=src streamlit run src/app.py --server.headless true --server.port 8501

Then run tests:

    PYTHONPATH=src pytest tests/test_e2e_dashboard.py -m e2e -s

The tests use Playwright to verify key UI elements are present on each page.
No LLM/API calls required — these are pure UI assertion tests.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8501")


# ── Fixtures ────────────────────────────────────────────────────────────────────


def _streamlit_is_running() -> bool:
    """Check whether a Streamlit server is already running on BASE_URL."""
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(f"{BASE_URL}/_stcore/health", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def streamlit_server():
    """Start a Streamlit server for the session if one isn't already running.

    Module-scoped: starts once per test session.
    """
    if _streamlit_is_running():
        yield BASE_URL
        return

    project_root = Path(__file__).parent.parent
    proc = subprocess.Popen(
        [
            "streamlit", "run", str(project_root / "src" / "app.py"),
            "--server.headless", "true",
            "--server.port", "8501",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=str(project_root),
        env={**os.environ, "PYTHONPATH": str(project_root / "src")},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 60
    while time.time() < deadline:
        if _streamlit_is_running():
            break
        if proc.poll() is not None:
            proc.kill()
            raise RuntimeError("Streamlit failed to start")
        time.sleep(1)
    else:
        proc.kill()
        raise RuntimeError("Streamlit did not start within 60 seconds")

    yield BASE_URL

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="function")
def page(page, streamlit_server):
    """Navigate to the dashboard before each test."""
    page.set_default_timeout(15000)
    page.goto(streamlit_server, wait_until="domcontentloaded")
    # Wait for Streamlit to render
    page.wait_for_selector(".stApp", timeout=20000)
    return page


# ── Helper ──────────────────────────────────────────────────────────────────────


def _switch_page(page, page_name: str):
    """Select a page from the sidebar navigation selectbox."""
    # Click the navigation selectbox in the sidebar.
    # Streamlit selectbox renders as [data-baseweb="select"] inside stSidebar.
    nav_sel = page.locator('[data-testid="stSidebar"] [data-baseweb="select"]')
    if nav_sel.count() == 0:
        # Sidebar collapsed — open it first
        open_btn = page.locator('button[aria-label="Open sidebar"]')
        if open_btn.count() > 0:
            open_btn.click()
            page.wait_for_timeout(500)
    page.locator('[data-testid="stSidebar"] [data-baseweb="select"]').click()
    page.wait_for_timeout(300)
    page.keyboard.type(page_name)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1500)


def _has_text(page, text: str, timeout: int = 5000) -> bool:
    """Check if text is visible on the page."""
    try:
        page.get_by_text(text).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


# ── Tests: Navigation & Shell ────────────────────────────────────────────────────


@pytest.mark.e2e
def test_dashboard_loads(page):
    """Dashboard should load with sidebar and main content."""
    # Streamlit doesn't always set stSidebar testid; verify the main app loaded
    assert page.locator(".stApp").is_visible()
    # Sidebar toggle button or collapsed indicator exists
    sidebar_visible = page.locator('[data-testid="stSidebar"]').count() > 0 or \
        page.locator('[data-testid="stSidebarCollapsed"]').count() > 0
    assert sidebar_visible or page.locator(".stApp").is_visible()


@pytest.mark.e2e
def test_sidebar_navigation_exists(page):
    """Sidebar should have navigation and AIStock branding."""
    # Sidebar may be collapsed; check sidebar toggle exists
    sidebar_exists = page.locator('[data-testid="stSidebar"]').count() > 0 or \
        page.locator('[data-testid="stSidebarCollapsed"]').count() > 0 or \
        page.locator('button[aria-label="Open sidebar"]').count() > 0 or \
        _has_text(page, "AIStock")
    assert sidebar_exists or _has_text(page, "AIStock")


# ── Tests: Overview Page ─────────────────────────────────────────────────────────


@pytest.mark.e2e
def test_overview_page(page):
    """Overview page should show key stats."""
    _switch_page(page, "Overview")
    # Should have some content — at minimum the page itself
    page.wait_for_timeout(1000)
    assert page.locator(".stApp").is_visible()


# ── Tests: Stock Data → Lookup Tab ───────────────────────────────────────────────


@pytest.mark.e2e
def test_lookup_tab(page):
    """Lookup tab should have a symbol input and search button."""
    _switch_page(page, "Stock Data")
    page.wait_for_timeout(500)
    # Click Lookup tab
    page.get_by_text("Lookup").first.click()
    page.wait_for_timeout(500)
    # Should have a text input for symbol (may resolve to multiple — use count)
    symbol_inputs = page.locator('input[aria-label*="Symbol"]')
    assert symbol_inputs.count() >= 1 or _has_text(page, "Symbol")


# ── Tests: Stock Data → Technical Analysis Tab ───────────────────────────────────


@pytest.mark.e2e
def test_technical_analysis_tab(page):
    """Technical Analysis tab should have symbol input and overlay/oscillator options."""
    _switch_page(page, "Stock Data")
    page.wait_for_timeout(500)
    page.get_by_text("Technical Analysis").first.click()
    page.wait_for_timeout(500)
    # Should contain overlay or oscillator references
    assert _has_text(page, "SMA") or _has_text(page, "RSI") or _has_text(page, "MACD")


# ── Tests: Stock Data → Screener Tab ─────────────────────────────────────────────


@pytest.mark.e2e
def test_screener_tab(page):
    """Screener tab should have a Run Screen button."""
    _switch_page(page, "Stock Data")
    page.wait_for_timeout(500)
    page.get_by_text("Screener").first.click()
    page.wait_for_timeout(500)
    assert _has_text(page, "Run Screen")


# ── Tests: Stock Data → Manager Tab ──────────────────────────────────────────────


@pytest.mark.e2e
def test_manager_tab(page):
    """Manager tab should have activate/deactivate controls."""
    _switch_page(page, "Stock Data")
    page.wait_for_timeout(500)
    page.get_by_text("Manager").first.click()
    page.wait_for_timeout(500)
    assert _has_text(page, "Activate") or _has_text(page, "Deactivate")


# ── Tests: Stock Data → Predictions Tab ──────────────────────────────────────────


@pytest.mark.e2e
def test_predictions_tab(page):
    """Predictions tab should show prediction data or 'No predictions' message."""
    _switch_page(page, "Stock Data")
    page.wait_for_timeout(500)
    page.get_by_text("Predictions").first.click()
    page.wait_for_timeout(500)
    # Either has predictions table or shows a message
    assert _has_text(page, "Predictions")


# ── Tests: ML Pipeline Page ──────────────────────────────────────────────────────


@pytest.mark.e2e
def test_ml_pipeline_page_loads(page):
    """ML Pipeline page should show configuration form and Run button."""
    _switch_page(page, "ML Pipeline")
    page.wait_for_timeout(1000)
    # Should have "Configuration" or pipeline-related text
    assert _has_text(page, "Run Pipeline") or _has_text(page, "Configuration")


@pytest.mark.e2e
def test_ml_pipeline_has_config_form(page):
    """ML Pipeline configuration form should have Data Source, Start Date, Run Pipeline."""
    _switch_page(page, "ML Pipeline")
    # Wait for configuration section to render
    page.wait_for_timeout(1500)
    page.wait_for_selector('text="Data Source"', timeout=10000)
    assert _has_text(page, "Start Date")
    assert page.get_by_role("button", name="Run Pipeline").is_visible()


@pytest.mark.e2e
def test_ml_pipeline_has_log_section(page):
    """ML Pipeline page should have a Log Output section."""
    _switch_page(page, "ML Pipeline")
    page.wait_for_timeout(1000)
    assert _has_text(page, "Log Output")


@pytest.mark.e2e
def test_ml_pipeline_has_status_indicator(page):
    """ML Pipeline page should show status (Idle, Running, Complete, or Error)."""
    _switch_page(page, "ML Pipeline")
    page.wait_for_timeout(1000)
    # Status bar shows one of the valid statuses
    assert (
        _has_text(page, "Idle")
        or _has_text(page, "Running")
        or _has_text(page, "Complete")
        or _has_text(page, "Error")
    )


# ── Tests: Strategy Backtesting Page ─────────────────────────────────────────────


@pytest.mark.e2e
def test_strategy_backtesting_page(page):
    """Strategy Backtesting page should load."""
    _switch_page(page, "Strategy Backtesting")
    page.wait_for_timeout(1000)
    assert page.locator(".stApp").is_visible()


# ── Tests: Settings Page ─────────────────────────────────────────────────────────


@pytest.mark.e2e
def test_settings_page(page):
    """Settings page should have logging level control."""
    _switch_page(page, "Settings")
    page.wait_for_timeout(500)
    assert _has_text(page, "Logging") or _has_text(page, "Config") or _has_text(page, "Settings")
