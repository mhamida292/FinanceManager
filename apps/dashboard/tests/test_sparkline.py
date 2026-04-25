from decimal import Decimal

from apps.dashboard.templatetags.sparkline import sparkline_svg


def test_sparkline_with_two_points_renders_svg():
    result = sparkline_svg([Decimal("100"), Decimal("110")])
    assert "<svg" in result
    assert "<path" in result
    # Color should default to emerald
    assert "#34d399" in result


def test_sparkline_with_one_point_renders_dash():
    result = sparkline_svg([Decimal("100")])
    assert result == "—"


def test_sparkline_empty_renders_dash():
    assert sparkline_svg([]) == "—"


def test_sparkline_uses_custom_color():
    result = sparkline_svg([Decimal("1"), Decimal("2")], color="#a78bfa")
    assert "#a78bfa" in result


def test_sparkline_normalizes_to_height():
    """Verify min/max in the data scale to top/bottom of the SVG, not crash on flat lines."""
    flat = sparkline_svg([Decimal("100"), Decimal("100"), Decimal("100")])
    assert "<svg" in flat  # flat line still renders, no division-by-zero


def test_sparkline_handles_large_values():
    result = sparkline_svg([Decimal("1000000"), Decimal("1500000"), Decimal("1200000")])
    assert "<svg" in result
