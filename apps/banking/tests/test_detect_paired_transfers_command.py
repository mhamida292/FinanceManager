from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.banking.models import Account, Institution, Transaction

User = get_user_model()


def _setup_user_with_two_accounts(username):
    user = User.objects.create_user(username=username, password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    chk = Account.objects.create(institution=inst, name="Checking", type="checking",
        balance=Decimal("0"), external_id="CHK")
    cc = Account.objects.create(institution=inst, name="Card", type="credit",
        balance=Decimal("0"), external_id="CC")
    return user, chk, cc


@pytest.mark.django_db
def test_pair_detect_marks_classic_credit_card_payment_pair():
    """Credit card payment: checking -100, credit card +100 raw (display +100 after sign flip)."""
    user, chk, cc = _setup_user_with_two_accounts("alice_pp1")
    base = datetime(2026, 4, 18, tzinfo=timezone.utc)
    chk_tx = Transaction.objects.create(account=chk, posted_at=base,
        amount=Decimal("-81.92"), external_id="chk_pymt",
        payee="CAPITAL ONE", category="other")
    cc_tx = Transaction.objects.create(account=cc, posted_at=base + timedelta(days=1),
        amount=Decimal("-81.92"), external_id="cc_pymt",
        payee="CAPITAL ONE MOBILE PYMT", category="other")
    # On credit card, raw -81.92 → display_amount = +81.92 (incoming payment).
    # On checking, raw -81.92 → display_amount = -81.92 (outgoing).
    # Opposite signs, equal abs, different accounts, within 2 days → pair.

    call_command("detect_paired_transfers", stdout=StringIO())

    chk_tx.refresh_from_db(); cc_tx.refresh_from_db()
    assert chk_tx.category == "transfer"
    assert cc_tx.category == "transfer"


@pytest.mark.django_db
def test_pair_detect_skips_outside_window():
    user, chk, cc = _setup_user_with_two_accounts("alice_pp2")
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    chk_tx = Transaction.objects.create(account=chk, posted_at=base,
        amount=Decimal("-50"), external_id="chk_x",
        payee="CAPITAL ONE", category="other")
    # 5 days later — outside default window of 2.
    cc_tx = Transaction.objects.create(account=cc, posted_at=base + timedelta(days=5),
        amount=Decimal("-50"), external_id="cc_x",
        payee="CAPITAL ONE MOBILE PYMT", category="other")

    call_command("detect_paired_transfers", stdout=StringIO())

    chk_tx.refresh_from_db(); cc_tx.refresh_from_db()
    assert chk_tx.category == "other"
    assert cc_tx.category == "other"


@pytest.mark.django_db
def test_pair_detect_skips_same_account():
    user, chk, _cc = _setup_user_with_two_accounts("alice_pp3")
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    a_tx = Transaction.objects.create(account=chk, posted_at=base,
        amount=Decimal("-50"), external_id="chk_a", category="other")
    b_tx = Transaction.objects.create(account=chk, posted_at=base + timedelta(days=1),
        amount=Decimal("50"), external_id="chk_b", category="other")
    # Same account — must NOT pair (could be a refund or coincidence).

    call_command("detect_paired_transfers", stdout=StringIO())

    a_tx.refresh_from_db(); b_tx.refresh_from_db()
    assert a_tx.category == "other"
    assert b_tx.category == "other"


@pytest.mark.django_db
def test_pair_detect_skips_manual_overrides():
    user, chk, cc = _setup_user_with_two_accounts("alice_pp4")
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    chk_tx = Transaction.objects.create(account=chk, posted_at=base,
        amount=Decimal("-50"), external_id="chk_m", category="personal", category_manual=True)
    cc_tx = Transaction.objects.create(account=cc, posted_at=base,
        amount=Decimal("-50"), external_id="cc_m", category="other", category_manual=False)

    call_command("detect_paired_transfers", stdout=StringIO())

    chk_tx.refresh_from_db(); cc_tx.refresh_from_db()
    # chk_tx has manual override and is excluded from candidates; without its match, cc_tx stays too.
    assert chk_tx.category == "personal"
    assert cc_tx.category == "other"


@pytest.mark.django_db
def test_pair_detect_user_isolation():
    a_user, a_chk, a_cc = _setup_user_with_two_accounts("alice_pp5")
    b_user, b_chk, b_cc = _setup_user_with_two_accounts("bob_pp5")
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    a_chk_tx = Transaction.objects.create(account=a_chk, posted_at=base,
        amount=Decimal("-50"), external_id="ax", category="other")
    a_cc_tx = Transaction.objects.create(account=a_cc, posted_at=base,
        amount=Decimal("-50"), external_id="ay", category="other")
    b_chk_tx = Transaction.objects.create(account=b_chk, posted_at=base,
        amount=Decimal("-50"), external_id="bx", category="other")
    b_cc_tx = Transaction.objects.create(account=b_cc, posted_at=base,
        amount=Decimal("-50"), external_id="by", category="other")

    # Run scoped to alice only.
    call_command("detect_paired_transfers", "--user", "alice_pp5", stdout=StringIO())

    a_chk_tx.refresh_from_db(); a_cc_tx.refresh_from_db()
    b_chk_tx.refresh_from_db(); b_cc_tx.refresh_from_db()
    assert a_chk_tx.category == "transfer"
    assert a_cc_tx.category == "transfer"
    assert b_chk_tx.category == "other"
    assert b_cc_tx.category == "other"
