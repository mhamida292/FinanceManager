# FinLab

Track your bank accounts, investments, and physical assets in one self-hosted dashboard. SimpleFIN aggregates US banks; you add manual investments and assets; mobile-friendly and PWA-installable; runs in Docker.

Multi-tenant. Built with Django 5.1, Postgres 16, openpyxl. Light/dark theme, off-canvas mobile drawer with finger-tracked swipe gestures, XLSX export.

## Prerequisites

- A Linux host (or any machine) running **Docker Engine 24+** and the **Compose v2 plugin** (`docker compose ...`).
- Roughly 1 GB of free disk for the Postgres volume + image layers.
- A reverse proxy (nginx, Caddy, NPM, Traefik) on the host if you want HTTPS / a public hostname. Optional for LAN-only use.
- A **SimpleFIN Bridge** account if you want bank aggregation — see Step 0. You can skip it and only use the manual-investment / manual-asset / manual-liability features.

## Step 0 — Sign up for SimpleFIN (optional but recommended)

FinLab uses [SimpleFIN Bridge](https://beta-bridge.simplefin.org/) for read-only bank and brokerage aggregation. It's a paid service (~$1.50/month per bridge account, US institutions only).

1. Create an account at <https://beta-bridge.simplefin.org/> and add the bank/brokerage logins you want to track.
2. Keep the tab open — once FinLab is running you'll generate a **Setup Token** here and paste it into the app to link your accounts.

Skip this step entirely if you only want to use the manual investment / asset / liability tracking.

## Step 1 — Clone and configure

```bash
git clone https://github.com/mhamida292/FinLab.git finlab && cd finlab
cp .env.example .env
```

Edit `.env` and set every value marked `changeme`:

| Variable | How to set it |
|---|---|
| `DJANGO_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `FIELD_ENCRYPTION_KEY` | `python3 -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |
| `POSTGRES_PASSWORD` | Pick a strong password |
| `DATABASE_URL` | Must match the password above: `postgres://finance:<password>@db:5432/finance` |
| `WEB_PORT` | A free TCP port on the host (e.g. `3120`) |
| `DJANGO_TIME_ZONE` | Your local IANA tz, e.g. `America/New_York` |

Leave `DJANGO_DEBUG=true` and `DJANGO_ALLOWED_HOSTS=*` for first boot. You'll tighten both once a reverse proxy is in front (see [Reverse proxy](#reverse-proxy-https)).

## Step 2 — Build and start

```bash
docker compose build
docker compose up -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

## Step 3 — Sign in and link your data

Visit `http://<host>:<WEB_PORT>` and log in with the superuser you just created. Additional household members can self-register at `/signup/` (each user's data is isolated).

To link banks via SimpleFIN:

1. Go to **Banking → Link account** in the app.
2. In the SimpleFIN tab from Step 0, generate a new **Setup Token**.
3. Paste the token into FinLab. The app exchanges it for a long-lived access URL (encrypted at rest with `FIELD_ENCRYPTION_KEY`) and pulls your accounts.

Manual investments, assets, and liabilities can be added directly through the **Investments**, **Assets**, and **Liabilities** pages — no SimpleFIN needed.

## Reverse proxy (HTTPS)

Front the container with nginx (or NPM, Caddy, etc.) on the host. Example nginx block:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.example.com;

    # your TLS cert lines

    location / {
        proxy_pass         http://127.0.0.1:<WEB_PORT>;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

Then in `.env` set:
- `DJANGO_DEBUG=false`
- `DJANGO_ALLOWED_HOSTS=your-domain.example.com`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.example.com`

Restart: `docker compose up -d web`.

## Tests

```bash
docker compose exec web pytest -v
```

## Daily auto-refresh

Add a host crontab entry (not inside the container):

```cron
# Sync linked SimpleFIN institutions + refresh manual investment prices + scrape asset prices
0 3 * * * cd /opt/finlab && /usr/bin/docker compose exec -T web python manage.py sync_all >> /var/log/finlab-sync.log 2>&1

# Backup Postgres nightly, keep 30 days
0 2 * * * cd /opt/finlab && /usr/bin/docker compose exec -T web python manage.py dump_backup >> /var/log/finlab-backup.log 2>&1
```

Backups land in `./backups/finance-YYYY-MM-DD-HHMM.sql.gz` (bind-mounted from host). Files older than 30 days are pruned automatically. Off-site copies are your responsibility — `rsync -a ./backups/ user@nas:/backups/finlab/` works fine in another cron entry.

## Restore from backup

```bash
gunzip -c backups/finance-YYYY-MM-DD-HHMM.sql.gz | docker compose exec -T db psql -U finance -d finance
```

## Demo data

Seed a user account with realistic-looking fake data (~6 months of bank transactions, investment holdings, assets, liabilities):

```bash
docker compose exec web python manage.py seed_demo --user <username>
docker compose exec web python manage.py seed_demo --user <username> --clear  # wipe and reseed
```

`--clear` only removes seed-tagged rows (`external_id` starts `demo-` or `name` starts `Demo `); real SimpleFIN data on the same account is left alone.
