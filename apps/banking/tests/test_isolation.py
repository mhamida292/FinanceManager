from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.banking.models import Account, Institution, Transaction

User = get_user_model()


@pytest.fixture
def two_users_with_data(db):
    alice = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    bob = User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")

    inst_a = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example/token")
    inst_b = Institution.objects.create(user=bob, name="Bob Bank", access_url="https://bob.example/token")

    acct_a = Account.objects.create(
        institution=inst_a, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    acct_b = Account.objects.create(
        institution=inst_b, name="Bob Checking", type="checking",
        balance=Decimal("200.00"), external_id="B-1",
    )

    Transaction.objects.create(
        account=acct_a, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-10.00"), description="Alice coffee", external_id="TA-1",
    )
    Transaction.objects.create(
        account=acct_b, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-20.00"), description="Bob coffee", external_id="TB-1",
    )

    return alice, bob, inst_a, inst_b, acct_a, acct_b


def test_institution_for_user_returns_only_own_rows(two_users_with_data):
    alice, bob, *_ = two_users_with_data
    assert list(Institution.objects.for_user(alice).values_list("name", flat=True)) == ["Alice Bank"]
    assert list(Institution.objects.for_user(bob).values_list("name", flat=True)) == ["Bob Bank"]


def test_account_for_user_returns_only_own_rows(two_users_with_data):
    alice, bob, *_ = two_users_with_data
    assert list(Account.objects.for_user(alice).values_list("name", flat=True)) == ["Alice Checking"]
    assert list(Account.objects.for_user(bob).values_list("name", flat=True)) == ["Bob Checking"]


def test_transaction_for_user_returns_only_own_rows(two_users_with_data):
    alice, bob, *_ = two_users_with_data
    assert list(Transaction.objects.for_user(alice).values_list("description", flat=True)) == ["Alice coffee"]
    assert list(Transaction.objects.for_user(bob).values_list("description", flat=True)) == ["Bob coffee"]


def test_institution_access_url_round_trips_encrypted(two_users_with_data):
    """Sanity-check that the EncryptedTextField decrypts on read."""
    alice, *_ = two_users_with_data
    fresh = Institution.objects.get(user=alice)
    assert fresh.access_url == "https://alice.example/token"
