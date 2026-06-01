"""Tests for shared utility functions (src/utils.py)."""
from datetime import date

import pytest

from utils import safe_float, safe_int, safe_date, nan_safe
from display import fmt_market_cap


class TestSafeFloat:
    def test_valid_number_returns_float(self):
        assert safe_float("3.14") == pytest.approx(3.14)
        assert safe_float(42) == 42.0
        assert safe_float("0") == 0.0
        assert safe_float("-1.5") == pytest.approx(-1.5)

    def test_none_returns_none(self):
        assert safe_float(None) is None

    def test_nan_returns_none(self):
        assert safe_float(float('nan')) is None

    def test_empty_string_returns_none(self):
        assert safe_float("") is None

    def test_garbage_string_returns_none(self):
        assert safe_float("abc") is None
        assert safe_float("12ab34") is None

    def test_infinity_handled(self):
        assert safe_float("inf") == float("inf")
        assert safe_float("-inf") == float("-inf")

    def test_list_returns_none(self):
        assert safe_float([1, 2]) is None


class TestSafeInt:
    def test_valid_integer_string(self):
        assert safe_int("42") == 42
        assert safe_int("0") == 0
        assert safe_int("-1") == -1

    def test_float_string_truncates(self):
        assert safe_int("3.14") == 3

    def test_none_returns_none(self):
        assert safe_int(None) is None

    def test_invalid_returns_none(self):
        assert safe_int("abc") is None
        assert safe_int("") is None

    def test_nan_returns_none(self):
        assert safe_int(float('nan')) is None


class TestSafeDate:
    def test_valid_iso_date(self):
        assert safe_date("2024-01-15") == date(2024, 1, 15)

    def test_none_returns_none(self):
        assert safe_date(None) is None

    def test_empty_string_returns_none(self):
        assert safe_date("") is None

    def test_magic_none_string_returns_none(self):
        assert safe_date("None") is None

    def test_invalid_month_returns_none(self):
        assert safe_date("2024-13-01") is None

    def test_invalid_day_returns_none(self):
        assert safe_date("2024-02-30") is None

    def test_garbage_returns_none(self):
        assert safe_date("not-a-date") is None

    def test_wrong_format_returns_none(self):
        assert safe_date("2024/01/15") is None


class TestNanSafe:
    def test_wraps_valid_input(self):
        @nan_safe
        def double(x):
            return f"{x * 2}"
        assert double(5) == "10"

    def test_none_returns_emdash(self):
        @nan_safe
        def identity(x):
            return x
        assert identity(None) == "—"

    def test_nan_returns_emdash(self):
        @nan_safe
        def passthrough(x):
            return x
        assert passthrough(float('nan')) == "—"

    def test_exception_in_fn_returns_emdash(self):
        @nan_safe
        def raiser(_):
            raise ValueError("boom")
        assert raiser(1) == "—"

    def test_type_error_returns_emdash(self):
        @nan_safe
        def bad_op(x):
            return x + "string"
        assert bad_op(1) == "—"


class TestFmtMarketCap:
    def test_trillions(self):
        assert fmt_market_cap(1_500_000_000_000) == "$1.50T"

    def test_billions(self):
        assert fmt_market_cap(5_000_000_000) == "$5.00B"

    def test_millions(self):
        assert fmt_market_cap(500_000_000) == "$500.0M"

    def test_below_million(self):
        result = fmt_market_cap(999_999)
        assert "$" in result

    def test_none_returns_emdash(self):
        assert fmt_market_cap(None) == "—"

    def test_nan_returns_emdash(self):
        assert fmt_market_cap(float('nan')) == "—"

    def test_invalid_type_returns_emdash(self):
        assert fmt_market_cap("abc") == "—"
