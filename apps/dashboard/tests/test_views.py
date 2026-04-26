from datetime import datetime, timezone as dt_tz
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.banking.models import Account, Institution, Transaction

User = get_user_model()


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice", password="correct-horse-battery-staple")


@pytest.fixture
def alice_client(alice):
    c = Client()
    c.force_login(alice)
    return c


def test_dashboard_recent_transactions_show_renamed_label(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Bank", access_url="https://x")
    account = Account.objects.create(
        institution=inst, name="Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    Transaction.objects.create(
        account=account,
        posted_at=datetime(2026, 1, 1, tzinfo=dt_tz.utc),
        amount=Decimal("-12.34"), description="DESC", payee="ProviderPayee",
        display_name="My Custom Label", external_id="t-1",
    )

    response = alice_client.get(reverse("home"))
    assert response.status_code == 200
    assert b"My Custom Label" in response.content
    assert b"ProviderPayee" not in response.content
