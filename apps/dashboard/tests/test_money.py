from decimal import Decimal

from django.template import Context, Template
import pytest


def render(s: str, ctx: dict | None = None) -> str:
    return Template("{% load money %}" + s).render(Context(ctx or {}))


def test_positive_dollar():
    assert render("{{ v|money }}", {"v": Decimal("1234.56")}) == "$1,234.56"


def test_negative_dollar_uses_minus_sign():
    assert render("{{ v|money }}", {"v": Decimal("-1234.56")}) == "−$1,234.56"


def test_zero():
    assert render("{{ v|money }}", {"v": Decimal("0")}) == "$0.00"


def test_large_number_with_commas():
    assert render("{{ v|money }}", {"v": Decimal("1234567.89")}) == "$1,234,567.89"


def test_none_returns_em_dash():
    assert render("{{ v|money }}", {"v": None}) == "—"


def test_float_input():
    assert render("{{ v|money }}", {"v": 1234.5}) == "$1,234.50"


def test_int_input():
    assert render("{{ v|money }}", {"v": 100}) == "$100.00"


def test_string_numeric_input():
    assert render("{{ v|money }}", {"v": "42.7"}) == "$42.70"


def test_garbage_string_returns_em_dash():
    assert render("{{ v|money }}", {"v": "not a number"}) == "—"


def test_signed_kwarg_shows_plus_for_positive():
    """`{{ v|money:'signed' }}` prefixes positives with + (useful for gain/loss)."""
    assert render("{{ v|money:'signed' }}", {"v": Decimal("523.10")}) == "+$523.10"


def test_signed_kwarg_keeps_minus_for_negative():
    assert render("{{ v|money:'signed' }}", {"v": Decimal("-523.10")}) == "−$523.10"


def test_liability_mode_prefixes_minus_on_positive():
    """Liabilities stored as positive Decimals render with a minus sign."""
    assert render("{{ v|money:'liability' }}", {"v": Decimal("1500")}) == "−$1,500.00"


def test_liability_mode_minus_on_zero_too():
    """Even zero gets a minus in liability mode (consistent rendering for empty liability rows)."""
    assert render("{{ v|money:'liability' }}", {"v": Decimal("0")}) == "−$0.00"
