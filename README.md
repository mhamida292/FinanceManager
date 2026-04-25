# FinLab

Self-hosted personal finance dashboard. Multi-tenant, SimpleFIN-aggregated, runs on Docker. Tracks bank accounts, transactions, investments (SimpleFIN + manual), scraped/manual assets, and manual liabilities.

Built with Django 5.1, Postgres 16, openpyxl. Light/dark theme, mobile responsive (PWA-installable), CSS off-canvas drawer with finger-tracked swipe gestures, XLSX export.

## First-time setup

```bash
git clone <repo-url> finlab && cd finlab

cp .env.example .env
# Edit .env:
#   DJANGO_SECRET_KEY:     python3 -c "import secrets; print(secrets.token_urlsafe(50))"
#   FIELD_ENCRYPTION_KEY:  python3 -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
#   POSTGRES_PASSWORD:     choose a strong one
#   DATABASE_URL:          postgres://finance:<that password>@db:5432/finance
#   WEB_PORT:              pick a free port on the host (e.g. 3120)

docker compose build
docker compose up -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Visit `http://<host>:<WEB_PORT>` and sign in. Additional users can self-register at `/signup/`.

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
