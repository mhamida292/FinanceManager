from dataclasses import dataclass
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
            a.current_value = (result.price * a.quantity).quantize(Decimal("0.01"))
            a.last_priced_at = result.at
            a.save(update_fields=["current_value", "last_priced_at"])
            _snapshot(a)
            updated += 1

    return RefreshResult(updated=updated, failed=failed)


def delete_asset(asset: Asset) -> None:
    asset.delete()


def _snapshot(asset: Asset) -> None:
    AssetPriceSnapshot.objects.create(asset=asset, at=timezone.now(), value=asset.current_value)
