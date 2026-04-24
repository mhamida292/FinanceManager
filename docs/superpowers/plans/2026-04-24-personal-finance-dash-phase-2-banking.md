# Personal Finance Dashboard — Phase 2: Banking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** User can paste a SimpleFIN setup token, the app exchanges it for an Access URL, stores it encrypted, fetches accounts + transactions, and renders them on `/banks/`. Full per-user data isolation — user A's bank rows are invisible to user B.

**Architecture:** Two new Django apps — `apps/banking/` for domain models (Institution, Account, Transaction) and `apps/providers/` for the pluggable SimpleFIN integration. A custom `EncryptedTextField` for at-rest encryption of the access URL. A `for_user()` QuerySet manager on every user-scoped model, enforced by a dedicated isolation test. Sync is synchronous for v2 — Django Q2 and scheduling ship in Phase 5.

**Tech Stack:** Adds `cryptography` (Fernet) and `requests` to `requirements.txt`. Everything else same as Phase 1 (Django 5, Postgres 16).

**Non-Goals for Phase 2:**
- Django Q2 / background jobs / daily cron — Phase 5.
- `SyncJob` model — Phase 5. In this phase, sync errors surface inline as request errors; failures aren't persisted.
- Investments (Phase 3), assets (Phase 4), dashboard aggregation (Phase 5).
- Transaction categorization, recategorization, tagging, search. Transactions display as SimpleFIN returns them, ordered by date desc.
- Pagination. V2 loads latest 500 transactions per account — enough for a few months. Real pagination lands later.
- CSV import.
- Mobile / responsive polish.

---

## File Structure

```
finance/
├── apps/
│   ├── accounts/              # (unchanged from Phase 1)
│   ├── banking/               # NEW
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── admin.py
│   │   ├── fields.py          # EncryptedTextField
│   │   ├── managers.py        # shared UserScoped QuerySet base
│   │   ├── models.py          # Institution, Account, Transaction
│   │   ├── services.py        # link_institution + sync_institution (orchestration)
│   │   ├── urls.py            # /banks/, /banks/link/, /banks/<id>/, /banks/accounts/<id>/, /banks/<id>/sync/
│   │   ├── views.py           # BanksListView, LinkFormView, AccountDetailView, sync_institution_view
│   │   ├── migrations/
│   │   │   └── __init__.py    # filled by `makemigrations`
│   │   ├── tests/
│   │   │   ├── __init__.py
│   │   │   ├── test_fields.py       # EncryptedTextField roundtrip
│   │   │   ├── test_models.py       # model-level sanity (FK chains, ordering)
│   │   │   ├── test_isolation.py    # the non-skippable multi-tenancy test
│   │   │   ├── test_services.py     # link + sync with faked provider
│   │   │   └── test_views.py        # banks list, link form, account detail
│   │   └── templates/banking/
│   │       ├── banks_list.html
│   │       ├── link_form.html
│   │       └── account_detail.html
│   └── providers/             # NEW
│       ├── __init__.py
│       ├── apps.py
│       ├── base.py            # FinancialProvider Protocol + data dataclasses
│       ├── registry.py        # name → provider class lookup
│       ├── simplefin.py       # SimpleFINClient + SimpleFINProvider
│       └── tests/
│           ├── __init__.py
│           └── test_simplefin.py    # against canned HTTP fixtures
└── config/                    # (unchanged from Phase 1, except adding FIELD_ENCRYPTION_KEY to settings)
```

Boundary rationale:
- `apps/banking/` owns domain models + user-facing views. One responsibility: bank data as the user sees it.
- `apps/providers/` owns wire-level integration. One responsibility: talk to external aggregators and normalize their data into dataclasses the rest of the app consumes.
- `apps/banking/services.py` is the seam — callers in `views.py` call service functions like `link_institution(user, setup_token)` and `sync_institution(institution)`. Services call providers. Providers never touch Django models. This keeps provider code dumb (pure HTTP + parsing) and makes it trivially swappable (Phase 2 only has SimpleFIN; a future Plaid provider drops in here).

---

## Task 1: Add dependencies and `FIELD_ENCRYPTION_KEY` to settings

**Files:**
- Modify: `requirements.txt`
- Modify: `config/settings.py`
- Modify: `.env.example`

- [ ] **Step 1: Append to `requirements.txt`**

```
cryptography==44.0.0
requests==2.32.3
```

- [ ] **Step 2: Read `config/settings.py` then append at the bottom**

```python

# --- Banking / Providers ---
# 32-byte urlsafe-base64 Fernet key. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# This encrypts SimpleFIN access URLs (bank read credentials) at rest.
# ROTATION: changing this key makes every stored access URL unreadable.
# Back it up separately from POSTGRES backups — keys should not live where ciphertext lives.
FIELD_ENCRYPTION_KEY = os.environ["FIELD_ENCRYPTION_KEY"]
```

- [ ] **Step 3: Add to `.env.example`** (after the existing Django block, before Postgres)

```dotenv

# --- Field encryption ---
# 32-byte urlsafe-base64 Fernet key. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEY=changeme
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt config/settings.py .env.example
git commit -m "chore(banking): add cryptography + requests deps and FIELD_ENCRYPTION_KEY"
```

- [ ] **Step 5: Add the key to the user's actual `.env`**

The user's `.env` (gitignored) won't auto-update from the example. Tell the user to run:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

and paste the output into `.env` as `FIELD_ENCRYPTION_KEY=<output>`. Without this, Django will `KeyError` on startup at the new settings line.

- [ ] **Step 6: Rebuild the `web` image so the new deps are installed**

```bash
docker compose build web
docker compose up -d web
docker compose logs web | tail -20
```

Expect a clean boot (no `KeyError` for `FIELD_ENCRYPTION_KEY`, no `ModuleNotFoundError` for `cryptography`). If `KeyError`, the user hasn't added the key to `.env` yet — stop and have them do Step 5.

---

## Task 2: Create `apps/banking/` app skeleton

**Files:**
- Create: `apps/banking/__init__.py`
- Create: `apps/banking/apps.py`
- Modify: `config/settings.py`

- [ ] **Step 1: Create `apps/banking/__init__.py`** — empty.

- [ ] **Step 2: Write `apps/banking/apps.py`**

```python
from django.apps import AppConfig


class BankingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.banking"
    label = "banking"
```

- [ ] **Step 3: Add to `INSTALLED_APPS` in `config/settings.py`**

Find the `INSTALLED_APPS = [...]` block and add `"apps.banking",` after `"apps.accounts",`. Final block:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.banking",
]
```

- [ ] **Step 4: Commit**

```bash
git add apps/banking/ config/settings.py
git commit -m "feat(banking): add banking app skeleton and register it"
```

---

## Task 3: `EncryptedTextField` — custom model field with Fernet

**Files:**
- Create: `apps/banking/fields.py`
- Create: `apps/banking/tests/__init__.py`
- Create: `apps/banking/tests/test_fields.py`

- [ ] **Step 1: Write the failing test `apps/banking/tests/test_fields.py`**

```python
import pytest
from cryptography.fernet import Fernet
from django.db import connection, models

from apps.banking.fields import EncryptedTextField


class _FakeModel(models.Model):
    """Ephemeral model used only for field-level roundtrip testing."""
    secret = EncryptedTextField()

    class Meta:
        app_label = "banking"
        managed = False


def test_encrypted_field_roundtrips_plaintext_via_get_prep_and_from_db():
    field = EncryptedTextField()
    plaintext = "https://bridge.simplefin.org/simplefin/access/SECRETTOKEN"
    ciphertext = field.get_prep_value(plaintext)
    assert ciphertext != plaintext
    assert ciphertext.startswith("gAAAA")  # Fernet token prefix
    # from_db_value should decrypt back
    roundtripped = field.from_db_value(ciphertext, None, connection)
    assert roundtripped == plaintext


def test_encrypted_field_none_roundtrips_as_none():
    field = EncryptedTextField()
    assert field.get_prep_value(None) is None
    assert field.from_db_value(None, None, connection) is None


def test_encrypted_field_different_calls_produce_different_ciphertext():
    """Fernet uses a random IV, so two encryptions of the same plaintext differ."""
    field = EncryptedTextField()
    plaintext = "same input"
    first = field.get_prep_value(plaintext)
    second = field.get_prep_value(plaintext)
    assert first != second
    assert field.from_db_value(first, None, connection) == plaintext
    assert field.from_db_value(second, None, connection) == plaintext
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec web pytest apps/banking/tests/test_fields.py -v
```

Expected: ImportError (no `apps.banking.fields` module yet).

- [ ] **Step 3: Write `apps/banking/fields.py`**

```python
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import models


class EncryptedTextField(models.TextField):
    """Transparently encrypts content at rest using Fernet (symmetric AES-128-CBC + HMAC).

    Reads and writes plaintext in Python; stores base64-encoded Fernet tokens in the DB.
    Loses all content if ``FIELD_ENCRYPTION_KEY`` is rotated — back up the key separately.
    """

    description = "Text field encrypted at rest with Fernet."

    def _get_fernet(self) -> Fernet:
        key = settings.FIELD_ENCRYPTION_KEY
        if isinstance(key, str):
            key = key.encode()
        return Fernet(key)

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return self._get_fernet().decrypt(value.encode()).decode()

    def to_python(self, value):
        if value is None or not isinstance(value, str):
            return value
        # Already-plaintext (e.g. from a form) passes through unchanged.
        return value

    def get_prep_value(self, value):
        if value is None:
            return value
        return self._get_fernet().encrypt(str(value).encode()).decode()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker compose exec web pytest apps/banking/tests/test_fields.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/banking/fields.py apps/banking/tests/__init__.py apps/banking/tests/test_fields.py
git commit -m "feat(banking): add EncryptedTextField with Fernet roundtrip tests"
```

---

## Task 4: Shared `UserScopedQuerySet` base + manager helpers

**Files:**
- Create: `apps/banking/managers.py`

Why factor this out rather than inlining `for_user()` on every model: we have three models in this app that each need the same pattern (Institution has `user` directly; Account/Transaction go through chained FKs). Defining the base in one place + per-model overrides keeps the pattern explicit. Future apps (investments, assets) reuse it.

- [ ] **Step 1: Write `apps/banking/managers.py`**

```python
from django.db import models


class UserScopedQuerySet(models.QuerySet):
    """Base QuerySet for user-owned rows. Subclasses override ``for_user`` to
    filter through whatever FK chain reaches ``User``.

    Views MUST call ``Model.objects.for_user(request.user)`` before returning
    or serializing user data. A non-skippable test per app verifies that two
    users cannot see each other's rows.
    """

    def for_user(self, user):
        raise NotImplementedError(
            f"Subclasses of UserScopedQuerySet must override for_user(). "
            f"Missing on {type(self).__name__}."
        )
```

- [ ] **Step 2: Commit**

```bash
git add apps/banking/managers.py
git commit -m "feat(banking): add UserScopedQuerySet base"
```

---

## Task 5: `Institution` model + migration

**Files:**
- Create: `apps/banking/models.py` (will grow through Tasks 5–7; start with just Institution)
- Create migration via `makemigrations` (generated file)

- [ ] **Step 1: Write `apps/banking/models.py` (Institution only — Account + Transaction land in Tasks 6 and 7)**

```python
from django.conf import settings
from django.db import models

from .fields import EncryptedTextField
from .managers import UserScopedQuerySet


class InstitutionQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(user=user)


class Institution(models.Model):
    """One SimpleFIN Access URL per row. May back multiple Accounts."""

    PROVIDER_CHOICES = [
        ("simplefin", "SimpleFIN"),
        # ("plaid", "Plaid"),  # future
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="institutions")
    name = models.CharField(max_length=200, help_text="User-friendly label for this connection.")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default="simplefin")
    access_url = EncryptedTextField(help_text="Provider access URL. Encrypted at rest.")
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    objects = InstitutionQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_provider_display()})"
```

- [ ] **Step 2: Generate the migration**

```bash
docker compose exec web python manage.py makemigrations banking
```

Expected: creates `apps/banking/migrations/0001_initial.py` (generated — don't hand-write).

- [ ] **Step 3: Apply the migration**

```bash
docker compose exec web python manage.py migrate
```

Expected: `Applying banking.0001_initial... OK`

- [ ] **Step 4: Commit**

```bash
git add apps/banking/models.py apps/banking/migrations/
git commit -m "feat(banking): add Institution model with encrypted access_url"
```

---

## Task 6: `Account` model

**Files:**
- Modify: `apps/banking/models.py`
- New migration (generated)

- [ ] **Step 1: Read `apps/banking/models.py` and append this before the final newline**

```python


class AccountQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(institution__user=user)


class Account(models.Model):
    """A bank account exposed via a SimpleFIN Institution."""

    TYPE_CHOICES = [
        ("checking", "Checking"),
        ("savings", "Savings"),
        ("credit", "Credit Card"),
        ("loan", "Loan"),
        ("other", "Other"),
    ]

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="accounts")
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="other")
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="USD")
    org_name = models.CharField(max_length=200, blank=True, help_text="Institution name from provider (e.g., 'Chase').")
    external_id = models.CharField(max_length=200, help_text="Provider's account ID; used as the upsert key.")
    last_synced_at = models.DateTimeField(null=True, blank=True)

    objects = AccountQuerySet.as_manager()

    class Meta:
        ordering = ["institution", "name"]
        constraints = [
            models.UniqueConstraint(fields=["institution", "external_id"], name="uniq_account_per_institution"),
        ]

    def __str__(self):
        return f"{self.org_name or self.institution.name} · {self.name}"
```

- [ ] **Step 2: Generate migration**

```bash
docker compose exec web python manage.py makemigrations banking
```

Expected: creates `apps/banking/migrations/0002_account.py`.

- [ ] **Step 3: Apply migration**

```bash
docker compose exec web python manage.py migrate
```

- [ ] **Step 4: Commit**

```bash
git add apps/banking/models.py apps/banking/migrations/
git commit -m "feat(banking): add Account model chained to Institution"
```

---

## Task 7: `Transaction` model

**Files:**
- Modify: `apps/banking/models.py`
- New migration (generated)

- [ ] **Step 1: Append to `apps/banking/models.py`**

```python


class TransactionQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(account__institution__user=user)


class Transaction(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="transactions")
    posted_at = models.DateTimeField(db_index=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    description = models.CharField(max_length=500, blank=True)
    payee = models.CharField(max_length=200, blank=True)
    memo = models.CharField(max_length=500, blank=True)
    pending = models.BooleanField(default=False)
    external_id = models.CharField(max_length=200, help_text="Provider's txn ID; upsert key.")

    objects = TransactionQuerySet.as_manager()

    class Meta:
        ordering = ["-posted_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["account", "external_id"], name="uniq_txn_per_account"),
        ]

    def __str__(self):
        return f"{self.posted_at:%Y-%m-%d} {self.amount} {self.payee or self.description}"
```

- [ ] **Step 2: Generate + apply migration**

```bash
docker compose exec web python manage.py makemigrations banking
docker compose exec web python manage.py migrate
```

- [ ] **Step 3: Commit**

```bash
git add apps/banking/models.py apps/banking/migrations/
git commit -m "feat(banking): add Transaction model chained to Account"
```

---

## Task 8: Multi-tenancy isolation test (non-skippable)

This is the test we absolutely will not ship without. Every user-scoped model must be filterable via `for_user()` and must not leak cross-user data.

**Files:**
- Create: `apps/banking/tests/test_isolation.py`

- [ ] **Step 1: Write `apps/banking/tests/test_isolation.py`**

```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.banking.models import Account, Institution, Transaction

User = get_user_model()


@pytest.fixture
def two_users_with_data(db):
    alice = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    bob = User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")

    inst_a = Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example/token")
    inst_b = Institution.objects.create(user=bob, name="Bob Bank", access_url="https://bob.example/token")

    acct_a = Account.objects.create(
        institution=inst_a, name="Alice Checking", type="checking",
        balance=Decimal("100.00"), external_id="A-1",
    )
    acct_b = Account.objects.create(
        institution=inst_b, name="Bob Checking", type="checking",
        balance=Decimal("200.00"), external_id="B-1",
    )

    Transaction.objects.create(
        account=acct_a, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-10.00"), description="Alice coffee", external_id="TA-1",
    )
    Transaction.objects.create(
        account=acct_b, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("-20.00"), description="Bob coffee", external_id="TB-1",
    )

    return alice, bob, inst_a, inst_b, acct_a, acct_b


def test_institution_for_user_returns_only_own_rows(two_users_with_data):
    alice, bob, *_ = two_users_with_data
    assert list(Institution.objects.for_user(alice).values_list("name", flat=True)) == ["Alice Bank"]
    assert list(Institution.objects.for_user(bob).values_list("name", flat=True)) == ["Bob Bank"]


def test_account_for_user_returns_only_own_rows(two_users_with_data):
    alice, bob, *_ = two_users_with_data
    assert list(Account.objects.for_user(alice).values_list("name", flat=True)) == ["Alice Checking"]
    assert list(Account.objects.for_user(bob).values_list("name", flat=True)) == ["Bob Checking"]


def test_transaction_for_user_returns_only_own_rows(two_users_with_data):
    alice, bob, *_ = two_users_with_data
    assert list(Transaction.objects.for_user(alice).values_list("description", flat=True)) == ["Alice coffee"]
    assert list(Transaction.objects.for_user(bob).values_list("description", flat=True)) == ["Bob coffee"]


def test_institution_access_url_round_trips_encrypted(two_users_with_data):
    """Sanity-check that the EncryptedTextField decrypts on read."""
    alice, *_ = two_users_with_data
    fresh = Institution.objects.get(user=alice)
    assert fresh.access_url == "https://alice.example/token"
```

- [ ] **Step 2: Run and verify**

```bash
docker compose exec web pytest apps/banking/tests/test_isolation.py -v
```

Expected: 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add apps/banking/tests/test_isolation.py
git commit -m "test(banking): non-skippable multi-tenancy isolation test"
```

---

## Task 9: Django admin registration

**Files:**
- Create: `apps/banking/admin.py`

- [ ] **Step 1: Write `apps/banking/admin.py`**

```python
from django.contrib import admin

from .models import Account, Institution, Transaction


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "provider", "last_synced_at", "created_at")
    list_filter = ("provider", "user")
    search_fields = ("name", "user__username")
    readonly_fields = ("created_at", "last_synced_at")
    # access_url stays writable for debugging but is displayed encrypted in list_display by absence


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("__str__", "type", "balance", "currency", "last_synced_at")
    list_filter = ("type", "institution__user")
    search_fields = ("name", "org_name", "external_id")
    readonly_fields = ("last_synced_at",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("posted_at", "payee", "amount", "account", "pending")
    list_filter = ("pending", "account__institution__user")
    search_fields = ("payee", "description", "memo", "external_id")
    date_hierarchy = "posted_at"
```

- [ ] **Step 2: Smoke-check in the browser (optional but recommended)**

With containers running, visit `http://<your-tailnet-ip>:<WEB_PORT>/admin/` and log in as one of the superusers. Confirm Institution, Account, Transaction all appear under "Banking" and clicking each gives an empty list view.

- [ ] **Step 3: Commit**

```bash
git add apps/banking/admin.py
git commit -m "feat(banking): register Institution/Account/Transaction in admin"
```

---

## Task 10: `apps/providers/` skeleton + Protocol

**Files:**
- Create: `apps/providers/__init__.py`
- Create: `apps/providers/apps.py`
- Create: `apps/providers/base.py`
- Modify: `config/settings.py` (add to INSTALLED_APPS)

- [ ] **Step 1: `apps/providers/__init__.py`** — empty.

- [ ] **Step 2: `apps/providers/apps.py`**

```python
from django.apps import AppConfig


class ProvidersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.providers"
    label = "providers"
```

- [ ] **Step 3: `apps/providers/base.py`** — Protocol + dataclasses

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Protocol


@dataclass(frozen=True)
class AccountData:
    external_id: str
    name: str
    type: str            # "checking" | "savings" | "credit" | "loan" | "other"
    balance: Decimal
    currency: str
    org_name: str


@dataclass(frozen=True)
class TransactionData:
    external_id: str
    posted_at: datetime
    amount: Decimal
    description: str
    payee: str
    memo: str
    pending: bool


@dataclass(frozen=True)
class AccountSyncPayload:
    """What a provider returns from a sync call: each account with its own recent transactions."""
    account: AccountData
    transactions: tuple[TransactionData, ...]


class FinancialProvider(Protocol):
    """Contract every aggregator implementation must satisfy.

    Keep provider code pure: no Django model imports, no DB writes. The
    service layer in apps/banking/services.py takes provider output and
    upserts it into the domain models.
    """

    name: str  # "simplefin", "plaid", ...

    def exchange_setup_token(self, setup_token: str) -> str:
        """Convert a one-time setup token into a long-lived access URL."""
        ...

    def fetch_accounts_with_transactions(self, access_url: str) -> Iterable[AccountSyncPayload]:
        """Pull every account + its recent transactions in one call."""
        ...
```

- [ ] **Step 4: Add `apps.providers` to `INSTALLED_APPS`** in `config/settings.py` right after `apps.banking`.

- [ ] **Step 5: Commit**

```bash
git add apps/providers/ config/settings.py
git commit -m "feat(providers): app skeleton, FinancialProvider Protocol, data dataclasses"
```

---

## Task 11: Provider registry

**Files:**
- Create: `apps/providers/registry.py`

- [ ] **Step 1: Write `apps/providers/registry.py`**

```python
from typing import Type

from .base import FinancialProvider

_REGISTRY: dict[str, Type[FinancialProvider]] = {}


def register(provider_cls: Type[FinancialProvider]) -> Type[FinancialProvider]:
    """Class decorator / function that adds a provider to the registry by name."""
    _REGISTRY[provider_cls.name] = provider_cls
    return provider_cls


def get(name: str) -> FinancialProvider:
    """Return a fresh instance of the named provider."""
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown provider: {name!r}. Registered: {sorted(_REGISTRY)}") from exc
    return cls()
```

- [ ] **Step 2: Commit**

```bash
git add apps/providers/registry.py
git commit -m "feat(providers): name-keyed registry"
```

---

## Task 12: `SimpleFINProvider` — implement the Protocol

**Files:**
- Create: `apps/providers/simplefin.py`

SimpleFIN wire protocol summary:
- **Setup token** (one-time): base64 string. Decode → get a URL. HTTP POST (empty body) to that URL → response body is the Access URL as plaintext.
- **Access URL**: looks like `https://USER:TOKEN@bridge.simplefin.org/simplefin`. HTTP Basic auth is embedded. GET `{access_url}/accounts` returns JSON with accounts + transactions.
- Response shape: `{"errors": [], "accounts": [{"id": "...", "name": "...", "currency": "USD", "balance": "1234.56", "org": {"domain": "...", "name": "..."}, "transactions": [{"id": "...", "posted": 1706000000, "amount": "-42.18", "description": "...", "payee": "...", "memo": "", "pending": false}]}]}`
- Amounts are strings (so parse via `Decimal`).
- `posted` is a Unix timestamp (seconds, UTC).
- For max history, append `?start-date=0` to the accounts URL.

- [ ] **Step 1: Write `apps/providers/simplefin.py`**

```python
import base64
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

import requests

from .base import AccountData, AccountSyncPayload, FinancialProvider, TransactionData
from .registry import register

_SIMPLEFIN_TYPE_HINTS = {
    # SimpleFIN doesn't have a standard account-type field, so we guess from the account name.
    "checking": ("checking", "chk"),
    "savings": ("savings", "sav"),
    "credit": ("credit", "card", "visa", "mastercard", "amex"),
    "loan": ("loan", "mortgage", "auto"),
}


def _guess_type(name: str) -> str:
    lower = name.lower()
    for typ, hints in _SIMPLEFIN_TYPE_HINTS.items():
        if any(h in lower for h in hints):
            return typ
    return "other"


@register
class SimpleFINProvider:
    name = "simplefin"

    def __init__(self, http: requests.Session | None = None, timeout: float = 30.0) -> None:
        self._http = http or requests.Session()
        self._timeout = timeout

    def exchange_setup_token(self, setup_token: str) -> str:
        """POST to the decoded setup-token URL; response body is the access URL."""
        try:
            decoded = base64.b64decode(setup_token.strip(), validate=True).decode().strip()
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Setup token is not valid base64.") from exc
        if not decoded.startswith("https://"):
            raise ValueError("Decoded setup token is not an HTTPS URL.")
        response = self._http.post(decoded, timeout=self._timeout)
        response.raise_for_status()
        access_url = response.text.strip()
        if not access_url.startswith("https://"):
            raise ValueError(f"Unexpected setup-exchange response: {access_url[:80]!r}")
        return access_url

    def fetch_accounts_with_transactions(self, access_url: str) -> Iterable[AccountSyncPayload]:
        url = f"{access_url.rstrip('/')}/accounts?start-date=0"
        response = self._http.get(url, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()

        errors = payload.get("errors") or []
        if errors:
            # Errors are usually per-institution and don't fail the whole call — surface them but keep going.
            # For Phase 2 we just log via exception message if there's nothing usable.
            if not payload.get("accounts"):
                raise RuntimeError(f"SimpleFIN returned errors and no accounts: {errors}")

        for raw_account in payload.get("accounts", []):
            yield self._parse_account(raw_account)

    def _parse_account(self, raw: dict) -> AccountSyncPayload:
        org = raw.get("org", {}) or {}
        account = AccountData(
            external_id=str(raw["id"]),
            name=str(raw.get("name", "Unnamed Account")),
            type=_guess_type(str(raw.get("name", ""))),
            balance=Decimal(str(raw.get("balance", "0"))),
            currency=str(raw.get("currency", "USD")),
            org_name=str(org.get("name", "")),
        )
        transactions = tuple(self._parse_transaction(t) for t in raw.get("transactions", []))
        return AccountSyncPayload(account=account, transactions=transactions)

    def _parse_transaction(self, raw: dict) -> TransactionData:
        posted = datetime.fromtimestamp(int(raw["posted"]), tz=timezone.utc)
        return TransactionData(
            external_id=str(raw["id"]),
            posted_at=posted,
            amount=Decimal(str(raw.get("amount", "0"))),
            description=str(raw.get("description", "")),
            payee=str(raw.get("payee", "")),
            memo=str(raw.get("memo", "")),
            pending=bool(raw.get("pending", False)),
        )
```

- [ ] **Step 2: Commit**

```bash
git add apps/providers/simplefin.py
git commit -m "feat(providers): SimpleFIN client with setup-token exchange and accounts fetch"
```

---

## Task 13: SimpleFIN provider tests (with mocked HTTP)

**Files:**
- Create: `apps/providers/tests/__init__.py`
- Create: `apps/providers/tests/test_simplefin.py`
- Modify: `requirements.txt` (append `responses`)

`responses` is a drop-in mock layer for the `requests` library — register expected URLs + response bodies, then call your code normally.

- [ ] **Step 1: Append to `requirements.txt`**

```
responses==0.25.3
```

- [ ] **Step 2: Rebuild the image so the new dep lands**

```bash
docker compose build web
docker compose up -d web
```

- [ ] **Step 3: Create `apps/providers/tests/__init__.py`** — empty.

- [ ] **Step 4: Write `apps/providers/tests/test_simplefin.py`**

```python
import base64
import json

import pytest
import responses

from apps.providers.simplefin import SimpleFINProvider


def _encode_setup_url(url: str) -> str:
    return base64.b64encode(url.encode()).decode()


@responses.activate
def test_exchange_setup_token_returns_access_url():
    setup_url = "https://bridge.simplefin.org/simplefin/claim/ABCDEF"
    access_url = "https://USER:TOKEN@bridge.simplefin.org/simplefin"
    responses.add(responses.POST, setup_url, body=access_url, status=200)

    got = SimpleFINProvider().exchange_setup_token(_encode_setup_url(setup_url))
    assert got == access_url


@responses.activate
def test_exchange_setup_token_rejects_non_base64():
    with pytest.raises(ValueError, match="not valid base64"):
        SimpleFINProvider().exchange_setup_token("not!!base64!!")


@responses.activate
def test_exchange_setup_token_rejects_non_https_decoded():
    with pytest.raises(ValueError, match="not an HTTPS URL"):
        SimpleFINProvider().exchange_setup_token(_encode_setup_url("ftp://evil.example/x"))


@responses.activate
def test_fetch_accounts_parses_payload():
    access_url = "https://USER:TOKEN@bridge.simplefin.org/simplefin"
    accounts_url = f"{access_url}/accounts?start-date=0"
    responses.add(
        responses.GET,
        accounts_url,
        json={
            "errors": [],
            "accounts": [
                {
                    "id": "ACC-1",
                    "name": "Joint Checking",
                    "currency": "USD",
                    "balance": "1234.56",
                    "org": {"name": "Chase"},
                    "transactions": [
                        {
                            "id": "TXN-1",
                            "posted": 1706000000,
                            "amount": "-42.18",
                            "description": "Coffee shop",
                            "payee": "Starbucks",
                            "memo": "",
                            "pending": False,
                        }
                    ],
                }
            ],
        },
        status=200,
    )

    payloads = list(SimpleFINProvider().fetch_accounts_with_transactions(access_url))

    assert len(payloads) == 1
    p = payloads[0]
    assert p.account.external_id == "ACC-1"
    assert p.account.name == "Joint Checking"
    assert p.account.type == "checking"
    assert p.account.balance == __import__("decimal").Decimal("1234.56")
    assert p.account.org_name == "Chase"
    assert len(p.transactions) == 1
    assert p.transactions[0].external_id == "TXN-1"
    assert p.transactions[0].payee == "Starbucks"
    assert p.transactions[0].amount == __import__("decimal").Decimal("-42.18")


@responses.activate
def test_fetch_raises_when_errors_and_no_accounts():
    access_url = "https://U:T@bridge.simplefin.org/simplefin"
    responses.add(
        responses.GET,
        f"{access_url}/accounts?start-date=0",
        json={"errors": ["broken"], "accounts": []},
        status=200,
    )
    with pytest.raises(RuntimeError, match="errors and no accounts"):
        list(SimpleFINProvider().fetch_accounts_with_transactions(access_url))
```

- [ ] **Step 5: Run tests**

```bash
docker compose exec web pytest apps/providers/tests/ -v
```

Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/providers/tests/ requirements.txt
git commit -m "test(providers): SimpleFIN client against mocked HTTP responses"
```

---

## Task 14: Service layer — `link_institution` + `sync_institution`

**Files:**
- Create: `apps/banking/services.py`

This is the seam between views and providers. Views call these functions with a user + input; services call providers, upsert model rows, and return domain objects.

- [ ] **Step 1: Write `apps/banking/services.py`**

```python
from dataclasses import dataclass
from django.db import transaction
from django.utils import timezone

from apps.providers.registry import get as get_provider

from .models import Account, Institution, Transaction


@dataclass
class SyncResult:
    institution: Institution
    accounts_created: int
    accounts_updated: int
    transactions_created: int
    transactions_updated: int


def link_institution(*, user, setup_token: str, display_name: str, provider_name: str = "simplefin") -> Institution:
    """Exchange a setup token for an access URL, store it, and do an initial sync."""
    provider = get_provider(provider_name)
    access_url = provider.exchange_setup_token(setup_token)
    institution = Institution.objects.create(
        user=user,
        name=display_name,
        provider=provider_name,
        access_url=access_url,
    )
    sync_institution(institution)
    return institution


def sync_institution(institution: Institution) -> SyncResult:
    """Fetch fresh data from the provider and upsert accounts + transactions."""
    provider = get_provider(institution.provider)

    accounts_created = accounts_updated = 0
    transactions_created = transactions_updated = 0

    with transaction.atomic():
        for payload in provider.fetch_accounts_with_transactions(institution.access_url):
            acc, acc_created = Account.objects.update_or_create(
                institution=institution,
                external_id=payload.account.external_id,
                defaults={
                    "name": payload.account.name,
                    "type": payload.account.type,
                    "balance": payload.account.balance,
                    "currency": payload.account.currency,
                    "org_name": payload.account.org_name,
                    "last_synced_at": timezone.now(),
                },
            )
            if acc_created:
                accounts_created += 1
            else:
                accounts_updated += 1

            for tx in payload.transactions:
                _, tx_created = Transaction.objects.update_or_create(
                    account=acc,
                    external_id=tx.external_id,
                    defaults={
                        "posted_at": tx.posted_at,
                        "amount": tx.amount,
                        "description": tx.description,
                        "payee": tx.payee,
                        "memo": tx.memo,
                        "pending": tx.pending,
                    },
                )
                if tx_created:
                    transactions_created += 1
                else:
                    transactions_updated += 1

        institution.last_synced_at = timezone.now()
        institution.save(update_fields=["last_synced_at"])

    return SyncResult(
        institution=institution,
        accounts_created=accounts_created,
        accounts_updated=accounts_updated,
        transactions_created=transactions_created,
        transactions_updated=transactions_updated,
    )
```

- [ ] **Step 2: Commit**

```bash
git add apps/banking/services.py
git commit -m "feat(banking): link_institution and sync_institution services with upsert logic"
```

---

## Task 15: Service-layer tests (with a fake provider)

**Files:**
- Create: `apps/banking/tests/test_services.py`

- [ ] **Step 1: Write the test**

```python
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.banking.models import Account, Institution, Transaction
from apps.banking.services import link_institution, sync_institution
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

    def fetch_accounts_with_transactions(self, access_url: str):
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
    # Second sync — should update, not duplicate
    result = sync_institution(inst)
    assert result.accounts_created == 0
    assert result.accounts_updated == 1
    assert result.transactions_created == 0
    assert result.transactions_updated == 1
    assert Account.objects.filter(institution=inst).count() == 1
    assert Transaction.objects.filter(account__institution=inst).count() == 1
```

- [ ] **Step 2: Run**

```bash
docker compose exec web pytest apps/banking/tests/test_services.py -v
```

Expected: 2 tests pass.

- [ ] **Step 3: Commit**

```bash
git add apps/banking/tests/test_services.py
git commit -m "test(banking): link + sync services with a fake provider"
```

---

## Task 16: Banking URLs

**Files:**
- Create: `apps/banking/urls.py`
- Modify: `config/urls.py`

- [ ] **Step 1: Write `apps/banking/urls.py`**

```python
from django.urls import path

from . import views

app_name = "banking"

urlpatterns = [
    path("", views.banks_list, name="list"),
    path("link/", views.link_form, name="link"),
    path("<int:institution_id>/sync/", views.sync_institution_view, name="sync"),
    path("accounts/<int:account_id>/", views.account_detail, name="account_detail"),
]
```

- [ ] **Step 2: Include in `config/urls.py`**

Replace the content with:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("banks/", include("apps.banking.urls")),
    path("", include("apps.accounts.urls")),
]
```

The order matters: `/banks/` has to be registered before the catch-all empty-path include in accounts.

- [ ] **Step 3: Commit**

```bash
git add apps/banking/urls.py config/urls.py
git commit -m "feat(banking): wire URL routes under /banks/"
```

---

## Task 17: Banks list view + template

**Files:**
- Create: `apps/banking/views.py` (starts here, grows in Tasks 18–20)
- Create: `apps/banking/templates/banking/banks_list.html`

- [ ] **Step 1: Write `apps/banking/views.py`**

```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Institution


@login_required
def banks_list(request):
    institutions = (
        Institution.objects
        .for_user(request.user)
        .prefetch_related("accounts")
    )
    return render(request, "banking/banks_list.html", {"institutions": institutions})


# link_form, sync_institution_view, account_detail land in Tasks 18–20.
```

Add stubs for the not-yet-written views so URLs don't error on import:

```python
def link_form(request):
    raise NotImplementedError  # Task 18


def sync_institution_view(request, institution_id):
    raise NotImplementedError  # Task 19


def account_detail(request, account_id):
    raise NotImplementedError  # Task 20
```

(The full `views.py` at end-of-Task-17:)

```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Institution


@login_required
def banks_list(request):
    institutions = (
        Institution.objects
        .for_user(request.user)
        .prefetch_related("accounts")
    )
    return render(request, "banking/banks_list.html", {"institutions": institutions})


@login_required
def link_form(request):
    raise NotImplementedError  # Task 18


@login_required
def sync_institution_view(request, institution_id):
    raise NotImplementedError  # Task 19


@login_required
def account_detail(request, account_id):
    raise NotImplementedError  # Task 20
```

- [ ] **Step 2: Write `apps/banking/templates/banking/banks_list.html`**

```html
{% extends "base.html" %}
{% block title %}Banks{% endblock %}
{% block content %}
<div class="flex items-center justify-between mb-6">
  <h1 class="text-2xl font-bold">Banks</h1>
  <a href="{% url 'banking:link' %}"
     class="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-4 py-2 rounded">
    + Link account
  </a>
</div>

{% if not institutions %}
  <div class="bg-slate-900 border border-slate-800 rounded p-6 text-slate-400">
    No banks linked yet. Click <strong class="text-slate-200">Link account</strong> to connect a bank via SimpleFIN.
  </div>
{% else %}
  <div class="space-y-4">
    {% for inst in institutions %}
    <div class="bg-slate-900 border border-slate-800 rounded">
      <div class="flex items-center justify-between px-5 py-3 border-b border-slate-800">
        <div>
          <div class="font-semibold">{{ inst.name }}</div>
          <div class="text-xs text-slate-500">
            {{ inst.get_provider_display }} ·
            Last synced: {% if inst.last_synced_at %}{{ inst.last_synced_at|date:"M j, Y g:i a" }}{% else %}never{% endif %}
          </div>
        </div>
        <form method="post" action="{% url 'banking:sync' inst.id %}" class="m-0">
          {% csrf_token %}
          <button type="submit" class="text-slate-400 hover:text-white text-sm">⟳ Sync</button>
        </form>
      </div>
      <div class="divide-y divide-slate-800">
        {% for account in inst.accounts.all %}
        <a href="{% url 'banking:account_detail' account.id %}"
           class="flex items-center justify-between px-5 py-3 hover:bg-slate-800/40">
          <div>
            <div class="font-medium">{{ account.name }}</div>
            <div class="text-xs text-slate-500">{{ account.org_name|default:"" }} · {{ account.get_type_display }}</div>
          </div>
          <div class="font-mono {% if account.balance < 0 %}text-red-300{% else %}text-slate-100{% endif %}">
            {{ account.balance }} {{ account.currency }}
          </div>
        </a>
        {% empty %}
        <div class="px-5 py-3 text-slate-500 text-sm">No accounts returned yet — try syncing.</div>
        {% endfor %}
      </div>
    </div>
    {% endfor %}
  </div>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add apps/banking/views.py apps/banking/templates/
git commit -m "feat(banking): banks_list view and template"
```

---

## Task 18: Link form view — accept setup token, call service, redirect

**Files:**
- Modify: `apps/banking/views.py`
- Create: `apps/banking/templates/banking/link_form.html`

- [ ] **Step 1: Replace the `link_form` stub in `apps/banking/views.py`** with:

```python
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .services import link_institution
```

(Add these imports to the top; keep the existing imports.)

Replace the `link_form` stub body:

```python
@login_required
@require_http_methods(["GET", "POST"])
def link_form(request):
    if request.method == "POST":
        setup_token = request.POST.get("setup_token", "").strip()
        display_name = request.POST.get("display_name", "").strip() or "SimpleFIN Account"
        if not setup_token:
            messages.error(request, "Setup token is required.")
            return render(request, "banking/link_form.html", {})
        try:
            link_institution(user=request.user, setup_token=setup_token, display_name=display_name)
        except Exception as exc:
            messages.error(request, f"Link failed: {exc}")
            return render(request, "banking/link_form.html", {"display_name": display_name})
        messages.success(request, "Institution linked. Initial sync complete.")
        return HttpResponseRedirect(reverse("banking:list"))
    return render(request, "banking/link_form.html", {})
```

- [ ] **Step 2: Write `apps/banking/templates/banking/link_form.html`**

```html
{% extends "base.html" %}
{% block title %}Link account{% endblock %}
{% block content %}
<div class="max-w-xl mx-auto">
  <h1 class="text-2xl font-bold mb-4">Link a bank via SimpleFIN</h1>
  <ol class="text-slate-400 text-sm list-decimal list-inside space-y-1 mb-6">
    <li>Open <a href="https://beta-bridge.simplefin.org/" class="text-emerald-400 underline" target="_blank" rel="noopener">beta-bridge.simplefin.org</a>, sign in, connect your bank(s).</li>
    <li>Create a new <strong>Setup Token</strong>.</li>
    <li>Paste it below. This app will exchange it for a long-lived access URL (encrypted at rest).</li>
  </ol>

  {% if messages %}
    {% for message in messages %}
    <div class="bg-{% if message.tags == 'error' %}red-900/40 border-red-700 text-red-200{% else %}emerald-900/40 border-emerald-700 text-emerald-200{% endif %} border p-3 rounded text-sm mb-4">
      {{ message }}
    </div>
    {% endfor %}
  {% endif %}

  <form method="post" class="space-y-4">
    {% csrf_token %}
    <div>
      <label class="block text-sm text-slate-400 mb-1" for="id_display_name">Display name</label>
      <input id="id_display_name" name="display_name" type="text" value="{{ display_name|default:'' }}"
             placeholder="e.g., SimpleFIN · Main banks"
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2">
    </div>
    <div>
      <label class="block text-sm text-slate-400 mb-1" for="id_setup_token">Setup token</label>
      <textarea id="id_setup_token" name="setup_token" rows="4" required
                class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 font-mono text-xs"
                placeholder="base64 blob from SimpleFIN Bridge"></textarea>
    </div>
    <div class="flex items-center gap-3">
      <button type="submit" class="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-5 py-2 rounded">
        Link
      </button>
      <a href="{% url 'banking:list' %}" class="text-slate-400 hover:text-white text-sm">Cancel</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add apps/banking/views.py apps/banking/templates/banking/link_form.html
git commit -m "feat(banking): link_form view and template"
```

---

## Task 19: Manual sync view — POST-only, re-sync an existing institution

**Files:**
- Modify: `apps/banking/views.py`

- [ ] **Step 1: Replace the `sync_institution_view` stub with**:

```python
from django.shortcuts import get_object_or_404

from .services import sync_institution


@login_required
@require_http_methods(["POST"])
def sync_institution_view(request, institution_id):
    institution = get_object_or_404(Institution.objects.for_user(request.user), pk=institution_id)
    try:
        result = sync_institution(institution)
    except Exception as exc:
        messages.error(request, f"Sync failed: {exc}")
    else:
        messages.success(
            request,
            f"Synced {result.accounts_created + result.accounts_updated} accounts "
            f"({result.transactions_created} new transactions).",
        )
    return HttpResponseRedirect(reverse("banking:list"))
```

(Add the `get_object_or_404` import at the top if not already present.)

- [ ] **Step 2: Commit**

```bash
git add apps/banking/views.py
git commit -m "feat(banking): manual sync view (POST /banks/<id>/sync/)"
```

---

## Task 20: Account detail view + template (transactions list)

**Files:**
- Modify: `apps/banking/views.py`
- Create: `apps/banking/templates/banking/account_detail.html`

- [ ] **Step 1: Replace the `account_detail` stub**:

```python
from .models import Account, Transaction


@login_required
def account_detail(request, account_id):
    account = get_object_or_404(Account.objects.for_user(request.user), pk=account_id)
    transactions = (
        Transaction.objects
        .filter(account=account)
        .order_by("-posted_at", "-id")[:500]
    )
    return render(request, "banking/account_detail.html", {
        "account": account,
        "transactions": transactions,
    })
```

- [ ] **Step 2: Write `apps/banking/templates/banking/account_detail.html`**

```html
{% extends "base.html" %}
{% block title %}{{ account.name }}{% endblock %}
{% block content %}
<a href="{% url 'banking:list' %}" class="text-slate-500 hover:text-white text-sm">← Banks</a>

<div class="flex items-end justify-between mt-2 mb-6">
  <div>
    <h1 class="text-2xl font-bold">{{ account.name }}</h1>
    <div class="text-slate-500 text-sm">{{ account.org_name }} · {{ account.get_type_display }}</div>
  </div>
  <div class="text-right">
    <div class="text-xs text-slate-500 uppercase tracking-wider">Balance</div>
    <div class="text-2xl font-mono {% if account.balance < 0 %}text-red-300{% else %}text-emerald-200{% endif %}">
      {{ account.balance }} {{ account.currency }}
    </div>
  </div>
</div>

{% if not transactions %}
  <div class="bg-slate-900 border border-slate-800 rounded p-6 text-slate-400 text-sm">
    No transactions yet.
  </div>
{% else %}
  <div class="bg-slate-900 border border-slate-800 rounded divide-y divide-slate-800">
    {% for tx in transactions %}
    <div class="flex items-start justify-between px-5 py-3">
      <div class="min-w-0 pr-4">
        <div class="font-medium truncate">{{ tx.payee|default:tx.description }}</div>
        <div class="text-xs text-slate-500">
          {{ tx.posted_at|date:"M j, Y" }}{% if tx.pending %} · <span class="text-amber-400">pending</span>{% endif %}
          {% if tx.memo %} · {{ tx.memo }}{% endif %}
        </div>
      </div>
      <div class="font-mono {% if tx.amount < 0 %}text-red-300{% else %}text-emerald-200{% endif %}">
        {{ tx.amount }}
      </div>
    </div>
    {% endfor %}
  </div>
  <p class="text-xs text-slate-500 mt-3">Showing latest 500 transactions. Full history / pagination later.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add apps/banking/views.py apps/banking/templates/banking/account_detail.html
git commit -m "feat(banking): account_detail view and transactions template"
```

---

## Task 21: Activate "Banks" nav link in base.html

**Files:**
- Modify: `apps/accounts/templates/base.html`

- [ ] **Step 1: Read `apps/accounts/templates/base.html` and find the line**:

```html
      <a href="/banks/" class="text-slate-500">Banks</a>
```

Replace with:

```html
      <a href="{% url 'banking:list' %}" class="text-slate-300 hover:text-white">Banks</a>
```

Leave Investments/Assets grey until Phases 3/4 activate them.

- [ ] **Step 2: Commit**

```bash
git add apps/accounts/templates/base.html
git commit -m "feat(banking): activate Banks nav link in base template"
```

---

## Task 22: View-level tests (request/response)

**Files:**
- Create: `apps/banking/tests/test_views.py`

- [ ] **Step 1: Write the tests**

```python
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
    assert b"No banks linked yet" in response.content


def test_banks_list_shows_only_own_institutions(alice, bob, alice_client):
    Institution.objects.create(user=alice, name="Alice Bank", access_url="https://alice.example")
    Institution.objects.create(user=bob, name="Bob Bank", access_url="https://bob.example")

    response = alice_client.get(reverse("banking:list"))
    assert b"Alice Bank" in response.content
    assert b"Bob Bank" not in response.content


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
```

- [ ] **Step 2: Run**

```bash
docker compose exec web pytest apps/banking/tests/test_views.py -v
```

Expected: 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add apps/banking/tests/test_views.py
git commit -m "test(banking): view-level tests for isolation and anonymous redirect"
```

---

## Task 23: Full test suite run + manual smoke test checkpoint

No code changes — integration gate.

- [ ] **Step 1: Run everything**

```bash
docker compose exec web pytest -v
```

Expected counts:
- Phase 1: 5 login-related tests
- Phase 2: 3 field + 4 isolation + 5 simplefin + 2 services + 5 views = 19 new
- **Total: 24 tests, all green.**

If anything fails, **don't proceed** — fix the failing case first.

- [ ] **Step 2: Manual flow check in browser**

On any tailnet device, visit `http://<host>:<WEB_PORT>/banks/`.

1. Page loads with "No banks linked yet."
2. Click "Link account" → form loads.
3. Go to https://beta-bridge.simplefin.org/, create a test connection (they have sandbox/demo banks), get a setup token.
4. Paste token + display name → submit. Expect redirect back to `/banks/` with the green success flash and a list of real accounts.
5. Click an account → transactions list renders with 500 most recent.
6. Click "⟳ Sync" on the institution → page reloads, "Synced N accounts (0 new transactions)".
7. Log in as `dad` in a private window. `/banks/` should be empty — confirms isolation.

- [ ] **Step 3: No commit — verification only.**

---

## Phase 2 Definition of Done

- [ ] `docker compose exec web pytest -v` reports 24 passing tests.
- [ ] `/banks/` renders for a logged-in user; anonymous gets redirected.
- [ ] A real SimpleFIN setup token links, does an initial sync, and shows accounts + transactions.
- [ ] Clicking an account shows its transaction list.
- [ ] Clicking "Sync" on an institution re-pulls and the page reports what changed.
- [ ] Logging in as `dad` shows zero institutions (isolation holds).
- [ ] `Institution.access_url` is stored encrypted — verify with `docker compose exec db psql -U finance -c "select access_url from banking_institution limit 1"` → you see a `gAAAA...` Fernet token, not the real URL.
- [ ] Django admin at `/admin/banking/` lists Institution / Account / Transaction.

When all green, Phase 2 ships. Next: write Phase 3 (Investments).
