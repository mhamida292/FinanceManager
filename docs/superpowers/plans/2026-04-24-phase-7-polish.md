# Phase 7 — Polish & Power Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the four polish features that round out the Personal Finance Dash: a money template filter applied everywhere, a redesigned Investments page that shows every holding grouped by account, a full Transactions page with filtering + pagination, and a single-workbook XLSX export.

**Architecture:** Four independent feature bundles. Bundle 1 (money filter) is a foundation everything else uses, so it ships first and gets swept into existing templates. Bundles 2-4 are each a vertical slice (model query → view → template → tests). All work is done on branch `phase-7-polish` (already created off master after Phase 8 merge).

**Tech Stack:** Django 5.1, openpyxl 3.x for XLSX export, no new JS dependencies (HTMX not used here — `?page=N` is server-rendered for simplicity and bookmarkability).

---

## File structure

**Bundle 1 — Money filter:**
- Create: `apps/dashboard/templatetags/money.py` (filter lives next to existing `sparkline.py`)
- Create: `apps/dashboard/tests/test_money.py`
- Modify: every template using `|floatformat:2` (sweep)

**Bundle 2 — Investments redesign:**
- Modify: `apps/investments/views.py` — replace `investments_list` body
- Modify: `apps/investments/templates/investments/investments_list.html` — full rewrite as all-holdings-grouped-by-account
- Modify: `apps/investments/tests/test_views.py` — adjust list-view tests

**Bundle 3 — Transactions page + pagination:**
- Modify: `apps/banking/views.py` — add `transactions_list` view
- Modify: `apps/banking/urls.py` — add `path("transactions/", ...)` (top-level mount via accounts urls so URL is `/transactions/`)
- Actually: Modify: `apps/accounts/urls.py` to mount the transactions URL at `/transactions/` since it's a global view
- Create: `apps/banking/templates/banking/transactions_list.html`
- Modify: `apps/dashboard/templates/dashboard/index.html` — wire "See all →" link
- Modify: `apps/accounts/templates/base.html` — add Transactions to sidebar nav (between Dashboard and Banks)
- Modify: `apps/banking/tests/test_views.py` — tests for filtering, pagination, multi-tenant isolation

**Bundle 4 — XLSX export:**
- Modify: `requirements.txt` — add `openpyxl==3.1.5` (latest stable)
- Create: `apps/exports/__init__.py`
- Create: `apps/exports/apps.py`
- Create: `apps/exports/views.py` — `xlsx_export` view
- Create: `apps/exports/services.py` — `build_workbook(user) -> Workbook`
- Create: `apps/exports/urls.py`
- Create: `apps/exports/tests/__init__.py`
- Create: `apps/exports/tests/test_export.py`
- Modify: `config/settings.py` — add `apps.exports` to `INSTALLED_APPS`
- Modify: `config/urls.py` — mount `apps.exports.urls` at `/export/`
- Modify: `apps/accounts/templates/base.html` — add ↓ download icon to top bar (next to ⟳ and ☾)

---

## Bundle 1 — Money template filter (TDD)

**Why first:** Filter is referenced by Bundles 2-4 templates, and the sweep is mechanical — get it done before the bigger features change template structure.

### Task 1: Implement money filter with TDD

**Files:**
- Create: `apps/dashboard/templatetags/money.py`
- Create: `apps/dashboard/tests/test_money.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/dashboard/tests/test_money.py
from decimal import Decimal

from django.template import Context, Template
import pytest


def render(s: str, ctx: dict | None = None) -> str:
    return Template("{% load money %}" + s).render(Context(ctx or {}))


def test_positive_dollar():
    assert render("{{ v|money }}", {"v": Decimal("1234.56")}) == "$1,234.56"


def test_negative_dollar_uses_minus_sign():
    assert render("{{ v|money }}", {"v": Decimal("-1234.56")}) == "−$1,234.56"


def test_zero():
    assert render("{{ v|money }}", {"v": Decimal("0")}) == "$0.00"


def test_large_number_with_commas():
    assert render("{{ v|money }}", {"v": Decimal("1234567.89")}) == "$1,234,567.89"


def test_none_returns_em_dash():
    assert render("{{ v|money }}", {"v": None}) == "—"


def test_float_input():
    assert render("{{ v|money }}", {"v": 1234.5}) == "$1,234.50"


def test_int_input():
    assert render("{{ v|money }}", {"v": 100}) == "$100.00"


def test_string_numeric_input():
    assert render("{{ v|money }}", {"v": "42.7"}) == "$42.70"


def test_garbage_string_returns_em_dash():
    assert render("{{ v|money }}", {"v": "not a number"}) == "—"


def test_signed_kwarg_shows_plus_for_positive():
    """`{{ v|money:'signed' }}` prefixes positives with + (useful for gain/loss)."""
    assert render("{{ v|money:'signed' }}", {"v": Decimal("523.10")}) == "+$523.10"


def test_signed_kwarg_keeps_minus_for_negative():
    assert render("{{ v|money:'signed' }}", {"v": Decimal("-523.10")}) == "−$523.10"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec web pytest apps/dashboard/tests/test_money.py -v`
Expected: ImportError or 11 failures because `money.py` doesn't exist.

- [ ] **Step 3: Implement the filter**

```python
# apps/dashboard/templatetags/money.py
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter(name="money")
def money(value, mode: str = "") -> str:
    """Format a number as US dollar currency.

    - `{{ v|money }}` → '$1,234.56' / '−$1,234.56' / '—' for None or invalid.
    - `{{ v|money:"signed" }}` → adds '+' prefix on positives ('+$523.10').
    """
    if value is None or value == "":
        return "—"
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "—"

    is_negative = d < 0
    abs_str = f"{abs(d):,.2f}"
    formatted = f"${abs_str}"

    if is_negative:
        return f"−{formatted}"  # U+2212 minus sign for typographic alignment with monospace font
    if mode == "signed":
        return f"+{formatted}"
    return formatted
```

- [ ] **Step 4: Run tests to verify pass**

Run: `docker compose exec web pytest apps/dashboard/tests/test_money.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/dashboard/templatetags/money.py apps/dashboard/tests/test_money.py
git commit -m "feat(money): {{ value|money }} template filter ($ + commas + signed mode)"
```

### Task 2: Sweep templates to use `|money`

**Files:**
- Modify: every `.html` containing `|floatformat:2` (use grep to find)

Replace patterns like `${{ x|floatformat:2 }}` with `{{ x|money }}` and `{% if amount >= 0 %}+{% endif %}${{ amount|floatformat:2 }}` with `{{ amount|money:"signed" }}`. Be careful with templates that already render the `$` — the new filter includes it.

- [ ] **Step 1: Locate every template using `|floatformat:2`**

Run: grep across `apps/**/*.html` for `floatformat:2`.

- [ ] **Step 2: For each template, add `{% load money %}` at top (right after `{% extends %}`/`{% block %}`) and replace currency formatting**

Examples:
- `${{ v|floatformat:2 }}` → `{{ v|money }}`
- `−${{ v|floatformat:2 }}` → `{{ v|money }}` (filter already handles sign)
- `{% if amount >= 0 %}+{% endif %}${{ amount|floatformat:2 }}` → `{{ amount|money:"signed" }}`

Files known to need it (found pre-plan):
- `apps/dashboard/templates/dashboard/index.html`
- `apps/banking/templates/banking/banks_list.html`
- `apps/banking/templates/banking/account_detail.html`
- `apps/investments/templates/investments/investments_list.html`
- `apps/investments/templates/investments/account_detail.html`
- `apps/assets/templates/assets/assets_list.html`
- `apps/liabilities/templates/liabilities/liabilities_list.html`

For any template that conditionally colors negatives (e.g. `style="color: {% if x < 0 %}red{% else %}green{% endif %};"`), keep that conditional. The filter only changes the text rendering, not the color logic.

- [ ] **Step 3: Visually verify by reading each modified template**

Confirm no double-`$`, no leftover `floatformat:2` for currency.

- [ ] **Step 4: Run full test suite to catch any string-match assertions**

Run: `docker compose exec web pytest -q`
Expected: all green. If a test asserts on the old `$1234.56` text, update it to assert `$1,234.56`.

- [ ] **Step 5: Commit**

```bash
git add apps/
git commit -m "refactor(templates): use {{ |money }} filter for all currency formatting"
```

---

## Bundle 2 — Investments redesign as all-holdings-by-account

**Why now:** Investments is the most data-rich page. Sweeping in Bundle 1 lands the money filter, then this rewrite gives the page a meaningful default view.

**Design:**
- Page top: portfolio total (large, gain/loss color), portfolio gain $ and gain % (smaller), updated timestamp
- For each investment account, a section card containing:
  - Section header: account name (large) + broker (muted) + section total (right, prominent) + section gain $/% (color)
  - Holdings table (desktop) / stacked cards (mobile) — same Phase 8 pattern
- Account cash balance shown in the section header subtext (e.g. "Robinhood · brokerage · $1,250 cash")
- Empty state if no holdings in the account but cash exists: show just the cash line
- Below all sections: link "+ Manual account" + "⟳ Refresh prices" form

### Task 3: Rewrite investments_list view to compute per-account aggregates

**Files:**
- Modify: `apps/investments/views.py:30-44`

- [ ] **Step 1: Replace investments_list with the enriched version**

```python
@login_required
def investments_list(request):
    accounts = (
        InvestmentAccount.objects
        .for_user(request.user)
        .prefetch_related("holdings")
        .order_by("broker", "name")
    )
    sections = []
    portfolio_value = Decimal("0")
    portfolio_cost = Decimal("0")
    for acc in accounts:
        holdings = list(acc.holdings.all().order_by("symbol"))
        holdings_value = sum((h.market_value for h in holdings), Decimal("0"))
        holdings_cost = sum((h.cost_basis or Decimal("0") for h in holdings), Decimal("0"))
        section_total = holdings_value + acc.cash_balance
        section_gain = (holdings_value - holdings_cost) if holdings_cost else None
        section_gain_pct = (section_gain / holdings_cost * 100) if section_gain is not None and holdings_cost else None
        sections.append({
            "account": acc,
            "holdings": holdings,
            "holdings_value": holdings_value,
            "section_total": section_total,
            "section_gain": section_gain,
            "section_gain_pct": section_gain_pct,
        })
        portfolio_value += section_total
        portfolio_cost += holdings_cost
    portfolio_gain = (portfolio_value - acc.cash_balance - portfolio_cost) if portfolio_cost else None  # gain excludes cash
    # Recompute portfolio_gain correctly: gain = sum of holdings_value across accounts - portfolio_cost
    portfolio_holdings_value = sum((s["holdings_value"] for s in sections), Decimal("0"))
    portfolio_gain = (portfolio_holdings_value - portfolio_cost) if portfolio_cost else None
    portfolio_gain_pct = (portfolio_gain / portfolio_cost * 100) if portfolio_gain is not None and portfolio_cost else None
    return render(request, "investments/investments_list.html", {
        "sections": sections,
        "portfolio_value": portfolio_value,
        "portfolio_gain": portfolio_gain,
        "portfolio_gain_pct": portfolio_gain_pct,
    })
```

(Note: removed the buggy intermediate `portfolio_gain` line — final version recomputes from `portfolio_holdings_value`.)

- [ ] **Step 2: Run existing tests, expect failures**

Run: `docker compose exec web pytest apps/investments/tests/test_views.py -v`
Expected: tests that check for `accounts` or `grand_total` in context will fail.

### Task 4: Rewrite investments_list.html template

**Files:**
- Modify: `apps/investments/templates/investments/investments_list.html` — full rewrite

- [ ] **Step 1: Replace the template body**

```html
{% extends "base.html" %}
{% load money %}
{% block title %}Investments{% endblock %}
{% block content %}

<div class="flex items-end justify-between mb-6 flex-wrap gap-4">
  <div>
    <div class="text-[10px] uppercase tracking-widest" style="color: var(--dim);">Portfolio value</div>
    <div class="text-3xl sm:text-4xl font-bold num mt-1" style="color: var(--accent-positive);">{{ portfolio_value|money }}</div>
    {% if portfolio_gain is not None %}
    <div class="text-sm num mt-1" style="color: {% if portfolio_gain < 0 %}var(--accent-negative){% else %}var(--accent-positive){% endif %};">
      {{ portfolio_gain|money:"signed" }}
      {% if portfolio_gain_pct is not None %}
        · {% if portfolio_gain_pct >= 0 %}+{% endif %}{{ portfolio_gain_pct|floatformat:2 }}%
      {% endif %}
      <span style="color: var(--muted);">all-time gain/loss</span>
    </div>
    {% endif %}
  </div>
  <div class="flex gap-2">
    <form method="post" action="{% url 'investments:refresh_prices' %}" class="m-0">
      {% csrf_token %}
      <button type="submit" class="text-sm border px-3 py-2 rounded" style="border-color: var(--border); color: var(--muted);">⟳ Refresh prices</button>
    </form>
    <a href="{% url 'investments:add_account' %}" class="font-bold px-4 py-2 rounded" style="background: var(--accent-positive); color: var(--bg);">+ Manual account</a>
  </div>
</div>

{% if messages %}
  {% for message in messages %}
  <div class="border p-3 rounded text-sm mb-4"
       style="{% if message.tags == 'error' %}background: var(--tint-lia); border-color: var(--accent-lia); color: var(--accent-lia);{% elif message.tags == 'warning' %}background: var(--tint-assets); border-color: var(--accent-assets); color: var(--accent-assets);{% else %}background: var(--tint-positive); border-color: var(--accent-positive); color: var(--accent-positive);{% endif %}">
    {{ message }}
  </div>
  {% endfor %}
{% endif %}

{% if not sections %}
  <div class="rounded border p-6 text-sm" style="background: var(--surface); border-color: var(--border); color: var(--muted);">
    No investment accounts yet. Click <strong style="color: var(--text);">+ Manual account</strong> to add a brokerage SimpleFIN doesn't reach.
  </div>
{% else %}
  <div class="space-y-6">
    {% for s in sections %}
    <section class="rounded border" style="background: var(--surface); border-color: var(--border);">

      {# Account section header #}
      <div class="px-5 py-4 flex items-end justify-between gap-3 flex-wrap" style="border-bottom: 1px solid var(--border);">
        <div class="min-w-0">
          <a href="{% url 'investments:account_detail' s.account.id %}" class="block">
            <div class="font-semibold text-lg truncate">{{ s.account.effective_name }}</div>
            <div class="text-xs" style="color: var(--muted);">
              {{ s.account.broker|default:s.account.get_source_display }}
              {% if s.account.cash_balance %} · {{ s.account.cash_balance|money }} cash{% endif %}
            </div>
          </a>
        </div>
        <div class="text-right">
          <div class="num font-bold text-lg whitespace-nowrap" style="color: var(--accent-positive);">{{ s.section_total|money }}</div>
          {% if s.section_gain is not None %}
          <div class="text-xs num" style="color: {% if s.section_gain < 0 %}var(--accent-negative){% else %}var(--accent-positive){% endif %};">
            {{ s.section_gain|money:"signed" }}
            {% if s.section_gain_pct is not None %}· {% if s.section_gain_pct >= 0 %}+{% endif %}{{ s.section_gain_pct|floatformat:2 }}%{% endif %}
          </div>
          {% endif %}
        </div>
      </div>

      {# Holdings — empty state if no holdings #}
      {% if not s.holdings %}
        <div class="px-5 py-4 text-sm" style="color: var(--muted);">No holdings — cash only.</div>
      {% else %}
        {# Desktop table #}
        <div class="hidden md:block">
          <table class="w-full text-sm">
            <thead style="border-bottom: 1px solid var(--border); color: var(--dim);">
              <tr class="text-[10px] uppercase tracking-widest">
                <th class="px-5 py-2 text-left">Symbol</th>
                <th class="px-5 py-2 text-right">Shares</th>
                <th class="px-5 py-2 text-right">Price</th>
                <th class="px-5 py-2 text-right">Value</th>
                <th class="px-5 py-2 text-right">Cost basis</th>
                <th class="px-5 py-2 text-right">Gain / loss</th>
              </tr>
            </thead>
            <tbody>
              {% for h in s.holdings %}
              <tr style="border-top: 1px solid var(--border);">
                <td class="px-5 py-2 num font-semibold">
                  <a href="{% url 'investments:account_detail' s.account.id %}">{{ h.symbol }}</a>
                </td>
                <td class="px-5 py-2 text-right num">{{ h.shares }}</td>
                <td class="px-5 py-2 text-right num">{{ h.current_price|money }}</td>
                <td class="px-5 py-2 text-right num">{{ h.market_value|money }}</td>
                <td class="px-5 py-2 text-right num">{{ h.cost_basis|money }}</td>
                <td class="px-5 py-2 text-right num"
                    style="color: {% if h.gain_loss and h.gain_loss < 0 %}var(--accent-negative){% elif h.gain_loss %}var(--accent-positive){% endif %};">
                  {% if h.gain_loss is not None %}
                    {{ h.gain_loss|money:"signed" }}
                    <div class="text-xs" style="color: var(--muted);">{% if h.gain_loss_percent >= 0 %}+{% endif %}{{ h.gain_loss_percent|floatformat:2 }}%</div>
                  {% else %}<span style="color: var(--dim);">—</span>{% endif %}
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>

        {# Mobile cards #}
        <div class="md:hidden">
          {% for h in s.holdings %}
          <div class="px-5 py-3" style="border-top: 1px solid var(--border);">
            <div class="flex items-baseline justify-between gap-3">
              <div class="num font-semibold truncate min-w-0">{{ h.symbol }}</div>
              <div class="num font-semibold whitespace-nowrap" style="color: var(--accent-positive);">{{ h.market_value|money }}</div>
            </div>
            <div class="flex items-baseline justify-between gap-3 mt-1">
              <div class="text-xs num" style="color: var(--muted);">
                <span class="num">{{ h.shares }}</span> sh @ <span class="num">{{ h.current_price|money }}</span>
              </div>
              {% if h.gain_loss is not None %}
              <div class="text-xs num whitespace-nowrap" style="color: {% if h.gain_loss < 0 %}var(--accent-negative){% else %}var(--accent-positive){% endif %};">
                {{ h.gain_loss|money:"signed" }}
                · {% if h.gain_loss_percent >= 0 %}+{% endif %}{{ h.gain_loss_percent|floatformat:2 }}%
              </div>
              {% endif %}
            </div>
          </div>
          {% endfor %}
        </div>
      {% endif %}
    </section>
    {% endfor %}
  </div>
{% endif %}
{% endblock %}
```

### Task 5: Update investments tests for new context shape

**Files:**
- Modify: `apps/investments/tests/test_views.py`

- [ ] **Step 1: Replace `accounts` / `grand_total` assertions with `sections` / `portfolio_value`**

The tests checking the list view should now assert that `sections` is in context with the right shape. Read the file, find the relevant tests, and update to assert e.g. `b"Portfolio value" in response.content` and the sum of section totals.

- [ ] **Step 2: Run tests**

Run: `docker compose exec web pytest apps/investments/ -v`
Expected: all pass.

- [ ] **Step 3: Commit Bundle 2**

```bash
git add apps/investments/
git commit -m "feat(investments): redesign list as all-holdings-by-account with section totals"
```

---

## Bundle 3 — /transactions/ page + filters + pagination + nav

### Task 6: Add Transactions URL + view

**Files:**
- Modify: `apps/banking/views.py` — add `transactions_list`
- Modify: `apps/accounts/urls.py` — add `path("transactions/", banking_views.transactions_list, name="transactions")`

- [ ] **Step 1: Add the view**

```python
# apps/banking/views.py — append below existing imports
from datetime import date, timedelta
from django.core.paginator import Paginator
from django.db.models import Q

# ... existing views ...

@login_required
def transactions_list(request):
    qs = (
        Transaction.objects
        .filter(account__institution__user=request.user)
        .select_related("account", "account__institution")
        .order_by("-posted_at", "-id")
    )

    # Filters
    account_id = request.GET.get("account")
    if account_id and account_id.isdigit():
        qs = qs.filter(account_id=int(account_id))

    preset = request.GET.get("range", "")
    today = date.today()
    if preset == "30d":
        qs = qs.filter(posted_at__gte=today - timedelta(days=30))
    elif preset == "90d":
        qs = qs.filter(posted_at__gte=today - timedelta(days=90))
    elif preset == "ytd":
        qs = qs.filter(posted_at__gte=date(today.year, 1, 1))
    elif preset == "1y":
        qs = qs.filter(posted_at__gte=today - timedelta(days=365))

    search = (request.GET.get("q") or "").strip()
    if search:
        qs = qs.filter(Q(payee__icontains=search) | Q(description__icontains=search) | Q(memo__icontains=search))

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    accounts = Account.objects.for_user(request.user).order_by("institution__name", "name")

    return render(request, "banking/transactions_list.html", {
        "page_obj": page_obj,
        "accounts": accounts,
        "selected_account": int(account_id) if account_id and account_id.isdigit() else None,
        "selected_range": preset,
        "search": search,
    })
```

- [ ] **Step 2: Mount the URL globally (so it's `/transactions/`, not `/banks/transactions/`)**

```python
# apps/accounts/urls.py — add import and path
from apps.banking import views as banking_views
# ... existing patterns ...
    path("transactions/", banking_views.transactions_list, name="transactions"),
```

### Task 7: Build the transactions_list.html template

**Files:**
- Create: `apps/banking/templates/banking/transactions_list.html`

- [ ] **Step 1: Write the template**

```html
{% extends "base.html" %}
{% load money %}
{% block title %}Transactions{% endblock %}
{% block content %}

<div class="flex items-end justify-between mb-6 flex-wrap gap-3">
  <h1 class="text-2xl font-bold">Transactions</h1>
  <div class="text-xs num" style="color: var(--muted);">
    Showing <span class="num">{{ page_obj.start_index }}</span>–<span class="num">{{ page_obj.end_index }}</span> of <span class="num">{{ page_obj.paginator.count }}</span>
  </div>
</div>

{# Filter toolbar #}
<form method="get" class="rounded border p-3 mb-4 flex flex-wrap gap-2 items-center" style="background: var(--surface); border-color: var(--border);">
  <select name="account" class="text-sm rounded px-2 py-1.5" style="background: var(--bg); border: 1px solid var(--border); color: var(--text);">
    <option value="">All accounts</option>
    {% for a in accounts %}
    <option value="{{ a.id }}" {% if a.id == selected_account %}selected{% endif %}>{{ a.effective_name }}</option>
    {% endfor %}
  </select>

  <select name="range" class="text-sm rounded px-2 py-1.5" style="background: var(--bg); border: 1px solid var(--border); color: var(--text);">
    <option value="" {% if not selected_range %}selected{% endif %}>All dates</option>
    <option value="30d" {% if selected_range == "30d" %}selected{% endif %}>Last 30 days</option>
    <option value="90d" {% if selected_range == "90d" %}selected{% endif %}>Last 90 days</option>
    <option value="ytd" {% if selected_range == "ytd" %}selected{% endif %}>Year to date</option>
    <option value="1y" {% if selected_range == "1y" %}selected{% endif %}>Last 12 months</option>
  </select>

  <input type="search" name="q" value="{{ search }}" placeholder="Search payee / memo" class="text-sm rounded px-3 py-1.5 flex-1 min-w-[150px]" style="background: var(--bg); border: 1px solid var(--border); color: var(--text);">

  <button type="submit" class="text-sm font-bold px-3 py-1.5 rounded" style="background: var(--accent-positive); color: var(--bg);">Apply</button>
  {% if selected_account or selected_range or search %}
    <a href="{% url 'transactions' %}" class="text-sm" style="color: var(--muted);">Clear</a>
  {% endif %}
</form>

{% if not page_obj.object_list %}
  <div class="rounded border p-6 text-sm" style="background: var(--surface); border-color: var(--border); color: var(--muted);">
    No transactions match your filters.
  </div>
{% else %}
  {# Desktop table #}
  <div class="hidden md:block rounded border overflow-hidden" style="background: var(--surface); border-color: var(--border);">
    <table class="w-full text-sm">
      <thead style="border-bottom: 1px solid var(--border); color: var(--dim);">
        <tr class="text-[10px] uppercase tracking-widest">
          <th class="px-4 py-2 text-left w-28">Date</th>
          <th class="px-4 py-2 text-left">Payee</th>
          <th class="px-4 py-2 text-right w-40">Account</th>
          <th class="px-4 py-2 text-right w-32">Amount</th>
        </tr>
      </thead>
      <tbody>
        {% for tx in page_obj.object_list %}
        <tr style="border-top: 1px solid var(--border);">
          <td class="px-4 py-2 num text-xs" style="color: var(--muted);">{{ tx.posted_at|date:"M j, Y" }}{% if tx.pending %} <span style="color: var(--accent-assets);">·pending</span>{% endif %}</td>
          <td class="px-4 py-2 truncate">{{ tx.payee|default:tx.description }}</td>
          <td class="px-4 py-2 text-right text-xs truncate" style="color: var(--muted);">
            <a href="{% url 'banking:account_detail' tx.account.id %}">{{ tx.account.effective_name }}</a>
          </td>
          <td class="px-4 py-2 text-right num font-semibold" style="color: {% if tx.amount < 0 %}var(--accent-negative){% else %}var(--accent-positive){% endif %};">
            {{ tx.amount|money:"signed" }}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {# Mobile cards #}
  <div class="md:hidden rounded border overflow-hidden" style="background: var(--surface); border-color: var(--border);">
    {% for tx in page_obj.object_list %}
    <div class="px-4 py-3" style="{% if not forloop.first %}border-top: 1px solid var(--border);{% endif %}">
      <div class="flex items-baseline justify-between gap-3">
        <div class="font-medium truncate min-w-0">{{ tx.payee|default:tx.description }}</div>
        <div class="num font-semibold whitespace-nowrap" style="color: {% if tx.amount < 0 %}var(--accent-negative){% else %}var(--accent-positive){% endif %};">
          {{ tx.amount|money:"signed" }}
        </div>
      </div>
      <div class="text-xs mt-0.5 truncate" style="color: var(--muted);">
        <span class="num">{{ tx.posted_at|date:"M j, Y" }}</span> · <a href="{% url 'banking:account_detail' tx.account.id %}">{{ tx.account.effective_name }}</a>
      </div>
    </div>
    {% endfor %}
  </div>

  {# Pagination — preserves existing query string #}
  {% if page_obj.has_other_pages %}
  <div class="mt-4 flex items-center justify-between text-sm">
    <div style="color: var(--muted);">Page <span class="num">{{ page_obj.number }}</span> of <span class="num">{{ page_obj.paginator.num_pages }}</span></div>
    <div class="flex gap-3">
      {% if page_obj.has_previous %}
        <a href="?{% if selected_account %}account={{ selected_account }}&{% endif %}{% if selected_range %}range={{ selected_range }}&{% endif %}{% if search %}q={{ search|urlencode }}&{% endif %}page={{ page_obj.previous_page_number }}" style="color: var(--accent-positive);">← Prev</a>
      {% else %}
        <span style="color: var(--dim);">← Prev</span>
      {% endif %}
      {% if page_obj.has_next %}
        <a href="?{% if selected_account %}account={{ selected_account }}&{% endif %}{% if selected_range %}range={{ selected_range }}&{% endif %}{% if search %}q={{ search|urlencode }}&{% endif %}page={{ page_obj.next_page_number }}" style="color: var(--accent-positive);">Next →</a>
      {% else %}
        <span style="color: var(--dim);">Next →</span>
      {% endif %}
    </div>
  </div>
  {% endif %}
{% endif %}

{% endblock %}
```

### Task 8: Wire dashboard "See all →" link + add Transactions to sidebar

**Files:**
- Modify: `apps/dashboard/templates/dashboard/index.html` — replace placeholder span
- Modify: `apps/accounts/templates/base.html` — add Transactions nav between Dashboard and Banks

- [ ] **Step 1: Replace dashboard placeholder**

In `apps/dashboard/templates/dashboard/index.html`, find:
```html
<span class="text-xs" style="color: var(--dim);">(See all → coming in Phase 7)</span>
```
Replace with:
```html
<a href="{% url 'transactions' %}" class="text-xs" style="color: var(--accent-positive);">See all →</a>
```

- [ ] **Step 2: Add Transactions nav link**

In `apps/accounts/templates/base.html`, find the sidebar nav block. After the Dashboard `<a>` and before Banks, insert:
```html
<a href="{% url 'transactions' %}" class="flex items-center justify-between px-2 py-1.5 rounded text-sm mb-0.5 {% if request.resolver_match.url_name == 'transactions' %}nav-active-default{% endif %}" style="{% if request.resolver_match.url_name != 'transactions' %}color: var(--muted);{% endif %}">Transactions</a>
```

### Task 9: Tests for transactions page

**Files:**
- Modify: `apps/banking/tests/test_views.py` — add tests for transactions_list

- [ ] **Step 1: Add tests**

```python
def test_transactions_list_shows_only_own(alice, bob, alice_client):
    a_inst = Institution.objects.create(user=alice, name="A Bank", access_url="https://a.example")
    b_inst = Institution.objects.create(user=bob, name="B Bank", access_url="https://b.example")
    a_acc = Account.objects.create(institution=a_inst, name="A Checking", type="checking",
                                   balance=Decimal("0"), external_id="A-1")
    b_acc = Account.objects.create(institution=b_inst, name="B Checking", type="checking",
                                   balance=Decimal("0"), external_id="B-1")
    Transaction.objects.create(account=a_acc, posted_at=date(2026, 4, 1), amount=Decimal("-10"), payee="Alice Coffee", external_id="t-a")
    Transaction.objects.create(account=b_acc, posted_at=date(2026, 4, 1), amount=Decimal("-20"), payee="Bob Coffee", external_id="t-b")

    response = alice_client.get(reverse("transactions"))
    assert b"Alice Coffee" in response.content
    assert b"Bob Coffee" not in response.content


def test_transactions_filter_by_account(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="A Bank", access_url="https://a.example")
    acc1 = Account.objects.create(institution=inst, name="Checking", type="checking",
                                  balance=Decimal("0"), external_id="A-1")
    acc2 = Account.objects.create(institution=inst, name="Savings", type="savings",
                                  balance=Decimal("0"), external_id="A-2")
    Transaction.objects.create(account=acc1, posted_at=date(2026, 4, 1), amount=Decimal("-10"), payee="Coffee A", external_id="t1")
    Transaction.objects.create(account=acc2, posted_at=date(2026, 4, 1), amount=Decimal("-20"), payee="Coffee B", external_id="t2")

    response = alice_client.get(reverse("transactions"), {"account": acc1.id})
    assert b"Coffee A" in response.content
    assert b"Coffee B" not in response.content


def test_transactions_search_payee(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="A Bank", access_url="https://a.example")
    acc = Account.objects.create(institution=inst, name="Checking", type="checking",
                                 balance=Decimal("0"), external_id="A-1")
    Transaction.objects.create(account=acc, posted_at=date(2026, 4, 1), amount=Decimal("-10"), payee="Trader Joes", external_id="t1")
    Transaction.objects.create(account=acc, posted_at=date(2026, 4, 1), amount=Decimal("-20"), payee="Whole Foods", external_id="t2")

    response = alice_client.get(reverse("transactions"), {"q": "trader"})
    assert b"Trader Joes" in response.content
    assert b"Whole Foods" not in response.content


def test_transactions_pagination(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="A Bank", access_url="https://a.example")
    acc = Account.objects.create(institution=inst, name="Checking", type="checking",
                                 balance=Decimal("0"), external_id="A-1")
    for i in range(60):
        Transaction.objects.create(account=acc, posted_at=date(2026, 4, 1), amount=Decimal("-1"),
                                   payee=f"tx-{i}", external_id=f"e-{i}")
    response = alice_client.get(reverse("transactions"))
    assert response.context["page_obj"].number == 1
    assert len(response.context["page_obj"].object_list) == 50
    response2 = alice_client.get(reverse("transactions"), {"page": 2})
    assert response2.context["page_obj"].number == 2
    assert len(response2.context["page_obj"].object_list) == 10
```

You may need `from datetime import date` at the top of the test file.

- [ ] **Step 2: Run tests**

Run: `docker compose exec web pytest apps/banking/tests/ -v`
Expected: all pass.

- [ ] **Step 3: Commit Bundle 3**

```bash
git add apps/banking/ apps/accounts/urls.py apps/accounts/templates/base.html apps/dashboard/templates/dashboard/index.html
git commit -m "feat(transactions): /transactions/ list with filters, pagination, sidebar nav"
```

---

## Bundle 4 — XLSX export

### Task 10: Add openpyxl dependency

**Files:**
- Modify: `requirements.txt` — add `openpyxl==3.1.5`

- [ ] **Step 1: Append to requirements**

```bash
echo "openpyxl==3.1.5" >> requirements.txt
```

- [ ] **Step 2: Rebuild container with new dep**

User will run on server:
```bash
docker compose build web && docker compose up -d
```

(Plan author leaves this for the user to execute since the agentic worker may not have docker access.)

### Task 11: Create exports app skeleton

**Files:**
- Create: `apps/exports/__init__.py` (empty)
- Create: `apps/exports/apps.py`
- Create: `apps/exports/services.py`
- Create: `apps/exports/views.py`
- Create: `apps/exports/urls.py`
- Create: `apps/exports/tests/__init__.py` (empty)
- Modify: `config/settings.py` — add to INSTALLED_APPS
- Modify: `config/urls.py` — mount

- [ ] **Step 1: apps.py**

```python
from django.apps import AppConfig

class ExportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.exports"
```

- [ ] **Step 2: services.py — workbook builder**

```python
from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from apps.assets.models import Asset
from apps.banking.models import Account
from apps.investments.models import InvestmentAccount
from apps.liabilities.models import Liability


HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="404040")
RIGHT = Alignment(horizontal="right")
MONEY_FORMAT = '"$"#,##0.00;[Red]-"$"#,##0.00'


def _autosize(ws, min_width: int = 10, max_width: int = 50) -> None:
    for col_idx in range(1, ws.max_column + 1):
        letter = get_column_letter(col_idx)
        longest = 0
        for cell in ws[letter]:
            longest = max(longest, len(str(cell.value)) if cell.value is not None else 0)
        ws.column_dimensions[letter].width = max(min_width, min(longest + 2, max_width))


def _write_header(ws, headers: list[str]) -> None:
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
    ws.freeze_panes = "A2"


def build_workbook(*, user) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)  # remove default empty sheet

    # ----- Bank accounts: one sheet per account, sheet contains transactions
    accounts = (
        Account.objects.for_user(user)
        .select_related("institution")
        .order_by("institution__name", "name")
    )
    for acc in accounts:
        title = (acc.effective_name or f"Account {acc.id}")[:31]  # excel sheet titles max 31 chars
        ws = wb.create_sheet(title=title)
        _write_header(ws, ["Date", "Payee", "Memo", "Amount", "Pending"])
        rows = acc.transactions.order_by("-posted_at", "-id")
        for tx in rows:
            ws.append([
                tx.posted_at,
                tx.payee or tx.description or "",
                tx.memo or "",
                float(tx.amount),
                "yes" if tx.pending else "",
            ])
        # Format amount column as currency
        for r in range(2, ws.max_row + 1):
            ws.cell(row=r, column=4).number_format = MONEY_FORMAT
            ws.cell(row=r, column=4).alignment = RIGHT
        _autosize(ws)

    # ----- Holdings sheet (all investment accounts in one sheet)
    ws = wb.create_sheet(title="Holdings")
    _write_header(ws, ["Account", "Broker", "Symbol", "Shares", "Price", "Market value", "Cost basis", "Gain $", "Gain %"])
    inv_accounts = InvestmentAccount.objects.for_user(user).prefetch_related("holdings").order_by("broker", "name")
    for acc in inv_accounts:
        for h in acc.holdings.all().order_by("symbol"):
            ws.append([
                acc.effective_name,
                acc.broker or "",
                h.symbol,
                float(h.shares),
                float(h.current_price or 0),
                float(h.market_value or 0),
                float(h.cost_basis) if h.cost_basis is not None else None,
                float(h.gain_loss) if h.gain_loss is not None else None,
                float(h.gain_loss_percent) if h.gain_loss_percent is not None else None,
            ])
    for r in range(2, ws.max_row + 1):
        for col in (5, 6, 7, 8):  # Price, Value, Cost, Gain $
            ws.cell(row=r, column=col).number_format = MONEY_FORMAT
            ws.cell(row=r, column=col).alignment = RIGHT
        ws.cell(row=r, column=9).number_format = "0.00"  # Gain %
    _autosize(ws)

    # ----- Assets sheet
    ws = wb.create_sheet(title="Assets")
    _write_header(ws, ["Name", "Kind", "Quantity", "Unit", "Value", "Last priced", "Notes"])
    for a in Asset.objects.for_user(user).order_by("name"):
        ws.append([
            a.name,
            a.kind,
            float(a.quantity) if a.quantity else "",
            a.unit or "",
            float(a.current_value or 0),
            a.last_priced_at,
            a.notes or "",
        ])
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=5).number_format = MONEY_FORMAT
        ws.cell(row=r, column=5).alignment = RIGHT
    _autosize(ws)

    # ----- Liabilities sheet
    ws = wb.create_sheet(title="Liabilities")
    _write_header(ws, ["Name", "Balance owed", "Notes"])
    for lia in Liability.objects.for_user(user).order_by("name"):
        ws.append([lia.name, float(lia.balance), lia.notes or ""])
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=2).number_format = MONEY_FORMAT
        ws.cell(row=r, column=2).alignment = RIGHT
    _autosize(ws)

    return wb
```

- [ ] **Step 3: views.py**

```python
from io import BytesIO
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

from .services import build_workbook


@login_required
def xlsx_export(request):
    wb = build_workbook(user=request.user)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"finance-{date.today().isoformat()}.xlsx"
    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
```

- [ ] **Step 4: urls.py**

```python
from django.urls import path
from . import views

app_name = "exports"
urlpatterns = [
    path("xlsx/", views.xlsx_export, name="xlsx"),
]
```

- [ ] **Step 5: settings.py — append to INSTALLED_APPS**

Add `"apps.exports"` to the INSTALLED_APPS tuple in `config/settings.py`.

- [ ] **Step 6: config/urls.py — mount at /export/**

Add `path("export/", include("apps.exports.urls"))` to `urlpatterns` in `config/urls.py`.

- [ ] **Step 7: base.html — add download icon to top bar**

In `apps/accounts/templates/base.html`, find the top bar right-side div (where ⟳ sync, ☾ theme toggle, username live). Insert before the theme toggle:

```html
<a href="{% url 'exports:xlsx' %}" class="p-1 text-sm" style="color: var(--muted);" title="Export to Excel" aria-label="Export to Excel">↓</a>
```

### Task 12: Tests for exports

**Files:**
- Create: `apps/exports/tests/test_export.py`

- [ ] **Step 1: Write tests**

```python
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from django.test import Client
from django.urls import reverse
from openpyxl import load_workbook

from apps.banking.models import Account, Institution, Transaction
from apps.investments.models import InvestmentAccount, Holding
from apps.assets.models import Asset
from apps.liabilities.models import Liability


pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(username="alice", password="x")


@pytest.fixture
def alice_client(alice):
    c = Client()
    c.force_login(alice)
    return c


def _load(response):
    return load_workbook(BytesIO(response.content))


def test_export_returns_xlsx(alice_client):
    response = alice_client.get(reverse("exports:xlsx"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    assert "attachment" in response["Content-Disposition"]


def test_export_contains_bank_account_sheet(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Bank", access_url="https://x")
    acc = Account.objects.create(institution=inst, name="Checking", type="checking",
                                 balance=Decimal("100"), external_id="A-1")
    Transaction.objects.create(account=acc, posted_at=date(2026, 4, 1),
                               amount=Decimal("-50"), payee="Coffee", external_id="t-1")
    response = alice_client.get(reverse("exports:xlsx"))
    wb = _load(response)
    assert "Checking" in wb.sheetnames
    ws = wb["Checking"]
    # Header + 1 row
    assert ws.max_row == 2
    assert ws.cell(row=2, column=2).value == "Coffee"


def test_export_includes_holdings_assets_liabilities_sheets(alice, alice_client):
    response = alice_client.get(reverse("exports:xlsx"))
    wb = _load(response)
    for name in ("Holdings", "Assets", "Liabilities"):
        assert name in wb.sheetnames


def test_export_excludes_other_users_data(alice, alice_client, django_user_model):
    bob = django_user_model.objects.create_user(username="bob", password="x")
    bob_inst = Institution.objects.create(user=bob, name="Bob Bank", access_url="https://b")
    Account.objects.create(institution=bob_inst, name="BobAccount", type="checking",
                           balance=Decimal("0"), external_id="B-1")
    response = alice_client.get(reverse("exports:xlsx"))
    wb = _load(response)
    assert "BobAccount" not in wb.sheetnames


def test_export_requires_login():
    c = Client()
    response = c.get(reverse("exports:xlsx"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]
```

- [ ] **Step 2: Run all tests**

Run: `docker compose exec web pytest -q`
Expected: all green.

- [ ] **Step 3: Commit Bundle 4**

```bash
git add requirements.txt apps/exports/ config/settings.py config/urls.py apps/accounts/templates/base.html
git commit -m "feat(exports): single-workbook XLSX export (banks per sheet, holdings/assets/liabilities)"
```

---

## Wrap-up

- [ ] **Smoke test on server:** rebuild container (`docker compose build && docker compose up -d`), pull branch, exercise each new feature
- [ ] **Push branch:** `git push origin phase-7-polish`
- [ ] **Merge to master after smoke approval**

---

## Self-review notes

- Money filter handles Decimal/float/int/None/string-numeric/garbage uniformly. Uses U+2212 minus sign for typographic alignment with monospace.
- Investments redesign drops the per-account drilldown from being primary navigation but keeps `/investments/<id>/` reachable via section-header link for editing/cash management.
- Pagination URL builder preserves account/range/q query params — manual concatenation chosen over a custom template tag for simplicity.
- XLSX export uses `Account.effective_name` truncated to 31 chars (Excel sheet name limit). If two accounts produce the same truncated name, openpyxl raises — punt that edge case until a user actually hits it.
- Tests verify multi-tenant isolation everywhere new querysets are introduced (transactions, exports).
