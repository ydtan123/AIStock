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


_CONTENT_LOCATOR = (
    '[data-testid="stSelectbox"]:has-text("Pipeline Run"), '
    ':text("No pipeline runs")'
)


def test_shows_run_selector_or_empty_state(app: Page) -> None:
    """Wait up to 10s for either the run selectbox or empty-state text to appear."""
    expect(app.locator(_CONTENT_LOCATOR).first).to_be_visible(timeout=10_000)


def _has_run_data(app: Page) -> bool:
    return app.locator('[data-testid="stSelectbox"]:has-text("Pipeline Run")').is_visible()


def test_top_n_filter_visible_when_data_present(app: Page) -> None:
    if not _has_run_data(app):
        pytest.skip("No pipeline data")
    expect(app.locator('[data-testid="stNumberInput"]').first).to_be_visible()


def test_stock_table_visible_when_data_present(app: Page) -> None:
    if not _has_run_data(app):
        pytest.skip("No pipeline data")
    expect(app.locator('[data-testid="stDataFrame"]').first).to_be_visible()


def test_no_exception(app: Page) -> None:
    expect(app.locator('[data-testid="stException"]')).to_have_count(0)
