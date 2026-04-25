# UI Overhaul — Design

**Date:** 2026-04-24
**Status:** Approved (brainstorming complete)
**Owner:** mohamed

---

## 1. Overview

Re-skin every page of the personal finance dashboard with a denser, data-app aesthetic on a sidebar layout. Add a per-user light/dark theme toggle. Add inline SVG sparklines next to the net-worth headline and per-investment-account rows. Make the app PWA-installable so it can be added to home screens with a custom logo.

Routing, models, services, and tests are untouched. This is a CSS + template overhaul — Phase 8 of the project.

### Goals

- A consistent visual language across every page (dashboard, transactions, banks, investments, assets, liabilities, settings, login, forms).
- Light/dark toggle persisted in `localStorage`, default following the OS via `prefers-color-scheme`.
- Mobile-friendly: sidebar collapses to a hamburger drawer below 768px.
- Numerically focused: monospace digits with tabular alignment in tables; clear category-color coding.
- PWA installable with proper favicon, apple-touch-icon, and manifest.

### Non-Goals

- Full charting / history pages — sparklines only. A `/history/` page can come later.
- Routing changes — every URL stays where it is.
- View / model / business-logic changes — all of those are scoped into Phase 7 (Quick polish) and prior phases.
- Notifications, animations beyond subtle hover states, drag-and-drop, or any rich interactivity.

---

## 2. Layout & structure

Two-column layout at desktop (≥768 px); single-column with a hamburger-driven drawer on mobile.

```
┌─────────────────────────────────────────────────────┐
│ [logo] FINANCE          (theme toggle, user menu)   │  ← top bar (sticky, ~52px)
├─────────┬───────────────────────────────────────────┤
│ VIEW    │                                           │
│  ◉ Dash │   Main content (max-width: 1280px)        │
│  ○ Tx   │                                           │
│  ○ Banks│                                           │
│  ○ Inv  │                                           │
│  ○ Asts │                                           │
│  ○ Liab │                                           │
│         │                                           │
│ ACCT    │                                           │
│  ○ Sett │                                           │
│  ○ Out  │                                           │
└─────────┴───────────────────────────────────────────┘
   180px         flex-1
```

**Sidebar nav order** (top → bottom):
- VIEW: Dashboard, Transactions, Banks, Investments, Assets, Liabilities
- ACCOUNT: Settings, Sign out

Active item gets a tinted background using the section's accent color. Count badges on the right of Banks / Investments / Assets / Liabilities (number of items in that section).

**Top bar:** logo + brand text on the far left (above the sidebar), theme toggle + `mhamida292 ▾` user menu on the right. Sticky on scroll.

**Main content:** scrollable, max-width 1280 px so a 4 K monitor doesn't waste space.

**Mobile (<768 px):**
- Sidebar collapses; hamburger button appears in the top bar.
- Tap → sidebar slides in from the left over the main content with a scrim overlay.
- Top bar stays sticky so the logo + theme toggle are always reachable.

---

## 3. Color system + theme toggle

CSS custom properties under `:root` (dark) and `[data-theme="light"]` (light). Same accent palette across themes; only the surface tones differ.

### Dark theme (default)

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#020617` | page background |
| `--surface` | `#0f172a` | cards, sidebar, table rows |
| `--border` | `#1e293b` | dividers, card borders |
| `--text` | `#e2e8f0` | body text |
| `--muted` | `#64748b` | labels, secondary text |
| `--dim` | `#475569` | section headings, hints |

### Light theme

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#f8fafc` | page background |
| `--surface` | `#ffffff` | cards, sidebar |
| `--border` | `#e2e8f0` | dividers |
| `--text` | `#0f172a` | body text |
| `--muted` | `#64748b` | labels (same — neutral) |
| `--dim` | `#94a3b8` | section headings |

### Accent palette (same hue, different lightness per theme)

| Category | `--accent-*` (dark) | `--accent-*` (light) |
|---|---|---|
| `--accent-cash` | `#60a5fa` (blue-400) | `#2563eb` (blue-600) |
| `--accent-inv` | `#a78bfa` (violet-400) | `#7c3aed` (violet-600) |
| `--accent-assets` | `#fbbf24` (amber-400) | `#d97706` (amber-600) |
| `--accent-lia` | `#f87171` (red-400) | `#dc2626` (red-600) |
| `--accent-positive` | `#34d399` (emerald-400) | `#059669` (emerald-600) |

### Theme toggle implementation

- Toggle button in the top bar (sun/moon icon).
- Stored in `localStorage.theme` as `"light"` or `"dark"`.
- On first visit (no stored value), defaults to `prefers-color-scheme` from the OS.
- A tiny inline script in the `<head>` reads the stored value and sets `data-theme` on `<html>` BEFORE Tailwind paints — prevents the "flash of wrong theme" on page load.
- No round-trip to Django; pure client-side flip.

---

## 4. Component library

Reusable patterns used across pages. Built once, applied everywhere via Tailwind utility classes referencing the CSS custom properties.

### Stat card (the 4 dashboard tiles)
1 px border, 6 px radius, 12 px padding. Uppercase letterspaced label (e.g., `CASH`). Big number in mono with the section's accent color. Optional sub-line (account count, % delta). Whole card is a link to its section.

### Table (transactions, holdings, accounts)
No outer border; rows separated by 1 px `--border` divider. Letterspaced uppercase header row in `--dim`. Right-aligned numbers (mono with tabular-nums), left-aligned text. Hover state: subtle row background tint. Per-row actions (✎, 🗑) on the far right.

### Sparkline
Inline SVG, 100 px wide × 24 px tall. Single stroke in the relevant accent color (emerald for net-worth, violet for investments). Tooltip on hover with date + value. Falls back to "—" if fewer than 2 data points exist. Server-side rendering via a custom Django template tag `{% sparkline values %}` — no JavaScript dependency.

### Nav item (sidebar)
6 px vertical / 8 px horizontal padding. 4 px radius. Active state: tinted background matching section accent. Right-aligned count badge (rounded pill, muted background).

### Button (3 variants)
- **Primary**: emerald background, dark text (current pattern, kept)
- **Secondary**: 1 px `--border`, no fill, `--muted` text → `--text` on hover
- **Danger**: red background for delete confirms

### Form input
`--surface` background, 1 px `--border`, 4 px radius, 8 px padding. Focus ring: 2 px accent color (emerald for primary forms, red for danger). Mono font for numeric inputs (price, shares, balance).

### Badge
Tiny pill, `--surface` background, `--muted` text — used for sidebar counts.

### Empty state
Centered card with explanatory text + the relevant primary CTA. No illustrations.

### Flash messages (Django messages framework)
Slim banner at the top of the content area. Color-coded: emerald (success), amber (warning), red (error). Dismissible.

---

## 5. Typography

- **Body / UI:** Inter (web font, self-hosted from `static/fonts/`)
- **Numbers:** JetBrains Mono (web font, self-hosted)
- **Tabular alignment:** all monospace numbers get `font-variant-numeric: tabular-nums` so columns line up cleanly
- **Type scale:**
  - Page title: 24 px / 700 weight
  - Section heading: 18 px / 600 weight
  - Body: 14 px / 400 weight
  - Label / caption: 11 px / 600 weight uppercase letterspaced
  - Micro: 10 px (sub-labels under stat values)

Self-hosting fonts (rather than CDN) is the homelab-friendly choice — faster, works offline, no third-party dependency.

---

## 6. Page-by-page

URL paths unchanged. Each existing template is updated to use the new components.

| Page | Treatment |
|---|---|
| `/` Dashboard | Net-worth headline + sparkline · 4-card stat row · "Latest transactions" table with `See all →` to `/transactions/` |
| `/transactions/` | Filter bar (account dropdown, date range, search) · dense table · pagination at the bottom · `Export to Excel` button top-right |
| `/banks/` | "Manage in Settings →" link in header · institution sections, each with an inline account table |
| `/banks/accounts/<id>/` | Account header (balance, delete) · transaction table |
| `/investments/` | Net total + sparkline · table of accounts with market value + gain $ + gain % per row · `View all holdings →` link |
| `/investments/accounts/<id>/` | Account header (broker, source, total, cash) · holdings table with editable cost-basis inline |
| `/investments/holdings/` | Flat all-holdings table with Account column |
| `/assets/` | Total + table of assets · kind icon (📈 / ✎) · refresh + add buttons |
| `/liabilities/` | Total · table merging bank credit/loan + manual liabilities · add manual button |
| `/settings/` | Stacked sections: Bank institutions (with `+ Link account` button per Phase 6 cleanup), Investment accounts, Scraped assets, plus user info header |
| `/login/` | Centered card on a plain page (no sidebar) — only deviation from the layout |
| `/admin/` | Untouched — Django admin keeps its native styling |

Form pages (link bank, add holding, add liability, edit asset, etc.) all use the same layout as their parent page, with the form rendered as a centered max-width card.

---

## 7. Logo + PWA integration

### Files (placed in `finance/static/`)
```
favicon.ico               # multi-size ICO (16, 32, 48)
favicon-32.png
favicon-16.png
apple-touch-icon.png      # 180×180 for iOS home screen
icon-192.png              # PWA standard
icon-512.png              # PWA splash
manifest.webmanifest      # tells the browser this is installable
```

### `<head>` additions in `base.html`
```html
<link rel="icon" href="/static/favicon.ico">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<link rel="manifest" href="/static/manifest.webmanifest">
<meta name="theme-color" content="#020617" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#f8fafc" media="(prefers-color-scheme: light)">
```

### `manifest.webmanifest`
```json
{
  "name": "Finance",
  "short_name": "Finance",
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

Result: any device hitting `https://finance.momajlab.com` from a browser → "Add to Home Screen" → installs as a fullscreen-launching app with the logo on the home screen.

### Logo asset workflow

User provides one square source image (ideally 512×512 PNG with transparent background, or SVG). Implementation phase generates the smaller derivatives. **Until the asset arrives, ship a placeholder text mark** ("FINANCE" in emerald, tight letterspaced) so the layout works.

---

## 8. Sparkline data sources

The sparkline template tag accepts a list of decimal values (or a queryset of snapshots) and renders an SVG path.

| Sparkline location | Data source |
|---|---|
| Net-worth headline (`/` dashboard) | Sum of all `PortfolioSnapshot.total_value` per day for the last 30 days, plus all `AssetPriceSnapshot` aggregated similarly |
| Per-investment-account row (`/investments/`) | `PortfolioSnapshot` rows for that account, last 30 days |

If a series has fewer than 2 data points (e.g., a brand-new account), render `—` instead. No backfill — sparklines fill in over time as the daily cron writes new snapshots.

---

## 9. Rollout / migration

**One branch, one drop:** `phase-8-ui` off master. Single PR with all templates re-themed atomically — no partially rebranded screens in production.

**Files touched:**
- Every `*.html` template (about 22 files).
- `apps/accounts/templates/base.html` — biggest rewrite (new layout shell, theme script, manifest links).
- New `static/css/app.css` — design tokens (CSS custom properties).
- New `static/fonts/` — Inter + JetBrains Mono self-hosted.
- New template tag library `apps/dashboard/templatetags/sparkline.py`.
- New `static/manifest.webmanifest`.
- Logo placeholder until user supplies asset.

**Theme-toggle script** lands in `base.html` head as a small inline `<script>` so it runs synchronously before paint.

**Tests:** existing 100+ pytest tests should pass unchanged — they assert HTTP behavior and text content, not CSS. Final smoke is the full `pytest -v` run.

**Manual smoke (after server deploy):**
- Theme toggle persists across page reloads.
- Theme defaults to OS preference on first visit (in a private window).
- Mobile sidebar collapses to hamburger at <768 px.
- Sparkline renders on dashboard with real `PortfolioSnapshot` data.
- All forms still submit (delete confirms, edit holding, link bank).
- All flash messages still display correctly.
- PWA install prompt appears in Chrome/Edge after first visit.
- "Add to Home Screen" on iOS Safari works and launches in standalone mode.
