# Asset Detail Page — Design Spec

**Date:** 2026-05-05
**Status:** Approved
**Branch:** TBD (likely `feature/asset-detail`)

## Goal

Today an asset is reachable only through the form (`/assets/<id>/edit/`) which is write-only — there's nowhere to *see* an asset's current state. The scraper persists `current_value` and `last_priced_at` but discards the per-unit price after computing the total, so even the underlying market price is invisible. Snapshots accumulate in `AssetPriceSnapshot` but are never plotted.

This feature adds a per-asset detail page that surfaces three things:
1. **Current per-unit scraped price** (new model field, persisted by the scraper).
2. **Last-updated stamp** (already in `last_priced_at`, just not surfaced).
3. **Value-over-time chart** (built from existing `AssetPriceSnapshot` rows, same visual language as the dashboard net-worth chart).

It also adds a per-asset "refresh" button so the user can re-scrape one asset without hitting "Refresh prices" globally.

## Decisions summary

| # | Decision | Choice |
|---|----------|--------|
| 1 | Where the new info lives | New `/assets/<id>/` detail page (B) |
| 2 | What the chart plots | Total asset value over time (A) |
| 3 | Manual assets get the page too | Yes (A) — no unit price line, chart still plots value |
| 4 | Per-unit price persistence | New nullable `last_unit_price` field on `Asset` |
| 5 | Per-asset refresh button | Yes, on detail page (scraped only) |
| 6 | Chart implementation | Refactor `networth_chart` helper to accept any series (option i) |
| 7 | Backfill of `last_unit_price` | Migration computes `current_value / quantity` for existing scraped rows |

## Model change

**File:** `apps/assets/models.py`

Add to `Asset`:

```python
last_unit_price = models.DecimalField(
    max_digits=18, decimal_places=4, null=True, blank=True,
    help_text="Per-unit scraped price from the most recent successful refresh. "
              "Null for manual assets and for scraped assets that have never been refreshed.",
)
```

Decimal places = 4 (vs 2 for `current_value`) so unit prices like `$2,041.5025/oz` aren't truncated.

**Migration** — `apps/assets/migrations/0002_asset_last_unit_price.py`:

1. `AddField` for `last_unit_price` (default null).
2. Data migration: for each scraped `Asset` where `quantity > 0` and `current_value > 0`, set `last_unit_price = (current_value / quantity).quantize(Decimal("0.0001"))`. Leave manual rows null. Reverse migration: noop (just drop the column).

## Service changes

**File:** `apps/assets/services.py`

In `refresh_scraped_assets`, persist the per-unit price:

```python
a.last_unit_price = result.price
a.current_value = (result.price * a.quantity).quantize(Decimal("0.01"))
a.last_priced_at = result.at
a.save(update_fields=["last_unit_price", "current_value", "last_priced_at"])
```

Add a new function `refresh_one_asset(asset: Asset) -> tuple[bool, str]`:
- Returns `(True, "")` on success, `(False, error_message)` on failure.
- Does nothing for manual assets — returns `(False, "manual assets have no source URL")`.
- Otherwise mirrors the per-asset block of `refresh_scraped_assets`, including the `_snapshot` call.

(Could also be implemented as `refresh_scraped_assets(user=user, only_asset_id=...)`. New function is cleaner — the bulk refresher already returns aggregate counts that don't apply to a single-asset action.)

## URL & view changes

**File:** `apps/assets/urls.py`

```python
path("<int:asset_id>/", views.asset_detail, name="detail"),
path("<int:asset_id>/refresh/", views.refresh_one, name="refresh_one"),
# (existing routes unchanged: edit at <int:asset_id>/edit/, delete, refresh)
```

**File:** `apps/assets/views.py`

```python
@login_required
def asset_detail(request, asset_id):
    asset = get_object_or_404(Asset.objects.for_user(request.user), pk=asset_id)
    series = build_asset_value_series(asset)  # see "Chart data" below
    return render(request, "assets/asset_detail.html", {
        "asset": asset,
        "series": series,
    })

@login_required
@require_http_methods(["POST"])
def refresh_one(request, asset_id):
    asset = get_object_or_404(Asset.objects.for_user(request.user), pk=asset_id)
    ok, err = refresh_one_asset(asset)
    if ok:
        messages.success(request, f"Refreshed {asset.name}.")
    else:
        messages.error(request, f"Refresh failed: {err}")
    return HttpResponseRedirect(reverse("assets:detail", args=[asset.id]))
```

## Chart data

**File:** `apps/assets/services.py`

```python
def build_asset_value_series(asset: Asset, days: int = 30) -> list[Decimal]:
    """Forward-filled daily series of this asset's value over `days` days, ending today.
    Mirrors the pattern from apps/dashboard/services.py: seed with the last snapshot
    before the window, then walk each day applying any in-window snapshot."""
```

Implementation walks the same algorithm as `apps/dashboard/services.py:146-193` for a single asset — seed with the latest `AssetPriceSnapshot` strictly before `cutoff`, then for each day in the window apply any in-window snapshot (latest wins per day), forward-filling otherwise. Returns a list of `Decimal`s, recent-last, length == `days`.

**Default window:** 30 days. (Future: a range selector — out of scope.)

If the asset has zero snapshots ever (shouldn't happen — `create_asset` always snapshots — but defensive), return a list of `days` zeros (mirrors the dashboard pipeline, which seeds zero when no snapshots exist). The chart helper's `<2-points` fallback won't fire in this case (30 zeros is technically renderable as a flat line), but the stat cards above the chart will already show `current_value` of zero, so the flat-zero chart line below is a reasonable degraded experience and the user can still see the chart container is there. If a more explicit "no data yet" placeholder becomes desirable, that's a follow-up to either this helper (return empty when all values are zero AND no snapshots exist) or the chart helper (render placeholder when all values are equal).

## Chart helper refactor

**File:** `apps/dashboard/templatetags/networth_chart.py` (file name unchanged — moving it would touch the dashboard template's `{% load %}`).

Inside the file:

1. Rename the implementation function `networth_chart_svg` → `value_chart_svg`. Add a new kwarg `value_label: str = "Value"` (default keeps current behavior).
2. The existing `{% networth_chart %}` template tag becomes a thin wrapper: `return value_chart_svg(values, days=int(days), value_label="Net worth")`. Dashboard template untouched.
3. Add a new `{% value_chart values value_label="Asset value" %}` template tag for the asset detail page.

This avoids file moves and dashboard template churn while letting asset detail consume a generically-named tag. CSS class names inside the SVG (`nw-chart`, `nw-tooltip`, etc.) stay as-is — they're scoped per-instance via the `nw-{uuid}` container ID, so no collision risk between dashboard and detail charts on the same page (and they aren't on the same page anyway).

## Templates

**New file:** `apps/assets/templates/assets/asset_detail.html`

Layout (top to bottom):

1. **Back link + title** — `← Assets` (muted), then `<h1>{{ asset.name }}</h1>` and a small kind badge (📈 Scraped / ✎ Manual).

2. **Stat cards row** — flex container, 3 cards on desktop (2 if manual since unit price is hidden), stacked on mobile. Each card:
   - **Current value** — large `{{ asset.current_value|money }}`, muted label "Current value".
   - **Unit price** (scraped only) — `{{ asset.last_unit_price|money }}` if not null else "—". Sub-label: `× {{ asset.quantity }} {{ asset.unit }}`.
   - **Last updated** — `{{ asset.last_priced_at|date:"M j, Y" }}` (or "Never"), with `title="{{ asset.last_priced_at|date:'c' }}"` for a full ISO timestamp on hover. Sub-label: humanized "(2 days ago)" via `{{ asset.last_priced_at|timesince }} ago`.

3. **Refresh button** (scraped only) — `<form method="post" action="{% url 'assets:refresh_one' asset.id %}">` with a "⟳ Refresh now" button. Sits right of the stat cards on desktop, full-width below on mobile.

4. **Chart** — `{% load value_chart %}` then `{% value_chart series value_label="Asset value" %}`. 320px tall, full-width. The "fewer than 2 points" fallback already lives in the chart helper.

5. **Notes** — if `asset.notes` non-empty, displayed in a muted text block.

6. **Edit / Delete actions** — bottom of page, `<a>` buttons going to existing `assets:edit` and `assets:delete` URLs.

**Existing list template** — `apps/assets/templates/assets/assets_list.html`:

- Asset name in the table cell becomes a link: `<a href="{% url 'assets:detail' a.id %}">{{ a.name }}</a>`.
- ✎ icon's `href` unchanged (still goes straight to edit).
- Mobile cards: wrap the name + notes block in an `<a>` tag to detail; action icons (✎, 🗑) outside the link.

## Testing

New tests in `apps/assets/tests/test_views.py`:

- `test_asset_detail_renders` — owner can GET, returns 200, context has `asset` and `series`.
- `test_asset_detail_isolation` — non-owner gets 404.
- `test_asset_detail_no_snapshots` — fresh asset (no snapshots, somehow) renders without crashing.
- `test_refresh_one_post` — POST to refresh-one for owner triggers scraper, updates `current_value`, `last_unit_price`, `last_priced_at`.
- `test_refresh_one_manual_rejected` — POST against a manual asset surfaces an error message, no model change.
- `test_refresh_one_isolation` — non-owner 404s.

New test in `apps/assets/tests/test_services.py`:

- `test_refresh_persists_unit_price` — after a successful refresh, `Asset.last_unit_price` matches the scraper result.
- `test_build_asset_value_series` — given a known snapshot history, the returned series has expected length and forward-fill values.

New test in `apps/assets/tests/`:

- `test_migration_backfill_unit_price` — existing scraped row with `current_value=200, quantity=10` gets `last_unit_price=20.0000` after migration; manual row stays null.

## Edge cases

- **Asset with no snapshots in the 30-day window** — chart helper renders "not enough data" placeholder. Stat cards still show `current_value` and `last_priced_at` from the row.
- **Refresh fails on detail page** — error message via Django messages, redirect back to detail. `last_priced_at` unchanged so the "stale" stamp stays accurate.
- **Manual asset with refresh button hidden** — tested explicitly; defense in depth: `refresh_one_asset` also rejects manual kinds at the service layer.
- **`quantity = 0` on a scraped asset** (theoretically possible since the field has no validator) — migration backfill skips it; runtime scraper still computes `current_value = 0`, `last_unit_price` set to whatever scraper returns. No special handling needed.

## Out of scope

- Range selector on the chart (1W / 1M / 1Y / All).
- Per-unit-price chart (decided: total-value only).
- Editing snapshots.
- Comparing multiple assets on one chart.
- Telemetry on detail-page visits.
