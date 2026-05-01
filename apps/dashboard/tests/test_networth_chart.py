from decimal import Decimal

from apps.dashboard.templatetags.networth_chart import networth_chart_svg


def test_networth_chart_with_data_renders_svg():
    values = [Decimal(str(v)) for v in [100, 110, 105, 115, 120]]
    out = networth_chart_svg(values)
    assert "<svg" in out
    assert "<path" in out
    # Tooltip element present.
    assert "nw-tooltip" in out
    # JS hover handler present.
    assert "mousemove" in out


def test_networth_chart_includes_min_max_labels():
    values = [Decimal("100.00"), Decimal("250.00"), Decimal("175.00")]
    out = networth_chart_svg(values)
    # Y-axis labels: min and max should appear.
    assert "$250" in out
    assert "$100" in out


def test_networth_chart_with_too_few_points_renders_placeholder():
    out = networth_chart_svg([Decimal("100")])
    assert "Not enough data" in out


def test_networth_chart_with_empty_renders_placeholder():
    out = networth_chart_svg([])
    assert "Not enough data" in out


def test_networth_chart_with_flat_data_does_not_divide_by_zero():
    """When all values are identical, the chart still renders."""
    values = [Decimal("100")] * 10
    out = networth_chart_svg(values)
    assert "<svg" in out  # didn't crash
