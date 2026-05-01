from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.banking.categories import (
    RESERVED_SLUGS, get_user_categories, is_valid_category_for_user,
)
from apps.banking.models import Account, Institution, Transaction, UserCategory

User = get_user_model()


@pytest.mark.django_db
def test_get_user_categories_includes_builtins():
    user = User.objects.create_user(username="alice_uc1", password="x")
    cats = get_user_categories(user)
    assert "groceries" in cats
    assert cats["groceries"]["custom"] is False
    assert cats["groceries"]["kind"] == "spending"
    assert cats["income"]["kind"] == "income"
    assert cats["transfer"]["kind"] == "transfer"


@pytest.mark.django_db
def test_get_user_categories_includes_custom():
    user = User.objects.create_user(username="alice_uc2", password="x")
    UserCategory.objects.create(user=user, slug="pets", label="Pets", color="#aabbcc")
    cats = get_user_categories(user)
    assert "pets" in cats
    assert cats["pets"]["label"] == "Pets"
    assert cats["pets"]["color"] == "#aabbcc"
    assert cats["pets"]["custom"] is True


@pytest.mark.django_db
def test_get_user_categories_isolation():
    alice = User.objects.create_user(username="alice_uc3", password="x")
    bob = User.objects.create_user(username="bob_uc3", password="x")
    UserCategory.objects.create(user=alice, slug="alicepets", label="Pets", color="#aaa")
    bob_cats = get_user_categories(bob)
    assert "alicepets" not in bob_cats


@pytest.mark.django_db
def test_is_valid_category_for_user():
    user = User.objects.create_user(username="alice_uc4", password="x")
    assert is_valid_category_for_user(user, "groceries")
    assert not is_valid_category_for_user(user, "pets")
    UserCategory.objects.create(user=user, slug="pets", label="Pets", color="#aaa")
    assert is_valid_category_for_user(user, "pets")


@pytest.mark.django_db
def test_categories_settings_requires_login(client):
    response = client.get(reverse("banking:categories_settings"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_categories_settings_add(client):
    user = User.objects.create_user(username="alice_uc5", password="x")
    client.force_login(user)
    response = client.post(reverse("banking:categories_settings"), {
        "action": "add", "label": "Pets", "color": "#aabbcc",
    })
    assert response.status_code == 302
    cat = UserCategory.objects.get(user=user)
    assert cat.label == "Pets"
    assert cat.slug == "pets"


@pytest.mark.django_db
def test_categories_settings_add_rejects_reserved_slug(client):
    user = User.objects.create_user(username="alice_uc6", password="x")
    client.force_login(user)
    client.post(reverse("banking:categories_settings"), {
        "action": "add", "label": "Groceries", "color": "#aaa",
    })
    # Should be rejected because slug "groceries" is reserved.
    assert UserCategory.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_categories_settings_delete_resets_affected_transactions(client):
    user = User.objects.create_user(username="alice_uc7", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    cat = UserCategory.objects.create(user=user, slug="pets", label="Pets", color="#aaa")
    from datetime import datetime, timezone
    tx = Transaction.objects.create(account=acc, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-10"), external_id="t1", category="pets", category_manual=True)

    client.force_login(user)
    client.post(reverse("banking:categories_settings"), {
        "action": "delete", "id": cat.id,
    })

    tx.refresh_from_db()
    assert tx.category == "uncategorized"
    assert UserCategory.objects.filter(user=user).count() == 0
