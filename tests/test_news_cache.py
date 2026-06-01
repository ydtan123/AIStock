"""Tests for news cache (src/news_cache.py)."""
import pytest

from news_cache import _key


class TestKey:
    def test_get_news_key_from_args(self):
        result = _key("get_news", ("AAPL", "2024-01-01", "2024-03-31"), {})
        assert result == ("AAPL", "2024-01-01", "2024-03-31")

    def test_get_news_key_from_kwargs(self):
        result = _key("get_news", (), {"ticker": "MSFT", "start_date": "2024-01-01",
                                        "end_date": "2024-06-30"})
        assert result == ("MSFT", "2024-01-01", "2024-06-30")

    def test_get_global_news_key_format(self):
        _, start, end = _key("get_global_news", ("2024-05-01", 14, 10), {})
        assert start == "2024-05-01"
        assert "14" in end
        assert "10" in end

    def test_get_insider_transactions_key(self):
        result = _key("get_insider_transactions", ("AAPL",), {})
        assert result == ("AAPL", "", "")

    def test_unknown_tool_returns_unknown(self):
        result = _key("unknown_tool", (), {})
        assert result == ("__unknown__", "", "")

    def test_mixed_args_and_kwargs(self):
        result = _key("get_news", ("TSLA",), {"start_date": "2024-01-01",
                                                "end_date": "2024-06-30"})
        assert result == ("TSLA", "2024-01-01", "2024-06-30")


class TestGetCached:
    def test_uncacheable_tool_returns_none(self):
        from news_cache import get_cached
        result = get_cached("uncacheable_tool", (), {})
        assert result is None


class TestSetCached:
    def test_uncacheable_tool_skips(self):
        from news_cache import set_cached
        result = set_cached("uncacheable", (), {}, "some data")
        assert result is None

    def test_empty_result_skips(self):
        from news_cache import set_cached
        result = set_cached("get_news", ("AAPL", "s", "e"), {}, "")
        assert result is None

    def test_whitespace_only_result_skips(self):
        from news_cache import set_cached
        result = set_cached("get_news", ("AAPL", "s", "e"), {}, "   ")
        assert result is None


class TestInstall:
    def test_install_is_idempotent_no_crash(self):
        """install() should not crash, even without tradingagents module."""
        from news_cache import install
        try:
            install()
        except ImportError:
            pass  # Expected when tradingagents not installed
