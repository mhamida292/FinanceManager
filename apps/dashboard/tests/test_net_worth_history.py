from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.banking.models import Account, AccountBalanceSnapshot, Institution
from apps.dashboard.services import net_worth_history

User = get_user_model()


@pytest.mark.django_db
def test_net_worth_history_includes_cash_balances():
    user = User.objects.create_user(username="alice_nwh1", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("500"), external_id="A",
    )
    today = date.today()
    AccountBalanceSnapshot.objects.create(account=acc, date=today, balance=Decimal("500"))
    AccountBalanceSnapshot.objects.create(account=acc, date=today - timedelta(days=1), balance=Decimal("400"))

    history = net_worth_history(user, days=3)
    # Most recent (today) should be 500. Day before should be 400.
    assert history[-1] == Decimal("500")
    assert history[-2] == Decimal("400")


@pytest.mark.django_db
def test_net_worth_history_subtracts_credit_card_liability():
    """A credit card with $1000 raw balance is a $1000 liability — should
    REDUCE net worth, not add to it."""
    user = User.objects.create_user(username="alice_nwh2", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    chk = Account.objects.create(institution=inst, name="Chk", type="checking",
        balance=Decimal("2000"), external_id="C")
    cc = Account.objects.create(institution=inst, name="Card", type="credit",
        balance=Decimal("1000"), external_id="CC")
    today = date.today()
    AccountBalanceSnapshot.objects.create(account=chk, date=today, balance=Decimal("2000"))
    AccountBalanceSnapshot.objects.create(account=cc, date=today, balance=Decimal("1000"))

    history = net_worth_history(user, days=1)
    # 2000 cash - 1000 liability = 1000 net worth.
    assert history[-1] == Decimal("1000")


@pytest.mark.django_db
def test_net_worth_history_carries_forward_seed():
    """If there's a snapshot from BEFORE the cutoff window, it should seed
    the carry-forward so leading days aren't undercounted."""
    user = User.objects.create_user(username="alice_nwh3", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="C")
    today = date.today()
    # Snapshot from 10 days ago — outside the 5-day window.
    AccountBalanceSnapshot.objects.create(
        account=acc, date=today - timedelta(days=10), balance=Decimal("777"),
    )

    history = net_worth_history(user, days=5)
    # Every day in the window should be 777 (carried forward).
    for value in history:
        assert value == Decimal("777")


@pytest.mark.django_db
def test_net_worth_history_smooths_newly_added_investment_account():
    """If an investment account's first PortfolioSnapshot is mid-window,
    the chart should treat it as if it had that value all 30 days
    (no fake jump on the day it was added)."""
    from apps.investments.models import InvestmentAccount, PortfolioSnapshot
    user = User.objects.create_user(username="alice_smooth_inv", password="x")
    ia = InvestmentAccount.objects.create(user=user, source="manual", broker="X", name="Roth")
    today = date.today()
    # First snapshot is 5 days ago — no pre-cutoff data, no earlier in-window data.
    PortfolioSnapshot.objects.create(
        investment_account=ia, date=today - timedelta(days=5), total_value=Decimal("25000"),
    )
    PortfolioSnapshot.objects.create(
        investment_account=ia, date=today, total_value=Decimal("25000"),
    )

    history = net_worth_history(user, days=30)
    # Every day should show $25000 (carried backwards from first known value).
    for v in history:
        assert v == Decimal("25000")


@pytest.mark.django_db
def test_net_worth_history_smooths_newly_added_asset():
    """Same as above but for assets."""
    from apps.assets.models import Asset, AssetPriceSnapshot
    from datetime import datetime, timezone as dt_tz
    user = User.objects.create_user(username="alice_smooth_asset", password="x")
    asset = Asset.objects.create(user=user, kind="manual", name="Gold", current_value=Decimal("10000"))
    today = date.today()
    AssetPriceSnapshot.objects.create(
        asset=asset, at=datetime.combine(today - timedelta(days=3), datetime.min.time(), tzinfo=dt_tz.utc),
        value=Decimal("10000"),
    )

    history = net_worth_history(user, days=30)
    # Every day should show $10000 carried backwards.
    for v in history:
        assert v == Decimal("10000")
