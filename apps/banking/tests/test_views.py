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


def test_rename_transaction_persists_display_name(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    tx = Transaction.objects.create(
        account=account,
        posted_at=datetime(2026, 1, 1, tzinfo=dt_tz.utc),
        amount=Decimal("-12.34"), description="AMZN MKTP US*A1B2C3", payee="",
        external_id="t-1",
    )
    response = alice_client.post(
        reverse("banking:rename_transaction", args=[tx.id]),
        {"display_name": "Amazon — coffee mug"},
    )
    assert response.status_code == 302
    tx.refresh_from_db()
    assert tx.display_name == "Amazon — coffee mug"
    assert tx.effective_payee == "Amazon — coffee mug"


def test_rename_transaction_blank_restores_provider_payee(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    tx = Transaction.objects.create(
        account=account,
        posted_at=datetime(2026, 1, 1, tzinfo=dt_tz.utc),
        amount=Decimal("-12.34"), description="DESC", payee="PAYEE",
        display_name="Old Custom", external_id="t-1",
    )
    alice_client.post(
        reverse("banking:rename_transaction", args=[tx.id]),
        {"display_name": ""},
    )
    tx.refresh_from_db()
    assert tx.display_name == ""
    assert tx.effective_payee == "PAYEE"


def test_rename_transaction_forbidden_for_other_user(alice, bob, bob_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    tx = Transaction.objects.create(
        account=account,
        posted_at=datetime(2026, 1, 1, tzinfo=dt_tz.utc),
        amount=Decimal("-12.34"), description="DESC", payee="PAYEE",
        external_id="t-1",
    )
    response = bob_client.post(
        reverse("banking:rename_transaction", args=[tx.id]),
        {"display_name": "Pwned"},
    )
    assert response.status_code == 404
    tx.refresh_from_db()
    assert tx.display_name == ""


def test_rename_transaction_redirects_to_next_param(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    tx = Transaction.objects.create(
        account=account,
        posted_at=datetime(2026, 1, 1, tzinfo=dt_tz.utc),
        amount=Decimal("-12.34"), description="DESC", payee="PAYEE",
        external_id="t-1",
    )
    target = reverse("banking:account_detail", args=[account.id])
    response = alice_client.post(
        reverse("banking:rename_transaction", args=[tx.id]),
        {"display_name": "X", "next": target},
    )
    assert response.status_code == 302
    assert response["Location"] == target


def test_rename_transaction_rejects_external_next(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    tx = Transaction.objects.create(
        account=account,
        posted_at=datetime(2026, 1, 1, tzinfo=dt_tz.utc),
        amount=Decimal("-12.34"), description="DESC", payee="PAYEE",
        external_id="t-1",
    )
    response = alice_client.post(
        reverse("banking:rename_transaction", args=[tx.id]),
        {"display_name": "X", "next": "https://evil.example/path"},
    )
    assert response.status_code == 302
    assert response["Location"] == reverse("transactions")


def test_rename_transaction_get_embeds_back_url_from_referer(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    tx = Transaction.objects.create(
        account=account,
        posted_at=datetime(2026, 1, 1, tzinfo=dt_tz.utc),
        amount=Decimal("-12.34"), description="DESC", payee="PAYEE",
        external_id="t-1",
    )
    target = reverse("banking:account_detail", args=[account.id])
    response = alice_client.get(
        reverse("banking:rename_transaction", args=[tx.id]),
        HTTP_REFERER="http://testserver" + target,
    )
    assert response.status_code == 200
    assert f'name="next" value="http://testserver{target}"'.encode() in response.content


def test_transactions_list_shows_rename_link_and_effective_payee(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    tx = Transaction.objects.create(
        account=account,
        posted_at=datetime(2026, 1, 1, tzinfo=dt_tz.utc),
        amount=Decimal("-12.34"), description="DESC", payee="ProviderPayee",
        display_name="My Custom Label", external_id="t-1",
    )
    response = alice_client.get(reverse("transactions"))
    rename_url = reverse("banking:rename_transaction", args=[tx.id])
    assert rename_url.encode() in response.content
    assert b"My Custom Label" in response.content
    assert b"ProviderPayee" not in response.content


def test_transactions_search_matches_renamed_label(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    account = Account.objects.create(
        institution=inst, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    Transaction.objects.create(
        account=account,
        posted_at=datetime(2026, 1, 1, tzinfo=dt_tz.utc),
        amount=Decimal("-12.34"), description="AMZN MKTP US*A1B2C3", payee="",
        display_name="Amazon coffee mug", external_id="t-1",
    )
    Transaction.objects.create(
        account=account,
        posted_at=datetime(2026, 1, 2, tzinfo=dt_tz.utc),
        amount=Decimal("-50.00"), description="GROCERY", payee="WHOLE FOODS",
        external_id="t-2",
    )

    # Search for the user's custom label finds only the renamed row.
    response = alice_client.get(reverse("transactions") + "?q=coffee+mug")
    assert response.status_code == 200
    assert b"Amazon coffee mug" in response.content
    assert b"WHOLE FOODS" not in response.content


def test_cash_list_excludes_credit_and_loan(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="B", access_url="https://x")
    Account.objects.create(institution=inst, name="MyChecking", type="checking",
                           balance=Decimal("100"), external_id="A-1")
    Account.objects.create(institution=inst, name="MyVisa", type="credit",
                           balance=Decimal("500"), external_id="A-2")
    Account.objects.create(institution=inst, name="MyLoan", type="loan",
                           balance=Decimal("12000"), external_id="A-3")
    response = alice_client.get(reverse("banking:list"))
    assert response.status_code == 200
    assert b"MyChecking" in response.content
    assert b"MyVisa" not in response.content
    assert b"MyLoan" not in response.content


def test_account_detail_back_link_credit_goes_to_liabilities(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="B", access_url="https://x")
    credit = Account.objects.create(institution=inst, name="MyVisa", type="credit",
                                    balance=Decimal("500"), external_id="A-1")
    response = alice_client.get(reverse("banking:account_detail", args=[credit.id]))
    assert response.status_code == 200
    assert reverse("liabilities:list").encode() in response.content
    assert b"\xe2\x86\x90 Liabilities" in response.content


def test_account_detail_back_link_checking_goes_to_cash(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="B", access_url="https://x")
    checking = Account.objects.create(institution=inst, name="MyChecking", type="checking",
                                       balance=Decimal("100"), external_id="A-1")
    response = alice_client.get(reverse("banking:account_detail", args=[checking.id]))
    assert response.status_code == 200
    assert reverse("banking:list").encode() in response.content
    assert b"\xe2\x86\x90 Cash" in response.content


def test_cash_list_includes_savings_and_other(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="B", access_url="https://x")
    Account.objects.create(institution=inst, name="MySavings", type="savings",
                           balance=Decimal("100"), external_id="A-1")
    Account.objects.create(institution=inst, name="MyOther", type="other",
                           balance=Decimal("100"), external_id="A-2")
    response = alice_client.get(reverse("banking:list"))
    assert response.status_code == 200
    assert b"MySavings" in response.content
    assert b"MyOther" in response.content


@pytest.mark.django_db
def test_spending_page_requires_login(client):
    response = client.get(reverse("spending"))
    assert response.status_code == 302  # redirected to login


@pytest.mark.django_db
def test_spending_page_renders_for_authenticated_user(client):
    user = User.objects.create_user(username="alice_spending", password="x")
    client.force_login(user)
    response = client.get(reverse("spending"))
    assert response.status_code == 200
    assert b"Spending" in response.content


@pytest.mark.django_db
def test_spending_page_aggregates_correctly(client):
    user = User.objects.create_user(username="alice_spending2", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="A",
    )
    Transaction.objects.create(
        account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-100"), external_id="t1", category="groceries",
    )
    client.force_login(user)
    response = client.get(reverse("spending"))
    assert response.status_code == 200
    assert b"Groceries" in response.content


@pytest.mark.django_db
def test_transactions_list_filters_by_category(client):
    user = User.objects.create_user(username="alice_filter", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="A",
    )
    Transaction.objects.create(
        account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-50"), external_id="t1",
        category="groceries", payee="Whole Foods",
    )
    Transaction.objects.create(
        account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-30"), external_id="t2",
        category="dining", payee="Sushi Place",
    )

    client.force_login(user)
    response = client.get(reverse("transactions") + "?category=groceries")
    assert response.status_code == 200
    assert b"Whole Foods" in response.content
    assert b"Sushi Place" not in response.content


@pytest.mark.django_db
def test_set_category_endpoint_requires_login(client):
    inst = Institution.objects.create(
        user=User.objects.create_user(username="bob_setcat", password="x"),
        name="B", access_url="https://x",
    )
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-1"), external_id="t1",
    )
    response = client.post(
        reverse("banking:set_category", args=[tx.id]),
        {"category": "personal"},
    )
    assert response.status_code == 302  # redirect to login


@pytest.mark.django_db
def test_set_category_endpoint_sets_manual(client):
    user = User.objects.create_user(username="alice_setcat", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-1"), external_id="t1", category="uncategorized",
    )
    client.force_login(user)
    response = client.post(
        reverse("banking:set_category", args=[tx.id]),
        {"category": "personal"},
    )
    assert response.status_code == 200
    tx.refresh_from_db()
    assert tx.category == "personal"
    assert tx.category_manual is True


@pytest.mark.django_db
def test_set_category_endpoint_rejects_invalid_value(client):
    user = User.objects.create_user(username="alice_setcat2", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-1"), external_id="t1",
    )
    client.force_login(user)
    response = client.post(
        reverse("banking:set_category", args=[tx.id]),
        {"category": "BOGUS"},
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_set_category_endpoint_user_isolation(client):
    alice = User.objects.create_user(username="alice_iso", password="x")
    bob = User.objects.create_user(username="bob_iso", password="x")
    inst = Institution.objects.create(user=bob, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    bob_tx = Transaction.objects.create(
        account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-1"), external_id="t1",
    )
    client.force_login(alice)
    response = client.post(
        reverse("banking:set_category", args=[bob_tx.id]),
        {"category": "personal"},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_bulk_set_category_requires_login(client):
    response = client.post(
        reverse("banking:bulk_set_category"),
        {"category": "groceries", "transaction_ids": [1, 2]},
    )
    assert response.status_code == 302  # redirect to login


@pytest.mark.django_db
def test_bulk_set_category_updates_listed_transactions(client):
    user = User.objects.create_user(username="alice_bulk1", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx1 = Transaction.objects.create(account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-1"), external_id="t1", category="uncategorized")
    tx2 = Transaction.objects.create(account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-2"), external_id="t2", category="uncategorized")
    tx3 = Transaction.objects.create(account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-3"), external_id="t3", category="uncategorized")

    client.force_login(user)
    response = client.post(
        reverse("banking:bulk_set_category"),
        {"category": "groceries", "transaction_ids": [tx1.id, tx3.id]},
    )
    assert response.status_code == 200
    tx1.refresh_from_db(); tx2.refresh_from_db(); tx3.refresh_from_db()
    assert tx1.category == "groceries"
    assert tx1.category_manual is True
    assert tx2.category == "uncategorized"  # untouched
    assert tx2.category_manual is False
    assert tx3.category == "groceries"
    assert tx3.category_manual is True


@pytest.mark.django_db
def test_bulk_set_category_rejects_invalid_category(client):
    user = User.objects.create_user(username="alice_bulk2", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx = Transaction.objects.create(account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-1"), external_id="t1")
    client.force_login(user)
    response = client.post(
        reverse("banking:bulk_set_category"),
        {"category": "BOGUS", "transaction_ids": [tx.id]},
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_bulk_set_category_user_isolation(client):
    alice = User.objects.create_user(username="alice_bulk3", password="x")
    bob = User.objects.create_user(username="bob_bulk", password="x")
    inst = Institution.objects.create(user=bob, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    bob_tx = Transaction.objects.create(account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-1"), external_id="t1", category="uncategorized")
    client.force_login(alice)
    response = client.post(
        reverse("banking:bulk_set_category"),
        {"category": "groceries", "transaction_ids": [bob_tx.id]},
    )
    # Alice can't update Bob's transaction. Endpoint scopes by user, so it returns 200 with 0 updated.
    assert response.status_code == 200
    bob_tx.refresh_from_db()
    assert bob_tx.category == "uncategorized"


@pytest.mark.django_db
def test_bulk_set_category_returns_count(client):
    user = User.objects.create_user(username="alice_bulk4", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx_ids = []
    for i in range(3):
        tx = Transaction.objects.create(account=acc, posted_at=datetime.now(dt_tz.utc),
            amount=Decimal(f"-{i+1}"), external_id=f"t{i}", category="uncategorized")
        tx_ids.append(tx.id)
    client.force_login(user)
    response = client.post(
        reverse("banking:bulk_set_category"),
        {"category": "groceries", "transaction_ids": tx_ids},
    )
    import json
    data = json.loads(response.content)
    assert data["updated"] == 3


@pytest.mark.django_db
def test_bulk_set_category_by_filter_requires_login(client):
    response = client.post(
        reverse("banking:bulk_set_category_by_filter"),
        {"target_category": "groceries", "category_filter": "uncategorized"},
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_bulk_set_category_by_filter_applies_to_search_matches(client):
    user = User.objects.create_user(username="alice_filter1", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx1 = Transaction.objects.create(account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-1"), external_id="t1", payee="Whole Foods", category="uncategorized")
    tx2 = Transaction.objects.create(account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-2"), external_id="t2", payee="Whole Foods Market", category="uncategorized")
    tx3 = Transaction.objects.create(account=acc, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-3"), external_id="t3", payee="Lyft", category="uncategorized")

    client.force_login(user)
    response = client.post(
        reverse("banking:bulk_set_category_by_filter"),
        {"target_category": "groceries", "q": "Whole Foods"},
    )
    assert response.status_code == 200
    tx1.refresh_from_db(); tx2.refresh_from_db(); tx3.refresh_from_db()
    assert tx1.category == "groceries"
    assert tx1.category_manual is True
    assert tx2.category == "groceries"
    assert tx3.category == "uncategorized"  # didn't match the search


@pytest.mark.django_db
def test_bulk_set_category_by_filter_user_isolation(client):
    alice = User.objects.create_user(username="alice_filter2", password="x")
    bob = User.objects.create_user(username="bob_filter2", password="x")
    inst_b = Institution.objects.create(user=bob, name="B", access_url="https://x")
    acc_b = Account.objects.create(institution=inst_b, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    bob_tx = Transaction.objects.create(account=acc_b, posted_at=datetime.now(dt_tz.utc),
        amount=Decimal("-1"), external_id="t1", category="uncategorized")

    client.force_login(alice)
    response = client.post(
        reverse("banking:bulk_set_category_by_filter"),
        {"target_category": "groceries"},  # Alice has no transactions, this should affect 0
    )
    assert response.status_code == 200
    bob_tx.refresh_from_db()
    assert bob_tx.category == "uncategorized"  # Bob's transaction untouched


@pytest.mark.django_db
def test_bulk_set_category_by_filter_rejects_invalid_category(client):
    user = User.objects.create_user(username="alice_filter3", password="x")
    client.force_login(user)
    response = client.post(
        reverse("banking:bulk_set_category_by_filter"),
        {"target_category": "BOGUS"},
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_spending_page_month_navigation_default_is_current(client):
    user = User.objects.create_user(username="alice_navmonth1", password="x")
    client.force_login(user)
    response = client.get(reverse("spending"))
    assert response.status_code == 200
    # Default month: prev_month should be set, next_month should be None (we're on current month).
    assert response.context["prev_month"] is not None
    assert response.context["next_month"] is None


@pytest.mark.django_db
def test_spending_page_month_navigation_specific_past_month(client):
    user = User.objects.create_user(username="alice_navmonth2", password="x")
    client.force_login(user)
    response = client.get(reverse("spending") + "?period=month&month=2024-06")
    assert response.status_code == 200
    assert response.context["period_label"] == "June 2024"
    # Prev/next exist for past months.
    assert response.context["prev_month"] == "2024-05"
    assert response.context["next_month"] == "2024-07"


@pytest.mark.django_db
def test_spending_page_month_navigation_invalid_falls_back(client):
    user = User.objects.create_user(username="alice_navmonth3", password="x")
    client.force_login(user)
    response = client.get(reverse("spending") + "?period=month&month=garbage")
    assert response.status_code == 200
    # Bad input → falls back to current month.
    assert response.context["next_month"] is None


from apps.banking.views import _resolve_page_size, ALLOWED_PAGE_SIZES


class _FakeReq:
    """Minimal stand-in for Django HttpRequest — only `.GET` is used by the helper."""
    def __init__(self, get_params):
        self.GET = get_params


def test_resolve_page_size_default_when_missing():
    key, n = _resolve_page_size(_FakeReq({}))
    assert key == "50"
    assert n == 50


def test_resolve_page_size_explicit_known_values():
    for raw, expected_n in [("25", 25), ("50", 50), ("100", 100), ("200", 200)]:
        key, n = _resolve_page_size(_FakeReq({"size": raw}))
        assert key == raw
        assert n == expected_n


def test_resolve_page_size_all_caps_at_1000():
    key, n = _resolve_page_size(_FakeReq({"size": "all"}))
    assert key == "all"
    assert n == 1000


def test_resolve_page_size_invalid_falls_back():
    for raw in ["foo", "99", "0", "-50", "1000", " "]:
        key, n = _resolve_page_size(_FakeReq({"size": raw}))
        assert key == "50"
        assert n == 50


def test_resolve_page_size_case_insensitive_for_all():
    key, n = _resolve_page_size(_FakeReq({"size": "ALL"}))
    assert key == "all"
    assert n == 1000


def test_allowed_page_sizes_constants():
    assert set(ALLOWED_PAGE_SIZES.keys()) == {"25", "50", "100", "200", "all"}
    assert ALLOWED_PAGE_SIZES["all"] == 1000


from datetime import date as _date
from decimal import Decimal as _D


@pytest.fixture
def alice_with_60_transactions(alice):
    """Give Alice 60 transactions on a single account so we can exercise pagination."""
    inst = Institution.objects.create(user=alice, name="A Bank", access_url="https://a.example")
    acct = Account.objects.create(
        institution=inst, name="Checking", type="checking",
        balance=_D("1000.00"), external_id="A-1",
    )
    for i in range(60):
        Transaction.objects.create(
            account=acct,
            external_id=f"T-{i}",
            posted_at=_date(2026, 4, 1),
            amount=_D("-10.00"),
            description=f"tx-{i}",
        )
    return alice


def test_transactions_default_page_size_is_50(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("transactions"))
    assert r.status_code == 200
    assert r.context["page_obj"].paginator.per_page == 50
    assert r.context["selected_size"] == "50"


def test_transactions_size_100_loads_all_60(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("transactions") + "?size=100")
    assert r.status_code == 200
    assert r.context["page_obj"].paginator.per_page == 100
    assert r.context["selected_size"] == "100"
    # All 60 fit on one page now.
    assert len(r.context["page_obj"].object_list) == 60


def test_transactions_size_all_caps_at_1000(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("transactions") + "?size=all")
    assert r.context["page_obj"].paginator.per_page == 1000
    assert r.context["selected_size"] == "all"


def test_transactions_size_invalid_falls_back_to_50(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("transactions") + "?size=garbage")
    assert r.context["page_obj"].paginator.per_page == 50
    assert r.context["selected_size"] == "50"


def test_transactions_size_propagates_through_filter_qs(alice_with_60_transactions, alice_client):
    """filter_qs must include `size` so pagination/category links carry it through."""
    r = alice_client.get(reverse("transactions") + "?size=100&q=tx")
    filter_qs = r.context["filter_qs"]
    assert "size=100" in filter_qs
    assert "q=tx" in filter_qs


def test_transactions_default_size_omitted_from_filter_qs(alice_with_60_transactions, alice_client):
    """When size is at default, don't pollute filter_qs with `size=50`."""
    r = alice_client.get(reverse("transactions") + "?q=tx")
    filter_qs = r.context["filter_qs"]
    assert "size=" not in filter_qs


def test_transactions_page_renders_size_selector(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("transactions"))
    assert b'name="size"' in r.content
    # All five options should render.
    for opt in (b'value="25"', b'value="50"', b'value="100"', b'value="200"', b'value="all"'):
        assert opt in r.content


def test_transactions_size_100_marks_correct_option(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("transactions") + "?size=100")
    body = r.content.decode()
    # The 100 option should be marked selected; the 50 option should not be.
    import re
    m_100 = re.search(r'value="100"\s*selected', body)
    m_50 = re.search(r'value="50"\s*selected', body)
    assert m_100, "size=100 not marked selected"
    assert not m_50, "size=50 incorrectly marked selected when ?size=100"
