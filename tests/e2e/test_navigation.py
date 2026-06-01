"""Navigation smoke tests — every page must load without crashing."""
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import PAGE_HEADERS, navigate_to


pytestmark = pytest.mark.e2e


def test_app_loads(app: Page) -> None:
    """App renders and sidebar navigation is visible."""
    expect(app.locator('[data-testid="stApp"]')).to_be_visible()
    expect(app.locator('[data-testid="stSidebar"]')).to_be_visible()


def test_sidebar_has_navigation_selectbox(app: Page) -> None:
    """Sidebar contains nav selectbox."""
    sidebar = app.locator('[data-testid="stSidebar"]')
    selectbox = sidebar.locator('[data-testid="stSelectbox"]').first
    expect(selectbox).to_be_visible()


def test_no_unhandled_errors_on_load(app: Page) -> None:
    """No Streamlit exception box on initial load."""
    expect(app.locator('[data-testid="stException"]')).to_have_count(0)


@pytest.mark.parametrize("page_name", [
    "Full Pipeline",
    "Selected Stocks",
    "Fast Evaluation",
    "Deep Evaluation",
    "Settings",
    "Job History",
])
def test_page_loads_without_exception(app: Page, page_name: str) -> None:
    """Every page navigates without a Streamlit exception."""
    navigate_to(app, page_name)
    expect(app.locator('[data-testid="stException"]')).to_have_count(0)


@pytest.mark.parametrize("page_name,expected_header", PAGE_HEADERS.items())
def test_page_shows_correct_header(app: Page, page_name: str, expected_header: str) -> None:
    """Each page shows its h1/h2 header after navigation."""
    navigate_to(app, page_name)
    header = app.locator("h1, h2").filter(has_text=expected_header).first
    expect(header).to_be_visible()
