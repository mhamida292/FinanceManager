import math
from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

from apps.banking.categories import CATEGORY_COLORS, CATEGORY_LABELS

register = template.Library()


def category_pie_svg(rows, size: int = 160) -> str:
    """Render an SVG donut/pie from a list of CategoryTotal rows.
    Returns '—' for empty input."""
    if not rows:
        return "—"

    total = sum((r.total for r in rows), Decimal("0"))
    if total <= 0:
        return "—"

    cx = cy = size / 2
    r = size / 2 - 2

    if len(rows) == 1:
        only = rows[0]
        return mark_safe(
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{only.color}">'
            f'<title>{only.label} · ${only.total:,.2f}</title>'
            f'</circle>'
            f'</svg>'
        )

    parts = [
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    ]
    angle = -math.pi / 2  # start at 12 o'clock
    for row in rows:
        slice_angle = float(row.total / total) * 2 * math.pi
        x1 = cx + r * math.cos(angle)
        y1 = cy + r * math.sin(angle)
        end_angle = angle + slice_angle
        x2 = cx + r * math.cos(end_angle)
        y2 = cy + r * math.sin(end_angle)
        large_arc = 1 if slice_angle > math.pi else 0
        d = f"M {cx} {cy} L {x1:.3f} {y1:.3f} A {r} {r} 0 {large_arc} 1 {x2:.3f} {y2:.3f} Z"
        parts.append(
            f'<path d="{d}" fill="{row.color}">'
            f'<title>{row.label} · ${row.total:,.2f}</title>'
            f'</path>'
        )
        angle = end_angle
    parts.append('</svg>')
    return mark_safe("".join(parts))


def category_pill_html(category: str) -> str:
    """Render a colored pill for a category key."""
    color = CATEGORY_COLORS.get(category, "#888888")
    label = CATEGORY_LABELS.get(category, category.title())
    return mark_safe(
        f'<span class="category-pill" style="background-color: {color}22; color: {color}; '
        f'padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500;">'
        f'{label}</span>'
    )


@register.simple_tag
def category_pie(rows, size=160):
    return category_pie_svg(rows, size=int(size))


@register.simple_tag
def category_pill(category):
    return category_pill_html(category)
