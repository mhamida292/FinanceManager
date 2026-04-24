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
    Asset.objects.create(user=alice, kind="manual", name="Alice's car", current_value=Decimal("18000"))
    Asset.objects.create(user=bob, kind="manual", name="Bob's painting", current_value=Decimal("5000"))
    r = alice_client.get(reverse("assets:list"))
    assert b"Alice's car" in r.content
    assert b"Bob's painting" not in r.content


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
