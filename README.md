# Personal Finance Dashboard

Self-hosted finance dashboard for momajlab. Django + HTMX, behind Tailscale.

## First-time setup

```bash
git clone <repo> finance && cd finance

cp .env.example .env
# Edit .env:
#   DJANGO_SECRET_KEY: python -c "import secrets; print(secrets.token_urlsafe(50))"
#   POSTGRES_PASSWORD: choose a strong one
#   DATABASE_URL: postgres://finance:<that password>@db:5432/finance
#   CLOUDFLARE_API_TOKEN: scoped DNS-edit token for momajlab.com

# DNS: add an A record finance.momajlab.com -> tailnet IP of this host (gray cloud)

docker compose build
docker compose up -d
docker compose exec web python manage.py createsuperuser   # mohamed
docker compose exec web python manage.py createsuperuser   # dad
```

Visit `https://finance.momajlab.com` from a tailnet device.

## Tests

```bash
docker compose exec web pytest -v
```

## Backups (added in Phase 5)

Nightly `pg_dump` to `./backups/` — see Phase 5 plan.

## Plans / specs

- Spec: `docs/superpowers/specs/2026-04-24-personal-finance-dash-design.md`
- Phase 1 (this): `docs/superpowers/plans/2026-04-24-personal-finance-dash-phase-1-foundation.md`
