from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.banking.models import Account, Institution, Transaction
from apps.providers import registry as registry_module
from apps.providers.base import AccountData, AccountSyncPayload, TransactionData

User = get_user_model()


class _BackfillProvider:
    name = "teller"

    def exchange_setup_token(self, t):
        return t

    def fetch_accounts_with_transactions(self, access_url, *, since=None):
        yield AccountSyncPayload(
            account=AccountData(
                external_id="ACC-1", name="Chk", type="checking",
                balance=Decimal("0"), currency="USD", org_name="Bank",
            ),
            transactions=(
                TransactionData(
                    external_id="T-NEW",
                    posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    amount=Decimal("-12"), description="Food", payee="Food",
                    memo="", pending=False, provider_category="dining",
                ),
            ),
        )

    def fetch_investment_accounts(self, access_url):
        return iter(())


@pytest.fixture
def _register_teller():
    original = registry_module._REGISTRY.copy()
    registry_module._REGISTRY["teller"] = _BackfillProvider
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(original)


@pytest.mark.django_db
def test_backfill_updates_teller_transactions(_register_teller):
    user = User.objects.create_user(username="alice_bf1", password="x")
    inst = Institution.objects.create(
        user=user, name="My Bank", provider="teller", access_url="tok",
    )
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="ACC-1",
    )
    # Pre-existing row with category=uncategorized.
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-12"), external_id="T-NEW",
        description="Food", payee="Food", category="uncategorized",
    )

    out = StringIO()
    call_command("categorize_existing_teller", stdout=out)

    tx.refresh_from_db()
    assert tx.category == "dining"
    assert tx.category_manual is False


@pytest.mark.django_db
def test_backfill_skips_manually_overridden(_register_teller):
    user = User.objects.create_user(username="alice_bf2", password="x")
    inst = Institution.objects.create(
        user=user, name="My Bank", provider="teller", access_url="tok",
    )
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="ACC-1",
    )
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-12"), external_id="T-NEW",
        category="personal", category_manual=True,
    )

    call_command("categorize_existing_teller", stdout=StringIO())

    tx.refresh_from_db()
    assert tx.category == "personal"
    assert tx.category_manual is True


@pytest.mark.django_db
def test_backfill_does_not_touch_simplefin_transactions(_register_teller):
    user = User.objects.create_user(username="alice_bf3", password="x")
    sf_inst = Institution.objects.create(
        user=user, name="SF", provider="simplefin", access_url="https://x",
    )
    acc = Account.objects.create(
        institution=sf_inst, name="Sf", type="checking",
        balance=Decimal("0"), external_id="SF-1",
    )
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-12"), external_id="SF-T1",
        category="uncategorized",
    )

    call_command("categorize_existing_teller", stdout=StringIO())

    tx.refresh_from_db()
    assert tx.category == "uncategorized"
