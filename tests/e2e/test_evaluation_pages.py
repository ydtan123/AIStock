"""E2E tests for Fast Evaluation and Deep Evaluation pages."""
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import navigate_to


pytestmark = pytest.mark.e2e


_CONTENT_LOCATOR = (
    '[data-testid="stSelectbox"]:has-text("Pipeline Run"), '
    ':text("No pipeline runs")'
)


def _has_run_data(app: Page) -> bool:
    return app.locator('[data-testid="stSelectbox"]:has-text("Pipeline Run")').is_visible()


def _has_stock_selector(app: Page) -> bool:
    return app.locator('[data-testid="stSelectbox"]:has-text("Stock")').is_visible()


class TestFastEvaluation:
    @pytest.fixture(autouse=True)
    def go_to_page(self, app: Page) -> None:
        navigate_to(app, "Fast Evaluation")

    def test_header_visible(self, app: Page) -> None:
        expect(app.locator("h1, h2").filter(has_text="Fast Evaluation").first).to_be_visible()

    def test_shows_run_selector_or_empty_state(self, app: Page) -> None:
        """Wait up to 10s for either run selectbox or empty-state message."""
        expect(app.locator(_CONTENT_LOCATOR).first).to_be_visible(timeout=10_000)

    def test_stock_selector_visible_when_data_present(self, app: Page) -> None:
        if not _has_run_data(app):
            pytest.skip("No pipeline data")
        assert _has_stock_selector(app), "Stock selectbox label not found"

    def test_shows_analyst_section_or_no_data_info(self, app: Page) -> None:
        if not _has_run_data(app):
            pytest.skip("No pipeline data")
        no_data = app.locator(':text("No fast evaluation")').is_visible()
        analyst_section = app.locator("h2, h3").filter(has_text="Analyst Opinions").is_visible()
        assert no_data or analyst_section

    def test_no_exception(self, app: Page) -> None:
        expect(app.locator('[data-testid="stException"]')).to_have_count(0)


class TestDeepEvaluation:
    @pytest.fixture(autouse=True)
    def go_to_page(self, app: Page) -> None:
        navigate_to(app, "Deep Evaluation")

    def test_header_visible(self, app: Page) -> None:
        expect(app.locator("h1, h2").filter(has_text="Deep Evaluation").first).to_be_visible()

    def test_shows_run_selector_or_empty_state(self, app: Page) -> None:
        """Wait up to 10s for either run selectbox or empty-state message."""
        expect(app.locator(_CONTENT_LOCATOR).first).to_be_visible(timeout=10_000)

    def test_stock_selector_visible_when_data_present(self, app: Page) -> None:
        if not _has_run_data(app):
            pytest.skip("No pipeline data")
        assert _has_stock_selector(app), "Stock selectbox label not found"

    def test_shows_summary_or_no_data_info(self, app: Page) -> None:
        if not _has_run_data(app):
            pytest.skip("No pipeline data")
        no_data = app.locator(':text("No deep evaluation")').is_visible()
        summary = app.locator("h2, h3").filter(has_text="Summary").is_visible()
        assert no_data or summary

    def test_no_exception(self, app: Page) -> None:
        expect(app.locator('[data-testid="stException"]')).to_have_count(0)
