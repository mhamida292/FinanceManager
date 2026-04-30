from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.banking.models import Account, Institution, Transaction

User = get_user_model()


@pytest.mark.django_db
def test_detect_transfers_marks_matching_uncategorized():
    user = User.objects.create_user(username="alice_dtx1", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    pymt = Transaction.objects.create(account=acc, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-100"), external_id="t1",
        payee="CAPITAL ONE MOBILE PYMT", category="uncategorized")
    coffee = Transaction.objects.create(account=acc, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-5"), external_id="t2",
        payee="Qamaria Yemeni Coffee", category="uncategorized")

    call_command("detect_transfers", stdout=StringIO())

    pymt.refresh_from_db(); coffee.refresh_from_db()
    assert pymt.category == "transfer"
    assert coffee.category == "uncategorized"


@pytest.mark.django_db
def test_detect_transfers_skips_manual_overrides():
    user = User.objects.create_user(username="alice_dtx2", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    # User manually set this Zelle to "personal" — must not be overridden.
    tx = Transaction.objects.create(account=acc, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-50"), external_id="t1",
        payee="ZELLE PAYMENT TO MOM", category="personal", category_manual=True)

    call_command("detect_transfers", stdout=StringIO())

    tx.refresh_from_db()
    assert tx.category == "personal"


@pytest.mark.django_db
def test_detect_transfers_skips_already_categorized():
    """Only uncategorized rows are touched. Existing categories (even non-manual) survive."""
    user = User.objects.create_user(username="alice_dtx3", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx = Transaction.objects.create(account=acc, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-50"), external_id="t1",
        payee="WIRE TRANSFER", category="other", category_manual=False)

    call_command("detect_transfers", stdout=StringIO())

    tx.refresh_from_db()
    assert tx.category == "other"  # unchanged — was already non-uncategorized


@pytest.mark.django_db
def test_detect_transfers_user_scope():
    alice = User.objects.create_user(username="alice_dtx4", password="x")
    bob = User.objects.create_user(username="bob_dtx", password="x")
    inst_a = Institution.objects.create(user=alice, name="A", access_url="https://x")
    inst_b = Institution.objects.create(user=bob, name="B", access_url="https://y")
    acc_a = Account.objects.create(institution=inst_a, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    acc_b = Account.objects.create(institution=inst_b, name="B", type="checking",
        balance=Decimal("0"), external_id="B")
    a_tx = Transaction.objects.create(account=acc_a, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-100"), external_id="ta", payee="CITI", category="uncategorized")
    b_tx = Transaction.objects.create(account=acc_b, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-100"), external_id="tb", payee="CITI", category="uncategorized")

    call_command("detect_transfers", "--user", "alice_dtx4", stdout=StringIO())

    a_tx.refresh_from_db(); b_tx.refresh_from_db()
    assert a_tx.category == "transfer"
    assert b_tx.category == "uncategorized"  # bob's row untouched
