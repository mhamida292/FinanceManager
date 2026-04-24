from datetime import datetime, timezone as tz
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.assets.models import Asset, AssetPriceSnapshot
from apps.assets.services import (
    create_asset, delete_asset, refresh_scraped_assets, update_asset,
)
from apps.providers.scrapers import registry as scraper_registry
from apps.providers.scrapers.base import ScrapedPrice

User = get_user_model()


class _FakeScraper:
    name = "css"
    prices_by_url: dict[str, Decimal] = {}
    errors_by_url: dict[str, str] = {}

    def fetch(self, url: str, selector: str = ""):
        if url in self.errors_by_url:
            raise RuntimeError(self.errors_by_url[url])
        return ScrapedPrice(
            source_url=url, price=self.prices_by_url[url], at=datetime.now(tz=tz.utc),
        )


@pytest.fixture
def fake_scraper():
    original = scraper_registry._REGISTRY.copy()
    _FakeScraper.prices_by_url = {}
    _FakeScraper.errors_by_url = {}
    scraper_registry._REGISTRY["css"] = _FakeScraper
    yield _FakeScraper
    scraper_registry._REGISTRY.clear()
    scraper_registry._REGISTRY.update(original)


@pytest.mark.django_db
def test_create_manual_asset_records_snapshot():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(user=user, kind="manual", name="Car", current_value=Decimal("18000"))
    assert a.current_value == Decimal("18000")
    assert AssetPriceSnapshot.objects.filter(asset=a).count() == 1


@pytest.mark.django_db
def test_create_scraped_asset_stores_url_and_quantity():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(
        user=user, kind="scraped", name="Gold Eagle",
        source_url="https://example.com/gold", quantity=Decimal("3"), unit="oz",
    )
    assert a.source_url == "https://example.com/gold"
    assert a.quantity == Decimal("3")
    assert a.unit == "oz"


@pytest.mark.django_db
def test_update_manual_asset_snapshots_new_value():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(user=user, kind="manual", name="Car", current_value=Decimal("18000"))
    update_asset(a, current_value=Decimal("16500"))
    a.refresh_from_db()
    assert a.current_value == Decimal("16500")
    assert AssetPriceSnapshot.objects.filter(asset=a).count() == 2


@pytest.mark.django_db
def test_refresh_scraped_hits_url_and_multiplies_by_quantity(fake_scraper):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(
        user=user, kind="scraped", name="Gold Eagle",
        source_url="https://example.com/gold", quantity=Decimal("3"),
    )
    fake_scraper.prices_by_url = {"https://example.com/gold": Decimal("2734.50")}

    result = refresh_scraped_assets(user=user)

    assert result.updated == 1
    assert result.failed == []
    a.refresh_from_db()
    assert a.current_value == Decimal("8203.50")


@pytest.mark.django_db
def test_refresh_skips_manual_assets(fake_scraper):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    create_asset(user=user, kind="manual", name="Car", current_value=Decimal("18000"))
    result = refresh_scraped_assets(user=user)
    assert result.updated == 0
    assert result.failed == []


@pytest.mark.django_db
def test_refresh_records_failure_without_breaking_others(fake_scraper):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a_good = create_asset(
        user=user, kind="scraped", name="OK",
        source_url="https://good.example/", quantity=Decimal("1"),
    )
    a_bad = create_asset(
        user=user, kind="scraped", name="BAD",
        source_url="https://bad.example/", quantity=Decimal("1"),
    )
    fake_scraper.prices_by_url = {"https://good.example/": Decimal("100")}
    fake_scraper.errors_by_url = {"https://bad.example/": "boom"}

    result = refresh_scraped_assets(user=user)

    assert result.updated == 1
    assert len(result.failed) == 1
    assert result.failed[0][0] == a_bad.id
    a_good.refresh_from_db()
    assert a_good.current_value == Decimal("100.00")


@pytest.mark.django_db
def test_delete_asset_cascades_snapshots():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(user=user, kind="manual", name="X", current_value=Decimal("1"))
    update_asset(a, current_value=Decimal("2"))
    assert AssetPriceSnapshot.objects.filter(asset=a).count() == 2
    delete_asset(a)
    assert AssetPriceSnapshot.objects.count() == 0
