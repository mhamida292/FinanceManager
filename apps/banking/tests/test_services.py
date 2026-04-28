from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.banking.models import Account, Institution, Transaction
from apps.banking.services import link_institution, sync_institution
from apps.providers import registry as registry_module
from apps.providers.base import AccountData, AccountSyncPayload, TransactionData

User = get_user_model()


class _FakeProvider:
    name = "fake"

    def __init__(self):
        self._payloads = [
            AccountSyncPayload(
                account=AccountData(
                    external_id="ACC-1", name="Checking", type="checking",
                    balance=Decimal("100.00"), currency="USD", org_name="FakeBank",
                ),
                transactions=(
                    TransactionData(
                        external_id="TXN-1",
                        posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        amount=Decimal("-5.00"), description="Coffee", payee="Cafe",
                        memo="", pending=False,
                    ),
                ),
            ),
        ]

    def exchange_setup_token(self, setup_token: str) -> str:
        return "https://FAKE:TOKEN@fake.example/simplefin"

    def fetch_accounts_with_transactions(self, access_url: str, *, since=None):
        yield from self._payloads


@pytest.fixture(autouse=True)
def _register_fake_provider():
    original = registry_module._REGISTRY.copy()
    registry_module._REGISTRY["fake"] = _FakeProvider
    registry_module._REGISTRY["simplefin"] = _FakeProvider  # override for link_institution default
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(original)


@pytest.mark.django_db
def test_link_institution_creates_institution_and_initial_sync():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    inst = link_institution(
        user=user, setup_token="base64token",
        display_name="My Main Bank", provider_name="fake",
    )
    assert isinstance(inst, Institution)
    assert inst.user == user
    assert inst.name == "My Main Bank"
    assert inst.access_url == "https://FAKE:TOKEN@fake.example/simplefin"
    assert Account.objects.filter(institution=inst).count() == 1
    assert Transaction.objects.filter(account__institution=inst).count() == 1
    assert inst.last_synced_at is not None


@pytest.mark.django_db
def test_sync_institution_is_idempotent():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    inst = link_institution(
        user=user, setup_token="base64token",
        display_name="Main", provider_name="fake",
    )
    result = sync_institution(inst)
    assert result.accounts_created == 0
    assert result.accounts_updated == 1
    assert result.transactions_created == 0
    assert result.transactions_updated == 1
    assert Account.objects.filter(institution=inst).count() == 1
    assert Transaction.objects.filter(account__institution=inst).count() == 1


@pytest.mark.django_db
def test_sync_does_not_overwrite_user_rename():
    """After a user renames an account, subsequent syncs preserve the display_name."""
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    inst = link_institution(
        user=user, setup_token="base64token",
        display_name="Main", provider_name="fake",
    )
    account = Account.objects.get(institution=inst)
    account.display_name = "Joint Checking"
    account.save(update_fields=["display_name"])

    sync_institution(inst)

    account.refresh_from_db()
    assert account.display_name == "Joint Checking"
    assert account.effective_name == "Joint Checking"
    # Provider-sourced name stays current too
    assert account.name == "Checking"


@pytest.mark.django_db
def test_sync_does_not_overwrite_user_type_change():
    """After a user reclassifies an account (e.g. Other → Credit), sync preserves the change."""
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    inst = link_institution(
        user=user, setup_token="base64token",
        display_name="Main", provider_name="fake",
    )
    account = Account.objects.get(institution=inst)
    # Provider's heuristic guess was 'checking' (name='Checking'); user reclassifies as credit.
    account.type = "credit"
    account.save(update_fields=["type"])

    sync_institution(inst)

    account.refresh_from_db()
    assert account.type == "credit", "Manual type override must survive sync"


@pytest.mark.django_db
def test_transaction_effective_payee_precedence():
    """display_name overrides payee, payee overrides description, all empty returns ''."""
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Checking", type="checking",
        balance=Decimal("0"), external_id="A-1",
    )

    tx_full = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-1.00"), description="DESC", payee="PAYEE",
        display_name="MyLabel", external_id="t-1",
    )
    tx_payee_only = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        amount=Decimal("-1.00"), description="DESC", payee="PAYEE", external_id="t-2",
    )
    tx_desc_only = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        amount=Decimal("-1.00"), description="DESC", payee="", external_id="t-3",
    )
    tx_empty = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
        amount=Decimal("-1.00"), description="", payee="", external_id="t-4",
    )

    assert tx_full.effective_payee == "MyLabel"
    assert tx_payee_only.effective_payee == "PAYEE"
    assert tx_desc_only.effective_payee == "DESC"
    assert tx_empty.effective_payee == ""


@pytest.mark.django_db
def test_display_amount_inverts_sign_for_credit_and_loan_accounts():
    """Provider APIs report credit-card charges as positive (issuer convention).
    From the user's perspective a charge is money spent — should display as
    negative. display_amount inverts the sign for credit and loan accounts only."""
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")

    checking = Account.objects.create(
        institution=inst, name="Checking", type="checking",
        balance=Decimal("0"), external_id="A-CHK",
    )
    credit = Account.objects.create(
        institution=inst, name="Card", type="credit",
        balance=Decimal("0"), external_id="A-CC",
    )
    loan = Account.objects.create(
        institution=inst, name="Mortgage", type="loan",
        balance=Decimal("0"), external_id="A-LN",
    )

    chk_debit = Transaction.objects.create(
        account=checking, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-50.00"), external_id="chk-1",
    )
    cc_charge = Transaction.objects.create(
        account=credit, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("50.00"), external_id="cc-1",
    )
    cc_payment = Transaction.objects.create(
        account=credit, posted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        amount=Decimal("-200.00"), external_id="cc-2",
    )
    loan_charge = Transaction.objects.create(
        account=loan, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("1500.00"), external_id="ln-1",
    )

    # Depository: pass-through.
    assert chk_debit.display_amount == Decimal("-50.00")
    # Credit charge (positive in raw) flips to negative.
    assert cc_charge.display_amount == Decimal("-50.00")
    # Credit payment (negative in raw) flips to positive.
    assert cc_payment.display_amount == Decimal("200.00")
    # Loan accrual flips the same way.
    assert loan_charge.display_amount == Decimal("-1500.00")


@pytest.mark.django_db
def test_sync_does_not_overwrite_transaction_rename():
    """After a user renames a transaction, subsequent syncs preserve the display_name."""
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    inst = link_institution(
        user=user, setup_token="base64token",
        display_name="Main", provider_name="fake",
    )
    tx = Transaction.objects.get(account__institution=inst, external_id="TXN-1")
    tx.display_name = "Daily latte"
    tx.save(update_fields=["display_name"])

    sync_institution(inst)

    tx.refresh_from_db()
    assert tx.display_name == "Daily latte"
    assert tx.effective_payee == "Daily latte"
    # Provider-sourced fields stay current
    assert tx.payee == "Cafe"
    assert tx.description == "Coffee"
