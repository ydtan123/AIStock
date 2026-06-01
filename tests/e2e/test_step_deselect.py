"""Regression test: deselecting first 3 pipeline steps must not blank the page."""
import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:8502"


def _step_checkbox(page: Page, label: str):
    return page.locator('[data-testid="stCheckbox"]').filter(has_text=label)


def _uncheck_step(page: Page, label: str) -> None:
    cb = _step_checkbox(page, label).locator("input")
    if cb.is_checked():
        _step_checkbox(page, label).click()
    page.wait_for_timeout(800)


def test_deselect_first_three_steps_page_not_blank(page):
    page.goto(BASE_URL, wait_until="networkidle")

    # Confirm all 4 step checkboxes present
    for label in ["1. Data Update", "2. Stock Selection", "3. Fast Evaluation", "4. Deep Evaluation"]:
        expect(_step_checkbox(page, label)).to_be_visible()

    # Uncheck steps 1, 2, 3
    _uncheck_step(page, "1. Data Update")
    _uncheck_step(page, "2. Stock Selection")
    _uncheck_step(page, "3. Fast Evaluation")

    # Page must NOT be blank: header still visible
    expect(page.get_by_role("heading", name="Full Pipeline")).to_be_visible()

    # Run/Stop buttons must still be visible
    expect(page.get_by_role("button", name="Run Pipeline")).to_be_visible()
    expect(page.get_by_role("button", name="Stop")).to_be_visible()

    # Step 4 checkbox still checked
    expect(_step_checkbox(page, "4. Deep Evaluation").locator("input")).to_be_checked()

    # Step 4 expander section visible
    expect(page.get_by_text("4. Deep Evaluation").first).to_be_visible()
