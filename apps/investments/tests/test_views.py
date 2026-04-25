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


def test_list_empty_context(alice_client):
    """Empty state: no investment accounts → empty sections list, portfolio_value = 0."""
    r = alice_client.get(reverse("investments:list"))
    assert r.status_code == 200
    assert r.context["sections"] == []
    assert r.context["portfolio_value"] == Decimal("0")
    assert r.context["portfolio_gain"] is None


def test_list_sections_shape(alice, alice_client):
    """sections is in context with one entry per investment account, with required keys."""
    acc1 = InvestmentAccount.objects.create(
        user=alice, source="manual", broker="Fidelity", name="401k",
        cash_balance=Decimal("500"),
    )
    Holding.objects.create(
        investment_account=acc1, symbol="VTI", shares=Decimal("10"),
        current_price=Decimal("200"), market_value=Decimal("2000"),
        cost_basis=Decimal("1500"),
    )
    acc2 = InvestmentAccount.objects.create(
        user=alice, source="manual", broker="Vanguard", name="IRA",
        cash_balance=Decimal("0"),
    )
    Holding.objects.create(
        investment_account=acc2, symbol="VXUS", shares=Decimal("5"),
        current_price=Decimal("60"), market_value=Decimal("300"),
        cost_basis=Decimal("400"),
    )

    r = alice_client.get(reverse("investments:list"))
    assert r.status_code == 200
    sections = r.context["sections"]
    assert len(sections) == 2
    for s in sections:
        assert "account" in s
        assert "holdings" in s
        assert "holdings_value" in s
        assert "section_total" in s
        assert "section_gain" in s
        assert "section_gain_pct" in s

    # ordered by broker, name → Fidelity 401k first, Vanguard IRA second
    fidelity = sections[0]
    vanguard = sections[1]
    assert fidelity["account"].id == acc1.id
    assert fidelity["holdings_value"] == Decimal("2000")
    assert fidelity["section_total"] == Decimal("2500")  # holdings + cash
    assert fidelity["section_gain"] == Decimal("500")  # 2000 - 1500

    assert vanguard["account"].id == acc2.id
    assert vanguard["holdings_value"] == Decimal("300")
    assert vanguard["section_total"] == Decimal("300")
    assert vanguard["section_gain"] == Decimal("-100")  # 300 - 400


def test_list_portfolio_value_equals_sum_of_section_totals(alice, alice_client):
    """portfolio_value in context equals sum of section_totals."""
    acc1 = InvestmentAccount.objects.create(
        user=alice, source="manual", broker="A", name="One",
        cash_balance=Decimal("100"),
    )
    Holding.objects.create(
        investment_account=acc1, symbol="AAA", shares=Decimal("1"),
        current_price=Decimal("50"), market_value=Decimal("50"),
        cost_basis=Decimal("40"),
    )
    acc2 = InvestmentAccount.objects.create(
        user=alice, source="manual", broker="B", name="Two",
        cash_balance=Decimal("25"),
    )
    Holding.objects.create(
        investment_account=acc2, symbol="BBB", shares=Decimal("2"),
        current_price=Decimal("75"), market_value=Decimal("150"),
        cost_basis=Decimal("100"),
    )

    r = alice_client.get(reverse("investments:list"))
    sections = r.context["sections"]
    expected_total = sum((s["section_total"] for s in sections), Decimal("0"))
    assert r.context["portfolio_value"] == expected_total
    # Sanity: 50 + 100 + 150 + 25 = 325
    assert r.context["portfolio_value"] == Decimal("325")
    # Portfolio gain excludes cash: (50 + 150) - (40 + 100) = 60
    assert r.context["portfolio_gain"] == Decimal("60")


def test_list_holdings_appear_in_rendered_html(alice, alice_client):
    """Holdings symbols render in the page body."""
    acc = InvestmentAccount.objects.create(
        user=alice, source="manual", broker="Fidelity", name="401k",
    )
    Holding.objects.create(
        investment_account=acc, symbol="VTI", shares=Decimal("10"),
        current_price=Decimal("200"), market_value=Decimal("2000"),
        cost_basis=Decimal("1500"),
    )
    Holding.objects.create(
        investment_account=acc, symbol="MSFT", shares=Decimal("5"),
        current_price=Decimal("400"), market_value=Decimal("2000"),
        cost_basis=Decimal("1800"),
    )

    r = alice_client.get(reverse("investments:list"))
    assert r.status_code == 200
    assert b"VTI" in r.content
    assert b"MSFT" in r.content
    assert b"Portfolio value" in r.content


def test_list_holdings_isolated_between_users(alice, bob, alice_client):
    """Bob's holdings should not appear when alice views the list."""
    bob_acc = InvestmentAccount.objects.create(
        user=bob, source="manual", broker="Vanguard", name="Bob IRA",
    )
    Holding.objects.create(
        investment_account=bob_acc, symbol="BOBSECRET", shares=Decimal("1"),
        current_price=Decimal("100"), market_value=Decimal("100"),
    )

    r = alice_client.get(reverse("investments:list"))
    assert r.status_code == 200
    assert b"BOBSECRET" not in r.content
    assert b"Bob IRA" not in r.content
    assert r.context["sections"] == []


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


def test_delete_investment_account_cascades(alice, alice_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="ToDelete")
    Holding.objects.create(investment_account=acc, symbol="AAPL", shares=Decimal("1"),
                            current_price=Decimal("100"), market_value=Decimal("100"))
    r = alice_client.post(reverse("investments:delete_account", args=[acc.id]))
    assert r.status_code == 302
    assert InvestmentAccount.objects.filter(pk=acc.id).count() == 0
    assert Holding.objects.filter(investment_account_id=acc.id).count() == 0


def test_delete_investment_account_forbidden_for_other_user(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="X")
    r = bob_client.post(reverse("investments:delete_account", args=[acc.id]))
    assert r.status_code == 404


def test_delete_holding_removes_only_that_holding(alice, alice_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    keep = Holding.objects.create(investment_account=acc, symbol="AAPL", shares=Decimal("1"),
                                   current_price=Decimal("100"), market_value=Decimal("100"))
    drop = Holding.objects.create(investment_account=acc, symbol="MSFT", shares=Decimal("1"),
                                   current_price=Decimal("400"), market_value=Decimal("400"))
    r = alice_client.post(reverse("investments:delete_holding", args=[drop.id]))
    assert r.status_code == 302
    assert Holding.objects.filter(pk=keep.id).exists()
    assert not Holding.objects.filter(pk=drop.id).exists()


def test_delete_holding_forbidden_for_other_user(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    h = Holding.objects.create(investment_account=acc, symbol="AAPL", shares=Decimal("1"),
                                current_price=Decimal("100"), market_value=Decimal("100"))
    r = bob_client.post(reverse("investments:delete_holding", args=[h.id]))
    assert r.status_code == 404
    assert Holding.objects.filter(pk=h.id).exists()


def test_edit_investment_account_persists(alice, alice_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="Old", name="Old name")
    r = alice_client.post(reverse("investments:edit_account", args=[acc.id]), {
        "name": "New name", "broker": "Fidelity", "notes": "401k",
        "cash_balance": "1234.56",
    })
    assert r.status_code == 302
    acc.refresh_from_db()
    assert acc.name == "New name"
    assert acc.broker == "Fidelity"
    assert acc.notes == "401k"
    assert acc.cash_balance == Decimal("1234.56")


def test_edit_investment_account_forbidden_for_other_user(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="X")
    r = bob_client.post(reverse("investments:edit_account", args=[acc.id]), {
        "name": "pwned", "broker": "X", "cash_balance": "0",
    })
    assert r.status_code == 404
