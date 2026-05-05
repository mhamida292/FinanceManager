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
    assert a.current_value == Decimal("8203.50")  # quantity x unit price


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
