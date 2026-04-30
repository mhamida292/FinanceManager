import math
import uuid
from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

from apps.banking.categories import CATEGORY_COLORS, CATEGORY_LABELS

register = template.Library()


def _ring_path(cx, cy, r_outer, r_inner, start_angle, end_angle):
    """Return SVG path 'd' attribute for a ring segment between two angles (radians)."""
    x1_o = cx + r_outer * math.cos(start_angle)
    y1_o = cy + r_outer * math.sin(start_angle)
    x2_o = cx + r_outer * math.cos(end_angle)
    y2_o = cy + r_outer * math.sin(end_angle)
    x1_i = cx + r_inner * math.cos(start_angle)
    y1_i = cy + r_inner * math.sin(start_angle)
    x2_i = cx + r_inner * math.cos(end_angle)
    y2_i = cy + r_inner * math.sin(end_angle)
    sweep_angle = end_angle - start_angle
    large_arc = 1 if sweep_angle > math.pi else 0
    return (
        f"M {x1_o:.3f} {y1_o:.3f} "
        f"A {r_outer} {r_outer} 0 {large_arc} 1 {x2_o:.3f} {y2_o:.3f} "
        f"L {x2_i:.3f} {y2_i:.3f} "
        f"A {r_inner} {r_inner} 0 {large_arc} 0 {x1_i:.3f} {y1_i:.3f} "
        f"Z"
    )


def category_pie_svg(rows, size: int = 160) -> str:
    """Render an interactive donut pie from a list of CategoryTotal rows.
    Returns '—' for empty input."""
    if not rows:
        return "—"

    total = sum((r.total for r in rows), Decimal("0"))
    if total <= 0:
        return "—"

    cx = cy = size / 2
    r_outer = size / 2 - 4
    r_inner = r_outer * 0.6
    scope = uuid.uuid4().hex[:8]
    container_id = f"pie-{scope}"

    # Center label fonts scale with size but are capped to stay within the donut hole.
    title_font = max(min(int(size * 0.06), 12), 10)
    amount_font = max(min(int(size * 0.10), 18), 13)

    parts = [
        f'<div id="{container_id}" class="cat-pie-wrap" style="position: relative; display: inline-block;">'
    ]
    parts.append(
        f'<svg class="cat-pie cat-pie-{scope}" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" '
        f'style="overflow: visible; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.15));">'
    )

    # Inline scoped CSS for hover.
    parts.append(
        f'<style>'
        f'.cat-pie-{scope} .slice {{ transition: transform 0.15s ease, filter 0.15s ease; '
        f'transform-origin: {cx}px {cy}px; cursor: pointer; }}'
        f'.cat-pie-{scope} .slice:hover {{ transform: scale(1.04); filter: brightness(1.15); }}'
        f'.cat-pie-{scope} .center-label {{ pointer-events: none; user-select: none; }}'
        f'</style>'
    )

    # Single-slice case: full donut ring drawn as one circle with a wide stroke.
    if len(rows) == 1:
        only = rows[0]
        ring_thickness = r_outer - r_inner
        ring_radius = (r_outer + r_inner) / 2
        parts.append(
            f'<circle class="slice" cx="{cx}" cy="{cy}" r="{ring_radius}" '
            f'fill="none" stroke="{only.color}" stroke-width="{ring_thickness}" '
            f'data-label="{only.label}" data-total="{only.total}" data-percent="100"/>'
        )
    else:
        angle = -math.pi / 2  # start at 12 o'clock
        for row in rows:
            slice_angle = float(row.total / total) * 2 * math.pi
            end_angle = angle + slice_angle
            d = _ring_path(cx, cy, r_outer, r_inner, angle, end_angle)
            percent = float(row.total / total) * 100
            parts.append(
                f'<path class="slice" d="{d}" fill="{row.color}" '
                f'data-label="{row.label}" data-total="{row.total}" data-percent="{percent:.1f}"/>'
            )
            angle = end_angle

    # Center label (three stacked text lines; title/amount show defaults, percent empty until hover).
    parts.append(
        f'<text class="center-label center-label-title" x="{cx}" y="{cy - amount_font * 0.7}" '
        f'text-anchor="middle" dominant-baseline="middle" '
        f'style="font-size: {title_font}px; fill: var(--muted, #888); '
        f'text-transform: uppercase; letter-spacing: 0.5px;">Total</text>'
    )
    parts.append(
        f'<text class="center-label center-label-amount" x="{cx}" y="{cy + amount_font * 0.15}" '
        f'text-anchor="middle" dominant-baseline="middle" '
        f'style="font-size: {amount_font}px; font-weight: 600; fill: var(--text, #ddd);">'
        f'${total:,.2f}</text>'
    )
    parts.append(
        f'<text class="center-label center-label-percent" x="{cx}" y="{cy + amount_font * 0.95}" '
        f'text-anchor="middle" dominant-baseline="middle" '
        f'style="font-size: {title_font}px; fill: var(--muted, #888);"></text>'
    )

    parts.append('</svg>')

    # Hover JS — attached scoped via container ID.
    parts.append(
        f'<script>'
        f'(function() {{'
        f'  const root = document.getElementById("{container_id}");'
        f'  if (!root) return;'
        f'  const title = root.querySelector(".center-label-title");'
        f'  const amount = root.querySelector(".center-label-amount");'
        f'  const percent = root.querySelector(".center-label-percent");'
        f'  const slices = root.querySelectorAll(".slice");'
        f'  const defaultTitle = "Total";'
        f'  const defaultAmount = "${total:,.2f}";'
        f'  slices.forEach(s => {{'
        f'    s.addEventListener("mouseenter", () => {{'
        f'      title.textContent = s.getAttribute("data-label");'
        f'      amount.textContent = "$" + parseFloat(s.getAttribute("data-total")).toLocaleString("en-US", {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});'
        f'      percent.textContent = s.getAttribute("data-percent") + "%";'
        f'    }});'
        f'    s.addEventListener("mouseleave", () => {{'
        f'      title.textContent = defaultTitle;'
        f'      amount.textContent = defaultAmount;'
        f'      percent.textContent = "";'
        f'    }});'
        f'  }});'
        f'}})();'
        f'</script>'
    )
    parts.append('</div>')
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
