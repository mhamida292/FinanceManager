# Asset Detail Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every asset a detail page at `/assets/<id>/` that surfaces its current value, the per-unit scraped price, a "last updated" stamp, and a 30-day value chart. Add a per-asset refresh button so users can re-scrape one asset without hitting the global refresh.

**Architecture:** A new nullable `Asset.last_unit_price` field is persisted by `refresh_scraped_assets` (and backfilled at migration time from `current_value / quantity`). New `refresh_one_asset` service handles single-asset refresh. New `build_asset_value_series` helper builds a 30-day forward-filled daily series from existing `AssetPriceSnapshot` rows, using the same algorithm as the dashboard's net-worth pipeline. The dashboard chart helper is generalized: `networth_chart_svg` is renamed to `value_chart_svg` with a `value_label` kwarg, the existing `{% networth_chart %}` tag becomes a thin wrapper, and a new `{% value_chart %}` tag is registered for asset use. A new `asset_detail` view + template renders everything; the list view's asset name becomes a link to the detail page.

**Tech Stack:** Django 5.1, pytest-django, server-rendered SVG. Tests run via `docker compose exec web pytest` per CLAUDE.md (Dockerfile uses `COPY . .`, no bind mount).

**Spec:** `docs/superpowers/specs/2026-05-05-asset-detail-page-design.md`

---

## File Structure

**Create:**
- `apps/assets/migrations/0002_asset_last_unit_price.py` — `AddField` + data migration backfill
- `apps/assets/templates/assets/asset_detail.html` — the new detail page

**Modify:**
- `apps/assets/models.py` — add `last_unit_price` field
- `apps/assets/services.py` — persist `last_unit_price` in `refresh_scraped_assets`, add `refresh_one_asset`, add `build_asset_value_series`
- `apps/assets/views.py` — add `asset_detail` and `refresh_one` views
- `apps/assets/urls.py` — register `detail` and `refresh_one` routes
- `apps/assets/templates/assets/assets_list.html` — link asset names to detail page
- `apps/dashboard/templatetags/networth_chart.py` — generalize `networth_chart_svg` → `value_chart_svg(value_label=...)`, register new `{% value_chart %}` tag, keep `{% networth_chart %}` as thin wrapper

**Test (extend):**
- `apps/assets/tests/test_services.py` — unit-price persistence, `refresh_one_asset`, `build_asset_value_series`
- `apps/assets/tests/test_views.py` — detail page, refresh-one endpoint, isolation
- `apps/assets/tests/` (new file `test_migrations.py`) — backfill correctness

---

## Task 1: Add `last_unit_price` field + migration with backfill

**Files:**
- Modify: `apps/assets/models.py`
- Create: `apps/assets/migrations/0002_asset_last_unit_price.py`
- Create: `apps/assets/tests/test_migrations.py`

- [ ] **Step 1: Write the failing migration backfill test**

Create `apps/assets/tests/test_migrations.py`:

```python
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db.migrations.executor import MigrationExecutor
from django.db import connection

User = get_user_model()


@pytest.mark.django_db(transaction=True)
def test_unit_price_backfill_for_scraped():
    """Existing scraped rows must get last_unit_price = current_value / quantity."""
    executor = MigrationExecutor(connection)
    # Roll back to the migration just before the new one.
    executor.migrate([("assets", "0001_initial")])
    old_apps = executor.loader.project_state([("assets", "0001_initial")]).apps
    OldAsset = old_apps.get_model("assets", "Asset")
    user = User.objects.create_user(username="alice", password="x" * 20)

    OldAsset.objects.create(
        user_id=user.id, kind="scraped", name="Gold",
        source_url="https://example.com/gold",
        quantity=Decimal("10"), current_value=Decimal("200.00"),
    )
    OldAsset.objects.create(
        user_id=user.id, kind="manual", name="Car",
        current_value=Decimal("18000.00"), quantity=Decimal("1"),
    )

    # Apply the new migration.
    executor.loader.build_graph()
    executor.migrate([("assets", "0002_asset_last_unit_price")])

    new_apps = executor.loader.project_state([("assets", "0002_asset_last_unit_price")]).apps
    NewAsset = new_apps.get_model("assets", "Asset")

    gold = NewAsset.objects.get(name="Gold")
    car = NewAsset.objects.get(name="Car")

    assert gold.last_unit_price == Decimal("20.0000")
    assert car.last_unit_price is None  # manual rows stay null
```

- [ ] **Step 2: Add the model field**

In `apps/assets/models.py`, inside the `Asset` class, add `last_unit_price` after `current_value` (around line 32):

```python
    last_unit_price = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True,
        help_text="Per-unit scraped price from the most recent successful refresh. "
                  "Null for manual assets and for scraped assets never refreshed.",
    )
```

- [ ] **Step 3: Generate the schema migration**

```bash
docker compose exec web python manage.py makemigrations assets --name asset_last_unit_price
```

This creates `apps/assets/migrations/0002_asset_last_unit_price.py` with the `AddField`. Open the file.

- [ ] **Step 4: Add a data-migration step inside the same migration**

Edit the generated `apps/assets/migrations/0002_asset_last_unit_price.py` to add a `RunPython` operation after the `AddField`. The full file should look like:

```python
from decimal import Decimal

from django.db import migrations, models


def _backfill_unit_price(apps, schema_editor):
    Asset = apps.get_model("assets", "Asset")
    for asset in Asset.objects.filter(kind="scraped"):
        if asset.quantity and asset.quantity > 0 and asset.current_value and asset.current_value > 0:
            asset.last_unit_price = (asset.current_value / asset.quantity).quantize(Decimal("0.0001"))
            asset.save(update_fields=["last_unit_price"])


def _noop_reverse(apps, schema_editor):
    """Reverse just drops the column; nothing to undo at the data level."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="last_unit_price",
            field=models.DecimalField(
                blank=True, decimal_places=4, max_digits=18, null=True,
                help_text="Per-unit scraped price from the most recent successful refresh. "
                          "Null for manual assets and for scraped assets never refreshed.",
            ),
        ),
        migrations.RunPython(_backfill_unit_price, _noop_reverse),
    ]
```

(If `makemigrations` produced slightly different formatting for the AddField, keep its version of the AddField field args and just append the `RunPython` operation.)

- [ ] **Step 5: Run the migration test**

```bash
docker compose exec web pytest apps/assets/tests/test_migrations.py -v
```

Expected: 1 pass.

- [ ] **Step 6: Run the existing assets tests to confirm no regressions**

```bash
docker compose exec web pytest apps/assets/ -q
```

Expected: all pre-existing tests still pass (the new field is nullable, so unrelated tests are unaffected).

- [ ] **Step 7: Commit**

```bash
git add apps/assets/models.py apps/assets/migrations/0002_asset_last_unit_price.py apps/assets/tests/test_migrations.py
git commit -m "feat(assets): add last_unit_price field with backfill migration

New nullable DecimalField(18,4) on Asset records per-unit scraped price.
Data migration derives it for existing scraped rows from current_value/quantity.
Manual rows stay null."
```

---

## Task 2: Persist `last_unit_price` in `refresh_scraped_assets`

**Files:**
- Modify: `apps/assets/services.py` (the `refresh_scraped_assets` function ~line 40)
- Test: `apps/assets/tests/test_services.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/assets/tests/test_services.py`:

```python
@pytest.mark.django_db
def test_refresh_persists_unit_price(fake_scraper):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(
        user=user, kind="scraped", name="Gold Eagle",
        source_url="https://example.com/gold", quantity=Decimal("3"),
    )
    fake_scraper.prices_by_url = {"https://example.com/gold": Decimal("2734.50")}

    refresh_scraped_assets(user=user)

    a.refresh_from_db()
    assert a.last_unit_price == Decimal("2734.5000")
    assert a.current_value == Decimal("8203.50")  # quantity × unit price
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
docker compose exec web pytest apps/assets/tests/test_services.py::test_refresh_persists_unit_price -v
```

Expected: FAIL with `assert None == Decimal('2734.5000')`.

- [ ] **Step 3: Update the refresh service**

In `apps/assets/services.py`, edit `refresh_scraped_assets` (around line 56). Find:

```python
            a.current_value = (result.price * a.quantity).quantize(Decimal("0.01"))
            a.last_priced_at = result.at
            a.save(update_fields=["current_value", "last_priced_at"])
```

Replace with:

```python
            a.last_unit_price = result.price.quantize(Decimal("0.0001"))
            a.current_value = (result.price * a.quantity).quantize(Decimal("0.01"))
            a.last_priced_at = result.at
            a.save(update_fields=["last_unit_price", "current_value", "last_priced_at"])
```

- [ ] **Step 4: Run tests**

```bash
docker compose exec web pytest apps/assets/tests/test_services.py -v
```

Expected: all pass, including the new one.

- [ ] **Step 5: Commit**

```bash
git add apps/assets/services.py apps/assets/tests/test_services.py
git commit -m "feat(assets): persist last_unit_price on scraper refresh

Stores the per-unit price (quantized to 4dp) alongside the existing
total current_value, so the detail page can display it."
```

---

## Task 3: Add `refresh_one_asset` service function

**Files:**
- Modify: `apps/assets/services.py` (add new function after `refresh_scraped_assets`)
- Test: `apps/assets/tests/test_services.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/assets/tests/test_services.py`:

```python
@pytest.mark.django_db
def test_refresh_one_asset_updates_just_that_asset(fake_scraper):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(
        user=user, kind="scraped", name="Gold",
        source_url="https://example.com/gold", quantity=Decimal("2"),
    )
    b = create_asset(
        user=user, kind="scraped", name="Silver",
        source_url="https://example.com/silver", quantity=Decimal("5"),
    )
    fake_scraper.prices_by_url = {
        "https://example.com/gold": Decimal("2000"),
        "https://example.com/silver": Decimal("30"),
    }
    # Import here so the failing import surfaces in this test.
    from apps.assets.services import refresh_one_asset

    ok, err = refresh_one_asset(a)
    assert ok is True
    assert err == ""
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.current_value == Decimal("4000.00")
    assert b.current_value == Decimal("0.00")  # untouched (was zero from create_asset)


@pytest.mark.django_db
def test_refresh_one_asset_rejects_manual():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(user=user, kind="manual", name="Car", current_value=Decimal("18000"))
    from apps.assets.services import refresh_one_asset
    ok, err = refresh_one_asset(a)
    assert ok is False
    assert "manual" in err.lower()
    a.refresh_from_db()
    assert a.current_value == Decimal("18000")  # unchanged


@pytest.mark.django_db
def test_refresh_one_asset_records_failure(fake_scraper):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(
        user=user, kind="scraped", name="Bad",
        source_url="https://bad.example/", quantity=Decimal("1"),
    )
    fake_scraper.errors_by_url = {"https://bad.example/": "boom"}
    from apps.assets.services import refresh_one_asset
    ok, err = refresh_one_asset(a)
    assert ok is False
    assert "boom" in err
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec web pytest apps/assets/tests/test_services.py::test_refresh_one_asset_updates_just_that_asset apps/assets/tests/test_services.py::test_refresh_one_asset_rejects_manual apps/assets/tests/test_services.py::test_refresh_one_asset_records_failure -v
```

Expected: 3 import errors / failures (`refresh_one_asset` does not exist).

- [ ] **Step 3: Implement `refresh_one_asset`**

In `apps/assets/services.py`, append after `refresh_scraped_assets` (after line 63):

```python
def refresh_one_asset(asset: Asset) -> tuple[bool, str]:
    """Re-scrape a single asset's URL and update current_value, last_unit_price, last_priced_at.

    Returns (True, "") on success, (False, error_message) otherwise. Manual assets are
    rejected at this layer; the calling view should hide the refresh button for them
    but defense-in-depth here protects against URL tampering or future callers.
    """
    if asset.kind != "scraped":
        return False, "manual assets have no source URL to refresh"
    if not asset.source_url:
        return False, "no source_url"
    scraper = get_scraper("css")
    try:
        result = scraper.fetch(asset.source_url, selector=asset.css_selector or "")
    except Exception as exc:
        return False, str(exc)
    asset.last_unit_price = result.price.quantize(Decimal("0.0001"))
    asset.current_value = (result.price * asset.quantity).quantize(Decimal("0.01"))
    asset.last_priced_at = result.at
    asset.save(update_fields=["last_unit_price", "current_value", "last_priced_at"])
    _snapshot(asset)
    return True, ""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec web pytest apps/assets/tests/test_services.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/assets/services.py apps/assets/tests/test_services.py
git commit -m "feat(assets): refresh_one_asset service for per-asset refresh

Tuple return (ok, err) instead of the bulk RefreshResult — single-asset
callers don't care about aggregate counts. Rejects manual assets so a
URL-tampering attempt still gets a graceful error."
```

---

## Task 4: Add `build_asset_value_series` helper

**Files:**
- Modify: `apps/assets/services.py` (append helper)
- Test: `apps/assets/tests/test_services.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/assets/tests/test_services.py`:

```python
from datetime import datetime as _dt, timedelta as _td, timezone as _tz, date as _date


@pytest.mark.django_db
def test_build_asset_value_series_returns_30_days_by_default():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(user=user, kind="manual", name="X", current_value=Decimal("100"))
    from apps.assets.services import build_asset_value_series
    series = build_asset_value_series(a)
    assert len(series) == 30


@pytest.mark.django_db
def test_build_asset_value_series_forward_fills_from_seed():
    """If the only snapshot is older than the window, every day in the window
    should report that snapshot's value (forward-fill from seed)."""
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = Asset.objects.create(user=user, kind="manual", name="X", current_value=Decimal("0"))
    AssetPriceSnapshot.objects.create(
        asset=a, at=_dt.now(tz=_tz.utc) - _td(days=60), value=Decimal("500"),
    )
    from apps.assets.services import build_asset_value_series
    series = build_asset_value_series(a, days=30)
    assert all(v == Decimal("500") for v in series)


@pytest.mark.django_db
def test_build_asset_value_series_picks_up_in_window_changes():
    """A snapshot inside the window updates the value from that day forward."""
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = Asset.objects.create(user=user, kind="manual", name="X", current_value=Decimal("0"))
    now = _dt.now(tz=_tz.utc)
    AssetPriceSnapshot.objects.create(asset=a, at=now - _td(days=60), value=Decimal("100"))
    AssetPriceSnapshot.objects.create(asset=a, at=now - _td(days=10), value=Decimal("200"))
    from apps.assets.services import build_asset_value_series
    series = build_asset_value_series(a, days=30)
    # Series is recent-last; days 0..19 should be 100, days 20..29 should be 200.
    # Allow for off-by-one if "today" overlaps the snapshot day.
    assert series[0] == Decimal("100")
    assert series[-1] == Decimal("200")
    # Some day within the last 11 should be 200.
    assert any(v == Decimal("200") for v in series[-11:])


@pytest.mark.django_db
def test_build_asset_value_series_empty_when_no_snapshots():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = Asset.objects.create(user=user, kind="manual", name="X", current_value=Decimal("0"))
    # No snapshots at all (edge case — create_asset normally produces one).
    from apps.assets.services import build_asset_value_series
    series = build_asset_value_series(a, days=30)
    # The chart helper renders a "not enough data" placeholder when len < 2,
    # so returning all-zeros or an empty list both work. We pick all-zeros for
    # consistency with the dashboard pipeline (which also seeds zero).
    assert len(series) == 30
    assert all(v == Decimal("0") for v in series)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec web pytest apps/assets/tests/test_services.py -v -k "build_asset_value_series"
```

Expected: 4 import-error failures.

- [ ] **Step 3: Implement `build_asset_value_series`**

In `apps/assets/services.py`, add at the top (right under the existing imports):

```python
from datetime import date as _date, timedelta as _td
```

Then append after `refresh_one_asset`:

```python
def build_asset_value_series(asset: Asset, days: int = 30) -> list[Decimal]:
    """Forward-filled daily series of this asset's value over `days` days, ending today.

    Mirrors the algorithm in apps/dashboard/services.py for a single asset:
      - seed with the latest AssetPriceSnapshot strictly before the window
      - walk each day, applying any in-window snapshot (latest wins per day)
      - forward-fill otherwise

    Returns a list of Decimals, oldest-first / recent-last, length == `days`.
    Empty/missing history yields a list of zeros (the chart helper's <2-points
    fallback covers the "no useful chart" UX).
    """
    today = _date.today()
    cutoff = today - _td(days=days - 1)  # series[0] corresponds to `cutoff`

    # Seed: latest snapshot before the window, or the earliest snapshot in-window if none-before.
    seed_decimal = Decimal("0")
    last_before = (
        AssetPriceSnapshot.objects
        .filter(asset=asset, at__date__lt=cutoff)
        .order_by("-at").only("value").first()
    )
    if last_before:
        seed_decimal = last_before.value
    else:
        first_in = (
            AssetPriceSnapshot.objects
            .filter(asset=asset, at__date__gte=cutoff)
            .order_by("at").only("value").first()
        )
        if first_in:
            seed_decimal = first_in.value

    # Snapshots inside the window, latest wins per day.
    in_window: dict[_date, Decimal] = {}
    for snap in (
        AssetPriceSnapshot.objects
        .filter(asset=asset, at__date__gte=cutoff)
        .only("at", "value")
        .order_by("at")
    ):
        in_window[snap.at.date()] = snap.value

    series: list[Decimal] = []
    current = seed_decimal
    for i in range(days):
        d = cutoff + _td(days=i)
        if d in in_window:
            current = in_window[d]
        series.append(current)
    return series
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec web pytest apps/assets/tests/test_services.py -v -k "build_asset_value_series"
```

Expected: 4 passes.

- [ ] **Step 5: Run full assets test suite to confirm no regressions**

```bash
docker compose exec web pytest apps/assets/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/assets/services.py apps/assets/tests/test_services.py
git commit -m "feat(assets): build_asset_value_series for per-asset chart data

30-day forward-filled series (oldest-first) built from AssetPriceSnapshot.
Mirrors the dashboard's single-asset walk algorithm. Empty history yields
all zeros so the chart helper's <2-points fallback can render."
```

---

## Task 5: Refactor chart helper for reuse

**Files:**
- Modify: `apps/dashboard/templatetags/networth_chart.py`
- Test: `apps/dashboard/tests/test_networth_chart.py` (extend)

- [ ] **Step 1: Skim the existing test file to learn the existing tests' shape**

```bash
docker compose exec web cat apps/dashboard/tests/test_networth_chart.py | head -50
```

(Tests cover the existing `networth_chart_svg` shape — they should all keep passing because we're keeping the wrapper.)

- [ ] **Step 2: Write the failing tests for the new generalized API**

Append to `apps/dashboard/tests/test_networth_chart.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
docker compose exec web pytest apps/dashboard/tests/test_networth_chart.py -v -k "value_chart"
```

Expected: 5 import-error failures (plus existing tests still passing).

- [ ] **Step 4: Refactor the chart helper**

Open `apps/dashboard/templatetags/networth_chart.py`. Make these changes in order:

**(a)** Rename the function `networth_chart_svg` → `value_chart_svg` and add the `value_label` kwarg.

Find the function signature (line 13):

```python
def networth_chart_svg(values: Iterable[Decimal], days: int = 30, width: int = 600, height: int = 320, end_date: date | None = None) -> str:
```

Replace with:

```python
def value_chart_svg(values: Iterable[Decimal], days: int = 30, width: int = 600, height: int = 320, end_date: date | None = None, value_label: str = "Value") -> str:
```

**(b)** Use `value_label` inside the rendered tooltip header. Find this block (around lines 158-166):

```python
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
```

Replace with:

```python
    # Tooltip element (HTML, positioned absolutely). Includes a label header
    # so callers can distinguish "Net worth" vs "Asset value" etc.
    from html import escape as _html_escape
    label_html = _html_escape(value_label)
    parts.append(
        f'<div class="nw-tooltip" style="position: absolute; display: none; '
        f'background: var(--surface, #161616); border: 1px solid var(--border, #333); '
        f'border-radius: 4px; padding: 6px 10px; font-size: 11px; '
        f'pointer-events: none; box-shadow: 0 4px 12px rgba(0,0,0,0.3); white-space: nowrap;">'
        f'<div class="nw-tt-date" style="color: var(--muted, #888); font-size: 10px; margin-bottom: 2px;"></div>'
        f'<div class="nw-tt-label" style="color: var(--muted, #888); font-size: 10px; margin-bottom: 2px;">{label_html}</div>'
        f'<div class="nw-tt-value" style="color: var(--accent-positive, #88a877); font-weight: 600;"></div>'
        f'</div>'
    )
```

**(c)** Add the wrapper for backward compatibility. After the function body ends (the line returning `mark_safe("".join(parts))` at line 232), add:

```python
def networth_chart_svg(values: Iterable[Decimal], days: int = 30, width: int = 600, height: int = 320, end_date: date | None = None) -> str:
    """Backward-compatible wrapper that calls value_chart_svg with the
    'Net worth' label. Existing dashboard callers keep working unchanged."""
    return value_chart_svg(values, days=days, width=width, height=height, end_date=end_date, value_label="Net worth")
```

**(d)** Register the new template tag. Find the existing tag at the bottom (around line 235):

```python
@register.simple_tag
def networth_chart(values, days=30):
    return networth_chart_svg(values, days=int(days))
```

Add right after:

```python
@register.simple_tag
def value_chart(values, days=30, value_label="Value"):
    return value_chart_svg(values, days=int(days), value_label=value_label)
```

- [ ] **Step 5: Run the chart tests**

```bash
docker compose exec web pytest apps/dashboard/tests/test_networth_chart.py -v
```

Expected: all pass (existing + new).

- [ ] **Step 6: Run the full dashboard test suite as a regression check**

```bash
docker compose exec web pytest apps/dashboard/ -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add apps/dashboard/templatetags/networth_chart.py apps/dashboard/tests/test_networth_chart.py
git commit -m "refactor(dashboard): generalize chart helper into value_chart_svg

Adds value_label kwarg + new {% value_chart %} tag. networth_chart_svg
is now a thin wrapper passing 'Net worth' as the label, so the dashboard
template's {% networth_chart history %} call is untouched."
```

---

## Task 6: Add `asset_detail` view + URL

**Files:**
- Modify: `apps/assets/urls.py`
- Modify: `apps/assets/views.py`
- Test: `apps/assets/tests/test_views.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/assets/tests/test_views.py`:

```python
def test_asset_detail_renders_for_owner(alice, alice_client):
    a = Asset.objects.create(user=alice, kind="manual", name="Painting", current_value=Decimal("5000"))
    r = alice_client.get(reverse("assets:detail", args=[a.id]))
    assert r.status_code == 200
    assert b"Painting" in r.content
    assert r.context["asset"].id == a.id
    assert "series" in r.context


def test_asset_detail_404_for_other_user(alice, bob_client):
    a = Asset.objects.create(user=alice, kind="manual", name="Painting", current_value=Decimal("5000"))
    r = bob_client.get(reverse("assets:detail", args=[a.id]))
    assert r.status_code == 404


def test_asset_detail_anonymous_redirects():
    c = Client()
    # Use a synthetic id; auth check fires before lookup.
    r = c.get(reverse("assets:detail", args=[1]))
    assert r.status_code == 302
    assert "/login/" in r["Location"]
```

- [ ] **Step 2: Add the URL pattern**

In `apps/assets/urls.py`, add the detail route. After the existing `add/` route (line 9), insert:

```python
    path("<int:asset_id>/", views.asset_detail, name="detail"),
```

The full file should now be:

```python
from django.urls import path

from . import views

app_name = "assets"

urlpatterns = [
    path("", views.assets_list, name="list"),
    path("add/", views.add_asset, name="add"),
    path("<int:asset_id>/", views.asset_detail, name="detail"),
    path("<int:asset_id>/edit/", views.edit_asset, name="edit"),
    path("<int:asset_id>/delete/", views.delete_asset_view, name="delete"),
    path("refresh/", views.refresh_prices, name="refresh"),
]
```

- [ ] **Step 3: Run the tests to verify they fail (with attribute error)**

```bash
docker compose exec web pytest apps/assets/tests/test_views.py -v -k "asset_detail"
```

Expected: failures referencing `views.asset_detail` not defined.

- [ ] **Step 4: Add the view**

In `apps/assets/views.py`, add the new view. Update the imports at the top to include `build_asset_value_series`:

Find:

```python
from .services import create_asset, delete_asset, refresh_scraped_assets, update_asset
```

Replace with:

```python
from .services import (
    build_asset_value_series, create_asset, delete_asset, refresh_scraped_assets, update_asset,
)
```

Then add the new view, immediately after `assets_list` (around line 32):

```python
@login_required
def asset_detail(request, asset_id):
    asset = get_object_or_404(Asset.objects.for_user(request.user), pk=asset_id)
    series = build_asset_value_series(asset)
    return render(request, "assets/asset_detail.html", {
        "asset": asset,
        "series": series,
    })
```

- [ ] **Step 5: Run the tests**

The template doesn't exist yet, so two of the three tests will still fail at render time. We'll fix that in Task 7. For now, run only the auth/404 tests:

```bash
docker compose exec web pytest apps/assets/tests/test_views.py::test_asset_detail_404_for_other_user apps/assets/tests/test_views.py::test_asset_detail_anonymous_redirects -v
```

Expected: 2 passes.

- [ ] **Step 6: Commit**

```bash
git add apps/assets/views.py apps/assets/urls.py apps/assets/tests/test_views.py
git commit -m "feat(assets): asset_detail view + URL

Renders the asset, an empty 30-day value series. Template comes next.
Auth + isolation tests pass; full render test deferred to template task."
```

---

## Task 7: Add `refresh_one` view + URL

**Files:**
- Modify: `apps/assets/urls.py`
- Modify: `apps/assets/views.py`
- Test: `apps/assets/tests/test_views.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/assets/tests/test_views.py`:

```python
def test_refresh_one_post_triggers_service(alice, alice_client):
    a = Asset.objects.create(
        user=alice, kind="scraped", name="Gold",
        source_url="https://example.com/gold", quantity=Decimal("2"),
    )
    with patch("apps.assets.views.refresh_one_asset") as mock_refresh:
        mock_refresh.return_value = (True, "")
        r = alice_client.post(reverse("assets:refresh_one", args=[a.id]))
    assert r.status_code == 302
    assert reverse("assets:detail", args=[a.id]) in r["Location"]
    mock_refresh.assert_called_once()
    # First positional arg should be the Asset instance.
    called_arg = mock_refresh.call_args.args[0]
    assert called_arg.id == a.id


def test_refresh_one_get_not_allowed(alice, alice_client):
    a = Asset.objects.create(
        user=alice, kind="scraped", name="Gold",
        source_url="https://example.com/gold", quantity=Decimal("1"),
    )
    r = alice_client.get(reverse("assets:refresh_one", args=[a.id]))
    assert r.status_code == 405


def test_refresh_one_404_for_other_user(alice, bob_client):
    a = Asset.objects.create(
        user=alice, kind="scraped", name="Gold",
        source_url="https://example.com/gold", quantity=Decimal("1"),
    )
    r = bob_client.post(reverse("assets:refresh_one", args=[a.id]))
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec web pytest apps/assets/tests/test_views.py -v -k "refresh_one"
```

Expected: 3 failures (URL not registered).

- [ ] **Step 3: Add the URL**

In `apps/assets/urls.py`, add the route between `delete/` and the global `refresh/`:

```python
    path("<int:asset_id>/refresh/", views.refresh_one, name="refresh_one"),
```

Full file:

```python
from django.urls import path

from . import views

app_name = "assets"

urlpatterns = [
    path("", views.assets_list, name="list"),
    path("add/", views.add_asset, name="add"),
    path("<int:asset_id>/", views.asset_detail, name="detail"),
    path("<int:asset_id>/edit/", views.edit_asset, name="edit"),
    path("<int:asset_id>/delete/", views.delete_asset_view, name="delete"),
    path("<int:asset_id>/refresh/", views.refresh_one, name="refresh_one"),
    path("refresh/", views.refresh_prices, name="refresh"),
]
```

- [ ] **Step 4: Add the view**

In `apps/assets/views.py`, update the services import to include `refresh_one_asset`:

Find:

```python
from .services import (
    build_asset_value_series, create_asset, delete_asset, refresh_scraped_assets, update_asset,
)
```

Replace with:

```python
from .services import (
    build_asset_value_series, create_asset, delete_asset, refresh_one_asset,
    refresh_scraped_assets, update_asset,
)
```

Then append the view at the end of the file (after `refresh_prices`):

```python
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

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker compose exec web pytest apps/assets/tests/test_views.py -v -k "refresh_one"
```

Expected: 3 passes.

- [ ] **Step 6: Commit**

```bash
git add apps/assets/views.py apps/assets/urls.py apps/assets/tests/test_views.py
git commit -m "feat(assets): per-asset refresh endpoint

POST /assets/<id>/refresh/ → run scraper for one asset, redirect back to
detail page with a success/error message."
```

---

## Task 8: Build the asset detail template

**Files:**
- Create: `apps/assets/templates/assets/asset_detail.html`
- Test: `apps/assets/tests/test_views.py`

- [ ] **Step 1: Write the failing render test**

Append to `apps/assets/tests/test_views.py`:

```python
def test_asset_detail_renders_template_and_chart(alice, alice_client):
    """End-to-end: detail page renders without 500, includes the chart, the unit
    price (for scraped), and the last-updated stamp."""
    from datetime import datetime, timezone as tz
    a = Asset.objects.create(
        user=alice, kind="scraped", name="Gold Eagle",
        source_url="https://example.com/gold",
        quantity=Decimal("5"),
        last_unit_price=Decimal("2000.0000"),
        current_value=Decimal("10000.00"),
        last_priced_at=datetime(2026, 4, 30, tzinfo=tz.utc),
    )
    r = alice_client.get(reverse("assets:detail", args=[a.id]))
    assert r.status_code == 200
    body = r.content.decode()
    assert "Gold Eagle" in body
    # Unit price + total value rendered via the money filter.
    assert "$10,000" in body
    assert "$2,000" in body
    # Last-updated text.
    assert "Apr" in body  # Apr 30 from last_priced_at
    # Refresh button form for scraped asset.
    assert "/refresh/" in body
    # Chart container — always renders when series has 2+ points.
    # (build_asset_value_series returns 30 entries, so always >=2.)
    assert "<svg" in body or "Not enough" in body


def test_asset_detail_manual_hides_refresh_and_unit_price(alice, alice_client):
    a = Asset.objects.create(user=alice, kind="manual", name="Camry", current_value=Decimal("18000"))
    r = alice_client.get(reverse("assets:detail", args=[a.id]))
    body = r.content.decode()
    assert "Camry" in body
    assert "$18,000" in body
    # No refresh button on manual.
    assert reverse("assets:refresh_one", args=[a.id]) not in body
    # No "Unit price" stat card.
    assert "Unit price" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec web pytest apps/assets/tests/test_views.py -v -k "asset_detail_renders_template or asset_detail_manual_hides"
```

Expected: 2 failures (`TemplateDoesNotExist` for `assets/asset_detail.html`).

- [ ] **Step 3: Create the template**

Create `apps/assets/templates/assets/asset_detail.html`:

```django
{% extends "base.html" %}
{% load money %}
{% load value_chart %}
{% block title %}{{ asset.name }}{% endblock %}
{% block content %}
<div class="max-w-3xl mx-auto">
  <a href="{% url 'assets:list' %}" class="text-sm" style="color: var(--muted);">← Assets</a>

  <div class="flex items-baseline gap-3 mt-2 mb-6 flex-wrap">
    <h1 class="text-2xl font-bold">{{ asset.name }}</h1>
    <span class="text-xs px-2 py-0.5 rounded" style="border: 1px solid var(--border); color: var(--muted);">
      {% if asset.kind == 'scraped' %}📈 Scraped{% else %}✎ Manual{% endif %}
    </span>
  </div>

  {% if messages %}
    {% for message in messages %}
    <div class="border p-3 rounded text-sm mb-4"
         style="{% if message.tags == 'error' %}background: var(--tint-lia); border-color: var(--accent-lia); color: var(--accent-lia);{% elif message.tags == 'warning' %}background: var(--tint-assets); border-color: var(--accent-assets); color: var(--accent-assets);{% else %}background: var(--tint-positive); border-color: var(--accent-positive); color: var(--accent-positive);{% endif %}">
      {{ message }}
    </div>
    {% endfor %}
  {% endif %}

  {# Stat cards row #}
  <div class="grid {% if asset.kind == 'scraped' %}grid-cols-1 sm:grid-cols-3{% else %}grid-cols-1 sm:grid-cols-2{% endif %} gap-3 mb-6">
    <div class="rounded p-4 border" style="background: var(--surface); border-color: var(--border);">
      <div class="text-[10px] uppercase tracking-widest" style="color: var(--muted);">Current value</div>
      <div class="text-2xl font-bold num mt-1" style="color: var(--accent-assets);">{{ asset.current_value|money }}</div>
    </div>

    {% if asset.kind == 'scraped' %}
    <div class="rounded p-4 border" style="background: var(--surface); border-color: var(--border);">
      <div class="text-[10px] uppercase tracking-widest" style="color: var(--muted);">Unit price</div>
      <div class="text-2xl font-bold num mt-1">
        {% if asset.last_unit_price %}{{ asset.last_unit_price|money }}{% else %}—{% endif %}
      </div>
      <div class="text-xs mt-1 num" style="color: var(--muted);">× {{ asset.quantity }} {{ asset.unit }}</div>
    </div>
    {% endif %}

    <div class="rounded p-4 border" style="background: var(--surface); border-color: var(--border);">
      <div class="text-[10px] uppercase tracking-widest" style="color: var(--muted);">Last updated</div>
      {% if asset.last_priced_at %}
      <div class="text-base font-semibold mt-1" title="{{ asset.last_priced_at|date:'c' }}">{{ asset.last_priced_at|date:"M j, Y" }}</div>
      <div class="text-xs mt-1" style="color: var(--muted);">{{ asset.last_priced_at|timesince }} ago</div>
      {% else %}
      <div class="text-base font-semibold mt-1" style="color: var(--muted);">Never</div>
      {% endif %}
    </div>
  </div>

  {# Refresh action (scraped only) #}
  {% if asset.kind == 'scraped' %}
  <form method="post" action="{% url 'assets:refresh_one' asset.id %}" class="mb-6">
    {% csrf_token %}
    <button type="submit" class="text-sm border px-3 py-2 rounded" style="border-color: var(--border); color: var(--muted);">⟳ Refresh now</button>
  </form>
  {% endif %}

  {# Chart #}
  <div class="rounded p-4 border mb-6" style="background: var(--surface); border-color: var(--border);">
    <div class="text-[10px] uppercase tracking-widest mb-2" style="color: var(--muted);">Value history (30 days)</div>
    {% value_chart series value_label="Asset value" %}
  </div>

  {# Notes #}
  {% if asset.notes %}
  <div class="rounded p-4 border mb-6" style="background: var(--surface); border-color: var(--border);">
    <div class="text-[10px] uppercase tracking-widest mb-2" style="color: var(--muted);">Notes</div>
    <div class="text-sm">{{ asset.notes }}</div>
  </div>
  {% endif %}

  {# Edit / Delete actions #}
  <div class="flex items-center gap-3">
    <a href="{% url 'assets:edit' asset.id %}" class="font-bold px-4 py-2 rounded" style="background: var(--accent-positive); color: var(--bg);">Edit</a>
    <a href="{% url 'assets:delete' asset.id %}" class="text-sm" style="color: var(--accent-negative);">Delete</a>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Run the render tests**

```bash
docker compose exec web pytest apps/assets/tests/test_views.py -v -k "asset_detail"
```

Expected: all 5 detail tests pass (including the earlier ones from Task 6 that were waiting on the template).

- [ ] **Step 5: Run the full assets test suite**

```bash
docker compose exec web pytest apps/assets/ -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/assets/templates/assets/asset_detail.html apps/assets/tests/test_views.py
git commit -m "feat(assets): asset detail page template

Stat cards (current value, unit price [scraped only], last updated),
refresh button (scraped only), 30-day value chart, notes block, edit/delete
actions. Manual assets get a 2-card row; scraped get 3 cards."
```

---

## Task 9: Link asset names from list to detail page

**Files:**
- Modify: `apps/assets/templates/assets/assets_list.html`
- Test: `apps/assets/tests/test_views.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/assets/tests/test_views.py`:

```python
def test_asset_list_name_links_to_detail(alice, alice_client):
    a = Asset.objects.create(user=alice, kind="manual", name="Linkable Painting", current_value=Decimal("100"))
    r = alice_client.get(reverse("assets:list"))
    body = r.content.decode()
    assert reverse("assets:detail", args=[a.id]) in body
    # The name should appear inside an <a> tag pointing at detail.
    import re
    pattern = re.compile(
        r'<a[^>]+href="' + re.escape(reverse("assets:detail", args=[a.id])) + r'"[^>]*>[^<]*Linkable Painting',
        re.DOTALL,
    )
    assert pattern.search(body), f"Asset name not wrapped in detail link: body excerpt = {body[:500]}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec web pytest apps/assets/tests/test_views.py::test_asset_list_name_links_to_detail -v
```

Expected: failure.

- [ ] **Step 3: Update the desktop table cell**

In `apps/assets/templates/assets/assets_list.html`, find the desktop name cell (around line 50-53):

```django
          <td class="px-4 py-3">
            <div class="font-medium">{{ a.name }}</div>
            {% if a.notes %}<div class="text-xs" style="color: var(--muted);">{{ a.notes }}</div>{% endif %}
          </td>
```

Replace with:

```django
          <td class="px-4 py-3">
            <a href="{% url 'assets:detail' a.id %}" class="font-medium hover:underline" style="color: var(--text);">{{ a.name }}</a>
            {% if a.notes %}<div class="text-xs" style="color: var(--muted);">{{ a.notes }}</div>{% endif %}
          </td>
```

- [ ] **Step 4: Update the mobile card name**

In the same file, find the mobile name block (around line 76-79):

```django
          <div class="font-medium truncate">
            <span class="mr-1">{% if a.kind == 'scraped' %}📈{% else %}✎{% endif %}</span>{{ a.name }}
          </div>
```

Replace with:

```django
          <a href="{% url 'assets:detail' a.id %}" class="font-medium truncate hover:underline" style="color: var(--text); display: block;">
            <span class="mr-1">{% if a.kind == 'scraped' %}📈{% else %}✎{% endif %}</span>{{ a.name }}
          </a>
```

- [ ] **Step 5: Run the test**

```bash
docker compose exec web pytest apps/assets/tests/test_views.py::test_asset_list_name_links_to_detail -v
```

Expected: pass.

- [ ] **Step 6: Run the full assets suite**

```bash
docker compose exec web pytest apps/assets/ -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add apps/assets/templates/assets/assets_list.html apps/assets/tests/test_views.py
git commit -m "feat(assets): link asset names on list to new detail page

Desktop: name cell becomes a link. Mobile: the name block becomes a link
(action icons stay outside so taps on ✎/🗑 don't navigate to detail)."
```

---

## Task 10: Final verification — rebuild, migrate, smoke-test

**Files:** none (operational task)

- [ ] **Step 1: Run the full test suite**

```bash
docker compose exec web pytest -q
```

Expected: all pass. Anything failing is a regression introduced earlier; fix before proceeding.

- [ ] **Step 2: Rebuild the web image**

```bash
docker compose build web
```

- [ ] **Step 3: Restart the web container**

```bash
docker compose up -d
```

- [ ] **Step 4: Run the migration on the running database**

```bash
docker compose exec web python manage.py migrate assets
```

Expected: `Applying assets.0002_asset_last_unit_price... OK`. The data migration silently backfills.

- [ ] **Step 5: Manual smoke test in browser**

1. Navigate to `/assets/`. Click an asset name (not the ✎ icon). Should land on `/assets/<id>/`.
2. On the detail page:
   - Confirm "Current value" stat card shows the same number as the list page.
   - For a scraped asset: confirm "Unit price" stat card shows a value (backfilled from `current_value / quantity`).
   - Confirm "Last updated" card shows a date and "X days ago" sublabel.
   - Confirm the chart renders below the stat cards.
   - Click "⟳ Refresh now" — page reloads with a "Refreshed X" success message; "Last updated" stamp moves to "0 minutes ago".
   - Click "Edit" — lands on the existing edit form unchanged.
3. Open a manual asset's detail page. Confirm: 2 stat cards (no "Unit price"), no refresh button, chart still renders.
4. Navigate to `/dashboard/`. Confirm the existing net-worth chart still renders unchanged (sanity check on chart helper refactor).

- [ ] **Step 6: Final commit if any fixups needed**

If the manual smoke test surfaces no issues, no further commit is required.

---

## Done

- All tests pass: `docker compose exec web pytest -q`
- Migration applied on running container
- Manual flows verified (asset name → detail → refresh → edit)
- Dashboard chart unaffected
- Nine commits on branch (one per task; Task 10 is verification, not code)
