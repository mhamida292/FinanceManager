from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.liabilities.models import Liability

User = get_user_model()


@pytest.mark.django_db
def test_liability_for_user_isolates():
    alice = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    bob = User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")
    Liability.objects.create(user=alice, name="Alice loan", balance=Decimal("1000"))
    Liability.objects.create(user=bob, name="Bob loan", balance=Decimal("2000"))

    assert list(Liability.objects.for_user(alice).values_list("name", flat=True)) == ["Alice loan"]
    assert list(Liability.objects.for_user(bob).values_list("name", flat=True)) == ["Bob loan"]
