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
def bob(db):
    return User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")


@pytest.fixture
def alice_client(alice):
    c = Client()
    c.force_login(alice)
    return c


@pytest.fixture
def bob_client(bob):
    c = Client()
    c.force_login(bob)
    return c


def test_banks_list_empty(alice_client):
    response = alice_client.get(reverse("banking:list"))
    assert response.status_code == 200
    assert b"No accounts yet" in response.content


def test_banks_list_shows_only_own_accounts(alice, bob, alice_client):
    alice_inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    bob_inst = Institution.objects.create(user=bob, name="Bob Bank", access_url="https://bob.example")
    Account.objects.create(
        institution=alice_inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    Account.objects.create(
        institution=bob_inst, name="Bob Savings", type="savings",
        balance=Decimal("200.00"), external_id="B-1",
    )

    response = alice_client.get(reverse("banking:list"))
    assert b"Alice Checking" in response.content
    assert b"Bob Savings" not in response.content


def test_account_detail_hidden_from_other_user(alice, bob, bob_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    response = bob_client.get(reverse("banking:account_detail", args=[account.id]))
    assert response.status_code == 404  # other user can't see or discover it


def test_sync_forbidden_for_other_users_institution(alice, bob, bob_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    response = bob_client.post(reverse("banking:sync", args=[inst.id]))
    assert response.status_code == 404


def test_anonymous_banks_list_redirects_to_login():
    c = Client()
    response = c.get(reverse("banking:list"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_rename_account_persists_display_name(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    response = alice_client.post(
        reverse("banking:rename_account", args=[account.id]),
        {"display_name": "Joint Checking"},
    )
    assert response.status_code == 302
    account.refresh_from_db()
    assert account.display_name == "Joint Checking"
    assert account.effective_name == "Joint Checking"


def test_rename_account_blank_restores_provider_name(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
        display_name="Old Custom Name",
    )
    alice_client.post(
        reverse("banking:rename_account", args=[account.id]),
        {"display_name": ""},
    )
    account.refresh_from_db()
    assert account.display_name == ""
    assert account.effective_name == "Alice Checking"


def test_rename_account_forbidden_for_other_user(alice, bob, bob_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    response = bob_client.post(
        reverse("banking:rename_account", args=[account.id]),
        {"display_name": "Pwned"},
    )
    assert response.status_code == 404
    account.refresh_from_db()
    assert account.display_name == ""


def test_rename_institution_persists_and_isolates(alice, bob, alice_client, bob_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")

    response = alice_client.post(
        reverse("banking:rename_institution", args=[inst.id]),
        {"display_name": "Family Banks"},
    )
    assert response.status_code == 302
    inst.refresh_from_db()
    assert inst.display_name == "Family Banks"

    response = bob_client.post(
        reverse("banking:rename_institution", args=[inst.id]),
        {"display_name": "Pwned"},
    )
    assert response.status_code == 404
    inst.refresh_from_db()
    assert inst.display_name == "Family Banks"


def test_delete_institution_cascades(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="ToDelete", access_url="https://x")
    Account.objects.create(institution=inst, name="Acc", type="checking", external_id="A-1")
    r = alice_client.post(reverse("banking:delete_institution", args=[inst.id]))
    assert r.status_code == 302
    assert Institution.objects.filter(pk=inst.id).count() == 0
    assert Account.objects.filter(institution_id=inst.id).count() == 0


def test_delete_institution_forbidden_for_other_user(alice, bob, bob_client):
    inst = Institution.objects.create(user=alice, name="X", access_url="https://x")
    r = bob_client.post(reverse("banking:delete_institution", args=[inst.id]))
    assert r.status_code == 404
    assert Institution.objects.filter(pk=inst.id).count() == 1


def test_delete_account_isolation(alice, bob, bob_client):
    inst = Institution.objects.create(user=alice, name="X", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="Acc", type="checking", external_id="A-1")
    r = bob_client.post(reverse("banking:delete_account", args=[acc.id]))
    assert r.status_code == 404
    assert Account.objects.filter(pk=acc.id).count() == 1


def test_transactions_list_shows_only_own(alice, bob, alice_client):
    a_inst = Institution.objects.create(user=alice, name="A Bank", access_url="https://a.example")
    b_inst = Institution.objects.create(user=bob, name="B Bank", access_url="https://b.example")
    a_acc = Account.objects.create(institution=a_inst, name="A Checking", type="checking",
                                   balance=Decimal("0"), external_id="A-1")
    b_acc = Account.objects.create(institution=b_inst, name="B Checking", type="checking",
                                   balance=Decimal("0"), external_id="B-1")
    Transaction.objects.create(account=a_acc, posted_at=datetime(2026, 4, 1, tzinfo=dt_tz.utc), amount=Decimal("-10"), payee="Alice Coffee", external_id="t-a")
    Transaction.objects.create(account=b_acc, posted_at=datetime(2026, 4, 1, tzinfo=dt_tz.utc), amount=Decimal("-20"), payee="Bob Coffee", external_id="t-b")

    response = alice_client.get(reverse("transactions"))
    assert b"Alice Coffee" in response.content
    assert b"Bob Coffee" not in response.content


def test_transactions_filter_by_account(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="A Bank", access_url="https://a.example")
    acc1 = Account.objects.create(institution=inst, name="Checking", type="checking",
                                  balance=Decimal("0"), external_id="A-1")
    acc2 = Account.objects.create(institution=inst, name="Savings", type="savings",
                                  balance=Decimal("0"), external_id="A-2")
    Transaction.objects.create(account=acc1, posted_at=datetime(2026, 4, 1, tzinfo=dt_tz.utc), amount=Decimal("-10"), payee="Coffee A", external_id="t1")
    Transaction.objects.create(account=acc2, posted_at=datetime(2026, 4, 1, tzinfo=dt_tz.utc), amount=Decimal("-20"), payee="Coffee B", external_id="t2")

    response = alice_client.get(reverse("transactions"), {"account": acc1.id})
    assert b"Coffee A" in response.content
    assert b"Coffee B" not in response.content


def test_transactions_search_payee(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="A Bank", access_url="https://a.example")
    acc = Account.objects.create(institution=inst, name="Checking", type="checking",
                                 balance=Decimal("0"), external_id="A-1")
    Transaction.objects.create(account=acc, posted_at=datetime(2026, 4, 1, tzinfo=dt_tz.utc), amount=Decimal("-10"), payee="Trader Joes", external_id="t1")
    Transaction.objects.create(account=acc, posted_at=datetime(2026, 4, 1, tzinfo=dt_tz.utc), amount=Decimal("-20"), payee="Whole Foods", external_id="t2")

    response = alice_client.get(reverse("transactions"), {"q": "trader"})
    assert b"Trader Joes" in response.content
    assert b"Whole Foods" not in response.content


def test_transactions_pagination(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="A Bank", access_url="https://a.example")
    acc = Account.objects.create(institution=inst, name="Checking", type="checking",
                                 balance=Decimal("0"), external_id="A-1")
    for i in range(60):
        Transaction.objects.create(account=acc, posted_at=datetime(2026, 4, 1, tzinfo=dt_tz.utc), amount=Decimal("-1"),
                                   payee=f"tx-{i}", external_id=f"e-{i}")
    response = alice_client.get(reverse("transactions"))
    assert response.context["page_obj"].number == 1
    assert len(response.context["page_obj"].object_list) == 50
    response2 = alice_client.get(reverse("transactions"), {"page": 2})
    assert response2.context["page_obj"].number == 2
    assert len(response2.context["page_obj"].object_list) == 10
