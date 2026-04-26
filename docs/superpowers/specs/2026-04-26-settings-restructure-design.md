# Settings Restructure & Cash/Liabilities Cleanup — Design

**Date:** 2026-04-26
**Status:** Approved, awaiting implementation plan

## Summary

Three connected changes that clean up the navigation around accounts:

1. **Sidebar:** rename "Banks" → "Cash"; the Cash page filters out credit/loan accounts so it shows only liquid bank accounts.
2. **Liabilities page:** keep the existing union of bank credit/loan accounts and manual liabilities, but show a small per-row type pill (`Credit` / `Loan` / `Manual`) so the source is obvious at a glance.
3. **Settings:** replace the flat "Bank institutions" list with a hierarchical "External connections" tree — each SimpleFIN connection expands to show its child bank accounts and SimpleFIN-sourced investment accounts inline. Manual investment accounts move to a separate "Manual investment accounts" section. The currently-missing rename action for `InvestmentAccount` gets added so the Settings tree pencils actually work.

## Motivation

- Credit cards and loans appearing on the "Banks" page is confusing — they're liabilities, not cash. The model already separates this (`Account.type IN ('credit','loan')`) and `apps/liabilities/services.py:liabilities_for()` already unions them into the Liabilities page; the Banks page just hadn't been filtered.
- The Settings page already manages SimpleFIN bridges, but it shows institutions and investment accounts as separate flat lists, hiding the parent–child relationship. Putting investment accounts under their parent bridge surfaces "what came from what."
- `InvestmentAccount` already has a `display_name` field intended for the rename pattern (matches `Institution.display_name` and `Account.display_name`), but no rename view was ever wired up. The Settings tree needs it.

## Existing state (relevant facts)

- `apps/liabilities/services.py:20-45` — `liabilities_for(user)` already returns bank credit/loan accounts and manual `Liability` rows in one sorted list, with `source="bank"` or `source="manual"` per row.
- `apps/liabilities/templates/liabilities/liabilities_list.html` — already renders both sources with subtitles ("🔗 from linked bank" vs "✎ manual"); it just lacks a compact type pill.
- `apps/banking/views.py:36-50` — `_safe_url` and `_safe_back` helpers exist (added in the rename feature) and can be lifted to a shared utility for the new `rename_investment_account` view.
- `apps/investments/views.py:198-215` — `edit_account` view writes the *broad* form (name, broker, notes, cash_balance), and writes user input directly to `account.name`. **For SimpleFIN-sourced investment accounts this would be clobbered on sync.** This bug is acknowledged but **out of scope** for this spec — addressed by the new rename view writing to `display_name`. Existing `edit_account` is left alone to avoid scope creep; users editing a SimpleFIN-sourced account today is a rare path.
- `apps/accounts/templates/accounts/settings.html` — current Settings template; will be heavily restructured.
- `apps/accounts/views.py:SettingsView` — provides the context (`institutions`, `investment_accounts`, `scraped_assets`).

## Design

### 1. Sidebar: "Banks" → "Cash"

`apps/accounts/templates/base.html:83` — change the link label:

```html
<a href="{% url 'banking:list' %}" ...>Cash</a>
```

URL path stays `/banks/` (no breaking change). The active-state class can stay `nav-active-cash` (it already has the cash-themed accent — coincidence but works).

### 2. Cash page: filter out credit/loan accounts

`apps/banking/views.py:banks_list` — add a queryset filter:

```python
accounts = (
    Account.objects
    .for_user(request.user)
    .filter(type__in=["checking", "savings", "other"])
    .select_related("institution")
    .order_by("institution__display_name", "institution__name", "display_name", "name")
)
```

Page heading text in `banks_list.html` changes from "Banks" → "Cash" (or similar). The per-account drill-down still works for credit/loan accounts because they're now reached from the Liabilities page.

### 3. Liabilities page: type pills

Extend `LiabilityRow` in `apps/liabilities/services.py`:

```python
@dataclass
class LiabilityRow:
    name: str
    balance: Decimal
    source: str           # "bank" | "manual"
    type_label: str       # "Credit" | "Loan" | "Manual"
    edit_url: str | None
    bank_account_id: int | None = None
    liability_id: int | None = None
```

In `liabilities_for()`, populate `type_label`:
- `"Credit"` when `acc.type == "credit"`
- `"Loan"` when `acc.type == "loan"`
- `"Manual"` for `Liability` rows

Update `liabilities_list.html` to show a small pill next to the row name:

```html
<span class="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded ml-2"
      style="background: var(--tint-lia); color: var(--accent-lia);">{{ row.type_label }}</span>
```

The existing subtitle line ("🔗 from linked bank…" / "✎ manual") stays.

### 4. Settings: External connections tree

`apps/accounts/views.py:SettingsView` — change the context:

```python
context["institutions"] = (
    Institution.objects.for_user(user)
    .prefetch_related("accounts", "investment_accounts")
    .order_by("name")
)
context["manual_investment_accounts"] = (
    InvestmentAccount.objects.for_user(user)
    .filter(source="manual")
    .order_by("name")
)
context["scraped_assets"] = ...  # unchanged
# Drop the old `investment_accounts` context var (replaced by the per-institution prefetch).
```

`apps/accounts/templates/accounts/settings.html` — replace the "Bank institutions" + "SimpleFIN-linked investment accounts" blocks with one "External connections" block:

```html
<h2 class="text-lg font-semibold mb-3">External connections</h2>
{% if not institutions %}
  <p class="text-sm mb-6" style="color: var(--muted);">None linked. Click <strong>+ Link account</strong> to connect a bank via SimpleFIN.</p>
{% else %}
  <div class="rounded border overflow-hidden mb-6" style="background: var(--surface); border-color: var(--border);">
    {% for inst in institutions %}
    <div class="px-5 py-3" style="{% if not forloop.first %}border-top: 1px solid var(--border);{% endif %}">
      {# Connection row: name + last-synced + sync/rename/delete actions #}
      <div class="flex items-center justify-between">
        <div>
          <div class="font-medium">{{ inst.effective_name }}</div>
          <div class="text-xs" style="color: var(--muted);">SimpleFIN · Last synced: ...</div>
        </div>
        <div class="flex items-center gap-3">
          {# sync form, rename link, delete link — same as today #}
        </div>
      </div>

      {# Child accounts indented #}
      {% for acc in inst.accounts.all %}
      <div class="flex items-center justify-between pl-6 mt-2 text-sm">
        <div>
          <span style="color: var(--muted);">↳</span>
          <span class="font-medium">{{ acc.effective_name }}</span>
          <span class="text-xs" style="color: var(--dim);">{{ acc.get_type_display }}</span>
        </div>
        <div class="flex items-center gap-3">
          <a href="{% url 'banking:rename_account' acc.id %}" ...>✎</a>
          <a href="{% url 'banking:delete_account' acc.id %}" ...>🗑</a>
        </div>
      </div>
      {% endfor %}

      {% for inv in inst.investment_accounts.all %}
      <div class="flex items-center justify-between pl-6 mt-2 text-sm">
        <div>
          <span style="color: var(--muted);">↳</span>
          <span class="font-medium">{{ inv.effective_name }}</span>
          <span class="text-xs" style="color: var(--dim);">Investment · {{ inv.broker }}</span>
        </div>
        <div class="flex items-center gap-3">
          <a href="{% url 'investments:rename_account' inv.id %}" ...>✎</a>
          <a href="{% url 'investments:delete_account' inv.id %}" ...>🗑</a>
        </div>
      </div>
      {% endfor %}
    </div>
    {% endfor %}
  </div>
{% endif %}
```

Plus a new section below:

```html
<h2 class="text-lg font-semibold mb-3">Manual investment accounts</h2>
{# rows of manual_investment_accounts with rename + delete pencils #}
```

No "+ Add" button in this Settings section — manual investment accounts are still created via the Investments page's existing "+ Add account" flow. Settings is for managing what already exists; creation lives on the Investments page.

Scraped assets and Export sections remain untouched.

### 5. New: `rename_investment_account` view

`apps/investments/views.py` — add a focused rename view mirroring `banking.views.rename_account`:

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
        return HttpResponseRedirect(reverse("accounts:settings"))
    return render(request, "banking/rename_form.html", {  # reuse the generic template
        "subject": "investment account",
        "object": account,
        "cancel_url": reverse("accounts:settings"),
        "current_value": account.display_name,
        "fallback_value": account.name,
    })
```

URL: `apps/investments/urls.py` — add:

```python
path("accounts/<int:account_id>/rename/", views.rename_investment_account, name="rename_account"),
```

The redirect goes back to `accounts:settings` because that's the primary surface for renaming. `_safe_back` from the Transaction-rename feature isn't needed here since there's only one entry point (Settings tree). Keep it simple.

### 6. Out of scope for this spec

- Fixing `edit_account` to write `display_name` instead of `name` (separate bug; affects SimpleFIN-sourced investment accounts only).
- Collapsible/expandable connection rows (flat indented is fine for the small connection counts).
- Renaming the `/banks/` URL path or any URL names. Only the sidebar label and page heading change; routes stay.
- Reorganizing the Investments tab — manual investment accounts still live there for the "+ Add" / list / edit-broker flows.
- Dashboard "recent transactions" / balance card relabeling (Dashboard already uses `effective_name`).

## Tests

`apps/banking/tests/test_views.py`:
- `test_banks_list_excludes_credit_and_loan` — create checking + credit + loan accounts, hit `/banks/`, assert credit/loan names not in response.
- `test_banks_list_includes_other_type` — confirm `type='other'` accounts still show.

`apps/liabilities/tests/test_services.py`:
- `test_liability_row_includes_type_label` — bank credit account → `"Credit"`; bank loan → `"Loan"`; manual → `"Manual"`.

`apps/liabilities/tests/test_views.py` (new file or extend existing):
- `test_liabilities_list_renders_type_pills` — page contains "Credit", "Loan", "Manual" pill text for the corresponding rows.

`apps/investments/tests/test_views.py`:
- `test_rename_investment_account_persists_display_name`
- `test_rename_investment_account_blank_restores_name`
- `test_rename_investment_account_forbidden_for_other_user`

`apps/accounts/tests/test_settings.py` (or wherever Settings is tested):
- `test_settings_groups_simplefin_accounts_under_institution` — institution row contains its bank accounts and SimpleFIN-sourced investment accounts; manual investment accounts NOT inside the connection block, but in the separate section.

## Risks

- **Settings template restructure is the largest single change.** Mitigation: TDD against the rendered HTML structure (assert specific text appears in the right blocks).
- **`liabilities_for` is also called from the dashboard's net-worth calculation.** Adding `type_label` to `LiabilityRow` shouldn't affect summing, but verify the dashboard's net-worth tests still pass after the change.
- **Sidebar label change is visible everywhere.** Manual smoke check after deploy: visit every page and confirm the active-state highlight still works on `/banks/` (no longer "Banks", now "Cash" — the active class compares URL path, not label, so should be fine).
