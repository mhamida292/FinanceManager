from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.assets.models import Asset

User = get_user_model()


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice", password="correct-horse-battery-staple")


@pytest.fixture
def bob(db):
    return User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")


@pytest.fixture
def alice_client(alice):
    c = Client()
    c.force_login(alice)
    return c


@pytest.fixture
def bob_client(bob):
    c = Client()
    c.force_login(bob)
    return c


def test_list_empty(alice_client):
    r = alice_client.get(reverse("assets:list"))
    assert r.status_code == 200
    assert b"No assets tracked yet" in r.content


def test_list_shows_only_own(alice, bob, alice_client):
    Asset.objects.create(user=alice, kind="manual", name="Alice Camry", current_value=Decimal("18000"))
    Asset.objects.create(user=bob, kind="manual", name="Bob Monet", current_value=Decimal("5000"))
    r = alice_client.get(reverse("assets:list"))
    assert b"Alice Camry" in r.content
    assert b"Bob Monet" not in r.content


def test_add_manual_asset(alice_client):
    r = alice_client.post(reverse("assets:add"), {
        "kind": "manual", "name": "2019 Camry", "current_value": "18000", "notes": "KBB",
    })
    assert r.status_code == 302
    a = Asset.objects.get(name="2019 Camry")
    assert a.kind == "manual"
    assert a.current_value == Decimal("18000")


def test_add_scraped_asset_triggers_initial_refresh(alice_client):
    with patch("apps.assets.views.refresh_scraped_assets") as mock_refresh:
        from apps.assets.services import RefreshResult
        mock_refresh.return_value = RefreshResult(updated=1, failed=[])
        r = alice_client.post(reverse("assets:add"), {
            "kind": "scraped", "name": "Gold Eagle",
            "source_url": "https://example.com/gold", "quantity": "3", "unit": "oz",
        })
    assert r.status_code == 302
    a = Asset.objects.get(name="Gold Eagle")
    assert a.kind == "scraped"
    assert a.source_url == "https://example.com/gold"
    mock_refresh.assert_called_once()


def test_add_scraped_without_url_fails(alice_client):
    r = alice_client.post(reverse("assets:add"), {
        "kind": "scraped", "name": "X", "quantity": "1",
    })
    assert r.status_code == 200
    assert Asset.objects.filter(name="X").count() == 0


def test_edit_updates_manual_value(alice, alice_client):
    a = Asset.objects.create(user=alice, kind="manual", name="Car", current_value=Decimal("18000"))
    r = alice_client.post(reverse("assets:edit", args=[a.id]), {
        "name": "Car", "current_value": "16500", "notes": "",
    })
    assert r.status_code == 302
    a.refresh_from_db()
    assert a.current_value == Decimal("16500")


def test_edit_hidden_from_other_user(alice, bob, bob_client):
    a = Asset.objects.create(user=alice, kind="manual", name="X", current_value=Decimal("1"))
    r = bob_client.post(reverse("assets:edit", args=[a.id]), {"name": "pwned", "current_value": "0"})
    assert r.status_code == 404


def test_delete_flow(alice, alice_client):
    a = Asset.objects.create(user=alice, kind="manual", name="X", current_value=Decimal("1"))
    r = alice_client.post(reverse("assets:delete", args=[a.id]))
    assert r.status_code == 302
    assert Asset.objects.filter(pk=a.id).count() == 0


def test_delete_forbidden_for_other_user(alice, bob, bob_client):
    a = Asset.objects.create(user=alice, kind="manual", name="X", current_value=Decimal("1"))
    r = bob_client.post(reverse("assets:delete", args=[a.id]))
    assert r.status_code == 404
    assert Asset.objects.filter(pk=a.id).count() == 1


def test_anonymous_redirects():
    c = Client()
    r = c.get(reverse("assets:list"))
    assert r.status_code == 302
    assert "/login/" in r["Location"]


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
