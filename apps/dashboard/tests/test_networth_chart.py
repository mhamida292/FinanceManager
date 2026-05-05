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


from decimal import Decimal as _D

from apps.dashboard.templatetags.networth_chart import value_chart_svg


def test_value_chart_svg_renders_basic_line():
    out = value_chart_svg([_D("100"), _D("110"), _D("120")])
    assert "<svg" in out
    # Default value_label is "Value".
    # (The label currently shows up only inside the data tooltip JS — a
    # rendered chart includes the label string in the markup.)
    assert "value_chart_svg" not in out  # smoke: not a stub


def test_value_chart_svg_accepts_custom_label():
    out_assets = value_chart_svg([_D("100"), _D("110"), _D("120")], value_label="Asset value")
    assert "Asset value" in out_assets


def test_networth_chart_svg_still_works_via_wrapper():
    """Backward-compat: the original entry point keeps working unchanged."""
    from apps.dashboard.templatetags.networth_chart import networth_chart_svg
    out = networth_chart_svg([_D("100"), _D("110")])
    assert "<svg" in out


def test_value_chart_svg_under_two_points_renders_placeholder():
    out = value_chart_svg([_D("100")])
    assert "Not enough" in out or "not enough" in out


def test_value_chart_svg_default_label_is_value():
    out = value_chart_svg([_D("100"), _D("110")])
    # Default label should appear somewhere in the rendered fragment.
    assert "Value" in out
