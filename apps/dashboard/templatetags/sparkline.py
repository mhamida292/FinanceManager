from decimal import Decimal
from typing import Iterable

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

DEFAULT_COLOR = "#34d399"  # emerald-400
WIDTH = 100
HEIGHT = 24
PADDING = 2  # leave a little room so the stroke doesn't clip at the edges


def sparkline_svg(values: Iterable[Decimal], color: str = DEFAULT_COLOR) -> str:
    """Render an inline SVG sparkline from a list of values.

    Returns ``"—"`` if fewer than 2 values (can't draw a line with one point).
    """
    values = list(values)
    if len(values) < 2:
        return "—"

    nums = [float(v) for v in values]
    lo, hi = min(nums), max(nums)
    span = hi - lo or 1.0  # avoid division by zero on flat series

    inner_w = WIDTH - 2 * PADDING
    inner_h = HEIGHT - 2 * PADDING
    step = inner_w / (len(nums) - 1)

    points = []
    for i, n in enumerate(nums):
        x = PADDING + i * step
        # Invert y because SVG origin is top-left
        y = PADDING + inner_h - ((n - lo) / span) * inner_h
        points.append(f"{x:.2f},{y:.2f}")

    path_d = "M" + " L".join(points)
    svg = (
        f'<svg width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="none">'
        f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )
    return svg


@register.simple_tag
def sparkline(values, color: str = DEFAULT_COLOR):
    return mark_safe(sparkline_svg(values, color))
