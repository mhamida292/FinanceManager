from decimal import Decimal

from apps.banking.services import CategoryTotal
from apps.banking.templatetags.category_tags import category_pie_svg, category_pill_html


def _row(cat, total, color="#888"):
    return CategoryTotal(category=cat, label=cat.title(), color=color,
                         total=Decimal(str(total)), percent=0.0)


def test_pie_svg_with_single_slice_returns_full_circle():
    rows = [_row("groceries", 100, "#7a9a6a")]
    svg = category_pie_svg(rows, size=160)
    assert svg.startswith("<svg")
    assert "fill=\"#7a9a6a\"" in svg
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
