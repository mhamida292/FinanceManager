# Personal Finance Dashboard — Phase 3: Investments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** User can see every investment position — from brokerages SimpleFIN reaches *and* from brokerages it doesn't — with current market value, cost basis, and gain/loss per holding. Supports manual entry for Fidelity (SimpleFIN unreliable there), 401k plans, and anything else aggregator-free. Prices for manual holdings come from Yahoo Finance via `yfinance`.

**Architecture:** New `apps/investments/` app with three models (`InvestmentAccount`, `Holding`, `PortfolioSnapshot`). Every account has a `source` field (`simplefin` | `manual`) — shape is identical, ingestion path differs. Provider abstraction extended with `fetch_investment_accounts` so the existing `FinancialProvider` Protocol covers both banking and investments cleanly. A new `PriceProvider` Protocol (first impl: `yfinance`) handles current-price lookups for manual holdings. Cost basis is per-position with a `cost_basis_source` field that locks user-entered values against sync overwrites — same pattern we used for Account `display_name` in Phase 2.

**Tech Stack:** Adds `yfinance==0.2.50`. Everything else is existing Django 5 / Postgres / HTMX.

**Non-Goals for Phase 3:**
- Daily automated price refresh (Phase 5 — host crontab).
- Automatic price lookup for SimpleFIN-sourced holdings; we trust SimpleFIN's `current_price` value for them. Refresh for those comes via re-syncing the institution.
- Buy/sell transaction history per holding (SimpleFIN returns some; we ignore for v1 — positions + current state only).
- Portfolio allocation charts, sector breakdowns, benchmarks, beta.
- Options, crypto, futures — equities and ETFs only in v1.
- Tax lots / FIFO / specific-share identification. Cost basis is one number per position.

---

## File Structure

```
finance/
├── apps/
│   ├── investments/              # NEW
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── admin.py
│   │   ├── models.py             # InvestmentAccount, Holding, PortfolioSnapshot
│   │   ├── managers.py           # InvestmentAccountQuerySet, HoldingQuerySet — for_user() chains
│   │   ├── services.py           # link / sync / manual create / refresh_prices
│   │   ├── urls.py
│   │   ├── views.py
│   │   ├── migrations/
│   │   │   └── __init__.py
│   │   ├── tests/
│   │   │   ├── __init__.py
│   │   │   ├── test_isolation.py
│   │   │   ├── test_models.py          # effective_name, gain_loss properties
│   │   │   ├── test_services.py        # sync preserves cost_basis_source=manual
│   │   │   ├── test_yfinance.py        # price provider with mocked HTTP
│   │   │   └── test_views.py           # auth + isolation + flows
│   │   └── templates/investments/
│   │       ├── investments_list.html
│   │       ├── account_detail.html
│   │       ├── add_account_form.html
│   │       ├── add_holding_form.html
│   │       └── edit_holding_form.html
│   └── providers/                # MODIFIED
│       ├── base.py               # add HoldingData, InvestmentAccountSyncPayload, new protocol method
│       ├── simplefin.py          # implement fetch_investment_accounts_with_holdings
│       ├── prices/               # NEW subpackage
│       │   ├── __init__.py
│       │   ├── base.py           # PriceProvider Protocol + PriceQuote dataclass
│       │   ├── registry.py       # name → class (mirror of providers/registry.py)
│       │   └── yahoo.py          # YahooFinancePriceProvider
│       └── tests/
│           └── test_yahoo.py     # mocked yfinance
```

Boundary rationale:
- **Same separation as Phase 2:** domain models live in `apps/investments/`, wire-level integration lives in `apps/providers/`. Services in `investments/services.py` are the seam.
- **`apps/providers/prices/`** is a deliberate subpackage — price sources are a different kind of provider (no auth, no OAuth, public endpoints, quote-only), so lumping them with the SimpleFIN-style aggregator providers would confuse the interface. Same registry pattern, different Protocol.
- `Holding` and `Account` intentionally share no parent class. The surface area is too different (holdings have shares/symbol/cost_basis, bank accounts have balance/transactions). A shared parent would pay zero rent.

---

## Task 1: Add `yfinance` dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Append to `requirements.txt`**

```
yfinance==0.2.50
```

`yfinance` pulls in `pandas` as a dep (~40MB). Accepted cost — it's the most maintained Python Yahoo Finance library and handles the session/cookie dance Yahoo requires.

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "chore(investments): add yfinance dependency"
```

---

## Task 2: `apps/investments/` skeleton

**Files:**
- Create: `apps/investments/__init__.py`
- Create: `apps/investments/apps.py`
- Modify: `config/settings.py`

- [ ] **Step 1: `apps/investments/__init__.py`** — empty.

- [ ] **Step 2: `apps/investments/apps.py`**

```python
from django.apps import AppConfig


class InvestmentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.investments"
    label = "investments"
```

- [ ] **Step 3: Add to `INSTALLED_APPS` in `config/settings.py`**

After `"apps.banking",` insert `"apps.investments",`. Final relevant section:

```python
    "apps.accounts",
    "apps.banking",
    "apps.investments",
    "apps.providers",
```

- [ ] **Step 4: Commit**

```bash
git add apps/investments/ config/settings.py
git commit -m "feat(investments): add investments app skeleton and register it"
```

---

## Task 3: Managers — `InvestmentAccountQuerySet` and `HoldingQuerySet`

**Files:**
- Create: `apps/investments/managers.py`

We'd like to reuse `apps.banking.managers.UserScopedQuerySet`. Importing across apps is fine; we just keep the subclasses in the owning app.

- [ ] **Step 1: Write `apps/investments/managers.py`**

```python
from apps.banking.managers import UserScopedQuerySet


class InvestmentAccountQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(user=user)


class HoldingQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(investment_account__user=user)


class PortfolioSnapshotQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(investment_account__user=user)
```

- [ ] **Step 2: Commit**

```bash
git add apps/investments/managers.py
git commit -m "feat(investments): UserScoped QuerySet subclasses with for_user() chains"
```

---

## Task 4: Models — `InvestmentAccount`, `Holding`, `PortfolioSnapshot`

**Files:**
- Create: `apps/investments/models.py`

Design notes:
- `InvestmentAccount.user` is always set (direct FK). For SimpleFIN-sourced rows, `institution` is also set. This double-wiring is intentional: `for_user()` filters on the direct `user` FK, which works uniformly for both sources without join surgery.
- `Holding.cost_basis_source` follows the `display_name` lock pattern from Phase 2: values written by sync are flagged `auto`; values written by the user are flagged `manual` and never overwritten on sync.
- `Holding.market_value` is **computed** (shares × current_price) and stored — stale between refreshes, fine for a dashboard. If this becomes an issue, it becomes a Python `@property` later.
- `PortfolioSnapshot` is written on every sync/refresh; one row per account per day. `update_or_create` guarantees idempotency.

- [ ] **Step 1: Write `apps/investments/models.py`**

```python
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.banking.models import Institution

from .managers import HoldingQuerySet, InvestmentAccountQuerySet, PortfolioSnapshotQuerySet


class InvestmentAccount(models.Model):
    """A brokerage account. May be SimpleFIN-sourced or user-entered."""

    SOURCE_CHOICES = [
        ("simplefin", "SimpleFIN"),
        ("manual", "Manual entry"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="investment_accounts")
    # Only set when source='simplefin'. Manual accounts have no institution parent.
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="investment_accounts",
        null=True, blank=True,
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    broker = models.CharField(max_length=200, blank=True, help_text="e.g., Fidelity, Robinhood. Free text.")
    name = models.CharField(max_length=200, help_text="Provider name for SimpleFIN accounts; user-entered for manual.")
    display_name = models.CharField(max_length=200, blank=True, default="", help_text="UI override; never overwritten by sync.")
    # SimpleFIN-specific
    external_id = models.CharField(max_length=200, blank=True, default="", help_text="Provider's account ID (SimpleFIN only).")
    currency = models.CharField(max_length=8, default="USD")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    objects = InvestmentAccountQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Uniqueness only applies when external_id is non-blank (SimpleFIN accounts).
            models.UniqueConstraint(
                fields=["institution", "external_id"],
                name="uniq_inv_account_per_institution",
                condition=~models.Q(external_id=""),
            ),
        ]

    @property
    def effective_name(self) -> str:
        return self.display_name or self.name

    def __str__(self):
        return f"{self.broker or self.effective_name} ({self.get_source_display()})"


class Holding(models.Model):
    """One position (ticker + share count) inside an InvestmentAccount."""

    COST_BASIS_SOURCE_CHOICES = [
        ("auto", "Auto (from provider)"),
        ("manual", "Manual (user-entered)"),
    ]

    investment_account = models.ForeignKey(InvestmentAccount, on_delete=models.CASCADE, related_name="holdings")
    symbol = models.CharField(max_length=20)
    description = models.CharField(max_length=200, blank=True, default="", help_text="Human-readable name, e.g. 'Apple Inc.'")
    shares = models.DecimalField(max_digits=16, decimal_places=6)
    current_price = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    market_value = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0"))
    cost_basis = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cost_basis_source = models.CharField(max_length=10, choices=COST_BASIS_SOURCE_CHOICES, default="auto")
    external_id = models.CharField(max_length=200, blank=True, default="", help_text="Provider's holding ID (SimpleFIN); blank for manual.")
    last_priced_at = models.DateTimeField(null=True, blank=True)

    objects = HoldingQuerySet.as_manager()

    class Meta:
        ordering = ["investment_account", "symbol"]
        constraints = [
            # For SimpleFIN holdings: external_id unique per account.
            models.UniqueConstraint(
                fields=["investment_account", "external_id"],
                name="uniq_holding_per_account_by_external_id",
                condition=~models.Q(external_id=""),
            ),
            # For manual holdings: one row per symbol per account (no lot tracking).
            models.UniqueConstraint(
                fields=["investment_account", "symbol"],
                name="uniq_manual_holding_per_symbol",
                condition=models.Q(external_id=""),
            ),
        ]

    @property
    def gain_loss(self) -> Decimal | None:
        if self.cost_basis is None:
            return None
        return self.market_value - self.cost_basis

    @property
    def gain_loss_percent(self) -> Decimal | None:
        if self.cost_basis is None or self.cost_basis == 0:
            return None
        return ((self.market_value - self.cost_basis) / self.cost_basis) * Decimal("100")

    def recompute_market_value(self) -> None:
        self.market_value = (self.shares * self.current_price).quantize(Decimal("0.01"))

    def __str__(self):
        return f"{self.symbol} × {self.shares}"


class PortfolioSnapshot(models.Model):
    investment_account = models.ForeignKey(InvestmentAccount, on_delete=models.CASCADE, related_name="snapshots")
    date = models.DateField(db_index=True)
    total_value = models.DecimalField(max_digits=18, decimal_places=2)

    objects = PortfolioSnapshotQuerySet.as_manager()

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["investment_account", "date"], name="uniq_snapshot_per_account_per_day"),
        ]

    def __str__(self):
        return f"{self.investment_account_id} on {self.date}: {self.total_value}"
```

- [ ] **Step 2: User generates migration** (remember the container-cp dance from Phase 2)

```bash
docker compose build web
docker compose up -d web
docker compose exec web python manage.py makemigrations investments
# note the filename from the output, e.g. 0001_initial.py
docker compose cp web:/app/apps/investments/migrations/0001_initial.py apps/investments/migrations/
docker compose exec web python manage.py migrate
```

Also create `apps/investments/migrations/__init__.py` as an empty file before makemigrations so Django has a package to write into.

- [ ] **Step 3: Commit**

```bash
git add apps/investments/models.py apps/investments/migrations/
git commit -m "feat(investments): InvestmentAccount, Holding, PortfolioSnapshot models"
```

---

## Task 5: Multi-tenancy isolation test

**Files:**
- Create: `apps/investments/tests/__init__.py`
- Create: `apps/investments/tests/test_isolation.py`

- [ ] **Step 1: Create `apps/investments/tests/__init__.py`** — empty.

- [ ] **Step 2: Write `apps/investments/tests/test_isolation.py`**

```python
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.investments.models import Holding, InvestmentAccount, PortfolioSnapshot

User = get_user_model()


@pytest.fixture
def two_users_with_investments(db):
    alice = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    bob = User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")

    inv_a = InvestmentAccount.objects.create(
        user=alice, source="manual", broker="Alice Brokerage", name="Alice IRA",
    )
    inv_b = InvestmentAccount.objects.create(
        user=bob, source="manual", broker="Bob Brokerage", name="Bob 401k",
    )

    h_a = Holding.objects.create(
        investment_account=inv_a, symbol="AAPL", shares=Decimal("10"),
        current_price=Decimal("180"), market_value=Decimal("1800"),
    )
    h_b = Holding.objects.create(
        investment_account=inv_b, symbol="MSFT", shares=Decimal("5"),
        current_price=Decimal("400"), market_value=Decimal("2000"),
    )

    PortfolioSnapshot.objects.create(investment_account=inv_a, date=date(2026, 4, 24), total_value=Decimal("1800"))
    PortfolioSnapshot.objects.create(investment_account=inv_b, date=date(2026, 4, 24), total_value=Decimal("2000"))

    return alice, bob, inv_a, inv_b, h_a, h_b


def test_investment_account_for_user_isolates(two_users_with_investments):
    alice, bob, *_ = two_users_with_investments
    assert list(InvestmentAccount.objects.for_user(alice).values_list("name", flat=True)) == ["Alice IRA"]
    assert list(InvestmentAccount.objects.for_user(bob).values_list("name", flat=True)) == ["Bob 401k"]


def test_holding_for_user_isolates(two_users_with_investments):
    alice, bob, *_ = two_users_with_investments
    assert list(Holding.objects.for_user(alice).values_list("symbol", flat=True)) == ["AAPL"]
    assert list(Holding.objects.for_user(bob).values_list("symbol", flat=True)) == ["MSFT"]


def test_snapshot_for_user_isolates(two_users_with_investments):
    alice, bob, *_ = two_users_with_investments
    assert PortfolioSnapshot.objects.for_user(alice).count() == 1
    assert PortfolioSnapshot.objects.for_user(bob).count() == 1


def test_gain_loss_properties(two_users_with_investments):
    _, _, _, _, h_a, _ = two_users_with_investments
    h_a.cost_basis = Decimal("1500")
    h_a.save()
    h_a.refresh_from_db()
    assert h_a.gain_loss == Decimal("300.00")
    assert h_a.gain_loss_percent == Decimal("20.00")


def test_gain_loss_none_without_cost_basis(two_users_with_investments):
    _, _, _, _, h_a, _ = two_users_with_investments
    assert h_a.cost_basis is None
    assert h_a.gain_loss is None
    assert h_a.gain_loss_percent is None
```

- [ ] **Step 3: Commit**

```bash
git add apps/investments/tests/
git commit -m "test(investments): isolation + gain/loss property tests"
```

---

## Task 6: Django admin registration

**Files:**
- Create: `apps/investments/admin.py`

- [ ] **Step 1: Write `apps/investments/admin.py`**

```python
from django.contrib import admin

from .models import Holding, InvestmentAccount, PortfolioSnapshot


@admin.register(InvestmentAccount)
class InvestmentAccountAdmin(admin.ModelAdmin):
    list_display = ("__str__", "source", "broker", "user", "last_synced_at")
    list_filter = ("source", "user")
    search_fields = ("name", "display_name", "broker", "external_id", "user__username")
    readonly_fields = ("created_at", "last_synced_at")


@admin.register(Holding)
class HoldingAdmin(admin.ModelAdmin):
    list_display = ("symbol", "investment_account", "shares", "current_price", "market_value", "cost_basis", "cost_basis_source")
    list_filter = ("cost_basis_source", "investment_account__source", "investment_account__user")
    search_fields = ("symbol", "description", "external_id")
    readonly_fields = ("last_priced_at", "market_value")


@admin.register(PortfolioSnapshot)
class PortfolioSnapshotAdmin(admin.ModelAdmin):
    list_display = ("date", "investment_account", "total_value")
    list_filter = ("investment_account__user", "date")
    date_hierarchy = "date"
```

- [ ] **Step 2: Commit**

```bash
git add apps/investments/admin.py
git commit -m "feat(investments): register models in admin"
```

---

## Task 7: Extend `FinancialProvider` Protocol with holdings

**Files:**
- Modify: `apps/providers/base.py`

- [ ] **Step 1: Append to `apps/providers/base.py`**

Before the existing `FinancialProvider` Protocol, add new dataclasses:

```python
@dataclass(frozen=True)
class HoldingData:
    external_id: str
    symbol: str
    description: str
    shares: Decimal
    current_price: Decimal
    market_value: Decimal
    cost_basis: Decimal | None   # None = provider didn't return it


@dataclass(frozen=True)
class InvestmentAccountSyncPayload:
    external_id: str
    name: str
    broker: str                   # SimpleFIN's "org.name" if present
    currency: str
    holdings: tuple[HoldingData, ...]
```

Then extend the `FinancialProvider` Protocol (modify the existing class definition to add one more method):

```python
class FinancialProvider(Protocol):
    name: str

    def exchange_setup_token(self, setup_token: str) -> str:
        ...

    def fetch_accounts_with_transactions(self, access_url: str) -> Iterable[AccountSyncPayload]:
        """Bank accounts and their recent transactions."""
        ...

    def fetch_investment_accounts(self, access_url: str) -> Iterable[InvestmentAccountSyncPayload]:
        """Investment accounts and their current holdings.

        Implementations may share an underlying API call with
        fetch_accounts_with_transactions — callers should not rely on whether
        or not two HTTP calls happen.
        """
        ...
```

- [ ] **Step 2: Commit**

```bash
git add apps/providers/base.py
git commit -m "feat(providers): extend Protocol with fetch_investment_accounts + HoldingData"
```

---

## Task 8: Implement `SimpleFINProvider.fetch_investment_accounts`

**Files:**
- Modify: `apps/providers/simplefin.py`

SimpleFIN's `/accounts` endpoint returns both bank and investment accounts in one list. Investment accounts have a non-empty `holdings` array. We filter and re-parse.

- [ ] **Step 1: Append to the `SimpleFINProvider` class in `apps/providers/simplefin.py`**

Add imports at the top:
```python
from .base import (
    AccountData, AccountSyncPayload, FinancialProvider, HoldingData,
    InvestmentAccountSyncPayload, TransactionData,
)
```

(Replace the existing import line of the same shape — just adds `HoldingData` and `InvestmentAccountSyncPayload`.)

Add methods to the `SimpleFINProvider` class (after `fetch_accounts_with_transactions`):

```python
    def fetch_investment_accounts(self, access_url: str) -> Iterable[InvestmentAccountSyncPayload]:
        url = f"{access_url.rstrip('/')}/accounts?start-date=0"
        response = self._http.get(url, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()

        for raw_account in payload.get("accounts", []):
            holdings = raw_account.get("holdings") or []
            if not holdings:
                continue  # bank account, skip
            yield self._parse_investment_account(raw_account)

    def _parse_investment_account(self, raw: dict) -> InvestmentAccountSyncPayload:
        org = raw.get("org", {}) or {}
        holdings = tuple(self._parse_holding(h) for h in raw.get("holdings", []))
        return InvestmentAccountSyncPayload(
            external_id=str(raw["id"]),
            name=str(raw.get("name", "Unnamed Account")),
            broker=str(org.get("name", "")),
            currency=str(raw.get("currency", "USD")),
            holdings=holdings,
        )

    def _parse_holding(self, raw: dict) -> HoldingData:
        shares = Decimal(str(raw.get("shares", "0")))
        price = Decimal(str(raw.get("price", "0")))
        market_value = Decimal(str(raw.get("market_value", str((shares * price).quantize(Decimal("0.01"))))))
        cost_basis_raw = raw.get("cost_basis")
        cost_basis = Decimal(str(cost_basis_raw)) if cost_basis_raw not in (None, "") else None
        return HoldingData(
            external_id=str(raw["id"]),
            symbol=str(raw.get("symbol", "")).upper(),
            description=str(raw.get("description", "")),
            shares=shares,
            current_price=price,
            market_value=market_value,
            cost_basis=cost_basis,
        )
```

Also, change the existing `fetch_accounts_with_transactions` to skip accounts that have a non-empty `holdings` array — so banking doesn't create bogus `Account` rows for brokerage accounts. Find the `for raw_account in payload.get("accounts", []):` loop in `fetch_accounts_with_transactions` and modify:

```python
        for raw_account in payload.get("accounts", []):
            if raw_account.get("holdings"):
                continue  # investment account — handled by fetch_investment_accounts
            yield self._parse_account(raw_account)
```

- [ ] **Step 2: Commit**

```bash
git add apps/providers/simplefin.py
git commit -m "feat(providers): SimpleFIN fetch_investment_accounts and bank-account filter"
```

---

## Task 9: SimpleFIN investment tests

**Files:**
- Modify: `apps/providers/tests/test_simplefin.py`

- [ ] **Step 1: Append new tests**

```python
from decimal import Decimal as _D  # reuse if already imported above; keep or dedupe


@responses.activate
def test_fetch_investment_accounts_parses_holdings():
    access_url = "https://U:T@bridge.simplefin.org/simplefin"
    responses.add(
        responses.GET,
        f"{access_url}/accounts?start-date=0",
        json={
            "errors": [],
            "accounts": [
                {
                    "id": "BANK-1", "name": "Checking", "currency": "USD", "balance": "500",
                    "org": {"name": "Chase"},
                    "transactions": [],
                },
                {
                    "id": "INV-1", "name": "Roth IRA", "currency": "USD", "balance": "10000",
                    "org": {"name": "Robinhood"},
                    "holdings": [
                        {
                            "id": "H-1", "symbol": "AAPL", "description": "Apple Inc.",
                            "shares": "10", "price": "180.00",
                            "market_value": "1800.00", "cost_basis": "1500.00",
                        },
                        {
                            "id": "H-2", "symbol": "VTI", "description": "Vanguard Total Stock",
                            "shares": "40", "price": "250.50",
                            "market_value": "10020.00",
                            # cost_basis omitted — provider may not have it
                        },
                    ],
                },
            ],
        },
        status=200,
    )

    provider = SimpleFINProvider()

    bank_payloads = list(provider.fetch_accounts_with_transactions(access_url))
    assert len(bank_payloads) == 1
    assert bank_payloads[0].account.external_id == "BANK-1"  # investment account was filtered out

    inv_payloads = list(provider.fetch_investment_accounts(access_url))
    assert len(inv_payloads) == 1
    inv = inv_payloads[0]
    assert inv.external_id == "INV-1"
    assert inv.broker == "Robinhood"
    assert len(inv.holdings) == 2

    aapl = inv.holdings[0]
    assert aapl.symbol == "AAPL"
    assert aapl.shares == Decimal("10")
    assert aapl.current_price == Decimal("180.00")
    assert aapl.market_value == Decimal("1800.00")
    assert aapl.cost_basis == Decimal("1500.00")

    vti = inv.holdings[1]
    assert vti.cost_basis is None   # provider didn't return it
```

- [ ] **Step 2: Commit**

```bash
git add apps/providers/tests/test_simplefin.py
git commit -m "test(providers): SimpleFIN investment-account parsing"
```

---

## Task 10: `PriceProvider` abstraction

**Files:**
- Create: `apps/providers/prices/__init__.py`
- Create: `apps/providers/prices/base.py`
- Create: `apps/providers/prices/registry.py`

- [ ] **Step 1: `apps/providers/prices/__init__.py`** — empty.

- [ ] **Step 2: Write `apps/providers/prices/base.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Protocol


@dataclass(frozen=True)
class PriceQuote:
    symbol: str
    price: Decimal
    at: datetime


class PriceProvider(Protocol):
    """Fetches current prices for one or more ticker symbols.

    Keep pure: no DB access. Callers are responsible for persistence.
    """

    name: str  # "yahoo", "polygon", ...

    def fetch_quotes(self, symbols: Iterable[str]) -> list[PriceQuote]:
        ...
```

- [ ] **Step 3: Write `apps/providers/prices/registry.py`**

```python
from typing import Type

from .base import PriceProvider

_REGISTRY: dict[str, Type[PriceProvider]] = {}


def register(provider_cls: Type[PriceProvider]) -> Type[PriceProvider]:
    _REGISTRY[provider_cls.name] = provider_cls
    return provider_cls


def get(name: str = "yahoo") -> PriceProvider:
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown price provider: {name!r}. Registered: {sorted(_REGISTRY)}") from exc
    return cls()
```

- [ ] **Step 4: Commit**

```bash
git add apps/providers/prices/
git commit -m "feat(providers): PriceProvider Protocol and registry subpackage"
```

---

## Task 11: Yahoo Finance price provider

**Files:**
- Create: `apps/providers/prices/yahoo.py`

`yfinance`'s `Tickers(...)` batch call is the most efficient way to fetch multiple symbols at once. We use `fast_info` for minimal network overhead.

- [ ] **Step 1: Write `apps/providers/prices/yahoo.py`**

```python
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

import yfinance as yf

from .base import PriceProvider, PriceQuote
from .registry import register


@register
class YahooFinancePriceProvider:
    name = "yahoo"

    def fetch_quotes(self, symbols: Iterable[str]) -> list[PriceQuote]:
        symbols = [s.strip().upper() for s in symbols if s and s.strip()]
        if not symbols:
            return []

        # Tickers object is batched; one HTTP round trip for all symbols.
        tickers = yf.Tickers(" ".join(symbols))
        now = datetime.now(tz=timezone.utc)
        quotes: list[PriceQuote] = []

        for symbol in symbols:
            try:
                info = tickers.tickers[symbol].fast_info
                price = info.get("last_price") or info.get("regular_market_price")
            except Exception:
                price = None
            if price is None:
                continue
            quotes.append(PriceQuote(
                symbol=symbol,
                price=Decimal(str(price)).quantize(Decimal("0.0001")),
                at=now,
            ))

        return quotes
```

- [ ] **Step 2: Wire into `apps/providers/apps.py` so the registry is populated at startup**

Add the Yahoo import to the existing `ready()` hook:

```python
    def ready(self) -> None:
        from . import simplefin  # noqa: F401
        from .prices import yahoo  # noqa: F401
```

- [ ] **Step 3: Commit**

```bash
git add apps/providers/prices/yahoo.py apps/providers/apps.py
git commit -m "feat(providers): Yahoo Finance price provider via yfinance"
```

---

## Task 12: Yahoo price-provider tests (mocked)

**Files:**
- Create: `apps/providers/tests/test_yahoo.py`

- [ ] **Step 1: Write the test**

Testing yfinance directly is painful — it relies on a session/cookie/crumb dance. We mock the `yf.Tickers` call entirely and verify our provider's parsing + quantization.

```python
from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.providers.prices.yahoo import YahooFinancePriceProvider


def _fake_ticker(price):
    t = MagicMock()
    t.fast_info = {"last_price": price}
    return t


@patch("apps.providers.prices.yahoo.yf.Tickers")
def test_fetch_quotes_maps_prices(mock_tickers_cls):
    mock_bundle = MagicMock()
    mock_bundle.tickers = {
        "AAPL": _fake_ticker(182.47),
        "MSFT": _fake_ticker(410.1),
    }
    mock_tickers_cls.return_value = mock_bundle

    quotes = YahooFinancePriceProvider().fetch_quotes(["AAPL", "msft"])  # lowercase normalized

    symbols = {q.symbol: q.price for q in quotes}
    assert symbols["AAPL"] == Decimal("182.4700")
    assert symbols["MSFT"] == Decimal("410.1000")


@patch("apps.providers.prices.yahoo.yf.Tickers")
def test_fetch_quotes_skips_unknown_symbol(mock_tickers_cls):
    t_good = _fake_ticker(100.0)
    t_bad = MagicMock()
    t_bad.fast_info = {}  # no price keys

    mock_bundle = MagicMock()
    mock_bundle.tickers = {"AAPL": t_good, "NOPE": t_bad}
    mock_tickers_cls.return_value = mock_bundle

    quotes = YahooFinancePriceProvider().fetch_quotes(["AAPL", "NOPE"])
    assert len(quotes) == 1
    assert quotes[0].symbol == "AAPL"


def test_fetch_quotes_empty_input_returns_empty():
    assert YahooFinancePriceProvider().fetch_quotes([]) == []
    assert YahooFinancePriceProvider().fetch_quotes(["", "   "]) == []
```

- [ ] **Step 2: Commit**

```bash
git add apps/providers/tests/test_yahoo.py
git commit -m "test(providers): Yahoo Finance price provider"
```

---

## Task 13: Service layer — `apps/investments/services.py`

**Files:**
- Create: `apps/investments/services.py`

Four public service functions:
- `sync_simplefin_investments(institution)` — pulls investment accounts for a linked SimpleFIN institution. Uses the same `Institution` row banking uses. Upserts `InvestmentAccount` and `Holding` rows via `external_id`. Preserves `cost_basis_source='manual'` values.
- `create_manual_account(user, broker, name, notes)` — user-entered brokerage.
- `upsert_manual_holding(investment_account, symbol, shares, cost_basis)` — user-entered position. Updates if symbol already exists on that account.
- `refresh_manual_prices(user)` — hits Yahoo Finance for every unique symbol held in manual accounts by this user, writes current_price + market_value + PortfolioSnapshot.

- [ ] **Step 1: Write `apps/investments/services.py`**

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.banking.models import Institution
from apps.providers.prices.registry import get as get_price_provider
from apps.providers.registry import get as get_provider

from .models import Holding, InvestmentAccount, PortfolioSnapshot


@dataclass
class InvestmentSyncResult:
    accounts_created: int
    accounts_updated: int
    holdings_created: int
    holdings_updated: int
    holdings_manual_basis_preserved: int


def sync_simplefin_investments(institution: Institution) -> InvestmentSyncResult:
    provider = get_provider(institution.provider)

    ac_created = ac_updated = 0
    h_created = h_updated = h_manual_preserved = 0

    with transaction.atomic():
        for payload in provider.fetch_investment_accounts(institution.access_url):
            acc, created = InvestmentAccount.objects.update_or_create(
                institution=institution,
                external_id=payload.external_id,
                defaults={
                    "user": institution.user,
                    "source": "simplefin",
                    "broker": payload.broker,
                    "name": payload.name,
                    "currency": payload.currency,
                    "last_synced_at": timezone.now(),
                },
            )
            if created:
                ac_created += 1
            else:
                ac_updated += 1

            for hd in payload.holdings:
                existing = Holding.objects.filter(
                    investment_account=acc, external_id=hd.external_id,
                ).first()

                preserve_manual_basis = bool(existing and existing.cost_basis_source == "manual")
                cost_basis = existing.cost_basis if preserve_manual_basis else hd.cost_basis
                cost_basis_source = "manual" if preserve_manual_basis else ("auto" if hd.cost_basis is not None else "auto")

                _, h_was_created = Holding.objects.update_or_create(
                    investment_account=acc,
                    external_id=hd.external_id,
                    defaults={
                        "symbol": hd.symbol,
                        "description": hd.description,
                        "shares": hd.shares,
                        "current_price": hd.current_price,
                        "market_value": hd.market_value,
                        "cost_basis": cost_basis,
                        "cost_basis_source": cost_basis_source,
                        "last_priced_at": timezone.now(),
                    },
                )
                if h_was_created:
                    h_created += 1
                else:
                    h_updated += 1
                if preserve_manual_basis:
                    h_manual_preserved += 1

            _snapshot_total(acc)

    return InvestmentSyncResult(
        accounts_created=ac_created,
        accounts_updated=ac_updated,
        holdings_created=h_created,
        holdings_updated=h_updated,
        holdings_manual_basis_preserved=h_manual_preserved,
    )


def create_manual_account(*, user, broker: str, name: str, notes: str = "") -> InvestmentAccount:
    return InvestmentAccount.objects.create(
        user=user,
        source="manual",
        broker=broker,
        name=name,
        notes=notes,
    )


def upsert_manual_holding(
    *,
    investment_account: InvestmentAccount,
    symbol: str,
    shares: Decimal,
    cost_basis: Decimal | None,
) -> Holding:
    assert investment_account.source == "manual", "upsert_manual_holding only valid for manual accounts"
    symbol = symbol.strip().upper()
    holding, _ = Holding.objects.update_or_create(
        investment_account=investment_account,
        external_id="",
        symbol=symbol,
        defaults={
            "shares": shares,
            "cost_basis": cost_basis,
            "cost_basis_source": "manual" if cost_basis is not None else "auto",
        },
    )
    holding.recompute_market_value()
    holding.save(update_fields=["market_value"])
    return holding


def update_cost_basis(*, holding: Holding, cost_basis: Decimal | None) -> Holding:
    holding.cost_basis = cost_basis
    holding.cost_basis_source = "manual" if cost_basis is not None else "auto"
    holding.save(update_fields=["cost_basis", "cost_basis_source"])
    return holding


def refresh_manual_prices(*, user) -> int:
    """Fetch Yahoo Finance prices for every manual holding symbol this user owns.
    Returns the number of holdings whose price was updated.
    """
    manual_holdings = list(
        Holding.objects
        .filter(investment_account__user=user, investment_account__source="manual")
        .select_related("investment_account")
    )
    symbols = sorted({h.symbol for h in manual_holdings if h.symbol})
    if not symbols:
        return 0

    quotes = {q.symbol: q for q in get_price_provider("yahoo").fetch_quotes(symbols)}
    now = timezone.now()
    updated = 0
    touched_accounts: set[int] = set()

    with transaction.atomic():
        for h in manual_holdings:
            quote = quotes.get(h.symbol)
            if quote is None:
                continue
            h.current_price = quote.price
            h.last_priced_at = now
            h.recompute_market_value()
            h.save(update_fields=["current_price", "market_value", "last_priced_at"])
            updated += 1
            touched_accounts.add(h.investment_account_id)

        for acc_id in touched_accounts:
            acc = InvestmentAccount.objects.get(pk=acc_id)
            _snapshot_total(acc)

    return updated


def _snapshot_total(account: InvestmentAccount) -> None:
    total = sum(
        (h.market_value for h in account.holdings.all()),
        start=Decimal("0"),
    )
    PortfolioSnapshot.objects.update_or_create(
        investment_account=account,
        date=date.today(),
        defaults={"total_value": total},
    )
```

- [ ] **Step 2: Commit**

```bash
git add apps/investments/services.py
git commit -m "feat(investments): sync, manual-entry, and price-refresh service functions"
```

---

## Task 14: Service-layer tests

**Files:**
- Create: `apps/investments/tests/test_services.py`

- [ ] **Step 1: Write the tests**

```python
from datetime import date, datetime, timezone as tz
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.banking.models import Institution
from apps.investments.models import Holding, InvestmentAccount, PortfolioSnapshot
from apps.investments.services import (
    create_manual_account, refresh_manual_prices, sync_simplefin_investments,
    update_cost_basis, upsert_manual_holding,
)
from apps.providers import registry as provider_registry
from apps.providers.base import HoldingData, InvestmentAccountSyncPayload
from apps.providers.prices import registry as price_registry
from apps.providers.prices.base import PriceQuote

User = get_user_model()


class _FakeSimpleFIN:
    name = "simplefin"

    def __init__(self, payloads):
        self._payloads = payloads

    def exchange_setup_token(self, setup_token):
        return "https://FAKE/simplefin"

    def fetch_accounts_with_transactions(self, access_url):
        return iter(())

    def fetch_investment_accounts(self, access_url):
        yield from self._payloads


class _FakePriceProvider:
    name = "yahoo"
    quotes_by_symbol: dict[str, Decimal] = {}

    def fetch_quotes(self, symbols):
        now = datetime.now(tz=tz.utc)
        return [
            PriceQuote(symbol=s.upper(), price=self.quotes_by_symbol[s.upper()], at=now)
            for s in symbols
            if s.upper() in self.quotes_by_symbol
        ]


@pytest.fixture
def fake_simplefin_single_holding():
    payloads = [
        InvestmentAccountSyncPayload(
            external_id="INV-1", name="Roth IRA", broker="Robinhood", currency="USD",
            holdings=(
                HoldingData(
                    external_id="H-1", symbol="AAPL", description="Apple",
                    shares=Decimal("10"), current_price=Decimal("180"),
                    market_value=Decimal("1800"), cost_basis=Decimal("1500"),
                ),
            ),
        ),
    ]
    original = provider_registry._REGISTRY.copy()
    provider_registry._REGISTRY["simplefin"] = lambda: _FakeSimpleFIN(payloads)
    yield
    provider_registry._REGISTRY.clear()
    provider_registry._REGISTRY.update(original)


@pytest.fixture
def fake_yahoo():
    original = price_registry._REGISTRY.copy()
    _FakePriceProvider.quotes_by_symbol = {}
    price_registry._REGISTRY["yahoo"] = _FakePriceProvider
    yield _FakePriceProvider
    price_registry._REGISTRY.clear()
    price_registry._REGISTRY.update(original)


@pytest.mark.django_db
def test_sync_simplefin_investments_creates_account_and_holdings(fake_simplefin_single_holding):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    inst = Institution.objects.create(user=user, name="Brokerage", access_url="https://FAKE")

    result = sync_simplefin_investments(inst)

    assert result.accounts_created == 1
    assert result.holdings_created == 1
    assert InvestmentAccount.objects.filter(institution=inst).count() == 1
    inv = InvestmentAccount.objects.get(institution=inst)
    assert inv.user == user
    assert inv.source == "simplefin"

    h = Holding.objects.get(investment_account=inv)
    assert h.symbol == "AAPL"
    assert h.cost_basis == Decimal("1500")
    assert h.cost_basis_source == "auto"
    # Snapshot written
    snap = PortfolioSnapshot.objects.get(investment_account=inv, date=date.today())
    assert snap.total_value == Decimal("1800")


@pytest.mark.django_db
def test_sync_preserves_manual_cost_basis(fake_simplefin_single_holding):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    inst = Institution.objects.create(user=user, name="B", access_url="https://FAKE")

    sync_simplefin_investments(inst)
    h = Holding.objects.get()
    update_cost_basis(holding=h, cost_basis=Decimal("2000"))  # user override
    assert h.cost_basis_source == "manual"

    result = sync_simplefin_investments(inst)

    h.refresh_from_db()
    assert h.cost_basis == Decimal("2000"), "Manual basis must survive sync"
    assert h.cost_basis_source == "manual"
    assert result.holdings_manual_basis_preserved == 1


@pytest.mark.django_db
def test_create_manual_account_and_holding():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    acc = create_manual_account(user=user, broker="Fidelity", name="401k")
    assert acc.source == "manual"

    h = upsert_manual_holding(
        investment_account=acc, symbol="vti",
        shares=Decimal("40"), cost_basis=Decimal("8000"),
    )
    assert h.symbol == "VTI"
    assert h.cost_basis_source == "manual"
    assert h.market_value == Decimal("0.00")  # no price yet


@pytest.mark.django_db
def test_upsert_manual_holding_updates_existing_symbol():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    acc = create_manual_account(user=user, broker="Fidelity", name="401k")
    upsert_manual_holding(investment_account=acc, symbol="VTI", shares=Decimal("40"), cost_basis=Decimal("8000"))
    upsert_manual_holding(investment_account=acc, symbol="VTI", shares=Decimal("50"), cost_basis=Decimal("9500"))

    assert Holding.objects.filter(investment_account=acc, symbol="VTI").count() == 1
    h = Holding.objects.get(investment_account=acc, symbol="VTI")
    assert h.shares == Decimal("50")
    assert h.cost_basis == Decimal("9500")


@pytest.mark.django_db
def test_refresh_manual_prices_updates_only_manual_holdings(fake_yahoo):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    acc = create_manual_account(user=user, broker="Fidelity", name="401k")
    upsert_manual_holding(investment_account=acc, symbol="VTI", shares=Decimal("40"), cost_basis=None)

    fake_yahoo.quotes_by_symbol = {"VTI": Decimal("250.00")}
    updated = refresh_manual_prices(user=user)

    assert updated == 1
    h = Holding.objects.get(symbol="VTI")
    assert h.current_price == Decimal("250.0000")
    assert h.market_value == Decimal("10000.00")
    snap = PortfolioSnapshot.objects.get(investment_account=acc, date=date.today())
    assert snap.total_value == Decimal("10000.00")
```

- [ ] **Step 2: Commit**

```bash
git add apps/investments/tests/test_services.py
git commit -m "test(investments): service-layer sync, manual upsert, price refresh"
```

---

## Task 15: URLs and views

**Files:**
- Create: `apps/investments/urls.py`
- Modify: `config/urls.py`
- Create: `apps/investments/views.py`

- [ ] **Step 1: Write `apps/investments/urls.py`**

```python
from django.urls import path

from . import views

app_name = "investments"

urlpatterns = [
    path("", views.investments_list, name="list"),
    path("accounts/add/", views.add_manual_account, name="add_account"),
    path("accounts/<int:account_id>/", views.account_detail, name="account_detail"),
    path("accounts/<int:account_id>/holdings/add/", views.add_holding, name="add_holding"),
    path("holdings/<int:holding_id>/edit/", views.edit_holding, name="edit_holding"),
    path("refresh/", views.refresh_prices, name="refresh_prices"),
    path("banks/<int:institution_id>/sync/", views.sync_investments_view, name="sync_from_bank"),
]
```

- [ ] **Step 2: Update `config/urls.py`** to include the new app — replace with:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("banks/", include("apps.banking.urls")),
    path("investments/", include("apps.investments.urls")),
    path("", include("apps.accounts.urls")),
]
```

- [ ] **Step 3: Write `apps/investments/views.py`**

```python
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.banking.models import Institution

from .models import Holding, InvestmentAccount
from .services import (
    create_manual_account, refresh_manual_prices, sync_simplefin_investments,
    update_cost_basis, upsert_manual_holding,
)


def _decimal_or_none(raw: str) -> Decimal | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"Not a valid number: {raw!r}")


@login_required
def investments_list(request):
    accounts = (
        InvestmentAccount.objects
        .for_user(request.user)
        .prefetch_related("holdings")
    )
    # Totals for the summary row
    grand_total = Decimal("0")
    for acc in accounts:
        grand_total += sum((h.market_value for h in acc.holdings.all()), Decimal("0"))
    return render(request, "investments/investments_list.html", {
        "accounts": accounts,
        "grand_total": grand_total,
    })


@login_required
def account_detail(request, account_id):
    account = get_object_or_404(InvestmentAccount.objects.for_user(request.user), pk=account_id)
    holdings = account.holdings.all().order_by("symbol")
    total_value = sum((h.market_value for h in holdings), Decimal("0"))
    total_cost = sum((h.cost_basis or Decimal("0") for h in holdings), Decimal("0"))
    total_gain = total_value - total_cost if total_cost else None
    return render(request, "investments/account_detail.html", {
        "account": account,
        "holdings": holdings,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_gain": total_gain,
    })


@login_required
@require_http_methods(["GET", "POST"])
def add_manual_account(request):
    if request.method == "POST":
        broker = request.POST.get("broker", "").strip()
        name = request.POST.get("name", "").strip()
        notes = request.POST.get("notes", "").strip()
        if not name:
            messages.error(request, "Account name is required.")
            return render(request, "investments/add_account_form.html", {"broker": broker, "name": name, "notes": notes})
        acc = create_manual_account(user=request.user, broker=broker, name=name, notes=notes)
        messages.success(request, f"Created {acc.effective_name}.")
        return HttpResponseRedirect(reverse("investments:account_detail", args=[acc.id]))
    return render(request, "investments/add_account_form.html", {})


@login_required
@require_http_methods(["GET", "POST"])
def add_holding(request, account_id):
    account = get_object_or_404(InvestmentAccount.objects.for_user(request.user), pk=account_id, source="manual")
    if request.method == "POST":
        symbol = request.POST.get("symbol", "").strip().upper()
        try:
            shares = _decimal_or_none(request.POST.get("shares", ""))
            cost_basis = _decimal_or_none(request.POST.get("cost_basis", ""))
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "investments/add_holding_form.html", {"account": account, **request.POST.dict()})
        if not symbol or shares is None:
            messages.error(request, "Symbol and shares are required.")
            return render(request, "investments/add_holding_form.html", {"account": account, **request.POST.dict()})
        upsert_manual_holding(investment_account=account, symbol=symbol, shares=shares, cost_basis=cost_basis)
        messages.success(request, f"Added {symbol} × {shares}.")
        return HttpResponseRedirect(reverse("investments:account_detail", args=[account.id]))
    return render(request, "investments/add_holding_form.html", {"account": account})


@login_required
@require_http_methods(["GET", "POST"])
def edit_holding(request, holding_id):
    holding = get_object_or_404(Holding.objects.for_user(request.user), pk=holding_id)
    account = holding.investment_account
    if request.method == "POST":
        try:
            cost_basis = _decimal_or_none(request.POST.get("cost_basis", ""))
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "investments/edit_holding_form.html", {"holding": holding})
        # Manual accounts may also edit shares; SimpleFIN accounts only edit cost_basis.
        if account.source == "manual":
            try:
                shares = _decimal_or_none(request.POST.get("shares", ""))
            except ValueError as exc:
                messages.error(request, str(exc))
                return render(request, "investments/edit_holding_form.html", {"holding": holding})
            if shares is not None:
                holding.shares = shares
                holding.recompute_market_value()
                holding.save(update_fields=["shares", "market_value"])
        update_cost_basis(holding=holding, cost_basis=cost_basis)
        messages.success(request, f"Updated {holding.symbol}.")
        return HttpResponseRedirect(reverse("investments:account_detail", args=[account.id]))
    return render(request, "investments/edit_holding_form.html", {"holding": holding})


@login_required
@require_http_methods(["POST"])
def refresh_prices(request):
    updated = refresh_manual_prices(user=request.user)
    messages.success(request, f"Refreshed prices for {updated} manual holding(s).")
    return HttpResponseRedirect(reverse("investments:list"))


@login_required
@require_http_methods(["POST"])
def sync_investments_view(request, institution_id):
    institution = get_object_or_404(Institution.objects.for_user(request.user), pk=institution_id)
    try:
        result = sync_simplefin_investments(institution)
    except Exception as exc:
        messages.error(request, f"Investment sync failed: {exc}")
    else:
        messages.success(
            request,
            f"Synced {result.accounts_created + result.accounts_updated} brokerage account(s), "
            f"{result.holdings_created} new holdings.",
        )
    return HttpResponseRedirect(reverse("investments:list"))
```

- [ ] **Step 4: Commit**

```bash
git add apps/investments/urls.py config/urls.py apps/investments/views.py
git commit -m "feat(investments): URL routes and views (list, detail, add, edit, refresh, sync)"
```

---

## Task 16: Templates

**Files:**
- Create: `apps/investments/templates/investments/investments_list.html`
- Create: `apps/investments/templates/investments/account_detail.html`
- Create: `apps/investments/templates/investments/add_account_form.html`
- Create: `apps/investments/templates/investments/add_holding_form.html`
- Create: `apps/investments/templates/investments/edit_holding_form.html`

- [ ] **Step 1: Write `investments_list.html`**

```html
{% extends "base.html" %}
{% block title %}Investments{% endblock %}
{% block content %}
<div class="flex items-center justify-between mb-6">
  <div>
    <h1 class="text-2xl font-bold">Investments</h1>
    <div class="text-slate-500 text-sm">Total: <span class="font-mono text-emerald-200">${{ grand_total|floatformat:2 }}</span></div>
  </div>
  <div class="flex gap-2">
    <form method="post" action="{% url 'investments:refresh_prices' %}" class="m-0">
      {% csrf_token %}
      <button type="submit" class="text-slate-400 hover:text-white text-sm border border-slate-700 px-3 py-2 rounded">⟳ Refresh prices</button>
    </form>
    <a href="{% url 'investments:add_account' %}" class="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-4 py-2 rounded">+ Manual account</a>
  </div>
</div>

{% if messages %}
  {% for message in messages %}
  <div class="bg-{% if message.tags == 'error' %}red-900/40 border-red-700 text-red-200{% else %}emerald-900/40 border-emerald-700 text-emerald-200{% endif %} border p-3 rounded text-sm mb-4">
    {{ message }}
  </div>
  {% endfor %}
{% endif %}

{% if not accounts %}
  <div class="bg-slate-900 border border-slate-800 rounded p-6 text-slate-400">
    No investment accounts yet. Click <strong class="text-slate-200">+ Manual account</strong> to type in a brokerage that SimpleFIN doesn't reach, or sync an existing linked bank.
  </div>
{% else %}
  <div class="space-y-4">
    {% for acc in accounts %}
    <a href="{% url 'investments:account_detail' acc.id %}" class="block bg-slate-900 border border-slate-800 rounded hover:bg-slate-800/40">
      <div class="flex items-center justify-between px-5 py-3">
        <div>
          <div class="font-semibold">{{ acc.effective_name }}</div>
          <div class="text-xs text-slate-500">{{ acc.broker|default:"" }} · {{ acc.get_source_display }}</div>
        </div>
        <div class="text-right">
          {% with total=acc.holdings.all|length %}
          <div class="text-xs text-slate-500">{{ total }} position{{ total|pluralize }}</div>
          {% endwith %}
        </div>
      </div>
    </a>
    {% endfor %}
  </div>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Write `account_detail.html`**

```html
{% extends "base.html" %}
{% block title %}{{ account.effective_name }}{% endblock %}
{% block content %}
<a href="{% url 'investments:list' %}" class="text-slate-500 hover:text-white text-sm">← Investments</a>

{% if messages %}
  {% for message in messages %}
  <div class="bg-{% if message.tags == 'error' %}red-900/40 border-red-700 text-red-200{% else %}emerald-900/40 border-emerald-700 text-emerald-200{% endif %} border p-3 rounded text-sm mt-3">
    {{ message }}
  </div>
  {% endfor %}
{% endif %}

<div class="flex items-end justify-between mt-2 mb-6">
  <div>
    <h1 class="text-2xl font-bold">{{ account.effective_name }}</h1>
    <div class="text-slate-500 text-sm">{{ account.broker|default:"" }} · {{ account.get_source_display }}</div>
  </div>
  <div class="text-right space-y-1">
    <div class="text-xs text-slate-500 uppercase tracking-wider">Market value</div>
    <div class="text-2xl font-mono text-emerald-200">${{ total_value|floatformat:2 }}</div>
    {% if total_gain is not None %}
      <div class="text-xs font-mono {% if total_gain < 0 %}text-red-300{% else %}text-emerald-400{% endif %}">
        gain/loss: {% if total_gain >= 0 %}+{% endif %}${{ total_gain|floatformat:2 }}
      </div>
    {% endif %}
  </div>
</div>

{% if account.source == 'manual' %}
<div class="mb-4">
  <a href="{% url 'investments:add_holding' account.id %}" class="text-emerald-400 hover:text-emerald-300 text-sm">+ Add holding</a>
</div>
{% endif %}

{% if not holdings %}
  <div class="bg-slate-900 border border-slate-800 rounded p-6 text-slate-400 text-sm">
    No holdings yet.
  </div>
{% else %}
  <div class="bg-slate-900 border border-slate-800 rounded overflow-hidden">
    <table class="w-full text-sm">
      <thead class="border-b border-slate-800 text-slate-500 text-xs uppercase tracking-wider">
        <tr>
          <th class="px-5 py-2 text-left">Symbol</th>
          <th class="px-5 py-2 text-right">Shares</th>
          <th class="px-5 py-2 text-right">Price</th>
          <th class="px-5 py-2 text-right">Value</th>
          <th class="px-5 py-2 text-right">Cost basis</th>
          <th class="px-5 py-2 text-right">Gain / loss</th>
          <th class="px-5 py-2"></th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-800">
        {% for h in holdings %}
        <tr>
          <td class="px-5 py-3 font-mono font-semibold">{{ h.symbol }}</td>
          <td class="px-5 py-3 text-right font-mono">{{ h.shares }}</td>
          <td class="px-5 py-3 text-right font-mono">${{ h.current_price|floatformat:2 }}</td>
          <td class="px-5 py-3 text-right font-mono">${{ h.market_value|floatformat:2 }}</td>
          <td class="px-5 py-3 text-right font-mono">
            {% if h.cost_basis is not None %}
              ${{ h.cost_basis|floatformat:2 }}
              {% if h.cost_basis_source == 'manual' %}<span class="text-amber-400 text-xs" title="Locked from sync overwrite">✋</span>{% endif %}
            {% else %}
              <span class="text-slate-600">—</span>
            {% endif %}
          </td>
          <td class="px-5 py-3 text-right font-mono {% if h.gain_loss and h.gain_loss < 0 %}text-red-300{% elif h.gain_loss %}text-emerald-400{% endif %}">
            {% if h.gain_loss is not None %}
              {% if h.gain_loss >= 0 %}+{% endif %}${{ h.gain_loss|floatformat:2 }}
              <div class="text-xs text-slate-500">{% if h.gain_loss_percent >= 0 %}+{% endif %}{{ h.gain_loss_percent|floatformat:2 }}%</div>
            {% else %}<span class="text-slate-600">—</span>{% endif %}
          </td>
          <td class="px-5 py-3 text-right">
            <a href="{% url 'investments:edit_holding' h.id %}" class="text-slate-500 hover:text-white text-sm">✎</a>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Write `add_account_form.html`**

```html
{% extends "base.html" %}
{% block title %}Add manual account{% endblock %}
{% block content %}
<div class="max-w-xl mx-auto">
  <h1 class="text-2xl font-bold mb-4">Add a manual brokerage account</h1>
  <p class="text-slate-400 text-sm mb-6">Use this for brokerages SimpleFIN can't connect to (Fidelity, 401k plans, etc.). You'll add positions next.</p>

  {% if messages %}
    {% for message in messages %}
    <div class="bg-red-900/40 border-red-700 text-red-200 border p-3 rounded text-sm mb-4">{{ message }}</div>
    {% endfor %}
  {% endif %}

  <form method="post" class="space-y-4">
    {% csrf_token %}
    <div>
      <label class="block text-sm text-slate-400 mb-1">Broker</label>
      <input name="broker" type="text" value="{{ broker|default:'' }}" placeholder="e.g., Fidelity"
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2">
    </div>
    <div>
      <label class="block text-sm text-slate-400 mb-1">Account name *</label>
      <input name="name" type="text" value="{{ name|default:'' }}" required placeholder="e.g., 401k, Roth IRA"
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2">
    </div>
    <div>
      <label class="block text-sm text-slate-400 mb-1">Notes</label>
      <textarea name="notes" rows="3" class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2">{{ notes|default:'' }}</textarea>
    </div>
    <div class="flex items-center gap-3">
      <button type="submit" class="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-5 py-2 rounded">Create</button>
      <a href="{% url 'investments:list' %}" class="text-slate-400 hover:text-white text-sm">Cancel</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 4: Write `add_holding_form.html`**

```html
{% extends "base.html" %}
{% block title %}Add holding{% endblock %}
{% block content %}
<div class="max-w-xl mx-auto">
  <a href="{% url 'investments:account_detail' account.id %}" class="text-slate-500 hover:text-white text-sm">← {{ account.effective_name }}</a>
  <h1 class="text-2xl font-bold mt-2 mb-4">Add a position</h1>

  {% if messages %}
    {% for message in messages %}
    <div class="bg-red-900/40 border-red-700 text-red-200 border p-3 rounded text-sm mb-4">{{ message }}</div>
    {% endfor %}
  {% endif %}

  <form method="post" class="space-y-4">
    {% csrf_token %}
    <div>
      <label class="block text-sm text-slate-400 mb-1">Symbol *</label>
      <input name="symbol" type="text" value="{{ symbol|default:'' }}" required
             placeholder="AAPL" autocapitalize="characters"
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 font-mono">
    </div>
    <div>
      <label class="block text-sm text-slate-400 mb-1">Shares *</label>
      <input name="shares" type="text" value="{{ shares|default:'' }}" required placeholder="10.5"
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 font-mono">
    </div>
    <div>
      <label class="block text-sm text-slate-400 mb-1">Cost basis (total, optional)</label>
      <input name="cost_basis" type="text" value="{{ cost_basis|default:'' }}" placeholder="1500.00"
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 font-mono">
      <p class="text-xs text-slate-500 mt-1">What you paid total for these shares. Leave blank if unknown.</p>
    </div>
    <div class="flex items-center gap-3">
      <button type="submit" class="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-5 py-2 rounded">Save</button>
      <a href="{% url 'investments:account_detail' account.id %}" class="text-slate-400 hover:text-white text-sm">Cancel</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 5: Write `edit_holding_form.html`**

```html
{% extends "base.html" %}
{% block title %}Edit {{ holding.symbol }}{% endblock %}
{% block content %}
<div class="max-w-xl mx-auto">
  <a href="{% url 'investments:account_detail' holding.investment_account.id %}" class="text-slate-500 hover:text-white text-sm">← {{ holding.investment_account.effective_name }}</a>
  <h1 class="text-2xl font-bold mt-2 mb-4">Edit {{ holding.symbol }}</h1>

  {% if messages %}
    {% for message in messages %}
    <div class="bg-red-900/40 border-red-700 text-red-200 border p-3 rounded text-sm mb-4">{{ message }}</div>
    {% endfor %}
  {% endif %}

  <form method="post" class="space-y-4">
    {% csrf_token %}
    {% if holding.investment_account.source == 'manual' %}
    <div>
      <label class="block text-sm text-slate-400 mb-1">Shares</label>
      <input name="shares" type="text" value="{{ holding.shares }}"
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 font-mono">
    </div>
    {% else %}
    <div class="text-xs text-slate-500">Shares are provider-managed for SimpleFIN holdings — edit cost basis only.</div>
    {% endif %}
    <div>
      <label class="block text-sm text-slate-400 mb-1">Cost basis (total)</label>
      <input name="cost_basis" type="text" value="{{ holding.cost_basis|default:'' }}"
             placeholder="1500.00"
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 font-mono">
      <p class="text-xs text-slate-500 mt-1">
        Total you paid for this position. {% if holding.cost_basis_source == 'manual' %}✋ Currently locked — sync won't overwrite.{% endif %}
        Leave blank to clear and let the provider re-populate on next sync.
      </p>
    </div>
    <div class="flex items-center gap-3">
      <button type="submit" class="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-5 py-2 rounded">Save</button>
      <a href="{% url 'investments:account_detail' holding.investment_account.id %}" class="text-slate-400 hover:text-white text-sm">Cancel</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 6: Commit**

```bash
git add apps/investments/templates/
git commit -m "feat(investments): list, detail, add-account, add-holding, edit-holding templates"
```

---

## Task 17: Activate Investments nav link

**Files:**
- Modify: `apps/accounts/templates/base.html`

- [ ] **Step 1: Find this line**:

```html
      <a href="/investments/" class="text-slate-500">Investments</a>
```

Replace with:

```html
      <a href="{% url 'investments:list' %}" class="text-slate-300 hover:text-white">Investments</a>
```

- [ ] **Step 2: Commit**

```bash
git add apps/accounts/templates/base.html
git commit -m "feat(investments): activate Investments nav link"
```

---

## Task 18: View-level tests

**Files:**
- Create: `apps/investments/tests/test_views.py`

- [ ] **Step 1: Write the tests**

```python
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.investments.models import Holding, InvestmentAccount

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
    r = alice_client.get(reverse("investments:list"))
    assert r.status_code == 200
    assert b"No investment accounts yet" in r.content


def test_list_shows_only_own_accounts(alice, bob, alice_client):
    InvestmentAccount.objects.create(user=alice, source="manual", broker="Fidelity", name="Alice 401k")
    InvestmentAccount.objects.create(user=bob, source="manual", broker="Vanguard", name="Bob IRA")
    r = alice_client.get(reverse("investments:list"))
    assert b"Alice 401k" in r.content
    assert b"Bob IRA" not in r.content


def test_add_manual_account_creates_and_redirects(alice_client):
    r = alice_client.post(reverse("investments:add_account"), {
        "broker": "Fidelity", "name": "401k", "notes": "employer match",
    })
    assert r.status_code == 302
    acc = InvestmentAccount.objects.get(name="401k")
    assert acc.source == "manual"
    assert acc.broker == "Fidelity"


def test_account_detail_hidden_from_other_user(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    r = bob_client.get(reverse("investments:account_detail", args=[acc.id]))
    assert r.status_code == 404


def test_add_holding_creates_and_redirects(alice, alice_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    r = alice_client.post(reverse("investments:add_holding", args=[acc.id]), {
        "symbol": "vti", "shares": "40", "cost_basis": "8000",
    })
    assert r.status_code == 302
    h = Holding.objects.get(investment_account=acc)
    assert h.symbol == "VTI"
    assert h.shares == Decimal("40")


def test_add_holding_rejects_for_other_users_account(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    r = bob_client.post(reverse("investments:add_holding", args=[acc.id]), {
        "symbol": "VTI", "shares": "40",
    })
    assert r.status_code == 404


def test_edit_holding_cost_basis(alice, alice_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    h = Holding.objects.create(investment_account=acc, symbol="AAPL", shares=Decimal("10"), current_price=Decimal("180"), market_value=Decimal("1800"))
    r = alice_client.post(reverse("investments:edit_holding", args=[h.id]), {
        "shares": "10", "cost_basis": "1500",
    })
    assert r.status_code == 302
    h.refresh_from_db()
    assert h.cost_basis == Decimal("1500")
    assert h.cost_basis_source == "manual"


def test_edit_holding_isolation(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="A")
    h = Holding.objects.create(investment_account=acc, symbol="AAPL", shares=Decimal("10"), current_price=Decimal("180"), market_value=Decimal("1800"))
    r = bob_client.post(reverse("investments:edit_holding", args=[h.id]), {"cost_basis": "0"})
    assert r.status_code == 404


def test_anonymous_redirects_to_login():
    c = Client()
    r = c.get(reverse("investments:list"))
    assert r.status_code == 302
    assert "/login/" in r["Location"]
```

- [ ] **Step 2: Commit**

```bash
git add apps/investments/tests/test_views.py
git commit -m "test(investments): view-level auth + isolation + happy-path flows"
```

---

## Task 19: Full suite + manual smoke test (USER)

No code changes — integration gate on the server.

- [ ] **Step 1: Pull + rebuild on server**

```bash
cd /opt/finance
git pull
docker compose build web
docker compose up -d web
docker compose exec web python manage.py makemigrations investments
docker compose cp web:/app/apps/investments/migrations/0001_initial.py apps/investments/migrations/
docker compose exec web python manage.py migrate
git add apps/investments/migrations/
git commit -m "feat(investments): initial migration"
git push
```

- [ ] **Step 2: Run the full suite**

```bash
docker compose exec web pytest -v
```

Expected: **28 (Phase 2) + ~20 (Phase 3) = ~48 passes.** If anything fails, fix before proceeding.

- [ ] **Step 3: Browser flow — manual account**

1. `/investments/` → "No investment accounts yet."
2. Click "+ Manual account" → enter Broker=Fidelity, Name=401k → create.
3. Lands on `/investments/accounts/<id>/`.
4. Click "+ Add holding" → Symbol=VTI, Shares=40, Cost basis=8000.
5. Back on detail, row shows VTI × 40, price $0 (no refresh yet), value $0, cost $8000.
6. Back to `/investments/`, click "⟳ Refresh prices". Success banner with count=1.
7. Detail page now shows a real price and market value. Gain/loss populated.

- [ ] **Step 4: Browser flow — SimpleFIN-sourced (if Robinhood works)**

1. From `/banks/`, if your linked institution has investment accounts, visit `/investments/banks/<institution_id>/sync/` (POST — add a temporary button or just curl it) OR extend the `/banks/` page to include a "Sync investments" button later.
2. Check `/investments/` — should list the new account with SimpleFIN-sourced holdings.
3. Edit a cost basis, then sync again → cost basis survives (because `cost_basis_source=manual`).

- [ ] **Step 5: Isolation check**

Log in as `dad` in a private window → `/investments/` shows nothing. Your manual 401k invisible.

- [ ] **Step 6: No commit — verification only.**

---

## Phase 3 Definition of Done

- [ ] `docker compose exec web pytest -v` reports all ~48 tests passing.
- [ ] `/investments/` renders for a logged-in user with their accounts and grand total.
- [ ] A manual investment account can be created, have holdings added, and prices refreshed from Yahoo Finance.
- [ ] Cost basis edits persist and survive a subsequent sync of the same institution.
- [ ] `dad` cannot see `mohamed`'s investments (isolation).
- [ ] Yahoo Finance quote refresh updates `market_value` + `last_priced_at` and writes a `PortfolioSnapshot` row for today.
- [ ] The Investments nav link is live.

When all green, Phase 3 ships. Next: Phase 4 — gold/manual assets via the accbullion.com scraper.
