"""Backend ABC + registry tests using fakes."""
import logging
from pathlib import Path

import pytest

from pipeline.backends.selectors import (
    SELECTOR_REGISTRY,
    ScoredTicker,
    StockSelector,
)
from pipeline.base import StepContext


def make_ctx(tmp_path, cfg=None):
    return StepContext(
        cfg=cfg or {},
        run_id=1,
        report_dir=tmp_path,
        logger=logging.getLogger("test"),
        session_factory=lambda: None,
    )


def test_scored_ticker_construction():
    t = ScoredTicker(ticker="AAPL", ml_score=0.5, sector="Tech")
    assert t.ticker == "AAPL"
    assert t.sector == "Tech"


def test_stock_selector_is_abstract():
    with pytest.raises(TypeError):
        StockSelector()  # type: ignore[abstract]


def test_stock_selector_subclass_must_define_name(tmp_path):
    class NoName(StockSelector):
        def select(self, ctx):
            return []

    with pytest.raises(TypeError, match="name"):
        NoName()  # type: ignore[abstract]


def test_fake_selector_registers_and_runs(tmp_path):
    @SELECTOR_REGISTRY.register
    class FakeSelector(StockSelector):
        name = "fake_selector_test"

        def __init__(self, cfg=None):
            self.cfg = cfg or {}

        def select(self, ctx):
            return [ScoredTicker(ticker="X", ml_score=1.0, sector=None)]

    assert "fake_selector_test" in SELECTOR_REGISTRY
    cls = SELECTOR_REGISTRY.get("fake_selector_test")
    out = cls().select(make_ctx(tmp_path))
    assert out[0].ticker == "X"
    SELECTOR_REGISTRY.unregister("fake_selector_test")
    assert "fake_selector_test" not in SELECTOR_REGISTRY


def test_registry_get_unknown_raises():
    with pytest.raises(KeyError, match="unknown selector"):
        SELECTOR_REGISTRY.get("does_not_exist")
