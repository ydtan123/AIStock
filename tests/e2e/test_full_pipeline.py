"""E2E tests for Full Pipeline page controls."""
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import navigate_to


pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def go_to_page(app: Page) -> None:
    navigate_to(app, "Full Pipeline")


def test_header_visible(app: Page) -> None:
    expect(app.locator("h1, h2").filter(has_text="Full Pipeline").first).to_be_visible()


def test_step_checkboxes_visible(app: Page) -> None:
    """Step selection checkboxes render (at least one for each pipeline step)."""
    checkboxes = app.locator('[data-testid="stCheckbox"]')
    expect(checkboxes.first).to_be_visible()
    assert checkboxes.count() >= 1


def test_run_button_visible(app: Page) -> None:
    run_btn = app.locator('[data-testid="stButton"]').filter(has_text="Run Pipeline")
    expect(run_btn).to_be_visible()


def test_stop_button_visible(app: Page) -> None:
    stop_btn = app.locator('[data-testid="stButton"]').filter(has_text="Stop")
    expect(stop_btn).to_be_visible()


def test_pipeline_not_running_on_load(app: Page) -> None:
    """Log area should not show 'Running...' before Run is clicked."""
    running_indicator = app.locator('[data-testid="stAlert"]').filter(has_text="Running")
    assert not running_indicator.is_visible()


def test_no_exception(app: Page) -> None:
    expect(app.locator('[data-testid="stException"]')).to_have_count(0)
