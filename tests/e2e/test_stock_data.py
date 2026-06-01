"""E2E tests for Stock Data page (tabs: Lookup, Technical, Screener, Manager)."""
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import navigate_to


pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def go_to_page(app: Page) -> None:
    navigate_to(app, "Stock Data")


def test_tabs_container_visible(app: Page) -> None:
    expect(app.locator('[data-testid="stTabs"]')).to_be_visible()


def test_four_tabs_present(app: Page) -> None:
    for tab_name in ("Lookup", "Technical", "Screener", "Manager"):
        tab = app.locator('[data-testid="stTab"]').filter(has_text=tab_name)
        expect(tab).to_be_visible()


def test_technical_tab_navigable(app: Page) -> None:
    app.locator('[data-testid="stTab"]').filter(has_text="Technical").click()
    expect(app.locator('[data-testid="stException"]')).to_have_count(0)


def test_screener_tab_navigable(app: Page) -> None:
    app.locator('[data-testid="stTab"]').filter(has_text="Screener").click()
    expect(app.locator('[data-testid="stException"]')).to_have_count(0)


def test_manager_tab_navigable(app: Page) -> None:
    app.locator('[data-testid="stTab"]').filter(has_text="Manager").click()
    expect(app.locator('[data-testid="stException"]')).to_have_count(0)


def test_no_exception(app: Page) -> None:
    expect(app.locator('[data-testid="stException"]')).to_have_count(0)
