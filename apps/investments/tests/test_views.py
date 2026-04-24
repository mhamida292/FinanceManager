from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.investments.models import Holding, InvestmentAccount

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
    r = alice_client.get(reverse("investments:list"))
    assert r.status_code == 200
    assert b"No investment accounts yet" in r.content


def test_list_shows_only_own_accounts(alice, bob, alice_client):
    InvestmentAccount.objects.create(user=alice, source="manual", broker="Fidelity", name="Alice 401k")
    InvestmentAccount.objects.create(user=bob, source="manual", broker="Vanguard", name="Bob IRA")
    r = alice_client.get(reverse("investments:list"))
    assert b"Alice 401k" in r.content
    assert b"Bob IRA" not in r.content


def test_add_manual_account_creates_and_redirects(alice_client):
    r = alice_client.post(reverse("investments:add_account"), {
        "broker": "Fidelity", "name": "401k", "notes": "employer match",
    })
    assert r.status_code == 302
    acc = InvestmentAccount.objects.get(name="401k")
    assert acc.source == "manual"
    assert acc.broker == "Fidelity"


def test_account_detail_hidden_from_other_user(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    r = bob_client.get(reverse("investments:account_detail", args=[acc.id]))
    assert r.status_code == 404


def test_add_holding_creates_and_redirects(alice, alice_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    r = alice_client.post(reverse("investments:add_holding", args=[acc.id]), {
        "symbol": "vti", "shares": "40", "cost_basis": "8000",
    })
    assert r.status_code == 302
    h = Holding.objects.get(investment_account=acc)
    assert h.symbol == "VTI"
    assert h.shares == Decimal("40")


def test_add_holding_rejects_for_other_users_account(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    r = bob_client.post(reverse("investments:add_holding", args=[acc.id]), {
        "symbol": "VTI", "shares": "40",
    })
    assert r.status_code == 404


def test_edit_holding_cost_basis(alice, alice_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    h = Holding.objects.create(investment_account=acc, symbol="AAPL", shares=Decimal("10"), current_price=Decimal("180"), market_value=Decimal("1800"))
    r = alice_client.post(reverse("investments:edit_holding", args=[h.id]), {
        "shares": "10", "cost_basis": "1500",
    })
    assert r.status_code == 302
    h.refresh_from_db()
    assert h.cost_basis == Decimal("1500")
    assert h.cost_basis_source == "manual"


def test_edit_holding_isolation(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    h = Holding.objects.create(investment_account=acc, symbol="AAPL", shares=Decimal("10"), current_price=Decimal("180"), market_value=Decimal("1800"))
    r = bob_client.post(reverse("investments:edit_holding", args=[h.id]), {"cost_basis": "0"})
    assert r.status_code == 404


def test_anonymous_redirects_to_login():
    c = Client()
    r = c.get(reverse("investments:list"))
    assert r.status_code == 302
    assert "/login/" in r["Location"]
