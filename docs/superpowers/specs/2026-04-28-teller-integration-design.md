# Teller Integration — Design

**Date:** 2026-04-28
**Status:** Approved, awaiting implementation plan
**Branch:** `feature/teller-integration`

## Summary

Add Teller.io as a second bank-aggregation provider alongside the existing SimpleFIN integration. Both providers run concurrently — users can link some institutions through Teller and others through SimpleFIN, and `sync_all` refreshes both. The integration is mostly additive; existing SimpleFIN code is unchanged.

Investments stay on SimpleFIN for now (Teller has no investments API). Users who eventually want to drop SimpleFIN entirely can migrate brokerage accounts to manual `InvestmentAccount` entry, which is already supported.

## Motivation

SimpleFIN has reliability and coverage gaps. Teller offers stronger bank coverage for US institutions, real account-type metadata (no name-guessing heuristic), and a free dev tier sufficient for personal homelab use (~100 enrollments). Plaid was considered and rejected — too expensive and not indie-friendly for self-hosted use.

Keeping SimpleFIN available as a peer rather than ripping it out preserves any institutions already linked and leaves a working path for investment aggregation if manual entry proves too tedious.

## Existing state (relevant facts)

- `apps/providers/base.py` — `FinancialProvider` Protocol already defines the contract (`exchange_setup_token`, `fetch_accounts_with_transactions`, `fetch_investment_accounts`). The `Institution.PROVIDER_CHOICES` model field has a commented-out Plaid placeholder, anticipating multi-provider.
- `apps/providers/registry.py` — name-based provider registry with `register` decorator and `get(name)` lookup. Adding a provider is one decorator call.
- `apps/banking/services.py:link_institution` and `sync_institution` — already provider-agnostic. They call `get_provider(institution.provider)` and trust the result. No changes needed.
- `apps/banking/models.py:13` — `Institution.access_url = EncryptedTextField(...)`. Field name is SimpleFIN-flavored but functionally just stores "the credential we need to hit the provider's API." For Teller it will hold the access token.
- `apps/banking/management/commands/sync_all.py:31` — runs `sync_simplefin_investments(inst)` against **every** institution regardless of provider. Currently safe because all institutions are SimpleFIN; would crash the moment a Teller institution exists.
- `apps/banking/templates/banking/link_form.html` — current link form, hardcoded SimpleFIN paste-token UI. Mounted at `/banking/link/`.
- `config/middleware.py` — `LoginRequiredMiddleware` with `EXEMPT_PATH_PREFIXES`. New Teller URLs are behind login (correct), no exemption needed.

## Design

### 1. New provider: `apps/providers/teller.py`

A `TellerProvider` class implementing the existing `FinancialProvider` Protocol:

```python
@register
class TellerProvider:
    name = "teller"

    def __init__(self, http=None, timeout=30.0):
        self._http = http or requests.Session()
        self._http.cert = (settings.TELLER_CERT_PATH, settings.TELLER_KEY_PATH)
        self._timeout = timeout
        self._base = "https://api.teller.io"

    def exchange_setup_token(self, setup_token: str) -> str:
        """Validate the access token by calling GET /accounts.
        On 200, return the token unchanged (it IS the access credential).
        On 401, raise ValueError."""

    def fetch_accounts_with_transactions(self, access_url):
        # 1. GET /accounts
        # 2. For each account: GET /accounts/{id}/balances + GET /accounts/{id}/transactions (paginated)
        # 3. yield AccountSyncPayload per account

    def fetch_investment_accounts(self, access_url):
        return iter(())  # Teller has no investments API.
```

**Auth:** `Authorization: Basic <base64(access_token + ":")>` on every request, plus mTLS via `Session.cert` set once at init.

**Account-type mapping** (Teller `subtype` → our `Account.type`):

| Teller subtype | Our type |
|---|---|
| `checking` | `checking` |
| `savings` | `savings` |
| `credit_card` | `credit` |
| `mortgage`, `auto_loan`, `student_loan` | `loan` |
| anything else | `other` |

This replaces `_guess_type` for Teller accounts (Teller has real metadata; the heuristic stays only for SimpleFIN).

**Transaction field mapping:**

| Our field | Teller source |
|---|---|
| `external_id` | `transaction.id` |
| `posted_at` | `transaction.date` parsed as midnight UTC (Teller does not provide a timestamp) |
| `amount` | `transaction.amount` (Teller signs the same way SimpleFIN does — debit negative for depository, positive for credit cards) |
| `description` | `transaction.description` |
| `payee` | `transaction.details.counterparty.name` if present, else `transaction.description` |
| `memo` | `""` (Teller has no separate memo field) |
| `pending` | `transaction.details.processing_status == "pending"` |

**Transaction history pagination:**

- **First sync** (no transactions stored for any account on this institution): paginate via `from_id` query parameter all the way back to the start of available history.
- **Subsequent syncs:** paginate forward from the most recent page, stopping (per account) once we've seen 30 consecutive transactions whose `external_id` already exists in the DB for that account. This bounds API cost while still catching late-posting transactions and reconciling pending → posted transitions.

API call cost per sync: 1 (accounts list) + 2N + Pages, where N = accounts and Pages depends on transaction volume. For a typical 3–5-account institution this is ~10 calls — fine. Compare to SimpleFIN's flat 1 call per institution.

### 2. Link flow: chooser page + Teller-specific page

**Chooser page** (`/banking/link/`):

`apps/banking/templates/banking/link_chooser.html` — small page with two cards. "Teller (connect a US bank)" and "SimpleFIN (paste a setup token)". Each card links to a provider-specific URL.

`apps/banking/views.py:link_form` — replace the current GET handler (which renders the SimpleFIN form) with one that renders the chooser. The POST path moves to `link_form_simplefin`.

**SimpleFIN-specific page** (`/banking/link/simplefin/`):

`apps/banking/views.py:link_form_simplefin` — the **exact** code path that today's `link_form` runs. The existing template `link_form.html` is reused unchanged.

**Teller-specific page** (`/banking/link/teller/`):

`apps/banking/views.py:link_form_teller` — GET renders `link_form_teller.html`, passing `TELLER_APPLICATION_ID` and `TELLER_ENVIRONMENT` to the template context.

`apps/banking/templates/banking/link_form_teller.html` — display name input, "Connect a bank" button, and (inside the `content` block, since `base.html` has no `extra_head` block):

1. A `<script src="https://cdn.teller.io/connect/connect.js">` tag.
2. An inline `<script>` that initializes `TellerConnect.setup({applicationId, environment, onSuccess: ...})` and binds it to the button.
3. On `onSuccess(enrollment)`, `fetch()`-POSTs `{access_token, display_name, csrfmiddlewaretoken}` to `/banking/link/teller/callback/`.
4. On a `{ok: true, redirect_url}` response, sets `window.location = redirect_url`.

**Callback view** (`/banking/link/teller/callback/`, POST only):

`apps/banking/views.py:link_form_teller_callback` — parses JSON body, calls `link_institution(user=request.user, setup_token=access_token, display_name=..., provider_name="teller")`, returns JSON `{ok: true, redirect_url: reverse("banking:list")}` on success or `{ok: false, error: str(exc)}` on failure.

**URL changes** in `apps/banking/urls.py`:

```
/banking/link/                     → link_form                 (chooser, GET only)
/banking/link/simplefin/           → link_form_simplefin       (GET renders form, POST submits token)
/banking/link/teller/              → link_form_teller          (GET only, renders the Connect-widget page)
/banking/link/teller/callback/     → link_form_teller_callback (POST only, JSON body)
```

### 3. `sync_all` fix

`apps/banking/management/commands/sync_all.py:31` — filter the SimpleFIN investments loop to provider="simplefin":

```python
# 2. SimpleFIN: investments
for inst in Institution.objects.filter(provider="simplefin"):
    ...
```

Update the docstring at line 1 to reflect that step 1 is multi-provider.

### 4. Model change

`apps/banking/models.py:16` — extend `PROVIDER_CHOICES`:

```python
PROVIDER_CHOICES = [
    ("simplefin", "SimpleFIN"),
    ("teller", "Teller"),
]
```

A no-op migration is generated for the choices change. Existing rows keep their `provider="simplefin"` value.

### 5. Configuration

`.env.example` additions:

```
# Teller (mTLS bank aggregation)
TELLER_APPLICATION_ID=
TELLER_ENVIRONMENT=sandbox
TELLER_CERT_PATH=/run/secrets/teller/cert.pem
TELLER_KEY_PATH=/run/secrets/teller/key.pem
```

`config/settings.py` — read all four env vars. `TELLER_APPLICATION_ID` and `TELLER_ENVIRONMENT` need to be passed to the link template context (either via a context processor or the view function — view function preferred for now since the link page is the only consumer).

`docker-compose.yml` — add a read-only volume mount on the `web` service:

```yaml
volumes:
  - ./secrets/teller:/run/secrets/teller:ro
```

`.gitignore` — add `secrets/teller/` so PEM files never get committed.

`README.md` — add a brief "Teller setup" section parallel to the existing SimpleFIN section, covering: register at teller.io, generate sandbox + dev certs, drop the PEM files in `secrets/teller/`, set the four env vars.

### 6. CSP

If a Content-Security-Policy is set in production via NPM (Cloudflare → NPM → Django), the `script-src` directive must allow `https://cdn.teller.io`. Currently CSP isn't enforced at the Django layer, so this is only a concern if the user later adds CSP at the proxy.

## Testing

**New tests (`apps/providers/tests/test_teller.py`):**

1. `test_exchange_setup_token_validates_against_accounts_endpoint` — `responses.add` a 200 response to `GET /accounts`, assert `exchange_setup_token` returns the input unchanged.
2. `test_exchange_setup_token_raises_on_401` — mock 401, assert `ValueError` with message indicating Teller rejected the token.
3. `test_fetch_accounts_with_transactions_parses_payload` — mock the 1 + 2N call sequence (accounts list, then balances + transactions per account) for one happy-path account. Assert the resulting `AccountSyncPayload` has the right `external_id`, `name`, `type`, `balance`, and one well-formed `TransactionData`.

**Tests deleted:**

- `test_fetch_investment_accounts_handles_robinhood_style_payload` in `apps/providers/tests/test_simplefin.py:156-199` — Robinhood-specific edge case becomes dead weight as investments move to manual entry.

**Tests untouched:**

- `apps/banking/tests/test_services.py` — link flow, sync idempotency, rename preservation, type-override preservation. The `_FakeProvider` fixture means these tests already exercise the registry path and will cover Teller institutions automatically.
- `apps/banking/tests/test_fields.py` — `EncryptedTextField`, provider-independent.
- All view tests across apps — provider-independent.
- The remaining 5 SimpleFIN provider tests in `test_simplefin.py` — SimpleFIN stays in active use.

**Net change:** +3 tests, -1 test, ~+35 net lines.

**Not tested (explicit non-goals):**

- The Teller Connect JS callback flow. Browser/widget integration is hard to mock meaningfully and adds little real safety. Verified by clicking through the sandbox once during implementation.
- The `sync_all.py` filter fix. A one-line change to a script that's already untested; adding test scaffolding for it costs more than it's worth.
- Pagination cursor handling. Will fall out of the first real sandbox sync; not worth a dedicated unit test.

## Out of scope

- **Removing SimpleFIN.** Both providers run concurrently. Future spec if SimpleFIN gets dropped.
- **Migrating SimpleFIN-backed investment accounts to manual entry.** Existing data stays as-is. Users can manually convert if and when they want.
- **Renaming `Institution.access_url` field.** It's misleading for Teller (stores a token, not a URL) but renaming costs a migration with no functional benefit. Field name stays.
- **Production-tier Teller billing setup.** Sandbox + dev tier covers personal homelab use.
- **CSP hardening at the Django layer.** If/when CSP is enforced, `https://cdn.teller.io` will need allow-listing in `script-src`.
- **Multi-user cert isolation.** Single application-wide Teller cert; if FinLab ever multi-tenants Teller credentials, that's a separate design.

## Risks

- **Teller's `from_id` pagination semantics.** First-sync backfill assumes `from_id` returns transactions strictly older than the given ID, with empty results signaling end-of-history. Verify against Teller docs and sandbox before assuming forever-loop is impossible.
- **Cert rotation downtime.** Replacing PEM files requires a `docker compose restart web`. Acceptable for this use case but worth noting.
- **Teller Connect script breakage.** CDN script can change without notice. If it does, new Teller enrollments break silently until someone tries to add a bank. No mitigation in this spec — accepted risk.
