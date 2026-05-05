from dataclasses import dataclass
from datetime import date as _date, timedelta as _td
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.providers.scrapers.registry import get as get_scraper

from .models import Asset, AssetPriceSnapshot


@dataclass
class RefreshResult:
    updated: int
    failed: list[tuple[int, str]]


def create_asset(*, user, kind: str, name: str, **fields) -> Asset:
    """fields may include: notes, quantity, unit, source_url, css_selector, current_value."""
    asset = Asset(user=user, kind=kind, name=name, **{k: v for k, v in fields.items() if v is not None})
    asset.save()
    _snapshot(asset)
    return asset


def update_asset(asset: Asset, **fields) -> Asset:
    """Update mutable fields on an existing asset. For manual assets, supply current_value;
    for scraped, supply source_url / css_selector / quantity / unit. ``kind`` is immutable."""
    for field, value in fields.items():
        if field == "kind":
            continue
        setattr(asset, field, value)
    asset.last_priced_at = timezone.now() if asset.kind == "manual" else asset.last_priced_at
    asset.save()
    if asset.kind == "manual":
        _snapshot(asset)
    return asset


def refresh_scraped_assets(*, user) -> RefreshResult:
    """Hit every scraped asset's URL for this user; update current_value + snapshot."""
    assets = list(Asset.objects.for_user(user).filter(kind="scraped"))
    scraper = get_scraper("css")
    updated = 0
    failed: list[tuple[int, str]] = []

    with transaction.atomic():
        for a in assets:
            if not a.source_url:
                failed.append((a.id, "no source_url"))
                continue
            try:
                result = scraper.fetch(a.source_url, selector=a.css_selector or "")
            except Exception as exc:
                failed.append((a.id, str(exc)))
                continue
            a.last_unit_price = result.price.quantize(Decimal("0.0001"))
            a.current_value = (result.price * a.quantity).quantize(Decimal("0.01"))
            a.last_priced_at = result.at
            a.save(update_fields=["last_unit_price", "current_value", "last_priced_at"])
            _snapshot(a)
            updated += 1

    return RefreshResult(updated=updated, failed=failed)


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


def delete_asset(asset: Asset) -> None:
    asset.delete()


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


def _snapshot(asset: Asset) -> None:
    AssetPriceSnapshot.objects.create(asset=asset, at=timezone.now(), value=asset.current_value)
