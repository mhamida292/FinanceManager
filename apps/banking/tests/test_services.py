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

    def fetch_accounts_with_transactions(self, access_url: str):
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
