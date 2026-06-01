"""E2E tests for Fast Evaluation and Deep Evaluation pages."""
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import navigate_to


pytestmark = pytest.mark.e2e


class TestFastEvaluation:
    @pytest.fixture(autouse=True)
    def go_to_page(self, app: Page) -> None:
        navigate_to(app, "Fast Evaluation")

    def test_header_visible(self, app: Page) -> None:
        expect(app.locator("h1, h2").filter(has_text="Fast Evaluation").first).to_be_visible()

    def test_shows_run_selector_or_empty_state(self, app: Page) -> None:
        run_selector = app.locator('[data-testid="stSelectbox"]').filter(has_text="Pipeline Run")
        empty_state = app.locator('[data-testid="stAlert"]').filter(has_text="No pipeline runs")
        assert run_selector.is_visible() or empty_state.is_visible()

    def test_stock_selector_visible_when_data_present(self, app: Page) -> None:
        run_selector = app.locator('[data-testid="stSelectbox"]').filter(has_text="Pipeline Run")
        if not run_selector.is_visible():
            pytest.skip("No pipeline data")
        expect(app.locator('[data-testid="stSelectbox"]').filter(has_text="Stock")).to_be_visible()

    def test_shows_analyst_section_or_no_data_info(self, app: Page) -> None:
        run_selector = app.locator('[data-testid="stSelectbox"]').filter(has_text="Pipeline Run")
        if not run_selector.is_visible():
            pytest.skip("No pipeline data")
        no_data = app.locator('[data-testid="stAlert"]').filter(has_text="No fast evaluation")
        analyst_section = app.locator("h2, h3").filter(has_text="Analyst Opinions")
        assert no_data.is_visible() or analyst_section.is_visible()

    def test_no_exception(self, app: Page) -> None:
        expect(app.locator('[data-testid="stException"]')).to_have_count(0)


class TestDeepEvaluation:
    @pytest.fixture(autouse=True)
    def go_to_page(self, app: Page) -> None:
        navigate_to(app, "Deep Evaluation")

    def test_header_visible(self, app: Page) -> None:
        expect(app.locator("h1, h2").filter(has_text="Deep Evaluation").first).to_be_visible()

    def test_shows_run_selector_or_empty_state(self, app: Page) -> None:
        run_selector = app.locator('[data-testid="stSelectbox"]').filter(has_text="Pipeline Run")
        empty_state = app.locator('[data-testid="stAlert"]').filter(has_text="No pipeline runs")
        assert run_selector.is_visible() or empty_state.is_visible()

    def test_stock_selector_visible_when_data_present(self, app: Page) -> None:
        run_selector = app.locator('[data-testid="stSelectbox"]').filter(has_text="Pipeline Run")
        if not run_selector.is_visible():
            pytest.skip("No pipeline data")
        expect(app.locator('[data-testid="stSelectbox"]').filter(has_text="Stock")).to_be_visible()

    def test_shows_summary_or_no_data_info(self, app: Page) -> None:
        run_selector = app.locator('[data-testid="stSelectbox"]').filter(has_text="Pipeline Run")
        if not run_selector.is_visible():
            pytest.skip("No pipeline data")
        no_data = app.locator('[data-testid="stAlert"]').filter(has_text="No deep evaluation")
        summary = app.locator("h2, h3").filter(has_text="Summary")
        assert no_data.is_visible() or summary.is_visible()

    def test_no_exception(self, app: Page) -> None:
        expect(app.locator('[data-testid="stException"]')).to_have_count(0)
