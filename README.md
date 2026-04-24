# Personal Finance Dashboard

Self-hosted finance dashboard for momajlab. Django + HTMX. Reachable on the tailnet; public hostname fronted by the homelab's existing nginx.

## First-time setup

```bash
git clone https://github.com/mhamida292/FinanceManager.git finance && cd finance

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
docker compose exec web python manage.py createsuperuser   # mohamed
docker compose exec web python manage.py createsuperuser   # dad
```

Visit `http://<host-or-tailnet-ip>:<WEB_PORT>` from any device on the tailnet.

## Putting nginx in front (when ready for `finance.momajlab.com`)

Add an `nginx` server block on the host:

```nginx
server {
    listen 443 ssl http2;
    server_name finance.momajlab.com;

    # your existing TLS cert lines

    location / {
        proxy_pass         http://127.0.0.1:<WEB_PORT>;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

Then in `.env`, flip `DJANGO_DEBUG=false`, set `DJANGO_ALLOWED_HOSTS=finance.momajlab.com`, and `DJANGO_CSRF_TRUSTED_ORIGINS=https://finance.momajlab.com`. Restart web: `docker compose up -d web`.

## Tests

```bash
docker compose exec web pytest -v
```

## Daily auto-refresh (set up once)

Add a crontab entry on the homelab host (not inside the container):

```bash
crontab -e
```

```cron
# Sync every linked SimpleFIN institution + refresh manual investment prices + scrape asset prices
0 3 * * * cd /opt/finance && /usr/bin/docker compose exec -T web python manage.py sync_all >> /var/log/finance-sync.log 2>&1

# Backup Postgres every night at 2am, keep 30 days
0 2 * * * cd /opt/finance && /usr/bin/docker compose exec -T web python manage.py dump_backup >> /var/log/finance-backup.log 2>&1
```

(Adjust `/opt/finance` to match your install path.)

Backups land in `./backups/finance-YYYY-MM-DD-HHMM.sql.gz` (bind-mounted from the host). Files older than 30 days are pruned automatically. Off-site copies are your responsibility — `rsync -a ./backups/ user@nas:/backups/finance/` works fine in another cron entry.

## Restoring from backup

```bash
gunzip -c backups/finance-2026-04-24-0200.sql.gz | docker compose exec -T db psql -U finance -d finance
```

## Plans / specs

- Spec: `docs/superpowers/specs/2026-04-24-personal-finance-dash-design.md`
- Phase 1 (foundation): `docs/superpowers/plans/2026-04-24-personal-finance-dash-phase-1-foundation.md`
- Phase 2 (banking): `docs/superpowers/plans/2026-04-24-personal-finance-dash-phase-2-banking.md`
- Phase 3 (investments): `docs/superpowers/plans/2026-04-24-personal-finance-dash-phase-3-investments.md`
- Phase 4 (assets): `docs/superpowers/plans/2026-04-24-personal-finance-dash-phase-4-assets.md`
- Phase 5 (dashboard / scheduling): `docs/superpowers/plans/2026-04-24-personal-finance-dash-phase-5-dashboard.md`
