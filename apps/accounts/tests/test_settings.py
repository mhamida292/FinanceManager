from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.banking.models import Account, Institution
from apps.investments.models import InvestmentAccount

User = get_user_model()


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice", password="correct-horse-battery-staple")


@pytest.fixture
def alice_client(alice):
    c = Client()
    c.force_login(alice)
    return c


def test_settings_groups_simplefin_accounts_under_their_institution(alice, alice_client):
    # SimpleFIN connection with one bank account and one investment account
    inst = Institution.objects.create(user=alice, name="Family Banks", access_url="https://x")
    Account.objects.create(institution=inst, name="Joint Checking", type="checking",
                           balance=Decimal("1000"), external_id="A-1")
    InvestmentAccount.objects.create(user=alice, source="simplefin", institution=inst,
                                      broker="Fidelity", name="Family 401k", external_id="I-1")
    # Manual investment account (not under any connection)
    InvestmentAccount.objects.create(user=alice, source="manual", broker="Vanguard", name="Roth IRA")

    response = alice_client.get(reverse("settings"))
    assert response.status_code == 200
    body = response.content.decode()

    # The new heading is present; the old per-section heading is gone.
    assert "External connections" in body
    assert "SimpleFIN-linked investment accounts" not in body

    # All three account names render somewhere on the page.
    assert "Joint Checking" in body
    assert "Family 401k" in body
    assert "Roth IRA" in body

    # New "Manual investment accounts" section exists.
    assert "Manual investment accounts" in body

    # The manual account name appears AFTER the External connections section
    # (it's grouped in the dedicated manual section, not under any institution).
    ext_pos = body.index("External connections")
    manual_section_pos = body.index("Manual investment accounts")
    roth_pos = body.index("Roth IRA")
    assert ext_pos < manual_section_pos < roth_pos

    # The Family 401k (SimpleFIN-sourced) appears BEFORE the Manual section
    # (it's nested under its institution).
    family_pos = body.index("Family 401k")
    assert family_pos < manual_section_pos


def test_settings_includes_rename_links_for_child_accounts(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Bank", access_url="https://x")
    bank_acc = Account.objects.create(institution=inst, name="Checking", type="checking",
                                       balance=Decimal("100"), external_id="A-1")
    inv_acc = InvestmentAccount.objects.create(user=alice, source="simplefin", institution=inst,
                                                broker="Fidelity", name="401k", external_id="I-1")

    response = alice_client.get(reverse("settings"))
    body = response.content.decode()

    assert reverse("banking:rename_account", args=[bank_acc.id]) in body
    assert reverse("investments:rename_account", args=[inv_acc.id]) in body
