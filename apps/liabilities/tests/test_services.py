from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.banking.models import Account, Institution
from apps.liabilities.models import Liability
from apps.liabilities.services import liabilities_for, total_liabilities

User = get_user_model()


@pytest.mark.django_db
def test_combined_source_listing_includes_bank_credit_and_manual():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    Account.objects.create(institution=inst, name="Visa", type="credit", balance=Decimal("500"), external_id="V1")
    Account.objects.create(institution=inst, name="Loan", type="loan", balance=Decimal("12000"), external_id="L1")
    Account.objects.create(institution=inst, name="Checking", type="checking", balance=Decimal("3000"), external_id="C1")
    Liability.objects.create(user=user, name="Student loan", balance=Decimal("25000"))

    rows = liabilities_for(user)
    names = [r.name for r in rows]
    assert "Visa" in names
    assert "Loan" in names
    assert "Student loan" in names
    assert "Checking" not in names

    assert total_liabilities(user) == Decimal("37500")  # 500 + 12000 + 25000


@pytest.mark.django_db
def test_total_liabilities_isolates_users():
    a = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    b = User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")
    Liability.objects.create(user=a, name="A", balance=Decimal("100"))
    Liability.objects.create(user=b, name="B", balance=Decimal("200"))
    assert total_liabilities(a) == Decimal("100")
    assert total_liabilities(b) == Decimal("200")
