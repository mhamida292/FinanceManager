from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.assets.models import Asset
from apps.banking.models import Account, Institution, Transaction
from apps.dashboard.services import net_worth_summary
from apps.investments.models import Holding, InvestmentAccount

User = get_user_model()


@pytest.mark.django_db
def test_net_worth_aggregates_across_apps():
    from apps.liabilities.models import Liability

    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")

    # Cash: $2000 (credit cards no longer subtracted from cash)
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    Account.objects.create(institution=inst, name="Checking", type="checking", balance=Decimal("2000"), external_id="A1")
    Account.objects.create(institution=inst, name="Card", type="credit", balance=Decimal("500"), external_id="A2")

    # Investments: $1800 holdings + $200 cash = $2000
    inv = InvestmentAccount.objects.create(user=user, source="manual", name="IRA", broker="Fidelity",
                                            cash_balance=Decimal("200"))
    Holding.objects.create(investment_account=inv, symbol="VTI", shares=Decimal("10"),
                            current_price=Decimal("180"), market_value=Decimal("1800"))

    # Assets: $20000
    Asset.objects.create(user=user, kind="manual", name="Car", current_value=Decimal("18000"))
    Asset.objects.create(user=user, kind="scraped", name="Gold Eagle",
                          source_url="https://x", quantity=Decimal("1"), current_value=Decimal("2000"))

    # Liabilities: $500 credit card + $1000 manual = $1500
    Liability.objects.create(user=user, name="Loan", balance=Decimal("1000"))

    Transaction.objects.create(account=Account.objects.get(name="Checking"),
                                posted_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
                                amount=Decimal("-50"), description="coffee", external_id="T1")

    summary = net_worth_summary(user)

    assert summary.cash == Decimal("2000")        # checking only
    assert summary.investments == Decimal("2000") # 1800 holdings + 200 cash
    assert summary.assets == Decimal("20000")
    assert summary.liabilities == Decimal("1500") # 500 credit card + 1000 manual loan
    assert summary.net_worth == Decimal("22500")  # 2000 + 2000 + 20000 - 1500
    assert summary.cash_account_count == 1
    assert summary.investment_holding_count == 1
    assert summary.asset_count == 2


@pytest.mark.django_db
def test_net_worth_isolation():
    alice = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    bob = User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")
    Asset.objects.create(user=alice, kind="manual", name="Alice", current_value=Decimal("100"))
    Asset.objects.create(user=bob, kind="manual", name="Bob", current_value=Decimal("99"))

    assert net_worth_summary(alice).net_worth == Decimal("100")
    assert net_worth_summary(bob).net_worth == Decimal("99")


@pytest.mark.django_db
def test_empty_user():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    summary = net_worth_summary(user)
    assert summary.net_worth == Decimal("0")
    assert summary.recent_transactions == []
