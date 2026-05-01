from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.banking.models import Account, AccountBalanceSnapshot, Institution, Transaction

User = get_user_model()


@pytest.mark.django_db
def test_balance_snapshot_display_balance_for_credit_account():
    user = User.objects.create_user(username="alice_bs1", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Card", type="credit",
        balance=Decimal("1234.56"), external_id="A",
    )
    snap = AccountBalanceSnapshot.objects.create(
        account=acc, date=date.today(), balance=Decimal("1234.56"),
    )
    # Credit card: raw is positive (amount owed), display flips it.
    assert snap.display_balance == Decimal("-1234.56")


@pytest.mark.django_db
def test_balance_snapshot_display_balance_for_checking():
    user = User.objects.create_user(username="alice_bs2", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("500.00"), external_id="A",
    )
    snap = AccountBalanceSnapshot.objects.create(
        account=acc, date=date.today(), balance=Decimal("500.00"),
    )
    # Depository: pass-through.
    assert snap.display_balance == Decimal("500.00")


@pytest.mark.django_db
def test_backfill_walks_transactions_backwards():
    """Setup: account balance is $1000 today. There's a -$50 txn today, +$2000
    yesterday. Yesterday's end-of-day = $1000 + $50 = $1050. Day before yesterday
    end-of-day = $1050 - $2000 = -$950."""
    user = User.objects.create_user(username="alice_bs3", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("1000"), external_id="A",
    )
    today = date.today()
    Transaction.objects.create(
        account=acc, posted_at=datetime.combine(today, datetime.min.time(), timezone.utc),
        amount=Decimal("-50"), external_id="t1",
    )
    Transaction.objects.create(
        account=acc, posted_at=datetime.combine(today - timedelta(days=1), datetime.min.time(), timezone.utc),
        amount=Decimal("2000"), external_id="t2",
    )

    call_command("backfill_balance_snapshots", "--days", "5", stdout=StringIO())

    snaps = {s.date: s.balance for s in AccountBalanceSnapshot.objects.filter(account=acc)}
    assert snaps[today] == Decimal("1000")
    assert snaps[today - timedelta(days=1)] == Decimal("1050")
    assert snaps[today - timedelta(days=2)] == Decimal("-950")


@pytest.mark.django_db
def test_backfill_idempotent():
    user = User.objects.create_user(username="alice_bs4", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("100"), external_id="A",
    )
    call_command("backfill_balance_snapshots", "--days", "3", stdout=StringIO())
    first_count = AccountBalanceSnapshot.objects.filter(account=acc).count()
    # Re-run.
    call_command("backfill_balance_snapshots", "--days", "3", stdout=StringIO())
    second_count = AccountBalanceSnapshot.objects.filter(account=acc).count()
    assert first_count == second_count


@pytest.mark.django_db
def test_backfill_user_scope():
    alice = User.objects.create_user(username="alice_bs5", password="x")
    bob = User.objects.create_user(username="bob_bs5", password="x")
    a_inst = Institution.objects.create(user=alice, name="A", access_url="https://x")
    b_inst = Institution.objects.create(user=bob, name="B", access_url="https://y")
    a_acc = Account.objects.create(institution=a_inst, name="A", type="checking",
        balance=Decimal("100"), external_id="A")
    b_acc = Account.objects.create(institution=b_inst, name="B", type="checking",
        balance=Decimal("100"), external_id="B")

    call_command("backfill_balance_snapshots", "--user", "alice_bs5", "--days", "3", stdout=StringIO())

    assert AccountBalanceSnapshot.objects.filter(account=a_acc).exists()
    assert not AccountBalanceSnapshot.objects.filter(account=b_acc).exists()
