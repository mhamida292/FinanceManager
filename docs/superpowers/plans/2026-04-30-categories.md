# Transaction Categories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface transaction categories in FinLab — ingest Teller's `details.category`, store it on `Transaction`, render pills + breakdown charts, allow inline override that survives re-sync.

**Architecture:** Curated 17-value vocabulary stored as a Python constant. New `Transaction.category` (CharField with choices) + `Transaction.category_manual` (boolean override flag). Aggregation services in `apps/banking/services.py`. Two new chart surfaces (dashboard widget + `/spending/` page) plus inline pill+filter on the existing transactions list. Backfill command re-fetches Teller history once at deploy time.

**Tech Stack:** Django 5.1, pytest-django, server-rendered SVG (no client-side chart lib), inline POST + HTML-fragment swap for pill edits (no HTMX dependency — vanilla `fetch` + `replaceWith`).

**Spec:** `docs/superpowers/specs/2026-04-30-categories-design.md`

---

## File Structure

**Create:**
- `apps/banking/categories.py` — vocabulary, Teller mapping, color map
- `apps/banking/migrations/0005_transaction_category.py` — auto-generated
- `apps/banking/templatetags/category_tags.py` — pie SVG renderer + pill HTML helper
- `apps/banking/templates/banking/spending.html` — `/spending/` page
- `apps/banking/templates/banking/_category_pill.html` — partial (rendered after edit)
- `apps/banking/templates/banking/_category_picker.html` — popup/drawer (returned by GET on the picker URL)
- `apps/banking/management/commands/categorize_existing_teller.py` — backfill
- `apps/banking/tests/test_categories.py` — vocabulary + mapping tests

**Modify:**
- `apps/banking/models.py` — add `category`, `category_manual` fields
- `apps/banking/services.py` — sync writer category logic + new aggregation services
- `apps/banking/views.py` — `/spending/` view, set-category endpoint, modify transactions-list view (filter)
- `apps/banking/urls.py` — register new routes
- `apps/banking/templates/banking/transactions_list.html` — pill + filter bar
- `apps/dashboard/views.py` — pass spending widget data
- `apps/dashboard/templates/dashboard/index.html` — render widget
- `apps/providers/base.py` — add `provider_category` to `TransactionData`
- `apps/providers/teller.py` — populate `provider_category` in `_parse_transaction`
- `apps/providers/tests/test_teller.py` — extend tests
- `apps/banking/tests/test_services.py` — extend with sync-regression + aggregation tests

---

## Task 1: Define category vocabulary and Teller mapping

**Files:**
- Create: `apps/banking/categories.py`
- Test: `apps/banking/tests/test_categories.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/banking/tests/test_categories.py
from apps.banking.categories import (
    ALL_CATEGORIES, CATEGORY_CHOICES, CATEGORY_COLORS, CATEGORY_LABELS,
    INCOME_CATEGORIES, SPENDING_CATEGORIES, TRANSFER_CATEGORIES,
    map_teller_category,
)


def test_spending_categories_contains_all_14():
    expected = {
        "groceries", "dining", "transportation", "utilities", "bills",
        "housing", "health", "entertainment", "shopping", "software",
        "travel", "personal", "charity", "other",
    }
    assert set(SPENDING_CATEGORIES) == expected


def test_all_categories_includes_income_transfer_uncategorized():
    assert "income" in ALL_CATEGORIES
    assert "transfer" in ALL_CATEGORIES
    assert "uncategorized" in ALL_CATEGORIES
    assert len(ALL_CATEGORIES) == 17


def test_category_choices_is_list_of_pairs():
    assert all(isinstance(c, tuple) and len(c) == 2 for c in CATEGORY_CHOICES)
    assert ("groceries", "Groceries") in CATEGORY_CHOICES


def test_category_colors_covers_all_categories():
    for c in ALL_CATEGORIES:
        assert c in CATEGORY_COLORS, f"missing color for {c}"
        assert CATEGORY_COLORS[c].startswith("#")


def test_category_labels_covers_all_categories():
    for c in ALL_CATEGORIES:
        assert c in CATEGORY_LABELS


def test_map_teller_category_known_values():
    assert map_teller_category("groceries") == "groceries"
    assert map_teller_category("bar") == "dining"
    assert map_teller_category("transport") == "transportation"
    assert map_teller_category("transportation") == "transportation"
    assert map_teller_category("fuel") == "transportation"
    assert map_teller_category("phone") == "bills"
    assert map_teller_category("insurance") == "bills"
    assert map_teller_category("loan") == "bills"
    assert map_teller_category("accommodation") == "housing"
    assert map_teller_category("home") == "housing"
    assert map_teller_category("clothing") == "shopping"
    assert map_teller_category("software") == "software"
    assert map_teller_category("charity") == "charity"
    assert map_teller_category("income") == "income"
    assert map_teller_category("tax") == "other"
    assert map_teller_category("advertising") == "other"


def test_map_teller_category_unknown_falls_through():
    assert map_teller_category("flying-saucers") == "uncategorized"


def test_map_teller_category_none_or_empty():
    assert map_teller_category(None) == "uncategorized"
    assert map_teller_category("") == "uncategorized"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest apps/banking/tests/test_categories.py -v`
Expected: FAIL — `apps.banking.categories` does not exist.

- [ ] **Step 3: Implement the module**

```python
# apps/banking/categories.py
"""Category vocabulary and Teller mapping. Single source of truth."""

SPENDING_CATEGORIES = [
    "groceries", "dining", "transportation", "utilities", "bills",
    "housing", "health", "entertainment", "shopping", "software",
    "travel", "personal", "charity", "other",
]

INCOME_CATEGORIES = ["income"]
TRANSFER_CATEGORIES = ["transfer"]
UNCATEGORIZED = "uncategorized"

ALL_CATEGORIES = SPENDING_CATEGORIES + INCOME_CATEGORIES + TRANSFER_CATEGORIES + [UNCATEGORIZED]

CATEGORY_LABELS = {c: c.replace("_", " ").title() for c in ALL_CATEGORIES}

CATEGORY_CHOICES = [(c, CATEGORY_LABELS[c]) for c in ALL_CATEGORIES]

# Quiet-theme-aligned palette: muted, distinct hues.
CATEGORY_COLORS = {
    "groceries":     "#7a9a6a",
    "dining":        "#c08868",
    "transportation":"#8a8aaa",
    "utilities":     "#c8a868",
    "bills":         "#a87a8a",
    "housing":       "#6a8a9a",
    "health":        "#9b6a7a",
    "entertainment": "#a89a6a",
    "shopping":      "#7a6a9a",
    "software":      "#6a9a8a",
    "travel":        "#9a8a6a",
    "personal":      "#aa7aaa",
    "charity":       "#7aaa9a",
    "other":         "#888888",
    "income":        "#88a877",
    "transfer":      "#5a7aaa",
    "uncategorized": "#444444",
}

# Teller's `details.category` strings → our 14-spending-category vocabulary.
TELLER_TO_FINLAB = {
    "groceries":      "groceries",
    "dining":         "dining",
    "bar":            "dining",
    "transport":      "transportation",
    "transportation": "transportation",
    "fuel":           "transportation",
    "utilities":      "utilities",
    "phone":          "bills",
    "insurance":      "bills",
    "loan":           "bills",
    "accommodation":  "housing",
    "home":           "housing",
    "health":         "health",
    "entertainment":  "entertainment",
    "sport":          "entertainment",
    "shopping":       "shopping",
    "clothing":       "shopping",
    "electronics":    "shopping",
    "software":       "software",
    "charity":        "charity",
    "income":         "income",
    # Fall-through to "other":
    "tax":         "other",
    "education":   "other",
    "investment":  "other",
    "service":     "other",
    "general":     "other",
    "office":      "other",
    "advertising": "other",
}


def map_teller_category(teller_value: str | None) -> str:
    """Translate a Teller category string into a FinLab category.
    Unknown strings, None, and empty strings → 'uncategorized'."""
    if not teller_value:
        return UNCATEGORIZED
    return TELLER_TO_FINLAB.get(teller_value, UNCATEGORIZED)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest apps/banking/tests/test_categories.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/banking/categories.py apps/banking/tests/test_categories.py
git commit -m "feat(banking): category vocabulary and Teller mapping"
```

---

## Task 2: Add `category` and `category_manual` to Transaction

**Files:**
- Modify: `apps/banking/models.py:105-145` (Transaction model)
- Create: `apps/banking/migrations/0005_transaction_category.py` (auto-generated)

- [ ] **Step 1: Add fields to the Transaction model**

In `apps/banking/models.py`, add these two imports near the top (file already imports `models` and `settings`):

```python
from .categories import CATEGORY_CHOICES, UNCATEGORIZED
```

Then add the two fields inside `class Transaction(...)`, after the `pending` field (around line 116):

```python
    pending = models.BooleanField(default=False)
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default=UNCATEGORIZED,
        db_index=True,
    )
    category_manual = models.BooleanField(default=False)
    external_id = models.CharField(max_length=200, help_text="Provider's txn ID; upsert key.")
```

- [ ] **Step 2: Generate the migration**

Run: `docker compose exec web python manage.py makemigrations banking`
Expected: creates `apps/banking/migrations/0005_transaction_category.py` adding both fields.

- [ ] **Step 3: Apply the migration locally and verify it loads**

Run: `docker compose exec web python manage.py migrate banking`
Expected: `Applying banking.0005_transaction_category... OK`

- [ ] **Step 4: Run the existing test suite to confirm nothing regressed**

Run: `docker compose exec web pytest apps/banking/ -q`
Expected: all existing tests still pass; new fields default `category="uncategorized"` and `category_manual=False` so existing assertions are unaffected.

- [ ] **Step 5: Commit**

```bash
git add apps/banking/models.py apps/banking/migrations/0005_transaction_category.py
git commit -m "feat(banking): add category and category_manual fields to Transaction"
```

---

## Task 3: Add `provider_category` to TransactionData

**Files:**
- Modify: `apps/providers/base.py:17-26` (TransactionData dataclass)

- [ ] **Step 1: Add the field**

In `apps/providers/base.py`, modify the `TransactionData` dataclass:

```python
@dataclass(frozen=True)
class TransactionData:
    external_id: str
    posted_at: datetime
    amount: Decimal
    description: str
    payee: str
    memo: str
    pending: bool
    provider_category: str | None = None
```

- [ ] **Step 2: Run the existing provider/banking tests to ensure nothing broke**

Run: `docker compose exec web pytest apps/providers/ apps/banking/ -q`
Expected: all pass. The new field defaults to `None` so existing `TransactionData(...)` constructions remain valid.

- [ ] **Step 3: Commit**

```bash
git add apps/providers/base.py
git commit -m "feat(providers): add provider_category to TransactionData"
```

---

## Task 4: Teller parser populates `provider_category`

**Files:**
- Modify: `apps/providers/teller.py:135-150` (`_parse_transaction`)
- Modify: `apps/providers/tests/test_teller.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add these tests at the end of `apps/providers/tests/test_teller.py`:

```python
def test_parse_transaction_extracts_category():
    provider = TellerProvider(http=requests.Session())
    raw = {
        "id": "txn_x",
        "date": "2026-04-15",
        "amount": "-12.50",
        "description": "Whole Foods",
        "details": {
            "category": "groceries",
            "counterparty": {"name": "Whole Foods Market"},
            "processing_status": "complete",
        },
    }
    tx = provider._parse_transaction(raw)
    assert tx.provider_category == "groceries"


def test_parse_transaction_handles_missing_category():
    provider = TellerProvider(http=requests.Session())
    raw = {
        "id": "txn_y",
        "date": "2026-04-15",
        "amount": "-5.00",
        "description": "Mystery",
        "details": {"counterparty": {}, "processing_status": "complete"},
    }
    tx = provider._parse_transaction(raw)
    assert tx.provider_category is None


def test_parse_transaction_handles_missing_details():
    provider = TellerProvider(http=requests.Session())
    raw = {
        "id": "txn_z",
        "date": "2026-04-15",
        "amount": "-5.00",
        "description": "Mystery",
    }
    tx = provider._parse_transaction(raw)
    assert tx.provider_category is None
```

If `requests` isn't already imported in the test file, add `import requests` at the top.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest apps/providers/tests/test_teller.py::test_parse_transaction_extracts_category apps/providers/tests/test_teller.py::test_parse_transaction_handles_missing_category apps/providers/tests/test_teller.py::test_parse_transaction_handles_missing_details -v`
Expected: FAIL — `provider_category` is not populated.

- [ ] **Step 3: Modify `_parse_transaction`**

Replace the body of `_parse_transaction` in `apps/providers/teller.py` with:

```python
    def _parse_transaction(self, raw: dict) -> TransactionData:
        details = raw.get("details") or {}
        counterparty = details.get("counterparty") or {}
        posted_at = datetime.combine(
            datetime.strptime(str(raw["date"]), "%Y-%m-%d").date(),
            time.min, tzinfo=timezone.utc,
        )
        return TransactionData(
            external_id=str(raw["id"]),
            posted_at=posted_at,
            amount=Decimal(str(raw.get("amount", "0"))),
            description=str(raw.get("description", "")),
            payee=str(counterparty.get("name") or raw.get("description", "")),
            memo="",
            pending=str(details.get("processing_status", "")) == "pending",
            provider_category=details.get("category"),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest apps/providers/tests/test_teller.py -v`
Expected: PASS (all existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add apps/providers/teller.py apps/providers/tests/test_teller.py
git commit -m "feat(teller): extract details.category into TransactionData.provider_category"
```

---

## Task 5: Sync writer maps `provider_category` for new and updated transactions

**Files:**
- Modify: `apps/banking/services.py:86-102` (transaction upsert in `sync_institution`)
- Modify: `apps/banking/tests/test_services.py` (extend `_FakeProvider` and add tests)

- [ ] **Step 1: Write the failing tests**

Append to `apps/banking/tests/test_services.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web pytest apps/banking/tests/test_services.py::test_new_transaction_from_teller_like_provider_gets_mapped_category -v`
Expected: FAIL — categories are still default `"uncategorized"`.

- [ ] **Step 3: Modify the sync writer**

In `apps/banking/services.py`, add this import at the top alongside the existing imports:

```python
from .categories import map_teller_category
```

Then replace the transaction upsert block (lines 86-102 — the `for tx in payload.transactions:` loop with `Transaction.objects.update_or_create`) with:

```python
            for tx in payload.transactions:
                mapped_category = map_teller_category(tx.provider_category)
                defaults = {
                    "posted_at": tx.posted_at,
                    "amount": tx.amount,
                    "description": tx.description,
                    "payee": tx.payee,
                    "memo": tx.memo,
                    "pending": tx.pending,
                }
                existing_tx = Transaction.objects.filter(
                    account=acc, external_id=tx.external_id,
                ).first()
                if existing_tx is None:
                    Transaction.objects.create(
                        account=acc, external_id=tx.external_id,
                        category=mapped_category,
                        category_manual=False,
                        **defaults,
                    )
                    transactions_created += 1
                else:
                    for field, value in defaults.items():
                        setattr(existing_tx, field, value)
                    # Only re-apply mapped category if user has not overridden it.
                    if not existing_tx.category_manual:
                        existing_tx.category = mapped_category
                    existing_tx.save()
                    transactions_updated += 1
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose exec web pytest apps/banking/tests/test_services.py -q`
Expected: PASS (all existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add apps/banking/services.py apps/banking/tests/test_services.py
git commit -m "feat(banking): apply Teller category mapping during sync"
```

---

## Task 6: Sync writer respects `category_manual` on update

**Files:**
- Test: `apps/banking/tests/test_services.py` (extend)

The implementation from Task 5 already includes the override-check. This task adds the regression test to lock that behavior in.

- [ ] **Step 1: Write the test**

Append to `apps/banking/tests/test_services.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `docker compose exec web pytest apps/banking/tests/test_services.py -q`
Expected: PASS — implementation from Task 5 already handles both cases.

- [ ] **Step 3: Commit**

```bash
git add apps/banking/tests/test_services.py
git commit -m "test(banking): regression tests for category override on re-sync"
```

---

## Task 7: `spending_breakdown` aggregation service

**Files:**
- Modify: `apps/banking/services.py` (append)
- Test: `apps/banking/tests/test_services.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `apps/banking/tests/test_services.py`:

```python
from datetime import date, timedelta
from apps.banking.services import spending_breakdown


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest apps/banking/tests/test_services.py -k spending_breakdown -v`
Expected: FAIL — `spending_breakdown` not defined.

- [ ] **Step 3: Implement the service**

Append to `apps/banking/services.py`:

```python
from dataclasses import dataclass as _dc
from datetime import date as _date
from decimal import Decimal as _Decimal

from .categories import (
    CATEGORY_COLORS, CATEGORY_LABELS, INCOME_CATEGORIES, SPENDING_CATEGORIES,
    TRANSFER_CATEGORIES, UNCATEGORIZED,
)


@_dc(frozen=True)
class CategoryTotal:
    category: str
    label: str
    color: str
    total: _Decimal       # absolute value of money flowing out, always >= 0
    percent: float        # share of total spending


def _date_to_aware_range(start: _date, end: _date):
    """Convert (start, end) dates to a [start_dt, end_dt) datetime range covering both endpoints inclusive."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    start_dt = _dt.combine(start, _dt.min.time(), tzinfo=_tz.utc)
    end_dt = _dt.combine(end + _td(days=1), _dt.min.time(), tzinfo=_tz.utc)
    return start_dt, end_dt


def spending_breakdown(user, start: _date, end: _date) -> list[CategoryTotal]:
    """Per-category spending totals for the inclusive [start, end] date range.
    Excludes income and transfer. Includes 'uncategorized' as a slice (muted).
    Sorted descending by total. Uses Transaction.display_amount to respect
    credit/loan sign-flipping."""
    start_dt, end_dt = _date_to_aware_range(start, end)
    qs = (
        Transaction.objects.for_user(user)
        .filter(posted_at__gte=start_dt, posted_at__lt=end_dt)
        .exclude(category__in=INCOME_CATEGORIES + TRANSFER_CATEGORIES)
        .select_related("account")
    )

    totals: dict[str, _Decimal] = {}
    for tx in qs:
        amt = tx.display_amount
        if amt >= 0:
            continue  # not a spend (e.g., refund) — exclude from breakdown
        totals[tx.category] = totals.get(tx.category, _Decimal("0")) + (-amt)

    grand = sum(totals.values(), _Decimal("0"))
    rows = [
        CategoryTotal(
            category=cat,
            label=CATEGORY_LABELS[cat],
            color=CATEGORY_COLORS[cat],
            total=total,
            percent=float(total / grand * 100) if grand > 0 else 0.0,
        )
        for cat, total in totals.items()
    ]
    rows.sort(key=lambda r: r.total, reverse=True)
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest apps/banking/tests/test_services.py -k spending_breakdown -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/banking/services.py apps/banking/tests/test_services.py
git commit -m "feat(banking): spending_breakdown aggregation service"
```

---

## Task 8: `income_expense_summary` aggregation service

**Files:**
- Modify: `apps/banking/services.py` (append)
- Test: `apps/banking/tests/test_services.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `apps/banking/tests/test_services.py`:

```python
from apps.banking.services import income_expense_summary


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest apps/banking/tests/test_services.py -k income_expense_summary -v`
Expected: FAIL.

- [ ] **Step 3: Implement the service**

Append to `apps/banking/services.py`:

```python
def income_expense_summary(user, start: _date, end: _date) -> tuple[_Decimal, _Decimal]:
    """Return (income_total, expense_total) for the inclusive [start, end] range.
    income_total = sum of display_amount where category in INCOME_CATEGORIES.
    expense_total = abs(sum) of display_amount over SPENDING + UNCATEGORIZED rows
    where display_amount < 0. Transfers excluded from both."""
    start_dt, end_dt = _date_to_aware_range(start, end)
    qs = (
        Transaction.objects.for_user(user)
        .filter(posted_at__gte=start_dt, posted_at__lt=end_dt)
        .exclude(category__in=TRANSFER_CATEGORIES)
        .select_related("account")
    )
    income = _Decimal("0")
    expense = _Decimal("0")
    for tx in qs:
        amt = tx.display_amount
        if tx.category in INCOME_CATEGORIES:
            if amt > 0:
                income += amt
        elif amt < 0:
            expense += -amt
    return income, expense
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest apps/banking/tests/test_services.py -k income_expense_summary -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/banking/services.py apps/banking/tests/test_services.py
git commit -m "feat(banking): income_expense_summary aggregation service"
```

---

## Task 9: `set_category` service

**Files:**
- Modify: `apps/banking/services.py` (append)
- Test: `apps/banking/tests/test_services.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `apps/banking/tests/test_services.py`:

```python
from apps.banking.services import set_category


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest apps/banking/tests/test_services.py -k set_category -v`
Expected: FAIL.

- [ ] **Step 3: Implement the service**

Append to `apps/banking/services.py`:

```python
from .categories import ALL_CATEGORIES


def set_category(transaction: "Transaction", category: str) -> "Transaction":
    """Set the category on a transaction and flag it as user-overridden.
    Raises ValueError if `category` is not a valid category key."""
    if category not in ALL_CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    transaction.category = category
    transaction.category_manual = True
    transaction.save(update_fields=["category", "category_manual"])
    return transaction
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest apps/banking/tests/test_services.py -k set_category -v`
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add apps/banking/services.py apps/banking/tests/test_services.py
git commit -m "feat(banking): set_category service flags manual override"
```

---

## Task 10: Pie SVG template tag

**Files:**
- Create: `apps/banking/templatetags/__init__.py` (if not present)
- Create: `apps/banking/templatetags/category_tags.py`
- Test: `apps/banking/tests/test_category_tags.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `apps/banking/tests/test_category_tags.py`:

```python
from decimal import Decimal

from apps.banking.services import CategoryTotal
from apps.banking.templatetags.category_tags import category_pie_svg, category_pill_html


def _row(cat, total, color="#888"):
    return CategoryTotal(category=cat, label=cat.title(), color=color,
                         total=Decimal(str(total)), percent=0.0)


def test_pie_svg_with_single_slice_returns_full_circle():
    rows = [_row("groceries", 100, "#7a9a6a")]
    svg = category_pie_svg(rows, size=160)
    assert svg.startswith("<svg")
    assert "fill=\"#7a9a6a\"" in svg
    assert 'width="160"' in svg


def test_pie_svg_with_no_rows_returns_dash():
    assert category_pie_svg([], size=160) == "—"


def test_pie_svg_with_multiple_slices_renders_each_color():
    rows = [_row("a", 50, "#aaaaaa"), _row("b", 50, "#bbbbbb")]
    svg = category_pie_svg(rows, size=120)
    assert "#aaaaaa" in svg
    assert "#bbbbbb" in svg


def test_category_pill_html_uses_color_and_label():
    html = category_pill_html("groceries")
    assert "Groceries" in html
    assert "#7a9a6a" in html or "rgb" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest apps/banking/tests/test_category_tags.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the template tag**

Create `apps/banking/templatetags/__init__.py` (empty file) if it doesn't exist.

Create `apps/banking/templatetags/category_tags.py`:

```python
import math
from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

from apps.banking.categories import CATEGORY_COLORS, CATEGORY_LABELS

register = template.Library()


def category_pie_svg(rows, size: int = 160) -> str:
    """Render an SVG donut/pie from a list of CategoryTotal rows.
    Returns '—' for empty input."""
    if not rows:
        return "—"

    total = sum((r.total for r in rows), Decimal("0"))
    if total <= 0:
        return "—"

    cx = cy = size / 2
    r = size / 2 - 2

    if len(rows) == 1:
        only = rows[0]
        return mark_safe(
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{only.color}"/>'
            f'</svg>'
        )

    parts = [
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    ]
    angle = -math.pi / 2  # start at 12 o'clock
    for row in rows:
        slice_angle = float(row.total / total) * 2 * math.pi
        x1 = cx + r * math.cos(angle)
        y1 = cy + r * math.sin(angle)
        end_angle = angle + slice_angle
        x2 = cx + r * math.cos(end_angle)
        y2 = cy + r * math.sin(end_angle)
        large_arc = 1 if slice_angle > math.pi else 0
        d = f"M {cx} {cy} L {x1:.3f} {y1:.3f} A {r} {r} 0 {large_arc} 1 {x2:.3f} {y2:.3f} Z"
        parts.append(f'<path d="{d}" fill="{row.color}"/>')
        angle = end_angle
    parts.append('</svg>')
    return mark_safe("".join(parts))


def category_pill_html(category: str) -> str:
    """Render a colored pill for a category key."""
    color = CATEGORY_COLORS.get(category, "#888888")
    label = CATEGORY_LABELS.get(category, category.title())
    return mark_safe(
        f'<span class="category-pill" style="background-color: {color}22; color: {color}; '
        f'padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500;">'
        f'{label}</span>'
    )


@register.simple_tag
def category_pie(rows, size=160):
    return category_pie_svg(rows, size=int(size))


@register.simple_tag
def category_pill(category):
    return category_pill_html(category)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest apps/banking/tests/test_category_tags.py -v`
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add apps/banking/templatetags/ apps/banking/tests/test_category_tags.py
git commit -m "feat(banking): category_pie and category_pill template tags"
```

---

## Task 11: `/spending/` page view, URL, and template

**Files:**
- Modify: `apps/banking/views.py` (add view; add helper for time-window parsing)
- Modify: `apps/banking/urls.py`
- Create: `apps/banking/templates/banking/spending.html`
- Test: `apps/banking/tests/test_views.py` (new file if not present, otherwise extend)

- [ ] **Step 1: Write the failing test**

Create or extend `apps/banking/tests/test_views.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.banking.models import Account, Institution, Transaction

User = get_user_model()


@pytest.mark.django_db
def test_spending_page_requires_login(client):
    response = client.get(reverse("spending"))
    assert response.status_code == 302  # redirected to login


@pytest.mark.django_db
def test_spending_page_renders_for_authenticated_user(client):
    user = User.objects.create_user(username="alice", password="x")
    client.force_login(user)
    response = client.get(reverse("spending"))
    assert response.status_code == 200
    assert b"Spending" in response.content


@pytest.mark.django_db
def test_spending_page_aggregates_correctly(client):
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="A",
    )
    Transaction.objects.create(
        account=acc, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-100"), external_id="t1", category="groceries",
    )
    client.force_login(user)
    response = client.get(reverse("spending"))
    assert response.status_code == 200
    assert b"Groceries" in response.content
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web pytest apps/banking/tests/test_views.py -v`
Expected: FAIL — `reverse('spending')` raises NoReverseMatch.

- [ ] **Step 3: Add the view**

In `apps/banking/views.py`, near the top imports, add:

```python
from datetime import date, timedelta

from .services import income_expense_summary, spending_breakdown
```

Add at the bottom of `apps/banking/views.py`:

```python
def _spending_window(period: str) -> tuple[date, date, str]:
    """Parse the ?period= query value into (start, end, label).
    Defaults to current month."""
    today = date.today()
    if period == "30d":
        return today - timedelta(days=29), today, "Last 30 days"
    if period == "ytd":
        return date(today.year, 1, 1), today, f"{today.year} YTD"
    # default: current calendar month
    start = date(today.year, today.month, 1)
    return start, today, today.strftime("%B %Y")


@login_required
def spending(request):
    period = request.GET.get("period", "month")
    start, end, label = _spending_window(period)
    breakdown = spending_breakdown(request.user, start, end)
    income_total, expense_total = income_expense_summary(request.user, start, end)
    return render(request, "banking/spending.html", {
        "rows": breakdown,
        "income_total": income_total,
        "expense_total": expense_total,
        "net": income_total - expense_total,
        "period": period,
        "period_label": label,
    })
```

- [ ] **Step 4: Register the URL**

The `transactions` route lives in `apps/accounts/urls.py:14` (top-level, no namespace). Add `/spending/` next to it.

Open `apps/accounts/urls.py` and add this line after the `transactions/` route (line 14):

```python
    path("spending/", banking_views.spending, name="spending"),
```

`from apps.banking import views as banking_views` is already imported at the top of that file.

- [ ] **Step 5: Create the template**

Create `apps/banking/templates/banking/spending.html`:

```django
{% extends "base.html" %}
{% load money %}
{% load category_tags %}
{% block title %}Spending{% endblock %}
{% block content %}

<div class="flex items-end justify-between mb-6 flex-wrap gap-3">
  <h1 class="text-2xl font-bold">Spending</h1>
  <div class="inline-flex rounded border overflow-hidden text-sm" style="border-color: var(--border);">
    <a href="?period=30d" class="px-3 py-1.5 {% if period == '30d' %}font-bold{% endif %}"
       style="{% if period == '30d' %}background: var(--tint-positive); color: var(--accent-positive);{% else %}color: var(--muted);{% endif %}">30d</a>
    <a href="?period=month" class="px-3 py-1.5 {% if period == 'month' or not period %}font-bold{% endif %}"
       style="{% if period == 'month' or not period %}background: var(--tint-positive); color: var(--accent-positive);{% else %}color: var(--muted);{% endif %}">Month</a>
    <a href="?period=ytd" class="px-3 py-1.5 {% if period == 'ytd' %}font-bold{% endif %}"
       style="{% if period == 'ytd' %}background: var(--tint-positive); color: var(--accent-positive);{% else %}color: var(--muted);{% endif %}">YTD</a>
  </div>
</div>

<div class="text-xs mb-4" style="color: var(--muted);">{{ period_label }}</div>

<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
  <div class="rounded border p-4" style="background: var(--surface); border-color: var(--border);">
    <div class="text-[10px] uppercase tracking-widest mb-3" style="color: var(--dim);">By category</div>
    <div class="flex justify-center">{% category_pie rows 200 %}</div>
  </div>

  <div class="rounded border p-4" style="background: var(--surface); border-color: var(--border);">
    <div class="text-[10px] uppercase tracking-widest mb-3" style="color: var(--dim);">Income vs Expense</div>
    {% if income_total or expense_total %}
      {% with total=income_total|add:expense_total %}
      <div class="flex h-7 rounded overflow-hidden text-xs">
        {% if income_total %}<div style="background: var(--accent-positive); color: var(--bg); width: {% widthratio income_total total 100 %}%; padding: 4px 8px; display: flex; align-items: center;">+{{ income_total|money }}</div>{% endif %}
        {% if expense_total %}<div style="background: var(--accent-negative); color: var(--bg); width: {% widthratio expense_total total 100 %}%; padding: 4px 8px; display: flex; align-items: center;">−{{ expense_total|money }}</div>{% endif %}
      </div>
      {% endwith %}
      <div class="text-xs mt-2" style="color: var(--muted);">
        Net: <span class="num font-semibold" style="color: {% if net < 0 %}var(--accent-negative){% else %}var(--accent-positive){% endif %};">{{ net|money:"signed" }}</span>
        · Transfers excluded
      </div>
    {% else %}
      <div class="text-sm" style="color: var(--muted);">No data in range.</div>
    {% endif %}
  </div>
</div>

<div class="rounded border overflow-hidden" style="background: var(--surface); border-color: var(--border);">
  <div class="px-4 py-2 text-[10px] uppercase tracking-widest" style="color: var(--dim); border-bottom: 1px solid var(--border);">Categories</div>
  {% for row in rows %}
  <a href="{% url 'transactions' %}?category={{ row.category }}" class="flex items-center justify-between px-4 py-2 text-sm" style="border-top: {% if not forloop.first %}1px solid var(--border){% endif %};">
    <span>{% category_pill row.category %}</span>
    <span class="num font-semibold">{{ row.total|money }}</span>
  </a>
  {% empty %}
  <div class="px-4 py-6 text-sm" style="color: var(--muted);">No spending in range.</div>
  {% endfor %}
</div>

{% endblock %}
```

- [ ] **Step 6: Run tests**

Run: `docker compose exec web pytest apps/banking/tests/test_views.py -v`
Expected: PASS (3).

- [ ] **Step 7: Commit**

```bash
git add apps/banking/views.py apps/accounts/urls.py apps/banking/templates/banking/spending.html apps/banking/tests/test_views.py
git commit -m "feat(banking): /spending/ page with pie + income/expense bar"
```

---

## Task 12: Transactions list — filter by category

**Files:**
- Modify: `apps/banking/views.py:243` (`transactions_list` view)
- Modify: `apps/banking/templates/banking/transactions_list.html`

- [ ] **Step 1: Write the failing test**

Append to `apps/banking/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_transactions_list_filters_by_category(client):
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="A",
    )
    Transaction.objects.create(
        account=acc, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-50"), external_id="t1",
        category="groceries", payee="Whole Foods",
    )
    Transaction.objects.create(
        account=acc, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-30"), external_id="t2",
        category="dining", payee="Sushi Place",
    )

    client.force_login(user)
    response = client.get(reverse("transactions") + "?category=groceries")
    assert response.status_code == 200
    assert b"Whole Foods" in response.content
    assert b"Sushi Place" not in response.content
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web pytest apps/banking/tests/test_views.py::test_transactions_list_filters_by_category -v`
Expected: FAIL — both transactions visible.

- [ ] **Step 3: Modify the `transactions_list` view**

In `apps/banking/views.py`, add these imports at the top with the others:

```python
from django.db.models import Count

from .categories import (
    CATEGORY_LABELS, INCOME_CATEGORIES, SPENDING_CATEGORIES, TRANSFER_CATEGORIES,
    UNCATEGORIZED,
)
```

Inside `transactions_list` (line 243), after the `search` filter block (around line 274) and before `paginator = Paginator(qs, 50)`, insert:

```python
    selected_category = (request.GET.get("category") or "").strip()
    if selected_category:
        qs = qs.filter(category=selected_category)

    # Top 5 spending categories by transaction count for this user (for filter pills).
    top_categories = list(
        Transaction.objects.for_user(request.user)
        .filter(category__in=SPENDING_CATEGORIES)
        .values("category")
        .annotate(n=Count("id"))
        .order_by("-n")
        .values_list("category", flat=True)[:5]
    )
    if not top_categories:
        top_categories = ["groceries", "dining", "transportation", "utilities", "shopping"]

    other_categories = [
        c for c in (SPENDING_CATEGORIES + INCOME_CATEGORIES + TRANSFER_CATEGORIES + [UNCATEGORIZED])
        if c not in top_categories
    ]
```

Add `category` to the `qs_params` dict (around line 282, alongside the existing `account`, `range`, `q` keys):

```python
    if selected_category:
        qs_params["category"] = selected_category
```

In the final `render(...)` call (around line 291), add to the context dict:

```python
        "selected_category": selected_category,
        "top_categories": top_categories,
        "other_categories": other_categories,
        "category_labels": CATEGORY_LABELS,
```

- [ ] **Step 4: Update the template's filter bar**

In `apps/banking/templates/banking/transactions_list.html`, after the existing filter `<form>` block (closing `</form>` around line 36), add:

```django
<div class="mb-4 flex flex-wrap gap-2 items-center text-xs">
  <span style="color: var(--muted);">Category:</span>
  <a href="?" class="px-2.5 py-1 rounded {% if not selected_category %}font-bold{% endif %}"
     style="{% if not selected_category %}background: var(--tint-positive); color: var(--accent-positive);{% else %}border: 1px solid var(--border); color: var(--muted);{% endif %}">All</a>
  {% for c in top_categories %}
  <a href="?category={{ c }}" class="px-2.5 py-1 rounded {% if selected_category == c %}font-bold{% endif %}"
     style="{% if selected_category == c %}background: var(--tint-positive); color: var(--accent-positive);{% else %}border: 1px solid var(--border); color: var(--muted);{% endif %}">{{ c|capfirst }}</a>
  {% endfor %}
  {% if other_categories %}
  <details class="relative">
    <summary class="cursor-pointer px-2.5 py-1 rounded list-none" style="border: 1px solid var(--border); color: var(--muted);">More ▾</summary>
    <div class="absolute z-10 mt-1 rounded border p-2 flex flex-col gap-1 text-sm" style="background: var(--surface); border-color: var(--border); min-width: 160px;">
      {% for c in other_categories %}
      <a href="?category={{ c }}" class="hover:underline" style="color: var(--muted);">{{ c|capfirst }}</a>
      {% endfor %}
    </div>
  </details>
  {% endif %}
</div>
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `docker compose exec web pytest apps/banking/tests/test_views.py::test_transactions_list_filters_by_category -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/banking/views.py apps/banking/templates/banking/transactions_list.html
git commit -m "feat(banking): category filter pills on transactions list"
```

---

## Task 13: Transactions list — render pill on each row

**Files:**
- Modify: `apps/banking/templates/banking/transactions_list.html`

- [ ] **Step 1: Add pill to desktop table**

In `apps/banking/templates/banking/transactions_list.html`:

In the desktop table `<thead>`, add a new column header before the Amount column:

```django
<th class="px-4 py-2 text-left w-32">Category</th>
```

In each `<tr>` row, add a corresponding `<td>` before the Amount cell:

```django
<td class="px-4 py-2">{% category_pill tx.category %}</td>
```

In the mobile card markup (the `<div class="md:hidden">` block), add a category pill to each card next to the date:

```django
<div class="text-xs mt-1">{% category_pill tx.category %}</div>
```

At the top of the file, add `{% load category_tags %}` after the existing `{% load money %}`.

- [ ] **Step 2: Run existing transactions tests to verify nothing broke**

Run: `docker compose exec web pytest apps/banking/tests/ -q -k transactions`
Expected: all pass.

- [ ] **Step 3: Visual smoke check (manual)**

```
docker compose exec web python manage.py runserver 0.0.0.0:8000
```

Then in a browser hit `/transactions/` and confirm pills appear on each row.

- [ ] **Step 4: Commit**

```bash
git add apps/banking/templates/banking/transactions_list.html
git commit -m "feat(banking): show category pill on transactions list rows"
```

---

## Task 14: Inline category picker — endpoint + UI

**Files:**
- Modify: `apps/banking/views.py` — add `set_category` view
- Modify: `apps/banking/urls.py` — register the route
- Modify: `apps/banking/templates/banking/transactions_list.html` — add picker JS + popup
- Test: `apps/banking/tests/test_views.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `apps/banking/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_set_category_endpoint_requires_login(client):
    inst = Institution.objects.create(
        user=User.objects.create_user(username="bob", password="x"),
        name="B", access_url="https://x",
    )
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-1"), external_id="t1",
    )
    response = client.post(
        reverse("banking:set_category", args=[tx.id]),
        {"category": "personal"},
    )
    assert response.status_code == 302  # redirect to login


@pytest.mark.django_db
def test_set_category_endpoint_sets_manual(client):
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime.now(timezone.utc),
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
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(user=user, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime.now(timezone.utc),
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
    alice = User.objects.create_user(username="alice", password="x")
    bob = User.objects.create_user(username="bob", password="x")
    inst = Institution.objects.create(user=bob, name="B", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="A", type="checking",
        balance=Decimal("0"), external_id="A")
    bob_tx = Transaction.objects.create(
        account=acc, posted_at=datetime.now(timezone.utc),
        amount=Decimal("-1"), external_id="t1",
    )
    client.force_login(alice)
    response = client.post(
        reverse("banking:set_category", args=[bob_tx.id]),
        {"category": "personal"},
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec web pytest apps/banking/tests/test_views.py -k set_category -v`
Expected: FAIL — `banking:set_category` URL doesn't exist.

- [ ] **Step 3: Add the view**

In `apps/banking/views.py`, add:

```python
from django.http import HttpResponseBadRequest
from .services import set_category as set_category_service


@login_required
@require_http_methods(["POST"])
def set_category(request, transaction_id):
    tx = get_object_or_404(
        Transaction.objects.for_user(request.user), pk=transaction_id,
    )
    category = request.POST.get("category", "").strip()
    try:
        set_category_service(tx, category)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    # Return the updated pill HTML so the client can swap it in place.
    from .templatetags.category_tags import category_pill_html
    return HttpResponse(category_pill_html(tx.category))
```

(Add `from django.http import HttpResponse` to the existing imports if not present.)

- [ ] **Step 4: Register the URL**

Add to `apps/banking/urls.py` (inside `urlpatterns`):

```python
path("transactions/<int:transaction_id>/set-category/", views.set_category, name="set_category"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec web pytest apps/banking/tests/test_views.py -k set_category -v`
Expected: PASS (4).

- [ ] **Step 6: Add the picker UI**

In `apps/banking/templates/banking/transactions_list.html`, wrap each pill in a clickable element with the transaction id, and add a popup template + JS at the bottom of the file (before `{% endblock %}`):

```django
{# wrap pills in trigger spans #}
{# Replace `{% category_pill tx.category %}` with: #}
<span class="category-trigger cursor-pointer" data-tx-id="{{ tx.id }}">{% category_pill tx.category %}</span>
```

Then at the end of the template (before `{% endblock %}`):

```html
<div id="cat-popup" class="hidden fixed bg-[var(--surface)] border rounded p-2 shadow-lg z-50" style="border-color: var(--border);">
  <div id="cat-popup-grid" class="grid grid-cols-2 gap-1 text-sm"></div>
</div>

<script>
(function() {
  const SPENDING = ["groceries","dining","transportation","utilities","bills","housing","health","entertainment","shopping","software","travel","personal","charity","other"];
  const popup = document.getElementById("cat-popup");
  const grid = document.getElementById("cat-popup-grid");
  let activeTrigger = null;

  function getCookie(name) {
    const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return m ? m[2] : null;
  }

  function openPopup(trigger) {
    activeTrigger = trigger;
    grid.innerHTML = "";
    SPENDING.forEach(cat => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "px-3 py-1.5 rounded hover:bg-[var(--tint-positive)] text-left";
      item.textContent = cat.charAt(0).toUpperCase() + cat.slice(1);
      item.addEventListener("click", () => assignCategory(cat));
      grid.appendChild(item);
    });
    const rect = trigger.getBoundingClientRect();
    popup.style.left = rect.left + "px";
    popup.style.top = (rect.bottom + 4) + "px";
    popup.classList.remove("hidden");
  }

  function closePopup() {
    popup.classList.add("hidden");
    activeTrigger = null;
  }

  async function assignCategory(category) {
    if (!activeTrigger) return;
    const txId = activeTrigger.dataset.txId;
    const csrf = getCookie("csrftoken");
    const fd = new FormData();
    fd.append("category", category);
    const resp = await fetch("/banking/transactions/" + txId + "/set-category/", {
      method: "POST", body: fd, headers: { "X-CSRFToken": csrf },
    });
    if (resp.ok) {
      const html = await resp.text();
      activeTrigger.innerHTML = html;
    }
    closePopup();
  }

  document.querySelectorAll(".category-trigger").forEach(el => {
    el.addEventListener("click", e => {
      e.stopPropagation();
      openPopup(el);
    });
  });
  document.addEventListener("click", e => {
    if (!popup.contains(e.target)) closePopup();
  });
})();
</script>
```

- [ ] **Step 7: Visual smoke check (manual)**

Hit `/transactions/`, click a pill, pick a category, watch it update without page reload.

- [ ] **Step 8: Commit**

```bash
git add apps/banking/views.py apps/banking/urls.py apps/banking/templates/banking/transactions_list.html apps/banking/tests/test_views.py
git commit -m "feat(banking): inline category picker on transactions list"
```

---

## Task 15: Dashboard widget — 30-day spending breakdown

**Files:**
- Modify: `apps/dashboard/views.py`
- Modify: `apps/dashboard/templates/dashboard/index.html`

- [ ] **Step 1: Add data to the dashboard view**

In `apps/dashboard/views.py`, replace the dashboard view body:

```python
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.banking.services import spending_breakdown

from .services import net_worth_history, net_worth_summary


@login_required
def dashboard(request):
    summary = net_worth_summary(request.user)
    history = net_worth_history(request.user, days=30)

    today = date.today()
    spending_rows = spending_breakdown(request.user, today - timedelta(days=29), today)

    return render(request, "dashboard/index.html", {
        "summary": summary,
        "history": history,
        "spending_rows": spending_rows[:5],   # top 4 + uncategorized at most, in render
        "spending_total": sum((r.total for r in spending_rows), __import__("decimal").Decimal("0")),
    })
```

- [ ] **Step 2: Add the widget to the template**

In `apps/dashboard/templates/dashboard/index.html`, before the "Latest transactions" header (around line 48), add:

```django
{% load category_tags %}

{% if spending_rows %}
<div class="rounded border p-4 mb-6" style="background: var(--surface); border-color: var(--border);">
  <div class="flex items-center justify-between mb-3">
    <div class="text-[10px] uppercase tracking-widest" style="color: var(--dim);">Spending · last 30 days</div>
    <a href="{% url 'spending' %}" class="text-xs" style="color: var(--accent-positive);">View all →</a>
  </div>
  <div class="flex items-center gap-4">
    <div>{% category_pie spending_rows 100 %}</div>
    <div class="flex-1 text-sm space-y-1">
      {% for row in spending_rows %}
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 min-w-0">
          <span style="display: inline-block; width: 8px; height: 8px; background: {{ row.color }}; border-radius: 1px; flex-shrink: 0;"></span>
          <span class="truncate">{{ row.label }}</span>
        </div>
        <span class="num font-semibold whitespace-nowrap">{{ row.total|money }}</span>
      </div>
      {% endfor %}
    </div>
  </div>
</div>
{% endif %}
```

If `{% load category_tags %}` is already in the file, do not duplicate it.

- [ ] **Step 3: Run the existing dashboard tests**

Run: `docker compose exec web pytest apps/dashboard/ -q`
Expected: PASS — no test for the widget yet (visual surface), but no regressions.

- [ ] **Step 4: Visual smoke check**

Hit `/` (dashboard), confirm the widget renders between net worth and recent transactions.

- [ ] **Step 5: Commit**

```bash
git add apps/dashboard/views.py apps/dashboard/templates/dashboard/index.html
git commit -m "feat(dashboard): 30-day spending breakdown widget"
```

---

## Task 16: Backfill management command

**Files:**
- Create: `apps/banking/management/commands/categorize_existing_teller.py`
- Test: `apps/banking/tests/test_categorize_command.py` (new)

- [ ] **Step 1: Write the failing test**

Create `apps/banking/tests/test_categorize_command.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.banking.models import Account, Institution, Transaction
from apps.providers import registry as registry_module
from apps.providers.base import AccountData, AccountSyncPayload, TransactionData

User = get_user_model()


class _BackfillProvider:
    name = "teller"

    def exchange_setup_token(self, t):
        return t

    def fetch_accounts_with_transactions(self, access_url, *, since=None):
        yield AccountSyncPayload(
            account=AccountData(
                external_id="ACC-1", name="Chk", type="checking",
                balance=Decimal("0"), currency="USD", org_name="Bank",
            ),
            transactions=(
                TransactionData(
                    external_id="T-NEW",
                    posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    amount=Decimal("-12"), description="Food", payee="Food",
                    memo="", pending=False, provider_category="dining",
                ),
            ),
        )

    def fetch_investment_accounts(self, access_url):
        return iter(())


@pytest.fixture
def _register_teller():
    original = registry_module._REGISTRY.copy()
    registry_module._REGISTRY["teller"] = _BackfillProvider
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(original)


@pytest.mark.django_db
def test_backfill_updates_teller_transactions(_register_teller):
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(
        user=user, name="My Bank", provider="teller", access_url="tok",
    )
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="ACC-1",
    )
    # Pre-existing row with category=uncategorized.
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-12"), external_id="T-NEW",
        description="Food", payee="Food", category="uncategorized",
    )

    out = StringIO()
    call_command("categorize_existing_teller", stdout=out)

    tx.refresh_from_db()
    assert tx.category == "dining"
    assert tx.category_manual is False


@pytest.mark.django_db
def test_backfill_skips_manually_overridden(_register_teller):
    user = User.objects.create_user(username="alice", password="x")
    inst = Institution.objects.create(
        user=user, name="My Bank", provider="teller", access_url="tok",
    )
    acc = Account.objects.create(
        institution=inst, name="Chk", type="checking",
        balance=Decimal("0"), external_id="ACC-1",
    )
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-12"), external_id="T-NEW",
        category="personal", category_manual=True,
    )

    call_command("categorize_existing_teller", stdout=StringIO())

    tx.refresh_from_db()
    assert tx.category == "personal"
    assert tx.category_manual is True


@pytest.mark.django_db
def test_backfill_does_not_touch_simplefin_transactions(_register_teller):
    user = User.objects.create_user(username="alice", password="x")
    sf_inst = Institution.objects.create(
        user=user, name="SF", provider="simplefin", access_url="https://x",
    )
    acc = Account.objects.create(
        institution=sf_inst, name="Sf", type="checking",
        balance=Decimal("0"), external_id="SF-1",
    )
    tx = Transaction.objects.create(
        account=acc, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-12"), external_id="SF-T1",
        category="uncategorized",
    )

    call_command("categorize_existing_teller", stdout=StringIO())

    tx.refresh_from_db()
    assert tx.category == "uncategorized"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest apps/banking/tests/test_categorize_command.py -v`
Expected: FAIL — command doesn't exist.

- [ ] **Step 3: Implement the command**

Create `apps/banking/management/commands/categorize_existing_teller.py`:

```python
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction

from apps.banking.categories import map_teller_category
from apps.banking.models import Institution, Transaction
from apps.providers.registry import get as get_provider


class Command(BaseCommand):
    help = "Backfill category on existing Teller-sourced transactions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user", help="Limit to one user (username). Defaults to all users.",
        )

    def handle(self, *args, **options):
        username = options.get("user")
        institutions = Institution.objects.filter(provider="teller")
        if username:
            institutions = institutions.filter(user__username=username)

        teller = get_provider("teller")
        updated_total = skipped_total = 0

        for inst in institutions:
            self.stdout.write(f"Processing institution: {inst.effective_name} ({inst.user.username})")
            account_external_ids = {
                a.external_id: a.id for a in inst.accounts.all()
            }
            tx_index: dict[tuple[int, str], Transaction] = {}
            for tx in Transaction.objects.filter(
                account__institution=inst,
            ).only("id", "account_id", "external_id", "category_manual", "category"):
                tx_index[(tx.account_id, tx.external_id)] = tx

            updated = skipped = 0

            with db_transaction.atomic():
                for payload in teller.fetch_accounts_with_transactions(inst.access_url, since=None):
                    acc_id = account_external_ids.get(payload.account.external_id)
                    if acc_id is None:
                        continue
                    for tx_data in payload.transactions:
                        existing = tx_index.get((acc_id, tx_data.external_id))
                        if existing is None:
                            continue
                        if existing.category_manual:
                            skipped += 1
                            continue
                        new_category = map_teller_category(tx_data.provider_category)
                        if existing.category != new_category:
                            existing.category = new_category
                            existing.save(update_fields=["category"])
                        updated += 1

            self.stdout.write(f"  Updated: {updated}, skipped (manual): {skipped}")
            updated_total += updated
            skipped_total += skipped

        self.stdout.write(self.style.SUCCESS(
            f"Done. {updated_total} updated, {skipped_total} skipped across all Teller institutions.",
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec web pytest apps/banking/tests/test_categorize_command.py -v`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add apps/banking/management/commands/categorize_existing_teller.py apps/banking/tests/test_categorize_command.py
git commit -m "feat(banking): categorize_existing_teller backfill command"
```

---

## Task 17: Final integration check

- [ ] **Step 1: Run the full test suite**

Run: `docker compose exec web pytest -q`
Expected: all green.

- [ ] **Step 2: Hit each surface in the browser**

Run: `docker compose exec web python manage.py runserver 0.0.0.0:8000`

- `/` — dashboard widget renders, top categories visible
- `/spending/` — pie + income/expense bar + category list, period toggle works
- `/transactions/` — pills on each row, filter pills at top, "More ▾" works, click pill → popup → assign → swap
- `/transactions/?category=groceries` — filtered list

- [ ] **Step 3: Run the backfill command in dry-fashion**

```
docker compose exec web python manage.py categorize_existing_teller
```

Expected: prints per-institution counts, no errors.

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feature/categories
```

Open a PR; review; merge to master per the deployment steps in the spec.
