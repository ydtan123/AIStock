"""Tests for fetcher factory (src/fetcher/__init__.py)."""
import pytest

from fetcher import create_fetcher
from fetcher.alpha_vantage import AlphaVantageFetcher
from fetcher.yahoo import YahooFetcher


class TestCreateFetcher:
    def test_alpha_vantage_source(self):
        cfg = {"source": "alpha_vantage", "alpha_vantage": {"api_key": "test_key"}}
        f = create_fetcher(cfg)
        assert isinstance(f, AlphaVantageFetcher)

    def test_yahoo_source(self):
        cfg = {"source": "yahoo"}
        f = create_fetcher(cfg)
        assert isinstance(f, YahooFetcher)

    def test_defaults_to_alpha_vantage(self):
        cfg = {"alpha_vantage": {"api_key": "test_key"}}
        f = create_fetcher(cfg)
        assert isinstance(f, AlphaVantageFetcher)

    def test_unknown_source_raises_value_error(self):
        cfg = {"source": "bloomberg"}
        with pytest.raises(ValueError, match="Unknown source"):
            create_fetcher(cfg)
