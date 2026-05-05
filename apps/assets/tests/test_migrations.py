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
