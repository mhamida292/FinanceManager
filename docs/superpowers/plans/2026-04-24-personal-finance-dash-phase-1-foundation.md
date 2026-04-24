# Personal Finance Dashboard — Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a containerized Django site reachable at `https://finance.momajlab.com` over Tailscale, with two real superuser accounts logging in over a real Let's Encrypt cert.

**Architecture:** Django 5 + HTMX (no SPA), Postgres 16, Caddy 2 with the `caddy-dns/cloudflare` plugin for DNS-01 TLS, all wired together with Docker Compose. This phase delivers the empty shell — auth, navigation skeleton, TLS, and Docker plumbing — so every subsequent phase ships features into a working stack.

**Tech Stack:** Python 3.12, Django 5.1, Postgres 16, Caddy 2, Docker Compose, gunicorn, argon2-cffi, dj-database-url, python-dotenv, whitenoise.

**Non-Goals for Phase 1:** Multi-tenancy QuerySet pattern (deferred to Phase 2 when first user-scoped model lands), Django Q2 / scheduled jobs (Phase 5), any real domain models, any HTMX interactivity beyond a sanity check.

---

## File Structure

```
finance/
├── .env.example                # template for runtime secrets
├── .dockerignore               # keep .git, .venv, etc. out of build context
├── Dockerfile                  # web image: Python 3.12 + gunicorn
├── Dockerfile.caddy            # Caddy with Cloudflare DNS plugin baked in
├── compose.yml                 # web + db + proxy
├── Caddyfile                   # finance.momajlab.com → web:8000 with DNS-01 TLS
├── requirements.txt            # pinned Python deps
├── manage.py                   # Django entrypoint
├── README.md                   # first-run instructions
├── config/
│   ├── __init__.py
│   ├── asgi.py
│   ├── wsgi.py
│   ├── settings.py             # single settings module, env-driven
│   ├── urls.py                 # root URL config
│   └── middleware.py           # LoginRequiredMiddleware
├── apps/
│   ├── __init__.py
│   └── accounts/
│       ├── __init__.py
│       ├── apps.py
│       ├── urls.py             # /login/, /logout/, /settings/
│       ├── views.py            # SettingsView placeholder
│       ├── tests/
│       │   ├── __init__.py
│       │   └── test_login.py   # auth redirect + happy path
│       └── templates/
│           ├── base.html       # nav skeleton (Tailwind CDN for now)
│           └── accounts/
│               ├── login.html
│               └── settings.html
└── docs/                       # already exists (spec lives here)
```

Boundary rationale:
- `config/` holds Django wiring only — settings, URL root, middleware. No domain logic.
- `apps/accounts/` owns auth-adjacent UI (login, settings shell). User-data models go in their own apps in later phases.
- `Dockerfile` and `Dockerfile.caddy` are split because they have nothing in common — bundling them in one multi-stage file would just create coupling between the app build and the proxy build.

---

## Task 1: Project skeleton — manage.py, config package, requirements

**Files:**
- Create: `requirements.txt`
- Create: `manage.py`
- Create: `config/__init__.py`
- Create: `config/settings.py`
- Create: `config/urls.py`
- Create: `config/wsgi.py`
- Create: `config/asgi.py`
- Create: `apps/__init__.py`

- [ ] **Step 1: Write `requirements.txt`**

```
Django==5.1.4
psycopg[binary]==3.2.3
dj-database-url==2.3.0
gunicorn==23.0.0
argon2-cffi==23.1.0
python-dotenv==1.0.1
whitenoise==6.8.2
```

- [ ] **Step 2: Write `manage.py`**

```python
#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH? Did you forget to activate a venv?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Create `config/__init__.py` and `apps/__init__.py`**

Both files: empty.

- [ ] **Step 4: Write `config/settings.py`**

```python
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=600),
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "America/New_York")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/settings/"
LOGOUT_REDIRECT_URL = "/login/"

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days
```

- [ ] **Step 5: Write `config/urls.py`**

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
]
```

- [ ] **Step 6: Write `config/wsgi.py`**

```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
```

- [ ] **Step 7: Write `config/asgi.py`**

```python
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_asgi_application()
```

- [ ] **Step 8: Commit**

```bash
git add requirements.txt manage.py config/ apps/__init__.py
git commit -m "chore: add Django project skeleton and dependencies"
```

---

## Task 2: Auth middleware (`LoginRequiredMiddleware`)

**Files:**
- Create: `config/middleware.py`

Why this exists in Phase 1: every page in this app should require auth except the login page itself and the admin. Doing it as a middleware (rather than per-view decorators) makes it impossible to forget on a new page.

- [ ] **Step 1: Write `config/middleware.py`**

```python
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class LoginRequiredMiddleware:
    """Redirect unauthenticated users to LOGIN_URL for all paths
    except whitelisted ones (login, logout, admin login, static).
    """

    EXEMPT_PATH_PREFIXES = (
        "/login/",
        "/logout/",
        "/admin/login/",
        "/static/",
        "/healthz",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            return self.get_response(request)
        if any(request.path.startswith(p) for p in self.EXEMPT_PATH_PREFIXES):
            return self.get_response(request)
        if request.path.startswith("/admin/"):
            # Django admin handles its own login redirect.
            return self.get_response(request)
        return redirect(f"{reverse('login')}?next={request.path}")
```

- [ ] **Step 2: Commit**

```bash
git add config/middleware.py
git commit -m "feat: redirect unauthenticated users to /login/ via middleware"
```

---

## Task 3: `accounts` app skeleton — apps.py, urls, settings view

**Files:**
- Create: `apps/accounts/__init__.py`
- Create: `apps/accounts/apps.py`
- Create: `apps/accounts/urls.py`
- Create: `apps/accounts/views.py`
- Create: `apps/accounts/templates/accounts/settings.html`
- Create: `apps/accounts/templates/accounts/login.html`
- Create: `apps/accounts/templates/base.html`

- [ ] **Step 1: Create `apps/accounts/__init__.py`** — empty file.

- [ ] **Step 2: Write `apps/accounts/apps.py`**

```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
```

- [ ] **Step 3: Write `apps/accounts/urls.py`**

```python
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("", views.home_redirect, name="home"),
    path("healthz", views.healthz, name="healthz"),
]
```

- [ ] **Step 4: Write `apps/accounts/views.py`**

```python
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/settings.html"


def home_redirect(request):
    # Real dashboard ships in Phase 5; for now, send authenticated users to settings.
    return redirect("settings")


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")
```

- [ ] **Step 5: Write `apps/accounts/templates/base.html`**

```html
{% load static %}
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{% block title %}Finance{% endblock %} · momajlab</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
  {% if user.is_authenticated %}
  <nav class="border-b border-slate-800 px-6 py-3 flex items-center justify-between">
    <div class="flex gap-6 items-center">
      <a href="/" class="font-bold text-emerald-400">finance.momajlab</a>
      <a href="/" class="text-slate-300 hover:text-white">Dashboard</a>
      <a href="/banks/" class="text-slate-500">Banks</a>
      <a href="/investments/" class="text-slate-500">Investments</a>
      <a href="/assets/" class="text-slate-500">Assets</a>
      <a href="{% url 'settings' %}" class="text-slate-300 hover:text-white">Settings</a>
    </div>
    <form action="{% url 'logout' %}" method="post" class="m-0">
      {% csrf_token %}
      <button type="submit" class="text-slate-400 hover:text-white">{{ user.username }} · log out</button>
    </form>
  </nav>
  {% endif %}
  <main class="max-w-6xl mx-auto p-6">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

Note: Banks/Investments/Assets links are intentionally rendered as inactive (slate-500 with no real route yet) — they ship in Phases 2–4. This makes the nav skeleton already in its final shape.

- [ ] **Step 6: Write `apps/accounts/templates/accounts/login.html`**

```html
{% extends "base.html" %}
{% block title %}Sign in{% endblock %}
{% block content %}
<div class="max-w-sm mx-auto mt-20">
  <h1 class="text-2xl font-bold text-emerald-400 mb-6">Sign in</h1>
  <form method="post" class="space-y-4">
    {% csrf_token %}
    {% if form.non_field_errors %}
      <div class="bg-red-900/40 border border-red-700 text-red-200 p-3 rounded text-sm">
        {{ form.non_field_errors }}
      </div>
    {% endif %}
    <div>
      <label class="block text-sm text-slate-400 mb-1" for="id_username">Username</label>
      <input id="id_username" name="username" type="text" autocomplete="username" required
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 focus:outline-none focus:border-emerald-500">
    </div>
    <div>
      <label class="block text-sm text-slate-400 mb-1" for="id_password">Password</label>
      <input id="id_password" name="password" type="password" autocomplete="current-password" required
             class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 focus:outline-none focus:border-emerald-500">
    </div>
    <button type="submit" class="w-full bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold py-2 rounded">
      Sign in
    </button>
    <input type="hidden" name="next" value="{{ next }}">
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: Write `apps/accounts/templates/accounts/settings.html`**

```html
{% extends "base.html" %}
{% block title %}Settings{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">Settings</h1>
<div class="bg-slate-900 border border-slate-800 rounded p-6">
  <p class="text-slate-400">Signed in as <strong class="text-slate-100">{{ user.username }}</strong>.</p>
  <p class="text-slate-500 text-sm mt-2">Phase 1 placeholder. Sync history, bank re-link, and password change land in later phases.</p>
</div>
{% endblock %}
```

- [ ] **Step 8: Commit**

```bash
git add apps/accounts/
git commit -m "feat: add accounts app with login, settings shell, and base template"
```

---

## Task 4: Tests for login + middleware redirect

**Files:**
- Create: `apps/accounts/tests/__init__.py`
- Create: `apps/accounts/tests/test_login.py`

- [ ] **Step 1: Create `apps/accounts/tests/__init__.py`** — empty.

- [ ] **Step 2: Write the failing test `apps/accounts/tests/test_login.py`**

```python
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_anonymous_request_to_settings_redirects_to_login():
    client = Client()
    response = client.get(reverse("settings"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_anonymous_request_to_root_redirects_to_login():
    client = Client()
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_login_with_valid_credentials_lands_on_settings():
    User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    client = Client()
    response = client.post(reverse("login"), {"username": "alice", "password": "correct-horse-battery-staple"}, follow=True)
    assert response.status_code == 200
    assert response.request["PATH_INFO"] == reverse("settings")


@pytest.mark.django_db
def test_login_with_bad_password_stays_on_login():
    User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    client = Client()
    response = client.post(reverse("login"), {"username": "alice", "password": "wrong"})
    assert response.status_code == 200
    assert b"Sign in" in response.content


@pytest.mark.django_db
def test_healthz_returns_ok_without_auth():
    client = Client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.content == b"ok"
```

- [ ] **Step 3: Add pytest config**

Append to `requirements.txt`:

```
pytest==8.3.4
pytest-django==4.9.0
```

Create `pytest.ini` at project root:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings
python_files = tests.py test_*.py *_tests.py
addopts = -ra
```

- [ ] **Step 4: Run tests to verify they pass**

Run (locally if you have a venv with deps; otherwise wait until Task 6 and run via `docker compose exec web pytest`):

```bash
pytest apps/accounts/tests/test_login.py -v
```

Expected: 5 tests pass.

If running before Docker is up, you'll need a `.env` with at minimum `DJANGO_SECRET_KEY=insecure-dev-key` and `DATABASE_URL=sqlite:///db.sqlite3`. Don't commit that `.env` — it's already gitignored.

- [ ] **Step 5: Commit**

```bash
git add apps/accounts/tests/ requirements.txt pytest.ini
git commit -m "test: cover login redirect, valid login, bad password, and health check"
```

---

## Task 5: `Dockerfile` for the web image

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Write `.dockerignore`**

```
.git
.gitignore
.venv
venv
env
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
.env
.env.*
backups/
.superpowers/
docs/
README.md
*.md
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput || true

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

The `|| true` on collectstatic is intentional: at build time the `DJANGO_SECRET_KEY` env var isn't set, so collectstatic fails. We'll move the collectstatic step to container start in Task 7's entrypoint instead. Leaving it here for now keeps the image self-bootstrapping if you ever pass a build-arg secret.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "build: add Python 3.12 web Dockerfile and .dockerignore"
```

---

## Task 6: `compose.yml` — web + db services

**Files:**
- Create: `compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Write `.env.example`**

```dotenv
# Copy to .env and fill in. .env is gitignored.

# Django
DJANGO_SECRET_KEY=changeme-generate-with-python-c-secrets-token-urlsafe-50
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=finance.momajlab.com,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://finance.momajlab.com
DJANGO_TIME_ZONE=America/New_York

# Postgres
POSTGRES_DB=finance
POSTGRES_USER=finance
POSTGRES_PASSWORD=changeme

# Computed for Django
DATABASE_URL=postgres://finance:changeme@db:5432/finance

# Caddy / Cloudflare DNS-01 (Phase 1, Task 9)
CLOUDFLARE_API_TOKEN=changeme-scoped-to-momajlab-com-DNS-edit
```

- [ ] **Step 2: Write `compose.yml` (web + db only — proxy lands in Task 9)**

```yaml
services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - finance_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10

  web:
    build: .
    restart: unless-stopped
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    expose:
      - "8000"
    # No ports: published — proxy will reach this over the internal network.

volumes:
  finance_pgdata:
```

For first-run convenience while Caddy isn't wired up yet, you can temporarily add `ports: ["8000:8000"]` under `web` to hit the app directly at `http://localhost:8000`. Remove it once Caddy is in place (Task 9).

- [ ] **Step 3: Commit**

```bash
git add compose.yml .env.example
git commit -m "build: add docker compose with web and db services"
```

---

## Task 7: Container entrypoint — migrations + collectstatic on start

**Files:**
- Create: `entrypoint.sh`
- Modify: `Dockerfile`

Why a separate entrypoint instead of running migrations from compose: when you eventually add a `cron` worker container in Phase 5, you don't want both containers racing to run migrations on startup. The entrypoint handles "is this the web role? then migrate" cleanly.

- [ ] **Step 1: Write `entrypoint.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

ROLE="${ROLE:-web}"

echo "[entrypoint] role=${ROLE}"

if [ "${ROLE}" = "web" ]; then
  echo "[entrypoint] running migrations"
  python manage.py migrate --noinput
  echo "[entrypoint] collecting static"
  python manage.py collectstatic --noinput
fi

exec "$@"
```

- [ ] **Step 2: Modify `Dockerfile`**

Replace the bottom of `Dockerfile` (from `RUN python manage.py collectstatic ...` onward) with:

```dockerfile
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

- [ ] **Step 3: Commit**

```bash
git add entrypoint.sh Dockerfile
git commit -m "build: run migrations and collectstatic on web container start"
```

---

## Task 8: First smoke test — bring it up, run tests, create users

This task has no code changes — it's the integration checkpoint. Do not skip.

- [ ] **Step 1: Create real `.env`**

```bash
cp .env.example .env
# Generate a real secret key:
python -c "import secrets; print(secrets.token_urlsafe(50))"
# Paste output as DJANGO_SECRET_KEY in .env
# Set POSTGRES_PASSWORD and DATABASE_URL to a real password.
```

- [ ] **Step 2: Build and start**

```bash
docker compose build
docker compose up -d
docker compose ps
```

Expected: both `db` (healthy) and `web` (running).

- [ ] **Step 3: Tail web logs and confirm migrations ran**

```bash
docker compose logs web | tail -50
```

Expected: lines mentioning `Applying contenttypes.0001_initial...` and `Applying auth.*` and ending with gunicorn `Listening at: http://0.0.0.0:8000`.

- [ ] **Step 4: Run the test suite inside the container**

```bash
docker compose exec web pytest -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Create both superusers**

```bash
docker compose exec web python manage.py createsuperuser
# username: mohamed, email: <yours>, password: <strong>
docker compose exec web python manage.py createsuperuser
# username: dad, email: <his>, password: <strong>
```

- [ ] **Step 6: Hit the health check**

If you temporarily added `ports: ["8000:8000"]`:

```bash
curl http://localhost:8000/healthz
```

Expected: `ok`

If you didn't, exec into the container:

```bash
docker compose exec web curl -s http://localhost:8000/healthz
```

Expected: `ok`

- [ ] **Step 7: No commit — this is verification only**

If everything passes, move to Task 9. If anything failed, fix it before continuing.

---

## Task 9: `Dockerfile.caddy` — Caddy with Cloudflare DNS plugin baked in

**Files:**
- Create: `Dockerfile.caddy`

The plain `caddy:2` image does not ship with the Cloudflare DNS provider. We build a one-line custom image that does.

- [ ] **Step 1: Write `Dockerfile.caddy`**

```dockerfile
FROM caddy:2.8.4-builder AS builder

RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare

FROM caddy:2.8.4

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile.caddy
git commit -m "build: caddy image with caddy-dns/cloudflare baked in"
```

---

## Task 10: `Caddyfile` for `finance.momajlab.com`

**Files:**
- Create: `Caddyfile`

- [ ] **Step 1: Write `Caddyfile`**

```caddy
{
    # global options
    email mohamed@momajlab.com
}

finance.momajlab.com {
    encode zstd gzip

    tls {
        dns cloudflare {env.CLOUDFLARE_API_TOKEN}
    }

    reverse_proxy web:8000
}
```

- [ ] **Step 2: Commit**

```bash
git add Caddyfile
git commit -m "build: caddy reverse proxy for finance.momajlab.com over DNS-01 TLS"
```

---

## Task 11: Add `proxy` service to `compose.yml`

**Files:**
- Modify: `compose.yml`

- [ ] **Step 1: Replace `compose.yml` with the full version**

```yaml
services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - finance_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10

  web:
    build: .
    restart: unless-stopped
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    expose:
      - "8000"

  proxy:
    build:
      context: .
      dockerfile: Dockerfile.caddy
    restart: unless-stopped
    env_file: .env
    ports:
      - "443:443"
      - "443:443/udp"
      - "80:80"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - web

volumes:
  finance_pgdata:
  caddy_data:
  caddy_config:
```

`caddy_data` is critical — that's where the Let's Encrypt cert and account key live. Losing it means re-issuing certs (which Let's Encrypt rate-limits at 5 issuances/week per FQDN).

- [ ] **Step 2: Commit**

```bash
git add compose.yml
git commit -m "build: add caddy proxy service and persistent cert volume"
```

---

## Task 12: DNS + tailnet IP setup (manual checkpoint)

This task has no code. It's the homelab/network setup that has to happen before Task 13's smoke test will work.

- [ ] **Step 1: Find the homelab's tailnet IP**

On the host that will run this stack:

```bash
tailscale ip -4
```

Expected: a `100.x.x.x` address. Note it.

- [ ] **Step 2: Create the Cloudflare DNS record**

In Cloudflare's dashboard for `momajlab.com`:
- Type: `A`
- Name: `finance`
- IPv4 address: the `100.x.x.x` from Step 1
- Proxy status: **DNS only** (gray cloud, NOT orange). Cloudflare can't proxy a non-routable IP.
- TTL: Auto

- [ ] **Step 3: Create the Cloudflare API token**

In Cloudflare dashboard → My Profile → API Tokens → Create Token → "Edit zone DNS" template.
- Permissions: `Zone : DNS : Edit`
- Zone Resources: `Include : Specific zone : momajlab.com`

Copy the token. Paste into `.env` as `CLOUDFLARE_API_TOKEN=...`. Don't commit `.env`.

- [ ] **Step 4: Verify DNS**

From any machine on your tailnet:

```bash
dig +short finance.momajlab.com
```

Expected: the same `100.x.x.x` you set.

- [ ] **Step 5: No commit — env-only changes**

---

## Task 13: End-to-end smoke test — TLS, login, two users

- [ ] **Step 1: Rebuild and restart with proxy**

```bash
docker compose down
docker compose build
docker compose up -d
docker compose ps
```

Expected: `db` healthy, `web` running, `proxy` running.

- [ ] **Step 2: Watch Caddy provision the cert**

```bash
docker compose logs -f proxy
```

Expected within ~30 seconds: lines about ACME DNS-01 challenge, then `certificate obtained successfully` for `finance.momajlab.com`. Press Ctrl-C to stop tailing.

If you see `solving challenge: presenting for challenge: adding temporary record for zone momajlab.com.: HTTP 4xx` — your API token doesn't have DNS edit permission for that zone. Re-do Task 12, Step 3.

- [ ] **Step 3: Browse to the site from a tailnet device**

Open `https://finance.momajlab.com` in a browser on a tailnet-connected device.

Expected:
- Browser shows a green padlock (real Let's Encrypt cert).
- You're redirected to `/login/?next=/`.
- Log in as `mohamed`. You land on `/settings/` showing "Signed in as mohamed".
- Click "log out". You're back at the login page.
- Log in as `dad`. Same flow.

- [ ] **Step 4: Verify off-tailnet failure (optional but reassuring)**

From a phone on cellular (off your tailnet):

```bash
dig +short finance.momajlab.com
```

You'll get the `100.x.x.x` address — but trying to load `https://finance.momajlab.com` will time out. That's correct: the IP isn't routable on the public internet.

- [ ] **Step 5: No commit — verification only**

---

## Task 14: README — first-run instructions

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add first-run README"
```

---

## Phase 1 Definition of Done

All boxes checked:

- [ ] `docker compose up -d` brings up `db`, `web`, `proxy` (all running).
- [ ] `docker compose exec web pytest -v` reports 5 passing tests.
- [ ] `https://finance.momajlab.com` loads from any tailnet device with a real Let's Encrypt cert (green padlock, no warnings).
- [ ] Both `mohamed` and `dad` can log in and out.
- [ ] Hitting any path while logged out redirects to `/login/?next=...`.
- [ ] `/healthz` returns `ok` without auth.
- [ ] `docker compose down && docker compose up -d` preserves user accounts (Postgres volume works).
- [ ] `docker compose down -v` (destructive, do not run unless intended) would wipe the DB — confirms volume name correctness.

When all green, Phase 1 ships. Move to writing Phase 2 (banking).
