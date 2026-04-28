# Teller Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Teller.io as a peer bank-aggregation provider alongside SimpleFIN, with mTLS auth, a Teller Connect widget link flow, and a chooser page that routes to either provider.

**Architecture:** New `TellerProvider` in `apps/providers/teller.py` implementing the existing `FinancialProvider` Protocol. The `Institution.provider` column is already plumbed through; both providers run concurrently. Link form at `/banking/link/` becomes a chooser that routes to provider-specific subpages. The `FinancialProvider` Protocol gains an optional `since` kwarg so Teller can paginate incrementally without leaking DB state into the provider layer (one small spec refinement, see "Deviation from spec" below).

**Tech Stack:** Django 5.1, requests (with `Session.cert` for mTLS), responses (test mocking), Teller Connect JS SDK from CDN, Postgres, Docker Compose.

## Deviation from spec

The spec calls for incremental syncs to paginate "stopping per account once we've seen 30 consecutive transactions whose external_id already exists in the DB for that account." Implementing that cleanly requires either pre-loading every existing transaction ID into memory and passing the set to the provider, or leaking DB queries into the provider layer (which is supposed to be pure per the comment in `apps/providers/base.py`).

**Replaced with:** a `since: datetime | None` kwarg on `fetch_accounts_with_transactions`. The service layer computes `since = institution.last_synced_at - timedelta(days=30)` (a 30-day overlap window for catching late-posting and pending → posted transitions) and passes it. Teller paginates via `from_id` until it hits a transaction older than `since`. SimpleFIN accepts and ignores the kwarg (it returns all transactions in one call regardless). On first sync, `since=None` means paginate fully back through history.

This is strictly simpler to implement, simpler to test, and provides equivalent practical coverage: bank transactions almost never post more than 30 days late.

---

## File Structure

**Created:**
- `apps/providers/teller.py` — `TellerProvider` class
- `apps/providers/tests/test_teller.py` — 3 unit tests
- `apps/banking/templates/banking/link_chooser.html` — provider chooser page
- `apps/banking/templates/banking/link_form_teller.html` — Teller-specific link page with embedded Connect widget
- `apps/banking/migrations/0004_alter_institution_provider.py` — auto-generated, adds "teller" to choices
- `secrets/teller/.gitkeep` — placeholder so the bind-mount target exists in the repo

**Modified:**
- `apps/banking/models.py` — add "teller" to `PROVIDER_CHOICES`
- `apps/banking/views.py` — split `link_form` into `link_form` (chooser), `link_form_simplefin`, `link_form_teller`, `link_form_teller_callback`
- `apps/banking/urls.py` — add new URL routes
- `apps/banking/services.py` — pass `since` to provider in `sync_institution`
- `apps/banking/management/commands/sync_all.py` — filter SimpleFIN-investments loop to `provider="simplefin"`
- `apps/providers/base.py` — extend `FinancialProvider.fetch_accounts_with_transactions` Protocol with optional `since` kwarg
- `apps/providers/simplefin.py` — accept and ignore `since` kwarg (signature compatibility only)
- `apps/providers/tests/test_simplefin.py` — delete `test_fetch_investment_accounts_handles_robinhood_style_payload`
- `apps/banking/tests/test_services.py` — add `since=None` kwarg to `_FakeProvider.fetch_accounts_with_transactions` signature
- `apps/banking/templates/banking/link_form.html` — keep as-is, will continue to render under the renamed `link_form_simplefin` view (no template change needed)
- `config/settings.py` — read `TELLER_*` env vars
- `compose.yml` — add `./secrets/teller:/run/secrets/teller:ro` volume mount on `web`
- `.env.example` — add four Teller env vars
- `.gitignore` — add `secrets/teller/*` (the existing `*.pem`/`*.key` already covers files; add directory exclusion for safety)
- `README.md` — Teller setup section

---

## Task 1: Add `teller` to provider choices and generate migration

**Files:**
- Modify: `apps/banking/models.py:13-19`
- Create: `apps/banking/migrations/0004_alter_institution_provider.py` (auto-generated)

- [ ] **Step 1: Update `PROVIDER_CHOICES`**

In `apps/banking/models.py`, replace lines 13-19 with:

```python
class Institution(models.Model):
    """One Access URL or token per row. May back multiple Accounts."""

    PROVIDER_CHOICES = [
        ("simplefin", "SimpleFIN"),
        ("teller", "Teller"),
    ]
```

- [ ] **Step 2: Generate the migration**

Run: `docker compose exec web python manage.py makemigrations banking`

Expected output: `Migrations for 'banking': apps/banking/migrations/0004_alter_institution_provider.py - Alter field provider on institution`

- [ ] **Step 3: Verify migration content**

Run: `cat apps/banking/migrations/0004_alter_institution_provider.py`

Expected: a single `AlterField` operation on `Institution.provider` adding `("teller", "Teller")` to the choices list. No data migration; existing rows keep `provider="simplefin"`.

- [ ] **Step 4: Run migration**

Run: `docker compose exec web python manage.py migrate banking`

Expected: `Applying banking.0004_alter_institution_provider... OK`

- [ ] **Step 5: Run banking tests to confirm nothing broke**

Run: `docker compose exec web pytest apps/banking/ -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/banking/models.py apps/banking/migrations/0004_alter_institution_provider.py
git commit -m "feat(banking): add 'teller' to Institution.PROVIDER_CHOICES"
```

---

## Task 2: Configuration — env vars, Docker volume, gitignore

**Files:**
- Modify: `.env.example`
- Modify: `config/settings.py`
- Modify: `compose.yml`
- Modify: `.gitignore`
- Create: `secrets/teller/.gitkeep`

- [ ] **Step 1: Append Teller env vars to `.env.example`**

Append to the end of `.env.example`:

```
# --- Teller (mTLS bank aggregation) ---
# Sign up at https://teller.io to get an application ID and a sandbox/dev cert pair.
# Drop the cert + key PEM files in ./secrets/teller/ on the host; they get mounted
# read-only into the container at /run/secrets/teller/.
# Environment values: "sandbox" (fake banks/data, free), "development" (real banks,
# free up to 100 enrollments), or "production" (paid).
TELLER_APPLICATION_ID=
TELLER_ENVIRONMENT=sandbox
TELLER_CERT_PATH=/run/secrets/teller/cert.pem
TELLER_KEY_PATH=/run/secrets/teller/key.pem
```

- [ ] **Step 2: Read Teller env vars in `config/settings.py`**

Append to the very end of `config/settings.py` (after the `FIELD_ENCRYPTION_KEY = ...` line):

```python
# --- Teller ---
# Empty/unset values are tolerated at import time; the TellerProvider will
# raise at construction time if the user actually tries to link a Teller
# account without configuring these. Lets the rest of the app boot without
# Teller credentials (e.g. for SimpleFIN-only deployments).
TELLER_APPLICATION_ID = os.environ.get("TELLER_APPLICATION_ID", "")
TELLER_ENVIRONMENT = os.environ.get("TELLER_ENVIRONMENT", "sandbox")
TELLER_CERT_PATH = os.environ.get("TELLER_CERT_PATH", "")
TELLER_KEY_PATH = os.environ.get("TELLER_KEY_PATH", "")
```

- [ ] **Step 3: Add Teller volume mount to `compose.yml`**

In `compose.yml`, modify the `web` service `volumes` section (currently `- ./backups:/backups`):

```yaml
    volumes:
      - ./backups:/backups
      - ./secrets/teller:/run/secrets/teller:ro
```

- [ ] **Step 4: Update `.gitignore`**

Add to `.gitignore` after the `*.key` line:

```
# Teller mTLS certs (also covered by *.pem / *.key but be explicit)
secrets/teller/*
!secrets/teller/.gitkeep
```

- [ ] **Step 5: Create the bind-mount target directory**

Run: `mkdir -p secrets/teller && touch secrets/teller/.gitkeep`

This ensures the directory exists in the repo (so the Docker bind mount has a target on a fresh checkout) without committing actual cert files.

- [ ] **Step 6: Commit**

```bash
git add .env.example config/settings.py compose.yml .gitignore secrets/teller/.gitkeep
git commit -m "feat(teller): add env vars, Docker mount, and secrets dir"
```

---

## Task 3: Extend `FinancialProvider` Protocol with `since` kwarg

**Files:**
- Modify: `apps/providers/base.py:65-80`
- Modify: `apps/providers/simplefin.py:54`
- Modify: `apps/banking/tests/test_services.py:39`

- [ ] **Step 1: Update the Protocol signature**

In `apps/providers/base.py`, replace the `fetch_accounts_with_transactions` method declaration on the `FinancialProvider` Protocol class (lines 69-71) with:

```python
    def fetch_accounts_with_transactions(
        self, access_url: str, *, since: "datetime | None" = None,
    ) -> Iterable[AccountSyncPayload]:
        """Pull every account + its recent transactions in one call.

        `since`, when provided, is a hint to providers that support incremental
        pagination (e.g. Teller's `from_id`) — they may stop fetching transactions
        older than this datetime. Providers that fetch all data in one call
        (e.g. SimpleFIN) accept and ignore the kwarg. None means "fetch everything".
        """
        ...
```

Add to the imports at the top of `apps/providers/base.py` (line 2 area) — `datetime` is already imported.

- [ ] **Step 2: Update SimpleFIN's signature to accept the kwarg**

In `apps/providers/simplefin.py`, replace line 54:

```python
    def fetch_accounts_with_transactions(
        self, access_url: str, *, since: "datetime | None" = None,
    ) -> Iterable[AccountSyncPayload]:
        # SimpleFIN returns all available transactions in one call; `since` is ignored.
```

The body (lines 55-70) stays unchanged.

- [ ] **Step 3: Update `_FakeProvider` in `test_services.py`**

In `apps/banking/tests/test_services.py:39`, replace:

```python
    def fetch_accounts_with_transactions(self, access_url: str):
        yield from self._payloads
```

with:

```python
    def fetch_accounts_with_transactions(self, access_url: str, *, since=None):
        yield from self._payloads
```

- [ ] **Step 4: Run all banking + provider tests**

Run: `docker compose exec web pytest apps/banking/ apps/providers/ -q`

Expected: all tests pass. The Protocol/signature change is backward-compatible for callers because `since` defaults to None.

- [ ] **Step 5: Commit**

```bash
git add apps/providers/base.py apps/providers/simplefin.py apps/banking/tests/test_services.py
git commit -m "feat(providers): add optional 'since' kwarg to fetch_accounts_with_transactions"
```

---

## Task 4: Pass `since` from `sync_institution`

**Files:**
- Modify: `apps/banking/services.py:34-104`

- [ ] **Step 1: Add timedelta import**

In `apps/banking/services.py`, change the imports near the top:

```python
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.providers.registry import get as get_provider

from .models import Account, Institution, Transaction
```

- [ ] **Step 2: Compute `since` and pass it to the provider**

In `apps/banking/services.py:sync_institution`, modify the body to compute `since` and pass it:

```python
def sync_institution(institution: Institution) -> SyncResult:
    """Fetch fresh data from the provider and upsert accounts + transactions."""
    provider = get_provider(institution.provider)

    # 30-day overlap on incremental syncs catches late-posting transactions and
    # reconciles pending → posted transitions. None on first sync = full backfill.
    since = None
    if institution.last_synced_at is not None:
        since = institution.last_synced_at - timedelta(days=30)

    accounts_created = accounts_updated = 0
    transactions_created = transactions_updated = 0

    with transaction.atomic():
        for payload in provider.fetch_accounts_with_transactions(
            institution.access_url, since=since,
        ):
            # ... rest unchanged ...
```

Only the `since=None` block (5 lines) and the `for payload in provider.fetch_accounts_with_transactions(institution.access_url, since=since):` line (changed from `institution.access_url` only) are new. The rest of the function body is unchanged.

- [ ] **Step 3: Run banking tests to confirm nothing broke**

Run: `docker compose exec web pytest apps/banking/tests/test_services.py -v`

Expected: all 6 tests pass. The fake provider already accepts `since=None` from Task 3.

- [ ] **Step 4: Commit**

```bash
git add apps/banking/services.py
git commit -m "feat(banking): compute and pass 'since' to providers on incremental sync"
```

---

## Task 5: TellerProvider scaffold with `exchange_setup_token` (TDD)

**Files:**
- Create: `apps/providers/teller.py`
- Create: `apps/providers/tests/test_teller.py`

- [ ] **Step 1: Write the first failing test**

Create `apps/providers/tests/test_teller.py` with:

```python
import base64
from decimal import Decimal

import pytest
import responses

from apps.providers.teller import TellerProvider


@pytest.fixture
def teller_settings(settings, tmp_path):
    """Stub TELLER_CERT_PATH/TELLER_KEY_PATH to real (empty) files so requests.Session.cert
    assignment doesn't fail. The HTTP layer is mocked by `responses`, so the cert
    is never actually used during these tests."""
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("dummy")
    key.write_text("dummy")
    settings.TELLER_CERT_PATH = str(cert)
    settings.TELLER_KEY_PATH = str(key)
    return settings


@responses.activate
def test_exchange_setup_token_returns_token_unchanged_on_success(teller_settings):
    """Teller has no token-exchange step; we validate the access token by calling
    GET /accounts and return the token verbatim on a 200."""
    access_token = "test_TELLER_ACCESS_TOKEN_abc"
    responses.add(
        responses.GET,
        "https://api.teller.io/accounts",
        json=[],
        status=200,
    )

    got = TellerProvider().exchange_setup_token(access_token)

    assert got == access_token
    assert len(responses.calls) == 1
    # Verify the Basic auth header was set with token + ":"
    auth = responses.calls[0].request.headers["Authorization"]
    expected = "Basic " + base64.b64encode(f"{access_token}:".encode()).decode()
    assert auth == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web pytest apps/providers/tests/test_teller.py -v`

Expected: ImportError or `ModuleNotFoundError: No module named 'apps.providers.teller'`.

- [ ] **Step 3: Create the minimal `TellerProvider`**

Create `apps/providers/teller.py` with:

```python
import base64
from typing import Iterable

import requests
from django.conf import settings

from .base import (
    AccountSyncPayload, FinancialProvider, InvestmentAccountSyncPayload,
)
from .registry import register


@register
class TellerProvider:
    name = "teller"

    def __init__(self, http: requests.Session | None = None, timeout: float = 30.0) -> None:
        self._http = http or requests.Session()
        if settings.TELLER_CERT_PATH and settings.TELLER_KEY_PATH:
            self._http.cert = (settings.TELLER_CERT_PATH, settings.TELLER_KEY_PATH)
        self._timeout = timeout
        self._base = "https://api.teller.io"

    def _auth_header(self, access_token: str) -> dict[str, str]:
        encoded = base64.b64encode(f"{access_token}:".encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def exchange_setup_token(self, setup_token: str) -> str:
        """For Teller, the 'setup token' is already the long-lived access token
        (Connect hands it back via `onSuccess`). We validate it by calling
        GET /accounts. Returns the token unchanged on success."""
        response = self._http.get(
            f"{self._base}/accounts",
            headers=self._auth_header(setup_token),
            timeout=self._timeout,
        )
        if response.status_code == 401:
            raise ValueError("Teller rejected the access token.")
        response.raise_for_status()
        return setup_token

    def fetch_accounts_with_transactions(
        self, access_url: str, *, since=None,
    ) -> Iterable[AccountSyncPayload]:
        # Implemented in Task 6.
        return iter(())

    def fetch_investment_accounts(self, access_url: str) -> Iterable[InvestmentAccountSyncPayload]:
        # Teller has no investments API.
        return iter(())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose exec web pytest apps/providers/tests/test_teller.py::test_exchange_setup_token_returns_token_unchanged_on_success -v`

Expected: PASS.

- [ ] **Step 5: Add the 401 test**

Append to `apps/providers/tests/test_teller.py`:

```python
@responses.activate
def test_exchange_setup_token_raises_on_401(teller_settings):
    responses.add(
        responses.GET,
        "https://api.teller.io/accounts",
        json={"error": {"code": "invalid_credentials", "message": "Bad token"}},
        status=401,
    )

    with pytest.raises(ValueError, match="Teller rejected the access token"):
        TellerProvider().exchange_setup_token("bad_token")
```

- [ ] **Step 6: Run the new test to verify it passes**

Run: `docker compose exec web pytest apps/providers/tests/test_teller.py -v`

Expected: 2 PASS.

- [ ] **Step 7: Verify TellerProvider is in the registry**

Run: `docker compose exec web python -c "from apps.providers.registry import get; print(get('teller').name)"`

Expected: `teller`

- [ ] **Step 8: Commit**

```bash
git add apps/providers/teller.py apps/providers/tests/test_teller.py
git commit -m "feat(providers): TellerProvider scaffold with token validation"
```

---

## Task 6: Implement `fetch_accounts_with_transactions` happy path (TDD)

**Files:**
- Modify: `apps/providers/teller.py`
- Modify: `apps/providers/tests/test_teller.py`

- [ ] **Step 1: Add the failing happy-path test**

Append to `apps/providers/tests/test_teller.py`:

```python
@responses.activate
def test_fetch_accounts_with_transactions_parses_payload(teller_settings):
    """One checking account, one balance call, one transactions page (no pagination)."""
    access_token = "test_TOKEN"

    # GET /accounts → one account
    responses.add(
        responses.GET,
        "https://api.teller.io/accounts",
        json=[
            {
                "id": "acc_test_1",
                "name": "Joint Checking",
                "type": "depository",
                "subtype": "checking",
                "currency": "USD",
                "institution": {"id": "ins_chase", "name": "Chase"},
                "links": {
                    "balances": "https://api.teller.io/accounts/acc_test_1/balances",
                    "transactions": "https://api.teller.io/accounts/acc_test_1/transactions",
                },
            },
        ],
        status=200,
    )

    # GET /accounts/{id}/balances → ledger balance
    responses.add(
        responses.GET,
        "https://api.teller.io/accounts/acc_test_1/balances",
        json={"account_id": "acc_test_1", "ledger": "1234.56", "available": "1200.00"},
        status=200,
    )

    # GET /accounts/{id}/transactions → one transaction, no more pages
    responses.add(
        responses.GET,
        "https://api.teller.io/accounts/acc_test_1/transactions",
        json=[
            {
                "id": "txn_test_1",
                "account_id": "acc_test_1",
                "date": "2026-04-15",
                "amount": "-42.18",
                "description": "Starbucks Coffee",
                "details": {
                    "processing_status": "complete",
                    "counterparty": {"name": "Starbucks", "type": "merchant"},
                },
            },
        ],
        status=200,
    )

    payloads = list(TellerProvider().fetch_accounts_with_transactions(access_token))

    assert len(payloads) == 1
    p = payloads[0]
    assert p.account.external_id == "acc_test_1"
    assert p.account.name == "Joint Checking"
    assert p.account.type == "checking"   # mapped from Teller subtype
    assert p.account.balance == Decimal("1234.56")
    assert p.account.currency == "USD"
    assert p.account.org_name == "Chase"

    assert len(p.transactions) == 1
    t = p.transactions[0]
    assert t.external_id == "txn_test_1"
    assert t.amount == Decimal("-42.18")
    assert t.description == "Starbucks Coffee"
    assert t.payee == "Starbucks"
    assert t.memo == ""
    assert t.pending is False
    # Date with no timestamp → midnight UTC
    assert t.posted_at.year == 2026 and t.posted_at.month == 4 and t.posted_at.day == 15
    assert t.posted_at.hour == 0 and t.posted_at.minute == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec web pytest apps/providers/tests/test_teller.py::test_fetch_accounts_with_transactions_parses_payload -v`

Expected: FAIL — current implementation returns `iter(())` so the assertion `len(payloads) == 1` fails with `assert 0 == 1`.

- [ ] **Step 3: Implement the method**

Replace the placeholder `fetch_accounts_with_transactions` in `apps/providers/teller.py` (and add helpers and imports). The full updated file should be:

```python
import base64
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Iterable

import requests
from django.conf import settings

from .base import (
    AccountData, AccountSyncPayload, FinancialProvider, HoldingData,
    InvestmentAccountSyncPayload, TransactionData,
)
from .registry import register

# Teller's `subtype` field maps directly to our Account.type values.
_TELLER_SUBTYPE_MAP = {
    "checking": "checking",
    "savings": "savings",
    "credit_card": "credit",
    "mortgage": "loan",
    "auto_loan": "loan",
    "student_loan": "loan",
    "personal_loan": "loan",
}


def _map_subtype(subtype: str) -> str:
    return _TELLER_SUBTYPE_MAP.get(subtype, "other")


@register
class TellerProvider:
    name = "teller"

    def __init__(self, http: requests.Session | None = None, timeout: float = 30.0) -> None:
        self._http = http or requests.Session()
        if settings.TELLER_CERT_PATH and settings.TELLER_KEY_PATH:
            self._http.cert = (settings.TELLER_CERT_PATH, settings.TELLER_KEY_PATH)
        self._timeout = timeout
        self._base = "https://api.teller.io"

    def _auth_header(self, access_token: str) -> dict[str, str]:
        encoded = base64.b64encode(f"{access_token}:".encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def exchange_setup_token(self, setup_token: str) -> str:
        """For Teller, the 'setup token' is already the long-lived access token
        (Connect hands it back via `onSuccess`). We validate it by calling
        GET /accounts. Returns the token unchanged on success."""
        response = self._http.get(
            f"{self._base}/accounts",
            headers=self._auth_header(setup_token),
            timeout=self._timeout,
        )
        if response.status_code == 401:
            raise ValueError("Teller rejected the access token.")
        response.raise_for_status()
        return setup_token

    def fetch_accounts_with_transactions(
        self, access_url: str, *, since: "datetime | None" = None,
    ) -> Iterable[AccountSyncPayload]:
        access_token = access_url   # For Teller, the "URL" stored is the access token.
        headers = self._auth_header(access_token)

        accounts_resp = self._http.get(
            f"{self._base}/accounts", headers=headers, timeout=self._timeout,
        )
        accounts_resp.raise_for_status()

        for raw_account in accounts_resp.json():
            yield self._fetch_one_account(raw_account, headers, since)

    def _fetch_one_account(
        self, raw_account: dict, headers: dict[str, str], since: "datetime | None",
    ) -> AccountSyncPayload:
        account_id = raw_account["id"]

        # Balance is on a separate endpoint.
        bal_resp = self._http.get(
            f"{self._base}/accounts/{account_id}/balances",
            headers=headers, timeout=self._timeout,
        )
        bal_resp.raise_for_status()
        balance = Decimal(str(bal_resp.json().get("ledger", "0")))

        institution = raw_account.get("institution") or {}
        account = AccountData(
            external_id=str(account_id),
            name=str(raw_account.get("name", "Unnamed Account")),
            type=_map_subtype(str(raw_account.get("subtype", ""))),
            balance=balance,
            currency=str(raw_account.get("currency", "USD")),
            org_name=str(institution.get("name", "")),
        )

        transactions = tuple(self._fetch_transactions(account_id, headers, since))
        return AccountSyncPayload(account=account, transactions=transactions)

    def _fetch_transactions(
        self, account_id: str, headers: dict[str, str], since: "datetime | None",
    ) -> Iterable[TransactionData]:
        """Paginate via from_id. Stops when:
           - the API returns an empty page, OR
           - `since` is provided and the oldest transaction on the current page
             is older than `since`."""
        url = f"{self._base}/accounts/{account_id}/transactions"
        params: dict[str, str] = {}

        while True:
            resp = self._http.get(url, headers=headers, params=params, timeout=self._timeout)
            resp.raise_for_status()
            page = resp.json()
            if not page:
                return

            oldest_on_page: datetime | None = None
            for raw in page:
                tx = self._parse_transaction(raw)
                yield tx
                if oldest_on_page is None or tx.posted_at < oldest_on_page:
                    oldest_on_page = tx.posted_at

            # Cutoff check after yielding the page.
            if since is not None and oldest_on_page is not None and oldest_on_page < since:
                return

            # Paginate to next (older) page using the last transaction's id.
            params = {"from_id": str(page[-1]["id"])}

    def _parse_transaction(self, raw: dict) -> TransactionData:
        details = raw.get("details") or {}
        counterparty = details.get("counterparty") or {}
        # Teller gives YYYY-MM-DD with no time; stamp midnight UTC.
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
        )

    def fetch_investment_accounts(self, access_url: str) -> Iterable[InvestmentAccountSyncPayload]:
        # Teller has no investments API.
        return iter(())
```

- [ ] **Step 4: Run all Teller tests**

Run: `docker compose exec web pytest apps/providers/tests/test_teller.py -v`

Expected: 3 PASS (the two from Task 5 plus the new one).

- [ ] **Step 5: Run the full provider + banking test suite to confirm nothing else broke**

Run: `docker compose exec web pytest apps/providers/ apps/banking/ -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/providers/teller.py apps/providers/tests/test_teller.py
git commit -m "feat(teller): implement fetch_accounts_with_transactions with from_id pagination"
```

---

## Task 7: Delete the Robinhood-specific SimpleFIN test

**Files:**
- Modify: `apps/providers/tests/test_simplefin.py:156-199`

- [ ] **Step 1: Delete the test**

In `apps/providers/tests/test_simplefin.py`, delete the entire `test_fetch_investment_accounts_handles_robinhood_style_payload` function (lines 156-199 inclusive, including the `@responses.activate` decorator and the trailing blank line).

- [ ] **Step 2: Run remaining SimpleFIN tests**

Run: `docker compose exec web pytest apps/providers/tests/test_simplefin.py -v`

Expected: 5 tests PASS (was 6).

- [ ] **Step 3: Commit**

```bash
git add apps/providers/tests/test_simplefin.py
git commit -m "test(simplefin): drop Robinhood edge-case test (investments going manual)"
```

---

## Task 8: Fix `sync_all` to scope SimpleFIN-investments loop by provider

**Files:**
- Modify: `apps/banking/management/commands/sync_all.py:1-3, 30-36`

- [ ] **Step 1: Update the docstring**

In `apps/banking/management/commands/sync_all.py`, replace lines 1-3:

```python
"""Run every refresh path: bank sync (multi-provider), SimpleFIN investment sync,
yfinance price refresh on manual investments, scraped asset refresh.

Runs across ALL users in one shot. Designed for nightly host-crontab invocation:
    0 3 * * * cd /opt/finance && docker compose exec -T web python manage.py sync_all
"""
```

- [ ] **Step 2: Filter the SimpleFIN-investments loop**

Replace lines 30-36 (the `# 2. SimpleFIN: investments` block) with:

```python
        # 2. SimpleFIN: investments (Teller has no investments API)
        for inst in Institution.objects.filter(provider="simplefin"):
            try:
                result = sync_simplefin_investments(inst)
                self.stdout.write(f"[invest] {inst}: {result.holdings_updated} holdings updated, {result.holdings_manual_basis_preserved} manual basis preserved")
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"[invest] {inst} FAILED: {exc}"))
```

The diff is one line: `Institution.objects.all()` → `Institution.objects.filter(provider="simplefin")`.

- [ ] **Step 3: Smoke test the command (no Teller institutions exist yet, so behavior is unchanged)**

Run: `docker compose exec web python manage.py sync_all 2>&1 | head -20`

Expected: command runs to completion without errors. With no Teller institutions in the DB, output is identical to before the change.

- [ ] **Step 4: Commit**

```bash
git add apps/banking/management/commands/sync_all.py
git commit -m "fix(sync_all): scope SimpleFIN-investments loop to provider='simplefin'"
```

---

## Task 9: Convert `link_form` view into a chooser; add SimpleFIN-specific view

**Files:**
- Modify: `apps/banking/views.py:64-80`
- Create: `apps/banking/templates/banking/link_chooser.html`

- [ ] **Step 1: Split the existing `link_form` view**

In `apps/banking/views.py`, replace the existing `link_form` view (lines 64-80 inclusive) with:

```python
@login_required
def link_form(request):
    """Provider chooser. Routes to /banking/link/simplefin/ or /banking/link/teller/."""
    return render(request, "banking/link_chooser.html", {})


@login_required
@require_http_methods(["GET", "POST"])
def link_form_simplefin(request):
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

The body of `link_form_simplefin` is the *exact* code from the old `link_form` POST/GET handler (a verbatim move).

- [ ] **Step 2: Create the chooser template**

Create `apps/banking/templates/banking/link_chooser.html` with:

```html
{% extends "base.html" %}
{% block title %}Link an account{% endblock %}
{% block content %}
<div class="max-w-3xl mx-auto">
  <h1 class="text-2xl font-bold mb-6">Link an account — pick a provider</h1>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
    <a href="{% url 'banking:link_teller' %}"
       class="block p-6 rounded-lg border hover:opacity-90 transition-opacity"
       style="background: var(--surface); border-color: var(--border); color: var(--text);">
      <div class="text-lg font-bold mb-2">Teller</div>
      <p class="text-sm" style="color: var(--muted);">
        Connect a US bank through a secure popup. Recommended for most accounts.
        Free up to 100 enrollments.
      </p>
    </a>
    <a href="{% url 'banking:link_simplefin' %}"
       class="block p-6 rounded-lg border hover:opacity-90 transition-opacity"
       style="background: var(--surface); border-color: var(--border); color: var(--text);">
      <div class="text-lg font-bold mb-2">SimpleFIN</div>
      <p class="text-sm" style="color: var(--muted);">
        Paste a setup token from SimpleFIN Bridge. Best for investment accounts
        (Robinhood, Fidelity, etc.).
      </p>
    </a>
  </div>
  <div class="mt-6">
    <a href="{% url 'banking:list' %}" class="text-sm" style="color: var(--muted);">← Back to accounts</a>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Smoke test (URLs not yet wired, so this will 404; verify in Task 11)**

(No test runs at this step — Task 11 wires the URLs and runs the integration test.)

- [ ] **Step 4: Commit**

```bash
git add apps/banking/views.py apps/banking/templates/banking/link_chooser.html
git commit -m "feat(banking): split link_form into chooser + simplefin views"
```

---

## Task 10: Add Teller link view, callback view, and template

**Files:**
- Modify: `apps/banking/views.py` (add at the end, before the existing `account_detail` view if you want logical ordering, or simply append after `link_form_simplefin`)
- Create: `apps/banking/templates/banking/link_form_teller.html`

- [ ] **Step 1: Add imports for the callback view**

In `apps/banking/views.py`, add to the existing imports near the top:

```python
import json

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
```

(`JsonResponse` is the new addition; `HttpResponseRedirect` is already imported. `settings` and `json` are new.)

- [ ] **Step 2: Add the Teller link views**

In `apps/banking/views.py`, append these two views directly after `link_form_simplefin`:

```python
@login_required
def link_form_teller(request):
    return render(request, "banking/link_form_teller.html", {
        "teller_application_id": settings.TELLER_APPLICATION_ID,
        "teller_environment": settings.TELLER_ENVIRONMENT,
    })


@login_required
@require_http_methods(["POST"])
def link_form_teller_callback(request):
    """Receives JSON {access_token, display_name} from the Teller Connect onSuccess
    callback. Validates and links the institution; returns JSON for the JS to consume."""
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid JSON body."}, status=400)

    access_token = (body.get("access_token") or "").strip()
    display_name = (body.get("display_name") or "").strip() or "Teller Account"
    if not access_token:
        return JsonResponse({"ok": False, "error": "access_token is required."}, status=400)

    try:
        link_institution(
            user=request.user,
            setup_token=access_token,
            display_name=display_name,
            provider_name="teller",
        )
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse({"ok": True, "redirect_url": reverse("banking:list")})
```

- [ ] **Step 3: Create the Teller link template**

Create `apps/banking/templates/banking/link_form_teller.html` with:

```html
{% extends "base.html" %}
{% block title %}Connect a bank via Teller{% endblock %}
{% block content %}
<div class="max-w-xl mx-auto">
  <h1 class="text-2xl font-bold mb-4">Connect a bank via Teller</h1>
  <p class="text-sm mb-6" style="color: var(--muted);">
    Click "Connect a bank" to launch a secure popup. After authenticating with
    your bank, you'll be redirected back here and an initial sync will run.
  </p>

  {% if messages %}
    {% for message in messages %}
    <div class="border p-3 rounded text-sm mb-4"
         style="{% if message.tags == 'error' %}background: var(--tint-lia); border-color: var(--accent-lia); color: var(--accent-lia);{% else %}background: var(--tint-positive); border-color: var(--accent-positive); color: var(--accent-positive);{% endif %}">
      {{ message }}
    </div>
    {% endfor %}
  {% endif %}

  <div class="space-y-4">
    <div>
      <label class="block text-sm mb-1" style="color: var(--muted);" for="id_display_name">Display name</label>
      <input id="id_display_name" type="text" value=""
             placeholder="e.g., Teller · Main banks"
             class="w-full rounded px-3 py-2"
             style="background: var(--surface); border: 1px solid var(--border); color: var(--text);">
    </div>
    <div class="flex items-center gap-3">
      <button id="teller-connect-btn" type="button"
              class="font-bold px-5 py-2 rounded"
              style="background: var(--accent-positive); color: var(--bg);">
        Connect a bank →
      </button>
      <a href="{% url 'banking:link' %}" class="text-sm" style="color: var(--muted);">Cancel</a>
    </div>
    <div id="teller-status" class="text-sm" style="color: var(--muted);"></div>
  </div>
</div>

<script src="https://cdn.teller.io/connect/connect.js"></script>
<script>
(function () {
  const APPLICATION_ID = "{{ teller_application_id|default:""|escapejs }}";
  const ENVIRONMENT = "{{ teller_environment|default:"sandbox"|escapejs }}";
  const CSRF_TOKEN = "{{ csrf_token|escapejs }}";
  const CALLBACK_URL = "{% url 'banking:link_teller_callback' %}";

  const btn = document.getElementById("teller-connect-btn");
  const status = document.getElementById("teller-status");
  const displayNameInput = document.getElementById("id_display_name");

  if (!APPLICATION_ID) {
    btn.disabled = true;
    status.textContent = "Teller is not configured. Set TELLER_APPLICATION_ID in your .env file.";
    status.style.color = "var(--accent-negative)";
    return;
  }

  const teller = TellerConnect.setup({
    applicationId: APPLICATION_ID,
    environment: ENVIRONMENT,
    products: ["transactions", "balance"],
    onSuccess: function (enrollment) {
      status.textContent = "Linking…";
      fetch(CALLBACK_URL, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": CSRF_TOKEN,
        },
        body: JSON.stringify({
          access_token: enrollment.accessToken,
          display_name: displayNameInput.value.trim(),
        }),
      })
        .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
        .then(function (res) {
          if (res.body.ok) {
            window.location = res.body.redirect_url;
          } else {
            status.textContent = "Link failed: " + (res.body.error || "Unknown error");
            status.style.color = "var(--accent-negative)";
          }
        })
        .catch(function (err) {
          status.textContent = "Link failed: " + err.message;
          status.style.color = "var(--accent-negative)";
        });
    },
    onExit: function () {
      status.textContent = "Connect was closed before linking.";
    },
  });

  btn.addEventListener("click", function () { teller.open(); });
})();
</script>
{% endblock %}
```

- [ ] **Step 4: Commit**

```bash
git add apps/banking/views.py apps/banking/templates/banking/link_form_teller.html
git commit -m "feat(banking): add Teller link view, callback view, and Connect widget template"
```

---

## Task 11: Wire URL routes and verify end-to-end navigation

**Files:**
- Modify: `apps/banking/urls.py`

- [ ] **Step 1: Add URL routes**

In `apps/banking/urls.py`, replace the `urlpatterns` list (lines 7-17) with:

```python
urlpatterns = [
    path("", views.banks_list, name="list"),
    path("link/", views.link_form, name="link"),
    path("link/simplefin/", views.link_form_simplefin, name="link_simplefin"),
    path("link/teller/", views.link_form_teller, name="link_teller"),
    path("link/teller/callback/", views.link_form_teller_callback, name="link_teller_callback"),
    path("<int:institution_id>/sync/", views.sync_institution_view, name="sync"),
    path("<int:institution_id>/rename/", views.rename_institution, name="rename_institution"),
    path("accounts/<int:account_id>/", views.account_detail, name="account_detail"),
    path("accounts/<int:account_id>/rename/", views.rename_account, name="rename_account"),
    path("transactions/<int:transaction_id>/rename/", views.rename_transaction, name="rename_transaction"),
    path("<int:institution_id>/delete/", views.delete_institution, name="delete_institution"),
    path("accounts/<int:account_id>/delete/", views.delete_account, name="delete_account"),
]
```

- [ ] **Step 2: Verify URLs resolve**

Run:

```bash
docker compose exec web python manage.py shell -c "from django.urls import reverse; print(reverse('banking:link')); print(reverse('banking:link_simplefin')); print(reverse('banking:link_teller')); print(reverse('banking:link_teller_callback'))"
```

Expected:
```
/banking/link/
/banking/link/simplefin/
/banking/link/teller/
/banking/link/teller/callback/
```

- [ ] **Step 3: Run the full test suite to ensure nothing else regressed**

Run: `docker compose exec web pytest -q`

Expected: all tests pass. Note: there are no Django view tests for these new URLs (the spec scoped them out — Connect callback is verified via sandbox, not unit tests), so this just confirms nothing in `views.py` got broken syntactically.

- [ ] **Step 4: Manual smoke test of GET routes**

Run: `docker compose exec web python manage.py runserver_plus 0.0.0.0:8000 &` (or restart the web container if using compose).

Then with a logged-in session, visit (in a browser, or curl with session cookie):

- `GET /banking/link/` — should render the chooser with two cards
- `GET /banking/link/simplefin/` — should render the existing setup-token form
- `GET /banking/link/teller/` — should render the Teller page; if `TELLER_APPLICATION_ID` is empty, the button shows a disabled state with a config error message

The Teller widget itself can't be tested without real credentials (Task 13 covers sandbox setup).

- [ ] **Step 5: Commit**

```bash
git add apps/banking/urls.py
git commit -m "feat(banking): wire URL routes for chooser, SimpleFIN, and Teller link flows"
```

---

## Task 12: Update README with Teller setup section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Teller setup section**

In `README.md`, find the existing "Step 0 — Sign up for SimpleFIN" section. Insert a new "Step 0b — Teller setup (optional alternative)" section immediately after the SimpleFIN section, in the same style:

```markdown
## Step 0b — Teller setup (optional alternative)

FinLab supports Teller as an alternative to SimpleFIN for bank aggregation.
Teller covers more US institutions and uses real account-type metadata, but
requires mTLS client certificates.

1. **Create a Teller account** at <https://teller.io>. The free `sandbox` and
   `development` tiers (~100 enrollments) are sufficient for personal use.
2. **Generate a certificate pair** in the Teller dashboard. Download both
   `cert.pem` and `key.pem`.
3. **Place the cert files** in `secrets/teller/` on the host (this directory is
   bind-mounted into the container at `/run/secrets/teller/` — see
   `compose.yml`):

   ```
   secrets/teller/
   ├── cert.pem
   └── key.pem
   ```

4. **Configure the four env vars** in `.env`:

   ```
   TELLER_APPLICATION_ID=<from the Teller dashboard>
   TELLER_ENVIRONMENT=sandbox  # or "development" / "production"
   TELLER_CERT_PATH=/run/secrets/teller/cert.pem
   TELLER_KEY_PATH=/run/secrets/teller/key.pem
   ```

5. **Restart the `web` container** so it picks up the env and mount:
   `docker compose up -d web`.
6. **Link a bank** at `/banking/link/` → Teller card → "Connect a bank".

You can run Teller and SimpleFIN side-by-side; each linked institution remembers
its own provider and syncs independently.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): document Teller setup"
```

---

## Task 13: Final verification — full test suite + manual sandbox smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the entire pytest suite one more time**

Run: `docker compose exec web pytest -q`

Expected: all tests pass. Net change versus pre-branch state: +3 tests (Teller), -1 test (Robinhood SimpleFIN edge case).

- [ ] **Step 2: Verify the migration applied cleanly**

Run: `docker compose exec web python manage.py showmigrations banking`

Expected: all migrations including `0004_alter_institution_provider` show `[X]` (applied).

- [ ] **Step 3: Verify TellerProvider is in the registry**

Run:

```bash
docker compose exec web python -c "
from apps.providers.registry import _REGISTRY
print('Registered providers:', sorted(_REGISTRY.keys()))
"
```

Expected: `Registered providers: ['simplefin', 'teller']`.

- [ ] **Step 4: (Manual) Sandbox smoke test**

If you have a Teller sandbox cert + application ID:

1. Drop the PEM files in `secrets/teller/`.
2. Set `TELLER_APPLICATION_ID` and `TELLER_ENVIRONMENT=sandbox` in `.env`.
3. `docker compose up -d --build web`.
4. Visit `/banking/link/` → click "Teller" → "Connect a bank".
5. Choose a sandbox institution (e.g., "Capital One"), enter sandbox creds.
6. Verify the institution appears in `/banking/` after redirect, with at least one account and recent transactions populated.
7. Click "Sync" on the institution. Verify it succeeds with no new transactions (idempotency).
8. Verify `docker compose exec web python manage.py sync_all` runs cleanly with both a SimpleFIN and a Teller institution present.

If you don't have sandbox credentials yet, skip this step — the unit tests confirm the code paths work; full sandbox verification can happen on the next environment with credentials.

- [ ] **Step 5: Final summary commit (optional, only if any tweaks were needed)**

If steps 1-4 all passed without changes, no commit is needed. If any tweaks were necessary, commit them with a descriptive message.

---

## Done

At this point:

- TellerProvider is registered alongside SimpleFINProvider.
- `/banking/link/` shows a chooser; both providers are reachable from there.
- The model's `provider` choices include `teller`.
- `sync_all` does not blindly call SimpleFIN-investments on Teller institutions.
- Tests: +3 Teller, -1 SimpleFIN Robinhood, all service-layer tests untouched.
- Configuration: env vars, Docker mount, secrets dir all wired.
- README documents Teller setup.

Next phase (separate plan, not in scope here): if Teller proves reliable, optionally migrate any SimpleFIN-backed brokerage accounts to manual `InvestmentAccount` entries and drop the SimpleFIN integration entirely.
