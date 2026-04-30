from decimal import Decimal

from apps.banking.services import CategoryTotal
from apps.banking.templatetags.category_tags import category_pie_svg, category_pill_html


def _row(cat, total, color="#888"):
    return CategoryTotal(category=cat, label=cat.title(), color=color,
                         total=Decimal(str(total)), percent=0.0)


def test_pie_svg_with_single_slice_returns_full_circle():
    rows = [_row("groceries", 100, "#7a9a6a")]
    svg = category_pie_svg(rows, size=160)
    assert svg.startswith("<div") or svg.startswith("<svg")
    # Single-slice donut: circle with stroke (not fill) using the slice color.
    assert "#7a9a6a" in svg
    assert 'width="160"' in svg


def test_pie_svg_with_no_rows_returns_dash():
    assert category_pie_svg([], size=160) == "—"


def test_pie_svg_with_multiple_slices_renders_each_color():
    rows = [_row("a", 50, "#aaaaaa"), _row("b", 50, "#bbbbbb")]
    svg = category_pie_svg(rows, size=120)
    assert "#aaaaaa" in svg
    assert "#bbbbbb" in svg


def test_category_pill_html_uses_color_and_label():
    html = category_pill_html("groceries")
    assert "Groceries" in html
    assert "#7a9a6a" in html or "rgb" in html


def test_pie_svg_each_slice_has_data_attrs_for_hover():
    rows = [_row("groceries", 258, "#7a9a6a"), _row("dining", 285, "#c08868")]
    svg = category_pie_svg(rows, size=160)
    # Each slice has data-label, data-total, data-percent for the JS hover handler.
    assert 'data-label="Groceries"' in svg
    assert 'data-label="Dining"' in svg
    assert 'data-total="258"' in svg or 'data-total="258.00"' in svg
    assert 'data-percent="' in svg


def test_pie_svg_single_slice_also_has_data_attrs():
    rows = [_row("groceries", 100, "#7a9a6a")]
    svg = category_pie_svg(rows, size=160)
    assert 'data-label="Groceries"' in svg
    assert 'data-percent="100"' in svg


def test_pie_svg_is_donut_with_inner_circle():
    rows = [_row("groceries", 100, "#7a9a6a"), _row("dining", 50, "#c08868")]
    svg = category_pie_svg(rows, size=200)
    # The donut should produce ring segments — paths should contain TWO arc commands.
    # Count the 'A' arc commands in the path data (space-padded to avoid false matches).
    assert svg.count(" A ") >= 2  # at least one outer + one inner arc per slice means 2 arcs minimum


def test_pie_svg_has_empty_center_text_by_default():
    rows = [_row("groceries", 100, "#7a9a6a"), _row("dining", 200, "#c08868")]
    svg = category_pie_svg(rows, size=200)
    # Center text elements exist for the JS hover handler to populate.
    assert "center-label-title" in svg
    assert "center-label-amount" in svg
    # But by default, no total text is rendered (it appears only on hover via JS).
    assert "TOTAL" not in svg
    assert "$300" not in svg


def test_pie_svg_has_data_attributes_for_hover():
    rows = [_row("groceries", 100, "#7a9a6a")]
    svg = category_pie_svg(rows, size=200)
    # Each slice path should have data-label and data-total for the JS hover handler.
    assert "data-label=" in svg or "data-category=" in svg
