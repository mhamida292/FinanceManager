# Personal Finance Dashboard — Design

**Date:** 2026-04-24
**Status:** Approved (brainstorming complete)
**Owner:** mohamed

---

## 1. Overview

Self-hosted, multi-user personal finance dashboard for a homelab. Two users (Mohamed and his father), fully isolated data tenancy. Aggregates bank transactions, investment holdings, and a manually-tracked physical-gold portfolio into a single dashboard. Reachable as `https://finance.momajlab.com` over the user's tailnet, with a path to public exposure via Cloudflare Tunnel later.

### Goals (v1)

- Link bank accounts and brokerages via SimpleFIN; show balances and transactions in one place.
- Investments page with per-position holdings, cost basis, and gain/loss.
- Custom-asset page tracking specific gold-bullion products by quantity, with daily price scraping from accbullion.com.
- Net-worth dashboard rolling up cash + investments + gold.
- Daily automated sync at 3am plus a manual "Sync now" button.
- Full data tenancy isolation between users.

### Non-Goals (v1)

- Budgeting features (per-category limits, alerts).
- Manual transaction recategorization (we display SimpleFIN's category as-is).
- CSV import for older transactions.
- Mobile native app.
- TOTP / 2FA (schema-ready, deferred to v1.1).
- Public internet exposure (deferred — Cloudflare Tunnel layer added later).
- Recurring-transaction detection.
- Notifications / email alerts.

---

## 2. Architecture & Stack

### Language & Framework
- **Python 3.12 + Django 5.x** (server-rendered)
- **HTMX** for interactivity without an SPA
- **Tailwind CSS** for styling (or vanilla — decided at implementation time)
- **Postgres 16** for storage
- **Caddy 2** as reverse proxy with `caddy-dns/cloudflare` plugin
- **Django Q2** as the background job runner

### Service Topology

Single Docker Compose stack. Four services (option to collapse `cron` into `web` revisited at planning time):

| Service | Image | Purpose |
|---|---|---|
| `web` | Custom Django image | Web UI, HTTP API, sync triggers |
| `db` | `postgres:16` | All persistent data |
| `cron` | Same Django image | Django Q2 worker — runs scheduled syncs and gold scrape |
| `proxy` | `caddy:2` (custom build with Cloudflare DNS plugin) | TLS termination, reverse proxy |

### Repository Layout

```
finance/
├── apps/
│   ├── accounts/      # users, sessions
│   ├── banking/       # institutions, accounts, transactions
│   ├── investments/   # holdings, portfolio snapshots
│   ├── assets/        # gold + future manual assets
│   ├── providers/     # SimpleFIN client + scraper plugins
│   └── dashboard/     # HTMX views, templates
├── config/            # Django settings, urls, asgi/wsgi
├── compose.yml
├── Dockerfile
├── Caddyfile
├── .env.example
└── backups/           # bind-mounted, gitignored
```

### Networking

- **LAN/Tailscale-only initially.**
- DNS: A record `finance.momajlab.com` → homelab tailnet IP (e.g., `100.64.x.x`) at Cloudflare.
- TLS: Caddy issues a Let's Encrypt cert via DNS-01 challenge using a scoped Cloudflare API token. Result: real public TLS cert on a service that's only reachable inside the tailnet.
- **Future Cloudflare Tunnel:** point an existing tunnel at `proxy:443` and either swap the DNS record or add a second hostname. Cloudflare Access can sit in front for an extra auth layer (Google login + email allowlist).

### External Dependencies

- **SimpleFIN Bridge** — pull-based aggregator, $1.50/month flat fee. Holds an Access URL per linked institution.
- **accbullion.com** — public HTML scrape for per-product gold prices. No auth.
- **Cloudflare** — DNS, optional Tunnel later.
- **No webhook ingress required** — pull-based for everything.

---

## 3. Data Model

Eight tables across five Django apps. Multi-tenancy is enforced via a `user` foreign key (direct or chained) on every user-owned row.

### accounts app
- **`User`** — Django built-in. Username, email, hashed password.

### banking app
- **`Institution`**
  - `id` (pk), `user_id` (fk → User)
  - `name`
  - `access_url` — encrypted at rest with `FIELD_ENCRYPTION_KEY` from env
  - `provider` — `'simplefin'` for v1; field exists to support `'plaid'` etc. later
  - `last_synced_at`
- **`Account`**
  - `id` (pk), `institution_id` (fk → Institution)
  - `name`, `type` (checking/savings/credit/...)
  - `balance`, `currency`
  - `external_id` (unique with institution_id) — SimpleFIN's account id
  - `last_synced_at`
- **`Transaction`**
  - `id` (pk), `account_id` (fk → Account)
  - `date`, `amount`
  - `description`, `category` (string from SimpleFIN; not normalized in v1)
  - `pending` (bool)
  - `external_id` (unique with account_id) — SimpleFIN's txn id

### investments app
- **`InvestmentAccount`**
  - `id` (pk), `institution_id` (fk → Institution)
  - `name`, `broker`
  - `external_id` (unique with institution_id)
  - `last_synced_at`
- **`Holding`**
  - `id` (pk), `investment_account_id` (fk → InvestmentAccount)
  - `symbol`, `name`
  - `shares` (decimal), `current_price`, `market_value`
  - `cost_basis` (nullable)
  - `cost_basis_source` (`'auto'` | `'manual'`) — controls overwrite-on-sync behavior
- **`PortfolioSnapshot`**
  - `id` (pk), `investment_account_id` (fk → InvestmentAccount)
  - `date` (unique with investment_account_id)
  - `total_value`

### assets app
- **`AssetProduct`** (global, not per-user)
  - `id` (pk), `name`
  - `source` (`'accbullion'`), `source_url`
  - `unit` (`'oz'` | `'each'`)
- **`AssetHolding`**
  - `id` (pk), `user_id` (fk → User), `product_id` (fk → AssetProduct)
  - `quantity` (decimal), `notes`
- **`AssetPriceSnapshot`**
  - `id` (pk), `product_id` (fk → AssetProduct)
  - `scraped_at`, `price_per_unit`

### ops
- **`SyncJob`**
  - `id` (pk)
  - `institution_id` (fk → Institution, nullable) — set for SimpleFIN syncs
  - `asset_product_id` (fk → AssetProduct, nullable) — set for scraper jobs
  - Exactly one of the two FKs is non-null per row.
  - `started_at`, `finished_at`
  - `status` (`'ok'` | `'failed'` | `'requires_relink'`)
  - `error_message`
  - **Visibility on `/settings/`:** a user sees institution jobs that belong to them, plus scraper jobs for any `AssetProduct` they currently hold (joined via `AssetHolding`).

### Multi-tenancy enforcement

- Every model exposes `objects.for_user(user)` via a custom QuerySet manager. Chained models filter through their FK chain (e.g., `Transaction.objects.for_user(u)` filters via `account__institution__user=u`).
- All user-facing views call `for_user(request.user)` — never the bare manager.
- A non-skippable test (`test_isolation.py` per app) creates two users, populates data for both, and asserts no cross-tenant rows leak.
- Django admin (`/admin/`) intentionally bypasses this isolation — superusers see everything for debugging.

---

## 4. Sync Flow

### Provider abstraction

```python
class FinancialProvider(Protocol):
    name: str
    def link(setup_token: str) -> str: ...                # returns access_url
    def fetch_accounts(access_url: str) -> list[AccountData]: ...
    def fetch_transactions(access_url: str, since: datetime) -> list[TxnData]: ...
    def fetch_holdings(access_url: str) -> list[HoldingData]: ...
```

`apps/providers/simplefin.py` implements this. Adding Plaid later means writing `plaid.py` and registering it. The rest of the app reads `Institution.provider` and dispatches via a registry.

### Scraper abstraction

```python
class PriceScraper(Protocol):
    source: str   # 'accbullion'
    def fetch_price(source_url: str) -> Decimal: ...
```

### SimpleFIN linking flow (one-time per institution)

1. User clicks "Add account" → backend opens SimpleFIN's hosted UI in a popup.
2. SimpleFIN redirects back with a one-time **setup token**.
3. Backend exchanges setup token → **Access URL** (single HTTP call, time-limited).
4. Encrypt the Access URL with `FIELD_ENCRYPTION_KEY`, save on `Institution`.
5. Immediately call `fetch_accounts` to populate the DB.

### Scheduled sync

- A Django Q2 schedule fires at **03:00 daily**.
- The schedule enqueues one sync job per `Institution`, plus one scrape job per `AssetProduct` referenced by any `AssetHolding`.
- Each job runs in a worker process inside the `cron` service.
- **Backfill on first link:** request maximum available history from SimpleFIN per institution (varies by bank — typically 90 days, sometimes years).

### Manual sync

- "Sync now" button on the dashboard issues `POST /sync/`.
- Backend enqueues the same jobs at high priority.
- HTMX polls `/sync/status/` every 2s and updates inline ("Syncing... 12 new transactions").

### Idempotency

- All upserts use `update_or_create(external_id=...)`. Re-running a sync produces zero duplicates.
- After holdings upsert, `PortfolioSnapshot` for today is `update_or_create`'d so re-runs same day overwrite cleanly.

### Cost-basis special case

- When SimpleFIN provides cost basis: write it with `cost_basis_source='auto'`.
- When SimpleFIN omits it: `cost_basis=NULL`. Inline edit in the UI lets the user enter it; that flips `cost_basis_source='manual'`.
- Future syncs **never** overwrite `manual` basis — they only update `shares` and `current_price`.

### Failure handling

| Error | Behavior | User-visible |
|---|---|---|
| Transient (network, 5xx) | `SyncJob` failed, exponential backoff, up to 3 attempts | Banner only after all 3 fail: "Sync failed — will retry tomorrow" |
| Auth (401/403, revoked Access URL) | `SyncJob` failed with `status='requires_relink'`, no retry | Banner: "Re-link required for [Bank]" + button to redo SimpleFIN flow |
| Scraper (HTML changed) | `SyncJob` failed, error logged with HTML snippet | Banner on /assets/: "Couldn't fetch [Product] — last good value [date]" |

---

## 5. Auth & Multi-tenancy

### Auth

- Django built-in `User`. **No public signup.** Two superusers created via `createsuperuser` at first deploy.
- Password hashing: `argon2` (via `argon2-cffi`). Stronger than the default PBKDF2.
- Sessions via Django's signed cookies — `httpOnly`, `Secure`, `SameSite=Lax`.
- CSRF protection on by default.
- 30-day "remember me" sessions.
- **TOTP-ready:** schema and middleware leave a clean slot for `django-otp`. Adding it later is a one-day change (install package, add a model, add a view, require it via middleware).

### Admin panel

- `/admin/` — superuser only. Both Mohamed and dad are superusers.
- Free CRUD over every table — primary tool for debugging when sync produces unexpected data.
- Admin intentionally sees all rows across users (small trust circle).

### Future Cloudflare Tunnel hardening

When the tunnel is enabled, **Cloudflare Access** can sit in front: Google login + email allowlist before requests reach Django. App-side code unchanged.

---

## 6. UI / Pages

Six application pages plus the Django admin. Server-rendered with HTMX for interactive bits (sync status, inline edits, transaction filtering).

| URL | Purpose | Notes |
|---|---|---|
| `/login/` | Sign in | Standard Django login view, custom template |
| `/` | Dashboard | Net-worth headline, sync button, three summary cards (Cash / Investments / Gold), recent-transactions list, sync-status banner |
| `/banks/` | Bank accounts | Institution list, per-account balance + transactions, "Add account" button (SimpleFIN flow) |
| `/investments/` | Investments | Per-account holdings table: ticker, shares, current price, market value, cost basis, gain/loss $/%; inline edit for cost basis |
| `/assets/` | Gold & manual assets | Holdings list, per-product last-scraped price, total value; "Add holding" with product picker or new-product form |
| `/settings/` | Settings | Re-link institution, view sync history (`SyncJob` log), change password |
| `/admin/` | Django admin | Superuser only |

---

## 7. Operations & Deployment

### Secrets

Stored in `.env` (gitignored), loaded by Compose. (Docker secrets is a v2 hardening if needed; env is fine for a homelab.)

- `DJANGO_SECRET_KEY` — session signing
- `FIELD_ENCRYPTION_KEY` — at-rest encryption for `Institution.access_url`
- `POSTGRES_PASSWORD`
- `CLOUDFLARE_API_TOKEN` — DNS-01 challenge, scoped to `momajlab.com` only

### Backups

- Nightly job in `cron` service: `pg_dump | gzip > /backups/finance-$(date +%F).sql.gz`
- `./backups/` is bind-mounted from host — files persist across container restarts.
- 30-day retention via `find /backups -mtime +30 -delete` in the same job.
- Off-site copy is the user's responsibility (rsync to NAS / cloud, on the user's preferred cadence).

### Logs & observability

- Django logs structured JSON to stdout. `docker compose logs -f web` is the read tool.
- `SyncJob` table doubles as an in-app sync log, surfaced in `/settings/`.
- Loki / Grafana optional later; not required for v1.

### First-time setup

1. `git clone` repo, copy `.env.example` → `.env`, fill in secrets.
2. `docker compose up -d`
3. `docker compose exec web python manage.py migrate`
4. `docker compose exec web python manage.py createsuperuser` (×2 — one for each user)
5. Open `https://finance.momajlab.com` on a tailnet device, log in, click "Add account."

### Updates

`git pull && docker compose build && docker compose up -d`. Migrations run automatically on `web` container start.

### Resource sizing

~512MB RAM total at idle. ~2GB Postgres disk after a year of full sync history. Negligible CPU outside the 3am sync window.

---

## 8. Open / Deferred

- **Gold scraper specifics for accbullion.com** — exact CSS selectors and product URL patterns to be determined when implementing the scraper. The data model and abstraction are in place to plug them in.
- **Whether to collapse `cron` into `web`** — open trim decision from brainstorming. Default plan keeps them separate; will revisit at implementation-plan time.
- **Whether to collapse five Django apps into three** — same. Default plan keeps the five-app split.
- **Tailwind vs. vanilla CSS** — defer to implementation phase.
- **TOTP** — explicitly v1.1.
- **CSV import, budgeting, alerts, recategorization** — explicitly v2.

---

## 9. Pricing / Cost

- SimpleFIN Bridge: **$1.50 / month** (flat).
- Cloudflare DNS + Tunnel: free.
- Compute: runs on user's existing homelab.
- **Total monthly external cost: ~$1.50.**
