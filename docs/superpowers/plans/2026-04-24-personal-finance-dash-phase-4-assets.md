# Personal Finance Dashboard — Phase 4: Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `/assets/` page where the user tracks anything that isn't a bank account or brokerage position — gold coins, cars, art, cash at home, collectibles. Two flavors:
- **Scraped** — URL + optional CSS selector; per-unit price is pulled on refresh, total = price × quantity.
- **Manual** — user types a total value directly; it sits stable until the user updates it.

**Architecture:** One `apps/assets/` app, one `Asset` model with a `kind` field discriminating scraped vs manual. No global-product table — every asset is per-user (if two users own the same coin, they each add a row; one extra HTTP request on refresh, negligible for v1). Scraper abstraction mirrors the price-provider layout in `apps/providers/prices/` — new `apps/providers/scrapers/` subpackage with `PriceScraper` Protocol + `CSSSelectorScraper` impl. Delete is included in this phase (small scope; nice to have for user-typed data).

**Tech Stack:** Adds `beautifulsoup4==4.12.3` and `lxml==5.3.0` for HTML parsing. Scraping via `requests` (already installed).

**Non-Goals for Phase 4:**
- Daily auto-refresh (Phase 5 host crontab).
- Global/shared products — every asset belongs to one user, even if multiple users own the same thing.
- Sector / category / tag taxonomy.
- Value history chart (we snapshot values, but UI renders later).
- Buy/sell transaction log per asset.

---

## File Structure

```
finance/
├── apps/
│   ├── assets/                    # NEW
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── admin.py
│   │   ├── models.py              # Asset, AssetPriceSnapshot
│   │   ├── managers.py            # AssetQuerySet with for_user()
│   │   ├── services.py            # create/update/refresh/delete
│   │   ├── urls.py
│   │   ├── views.py
│   │   ├── migrations/
│   │   │   └── __init__.py
│   │   ├── tests/
│   │   │   ├── __init__.py
│   │   │   ├── test_isolation.py
│   │   │   ├── test_services.py
│   │   │   ├── test_scraper.py
│   │   │   └── test_views.py
│   │   └── templates/assets/
│   │       ├── assets_list.html
│   │       ├── asset_form.html          # shared for add + edit
│   │       └── asset_confirm_delete.html
│   └── providers/
│       ├── apps.py                # MODIFIED: import scraper on ready()
│       └── scrapers/              # NEW
│           ├── __init__.py
│           ├── base.py            # PriceScraper Protocol + ScrapedPrice dataclass
│           ├── registry.py        # name → class
│           └── css.py             # CSSSelectorScraper
```

---

## Task 1: Dependencies

**Files:** Modify `requirements.txt`

- [ ] **Step 1: Append to `requirements.txt`**

```
beautifulsoup4==4.12.3
lxml==5.3.0
```

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "chore(assets): add beautifulsoup4 + lxml for HTML scraping"
```

---

## Task 2: `apps/assets/` skeleton

**Files:**
- Create: `apps/assets/__init__.py`
- Create: `apps/assets/apps.py`
- Create: `apps/assets/migrations/__init__.py`
- Modify: `config/settings.py`

- [ ] **Step 1: `apps/assets/__init__.py`** — empty.

- [ ] **Step 2: `apps/assets/apps.py`**

```python
from django.apps import AppConfig


class AssetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.assets"
    label = "assets"
```

- [ ] **Step 3: `apps/assets/migrations/__init__.py`** — empty.

- [ ] **Step 4: Update `INSTALLED_APPS`** in `config/settings.py` — add `"apps.assets",` after `"apps.investments",`. Final relevant block:

```python
    "apps.accounts",
    "apps.banking",
    "apps.investments",
    "apps.assets",
    "apps.providers",
```

- [ ] **Step 5: Commit**

```bash
git add apps/assets/ config/settings.py
git commit -m "feat(assets): add assets app skeleton and register it"
```

---

## Task 3: Manager (UserScopedQuerySet)

**Files:** Create `apps/assets/managers.py`

- [ ] **Step 1: Write file**

```python
from apps.banking.managers import UserScopedQuerySet


class AssetQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(user=user)


class AssetPriceSnapshotQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(asset__user=user)
```

- [ ] **Step 2: Commit**

```bash
git add apps/assets/managers.py
git commit -m "feat(assets): UserScoped QuerySet subclasses"
```

---

## Task 4: Models

**Files:** Create `apps/assets/models.py`

Design notes:
- `kind` discriminator: `"scraped"` for URL-based assets, `"manual"` for user-typed values.
- **Single `current_value` field** holds the total (quantity × per-unit for scraped, user-entered for manual). Simpler than tracking unit prices separately in the DB.
- `last_priced_at` is always populated — on refresh for scraped, on save for manual.
- `AssetPriceSnapshot` records history (one row per refresh/save) — unused in Phase 4 UI but cheap to populate for future charting.

- [ ] **Step 1: Write `apps/assets/models.py`**

```python
from decimal import Decimal

from django.conf import settings
from django.db import models

from .managers import AssetPriceSnapshotQuerySet, AssetQuerySet


class Asset(models.Model):
    """A user-tracked asset. Either scraped from a URL or manually valued."""

    KIND_CHOICES = [
        ("scraped", "Scraped from URL"),
        ("manual", "Manual value"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assets")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    name = models.CharField(max_length=200)
    notes = models.TextField(blank=True, default="")

    # Quantity is meaningful for scraped (multiplied by per-unit scrape), ignored for manual.
    quantity = models.DecimalField(max_digits=16, decimal_places=6, default=Decimal("1"))
    unit = models.CharField(max_length=20, blank=True, default="", help_text="'oz', 'each', etc. Optional.")

    # Scraped-only fields.
    source_url = models.URLField(blank=True, default="")
    css_selector = models.CharField(max_length=500, blank=True, default="",
                                     help_text="Optional. Blank = auto-detect first $-prefixed price on the page.")

    # Current total value. For scraped: last_scraped_unit_price × quantity. For manual: user-entered directly.
    current_value = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0"))
    last_priced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AssetQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_kind_display()})"


class AssetPriceSnapshot(models.Model):
    """Daily (or on-refresh) value record. Enables history charts later; unused in Phase 4 UI."""
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="snapshots")
    at = models.DateTimeField(db_index=True)
    value = models.DecimalField(max_digits=18, decimal_places=2)

    objects = AssetPriceSnapshotQuerySet.as_manager()

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"{self.asset_id} @ {self.at:%Y-%m-%d}: {self.value}"
```

- [ ] **Step 2: Commit**

```bash
git add apps/assets/models.py
git commit -m "feat(assets): Asset + AssetPriceSnapshot models"
```

---

## Task 5: Isolation test

**Files:**
- Create: `apps/assets/tests/__init__.py`
- Create: `apps/assets/tests/test_isolation.py`

- [ ] **Step 1: `apps/assets/tests/__init__.py`** — empty.

- [ ] **Step 2: Write `apps/assets/tests/test_isolation.py`**

```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.assets.models import Asset, AssetPriceSnapshot

User = get_user_model()


@pytest.fixture
def two_users_with_assets(db):
    alice = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    bob = User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")

    alice_gold = Asset.objects.create(
        user=alice, kind="scraped", name="1oz Gold Eagle",
        source_url="https://example.com/gold", quantity=Decimal("3"),
        current_value=Decimal("6000"),
    )
    alice_car = Asset.objects.create(
        user=alice, kind="manual", name="Alice's car",
        current_value=Decimal("18000"),
    )
    bob_art = Asset.objects.create(
        user=bob, kind="manual", name="Bob's painting",
        current_value=Decimal("5000"),
    )

    AssetPriceSnapshot.objects.create(asset=alice_gold, at=datetime(2026, 4, 24, tzinfo=timezone.utc), value=Decimal("6000"))
    AssetPriceSnapshot.objects.create(asset=bob_art, at=datetime(2026, 4, 24, tzinfo=timezone.utc), value=Decimal("5000"))

    return alice, bob, alice_gold, alice_car, bob_art


def test_asset_for_user_isolates(two_users_with_assets):
    alice, bob, *_ = two_users_with_assets
    assert set(Asset.objects.for_user(alice).values_list("name", flat=True)) == {"1oz Gold Eagle", "Alice's car"}
    assert list(Asset.objects.for_user(bob).values_list("name", flat=True)) == ["Bob's painting"]


def test_snapshot_for_user_isolates(two_users_with_assets):
    alice, bob, *_ = two_users_with_assets
    assert AssetPriceSnapshot.objects.for_user(alice).count() == 1
    assert AssetPriceSnapshot.objects.for_user(bob).count() == 1
```

- [ ] **Step 3: Commit**

```bash
git add apps/assets/tests/
git commit -m "test(assets): isolation test"
```

---

## Task 6: Django admin

**Files:** Create `apps/assets/admin.py`

- [ ] **Step 1: Write file**

```python
from django.contrib import admin

from .models import Asset, AssetPriceSnapshot


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "user", "quantity", "unit", "current_value", "last_priced_at")
    list_filter = ("kind", "user")
    search_fields = ("name", "notes", "source_url", "user__username")
    readonly_fields = ("created_at", "last_priced_at")


@admin.register(AssetPriceSnapshot)
class AssetPriceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("at", "asset", "value")
    list_filter = ("asset__user",)
    date_hierarchy = "at"
```

- [ ] **Step 2: Commit**

```bash
git add apps/assets/admin.py
git commit -m "feat(assets): admin registration"
```

---

## Task 7: Scraper subpackage

**Files:**
- Create: `apps/providers/scrapers/__init__.py`
- Create: `apps/providers/scrapers/base.py`
- Create: `apps/providers/scrapers/registry.py`

- [ ] **Step 1: `apps/providers/scrapers/__init__.py`** — empty.

- [ ] **Step 2: Write `apps/providers/scrapers/base.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class ScrapedPrice:
    source_url: str
    price: Decimal
    at: datetime
    raw_text: str = ""  # the matched text, for debugging


class PriceScraper(Protocol):
    """Fetches a single price from a URL. Keep pure: no DB, no model imports."""
    name: str  # "css", ...

    def fetch(self, url: str, selector: str = "") -> ScrapedPrice:
        ...
```

- [ ] **Step 3: Write `apps/providers/scrapers/registry.py`**

```python
from typing import Type

from .base import PriceScraper

_REGISTRY: dict[str, Type[PriceScraper]] = {}


def register(cls: Type[PriceScraper]) -> Type[PriceScraper]:
    _REGISTRY[cls.name] = cls
    return cls


def get(name: str = "css") -> PriceScraper:
    try:
        return _REGISTRY[name]()
    except KeyError as exc:
        raise ValueError(f"Unknown scraper: {name!r}. Registered: {sorted(_REGISTRY)}") from exc
```

- [ ] **Step 4: Commit**

```bash
git add apps/providers/scrapers/
git commit -m "feat(providers): PriceScraper Protocol + registry subpackage"
```

---

## Task 8: `CSSSelectorScraper`

**Files:**
- Create: `apps/providers/scrapers/css.py`
- Modify: `apps/providers/apps.py` (register on ready)

Scrape logic:
1. HTTP GET the URL (with a browser-ish User-Agent to avoid basic bot blocks).
2. Parse with BeautifulSoup.
3. If selector provided: `soup.select_one(selector)` → extract text.
4. If no match or no selector: run heuristics — search elements with `price` / `current-price` / `amount` in class for the first `$X.XX`. Fallback: search full page text.
5. Parse the first dollar-prefixed number into a Decimal.
6. Raise `RuntimeError` if nothing found (service layer catches and surfaces via `messages`).

- [ ] **Step 1: Write `apps/providers/scrapers/css.py`**

```python
import re
from datetime import datetime, timezone
from decimal import Decimal

import requests
from bs4 import BeautifulSoup

from .base import PriceScraper, ScrapedPrice
from .registry import register

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_PRICE_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
_HEURISTIC_CLASS_HINTS = ("current-price", "price-current", "product-price", "price", "amount")


@register
class CSSSelectorScraper:
    name = "css"

    def __init__(self, http: requests.Session | None = None, timeout: float = 20.0) -> None:
        self._http = http or requests.Session()
        self._timeout = timeout

    def fetch(self, url: str, selector: str = "") -> ScrapedPrice:
        response = self._http.get(url, headers={"User-Agent": _USER_AGENT}, timeout=self._timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        text, match = self._extract(soup, selector)
        if match is None:
            raise RuntimeError(f"No $-prefixed price found at {url} (selector={selector!r})")

        price_str = match.group(1).replace(",", "")
        return ScrapedPrice(
            source_url=url,
            price=Decimal(price_str),
            at=datetime.now(tz=timezone.utc),
            raw_text=text[:200],
        )

    def _extract(self, soup: BeautifulSoup, selector: str) -> tuple[str, re.Match | None]:
        # 1. Explicit selector
        if selector:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(" ", strip=True)
                match = _PRICE_RE.search(text)
                if match:
                    return text, match

        # 2. Heuristic: elements with price-like class names
        for hint in _HEURISTIC_CLASS_HINTS:
            for element in soup.select(f"[class*={hint}]"):
                text = element.get_text(" ", strip=True)
                match = _PRICE_RE.search(text)
                if match:
                    return text, match

        # 3. Last resort: full page
        text = soup.get_text(" ", strip=True)
        return text, _PRICE_RE.search(text)
```

- [ ] **Step 2: Modify `apps/providers/apps.py` to import the scraper at app-ready**

Existing ready() imports simplefin and yahoo. Add the scraper:

```python
    def ready(self) -> None:
        from . import simplefin  # noqa: F401
        from .prices import yahoo  # noqa: F401
        from .scrapers import css  # noqa: F401
```

- [ ] **Step 3: Commit**

```bash
git add apps/providers/scrapers/css.py apps/providers/apps.py
git commit -m "feat(providers): CSSSelectorScraper with explicit-selector → heuristic → full-page fallback"
```

---

## Task 9: Scraper tests

**Files:** Create `apps/providers/tests/test_scraper.py`

- [ ] **Step 1: Write the file**

```python
from decimal import Decimal

import pytest
import responses

from apps.providers.scrapers.css import CSSSelectorScraper


_HTML_WITH_EXPLICIT_PRICE = """
<!doctype html>
<html><body>
  <div class="product-price"><span class="amount">$2,734.50</span></div>
</body></html>
"""

_HTML_NO_MATCHING_SELECTOR_BUT_HEURISTIC = """
<!doctype html>
<html><body>
  <div class="some-wrapper"><span class="price">Our price: $1,099.99</span></div>
</body></html>
"""

_HTML_ONLY_FULL_PAGE = """
<!doctype html>
<html><body>
  <p>Shipping from $9.99 and available for $87.42 today only.</p>
</body></html>
"""

_HTML_NO_PRICE = "<html><body><p>Out of stock</p></body></html>"


@responses.activate
def test_scraper_uses_explicit_selector_when_given():
    responses.add(responses.GET, "https://example.com/p1", body=_HTML_WITH_EXPLICIT_PRICE, status=200)
    got = CSSSelectorScraper().fetch("https://example.com/p1", selector=".product-price .amount")
    assert got.price == Decimal("2734.50")
    assert got.source_url == "https://example.com/p1"


@responses.activate
def test_scraper_falls_back_to_heuristic_when_no_selector():
    responses.add(responses.GET, "https://example.com/p2", body=_HTML_NO_MATCHING_SELECTOR_BUT_HEURISTIC, status=200)
    got = CSSSelectorScraper().fetch("https://example.com/p2")
    assert got.price == Decimal("1099.99")


@responses.activate
def test_scraper_last_resort_full_page_text():
    responses.add(responses.GET, "https://example.com/p3", body=_HTML_ONLY_FULL_PAGE, status=200)
    got = CSSSelectorScraper().fetch("https://example.com/p3")
    # First $-match is $9.99
    assert got.price == Decimal("9.99")


@responses.activate
def test_scraper_raises_when_no_price_anywhere():
    responses.add(responses.GET, "https://example.com/p4", body=_HTML_NO_PRICE, status=200)
    with pytest.raises(RuntimeError, match="No \\$-prefixed price"):
        CSSSelectorScraper().fetch("https://example.com/p4")


@responses.activate
def test_scraper_handles_comma_thousands():
    responses.add(responses.GET, "https://example.com/p5",
                  body='<div class="price">$12,345.67</div>', status=200)
    got = CSSSelectorScraper().fetch("https://example.com/p5")
    assert got.price == Decimal("12345.67")
```

- [ ] **Step 2: Commit**

```bash
git add apps/providers/tests/test_scraper.py
git commit -m "test(providers): CSSSelectorScraper covers explicit, heuristic, fallback, failure"
```

---

## Task 10: Service layer

**Files:** Create `apps/assets/services.py`

- [ ] **Step 1: Write the file**

```python
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.providers.scrapers.registry import get as get_scraper

from .models import Asset, AssetPriceSnapshot


@dataclass
class RefreshResult:
    updated: int
    failed: list[tuple[int, str]]  # [(asset_id, error_message)]


def create_asset(*, user, kind: str, name: str, **fields) -> Asset:
    """fields may include: notes, quantity, unit, source_url, css_selector, current_value."""
    asset = Asset(user=user, kind=kind, name=name, **{k: v for k, v in fields.items() if v is not None})
    asset.save()
    _snapshot(asset)
    return asset


def update_asset(asset: Asset, **fields) -> Asset:
    """Update mutable fields on an existing asset. For manual assets, supply current_value;
    for scraped, supply source_url / css_selector / quantity / unit. ``kind`` is immutable."""
    for field, value in fields.items():
        if field == "kind":
            continue
        setattr(asset, field, value)
    asset.last_priced_at = timezone.now() if asset.kind == "manual" else asset.last_priced_at
    asset.save()
    if asset.kind == "manual":
        _snapshot(asset)
    return asset


def refresh_scraped_assets(*, user) -> RefreshResult:
    """Hit every scraped asset's URL for this user; update current_value + snapshot."""
    assets = list(Asset.objects.for_user(user).filter(kind="scraped"))
    scraper = get_scraper("css")
    updated = 0
    failed: list[tuple[int, str]] = []

    with transaction.atomic():
        for a in assets:
            if not a.source_url:
                failed.append((a.id, "no source_url"))
                continue
            try:
                result = scraper.fetch(a.source_url, selector=a.css_selector or "")
            except Exception as exc:
                failed.append((a.id, str(exc)))
                continue
            a.current_value = (result.price * a.quantity).quantize(Decimal("0.01"))
            a.last_priced_at = result.at
            a.save(update_fields=["current_value", "last_priced_at"])
            _snapshot(a)
            updated += 1

    return RefreshResult(updated=updated, failed=failed)


def delete_asset(asset: Asset) -> None:
    asset.delete()


def _snapshot(asset: Asset) -> None:
    AssetPriceSnapshot.objects.create(asset=asset, at=timezone.now(), value=asset.current_value)
```

- [ ] **Step 2: Commit**

```bash
git add apps/assets/services.py
git commit -m "feat(assets): create, update, refresh, delete service functions"
```

---

## Task 11: Service tests

**Files:** Create `apps/assets/tests/test_services.py`

- [ ] **Step 1: Write the file**

```python
from datetime import datetime, timezone as tz
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.assets.models import Asset, AssetPriceSnapshot
from apps.assets.services import (
    create_asset, delete_asset, refresh_scraped_assets, update_asset,
)
from apps.providers.scrapers import registry as scraper_registry
from apps.providers.scrapers.base import ScrapedPrice

User = get_user_model()


class _FakeScraper:
    name = "css"
    prices_by_url: dict[str, Decimal] = {}
    errors_by_url: dict[str, str] = {}

    def fetch(self, url: str, selector: str = ""):
        if url in self.errors_by_url:
            raise RuntimeError(self.errors_by_url[url])
        return ScrapedPrice(
            source_url=url, price=self.prices_by_url[url], at=datetime.now(tz=tz.utc),
        )


@pytest.fixture
def fake_scraper():
    original = scraper_registry._REGISTRY.copy()
    _FakeScraper.prices_by_url = {}
    _FakeScraper.errors_by_url = {}
    scraper_registry._REGISTRY["css"] = _FakeScraper
    yield _FakeScraper
    scraper_registry._REGISTRY.clear()
    scraper_registry._REGISTRY.update(original)


@pytest.mark.django_db
def test_create_manual_asset_records_snapshot():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(user=user, kind="manual", name="Car", current_value=Decimal("18000"))
    assert a.current_value == Decimal("18000")
    assert AssetPriceSnapshot.objects.filter(asset=a).count() == 1


@pytest.mark.django_db
def test_create_scraped_asset_stores_url_and_quantity():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(
        user=user, kind="scraped", name="Gold Eagle",
        source_url="https://example.com/gold", quantity=Decimal("3"), unit="oz",
    )
    assert a.source_url == "https://example.com/gold"
    assert a.quantity == Decimal("3")
    assert a.unit == "oz"


@pytest.mark.django_db
def test_update_manual_asset_snapshots_new_value():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(user=user, kind="manual", name="Car", current_value=Decimal("18000"))
    update_asset(a, current_value=Decimal("16500"))
    a.refresh_from_db()
    assert a.current_value == Decimal("16500")
    assert AssetPriceSnapshot.objects.filter(asset=a).count() == 2


@pytest.mark.django_db
def test_refresh_scraped_hits_url_and_multiplies_by_quantity(fake_scraper):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(
        user=user, kind="scraped", name="Gold Eagle",
        source_url="https://example.com/gold", quantity=Decimal("3"),
    )
    fake_scraper.prices_by_url = {"https://example.com/gold": Decimal("2734.50")}

    result = refresh_scraped_assets(user=user)

    assert result.updated == 1
    assert result.failed == []
    a.refresh_from_db()
    assert a.current_value == Decimal("8203.50")  # 2734.50 × 3


@pytest.mark.django_db
def test_refresh_skips_manual_assets(fake_scraper):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    create_asset(user=user, kind="manual", name="Car", current_value=Decimal("18000"))
    result = refresh_scraped_assets(user=user)
    assert result.updated == 0
    assert result.failed == []


@pytest.mark.django_db
def test_refresh_records_failure_without_breaking_others(fake_scraper):
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a_good = create_asset(
        user=user, kind="scraped", name="OK",
        source_url="https://good.example/", quantity=Decimal("1"),
    )
    a_bad = create_asset(
        user=user, kind="scraped", name="BAD",
        source_url="https://bad.example/", quantity=Decimal("1"),
    )
    fake_scraper.prices_by_url = {"https://good.example/": Decimal("100")}
    fake_scraper.errors_by_url = {"https://bad.example/": "boom"}

    result = refresh_scraped_assets(user=user)

    assert result.updated == 1
    assert len(result.failed) == 1
    assert result.failed[0][0] == a_bad.id
    a_good.refresh_from_db()
    assert a_good.current_value == Decimal("100.00")


@pytest.mark.django_db
def test_delete_asset_cascades_snapshots():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    a = create_asset(user=user, kind="manual", name="X", current_value=Decimal("1"))
    update_asset(a, current_value=Decimal("2"))
    assert AssetPriceSnapshot.objects.filter(asset=a).count() == 2
    delete_asset(a)
    assert AssetPriceSnapshot.objects.count() == 0
```

- [ ] **Step 2: Commit**

```bash
git add apps/assets/tests/test_services.py
git commit -m "test(assets): service layer — create/update/refresh/delete"
```

---

## Task 12: URLs + views

**Files:**
- Create: `apps/assets/urls.py`
- Modify: `config/urls.py`
- Create: `apps/assets/views.py`

- [ ] **Step 1: Write `apps/assets/urls.py`**

```python
from django.urls import path

from . import views

app_name = "assets"

urlpatterns = [
    path("", views.assets_list, name="list"),
    path("add/", views.add_asset, name="add"),
    path("<int:asset_id>/edit/", views.edit_asset, name="edit"),
    path("<int:asset_id>/delete/", views.delete_asset_view, name="delete"),
    path("refresh/", views.refresh_prices, name="refresh"),
]
```

- [ ] **Step 2: Replace `config/urls.py`**

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("banks/", include("apps.banking.urls")),
    path("investments/", include("apps.investments.urls")),
    path("assets/", include("apps.assets.urls")),
    path("", include("apps.accounts.urls")),
]
```

- [ ] **Step 3: Write `apps/assets/views.py`**

```python
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import Asset
from .services import create_asset, delete_asset, refresh_scraped_assets, update_asset


def _decimal_or_default(raw: str, default: Decimal) -> Decimal:
    raw = (raw or "").strip()
    if not raw:
        return default
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"Not a valid number: {raw!r}")


@login_required
def assets_list(request):
    assets = Asset.objects.for_user(request.user)
    total = sum((a.current_value for a in assets), Decimal("0"))
    return render(request, "assets/assets_list.html", {
        "assets": assets,
        "total": total,
    })


@login_required
@require_http_methods(["GET", "POST"])
def add_asset(request):
    if request.method == "POST":
        kind = request.POST.get("kind", "manual")
        name = request.POST.get("name", "").strip()
        notes = request.POST.get("notes", "").strip()

        if not name:
            messages.error(request, "Name is required.")
            return render(request, "assets/asset_form.html", {"mode": "add", "data": request.POST})

        try:
            if kind == "scraped":
                source_url = request.POST.get("source_url", "").strip()
                css_selector = request.POST.get("css_selector", "").strip()
                unit = request.POST.get("unit", "").strip()
                quantity = _decimal_or_default(request.POST.get("quantity", ""), Decimal("1"))
                if not source_url:
                    messages.error(request, "URL is required for scraped assets.")
                    return render(request, "assets/asset_form.html", {"mode": "add", "data": request.POST})
                asset = create_asset(
                    user=request.user, kind="scraped", name=name, notes=notes,
                    source_url=source_url, css_selector=css_selector, unit=unit, quantity=quantity,
                )
                # Immediate first scrape so the user sees a value on return
                refresh_scraped_assets(user=request.user)
                messages.success(request, f"Added {name}. Refresh ran — check the list for the value.")
            else:
                current_value = _decimal_or_default(request.POST.get("current_value", ""), Decimal("0"))
                asset = create_asset(
                    user=request.user, kind="manual", name=name, notes=notes,
                    current_value=current_value,
                )
                messages.success(request, f"Added {name}.")
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "assets/asset_form.html", {"mode": "add", "data": request.POST})

        return HttpResponseRedirect(reverse("assets:list"))

    return render(request, "assets/asset_form.html", {"mode": "add", "data": {"kind": "manual"}})


@login_required
@require_http_methods(["GET", "POST"])
def edit_asset(request, asset_id):
    asset = get_object_or_404(Asset.objects.for_user(request.user), pk=asset_id)
    if request.method == "POST":
        fields = {"name": request.POST.get("name", "").strip(),
                  "notes": request.POST.get("notes", "").strip()}
        try:
            if asset.kind == "scraped":
                fields["source_url"] = request.POST.get("source_url", "").strip()
                fields["css_selector"] = request.POST.get("css_selector", "").strip()
                fields["unit"] = request.POST.get("unit", "").strip()
                fields["quantity"] = _decimal_or_default(request.POST.get("quantity", ""), asset.quantity)
            else:
                fields["current_value"] = _decimal_or_default(
                    request.POST.get("current_value", ""), asset.current_value
                )
            update_asset(asset, **fields)
            messages.success(request, f"Updated {asset.name}.")
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "assets/asset_form.html", {"mode": "edit", "asset": asset, "data": request.POST})
        return HttpResponseRedirect(reverse("assets:list"))

    return render(request, "assets/asset_form.html", {"mode": "edit", "asset": asset, "data": {
        "kind": asset.kind, "name": asset.name, "notes": asset.notes, "quantity": asset.quantity,
        "unit": asset.unit, "source_url": asset.source_url, "css_selector": asset.css_selector,
        "current_value": asset.current_value,
    }})


@login_required
@require_http_methods(["GET", "POST"])
def delete_asset_view(request, asset_id):
    asset = get_object_or_404(Asset.objects.for_user(request.user), pk=asset_id)
    if request.method == "POST":
        name = asset.name
        delete_asset(asset)
        messages.success(request, f"Deleted {name}.")
        return HttpResponseRedirect(reverse("assets:list"))
    return render(request, "assets/asset_confirm_delete.html", {"asset": asset})


@login_required
@require_http_methods(["POST"])
def refresh_prices(request):
    result = refresh_scraped_assets(user=request.user)
    if result.failed:
        messages.warning(request, f"Refreshed {result.updated}; {len(result.failed)} failed.")
        for asset_id, err in result.failed:
            messages.error(request, f"Asset {asset_id}: {err}")
    else:
        messages.success(request, f"Refreshed {result.updated} scraped asset(s).")
    return HttpResponseRedirect(reverse("assets:list"))
```

- [ ] **Step 4: Commit**

```bash
git add apps/assets/urls.py apps/assets/views.py config/urls.py
git commit -m "feat(assets): URL routes + list/add/edit/delete/refresh views"
```

---

## Task 13: Templates + activate nav

**Files:**
- Create: `apps/assets/templates/assets/assets_list.html`
- Create: `apps/assets/templates/assets/asset_form.html`
- Create: `apps/assets/templates/assets/asset_confirm_delete.html`
- Modify: `apps/accounts/templates/base.html`

- [ ] **Step 1: `apps/assets/templates/assets/assets_list.html`**

```html
{% extends "base.html" %}
{% block title %}Assets{% endblock %}
{% block content %}
<div class="flex items-center justify-between mb-6">
  <div>
    <h1 class="text-2xl font-bold">Assets</h1>
    <div class="text-slate-500 text-sm">Total: <span class="font-mono text-emerald-200">${{ total|floatformat:2 }}</span></div>
  </div>
  <div class="flex gap-2">
    <form method="post" action="{% url 'assets:refresh' %}" class="m-0">
      {% csrf_token %}
      <button type="submit" class="text-slate-400 hover:text-white text-sm border border-slate-700 px-3 py-2 rounded">⟳ Refresh prices</button>
    </form>
    <a href="{% url 'assets:add' %}" class="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-4 py-2 rounded">+ Add</a>
  </div>
</div>

{% if messages %}
  {% for message in messages %}
  <div class="bg-{% if message.tags == 'error' %}red-900/40 border-red-700 text-red-200{% elif message.tags == 'warning' %}amber-900/40 border-amber-700 text-amber-200{% else %}emerald-900/40 border-emerald-700 text-emerald-200{% endif %} border p-3 rounded text-sm mb-4">
    {{ message }}
  </div>
  {% endfor %}
{% endif %}

{% if not assets %}
  <div class="bg-slate-900 border border-slate-800 rounded p-6 text-slate-400">
    No assets tracked yet. Click <strong class="text-slate-200">+ Add</strong> to track gold, art, cars, cash, or anything else.
  </div>
{% else %}
  <div class="bg-slate-900 border border-slate-800 rounded overflow-hidden">
    <table class="w-full text-sm">
      <thead class="border-b border-slate-800 text-slate-500 text-xs uppercase tracking-wider">
        <tr>
          <th class="px-5 py-2 w-10"></th>
          <th class="px-5 py-2 text-left">Name</th>
          <th class="px-5 py-2 text-right">Qty</th>
          <th class="px-5 py-2 text-right">Value</th>
          <th class="px-5 py-2 text-right">Updated</th>
          <th class="px-5 py-2"></th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-800">
        {% for a in assets %}
        <tr>
          <td class="px-5 py-3 text-center">{% if a.kind == 'scraped' %}📈{% else %}✎{% endif %}</td>
          <td class="px-5 py-3">
            <div class="font-medium">{{ a.name }}</div>
            {% if a.notes %}<div class="text-xs text-slate-500">{{ a.notes }}</div>{% endif %}
          </td>
          <td class="px-5 py-3 text-right font-mono text-slate-400">
            {% if a.kind == 'scraped' %}{{ a.quantity }} {{ a.unit }}{% else %}—{% endif %}
          </td>
          <td class="px-5 py-3 text-right font-mono text-emerald-200">${{ a.current_value|floatformat:2 }}</td>
          <td class="px-5 py-3 text-right text-xs text-slate-500">
            {% if a.last_priced_at %}{{ a.last_priced_at|date:"M j" }}{% else %}never{% endif %}
          </td>
          <td class="px-5 py-3 text-right whitespace-nowrap">
            <a href="{% url 'assets:edit' a.id %}" class="text-slate-500 hover:text-white text-sm">✎</a>
            <a href="{% url 'assets:delete' a.id %}" class="text-slate-600 hover:text-red-400 text-sm ml-2">🗑</a>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: `apps/assets/templates/assets/asset_form.html`**

```html
{% extends "base.html" %}
{% block title %}{% if mode == 'edit' %}Edit {{ asset.name }}{% else %}Add asset{% endif %}{% endblock %}
{% block content %}
<div class="max-w-xl mx-auto">
  <a href="{% url 'assets:list' %}" class="text-slate-500 hover:text-white text-sm">← Assets</a>
  <h1 class="text-2xl font-bold mt-2 mb-6">{% if mode == 'edit' %}Edit {{ asset.name }}{% else %}Add an asset{% endif %}</h1>

  {% if messages %}
    {% for message in messages %}
    <div class="bg-red-900/40 border-red-700 text-red-200 border p-3 rounded text-sm mb-4">{{ message }}</div>
    {% endfor %}
  {% endif %}

  <form method="post" class="space-y-4">
    {% csrf_token %}

    {% if mode != 'edit' %}
    <div class="bg-slate-900 border border-slate-800 rounded p-4">
      <div class="text-sm text-slate-400 mb-2">What kind of asset?</div>
      <label class="flex items-center gap-2 mb-1">
        <input type="radio" name="kind" value="scraped" {% if data.kind == 'scraped' %}checked{% endif %} onclick="toggleKind()">
        <span>📈 Scraped from a URL (gold coins, commodities)</span>
      </label>
      <label class="flex items-center gap-2">
        <input type="radio" name="kind" value="manual" {% if data.kind != 'scraped' %}checked{% endif %} onclick="toggleKind()">
        <span>✎ Manual value (car, art, cash, anything you value yourself)</span>
      </label>
    </div>
    {% else %}
    <input type="hidden" name="kind" value="{{ asset.kind }}">
    <div class="text-xs text-slate-500">{% if asset.kind == 'scraped' %}📈 Scraped{% else %}✎ Manual{% endif %} (kind can't be changed after creation)</div>
    {% endif %}

    <div>
      <label class="block text-sm text-slate-400 mb-1">Name *</label>
      <input name="name" type="text" required value="{{ data.name|default:'' }}"
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2"
             placeholder="e.g. 1oz Gold Eagle, 2019 Camry, Cash at home">
    </div>

    <div id="scraped-fields" class="space-y-4" style="display:{% if data.kind == 'scraped' %}block{% else %}none{% endif %}">
      <div>
        <label class="block text-sm text-slate-400 mb-1">URL *</label>
        <input name="source_url" type="url" value="{{ data.source_url|default:'' }}"
               class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2"
               placeholder="https://accbullion.com/...">
      </div>
      <div>
        <label class="block text-sm text-slate-400 mb-1">CSS selector (optional)</label>
        <input name="css_selector" type="text" value="{{ data.css_selector|default:'' }}"
               class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 font-mono text-xs"
               placeholder=".product-price .amount — or leave blank for auto-detect">
        <p class="text-xs text-slate-500 mt-1">Blank = scraper searches the page for the first <code>$X.XX</code>.</p>
      </div>
      <div class="flex gap-2">
        <div class="flex-1">
          <label class="block text-sm text-slate-400 mb-1">Quantity</label>
          <input name="quantity" type="text" value="{{ data.quantity|default:'1' }}"
                 class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 font-mono">
        </div>
        <div class="flex-1">
          <label class="block text-sm text-slate-400 mb-1">Unit</label>
          <input name="unit" type="text" value="{{ data.unit|default:'' }}" placeholder="oz / each"
                 class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2">
        </div>
      </div>
    </div>

    <div id="manual-fields" class="space-y-4" style="display:{% if data.kind != 'scraped' %}block{% else %}none{% endif %}">
      <div>
        <label class="block text-sm text-slate-400 mb-1">Total value *</label>
        <input name="current_value" type="text" value="{{ data.current_value|default:'' }}" placeholder="18000.00"
               class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 font-mono">
      </div>
    </div>

    <div>
      <label class="block text-sm text-slate-400 mb-1">Notes</label>
      <textarea name="notes" rows="2"
                class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2">{{ data.notes|default:'' }}</textarea>
    </div>

    <div class="flex items-center gap-3 pt-2">
      <button type="submit" class="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-5 py-2 rounded">Save</button>
      <a href="{% url 'assets:list' %}" class="text-slate-400 hover:text-white text-sm">Cancel</a>
    </div>
  </form>

  <script>
    function toggleKind() {
      var scraped = document.querySelector('input[name="kind"][value="scraped"]').checked;
      document.getElementById('scraped-fields').style.display = scraped ? 'block' : 'none';
      document.getElementById('manual-fields').style.display = scraped ? 'none' : 'block';
    }
  </script>
</div>
{% endblock %}
```

- [ ] **Step 3: `apps/assets/templates/assets/asset_confirm_delete.html`**

```html
{% extends "base.html" %}
{% block title %}Delete {{ asset.name }}{% endblock %}
{% block content %}
<div class="max-w-md mx-auto mt-10">
  <h1 class="text-2xl font-bold mb-4">Delete "{{ asset.name }}"?</h1>
  <p class="text-slate-400 text-sm mb-6">
    This also removes its price history. This can't be undone.
  </p>
  <form method="post" class="flex items-center gap-3">
    {% csrf_token %}
    <button type="submit" class="bg-red-600 hover:bg-red-500 text-white font-bold px-5 py-2 rounded">Delete</button>
    <a href="{% url 'assets:list' %}" class="text-slate-400 hover:text-white text-sm">Cancel</a>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 4: Modify `apps/accounts/templates/base.html`**

Find this line:
```html
      <a href="/assets/" class="text-slate-500">Assets</a>
```

Replace with:
```html
      <a href="{% url 'assets:list' %}" class="text-slate-300 hover:text-white">Assets</a>
```

- [ ] **Step 5: Commit**

```bash
git add apps/assets/templates/ apps/accounts/templates/base.html
git commit -m "feat(assets): templates + activate Assets nav link"
```

---

## Task 14: View tests

**Files:** Create `apps/assets/tests/test_views.py`

- [ ] **Step 1: Write the file**

```python
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.assets.models import Asset

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
    r = alice_client.get(reverse("assets:list"))
    assert r.status_code == 200
    assert b"No assets tracked yet" in r.content


def test_list_shows_only_own(alice, bob, alice_client):
    Asset.objects.create(user=alice, kind="manual", name="Alice's car", current_value=Decimal("18000"))
    Asset.objects.create(user=bob, kind="manual", name="Bob's painting", current_value=Decimal("5000"))
    r = alice_client.get(reverse("assets:list"))
    assert b"Alice's car" in r.content
    assert b"Bob's painting" not in r.content


def test_add_manual_asset(alice_client):
    r = alice_client.post(reverse("assets:add"), {
        "kind": "manual", "name": "2019 Camry", "current_value": "18000", "notes": "KBB",
    })
    assert r.status_code == 302
    a = Asset.objects.get(name="2019 Camry")
    assert a.kind == "manual"
    assert a.current_value == Decimal("18000")


def test_add_scraped_asset_triggers_initial_refresh(alice_client):
    with patch("apps.assets.views.refresh_scraped_assets") as mock_refresh:
        from apps.assets.services import RefreshResult
        mock_refresh.return_value = RefreshResult(updated=1, failed=[])
        r = alice_client.post(reverse("assets:add"), {
            "kind": "scraped", "name": "Gold Eagle",
            "source_url": "https://example.com/gold", "quantity": "3", "unit": "oz",
        })
    assert r.status_code == 302
    a = Asset.objects.get(name="Gold Eagle")
    assert a.kind == "scraped"
    assert a.source_url == "https://example.com/gold"
    mock_refresh.assert_called_once()


def test_add_scraped_without_url_fails(alice_client):
    r = alice_client.post(reverse("assets:add"), {
        "kind": "scraped", "name": "X", "quantity": "1",
    })
    # 200 = re-rendered form with error, not a redirect
    assert r.status_code == 200
    assert Asset.objects.filter(name="X").count() == 0


def test_edit_updates_manual_value(alice, alice_client):
    a = Asset.objects.create(user=alice, kind="manual", name="Car", current_value=Decimal("18000"))
    r = alice_client.post(reverse("assets:edit", args=[a.id]), {
        "name": "Car", "current_value": "16500", "notes": "",
    })
    assert r.status_code == 302
    a.refresh_from_db()
    assert a.current_value == Decimal("16500")


def test_edit_hidden_from_other_user(alice, bob, bob_client):
    a = Asset.objects.create(user=alice, kind="manual", name="X", current_value=Decimal("1"))
    r = bob_client.post(reverse("assets:edit", args=[a.id]), {"name": "pwned", "current_value": "0"})
    assert r.status_code == 404


def test_delete_flow(alice, alice_client):
    a = Asset.objects.create(user=alice, kind="manual", name="X", current_value=Decimal("1"))
    r = alice_client.post(reverse("assets:delete", args=[a.id]))
    assert r.status_code == 302
    assert Asset.objects.filter(pk=a.id).count() == 0


def test_delete_forbidden_for_other_user(alice, bob, bob_client):
    a = Asset.objects.create(user=alice, kind="manual", name="X", current_value=Decimal("1"))
    r = bob_client.post(reverse("assets:delete", args=[a.id]))
    assert r.status_code == 404
    assert Asset.objects.filter(pk=a.id).count() == 1


def test_anonymous_redirects():
    c = Client()
    r = c.get(reverse("assets:list"))
    assert r.status_code == 302
    assert "/login/" in r["Location"]
```

- [ ] **Step 2: Commit**

```bash
git add apps/assets/tests/test_views.py
git commit -m "test(assets): view-level auth + isolation + add/edit/delete flows"
```

---

## Task 15: USER smoke test

No code changes — integration gate on the server.

- [ ] **Step 1: Pull, rebuild, migrate on the server**

```bash
cd /opt/finance
git pull
docker compose build web
docker compose up -d web
docker compose exec web python manage.py makemigrations assets
docker compose exec web ls apps/assets/migrations/
docker compose cp web:/app/apps/assets/migrations/0001_initial.py apps/assets/migrations/
docker compose exec web python manage.py migrate
git add apps/assets/migrations/
git commit -m "feat(assets): initial migration"
git push
```

- [ ] **Step 2: Run full test suite**

```bash
docker compose exec web pytest -v
```

Expected: **~48 (Phase 3) + ~19 (Phase 4) = ~67 passes.**

- [ ] **Step 3: Browser — manual asset**

1. `/assets/` → "No assets tracked yet"
2. **+ Add** → radio "Manual" → Name="2019 Camry", Total value="18000", Notes="KBB July 2026" → Save
3. Row appears with ✎ icon, value $18,000, updated "today"

- [ ] **Step 4: Browser — scraped asset**

1. **+ Add** → radio "Scraped" → Name="1oz Gold Eagle", URL="https://accbullion.com/..." (or any public product page), leave selector blank, Quantity=3, Unit="oz" → Save
2. Success banner; row appears with 📈 icon and a scraped value
3. If the value is wrong, click ✎ and provide a specific CSS selector — save and click **⟳ Refresh prices** to re-scrape
4. If scrape completely fails, an error flash shows the reason

- [ ] **Step 5: Refresh + edit + delete**

1. Click **⟳ Refresh prices** on `/assets/` — the scraped row updates; the manual row doesn't move
2. Click ✎ on the Camry → change value to 16500 → save
3. Click 🗑 on a test asset → confirm page → Delete → it's gone

- [ ] **Step 6: Isolation**

Log in as `dad` in a private window → `/assets/` empty.

- [ ] **Step 7: No commit — verification only.**

---

## Phase 4 Definition of Done

- [ ] `docker compose exec web pytest -v` reports ~67 tests passing.
- [ ] `/assets/` renders for a logged-in user with summary + rows.
- [ ] Adding a manual asset persists the value and shows on the list.
- [ ] Adding a scraped asset triggers an immediate fetch; value appears.
- [ ] Refresh button updates only scraped assets.
- [ ] Edit works for both kinds; delete works with a confirm page.
- [ ] `dad` can't see `mohamed`'s assets (isolation).
- [ ] Assets nav link is live.

When all green, Phase 4 ships. Next: **Phase 5 — dashboard + nightly sync via host crontab + backups + delete buttons for Institution / Account / InvestmentAccount.**
