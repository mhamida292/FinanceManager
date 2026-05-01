from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.banking.models import Account, Institution, Transaction
from apps.banking.services import income_expense_summary, link_institution, set_category, spending_breakdown, sync_institution
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
def test_display_balance_inverts_sign_for_credit_and_loan_accounts():
    """Provider APIs report credit-card and loan balances as positive (amount owed).
    display_balance flips that for user-facing rendering so it lines up with the
    Liabilities page's convention."""
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")

    checking = Account.objects.create(
        institution=inst, name="Checking", type="checking",
        balance=Decimal("1500.00"), external_id="A-CHK",
    )
    overdrawn = Account.objects.create(
        institution=inst, name="Overdrawn", type="checking",
        balance=Decimal("-25.00"), external_id="A-OD",
    )
    credit = Account.objects.create(
        institution=inst, name="Card", type="credit",
        balance=Decimal("1234.56"), external_id="A-CC",
    )
    loan = Account.objects.create(
        institution=inst, name="Mortgage", type="loan",
        balance=Decimal("250000.00"), external_id="A-LN",
    )

    # Depository: pass-through (sign preserved).
    assert checking.display_balance == Decimal("1500.00")
    assert overdrawn.display_balance == Decimal("-25.00")
    # Credit / loan: always negative (regardless of how provider signed it).
    assert credit.display_balance == Decimal("-1234.56")
    assert loan.display_balance == Decimal("-250000.00")


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


@pytest.mark.django_db
def test_new_transaction_from_teller_like_provider_gets_mapped_category(monkeypatch):
    """When the provider returns provider_category='groceries', the new Transaction
    is created with category='groceries' (mapped) and category_manual=False."""
    user = User.objects.create_user(username="alice", password="x")

    class _CategorizingProvider(_FakeProvider):
        def __init__(self):
            super().__init__()
            self._payloads = [
                AccountSyncPayload(
                    account=AccountData(
                        external_id="ACC-1", name="Checking", type="checking",
                        balance=Decimal("100"), currency="USD", org_name="Bank",
                    ),
                    transactions=(
                        TransactionData(
                            external_id="TXN-G",
                            posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                            amount=Decimal("-25.00"), description="Whole Foods",
                            payee="Whole Foods", memo="", pending=False,
                            provider_category="groceries",
                        ),
                        TransactionData(
                            external_id="TXN-N",
                            posted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                            amount=Decimal("-3.00"), description="Cash",
                            payee="ATM", memo="", pending=False,
                            provider_category=None,
                        ),
                    ),
                ),
            ]

    registry_module._REGISTRY["fake"] = _CategorizingProvider
    registry_module._REGISTRY["simplefin"] = _CategorizingProvider

    inst = link_institution(
        user=user, setup_token="t", display_name="Bank", provider_name="fake",
    )
    txg = Transaction.objects.get(account__institution=inst, external_id="TXN-G")
    txn = Transaction.objects.get(account__institution=inst, external_id="TXN-N")

    assert txg.category == "groceries"
    assert txg.category_manual is False
    assert txn.category == "uncategorized"
    assert txn.category_manual is False


@pytest.mark.django_db
def test_sync_does_not_overwrite_user_category_override():
    """If a user manually sets category and category_manual=True, sync must preserve it."""
    user = User.objects.create_user(username="alice", password="x")

    class _CategorizingProvider(_FakeProvider):
        def __init__(self):
            super().__init__()
            self._payloads = [
                AccountSyncPayload(
                    account=AccountData(
                        external_id="ACC-1", name="Checking", type="checking",
                        balance=Decimal("100"), currency="USD", org_name="Bank",
                    ),
                    transactions=(
                        TransactionData(
                            external_id="TXN-1",
                            posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                            amount=Decimal("-25"), description="Generic",
                            payee="Generic", memo="", pending=False,
                            provider_category="dining",
                        ),
                    ),
                ),
            ]

    registry_module._REGISTRY["fake"] = _CategorizingProvider
    registry_module._REGISTRY["simplefin"] = _CategorizingProvider

    inst = link_institution(
        user=user, setup_token="t", display_name="Bank", provider_name="fake",
    )
    tx = Transaction.objects.get(account__institution=inst, external_id="TXN-1")
    # User overrides
    tx.category = "personal"
    tx.category_manual = True
    tx.save(update_fields=["category", "category_manual"])

    sync_institution(inst)

    tx.refresh_from_db()
    assert tx.category == "personal", "Manual override must survive sync"
    assert tx.category_manual is True


@pytest.mark.django_db
def test_sync_re_applies_mapping_when_not_manually_overridden():
    """If category_manual is False, sync re-applies the mapped category each time
    (in case the provider's classification changed)."""
    user = User.objects.create_user(username="alice", password="x")

    class _MutableProvider:
        name = "fake"

        def __init__(self):
            self.current_category = "dining"

        def exchange_setup_token(self, t):
            return "https://fake"

        def fetch_accounts_with_transactions(self, access_url, *, since=None):
            yield AccountSyncPayload(
                account=AccountData(
                    external_id="ACC-1", name="Checking", type="checking",
                    balance=Decimal("100"), currency="USD", org_name="Bank",
                ),
                transactions=(
                    TransactionData(
                        external_id="TXN-1",
                        posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        amount=Decimal("-25"), description="X", payee="X",
                        memo="", pending=False,
                        provider_category=self.current_category,
                    ),
                ),
            )

    provider_instance = _MutableProvider()
    registry_module._REGISTRY["fake"] = lambda: provider_instance
    registry_module._REGISTRY["simplefin"] = lambda: provider_instance

    inst = link_institution(
        user=user, setup_token="t", display_name="Bank", provider_name="fake",
    )
    tx = Transaction.objects.get(account__institution=inst, external_id="TXN-1")
    assert tx.category == "dining"

    # Provider re-categorizes; user has NOT overridden.
    provider_instance.current_category = "groceries"
    sync_institution(inst)

    tx.refresh_from_db()
    assert tx.category == "groceries"
    assert tx.category_manual is False


@pytest.mark.django_db
def test_spending_breakdown_orders_descending_excludes_income_and_transfer():
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="A1",
    )
    base = datetime(2026, 4, 15, tzinfo=timezone.utc)
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("-300"),
        external_id="t1", category="groceries")
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("-100"),
        external_id="t2", category="dining")
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("2000"),
        external_id="t3", category="income")
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("-500"),
        external_id="t4", category="transfer")
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("-50"),
        external_id="t5", category="uncategorized")

    rows = spending_breakdown(user, date(2026, 4, 1), date(2026, 4, 30))
    keys = [r.category for r in rows]

    assert "income" not in keys
    assert "transfer" not in keys
    # Descending by total
    assert keys[0] == "groceries"
    assert keys[1] == "dining"
    # Uncategorized is included (call to action)
    assert "uncategorized" in keys


@pytest.mark.django_db
def test_spending_breakdown_user_isolation():
    alice = User.objects.create_user(username="alice", password="x")
    bob = User.objects.create_user(username="bob", password="x")
    inst_a = Institution.objects.create(user=alice, name="A", access_url="https://x")
    inst_b = Institution.objects.create(user=bob, name="B", access_url="https://y")
    acc_a = Account.objects.create(institution=inst_a, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    acc_b = Account.objects.create(institution=inst_b, name="B", type="checking",
        balance=Decimal("0"), external_id="B")
    base = datetime(2026, 4, 15, tzinfo=timezone.utc)
    Transaction.objects.create(account=acc_a, posted_at=base, amount=Decimal("-100"),
        external_id="t1", category="groceries")
    Transaction.objects.create(account=acc_b, posted_at=base, amount=Decimal("-9999"),
        external_id="t2", category="groceries")

    rows = spending_breakdown(alice, date(2026, 4, 1), date(2026, 4, 30))
    totals = {r.category: r.total for r in rows}
    assert totals["groceries"] == Decimal("100")


@pytest.mark.django_db
def test_spending_breakdown_credit_card_charge_counts_as_spending():
    """A credit-card charge has positive raw amount but display_amount is negative.
    spending_breakdown should treat it as money out (positive total)."""
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    cc = Account.objects.create(
        institution=inst, name="Card", type="credit",
        balance=Decimal("0"), external_id="CC",
    )
    base = datetime(2026, 4, 15, tzinfo=timezone.utc)
    # Raw +$50 charge on a credit card = $50 spent.
    Transaction.objects.create(account=cc, posted_at=base, amount=Decimal("50"),
        external_id="t1", category="dining")

    rows = spending_breakdown(user, date(2026, 4, 1), date(2026, 4, 30))
    dining = [r for r in rows if r.category == "dining"][0]
    assert dining.total == Decimal("50")


@pytest.mark.django_db
def test_spending_breakdown_empty_range():
    user = User.objects.create_user(username="alice", password="x")
    rows = spending_breakdown(user, date(2026, 4, 1), date(2026, 4, 30))
    assert rows == []


@pytest.mark.django_db
def test_income_expense_summary_excludes_transfers():
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="A",
    )
    base = datetime(2026, 4, 15, tzinfo=timezone.utc)
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("2000"),
        external_id="t1", category="income")
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("500"),
        external_id="t2", category="income")
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("-300"),
        external_id="t3", category="groceries")
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("-100"),
        external_id="t4", category="dining")
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("-1000"),
        external_id="t5", category="transfer")

    income, expense = income_expense_summary(user, date(2026, 4, 1), date(2026, 4, 30))
    assert income == Decimal("2500")
    assert expense == Decimal("400")


@pytest.mark.django_db
def test_income_expense_summary_empty_range():
    user = User.objects.create_user(username="alice", password="x")
    income, expense = income_expense_summary(user, date(2026, 4, 1), date(2026, 4, 30))
    assert income == Decimal("0")
    assert expense == Decimal("0")


@pytest.mark.django_db
def test_set_category_marks_manual():
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="A",
    )
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        amount=Decimal("-10"), external_id="t1", category="uncategorized",
    )

    set_category(tx, "personal")

    tx.refresh_from_db()
    assert tx.category == "personal"
    assert tx.category_manual is True


@pytest.mark.django_db
def test_set_category_rejects_unknown_value():
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="A",
    )
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        amount=Decimal("-10"), external_id="t1",
    )

    with pytest.raises(ValueError):
        set_category(tx, "not-a-real-category")


@pytest.mark.django_db
def test_spending_breakdown_include_transfers_flag():
    """When include_transfers=True, transfers appear as a slice. By default they don't."""
    user = User.objects.create_user(username="alice_xfer", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="A",
    )
    base = datetime(2026, 4, 15, tzinfo=timezone.utc)
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("-300"),
        external_id="t1", category="groceries")
    Transaction.objects.create(account=acc, posted_at=base, amount=Decimal("-500"),
        external_id="t2", category="transfer")

    # Default: transfers excluded.
    rows_default = spending_breakdown(user, date(2026, 4, 1), date(2026, 4, 30))
    keys_default = [r.category for r in rows_default]
    assert "transfer" not in keys_default

    # With flag: transfers included.
    rows_with = spending_breakdown(user, date(2026, 4, 1), date(2026, 4, 30), include_transfers=True)
    keys_with = [r.category for r in rows_with]
    assert "transfer" in keys_with
    transfer_row = [r for r in rows_with if r.category == "transfer"][0]
    assert transfer_row.total == Decimal("500")


@pytest.mark.django_db
def test_sync_auto_detects_transfer_when_provider_category_missing():
    """When provider_category=None and payee matches a transfer pattern,
    the new transaction is created with category='transfer'."""
    user = User.objects.create_user(username="alice_xferdetect", password="x")

    class _AutoXferProvider(_FakeProvider):
        def __init__(self):
            super().__init__()
            self._payloads = [
                AccountSyncPayload(
                    account=AccountData(
                        external_id="ACC-1", name="Checking", type="checking",
                        balance=Decimal("100"), currency="USD", org_name="Bank",
                    ),
                    transactions=(
                        TransactionData(
                            external_id="TXN-PYMT",
                            posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                            amount=Decimal("-170"), description="",
                            payee="CAPITAL ONE MOBILE PYMT", memo="", pending=False,
                            provider_category=None,
                        ),
                        TransactionData(
                            external_id="TXN-COFFEE",
                            posted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                            amount=Decimal("-5"), description="",
                            payee="Qamaria Yemeni Coffee", memo="", pending=False,
                            provider_category=None,
                        ),
                    ),
                ),
            ]

    registry_module._REGISTRY["fake"] = _AutoXferProvider
    registry_module._REGISTRY["simplefin"] = _AutoXferProvider

    inst = link_institution(
        user=user, setup_token="t", display_name="Bank", provider_name="fake",
    )
    pymt = Transaction.objects.get(account__institution=inst, external_id="TXN-PYMT")
    coffee = Transaction.objects.get(account__institution=inst, external_id="TXN-COFFEE")

    assert pymt.category == "transfer"  # heuristic caught it
    assert coffee.category == "uncategorized"  # no pattern match


@pytest.mark.django_db
def test_sync_overrides_other_with_transfer_heuristic_when_payee_matches():
    """If Teller classified a transaction as a vague category that maps to 'other'
    AND the payee matches a transfer keyword, the heuristic upgrades it to 'transfer'."""
    user = User.objects.create_user(username="alice_xferskip", password="x")

    class _MisLabeledProvider(_FakeProvider):
        def __init__(self):
            super().__init__()
            self._payloads = [
                AccountSyncPayload(
                    account=AccountData(
                        external_id="ACC-1", name="Checking", type="checking",
                        balance=Decimal("100"), currency="USD", org_name="Bank",
                    ),
                    transactions=(
                        TransactionData(
                            external_id="TXN-1",
                            posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                            amount=Decimal("-50"), description="",
                            payee="ZELLE TRANSFER TO SAM", memo="", pending=False,
                            # Teller used vague "service" → maps to "other"; heuristic upgrades.
                            provider_category="service",
                        ),
                    ),
                ),
            ]

    registry_module._REGISTRY["fake"] = _MisLabeledProvider
    registry_module._REGISTRY["simplefin"] = _MisLabeledProvider

    inst = link_institution(
        user=user, setup_token="t", display_name="Bank", provider_name="fake",
    )
    tx = Transaction.objects.get(account__institution=inst, external_id="TXN-1")
    # Teller said "service" → maps to "other"; heuristic sees ZELLE and upgrades to "transfer".
    assert tx.category == "transfer"


@pytest.mark.django_db
def test_sync_auto_detects_transfer_when_teller_marks_as_other():
    """When Teller's category maps to 'other' AND the payee matches a transfer pattern,
    the sync hook overrides 'other' to 'transfer'."""
    user = User.objects.create_user(username="alice_xferother", password="x")

    class _MisLabeledOtherProvider(_FakeProvider):
        def __init__(self):
            super().__init__()
            self._payloads = [
                AccountSyncPayload(
                    account=AccountData(
                        external_id="ACC-1", name="Checking", type="checking",
                        balance=Decimal("100"), currency="USD", org_name="Bank",
                    ),
                    transactions=(
                        TransactionData(
                            external_id="TXN-PYMT",
                            posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                            amount=Decimal("-100"), description="",
                            payee="CAPITAL ONE MOBILE PYMT", memo="", pending=False,
                            # Teller said "service" → maps to "other" via TELLER_TO_FINLAB.
                            provider_category="service",
                        ),
                    ),
                ),
            ]

    registry_module._REGISTRY["fake"] = _MisLabeledOtherProvider
    registry_module._REGISTRY["simplefin"] = _MisLabeledOtherProvider

    inst = link_institution(
        user=user, setup_token="t", display_name="Bank", provider_name="fake",
    )
    tx = Transaction.objects.get(account__institution=inst, external_id="TXN-PYMT")
    assert tx.category == "transfer"  # heuristic upgraded "other" → "transfer"
