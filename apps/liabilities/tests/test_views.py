from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.liabilities.models import Liability

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


def test_list_empty(alice_client):
    r = alice_client.get(reverse("liabilities:list"))
    assert r.status_code == 200
    assert b"No liabilities" in r.content


def test_add_persists(alice_client):
    r = alice_client.post(reverse("liabilities:add"), {"name": "Student loan", "balance": "25000", "notes": "5%"})
    assert r.status_code == 302
    assert Liability.objects.filter(name="Student loan").exists()


def test_edit_isolation(alice, bob, bob_client):
    lia = Liability.objects.create(user=alice, name="X", balance=Decimal("1"))
    r = bob_client.post(reverse("liabilities:edit", args=[lia.id]), {"name": "pwn", "balance": "0"})
    assert r.status_code == 404


def test_delete_flow(alice, alice_client):
    lia = Liability.objects.create(user=alice, name="X", balance=Decimal("1"))
    r = alice_client.post(reverse("liabilities:delete", args=[lia.id]))
    assert r.status_code == 302
    assert not Liability.objects.filter(pk=lia.id).exists()


def test_delete_isolation(alice, bob, bob_client):
    lia = Liability.objects.create(user=alice, name="X", balance=Decimal("1"))
    r = bob_client.post(reverse("liabilities:delete", args=[lia.id]))
    assert r.status_code == 404
    assert Liability.objects.filter(pk=lia.id).exists()


def test_anonymous_redirects():
    c = Client()
    r = c.get(reverse("liabilities:list"))
    assert r.status_code == 302
    assert "/login/" in r["Location"]


def test_liabilities_list_renders_type_pills(alice, alice_client):
    from apps.banking.models import Institution, Account
    inst = Institution.objects.create(user=alice, name="Bank", access_url="https://x")
    Account.objects.create(institution=inst, name="Visa", type="credit",
                           balance=Decimal("500"), external_id="V1")
    Account.objects.create(institution=inst, name="CarLoan", type="loan",
                           balance=Decimal("12000"), external_id="L1")
    Liability.objects.create(user=alice, name="Student loan", balance=Decimal("25000"))

    response = alice_client.get(reverse("liabilities:list"))
    assert response.status_code == 200
    assert b"Credit" in response.content
    assert b"Loan" in response.content
    assert b"Manual" in response.content
