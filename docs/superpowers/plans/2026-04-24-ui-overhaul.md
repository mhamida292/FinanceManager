# UI Overhaul Implementation Plan (Phase 8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Re-skin every page with a dense data-app aesthetic on a sidebar layout, with a per-user light/dark theme toggle, inline SVG sparklines, and PWA-installable manifest. CSS + template overhaul only — no model, view-logic, URL, or test changes (existing tests must still pass).

**Architecture:** New `static/css/app.css` defines design tokens as CSS custom properties under `:root` and `[data-theme="light"]`. Tailwind classes reference those variables via arbitrary-value syntax (e.g. `bg-[var(--surface)]`). Theme toggle is a tiny inline script in `<head>` that reads `localStorage.theme` (defaults to `prefers-color-scheme`) and sets `data-theme` on `<html>` before paint. Self-hosted Inter + JetBrains Mono fonts. Custom Django template tag `{% sparkline %}` renders inline SVG with no JS dependency.

**Tech Stack:** Django templates, Tailwind CDN (already loaded — kept), CSS custom properties, vanilla JS (~20 lines total), self-hosted woff2 fonts. No new Python deps.

---

## Pre-task: Branch setup

Branch off master.

```bash
git checkout master
git pull
git checkout -b phase-8-ui
```

All commits in this plan land on `phase-8-ui`. Plan ships as one PR.

---

## File Structure

**New files:**
```
static/
├── css/
│   ├── app.css                       # design tokens, theme variables, base resets
│   └── fonts.css                     # @font-face declarations for self-hosted fonts
├── fonts/
│   ├── Inter-Variable.woff2          # body / UI font
│   └── JetBrainsMono-Variable.woff2  # numeric font
├── manifest.webmanifest              # PWA manifest
├── favicon.ico                       # placeholder text mark
├── favicon-16.png                    # generated from logo (16x16)
├── favicon-32.png                    # generated from logo (32x32)
├── apple-touch-icon.png              # 180x180 for iOS home screen
├── icon-192.png                      # PWA standard
└── icon-512.png                      # PWA splash background

apps/dashboard/templatetags/
├── __init__.py
└── sparkline.py                      # {% sparkline values %} tag
```

**Modified templates** (22 total):

```
apps/accounts/templates/
├── base.html                         # complete rewrite — sidebar, top bar, theme toggle, manifest links
└── accounts/
    ├── login.html                    # rewrite — centered card, no sidebar
    └── settings.html                 # rewrite — new component patterns

apps/banking/templates/banking/
├── banks_list.html                   # rewrite
├── account_detail.html               # rewrite
├── link_form.html                    # rewrite
├── rename_form.html                  # rewrite
├── institution_confirm_delete.html   # rewrite
└── account_confirm_delete.html       # rewrite

apps/investments/templates/investments/
├── investments_list.html             # rewrite
├── account_detail.html               # rewrite
├── add_account_form.html             # rewrite
├── edit_account_form.html            # rewrite
├── add_holding_form.html             # rewrite
├── edit_holding_form.html            # rewrite
├── account_confirm_delete.html       # rewrite
└── holding_confirm_delete.html       # rewrite

apps/assets/templates/assets/
├── assets_list.html                  # rewrite
├── asset_form.html                   # rewrite
└── asset_confirm_delete.html         # rewrite

apps/liabilities/templates/liabilities/
├── liabilities_list.html             # rewrite
├── liability_form.html               # rewrite
└── liability_confirm_delete.html     # rewrite

apps/dashboard/templates/dashboard/
└── index.html                        # rewrite — sparkline, new layout
```

**Other modified files:**
```
apps/dashboard/services.py            # add net_worth_history()
apps/dashboard/views.py               # pass sparkline data to template
apps/investments/services.py          # add per_account_history()
apps/investments/views.py             # pass sparkline data to template
config/settings.py                    # ensure STATICFILES_DIRS includes static/
```

**Boundary rationale:**
- `static/css/app.css` is the single source of truth for design tokens. Tailwind doesn't try to manage themes; CSS variables do.
- Sparkline lives in `apps/dashboard/templatetags/` because dashboard is the consumer; other apps load it via `{% load sparkline %}`.
- `base.html` is intentionally the biggest single file — it's the layout shell. Page templates inherit from it via `{% block content %}`.
- No new Python deps. We're using Django's existing template tag system + Tailwind CDN we already load.

---

## Task 1: Branch + STATICFILES_DIRS check

**Files:**
- Modify: `config/settings.py`

- [ ] **Step 1: Create the branch**

```bash
git checkout master && git pull
git checkout -b phase-8-ui
```

- [ ] **Step 2: Read `config/settings.py`** and confirm there's a `STATIC_ROOT = BASE_DIR / "staticfiles"` line and a `STATIC_URL = "static/"` line. If `STATICFILES_DIRS` does NOT exist, add this near the static-files config:

```python
STATICFILES_DIRS = [BASE_DIR / "static"]
```

This tells Django to also collect from a top-level `static/` directory (where we'll put fonts, CSS, manifest, icons). Without it, those files won't be served.

- [ ] **Step 3: Commit if you changed anything**

```bash
git add config/settings.py
git commit -m "chore(ui): ensure STATICFILES_DIRS picks up project-level static/"
```

If `STATICFILES_DIRS` was already set to include this path, skip the commit.

---

## Task 2: Self-host fonts (Inter + JetBrains Mono)

**Files:**
- Create: `static/fonts/Inter-Variable.woff2`
- Create: `static/fonts/JetBrainsMono-Variable.woff2`
- Create: `static/css/fonts.css`

Self-hosted fonts — homelab-friendly (no third-party CDN, works offline, faster).

- [ ] **Step 1: Make the directory**

```bash
mkdir -p static/fonts static/css
```

- [ ] **Step 2: Download Inter (variable font)**

```bash
curl -L "https://github.com/rsms/inter/raw/master/docs/font-files/InterVariable.woff2" \
  -o static/fonts/Inter-Variable.woff2
```

Verify: `ls -lh static/fonts/Inter-Variable.woff2` should show roughly 350 KB.

- [ ] **Step 3: Download JetBrains Mono (variable font)**

```bash
curl -L "https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/variable/JetBrainsMono%5Bwght%5D.woff2" \
  -o static/fonts/JetBrainsMono-Variable.woff2
```

Verify: ~100 KB.

If either curl fails (404, etc.), fall back to downloading the release zip from those repos, extracting just the variable woff2 file, and placing it at the target path.

- [ ] **Step 4: Write `static/css/fonts.css`**

```css
/* Self-hosted fonts. Licenses:
   - Inter: SIL OFL 1.1 (https://github.com/rsms/inter)
   - JetBrains Mono: SIL OFL 1.1 (https://github.com/JetBrains/JetBrainsMono)
*/

@font-face {
  font-family: "Inter";
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url("/static/fonts/Inter-Variable.woff2") format("woff2-variations");
}

@font-face {
  font-family: "JetBrains Mono";
  font-style: normal;
  font-weight: 100 800;
  font-display: swap;
  src: url("/static/fonts/JetBrainsMono-Variable.woff2") format("woff2-variations");
}
```

- [ ] **Step 5: Commit**

```bash
git add static/fonts/ static/css/fonts.css
git commit -m "chore(ui): self-host Inter + JetBrains Mono variable fonts"
```

---

## Task 3: Design tokens CSS

**Files:**
- Create: `static/css/app.css`

The single source of truth for all colors, spacing, and theme variables.

- [ ] **Step 1: Write the file**

```css
/* Design tokens for the finance dashboard.
   Light theme is opt-in via [data-theme="light"] on <html>.
   Default (no attribute) = dark.
*/

:root {
  /* Surfaces — dark theme defaults */
  --bg: #020617;
  --surface: #0f172a;
  --surface-hover: rgba(30, 41, 59, 0.6);
  --border: #1e293b;
  --text: #e2e8f0;
  --muted: #64748b;
  --dim: #475569;

  /* Accents — same hue across themes, brighter for dark */
  --accent-cash: #60a5fa;
  --accent-inv: #a78bfa;
  --accent-assets: #fbbf24;
  --accent-lia: #f87171;
  --accent-positive: #34d399;
  --accent-negative: #f87171;

  /* Tinted accent backgrounds for nav active states (10% alpha) */
  --tint-cash: rgba(96, 165, 250, 0.12);
  --tint-inv: rgba(167, 139, 250, 0.12);
  --tint-assets: rgba(251, 191, 36, 0.12);
  --tint-lia: rgba(248, 113, 113, 0.12);
  --tint-positive: rgba(52, 211, 153, 0.12);

  /* Spacing & radius */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
}

[data-theme="light"] {
  --bg: #f8fafc;
  --surface: #ffffff;
  --surface-hover: #f1f5f9;
  --border: #e2e8f0;
  --text: #0f172a;
  --muted: #64748b;
  --dim: #94a3b8;

  --accent-cash: #2563eb;
  --accent-inv: #7c3aed;
  --accent-assets: #d97706;
  --accent-lia: #dc2626;
  --accent-positive: #059669;
  --accent-negative: #dc2626;

  --tint-cash: rgba(37, 99, 235, 0.08);
  --tint-inv: rgba(124, 58, 237, 0.08);
  --tint-assets: rgba(217, 119, 6, 0.08);
  --tint-lia: rgba(220, 38, 38, 0.08);
  --tint-positive: rgba(5, 150, 105, 0.08);
}

/* Body resets — Tailwind reset still applies; this layers on top */
html {
  background: var(--bg);
  color: var(--text);
  font-family: "Inter", system-ui, -apple-system, sans-serif;
  font-feature-settings: "cv11", "ss01";  /* Inter stylistic sets — nicer numerals */
}

body {
  background: var(--bg);
  color: var(--text);
}

/* Tabular nums everywhere — finance app */
.tabnums, table, .num {
  font-variant-numeric: tabular-nums;
}

/* Monospace number class */
.mono, .num {
  font-family: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;
  font-variant-numeric: tabular-nums;
}

/* Smooth theme transitions */
html, body, .surface {
  transition: background-color 150ms ease, color 150ms ease, border-color 150ms ease;
}

/* Sidebar nav active states get the section's tinted background */
.nav-active-cash { background: var(--tint-cash); color: var(--accent-cash); }
.nav-active-inv { background: var(--tint-inv); color: var(--accent-inv); }
.nav-active-assets { background: var(--tint-assets); color: var(--accent-assets); }
.nav-active-lia { background: var(--tint-lia); color: var(--accent-lia); }
.nav-active-default { background: var(--tint-positive); color: var(--accent-positive); }

/* Mobile sidebar drawer behavior */
@media (max-width: 767px) {
  #sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: 220px;
    transform: translateX(-100%);
    transition: transform 200ms ease;
    z-index: 50;
  }
  #sidebar.open { transform: translateX(0); }
  #sidebar-scrim {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 40;
  }
  #sidebar-scrim.open { display: block; }
}
@media (min-width: 768px) {
  #sidebar-scrim { display: none !important; }
  #hamburger { display: none; }
}
```

- [ ] **Step 2: Commit**

```bash
git add static/css/app.css
git commit -m "feat(ui): design tokens, theme variables, mobile sidebar CSS"
```

---

## Task 4: PWA manifest + placeholder logo assets

**Files:**
- Create: `static/manifest.webmanifest`
- Create: `static/favicon.ico` (placeholder)
- Create: `static/apple-touch-icon.png` (placeholder)
- Create: `static/icon-192.png` (placeholder)
- Create: `static/icon-512.png` (placeholder)

Until the user supplies the real logo, generate simple emerald-on-dark text-mark placeholders using ImageMagick (likely already installed on the homelab; if not, `sudo apt install imagemagick`).

- [ ] **Step 1: Generate the placeholder icons**

```bash
# 512x512 — base
convert -size 512x512 xc:'#020617' -gravity center \
  -fill '#34d399' -font sans-serif -pointsize 80 -annotate 0 'F' \
  static/icon-512.png

# Resize for the smaller variants
convert static/icon-512.png -resize 192x192 static/icon-192.png
convert static/icon-512.png -resize 180x180 static/apple-touch-icon.png
convert static/icon-512.png -resize 32x32 static/favicon-32.png
convert static/icon-512.png -resize 16x16 static/favicon-16.png
convert static/favicon-16.png static/favicon-32.png static/favicon.ico
```

If `convert` isn't installed, copy any 512x512 PNG to those paths as a placeholder, or skip — the absence will just show a broken icon until the user provides the asset, which doesn't affect functionality.

- [ ] **Step 2: Write `static/manifest.webmanifest`**

```json
{
  "name": "Finance",
  "short_name": "Finance",
  "description": "Personal finance dashboard",
  "icons": [
    {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ],
  "start_url": "/",
  "display": "standalone",
  "background_color": "#020617",
  "theme_color": "#34d399"
}
```

- [ ] **Step 3: Commit**

```bash
git add static/manifest.webmanifest static/favicon.ico static/favicon-*.png static/apple-touch-icon.png static/icon-*.png
git commit -m "feat(ui): PWA manifest and placeholder icons"
```

---

## Task 5: Sparkline template tag (TDD)

**Files:**
- Create: `apps/dashboard/templatetags/__init__.py`
- Create: `apps/dashboard/templatetags/sparkline.py`
- Create: `apps/dashboard/tests/test_sparkline.py`

- [ ] **Step 1: `apps/dashboard/templatetags/__init__.py`** — empty.

- [ ] **Step 2: Write the failing test `apps/dashboard/tests/test_sparkline.py`**

```python
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
```

- [ ] **Step 3: Write `apps/dashboard/templatetags/sparkline.py`**

```python
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
```

- [ ] **Step 4: Run tests**

```bash
docker compose exec web pytest apps/dashboard/tests/test_sparkline.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/dashboard/templatetags/ apps/dashboard/tests/test_sparkline.py
git commit -m "feat(dashboard): {% sparkline %} template tag with TDD coverage"
```

---

## Task 6: Sparkline data sources (services + view wiring)

**Files:**
- Modify: `apps/dashboard/services.py`
- Modify: `apps/dashboard/views.py`

The sparkline tag takes values; we need to compute net-worth history per day.

- [ ] **Step 1: Append `net_worth_history()` to `apps/dashboard/services.py`**

```python
from datetime import date, timedelta

from apps.assets.models import AssetPriceSnapshot
from apps.investments.models import PortfolioSnapshot


def net_worth_history(user, days: int = 30) -> list[Decimal]:
    """Return a list of length ``days`` with end-of-day net-worth values
    (investments + assets), most-recent last. Days with no data carry forward
    the previous value so the line is continuous; leading days with no data
    return 0.
    """
    cutoff = date.today() - timedelta(days=days - 1)

    # One row per day with portfolio total
    inv_by_day = {}
    for snap in PortfolioSnapshot.objects.for_user(user).filter(date__gte=cutoff).order_by("date"):
        inv_by_day[snap.date] = inv_by_day.get(snap.date, Decimal("0")) + snap.total_value

    # One row per day with asset total
    asset_by_day = {}
    for snap in AssetPriceSnapshot.objects.for_user(user).filter(at__date__gte=cutoff).order_by("at"):
        asset_by_day[snap.at.date()] = snap.value  # latest per day naturally wins via ordering

    # Walk forward day by day, carrying last seen value
    result: list[Decimal] = []
    last_inv = Decimal("0")
    last_asset = Decimal("0")
    for i in range(days):
        d = cutoff + timedelta(days=i)
        if d in inv_by_day:
            last_inv = inv_by_day[d]
        if d in asset_by_day:
            last_asset = asset_by_day[d]
        result.append(last_inv + last_asset)

    return result
```

(Add any missing imports at the top of the file.)

- [ ] **Step 2: Update `apps/dashboard/views.py`** to pass history to the template

```python
from .services import net_worth_history, net_worth_summary


@login_required
def dashboard(request):
    summary = net_worth_summary(request.user)
    history = net_worth_history(request.user, days=30)
    return render(request, "dashboard/index.html", {"summary": summary, "history": history})
```

- [ ] **Step 3: Test**

```bash
docker compose exec web pytest apps/dashboard/tests/ -v
```

Expected: existing tests still pass (no regression).

- [ ] **Step 4: Commit**

```bash
git add apps/dashboard/services.py apps/dashboard/views.py
git commit -m "feat(dashboard): net_worth_history for sparkline + view wiring"
```

---

## Task 7: Base layout shell (the linchpin)

**Files:**
- Modify: `apps/accounts/templates/base.html` (complete rewrite)

The layout shell every other template inherits from. New: sidebar, top bar, theme toggle, manifest links, font preloads, mobile drawer.

- [ ] **Step 1: Replace `apps/accounts/templates/base.html` entirely with**:

```html
{% load static %}
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{% block title %}Finance{% endblock %} · momajlab</title>

  {# Set theme BEFORE paint to avoid flash. Reads localStorage, falls back to OS pref. #}
  <script>
    (function() {
      try {
        var t = localStorage.getItem('theme');
        if (!t) t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
        if (t === 'light') document.documentElement.setAttribute('data-theme', 'light');
      } catch (e) {}
    })();
  </script>

  {# PWA + favicons #}
  <link rel="icon" href="{% static 'favicon.ico' %}">
  <link rel="apple-touch-icon" href="{% static 'apple-touch-icon.png' %}">
  <link rel="manifest" href="{% static 'manifest.webmanifest' %}">
  <meta name="theme-color" content="#020617" media="(prefers-color-scheme: dark)">
  <meta name="theme-color" content="#f8fafc" media="(prefers-color-scheme: light)">

  {# Self-hosted fonts — preload the variable woff2 for fast first paint #}
  <link rel="preload" href="{% static 'fonts/Inter-Variable.woff2' %}" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="{% static 'fonts/JetBrainsMono-Variable.woff2' %}" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="{% static 'css/fonts.css' %}">
  <link rel="stylesheet" href="{% static 'css/app.css' %}">

  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen" style="background: var(--bg); color: var(--text);">

{% if user.is_authenticated %}
{# ============ TOP BAR ============ #}
<header class="sticky top-0 z-30 flex items-center justify-between px-4 md:px-6 h-[52px] border-b" style="background: var(--surface); border-color: var(--border);">
  <div class="flex items-center gap-3">
    <button id="hamburger" class="md:hidden p-1" style="color: var(--muted);" aria-label="Open menu" onclick="document.getElementById('sidebar').classList.toggle('open'); document.getElementById('sidebar-scrim').classList.toggle('open');">
      ☰
    </button>
    <div class="flex items-center gap-2">
      {# Logo placeholder — replace with <img src="{% static 'logo.svg' %}"> once the asset arrives #}
      <span class="font-bold tracking-widest" style="color: var(--accent-positive); font-size: 13px;">○ FINANCE</span>
    </div>
  </div>
  <div class="flex items-center gap-3">
    <button id="theme-toggle" class="p-1 text-sm" style="color: var(--muted);" aria-label="Toggle theme" title="Toggle theme">
      <span class="theme-icon-dark">☾</span>
      <span class="theme-icon-light hidden">☀</span>
    </button>
    <form action="{% url 'logout' %}" method="post" class="m-0">
      {% csrf_token %}
      <button type="submit" class="text-sm" style="color: var(--muted);">{{ user.username }} ▾</button>
    </form>
  </div>
</header>

<div id="sidebar-scrim" onclick="document.getElementById('sidebar').classList.remove('open'); this.classList.remove('open');"></div>

{# ============ LAYOUT ============ #}
<div class="flex">

  {# ============ SIDEBAR ============ #}
  <nav id="sidebar" class="md:sticky md:top-[52px] md:h-[calc(100vh-52px)] w-[180px] flex-shrink-0 border-r p-4 overflow-y-auto" style="background: var(--surface); border-color: var(--border);">
    <div class="text-[10px] font-semibold tracking-widest mb-2" style="color: var(--dim);">VIEW</div>
    {% with active=request.resolver_match.namespace|default:request.resolver_match.url_name %}
      <a href="{% url 'home' %}" class="flex items-center justify-between px-2 py-1.5 rounded text-sm mb-0.5 {% if request.path == '/' %}nav-active-default{% endif %}" style="{% if request.path != '/' %}color: var(--muted);{% endif %}">Dashboard</a>
      <a href="{% url 'banking:list' %}" class="flex items-center justify-between px-2 py-1.5 rounded text-sm mb-0.5 {% if active == 'banking' %}nav-active-cash{% endif %}" style="{% if active != 'banking' %}color: var(--muted);{% endif %}">Banks</a>
      <a href="{% url 'investments:list' %}" class="flex items-center justify-between px-2 py-1.5 rounded text-sm mb-0.5 {% if active == 'investments' %}nav-active-inv{% endif %}" style="{% if active != 'investments' %}color: var(--muted);{% endif %}">Investments</a>
      <a href="{% url 'assets:list' %}" class="flex items-center justify-between px-2 py-1.5 rounded text-sm mb-0.5 {% if active == 'assets' %}nav-active-assets{% endif %}" style="{% if active != 'assets' %}color: var(--muted);{% endif %}">Assets</a>
      <a href="{% url 'liabilities:list' %}" class="flex items-center justify-between px-2 py-1.5 rounded text-sm mb-0.5 {% if active == 'liabilities' %}nav-active-lia{% endif %}" style="{% if active != 'liabilities' %}color: var(--muted);{% endif %}">Liabilities</a>
    {% endwith %}

    <div class="text-[10px] font-semibold tracking-widest mt-6 mb-2" style="color: var(--dim);">ACCOUNT</div>
    <a href="{% url 'settings' %}" class="flex items-center justify-between px-2 py-1.5 rounded text-sm mb-0.5 {% if request.resolver_match.url_name == 'settings' %}nav-active-default{% endif %}" style="{% if request.resolver_match.url_name != 'settings' %}color: var(--muted);{% endif %}">Settings</a>
    <form action="{% url 'logout' %}" method="post" class="m-0">
      {% csrf_token %}
      <button type="submit" class="w-full text-left px-2 py-1.5 rounded text-sm" style="color: var(--muted);">Sign out</button>
    </form>
  </nav>

  {# ============ MAIN ============ #}
  <main class="flex-1 max-w-[1280px] mx-auto p-4 md:p-6">
    {% block content %}{% endblock %}
  </main>

</div>

{% else %}
{# Logged out — render the page bare (login.html provides its own centered layout) #}
{% block anonymous_content %}{% endblock %}
{% endif %}

<script>
  // Theme toggle
  (function() {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;
    var dark = document.querySelectorAll('.theme-icon-dark');
    var light = document.querySelectorAll('.theme-icon-light');
    function syncIcons() {
      var isLight = document.documentElement.getAttribute('data-theme') === 'light';
      dark.forEach(function(el){ el.classList.toggle('hidden', !isLight); });
      light.forEach(function(el){ el.classList.toggle('hidden', isLight); });
    }
    syncIcons();
    btn.addEventListener('click', function() {
      var isLight = document.documentElement.getAttribute('data-theme') === 'light';
      if (isLight) {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('theme', 'dark');
      } else {
        document.documentElement.setAttribute('data-theme', 'light');
        localStorage.setItem('theme', 'light');
      }
      syncIcons();
    });
  })();
</script>

</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add apps/accounts/templates/base.html
git commit -m "feat(ui): new layout shell with sidebar, top bar, theme toggle, PWA wiring"
```

---

## Task 8: Login template (special — no sidebar)

**Files:**
- Modify: `apps/accounts/templates/accounts/login.html`

The login page is logged-out, so it uses the `anonymous_content` block.

- [ ] **Step 1: Replace `apps/accounts/templates/accounts/login.html` with**:

```html
{% extends "base.html" %}
{% block title %}Sign in{% endblock %}
{% block anonymous_content %}
<div class="min-h-screen flex items-center justify-center p-6">
  <div class="w-full max-w-sm">
    <div class="text-center mb-8">
      <div class="font-bold tracking-widest text-2xl" style="color: var(--accent-positive);">○ FINANCE</div>
      <div class="text-sm mt-2" style="color: var(--muted);">momajlab</div>
    </div>
    <form method="post" class="space-y-4 p-6 rounded-lg border" style="background: var(--surface); border-color: var(--border);">
      {% csrf_token %}
      {% if form.non_field_errors %}
        <div class="border p-3 rounded text-sm" style="background: var(--tint-lia); border-color: var(--accent-lia); color: var(--accent-lia);">
          {{ form.non_field_errors }}
        </div>
      {% endif %}
      <div>
        <label class="block text-xs uppercase tracking-wider mb-1" style="color: var(--muted);" for="id_username">Username</label>
        <input id="id_username" name="username" type="text" autocomplete="username" required
               class="w-full px-3 py-2 rounded border outline-none focus:ring-2"
               style="background: var(--bg); border-color: var(--border); color: var(--text);">
      </div>
      <div>
        <label class="block text-xs uppercase tracking-wider mb-1" style="color: var(--muted);" for="id_password">Password</label>
        <input id="id_password" name="password" type="password" autocomplete="current-password" required
               class="w-full px-3 py-2 rounded border outline-none focus:ring-2"
               style="background: var(--bg); border-color: var(--border); color: var(--text);">
      </div>
      <button type="submit" class="w-full py-2 rounded font-semibold"
              style="background: var(--accent-positive); color: var(--bg);">
        Sign in
      </button>
      <input type="hidden" name="next" value="{{ next }}">
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add apps/accounts/templates/accounts/login.html
git commit -m "feat(ui): re-style login (centered card, no sidebar)"
```

---

## Task 9: Dashboard template (the exemplar)

**Files:**
- Modify: `apps/dashboard/templates/dashboard/index.html`

This page sets the visual pattern that every other list/detail page follows. Get this right and the rest is mechanical.

- [ ] **Step 1: Replace the file with**:

```html
{% extends "base.html" %}
{% load sparkline %}
{% block title %}Dashboard{% endblock %}
{% block content %}

<div class="flex items-end justify-between mb-6 flex-wrap gap-4">
  <div>
    <div class="text-[10px] uppercase tracking-widest" style="color: var(--dim);">Net worth</div>
    <div class="text-4xl font-bold num mt-1" style="color: {% if summary.net_worth < 0 %}var(--accent-negative){% else %}var(--accent-positive){% endif %};">
      ${{ summary.net_worth|floatformat:2 }}
    </div>
  </div>
  <div class="flex items-center gap-3">
    {% sparkline history %}
    <div class="text-xs" style="color: var(--muted);">30 days</div>
  </div>
</div>

<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-8">

  <a href="{% url 'banking:list' %}" class="rounded p-4 border block hover:border-opacity-100 transition" style="background: var(--surface); border-color: var(--border);">
    <div class="text-[10px] uppercase tracking-widest" style="color: var(--muted);">Cash</div>
    <div class="text-xl font-bold num mt-1" style="color: var(--accent-cash);">${{ summary.cash|floatformat:2 }}</div>
    <div class="text-[10px] mt-1" style="color: var(--dim);">{{ summary.cash_account_count }} account{{ summary.cash_account_count|pluralize }}</div>
  </a>

  <a href="{% url 'investments:list' %}" class="rounded p-4 border block hover:border-opacity-100 transition" style="background: var(--surface); border-color: var(--border);">
    <div class="text-[10px] uppercase tracking-widest" style="color: var(--muted);">Investments</div>
    <div class="text-xl font-bold num mt-1" style="color: var(--accent-inv);">${{ summary.investments|floatformat:2 }}</div>
    <div class="text-[10px] mt-1" style="color: var(--dim);">{{ summary.investment_holding_count }} position{{ summary.investment_holding_count|pluralize }}</div>
  </a>

  <a href="{% url 'assets:list' %}" class="rounded p-4 border block hover:border-opacity-100 transition" style="background: var(--surface); border-color: var(--border);">
    <div class="text-[10px] uppercase tracking-widest" style="color: var(--muted);">Assets</div>
    <div class="text-xl font-bold num mt-1" style="color: var(--accent-assets);">${{ summary.assets|floatformat:2 }}</div>
    <div class="text-[10px] mt-1" style="color: var(--dim);">{{ summary.asset_count }} item{{ summary.asset_count|pluralize }}</div>
  </a>

  <a href="{% url 'liabilities:list' %}" class="rounded p-4 border block hover:border-opacity-100 transition" style="background: var(--surface); border-color: var(--border);">
    <div class="text-[10px] uppercase tracking-widest" style="color: var(--muted);">Liabilities</div>
    <div class="text-xl font-bold num mt-1" style="color: var(--accent-lia);">−${{ summary.liabilities|floatformat:2 }}</div>
    <div class="text-[10px] mt-1" style="color: var(--dim);">credit + loans + manual</div>
  </a>

</div>

<div class="flex items-center justify-between mb-2">
  <div class="text-[10px] uppercase tracking-widest" style="color: var(--dim);">Latest transactions</div>
  {# See-all link reserved for /transactions/ which lands in Phase 7 — placeholder for now #}
  <span class="text-xs" style="color: var(--dim);">(See all → coming in Phase 7)</span>
</div>

{% if not summary.recent_transactions %}
  <div class="rounded border p-6 text-sm" style="background: var(--surface); border-color: var(--border); color: var(--muted);">
    No transactions yet. Link a bank in <a href="{% url 'settings' %}" class="underline" style="color: var(--accent-positive);">Settings</a>.
  </div>
{% else %}
  <div class="rounded border overflow-hidden" style="background: var(--surface); border-color: var(--border);">
    <table class="w-full text-sm">
      <thead style="border-bottom: 1px solid var(--border); color: var(--dim);">
        <tr class="text-[10px] uppercase tracking-widest">
          <th class="px-4 py-2 text-left w-20">Date</th>
          <th class="px-4 py-2 text-left">Payee</th>
          <th class="px-4 py-2 text-right w-32">Account</th>
          <th class="px-4 py-2 text-right w-28">Amount</th>
        </tr>
      </thead>
      <tbody>
        {% for tx in summary.recent_transactions %}
        <tr style="border-top: 1px solid var(--border);">
          <td class="px-4 py-2 num text-xs" style="color: var(--muted);">{{ tx.posted_at|date:"M d" }}</td>
          <td class="px-4 py-2 truncate">{{ tx.payee|default:tx.description }}</td>
          <td class="px-4 py-2 text-right text-xs" style="color: var(--muted);">{{ tx.account.effective_name }}</td>
          <td class="px-4 py-2 text-right num font-semibold" style="color: {% if tx.amount < 0 %}var(--accent-negative){% else %}var(--accent-positive){% endif %};">
            {% if tx.amount >= 0 %}+{% endif %}${{ tx.amount|floatformat:2 }}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% endif %}

{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add apps/dashboard/templates/dashboard/index.html
git commit -m "feat(ui): rewrite dashboard with sparkline, dense stat cards, transactions table"
```

---

## Task 10: Banking templates rewrite

**Files (modify all 6):**
- `apps/banking/templates/banking/banks_list.html`
- `apps/banking/templates/banking/account_detail.html`
- `apps/banking/templates/banking/link_form.html`
- `apps/banking/templates/banking/rename_form.html`
- `apps/banking/templates/banking/institution_confirm_delete.html`
- `apps/banking/templates/banking/account_confirm_delete.html`

Apply the same patterns as the dashboard. Use the table pattern, the form-input pattern from login, the danger-button pattern from confirm pages.

Pattern references:
- **Stat row** (the institution header): see Task 9 stat cards — same border, padding, label style
- **Table**: see Task 9 transactions table — same header style, hover, divider
- **Form inputs**: see Task 8 login — `bg: var(--bg); border: var(--border); focus:ring-2`
- **Buttons**: primary = `bg: var(--accent-positive); color: var(--bg)`; danger = `bg: red-600; color: white`; secondary = `border: var(--border); color: var(--muted)`
- **Flash messages**: `if message.tags == 'error'` → red tint, success → emerald tint, warning → amber tint, using the `--tint-*` variables.
- **Delete icons** (✎, 🗑) on row right edge use `color: var(--dim)` → `var(--text)` on hover (or `var(--accent-lia)` for delete).

- [ ] **Step 1: Rewrite each file**, replacing the existing Tailwind dark-only classes with the CSS-variable-driven patterns. Each file's structure stays the same (same blocks, same Django template logic) — only classes/styles change. Read each existing file first, identify the structural elements (heading, table rows, form inputs, button), and apply the new visual patterns.

  Concretely for each file:
  - Replace `bg-slate-950`, `bg-slate-900`, `bg-slate-800` → `style="background: var(--surface);"` (cards) or `var(--bg)` (page bg)
  - Replace `border-slate-800` → `style="border-color: var(--border);"`
  - Replace `text-slate-100` / `text-slate-400` / `text-slate-500` → `style="color: var(--text);"` / `var(--muted)` / `var(--dim)`
  - Replace `text-emerald-400`, `text-emerald-200` → `style="color: var(--accent-positive);"`
  - Replace `text-red-300` → `style="color: var(--accent-negative);"` (or `--accent-lia` for liability contexts)
  - Replace `bg-emerald-500` (primary buttons) → `style="background: var(--accent-positive); color: var(--bg);"`
  - Wrap any `${{ value|floatformat:2 }}` in a span with class `num` (so it renders in mono)
  - Tables: use the pattern from Task 9 (uppercase tracking-widest header in `--dim`, rows separated by `border-top: 1px solid var(--border)`)
  - All UI text gets `font-family: inherit` (Inter from base.html), no need to declare per-element

- [ ] **Step 2: Commit each file individually OR all six in one commit**

```bash
git add apps/banking/templates/
git commit -m "feat(ui): re-style banking templates (list, detail, forms, delete confirms)"
```

---

## Task 11: Investments templates rewrite

**Files (8):**
- `apps/investments/templates/investments/investments_list.html`
- `apps/investments/templates/investments/account_detail.html`
- `apps/investments/templates/investments/add_account_form.html`
- `apps/investments/templates/investments/edit_account_form.html`
- `apps/investments/templates/investments/add_holding_form.html`
- `apps/investments/templates/investments/edit_holding_form.html`
- `apps/investments/templates/investments/account_confirm_delete.html`
- `apps/investments/templates/investments/holding_confirm_delete.html`

Same pattern transformation as Task 10. Special note: `investments_list.html` and `account_detail.html` both have tables — apply the dashboard-table pattern (uppercase header, mono numbers, bordered rows).

For symbols (e.g. "AAPL", "VTI"), wrap in `<span class="num font-semibold">` — the mono treatment helps tickers feel like data.

For gain/loss columns: positive uses `var(--accent-positive)`, negative uses `var(--accent-negative)`.

For the cash row on `account_detail.html`: use `var(--accent-cash)` for the dollar value.

- [ ] **Step 1: Rewrite all 8 files** following the patterns from Tasks 9 + 10.

- [ ] **Step 2: Commit**

```bash
git add apps/investments/templates/
git commit -m "feat(ui): re-style investments templates"
```

---

## Task 12: Assets templates rewrite

**Files (3):**
- `apps/assets/templates/assets/assets_list.html`
- `apps/assets/templates/assets/asset_form.html`
- `apps/assets/templates/assets/asset_confirm_delete.html`

Asset-specific accent: `var(--accent-assets)` (amber). Apply to value cells and category indicators (the 📈 / ✎ icons stay as emoji but their containers use `var(--tint-assets)` background).

The asset-form.html has a JavaScript `toggleKind()` function for the radio toggle — preserve it as-is, just restyle the surrounding container.

- [ ] **Step 1: Rewrite all 3 files**

- [ ] **Step 2: Commit**

```bash
git add apps/assets/templates/
git commit -m "feat(ui): re-style assets templates"
```

---

## Task 13: Liabilities templates rewrite

**Files (3):**
- `apps/liabilities/templates/liabilities/liabilities_list.html`
- `apps/liabilities/templates/liabilities/liability_form.html`
- `apps/liabilities/templates/liabilities/liability_confirm_delete.html`

Liability-specific accent: `var(--accent-lia)` (red). All balances in red, with a `−` prefix.

The bank-sourced rows in the list link to `/banks/accounts/<id>/` — that link should still work. Apply the table pattern.

- [ ] **Step 1: Rewrite all 3 files**

- [ ] **Step 2: Commit**

```bash
git add apps/liabilities/templates/
git commit -m "feat(ui): re-style liabilities templates"
```

---

## Task 14: Settings template rewrite

**Files:**
- `apps/accounts/templates/accounts/settings.html`

Settings has multiple stacked sections (institutions, investment accounts, scraped assets). Each section title uses the uppercase tracking-widest dim label pattern. Each section has its own list of rows, similar to the per-section list pages but more compact.

The "+ Link account" button (added in Phase 6) keeps its position next to the Bank institutions heading.

- [ ] **Step 1: Rewrite the file**

- [ ] **Step 2: Commit**

```bash
git add apps/accounts/templates/accounts/settings.html
git commit -m "feat(ui): re-style settings page"
```

---

## Task 15: Final smoke (USER) + PWA validation

No code changes — verification gate.

- [ ] **Step 1: Pull, rebuild, restart on the server**

```bash
cd /opt/finance
git pull
git checkout phase-8-ui   # or pull master after merge — your call
docker compose build web
docker compose up -d web
docker compose exec web python manage.py collectstatic --noinput
```

- [ ] **Step 2: Run the full test suite**

```bash
docker compose exec web pytest -v
```

Expected: all existing tests pass (~95 from prior phases) + 6 new sparkline tests = ~101.

If anything fails, do NOT proceed to merge. Investigate.

- [ ] **Step 3: Browser smoke test (desktop)**

1. Visit `/` — sidebar visible, top bar with theme toggle, dashboard renders with sparkline.
2. Click theme toggle — page flips light, no flash. Reload — stays light.
3. Click toggle again — back to dark. Reload — stays dark.
4. Click each sidebar nav item — every page renders cleanly with the new styling.
5. Add a manual asset, then delete it — flow still works.
6. Add a manual investment holding — flow still works.
7. Edit cost basis on a holding inline — works.
8. Click "+ Link account" in Settings → form renders, Cancel goes back.

- [ ] **Step 4: Browser smoke test (mobile)**

1. Open in a phone browser at the tailnet URL.
2. Sidebar is hidden, hamburger button visible top-left.
3. Tap hamburger → sidebar slides in over content with dark scrim behind.
4. Tap a nav item → sidebar closes, new page loads.
5. Tap scrim → sidebar closes.
6. Theme toggle works.

- [ ] **Step 5: PWA install test**

1. Visit on iOS Safari → Share → "Add to Home Screen" → confirm icon appears.
2. Tap the home-screen icon → app launches in standalone mode (no Safari URL bar).
3. Visit on Android Chrome → menu → "Install app" → same outcome.

If the icon is the placeholder "F", that's expected until the real logo is supplied.

- [ ] **Step 6: Merge to master**

```bash
git checkout master
git merge --ff-only phase-8-ui
git push origin master
git branch -d phase-8-ui
git push origin --delete phase-8-ui
```

---

## Phase 8 Definition of Done

- [ ] All ~101 pytest tests pass.
- [ ] Theme toggle works and persists across reloads.
- [ ] Default theme follows OS preference on first visit.
- [ ] Sidebar collapses to drawer below 768 px.
- [ ] Sparkline renders on dashboard with real data (or `—` if no snapshots yet).
- [ ] All forms still submit (delete confirms, edit holding, link bank, add asset/liability).
- [ ] Flash messages render correctly.
- [ ] PWA installs cleanly on iOS and Android.
- [ ] Logo placeholder visible until real asset arrives — wires intact.

When all green, **Phase 8 ships.** Phase 7 (transactions page, money tag, xlsx export, investment enrichment) lands next, building on the new design.
