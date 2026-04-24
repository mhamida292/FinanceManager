# Personal Finance Dashboard — Phase 5: Dashboard, Scheduling & Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the actual dashboard, automate the daily refresh via host crontab, add backups, and fill in the delete buttons that were deferred from Phases 2 and 3.

**Architecture:** A new `apps/dashboard/` app for the aggregation logic + view + template. Two new management commands — `sync_all` (orchestrates every refresh path) and `dump_backup` (writes a timestamped pg_dump to a bind-mounted volume). Delete views land in their respective apps. Settings page becomes a real sync-history list. No Django Q2; the host's cron daemon calls into the web container.

**Tech Stack:** No new dependencies. Pure orchestration over the abstractions already built.

**Non-Goals for Phase 5:**
- 2FA / TOTP (still v1.1).
- Public Cloudflare Tunnel (user fronts via existing nginx when ready).
- History charts (we have snapshots for portfolio + assets but no chart UI).
- Recurring transaction detection, budgeting, alerts, categorization.

---

## File Structure

```
finance/
├── apps/
│   ├── dashboard/                     # NEW
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── services.py                # net_worth_summary(user) → dataclass
│   │   ├── views.py                   # dashboard view replacing home_redirect
│   │   ├── templates/dashboard/
│   │   │   └── index.html
│   │   └── tests/
│   │       ├── __init__.py
│   │       └── test_services.py
│   ├── banking/
│   │   ├── views.py                   # MODIFIED: add delete_institution + delete_account
│   │   ├── urls.py                    # MODIFIED: add 2 routes
│   │   ├── templates/banking/
│   │   │   ├── institution_confirm_delete.html   # NEW
│   │   │   └── account_confirm_delete.html        # NEW
│   │   ├── tests/test_views.py        # MODIFIED: delete tests
│   │   └── management/                # NEW
│   │       ├── __init__.py
│   │       └── commands/
│   │           ├── __init__.py
│   │           ├── sync_all.py        # orchestrator (or could live elsewhere — see note)
│   │           └── dump_backup.py
│   ├── investments/
│   │   ├── views.py                   # MODIFIED: add delete_account view
│   │   ├── urls.py                    # MODIFIED: add 1 route
│   │   ├── templates/investments/
│   │   │   └── account_confirm_delete.html  # NEW
│   │   └── tests/test_views.py        # MODIFIED: delete tests
│   └── accounts/
│       ├── views.py                   # MODIFIED: SettingsView shows sync history + per-row sync buttons
│       └── templates/accounts/
│           └── settings.html          # MODIFIED: real sync-history layout
├── backups/                           # bind-mount target (gitignored, exists from earlier compose plan)
└── compose.yml                        # MODIFIED: bind-mount ./backups into web container
```

Note on placement: `sync_all.py` and `dump_backup.py` live under `apps/banking/management/commands/` because Django requires management commands to be in an INSTALLED_APP, and banking is the most foundational. Naming-wise we could put them in dashboard, but banking already has the apps bus, so keeping them there reduces app-coupling.

---

## Task 1: Backups bind-mount

**Files:** Modify `compose.yml`

- [ ] **Step 1: Read `compose.yml`. Find the `web:` service block.** Add `volumes:` after `ports:`:

```yaml
  web:
    build: .
    restart: unless-stopped
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "${WEB_PORT:-8000}:8000"
    volumes:
      - ./backups:/backups
```

- [ ] **Step 2: Commit**

```bash
git add compose.yml
git commit -m "build(dashboard): bind-mount ./backups into web container"
```

---

## Task 2: `dump_backup` management command

**Files:** Create `apps/banking/management/__init__.py`, `apps/banking/management/commands/__init__.py`, `apps/banking/management/commands/dump_backup.py`

- [ ] **Step 1: Both `__init__.py` files** — empty.

- [ ] **Step 2: Write `apps/banking/management/commands/dump_backup.py`**

```python
"""Dump the Postgres database to /backups/finance-YYYY-MM-DD-HHMM.sql.gz.

Intended to be invoked nightly by the host crontab:
    0 2 * * * cd /opt/finance && docker compose exec -T web python manage.py dump_backup

Retention: deletes backup files in /backups/ older than RETENTION_DAYS.
"""
import gzip
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

BACKUP_DIR = Path("/backups")
RETENTION_DAYS = 30


class Command(BaseCommand):
    help = "Dump Postgres to a gzipped SQL file in /backups/, then prune old ones."

    def handle(self, *args, **options):
        if not BACKUP_DIR.is_dir():
            self.stderr.write(self.style.ERROR(f"{BACKUP_DIR} does not exist — check the compose bind-mount."))
            return

        db = settings.DATABASES["default"]
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        target = BACKUP_DIR / f"finance-{timestamp}.sql.gz"

        env = {
            **os.environ,
            "PGPASSWORD": db["PASSWORD"],
        }
        cmd = [
            "pg_dump",
            "--host", db["HOST"],
            "--port", str(db["PORT"] or 5432),
            "--username", db["USER"],
            "--dbname", db["NAME"],
            "--format", "plain",
            "--no-owner",
            "--no-privileges",
        ]
        self.stdout.write(f"[backup] dumping to {target} ...")
        try:
            with gzip.open(target, "wb") as gz:
                proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                gz.write(proc.stdout)
        except subprocess.CalledProcessError as exc:
            target.unlink(missing_ok=True)
            self.stderr.write(self.style.ERROR(f"pg_dump failed: {exc.stderr.decode()[:500]}"))
            return

        size_mb = target.stat().st_size / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(f"[backup] wrote {target.name} ({size_mb:.2f} MB)"))

        cutoff = time.time() - RETENTION_DAYS * 86400
        pruned = 0
        for f in BACKUP_DIR.glob("finance-*.sql.gz"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                pruned += 1
        if pruned:
            self.stdout.write(f"[backup] pruned {pruned} backup(s) older than {RETENTION_DAYS} days")
```

`pg_dump` is included in the `postgres-client` package which we may need to add to the Dockerfile. Note: the existing Dockerfile installs `libpq-dev` but not the actual `postgresql-client` binary that ships `pg_dump`. We need to add it.

- [ ] **Step 3: Modify `Dockerfile`** to install postgresql-client. Find the `apt-get install` line:

```dockerfile
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*
```

Add `postgresql-client`:

```dockerfile
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential libpq-dev postgresql-client curl \
 && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 4: Commit**

```bash
git add apps/banking/management/ Dockerfile
git commit -m "feat(dashboard): dump_backup command + postgresql-client in image"
```

---

## Task 3: `sync_all` management command

**Files:** Create `apps/banking/management/commands/sync_all.py`

- [ ] **Step 1: Write the file**

```python
"""Run every refresh path: SimpleFIN bank sync, SimpleFIN investment sync,
yfinance price refresh on manual investments, scraped asset refresh.

Runs across ALL users in one shot. Designed for nightly host-crontab invocation:
    0 3 * * * cd /opt/finance && docker compose exec -T web python manage.py sync_all
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.assets.services import refresh_scraped_assets
from apps.banking.models import Institution
from apps.banking.services import sync_institution
from apps.investments.services import refresh_manual_prices, sync_simplefin_investments

User = get_user_model()


class Command(BaseCommand):
    help = "Refresh all bank data, investment data, manual investment prices, and scraped asset prices."

    def handle(self, *args, **options):
        # 1. SimpleFIN: banking
        for inst in Institution.objects.all():
            try:
                result = sync_institution(inst)
                self.stdout.write(f"[bank] {inst}: {result.transactions_created} new txns, {result.accounts_updated} accounts updated")
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"[bank] {inst} FAILED: {exc}"))

        # 2. SimpleFIN: investments
        for inst in Institution.objects.all():
            try:
                result = sync_simplefin_investments(inst)
                self.stdout.write(f"[invest] {inst}: {result.holdings_updated} holdings updated, {result.holdings_manual_basis_preserved} manual basis preserved")
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"[invest] {inst} FAILED: {exc}"))

        # 3. yfinance: manual investment prices, per user
        for user in User.objects.all():
            try:
                n = refresh_manual_prices(user=user)
                if n:
                    self.stdout.write(f"[prices] {user.username}: refreshed {n} manual holding(s)")
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"[prices] {user.username} FAILED: {exc}"))

        # 4. Scraped assets, per user
        for user in User.objects.all():
            try:
                result = refresh_scraped_assets(user=user)
                if result.updated or result.failed:
                    self.stdout.write(f"[assets] {user.username}: refreshed {result.updated}, failed {len(result.failed)}")
                    for asset_id, err in result.failed:
                        self.stderr.write(self.style.WARNING(f"  asset {asset_id}: {err}"))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"[assets] {user.username} FAILED: {exc}"))

        self.stdout.write(self.style.SUCCESS("[sync_all] done"))
```

- [ ] **Step 2: Commit**

```bash
git add apps/banking/management/commands/sync_all.py
git commit -m "feat(dashboard): sync_all command — host crontab orchestrator"
```

---

## Task 4: Dashboard service — net-worth aggregation

**Files:** Create `apps/dashboard/__init__.py`, `apps/dashboard/apps.py`, `apps/dashboard/services.py`. Modify `config/settings.py`.

- [ ] **Step 1: `apps/dashboard/__init__.py`** — empty.

- [ ] **Step 2: `apps/dashboard/apps.py`**

```python
from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dashboard"
    label = "dashboard"
```

- [ ] **Step 3: Add to `INSTALLED_APPS`** in `config/settings.py` — add `"apps.dashboard",` after `"apps.assets",`. Final relevant block:

```python
    "apps.accounts",
    "apps.banking",
    "apps.investments",
    "apps.assets",
    "apps.dashboard",
    "apps.providers",
```

- [ ] **Step 4: Write `apps/dashboard/services.py`**

```python
from dataclasses import dataclass, field
from decimal import Decimal

from apps.assets.models import Asset
from apps.banking.models import Account, Transaction
from apps.investments.models import Holding


@dataclass
class NetWorthSummary:
    cash: Decimal = Decimal("0")
    investments: Decimal = Decimal("0")
    assets: Decimal = Decimal("0")
    cash_account_count: int = 0
    investment_holding_count: int = 0
    asset_count: int = 0
    recent_transactions: list = field(default_factory=list)

    @property
    def net_worth(self) -> Decimal:
        return self.cash + self.investments + self.assets


def net_worth_summary(user, recent_txn_limit: int = 10) -> NetWorthSummary:
    """Aggregate everything visible to this user into a single dashboard payload."""
    summary = NetWorthSummary()

    # Cash: bank-account balances. Treat credit-card balances (negative balance OR type='credit') as debt.
    for acc in Account.objects.for_user(user):
        if acc.type == "credit":
            summary.cash -= abs(acc.balance)
        else:
            summary.cash += acc.balance
        summary.cash_account_count += 1

    # Investments: sum of holdings' market_value
    for h in Holding.objects.for_user(user):
        summary.investments += h.market_value
        summary.investment_holding_count += 1

    # Assets: sum of current_value
    for a in Asset.objects.for_user(user):
        summary.assets += a.current_value
        summary.asset_count += 1

    summary.recent_transactions = list(
        Transaction.objects.for_user(user)
        .select_related("account", "account__institution")
        .order_by("-posted_at", "-id")[:recent_txn_limit]
    )

    return summary
```

- [ ] **Step 5: Commit**

```bash
git add apps/dashboard/ config/settings.py
git commit -m "feat(dashboard): app skeleton + net_worth_summary service"
```

---

## Task 5: Dashboard service tests

**Files:** Create `apps/dashboard/tests/__init__.py` and `apps/dashboard/tests/test_services.py`

- [ ] **Step 1: `__init__.py`** — empty.

- [ ] **Step 2: Write the test**

```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.assets.models import Asset
from apps.banking.models import Account, Institution, Transaction
from apps.dashboard.services import net_worth_summary
from apps.investments.models import Holding, InvestmentAccount

User = get_user_model()


@pytest.mark.django_db
def test_net_worth_aggregates_across_apps():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")

    # Cash: $1500
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    Account.objects.create(institution=inst, name="Checking", type="checking", balance=Decimal("2000"), external_id="A1")
    Account.objects.create(institution=inst, name="Card", type="credit", balance=Decimal("500"), external_id="A2")

    # Investments: $1800
    inv = InvestmentAccount.objects.create(user=user, source="manual", name="IRA", broker="Fidelity")
    Holding.objects.create(investment_account=inv, symbol="VTI", shares=Decimal("10"),
                            current_price=Decimal("180"), market_value=Decimal("1800"))

    # Assets: $20000 ($18000 car + $2000 gold)
    Asset.objects.create(user=user, kind="manual", name="Car", current_value=Decimal("18000"))
    Asset.objects.create(user=user, kind="scraped", name="Gold Eagle",
                          source_url="https://x", quantity=Decimal("1"), current_value=Decimal("2000"))

    Transaction.objects.create(account=Account.objects.get(name="Checking"),
                                posted_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
                                amount=Decimal("-50"), description="coffee", external_id="T1")

    summary = net_worth_summary(user)

    assert summary.cash == Decimal("1500")  # 2000 - 500 (credit)
    assert summary.investments == Decimal("1800")
    assert summary.assets == Decimal("20000")
    assert summary.net_worth == Decimal("23300")
    assert summary.cash_account_count == 2
    assert summary.investment_holding_count == 1
    assert summary.asset_count == 2
    assert len(summary.recent_transactions) == 1


@pytest.mark.django_db
def test_net_worth_isolation():
    alice = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    bob = User.objects.create_user(username="bob", password="correct-horse-battery-staple-bob")
    Asset.objects.create(user=alice, kind="manual", name="Alice", current_value=Decimal("100"))
    Asset.objects.create(user=bob, kind="manual", name="Bob", current_value=Decimal("99"))

    assert net_worth_summary(alice).net_worth == Decimal("100")
    assert net_worth_summary(bob).net_worth == Decimal("99")


@pytest.mark.django_db
def test_empty_user():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    summary = net_worth_summary(user)
    assert summary.net_worth == Decimal("0")
    assert summary.recent_transactions == []
```

- [ ] **Step 3: Commit**

```bash
git add apps/dashboard/tests/
git commit -m "test(dashboard): net_worth aggregation across apps + isolation"
```

---

## Task 6: Dashboard view + template + replace home_redirect

**Files:**
- Create: `apps/dashboard/views.py`
- Create: `apps/dashboard/templates/dashboard/index.html`
- Modify: `apps/accounts/views.py` (remove `home_redirect`)
- Modify: `apps/accounts/urls.py` (point `home` URL at dashboard view)

- [ ] **Step 1: Write `apps/dashboard/views.py`**

```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import net_worth_summary


@login_required
def dashboard(request):
    summary = net_worth_summary(request.user)
    return render(request, "dashboard/index.html", {"summary": summary})
```

- [ ] **Step 2: Write `apps/dashboard/templates/dashboard/index.html`**

```html
{% extends "base.html" %}
{% block title %}Dashboard{% endblock %}
{% block content %}
<div class="mb-8">
  <div class="text-xs text-slate-500 uppercase tracking-wider">Net worth</div>
  <div class="text-4xl font-bold {% if summary.net_worth < 0 %}text-red-300{% else %}text-emerald-200{% endif %}">
    ${{ summary.net_worth|floatformat:2 }}
  </div>
</div>

<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
  <a href="{% url 'banking:list' %}" class="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded p-5 block">
    <div class="text-xs text-blue-300 uppercase tracking-wider">Cash</div>
    <div class="text-2xl font-mono mt-1 {% if summary.cash < 0 %}text-red-300{% else %}text-blue-100{% endif %}">${{ summary.cash|floatformat:2 }}</div>
    <div class="text-xs text-slate-500 mt-1">{{ summary.cash_account_count }} account{{ summary.cash_account_count|pluralize }}</div>
  </a>
  <a href="{% url 'investments:list' %}" class="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded p-5 block">
    <div class="text-xs text-purple-300 uppercase tracking-wider">Investments</div>
    <div class="text-2xl font-mono mt-1 text-purple-100">${{ summary.investments|floatformat:2 }}</div>
    <div class="text-xs text-slate-500 mt-1">{{ summary.investment_holding_count }} position{{ summary.investment_holding_count|pluralize }}</div>
  </a>
  <a href="{% url 'assets:list' %}" class="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded p-5 block">
    <div class="text-xs text-amber-300 uppercase tracking-wider">Assets</div>
    <div class="text-2xl font-mono mt-1 text-amber-100">${{ summary.assets|floatformat:2 }}</div>
    <div class="text-xs text-slate-500 mt-1">{{ summary.asset_count }} item{{ summary.asset_count|pluralize }}</div>
  </a>
</div>

<div class="text-xs text-slate-500 uppercase tracking-wider mb-2">Recent transactions</div>
{% if not summary.recent_transactions %}
  <div class="bg-slate-900 border border-slate-800 rounded p-6 text-slate-400 text-sm">
    No transactions yet. Link a bank on <a href="{% url 'banking:list' %}" class="text-emerald-400 underline">/banks/</a>.
  </div>
{% else %}
  <div class="bg-slate-900 border border-slate-800 rounded divide-y divide-slate-800">
    {% for tx in summary.recent_transactions %}
    <div class="flex items-center justify-between px-5 py-3">
      <div class="min-w-0 pr-3">
        <div class="font-medium truncate">{{ tx.payee|default:tx.description }}</div>
        <div class="text-xs text-slate-500">
          {{ tx.posted_at|date:"M j" }} · {{ tx.account.effective_name }}
        </div>
      </div>
      <div class="font-mono {% if tx.amount < 0 %}text-red-300{% else %}text-emerald-200{% endif %}">
        {{ tx.amount }}
      </div>
    </div>
    {% endfor %}
  </div>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Modify `apps/accounts/urls.py`** — change the `home` route. Read first. Replace:

```python
    path("", views.home_redirect, name="home"),
```

With:

```python
    path("", dashboard_views.dashboard, name="home"),
```

And add an import at the top:
```python
from apps.dashboard import views as dashboard_views
```

- [ ] **Step 4: Modify `apps/accounts/views.py`** — delete the `home_redirect` function (no longer needed). The remaining functions stay: `SettingsView`, `healthz`. Also remove the now-unused `from django.shortcuts import redirect` import if nothing else uses it.

- [ ] **Step 5: Commit**

```bash
git add apps/dashboard/views.py apps/dashboard/templates/ apps/accounts/urls.py apps/accounts/views.py
git commit -m "feat(dashboard): real / page replaces home_redirect"
```

---

## Task 7: Settings page upgrade — sync history

**Files:**
- Modify: `apps/accounts/views.py` (extend SettingsView)
- Modify: `apps/accounts/templates/accounts/settings.html`

- [ ] **Step 1: Replace `SettingsView` in `apps/accounts/views.py`** — drop the bare `TemplateView` for one that pulls sync state. Read the file, then replace the class:

```python
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.assets.models import Asset
from apps.banking.models import Institution
from apps.investments.models import InvestmentAccount


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["institutions"] = Institution.objects.for_user(user).order_by("-last_synced_at")
        ctx["investment_accounts"] = (
            InvestmentAccount.objects.for_user(user)
            .filter(source="simplefin")
            .order_by("-last_synced_at")
        )
        ctx["scraped_assets"] = (
            Asset.objects.for_user(user)
            .filter(kind="scraped")
            .order_by("-last_priced_at")
        )
        return ctx
```

(Keep the rest of `views.py` — `healthz`, etc.)

- [ ] **Step 2: Replace `apps/accounts/templates/accounts/settings.html`**

```html
{% extends "base.html" %}
{% block title %}Settings{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">Settings</h1>

{% if messages %}
  {% for message in messages %}
  <div class="bg-{% if message.tags == 'error' %}red-900/40 border-red-700 text-red-200{% else %}emerald-900/40 border-emerald-700 text-emerald-200{% endif %} border p-3 rounded text-sm mb-4">
    {{ message }}
  </div>
  {% endfor %}
{% endif %}

<div class="bg-slate-900 border border-slate-800 rounded p-5 mb-6">
  <p class="text-slate-400 text-sm">Signed in as <strong class="text-slate-100">{{ user.username }}</strong>.</p>
</div>

<h2 class="text-lg font-semibold mb-3">Bank institutions</h2>
{% if not institutions %}
  <p class="text-slate-500 text-sm mb-6">None linked. Add one at <a href="{% url 'banking:list' %}" class="text-emerald-400 underline">/banks/</a>.</p>
{% else %}
  <div class="bg-slate-900 border border-slate-800 rounded divide-y divide-slate-800 mb-6">
    {% for inst in institutions %}
    <div class="flex items-center justify-between px-5 py-3">
      <div>
        <div class="font-medium">{{ inst.effective_name }}</div>
        <div class="text-xs text-slate-500">
          Last synced: {% if inst.last_synced_at %}{{ inst.last_synced_at|date:"M j, Y g:i a" }}{% else %}never{% endif %}
        </div>
      </div>
      <div class="flex items-center gap-3">
        <form method="post" action="{% url 'banking:sync' inst.id %}" class="m-0">
          {% csrf_token %}
          <button type="submit" class="text-slate-400 hover:text-white text-sm">⟳ Bank sync</button>
        </form>
        <a href="{% url 'banking:rename_institution' inst.id %}" class="text-slate-500 hover:text-white text-sm">✎</a>
        <a href="{% url 'banking:delete_institution' inst.id %}" class="text-slate-600 hover:text-red-400 text-sm">🗑</a>
      </div>
    </div>
    {% endfor %}
  </div>
{% endif %}

<h2 class="text-lg font-semibold mb-3">SimpleFIN-linked investment accounts</h2>
{% if not investment_accounts %}
  <p class="text-slate-500 text-sm mb-6">None.</p>
{% else %}
  <div class="bg-slate-900 border border-slate-800 rounded divide-y divide-slate-800 mb-6">
    {% for acc in investment_accounts %}
    <div class="flex items-center justify-between px-5 py-3">
      <div>
        <div class="font-medium">{{ acc.effective_name }}</div>
        <div class="text-xs text-slate-500">
          {{ acc.broker }} · Last synced: {% if acc.last_synced_at %}{{ acc.last_synced_at|date:"M j, Y g:i a" }}{% else %}never{% endif %}
        </div>
      </div>
      <a href="{% url 'investments:delete_account' acc.id %}" class="text-slate-600 hover:text-red-400 text-sm">🗑</a>
    </div>
    {% endfor %}
  </div>
{% endif %}

<h2 class="text-lg font-semibold mb-3">Scraped assets</h2>
{% if not scraped_assets %}
  <p class="text-slate-500 text-sm mb-6">None.</p>
{% else %}
  <div class="bg-slate-900 border border-slate-800 rounded divide-y divide-slate-800 mb-6">
    {% for a in scraped_assets %}
    <div class="flex items-center justify-between px-5 py-3">
      <div>
        <div class="font-medium">{{ a.name }}</div>
        <div class="text-xs text-slate-500">
          Last scraped: {% if a.last_priced_at %}{{ a.last_priced_at|date:"M j, Y g:i a" }}{% else %}never{% endif %}
        </div>
      </div>
      <div class="flex items-center gap-3">
        <a href="{% url 'assets:edit' a.id %}" class="text-slate-500 hover:text-white text-sm">✎</a>
      </div>
    </div>
    {% endfor %}
  </div>
{% endif %}

<form method="post" action="{% url 'assets:refresh' %}" class="m-0 mb-6">
  {% csrf_token %}
  <button type="submit" class="text-slate-400 hover:text-white text-sm border border-slate-700 px-3 py-2 rounded">⟳ Refresh all scraped assets</button>
</form>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add apps/accounts/views.py apps/accounts/templates/accounts/settings.html
git commit -m "feat(dashboard): settings page with sync history + per-row actions"
```

---

## Task 8: Delete views — Institution + Account in banking

**Files:**
- Modify: `apps/banking/urls.py` (add 2 routes)
- Modify: `apps/banking/views.py` (add 2 views)
- Create: `apps/banking/templates/banking/institution_confirm_delete.html`
- Create: `apps/banking/templates/banking/account_confirm_delete.html`

- [ ] **Step 1: Modify `apps/banking/urls.py`** — append two routes inside the `urlpatterns` list:

```python
    path("<int:institution_id>/delete/", views.delete_institution, name="delete_institution"),
    path("accounts/<int:account_id>/delete/", views.delete_account, name="delete_account"),
```

- [ ] **Step 2: Append two views to `apps/banking/views.py`**:

```python
@login_required
@require_http_methods(["GET", "POST"])
def delete_institution(request, institution_id):
    institution = get_object_or_404(Institution.objects.for_user(request.user), pk=institution_id)
    if request.method == "POST":
        name = institution.effective_name
        institution.delete()
        messages.success(request, f"Deleted {name} and all related accounts/transactions.")
        return HttpResponseRedirect(reverse("banking:list"))
    return render(request, "banking/institution_confirm_delete.html", {"institution": institution})


@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request, account_id):
    account = get_object_or_404(Account.objects.for_user(request.user), pk=account_id)
    if request.method == "POST":
        name = account.effective_name
        account.delete()
        messages.success(request, f"Deleted {name} and its transactions.")
        return HttpResponseRedirect(reverse("banking:list"))
    return render(request, "banking/account_confirm_delete.html", {"account": account})
```

- [ ] **Step 3: Write `apps/banking/templates/banking/institution_confirm_delete.html`**

```html
{% extends "base.html" %}
{% block title %}Delete {{ institution.effective_name }}{% endblock %}
{% block content %}
<div class="max-w-md mx-auto mt-10">
  <h1 class="text-2xl font-bold mb-4">Delete "{{ institution.effective_name }}"?</h1>
  <p class="text-slate-400 text-sm mb-2">This permanently removes:</p>
  <ul class="text-slate-400 text-sm mb-6 list-disc list-inside">
    <li>The institution row + its encrypted SimpleFIN access URL</li>
    <li>All bank accounts under it ({{ institution.accounts.count }})</li>
    <li>All transactions in those accounts</li>
    <li>All investment accounts linked through this institution</li>
  </ul>
  <form method="post" class="flex items-center gap-3">
    {% csrf_token %}
    <button type="submit" class="bg-red-600 hover:bg-red-500 text-white font-bold px-5 py-2 rounded">Delete</button>
    <a href="{% url 'banking:list' %}" class="text-slate-400 hover:text-white text-sm">Cancel</a>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 4: Write `apps/banking/templates/banking/account_confirm_delete.html`**

```html
{% extends "base.html" %}
{% block title %}Delete {{ account.effective_name }}{% endblock %}
{% block content %}
<div class="max-w-md mx-auto mt-10">
  <h1 class="text-2xl font-bold mb-4">Delete "{{ account.effective_name }}"?</h1>
  <p class="text-slate-400 text-sm mb-6">
    Removes this account and {{ account.transactions.count }} transaction(s). The parent institution stays.
    Subsequent syncs will re-create this account if SimpleFIN still returns it.
  </p>
  <form method="post" class="flex items-center gap-3">
    {% csrf_token %}
    <button type="submit" class="bg-red-600 hover:bg-red-500 text-white font-bold px-5 py-2 rounded">Delete</button>
    <a href="{% url 'banking:list' %}" class="text-slate-400 hover:text-white text-sm">Cancel</a>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 5: Commit**

```bash
git add apps/banking/urls.py apps/banking/views.py apps/banking/templates/
git commit -m "feat(banking): delete views for Institution and Account with confirm pages"
```

---

## Task 9: Delete view — InvestmentAccount

**Files:**
- Modify: `apps/investments/urls.py`
- Modify: `apps/investments/views.py`
- Create: `apps/investments/templates/investments/account_confirm_delete.html`

- [ ] **Step 1: Append to `apps/investments/urls.py`** inside `urlpatterns`:

```python
    path("accounts/<int:account_id>/delete/", views.delete_account, name="delete_account"),
```

- [ ] **Step 2: Append to `apps/investments/views.py`**:

```python
@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request, account_id):
    account = get_object_or_404(InvestmentAccount.objects.for_user(request.user), pk=account_id)
    if request.method == "POST":
        name = account.effective_name
        account.delete()
        messages.success(request, f"Deleted {name} and its holdings.")
        return HttpResponseRedirect(reverse("investments:list"))
    return render(request, "investments/account_confirm_delete.html", {"account": account})
```

- [ ] **Step 3: Write `apps/investments/templates/investments/account_confirm_delete.html`**

```html
{% extends "base.html" %}
{% block title %}Delete {{ account.effective_name }}{% endblock %}
{% block content %}
<div class="max-w-md mx-auto mt-10">
  <h1 class="text-2xl font-bold mb-4">Delete "{{ account.effective_name }}"?</h1>
  <p class="text-slate-400 text-sm mb-6">
    Removes this investment account and {{ account.holdings.count }} holding(s).
    {% if account.source == "simplefin" %}A subsequent SimpleFIN sync will re-create it from the linked institution.{% endif %}
  </p>
  <form method="post" class="flex items-center gap-3">
    {% csrf_token %}
    <button type="submit" class="bg-red-600 hover:bg-red-500 text-white font-bold px-5 py-2 rounded">Delete</button>
    <a href="{% url 'investments:list' %}" class="text-slate-400 hover:text-white text-sm">Cancel</a>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 4: Commit**

```bash
git add apps/investments/urls.py apps/investments/views.py apps/investments/templates/
git commit -m "feat(investments): delete view for InvestmentAccount with confirm page"
```

---

## Task 10: Add delete buttons to existing list pages

**Files:**
- Modify: `apps/banking/templates/banking/banks_list.html`
- Modify: `apps/investments/templates/investments/investments_list.html`

- [ ] **Step 1: Banks list** — read the file. Find the institution header row (the `<div class="flex items-center justify-between px-5 py-3 border-b border-slate-800">` with the rename link and sync form). Add a 🗑 link inside the existing actions div, after the sync form:

```html
          <a href="{% url 'banking:delete_institution' inst.id %}" class="text-slate-600 hover:text-red-400 text-sm" title="Delete">🗑</a>
```

For each account row, find the `<a href="{% url 'banking:rename_account' account.id %}" ...` rename link and add a delete link after it:

```html
          <a href="{% url 'banking:delete_account' account.id %}" class="text-slate-600 hover:text-red-400 text-sm" title="Delete">🗑</a>
```

- [ ] **Step 2: Investments list** — read the file. Find each account row's `<a href="{% url 'investments:account_detail' acc.id %}" ...` link. The delete should be a separate non-overlapping link. Restructure the row from a single `<a>` wrapper into a flex container with the link AND the delete icon side by side. Look for the existing structure and adapt — concretely, change:

```html
    <a href="{% url 'investments:account_detail' acc.id %}" class="block bg-slate-900 border border-slate-800 hover:bg-slate-800/40 rounded">
      <div class="flex items-center justify-between px-5 py-3">
        ...content...
      </div>
    </a>
```

To:

```html
    <div class="bg-slate-900 border border-slate-800 hover:bg-slate-800/40 rounded">
      <div class="flex items-center justify-between px-5 py-3">
        <a href="{% url 'investments:account_detail' acc.id %}" class="flex-1 flex items-center justify-between min-w-0 pr-3">
          <div>
            <div class="font-semibold">{{ acc.effective_name }}</div>
            <div class="text-xs text-slate-500">{{ acc.broker|default:"" }} · {{ acc.get_source_display }}</div>
          </div>
          <div class="text-right">
            {% with total=acc.holdings.all|length %}
            <div class="text-xs text-slate-500">{{ total }} position{{ total|pluralize }}</div>
            {% endwith %}
          </div>
        </a>
        <a href="{% url 'investments:delete_account' acc.id %}" class="text-slate-600 hover:text-red-400 text-sm ml-3" title="Delete">🗑</a>
      </div>
    </div>
```

- [ ] **Step 3: Commit**

```bash
git add apps/banking/templates/banking/banks_list.html apps/investments/templates/investments/investments_list.html
git commit -m "feat(dashboard): delete buttons on banks and investments list pages"
```

---

## Task 11: Tests for new delete views

**Files:**
- Modify: `apps/banking/tests/test_views.py` (append delete tests)
- Modify: `apps/investments/tests/test_views.py` (append delete tests)

- [ ] **Step 1: Append to `apps/banking/tests/test_views.py`**:

```python
def test_delete_institution_cascades(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="ToDelete", access_url="https://x")
    Account.objects.create(institution=inst, name="Acc", type="checking", external_id="A-1")
    r = alice_client.post(reverse("banking:delete_institution", args=[inst.id]))
    assert r.status_code == 302
    assert Institution.objects.filter(pk=inst.id).count() == 0
    assert Account.objects.filter(institution_id=inst.id).count() == 0


def test_delete_institution_forbidden_for_other_user(alice, bob, bob_client):
    inst = Institution.objects.create(user=alice, name="X", access_url="https://x")
    r = bob_client.post(reverse("banking:delete_institution", args=[inst.id]))
    assert r.status_code == 404
    assert Institution.objects.filter(pk=inst.id).count() == 1


def test_delete_account_isolation(alice, bob, bob_client):
    inst = Institution.objects.create(user=alice, name="X", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="Acc", type="checking", external_id="A-1")
    r = bob_client.post(reverse("banking:delete_account", args=[acc.id]))
    assert r.status_code == 404
    assert Account.objects.filter(pk=acc.id).count() == 1
```

- [ ] **Step 2: Append to `apps/investments/tests/test_views.py`**:

```python
def test_delete_investment_account_cascades(alice, alice_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="ToDelete")
    Holding.objects.create(investment_account=acc, symbol="AAPL", shares=Decimal("1"),
                            current_price=Decimal("100"), market_value=Decimal("100"))
    r = alice_client.post(reverse("investments:delete_account", args=[acc.id]))
    assert r.status_code == 302
    assert InvestmentAccount.objects.filter(pk=acc.id).count() == 0
    assert Holding.objects.filter(investment_account_id=acc.id).count() == 0


def test_delete_investment_account_forbidden_for_other_user(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(user=alice, source="manual", broker="F", name="X")
    r = bob_client.post(reverse("investments:delete_account", args=[acc.id]))
    assert r.status_code == 404
```

- [ ] **Step 3: Commit**

```bash
git add apps/banking/tests/test_views.py apps/investments/tests/test_views.py
git commit -m "test(dashboard): delete view auth + isolation + cascade"
```

---

## Task 12: README — host crontab + backups

**Files:** Modify `README.md`

- [ ] **Step 1: Append two new sections to `README.md` after the existing "Tests" section.** Read the current README first, then append:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(dashboard): host crontab + backup/restore instructions"
```

---

## Task 13: USER smoke test

No code changes — final integration gate.

- [ ] **Step 1: Pull, rebuild, migrate**

```bash
cd /opt/finance
git pull
docker compose build web    # picks up postgresql-client + new code
docker compose up -d web
mkdir -p backups            # for the bind mount
docker compose exec web python manage.py migrate    # no new schema, but safe
```

- [ ] **Step 2: Run full test suite — expect ~85 passes** (77 from Phase 4 + ~8 new)

```bash
docker compose exec web pytest -v
```

- [ ] **Step 3: Real dashboard**

Browser: hit `/` → see net worth + Cash/Investments/Assets cards (clickable) + recent transactions. Cards link to their respective sections.

- [ ] **Step 4: Manual run of the orchestrator**

```bash
docker compose exec web python manage.py sync_all
```

Expect output for each user / institution / asset. Re-run is idempotent.

- [ ] **Step 5: Manual run of the backup**

```bash
docker compose exec web python manage.py dump_backup
ls -lh backups/
```

You should see `finance-YYYY-MM-DD-HHMM.sql.gz`. Open it (`gunzip -c | head -50`) to verify it's real SQL.

- [ ] **Step 6: Set up the host crontab** (per the README instructions in Task 12).

- [ ] **Step 7: Test the delete flows in the browser**

- `/banks/` → 🗑 next to an institution → confirm → gone
- `/banks/` → 🗑 next to an account → confirm → gone (institution stays)
- `/investments/` → 🗑 next to an investment account → confirm → gone
- `/settings/` → 🗑 buttons mirror the banks/investments pages

- [ ] **Step 8: No commit — verification only.**

---

## Phase 5 Definition of Done

- [ ] `docker compose exec web pytest -v` reports ~85 tests passing.
- [ ] `/` renders net worth, three category cards, recent transactions list.
- [ ] `python manage.py sync_all` orchestrates SimpleFIN bank + investment + yfinance + scraper without errors.
- [ ] `python manage.py dump_backup` writes a gzipped SQL file to `./backups/` and prunes >30-day-old files.
- [ ] Host crontab is configured for both `sync_all` (3am daily) and `dump_backup` (2am daily).
- [ ] Delete buttons on `/banks/`, `/investments/`, and `/settings/` work with confirm pages.
- [ ] `/settings/` shows last-synced timestamps for institutions, investment accounts, and scraped assets, with per-row sync controls.

When all green, **v1 ships.** All five phases complete. Future work (TOTP, public exposure via Cloudflare Tunnel, history charts, budgets, alerts, recurring detection) is opt-in feature work, not blocking.
