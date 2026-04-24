from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.assets.models import Asset, AssetPriceSnapshot

User = get_user_model()


@pytest.fixture
def two_users_with_assets(db):
    alice = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    bob = User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")

    alice_gold = Asset.objects.create(
        user=alice, kind="scraped", name="1oz Gold Eagle",
        source_url="https://example.com/gold", quantity=Decimal("3"),
        current_value=Decimal("6000"),
    )
    alice_car = Asset.objects.create(
        user=alice, kind="manual", name="Alice's car",
        current_value=Decimal("18000"),
    )
    bob_art = Asset.objects.create(
        user=bob, kind="manual", name="Bob's painting",
        current_value=Decimal("5000"),
    )

    AssetPriceSnapshot.objects.create(asset=alice_gold, at=datetime(2026, 4, 24, tzinfo=timezone.utc), value=Decimal("6000"))
    AssetPriceSnapshot.objects.create(asset=bob_art, at=datetime(2026, 4, 24, tzinfo=timezone.utc), value=Decimal("5000"))

    return alice, bob, alice_gold, alice_car, bob_art


def test_asset_for_user_isolates(two_users_with_assets):
    alice, bob, *_ = two_users_with_assets
    assert set(Asset.objects.for_user(alice).values_list("name", flat=True)) == {"1oz Gold Eagle", "Alice's car"}
    assert list(Asset.objects.for_user(bob).values_list("name", flat=True)) == ["Bob's painting"]


def test_snapshot_for_user_isolates(two_users_with_assets):
    alice, bob, *_ = two_users_with_assets
    assert AssetPriceSnapshot.objects.for_user(alice).count() == 1
    assert AssetPriceSnapshot.objects.for_user(bob).count() == 1
