"""E2E tests for Selected Stocks page."""
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import navigate_to


pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def go_to_page(app: Page) -> None:
    navigate_to(app, "Selected Stocks")


def test_header_visible(app: Page) -> None:
    expect(app.locator("h1, h2").filter(has_text="Selected Stocks").first).to_be_visible()


def test_shows_run_selector_or_empty_state(app: Page) -> None:
    """Page shows run selectbox (data) or info/empty message (no data)."""
    run_selector = app.locator('[data-testid="stSelectbox"]').filter(has_text="Pipeline Run")
    empty_state = app.locator('[data-testid="stAlert"]').filter(has_text="No pipeline runs")
    assert run_selector.is_visible() or empty_state.is_visible(), \
        "Neither run selector nor empty-state message found"


def test_top_n_filter_visible_when_data_present(app: Page) -> None:
    run_selector = app.locator('[data-testid="stSelectbox"]').filter(has_text="Pipeline Run")
    if not run_selector.is_visible():
        pytest.skip("No pipeline data")
    expect(app.locator('[data-testid="stNumberInput"]').first).to_be_visible()


def test_stock_table_visible_when_data_present(app: Page) -> None:
    run_selector = app.locator('[data-testid="stSelectbox"]').filter(has_text="Pipeline Run")
    if not run_selector.is_visible():
        pytest.skip("No pipeline data")
    expect(app.locator('[data-testid="stDataFrame"]').first).to_be_visible()


def test_no_exception(app: Page) -> None:
    expect(app.locator('[data-testid="stException"]')).to_have_count(0)
