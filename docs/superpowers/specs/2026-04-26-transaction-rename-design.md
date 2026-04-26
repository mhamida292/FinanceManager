# Transaction Rename — Design

**Date:** 2026-04-26
**Status:** Approved, awaiting implementation plan

## Summary

Let users rename individual transactions. The user-supplied label takes display priority over the provider-supplied `payee`/`description`, persists across SimpleFIN syncs, and is searchable. Per-row only — no rule-based bulk rename (that belongs in the future categories/auto-classification feature).

## Motivation

Bank-supplied payees are often noisy ("AMZN MKTP US*A1B2C3"), and users want to clean them up. Institutions and Accounts already support rename via `display_name`/`effective_name`; transactions did not. This closes the gap using the same pattern, so the codebase stays consistent.

## Design

### Model

`apps/banking/models.py` — add a field and a property to `Transaction`:

```python
display_name = models.CharField(
    max_length=200, blank=True, default="",
    help_text="Optional override shown in the UI. Blank = use payee/description. Never overwritten by sync.",
)

@property
def effective_payee(self) -> str:
    return self.display_name or self.payee or self.description
```

Schema mirrors `Institution.display_name` and `Account.display_name` exactly.

### View + URL

`apps/banking/views.py`:

```python
@login_required
@require_http_methods(["GET", "POST"])
def rename_transaction(request, transaction_id):
    transaction = get_object_or_404(
        Transaction.objects.for_user(request.user), pk=transaction_id
    )
    if request.method == "POST":
        transaction.display_name = request.POST.get("display_name", "").strip()
        transaction.save(update_fields=["display_name"])
        messages.success(request, f'Renamed to "{transaction.effective_payee}".')
        return HttpResponseRedirect(_safe_back(request, default=reverse("transactions")))
    return render(request, "banking/rename_form.html", {
        "subject": "transaction",
        "object": transaction,
        "cancel_url": _safe_back(request, default=reverse("transactions")),
        "current_value": transaction.display_name,
        "fallback_value": transaction.payee or transaction.description,
    })
```

A small `_safe_back(request, default)` helper validates the `Referer` header against the host before honoring it; otherwise returns `default`. This lets rename work from both `transactions_list` and `account_detail` without hardcoding either.

Note on URL names: the transactions list is wired in `apps/accounts/urls.py` as `name="transactions"` at the root namespace (no `banking:` prefix), so the reverse target is `"transactions"`.

`apps/banking/urls.py` — add:

```python
path("transactions/<int:transaction_id>/rename/", views.rename_transaction, name="rename_transaction"),
```

### Template — reuse

The existing `apps/banking/templates/banking/rename_form.html` is already generic over `subject` / `fallback_value` / `current_value` / `cancel_url`. No changes required.

### Templates — display + entry points

- `apps/banking/templates/banking/transactions_list.html` (desktop table rows + mobile cards): swap the current payee/description rendering for `{{ tx.effective_payee }}`. Append a small `✎` link per row pointing to `{% url 'banking:rename_transaction' tx.id %}`.
- `apps/banking/templates/banking/account_detail.html`: same swap and same `✎` link in the embedded transaction list.

### Search

`transactions_list` view's search filter currently:

```python
qs = qs.filter(Q(payee__icontains=search) | Q(description__icontains=search) | Q(memo__icontains=search))
```

Extend to include `display_name`:

```python
qs = qs.filter(
    Q(display_name__icontains=search)
    | Q(payee__icontains=search)
    | Q(description__icontains=search)
    | Q(memo__icontains=search)
)
```

### Sync — no change required

`apps/banking/services.py` syncs transactions via `Transaction.objects.update_or_create(account=..., external_id=..., defaults={...})`. `display_name` is not in `defaults`, so it survives subsequent syncs untouched. This is the same mechanism Institution/Account renames already rely on.

### XLSX export

`apps/exports/services.py:62` currently writes `tx.payee or tx.description or ""` for the payee column. Swap to `tx.effective_payee` so exports reflect the user's renames consistently with the on-screen views.

### Migration

Auto-generated `AddField` for `Transaction.display_name`. Single migration, no data migration needed (default `""` matches the field default).

## Tests

`apps/banking/tests/` — mirror the existing rename tests:

1. `test_rename_transaction_persists_display_name` — POST to rename, assert `display_name` saved and `effective_payee` reflects it.
2. `test_rename_transaction_blank_restores_provider_payee` — POST blank, assert `display_name=""` and `effective_payee` falls back to `payee`.
3. `test_rename_transaction_forbidden_for_other_user` — bob tries to rename alice's txn, expect 404.
4. `test_sync_does_not_overwrite_transaction_rename` — set `display_name`, run sync that returns the same `external_id` with a fresh `payee`, assert `display_name` survives and `payee` is updated.
5. `test_search_matches_renamed_transaction` — search by the user's custom label hits the row.
6. `test_xlsx_export_uses_renamed_payee` — set `display_name`, run the exports service, assert the rendered payee column equals the override (extends `apps/exports/tests/test_export.py`).

## Out of scope

- Bulk rename / "apply to all matching" — defer to categories/rules feature.
- Auto-classification rules.
- Editing other transaction fields (amount, posted_at, memo).
- Rename history / audit log.

## Risks

- **Search scope creep:** including `display_name` in the OR filter is correct, but the field is not indexed. With <100k transactions per user it's fine; if it ever matters, add a `db_index` later.
- **Template churn:** two templates touched (transactions list, account detail). Existing tests cover the views; visual changes need a manual smoke check.
