import math
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


def networth_chart_svg(values: Iterable[Decimal], days: int = 30, width: int = 600, height: int = 200, end_date: date | None = None) -> str:
    """Render a polished line chart for net-worth history.
    `values` is a list of Decimals, most-recent last.
    `days` is the length of the window (default 30).
    `end_date` is the last day shown (default today).
    Returns an HTML/SVG fragment with inline JS for hover interactivity.
    """
    values = list(values)
    if len(values) < 2:
        return mark_safe(
            f'<div style="width: 100%; height: {height}px; display: flex; '
            f'align-items: center; justify-content: center; color: var(--muted, #888); '
            f'font-size: 12px;">Not enough data yet — keep syncing.</div>'
        )

    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=len(values) - 1)

    nums = [float(v) for v in values]
    lo, hi = min(nums), max(nums)
    span = hi - lo if hi > lo else max(abs(hi), 1.0)  # avoid zero division on flat series

    pad_x_left = 60   # room for Y-axis labels
    pad_x_right = 16
    pad_y_top = 16
    pad_y_bot = 32   # room for X-axis labels
    inner_w = width - pad_x_left - pad_x_right
    inner_h = height - pad_y_top - pad_y_bot

    # Build the polyline points and the area-fill path.
    step = inner_w / (len(nums) - 1)
    points = []
    for i, n in enumerate(nums):
        x = pad_x_left + i * step
        # Invert y because SVG origin is top-left.
        y = pad_y_top + inner_h - ((n - lo) / span if span else 0.5) * inner_h
        points.append((x, y))

    line_d = "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in points)
    # Area fill: down to the bottom of the chart, then back along the bottom.
    area_d = (
        line_d
        + f" L{points[-1][0]:.2f},{pad_y_top + inner_h:.2f}"
        + f" L{points[0][0]:.2f},{pad_y_top + inner_h:.2f} Z"
    )

    # Format helpers — values are dollars; show as $X,XXX.XX
    def fmt_dollars(v: float) -> str:
        return f"${v:,.0f}" if abs(v) >= 1000 else f"${v:,.2f}"

    # On Windows the %-d directive isn't supported. Fall back to manual format.
    try:
        start_label = start_date.strftime("%b %-d")
        end_label = end_date.strftime("%b %-d")
    except (TypeError, ValueError):
        start_label = f"{start_date.strftime('%b')} {start_date.day}"
        end_label = f"{end_date.strftime('%b')} {end_date.day}"

    scope = uuid.uuid4().hex[:8]
    container_id = f"nw-{scope}"

    # Build the SVG. Inline CSS scoped via class. JS at bottom hooks hover.
    parts = []
    parts.append(
        f'<div id="{container_id}" class="nw-chart-wrap" style="position: relative; width: 100%;">'
    )
    parts.append(
        f'<svg class="nw-chart nw-chart-{scope}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'style="width: 100%; height: {height}px; display: block;" '
        f'xmlns="http://www.w3.org/2000/svg">'
    )

    # Gradient definition for the area fill.
    parts.append(
        f'<defs>'
        f'<linearGradient id="nw-grad-{scope}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="var(--accent-positive, #88a877)" stop-opacity="0.35"/>'
        f'<stop offset="100%" stop-color="var(--accent-positive, #88a877)" stop-opacity="0"/>'
        f'</linearGradient>'
        f'</defs>'
    )

    # Y-axis labels (min and max).
    parts.append(
        f'<text x="{pad_x_left - 8}" y="{pad_y_top + 4}" text-anchor="end" '
        f'style="font-size: 10px; fill: var(--muted, #888); font-family: var(--mono, ui-monospace, monospace);">'
        f'{fmt_dollars(hi)}</text>'
    )
    parts.append(
        f'<text x="{pad_x_left - 8}" y="{pad_y_top + inner_h + 4}" text-anchor="end" '
        f'style="font-size: 10px; fill: var(--muted, #888); font-family: var(--mono, ui-monospace, monospace);">'
        f'{fmt_dollars(lo)}</text>'
    )

    # X-axis labels.
    parts.append(
        f'<text x="{pad_x_left}" y="{height - 8}" text-anchor="start" '
        f'style="font-size: 10px; fill: var(--muted, #888);">{start_label}</text>'
    )
    parts.append(
        f'<text x="{pad_x_left + inner_w}" y="{height - 8}" text-anchor="end" '
        f'style="font-size: 10px; fill: var(--muted, #888);">{end_label}</text>'
    )

    # Subtle horizontal grid line at midpoint.
    mid_y = pad_y_top + inner_h / 2
    parts.append(
        f'<line x1="{pad_x_left}" y1="{mid_y:.2f}" x2="{pad_x_left + inner_w}" y2="{mid_y:.2f}" '
        f'stroke="var(--border, #333)" stroke-width="1" stroke-dasharray="2,3" opacity="0.4"/>'
    )

    # Area fill.
    parts.append(
        f'<path d="{area_d}" fill="url(#nw-grad-{scope})" stroke="none"/>'
    )

    # Line.
    parts.append(
        f'<path d="{line_d}" fill="none" stroke="var(--accent-positive, #88a877)" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'style="filter: drop-shadow(0 1px 2px rgba(0,0,0,0.2));"/>'
    )

    # Hover guide line (hidden by default).
    parts.append(
        f'<line class="nw-guide" x1="0" y1="{pad_y_top}" x2="0" y2="{pad_y_top + inner_h}" '
        f'stroke="var(--accent-positive, #88a877)" stroke-width="1" stroke-dasharray="3,3" '
        f'style="display: none; pointer-events: none;"/>'
    )
    parts.append(
        f'<circle class="nw-dot" cx="0" cy="0" r="4" fill="var(--accent-positive, #88a877)" '
        f'stroke="var(--surface, #1a1a1a)" stroke-width="2" '
        f'style="display: none; pointer-events: none;"/>'
    )

    # Invisible overlay for capturing mouse events across the chart area.
    parts.append(
        f'<rect class="nw-hit" x="{pad_x_left}" y="{pad_y_top}" '
        f'width="{inner_w}" height="{inner_h}" fill="transparent" style="cursor: crosshair;"/>'
    )

    parts.append('</svg>')

    # Tooltip element (HTML, positioned absolutely).
    parts.append(
        f'<div class="nw-tooltip" style="position: absolute; display: none; '
        f'background: var(--surface, #161616); border: 1px solid var(--border, #333); '
        f'border-radius: 4px; padding: 6px 10px; font-size: 11px; '
        f'pointer-events: none; box-shadow: 0 4px 12px rgba(0,0,0,0.3); white-space: nowrap;">'
        f'<div class="nw-tt-date" style="color: var(--muted, #888); font-size: 10px; margin-bottom: 2px;"></div>'
        f'<div class="nw-tt-value" style="color: var(--accent-positive, #88a877); font-weight: 600;"></div>'
        f'</div>'
    )

    # Build a JS data array of [date, value] pairs.
    data_js = "[" + ",".join(
        f'["{(start_date + timedelta(days=i)).strftime("%b %d, %Y")}",{nums[i]:.2f}]'
        for i in range(len(nums))
    ) + "]"

    # Hover JS.
    parts.append(
        f'<script>'
        f'(function() {{'
        f'  const root = document.getElementById("{container_id}");'
        f'  if (!root) return;'
        f'  const svg = root.querySelector("svg");'
        f'  const guide = root.querySelector(".nw-guide");'
        f'  const dot = root.querySelector(".nw-dot");'
        f'  const hit = root.querySelector(".nw-hit");'
        f'  const tooltip = root.querySelector(".nw-tooltip");'
        f'  const ttDate = root.querySelector(".nw-tt-date");'
        f'  const ttValue = root.querySelector(".nw-tt-value");'
        f'  const data = {data_js};'
        f'  const padL = {pad_x_left};'
        f'  const padT = {pad_y_top};'
        f'  const padB = {pad_y_bot};'
        f'  const innerW = {inner_w};'
        f'  const innerH = {inner_h};'
        f'  const lo = {lo};'
        f'  const hi = {hi};'
        f'  const span = {span};'
        f'  function nearestIndex(svgX) {{'
        f'    const rel = svgX - padL;'
        f'    const i = Math.round((rel / innerW) * (data.length - 1));'
        f'    return Math.max(0, Math.min(data.length - 1, i));'
        f'  }}'
        f'  function moveHandler(e) {{'
        f'    const rect = svg.getBoundingClientRect();'
        f'    const sx = (e.clientX - rect.left) * ({width} / rect.width);'
        f'    const idx = nearestIndex(sx);'
        f'    const px = padL + (idx / (data.length - 1)) * innerW;'
        f'    const v = data[idx][1];'
        f'    const py = padT + innerH - ((v - lo) / (span || 1)) * innerH;'
        f'    guide.setAttribute("x1", px);'
        f'    guide.setAttribute("x2", px);'
        f'    guide.style.display = "";'
        f'    dot.setAttribute("cx", px);'
        f'    dot.setAttribute("cy", py);'
        f'    dot.style.display = "";'
        f'    ttDate.textContent = data[idx][0];'
        f'    ttValue.textContent = "$" + v.toLocaleString("en-US", {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});'
        f'    const ttLeft = (px / {width}) * rect.width;'
        f'    tooltip.style.display = "";'
        f'    tooltip.style.left = (ttLeft + 12) + "px";'
        f'    tooltip.style.top = (e.clientY - rect.top - 30) + "px";'
        f'  }}'
        f'  function leaveHandler() {{'
        f'    guide.style.display = "none";'
        f'    dot.style.display = "none";'
        f'    tooltip.style.display = "none";'
        f'  }}'
        f'  hit.addEventListener("mousemove", moveHandler);'
        f'  hit.addEventListener("mouseleave", leaveHandler);'
        f'}})();'
        f'</script>'
    )
    parts.append('</div>')
    return mark_safe("".join(parts))


@register.simple_tag
def networth_chart(values, days=30):
    return networth_chart_svg(values, days=int(days))
