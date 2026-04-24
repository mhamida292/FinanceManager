from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.investments.models import Holding, InvestmentAccount, PortfolioSnapshot

User = get_user_model()


@pytest.fixture
def two_users_with_investments(db):
    alice = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    bob = User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")

    inv_a = InvestmentAccount.objects.create(
        user=alice, source="manual", broker="Alice Brokerage", name="Alice IRA",
    )
    inv_b = InvestmentAccount.objects.create(
        user=bob, source="manual", broker="Bob Brokerage", name="Bob 401k",
    )

    h_a = Holding.objects.create(
        investment_account=inv_a, symbol="AAPL", shares=Decimal("10"),
        current_price=Decimal("180"), market_value=Decimal("1800"),
    )
    h_b = Holding.objects.create(
        investment_account=inv_b, symbol="MSFT", shares=Decimal("5"),
        current_price=Decimal("400"), market_value=Decimal("2000"),
    )

    PortfolioSnapshot.objects.create(investment_account=inv_a, date=date(2026, 4, 24), total_value=Decimal("1800"))
    PortfolioSnapshot.objects.create(investment_account=inv_b, date=date(2026, 4, 24), total_value=Decimal("2000"))

    return alice, bob, inv_a, inv_b, h_a, h_b


def test_investment_account_for_user_isolates(two_users_with_investments):
    alice, bob, *_ = two_users_with_investments
    assert list(InvestmentAccount.objects.for_user(alice).values_list("name", flat=True)) == ["Alice IRA"]
    assert list(InvestmentAccount.objects.for_user(bob).values_list("name", flat=True)) == ["Bob 401k"]


def test_holding_for_user_isolates(two_users_with_investments):
    alice, bob, *_ = two_users_with_investments
    assert list(Holding.objects.for_user(alice).values_list("symbol", flat=True)) == ["AAPL"]
    assert list(Holding.objects.for_user(bob).values_list("symbol", flat=True)) == ["MSFT"]


def test_snapshot_for_user_isolates(two_users_with_investments):
    alice, bob, *_ = two_users_with_investments
    assert PortfolioSnapshot.objects.for_user(alice).count() == 1
    assert PortfolioSnapshot.objects.for_user(bob).count() == 1


def test_gain_loss_properties(two_users_with_investments):
    _, _, _, _, h_a, _ = two_users_with_investments
    h_a.cost_basis = Decimal("1500")
    h_a.save()
    h_a.refresh_from_db()
    assert h_a.gain_loss == Decimal("300.00")
    assert h_a.gain_loss_percent == Decimal("20.00")


def test_gain_loss_none_without_cost_basis(two_users_with_investments):
    _, _, _, _, h_a, _ = two_users_with_investments
    assert h_a.cost_basis is None
    assert h_a.gain_loss is None
    assert h_a.gain_loss_percent is None
