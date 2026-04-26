# Settings Restructure & Cash/Liabilities Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move SimpleFIN connection management into a hierarchical Settings tree, demote the Banks sidebar tab to "Cash" (filtered to liquid accounts only), surface a per-row type pill on the Liabilities page, and add the missing rename action for `InvestmentAccount`.

**Architecture:** Pure UX/IA work — no model changes, no migrations. Filter the existing bank-account queryset on the Cash page, enrich the existing `LiabilityRow` dataclass with a type label, restructure the `SettingsView` context to group SimpleFIN-sourced accounts under their parent `Institution` via prefetch, and copy the existing `rename_account`/`rename_institution` pattern to `InvestmentAccount.display_name`.

**Tech Stack:** Django 5.1, pytest-django, Tailwind utility classes + CSS custom properties.

**Spec:** `docs/superpowers/specs/2026-04-26-settings-restructure-design.md`

**Test command convention:** Plan uses `pytest <path> -v`. **Do not invoke Docker** to run tests (per saved feedback). If `pytest` is not on PATH locally, skip the verification steps and note in the implementer's report that tests were not executed; the user will run them.

---

## File touch-list

- **Modify** `apps/banking/views.py` — `banks_list` filters to liquid types only.
- **Modify** `apps/banking/templates/banking/banks_list.html` — title + h1 "Banks" → "Cash".
- **Modify** `apps/banking/tests/test_views.py` — Cash filter tests.
- **Modify** `apps/accounts/templates/base.html:83` — sidebar label "Banks" → "Cash".
- **Modify** `apps/liabilities/services.py` — add `type_label` to `LiabilityRow`.
- **Modify** `apps/liabilities/tests/test_services.py` — type_label test.
- **Modify** `apps/liabilities/templates/liabilities/liabilities_list.html` — render type pill.
- **Modify** `apps/liabilities/tests/test_views.py` — pill render test.
- **Modify** `apps/investments/views.py` — `rename_investment_account` view.
- **Modify** `apps/investments/urls.py` — rename URL.
- **Modify** `apps/investments/tests/test_views.py` — rename tests.
- **Modify** `apps/accounts/views.py` — `SettingsView` context restructure.
- **Modify** `apps/accounts/templates/accounts/settings.html` — External connections tree + Manual investment accounts section.
- **Create** `apps/accounts/tests/test_settings.py` — settings render test.

---

## Task 1: Cash tab — filter + relabel

**Files:**
- Modify: `apps/banking/views.py:36-43` (`banks_list`)
- Modify: `apps/banking/templates/banking/banks_list.html:3-6` (title + h1)
- Modify: `apps/accounts/templates/base.html:83` (sidebar label)
- Test: `apps/banking/tests/test_views.py` (two new tests)

- [ ] **Step 1: Write the failing filter test (excludes credit/loan)**

Append to `apps/banking/tests/test_views.py`:

```python
def test_cash_list_excludes_credit_and_loan(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="B", access_url="https://x")
    Account.objects.create(institution=inst, name="MyChecking", type="checking",
                           balance=Decimal("100"), external_id="A-1")
    Account.objects.create(institution=inst, name="MyVisa", type="credit",
                           balance=Decimal("500"), external_id="A-2")
    Account.objects.create(institution=inst, name="MyLoan", type="loan",
                           balance=Decimal("12000"), external_id="A-3")
    response = alice_client.get(reverse("banking:list"))
    assert response.status_code == 200
    assert b"MyChecking" in response.content
    assert b"MyVisa" not in response.content
    assert b"MyLoan" not in response.content
```

- [ ] **Step 2: Write the failing filter test (includes savings + other)**

Append:

```python
def test_cash_list_includes_savings_and_other(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="B", access_url="https://x")
    Account.objects.create(institution=inst, name="MySavings", type="savings",
                           balance=Decimal("100"), external_id="A-1")
    Account.objects.create(institution=inst, name="MyOther", type="other",
                           balance=Decimal("100"), external_id="A-2")
    response = alice_client.get(reverse("banking:list"))
    assert response.status_code == 200
    assert b"MySavings" in response.content
    assert b"MyOther" in response.content
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest apps/banking/tests/test_views.py -v -k "cash_list"`
Expected: 2 FAILS — `MyVisa` and `MyLoan` will appear in content (currently no filter).

If `pytest` is unavailable, skip the verification and note in the report.

- [ ] **Step 4: Add the filter to `banks_list`**

In `apps/banking/views.py`, replace the `banks_list` view body (currently lines 36-43):

```python
@login_required
def banks_list(request):
    accounts = (
        Account.objects
        .for_user(request.user)
        .filter(type__in=["checking", "savings", "other"])
        .select_related("institution")
        .order_by("institution__display_name", "institution__name", "display_name", "name")
    )
    return render(request, "banking/banks_list.html", {"accounts": accounts})
```

- [ ] **Step 5: Update the page title and heading**

In `apps/banking/templates/banking/banks_list.html`, replace lines 3-6:

```html
{% block title %}Cash{% endblock %}
{% block content %}
<div class="flex items-center justify-between mb-6 flex-wrap gap-3">
  <h1 class="text-2xl font-bold">Cash</h1>
</div>
```

- [ ] **Step 6: Update the sidebar label**

In `apps/accounts/templates/base.html`, change line 83 — replace the visible text `Banks` with `Cash` (URL and CSS classes unchanged):

```html
      <a href="{% url 'banking:list' %}" class="flex items-center justify-between px-2 py-1.5 rounded text-sm mb-0.5 {% if active == 'banking' %}nav-active-cash{% endif %}" style="{% if active != 'banking' %}color: var(--muted);{% endif %}">Cash</a>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest apps/banking/tests/test_views.py -v -k "cash_list"`
Expected: 2 PASS.

If pytest unavailable, skip and note in report.

- [ ] **Step 8: Run the full banking suite for regressions**

Run: `pytest apps/banking/tests/ -v`
Expected: all green.

If pytest unavailable, skip and note.

- [ ] **Step 9: Commit**

```bash
git add apps/banking/views.py apps/banking/templates/banking/banks_list.html apps/accounts/templates/base.html apps/banking/tests/test_views.py
git commit -m "feat(banking): rename Banks→Cash and filter to liquid accounts"
```

---

## Task 2: Liabilities type pills

**Files:**
- Modify: `apps/liabilities/services.py:9-45` (`LiabilityRow` + `liabilities_for`)
- Modify: `apps/liabilities/tests/test_services.py` (one new test)
- Modify: `apps/liabilities/templates/liabilities/liabilities_list.html:31-39` (render pill)
- Modify: `apps/liabilities/tests/test_views.py` (one new test)

- [ ] **Step 1: Write the failing service test**

Append to `apps/liabilities/tests/test_services.py`:

```python
@pytest.mark.django_db
def test_liability_row_includes_type_label():
    user = User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    inst = Institution.objects.create(user=user, name="Bank", access_url="https://x")
    Account.objects.create(institution=inst, name="Visa", type="credit",
                           balance=Decimal("500"), external_id="V1")
    Account.objects.create(institution=inst, name="CarLoan", type="loan",
                           balance=Decimal("12000"), external_id="L1")
    Liability.objects.create(user=user, name="Student loan", balance=Decimal("25000"))

    rows = liabilities_for(user)
    by_name = {r.name: r for r in rows}
    assert by_name["Visa"].type_label == "Credit"
    assert by_name["CarLoan"].type_label == "Loan"
    assert by_name["Student loan"].type_label == "Manual"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest apps/liabilities/tests/test_services.py::test_liability_row_includes_type_label -v`
Expected: FAIL — `AttributeError: 'LiabilityRow' object has no attribute 'type_label'` (or `TypeError: __init__() missing 1 required positional argument` depending on dataclass shape).

- [ ] **Step 3: Add `type_label` to `LiabilityRow` and populate it**

In `apps/liabilities/services.py`, replace the dataclass and `liabilities_for` function (currently lines 9-45):

```python
@dataclass
class LiabilityRow:
    """Display-layer representation of a liability from any source."""
    name: str
    balance: Decimal
    source: str           # "bank" | "manual"
    type_label: str       # "Credit" | "Loan" | "Manual"
    edit_url: str | None  # set for manual; None for bank-sourced
    bank_account_id: int | None = None
    liability_id: int | None = None


def liabilities_for(user) -> list[LiabilityRow]:
    """Combined list: bank credit/loan accounts + manual Liability rows.
    Sorted by descending balance."""
    rows: list[LiabilityRow] = []

    type_to_label = {"credit": "Credit", "loan": "Loan"}
    for acc in Account.objects.for_user(user).filter(type__in=["credit", "loan"]):
        # For credit cards SimpleFIN reports balance as a positive number = what's owed.
        rows.append(LiabilityRow(
            name=acc.effective_name,
            balance=abs(acc.balance),
            source="bank",
            type_label=type_to_label[acc.type],
            edit_url=None,
            bank_account_id=acc.id,
        ))

    for lia in Liability.objects.for_user(user):
        rows.append(LiabilityRow(
            name=lia.name,
            balance=lia.balance,
            source="manual",
            type_label="Manual",
            edit_url=None,
            liability_id=lia.id,
        ))

    rows.sort(key=lambda r: r.balance, reverse=True)
    return rows
```

- [ ] **Step 4: Run service test to verify it passes**

Run: `pytest apps/liabilities/tests/test_services.py::test_liability_row_includes_type_label -v`
Expected: PASS.

- [ ] **Step 5: Write the failing template-render test**

Append to `apps/liabilities/tests/test_views.py`:

```python
def test_liabilities_list_renders_type_pills(alice, alice_client):
    from apps.banking.models import Institution, Account
    inst = Institution.objects.create(user=alice, name="Bank", access_url="https://x")
    Account.objects.create(institution=inst, name="Visa", type="credit",
                           balance=Decimal("500"), external_id="V1")
    Account.objects.create(institution=inst, name="CarLoan", type="loan",
                           balance=Decimal("12000"), external_id="L1")
    Liability.objects.create(user=alice, name="Student loan", balance=Decimal("25000"))

    response = alice_client.get(reverse("liabilities:list"))
    assert response.status_code == 200
    assert b"Credit" in response.content
    assert b"Loan" in response.content
    assert b"Manual" in response.content
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `pytest apps/liabilities/tests/test_views.py::test_liabilities_list_renders_type_pills -v`
Expected: FAIL — pill text not yet rendered.

- [ ] **Step 7: Render the pill in the liabilities template**

In `apps/liabilities/templates/liabilities/liabilities_list.html`, replace lines 28-40 (the `{% for row in rows %}` block's row content). Find the existing block:

```html
    {% for row in rows %}
    <div class="flex items-center justify-between px-5 py-3" style="{% if not forloop.first %}border-top: 1px solid var(--border);{% endif %}">
      {% if row.source == 'bank' %}
        <a href="{% url 'banking:account_detail' row.bank_account_id %}" class="flex-1 min-w-0 pr-3">
          <div class="font-medium">{{ row.name }}</div>
          <div class="text-xs" style="color: var(--muted);">🔗 from linked bank · view transactions →</div>
        </a>
      {% else %}
        <div class="flex-1 min-w-0 pr-3">
          <div class="font-medium">{{ row.name }}</div>
          <div class="text-xs" style="color: var(--muted);">✎ manual</div>
        </div>
      {% endif %}
```

Replace with (adding the pill next to `{{ row.name }}` in both branches):

```html
    {% for row in rows %}
    <div class="flex items-center justify-between px-5 py-3" style="{% if not forloop.first %}border-top: 1px solid var(--border);{% endif %}">
      {% if row.source == 'bank' %}
        <a href="{% url 'banking:account_detail' row.bank_account_id %}" class="flex-1 min-w-0 pr-3">
          <div class="font-medium">
            {{ row.name }}
            <span class="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded ml-2"
                  style="background: var(--tint-lia); color: var(--accent-lia);">{{ row.type_label }}</span>
          </div>
          <div class="text-xs" style="color: var(--muted);">🔗 from linked bank · view transactions →</div>
        </a>
      {% else %}
        <div class="flex-1 min-w-0 pr-3">
          <div class="font-medium">
            {{ row.name }}
            <span class="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded ml-2"
                  style="background: var(--tint-lia); color: var(--accent-lia);">{{ row.type_label }}</span>
          </div>
          <div class="text-xs" style="color: var(--muted);">✎ manual</div>
        </div>
      {% endif %}
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `pytest apps/liabilities/tests/test_views.py::test_liabilities_list_renders_type_pills -v`
Expected: PASS.

- [ ] **Step 9: Run the full liabilities suite for regressions**

Run: `pytest apps/liabilities/tests/ -v`
Expected: all green. The pre-existing `test_combined_source_listing_includes_bank_credit_and_manual` still passes because adding `type_label` doesn't change `name`/`balance`/`source`.

- [ ] **Step 10: Commit**

```bash
git add apps/liabilities/services.py apps/liabilities/templates/liabilities/liabilities_list.html apps/liabilities/tests/test_services.py apps/liabilities/tests/test_views.py
git commit -m "feat(liabilities): per-row Credit/Loan/Manual type pill"
```

---

## Task 3: `rename_investment_account` view + URL

**Files:**
- Modify: `apps/investments/views.py` (add view, near `edit_account` ~line 198)
- Modify: `apps/investments/urls.py` (add URL)
- Test: `apps/investments/tests/test_views.py` (three new tests)

- [ ] **Step 1: Write the persists test**

Append to `apps/investments/tests/test_views.py`:

```python
def test_rename_investment_account_persists_display_name(alice, alice_client):
    acc = InvestmentAccount.objects.create(
        user=alice, source="manual", broker="Fidelity", name="Alice 401k",
    )
    response = alice_client.post(
        reverse("investments:rename_account", args=[acc.id]),
        {"display_name": "Old Job 401k"},
    )
    assert response.status_code == 302
    acc.refresh_from_db()
    assert acc.display_name == "Old Job 401k"
    assert acc.effective_name == "Old Job 401k"
```

- [ ] **Step 2: Write the blank-restores test**

Append:

```python
def test_rename_investment_account_blank_restores_provider_name(alice, alice_client):
    acc = InvestmentAccount.objects.create(
        user=alice, source="manual", broker="Fidelity", name="Alice 401k",
        display_name="Old Custom Name",
    )
    alice_client.post(
        reverse("investments:rename_account", args=[acc.id]),
        {"display_name": ""},
    )
    acc.refresh_from_db()
    assert acc.display_name == ""
    assert acc.effective_name == "Alice 401k"
```

- [ ] **Step 3: Write the forbidden test**

Append:

```python
def test_rename_investment_account_forbidden_for_other_user(alice, bob, bob_client):
    acc = InvestmentAccount.objects.create(
        user=alice, source="manual", broker="Fidelity", name="Alice 401k",
    )
    response = bob_client.post(
        reverse("investments:rename_account", args=[acc.id]),
        {"display_name": "Pwned"},
    )
    assert response.status_code == 404
    acc.refresh_from_db()
    assert acc.display_name == ""
```

- [ ] **Step 4: Run the three tests to verify they fail**

Run: `pytest apps/investments/tests/test_views.py -v -k "rename_investment_account"`
Expected: 3 FAILS — `NoReverseMatch: Reverse for 'rename_account' not found` (or, since `delete_account` already exists with similar shape, the URL collision will surface differently — but the test will not pass until the URL is added).

- [ ] **Step 5: Add the view to `apps/investments/views.py`**

Append to `apps/investments/views.py` (after `edit_account`, around line 215):

```python
@login_required
@require_http_methods(["GET", "POST"])
def rename_investment_account(request, account_id):
    account = get_object_or_404(
        InvestmentAccount.objects.for_user(request.user), pk=account_id
    )
    if request.method == "POST":
        account.display_name = request.POST.get("display_name", "").strip()
        account.save(update_fields=["display_name"])
        messages.success(request, f'Renamed to "{account.effective_name}".')
        return HttpResponseRedirect(reverse("settings"))
    return render(request, "banking/rename_form.html", {
        "subject": "investment account",
        "object": account,
        "cancel_url": reverse("settings"),
        "current_value": account.display_name,
        "fallback_value": account.name,
    })
```

(The template `banking/rename_form.html` is shared and generic — already used by `rename_institution` and `rename_account`. The redirect uses `reverse("settings")` because the rename pencil only lives in the Settings tree. The `settings` URL name has no namespace per `apps/accounts/urls.py:12`.)

- [ ] **Step 6: Wire the URL**

In `apps/investments/urls.py`, add this line after the existing `path("accounts/<int:account_id>/edit/", ...)` (currently line 10):

```python
    path("accounts/<int:account_id>/rename/", views.rename_investment_account, name="rename_account"),
```

The full updated `urlpatterns` should look like:

```python
urlpatterns = [
    path("", views.investments_list, name="list"),
    path("accounts/add/", views.add_manual_account, name="add_account"),
    path("accounts/<int:account_id>/edit/", views.edit_account, name="edit_account"),
    path("accounts/<int:account_id>/rename/", views.rename_investment_account, name="rename_account"),
    path("accounts/<int:account_id>/", views.account_detail, name="account_detail"),
    path("accounts/<int:account_id>/holdings/add/", views.add_holding, name="add_holding"),
    path("holdings/<int:holding_id>/edit/", views.edit_holding, name="edit_holding"),
    path("holdings/<int:holding_id>/delete/", views.delete_holding, name="delete_holding"),
    path("refresh/", views.refresh_prices, name="refresh_prices"),
    path("banks/<int:institution_id>/sync/", views.sync_investments_view, name="sync_from_bank"),
    path("accounts/<int:account_id>/delete/", views.delete_account, name="delete_account"),
]
```

- [ ] **Step 7: Run the three tests to verify they pass**

Run: `pytest apps/investments/tests/test_views.py -v -k "rename_investment_account"`
Expected: 3 PASS.

- [ ] **Step 8: Run the full investments suite for regressions**

Run: `pytest apps/investments/tests/ -v`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add apps/investments/views.py apps/investments/urls.py apps/investments/tests/test_views.py
git commit -m "feat(investments): rename_investment_account writes display_name"
```

---

## Task 4: Settings restructure — External connections tree

**Files:**
- Modify: `apps/accounts/views.py:20-37` (`SettingsView.get_context_data`)
- Modify: `apps/accounts/templates/accounts/settings.html:19-65` (replace "Bank institutions" + "SimpleFIN-linked investment accounts" sections)
- Create: `apps/accounts/tests/test_settings.py`

- [ ] **Step 1: Write the failing settings render test**

Create `apps/accounts/tests/test_settings.py` with:

```python
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.banking.models import Account, Institution
from apps.investments.models import InvestmentAccount

User = get_user_model()


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice", password="correct-horse-battery-staple")


@pytest.fixture
def alice_client(alice):
    c = Client()
    c.force_login(alice)
    return c


def test_settings_groups_simplefin_accounts_under_their_institution(alice, alice_client):
    # SimpleFIN connection with one bank account and one investment account
    inst = Institution.objects.create(user=alice, name="Family Banks", access_url="https://x")
    Account.objects.create(institution=inst, name="Joint Checking", type="checking",
                           balance=Decimal("1000"), external_id="A-1")
    InvestmentAccount.objects.create(user=alice, source="simplefin", institution=inst,
                                      broker="Fidelity", name="Family 401k", external_id="I-1")
    # Manual investment account (not under any connection)
    InvestmentAccount.objects.create(user=alice, source="manual", broker="Vanguard", name="Roth IRA")

    response = alice_client.get(reverse("settings"))
    assert response.status_code == 200
    body = response.content.decode()

    # The new heading is present; the old per-section heading is gone.
    assert "External connections" in body
    assert "SimpleFIN-linked investment accounts" not in body

    # All three account names render somewhere on the page.
    assert "Joint Checking" in body
    assert "Family 401k" in body
    assert "Roth IRA" in body

    # New "Manual investment accounts" section exists.
    assert "Manual investment accounts" in body

    # The manual account name appears AFTER the External connections section
    # (it's grouped in the dedicated manual section, not under any institution).
    ext_pos = body.index("External connections")
    manual_section_pos = body.index("Manual investment accounts")
    roth_pos = body.index("Roth IRA")
    assert ext_pos < manual_section_pos < roth_pos

    # The Family 401k (SimpleFIN-sourced) appears BEFORE the Manual section
    # (it's nested under its institution).
    family_pos = body.index("Family 401k")
    assert family_pos < manual_section_pos


def test_settings_includes_rename_links_for_child_accounts(alice, alice_client):
    inst = Institution.objects.create(user=alice, name="Bank", access_url="https://x")
    bank_acc = Account.objects.create(institution=inst, name="Checking", type="checking",
                                       balance=Decimal("100"), external_id="A-1")
    inv_acc = InvestmentAccount.objects.create(user=alice, source="simplefin", institution=inst,
                                                broker="Fidelity", name="401k", external_id="I-1")

    response = alice_client.get(reverse("settings"))
    body = response.content.decode()

    assert reverse("banking:rename_account", args=[bank_acc.id]) in body
    assert reverse("investments:rename_account", args=[inv_acc.id]) in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest apps/accounts/tests/test_settings.py -v`
Expected: FAILS — current template still uses "Bank institutions" / "SimpleFIN-linked investment accounts" headings; new ones aren't present yet; rename URL for investment_account exists in code (added in Task 3) but isn't referenced by the template yet.

- [ ] **Step 3: Update `SettingsView.get_context_data`**

In `apps/accounts/views.py`, replace the `SettingsView` class body (currently lines 20-37):

```python
class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["institutions"] = (
            Institution.objects.for_user(user)
            .prefetch_related("accounts", "investment_accounts")
            .order_by("-last_synced_at")
        )
        ctx["manual_investment_accounts"] = (
            InvestmentAccount.objects.for_user(user)
            .filter(source="manual")
            .order_by("name")
        )
        ctx["scraped_assets"] = (
            Asset.objects.for_user(user)
            .filter(kind="scraped")
            .order_by("-last_priced_at")
        )
        return ctx
```

(Drops the old `investment_accounts` context key entirely; the template will be rewritten to read from the prefetched `inst.investment_accounts.all` and the new `manual_investment_accounts` list.)

- [ ] **Step 4: Update the settings template**

In `apps/accounts/templates/accounts/settings.html`, replace lines 19-65 (the entire block from `<div class="flex items-center justify-between mb-3"><h2>Bank institutions</h2>...` through the end of the `SimpleFIN-linked investment accounts` section). The replacement:

```html
<div class="flex items-center justify-between mb-3">
  <h2 class="text-lg font-semibold">External connections</h2>
  <a href="{% url 'banking:link' %}" class="font-bold px-3 py-1.5 rounded text-sm" style="background: var(--accent-positive); color: var(--bg);">+ Link account</a>
</div>
{% if not institutions %}
  <p class="text-sm mb-6" style="color: var(--muted);">None linked. Click <strong style="color: var(--text);">+ Link account</strong> above to connect a bank via SimpleFIN.</p>
{% else %}
  <div class="rounded border overflow-hidden mb-6" style="background: var(--surface); border-color: var(--border);">
    {% for inst in institutions %}
    <div class="px-5 py-3" style="{% if not forloop.first %}border-top: 1px solid var(--border);{% endif %}">
      {# Connection row #}
      <div class="flex items-center justify-between">
        <div>
          <div class="font-medium">{{ inst.effective_name }}</div>
          <div class="text-xs" style="color: var(--muted);">
            SimpleFIN · Last synced: {% if inst.last_synced_at %}<span class="num">{{ inst.last_synced_at|date:"M j, Y g:i a" }}</span>{% else %}never{% endif %}
          </div>
        </div>
        <div class="flex items-center gap-3">
          <form method="post" action="{% url 'banking:sync' inst.id %}" class="m-0">
            {% csrf_token %}
            <button type="submit" class="text-sm" style="color: var(--muted);">⟳ Bank sync</button>
          </form>
          <a href="{% url 'banking:rename_institution' inst.id %}" class="text-sm" style="color: var(--dim);">✎</a>
          <a href="{% url 'banking:delete_institution' inst.id %}" class="text-sm" style="color: var(--dim);">🗑</a>
        </div>
      </div>

      {# Child bank accounts #}
      {% for acc in inst.accounts.all %}
      <div class="flex items-center justify-between pl-6 mt-2 text-sm">
        <div class="min-w-0">
          <span style="color: var(--muted);">↳</span>
          <span class="font-medium">{{ acc.effective_name }}</span>
          <span class="text-xs ml-1" style="color: var(--dim);">{{ acc.get_type_display }}</span>
        </div>
        <div class="flex items-center gap-3">
          <a href="{% url 'banking:rename_account' acc.id %}" class="text-sm" style="color: var(--dim);" title="Rename">✎</a>
          <a href="{% url 'banking:delete_account' acc.id %}" class="text-sm" style="color: var(--dim);" title="Delete">🗑</a>
        </div>
      </div>
      {% endfor %}

      {# Child SimpleFIN-sourced investment accounts #}
      {% for inv in inst.investment_accounts.all %}
      <div class="flex items-center justify-between pl-6 mt-2 text-sm">
        <div class="min-w-0">
          <span style="color: var(--muted);">↳</span>
          <span class="font-medium">{{ inv.effective_name }}</span>
          <span class="text-xs ml-1" style="color: var(--dim);">Investment{% if inv.broker %} · {{ inv.broker }}{% endif %}</span>
        </div>
        <div class="flex items-center gap-3">
          <a href="{% url 'investments:rename_account' inv.id %}" class="text-sm" style="color: var(--dim);" title="Rename">✎</a>
          <a href="{% url 'investments:delete_account' inv.id %}" class="text-sm" style="color: var(--dim);" title="Delete">🗑</a>
        </div>
      </div>
      {% endfor %}
    </div>
    {% endfor %}
  </div>
{% endif %}

<h2 class="text-lg font-semibold mb-3">Manual investment accounts</h2>
{% if not manual_investment_accounts %}
  <p class="text-sm mb-6" style="color: var(--muted);">None. Add one on the <a href="{% url 'investments:list' %}" class="underline" style="color: var(--accent-positive);">Investments</a> page.</p>
{% else %}
  <div class="rounded border overflow-hidden mb-6" style="background: var(--surface); border-color: var(--border);">
    {% for inv in manual_investment_accounts %}
    <div class="flex items-center justify-between px-5 py-3" style="{% if not forloop.first %}border-top: 1px solid var(--border);{% endif %}">
      <div>
        <div class="font-medium">{{ inv.effective_name }}</div>
        <div class="text-xs" style="color: var(--muted);">{% if inv.broker %}{{ inv.broker }}{% else %}Manual entry{% endif %}</div>
      </div>
      <div class="flex items-center gap-3">
        <a href="{% url 'investments:rename_account' inv.id %}" class="text-sm" style="color: var(--dim);" title="Rename">✎</a>
        <a href="{% url 'investments:delete_account' inv.id %}" class="text-sm" style="color: var(--dim);" title="Delete">🗑</a>
      </div>
    </div>
    {% endfor %}
  </div>
{% endif %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest apps/accounts/tests/test_settings.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Run the whole project test suite for regressions**

Run: `pytest -q`
Expected: all green. (Possible breakage: existing dashboard tests, banking tests, or anything that relied on the old `investment_accounts` context key — but no test should reference that key directly. Verify.)

- [ ] **Step 7: Commit**

```bash
git add apps/accounts/views.py apps/accounts/templates/accounts/settings.html apps/accounts/tests/test_settings.py
git commit -m "feat(accounts): External connections tree groups SimpleFIN children"
```

---

## Final manual smoke check

After all four tasks land, do a quick browser pass:

1. Spin up the server (the user runs Docker manually — do not auto-start).
2. Sign in. The sidebar should show "Cash" instead of "Banks".
3. Visit `/banks/` (the Cash page). Heading reads "Cash". If you have credit/loan accounts, they no longer appear here.
4. Visit `/liabilities/`. Each row has a small `CREDIT` / `LOAN` / `MANUAL` pill next to the name.
5. Visit `/settings/`. The "External connections" section shows each SimpleFIN bridge with its child bank and investment accounts indented below. "Manual investment accounts" is its own section underneath.
6. On a SimpleFIN-sourced investment account row, click ✎. The rename form appears, "Save" returns to Settings, and the new name displays.
7. On a manual investment account row, click ✎. Same flow.
8. The pre-existing "Bank institutions" heading is gone.

If anything renders incorrectly, file as a follow-up rather than reopening tasks (manual smoke checks are not gating).
