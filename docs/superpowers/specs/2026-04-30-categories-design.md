# Transaction Categories — Design Spec

**Date:** 2026-04-30
**Status:** Approved
**Branch:** `feature/categories`

## Goal

Surface transaction categories in the FinLab UI. Teller's API returns a `details.category` field on every transaction; we ingest it, expose it on the transactions list, and add a "spending by category" view. SimpleFIN doesn't categorize — those transactions start as `uncategorized` and the user can assign categories manually.

## Decisions summary

| # | Decision | Choice |
|---|----------|--------|
| 1 | Provider scope | Teller seeds + manual override on any provider |
| 2 | UI surfaces | Inline pill/edit + spending breakdown + list filter |
| 3 | Vocabulary | Curated fixed list (14 spending + income + transfer + uncategorized) |
| 4 | Income/transfer in chart | Separate income-vs-expense bar; transfers excluded from both |
| 5 | Chart location | Both dashboard widget AND dedicated `/spending/` page |
| 6 | Default time window | 30d on widget, current month on `/spending/` |
| 7 | Storage | `CharField(choices=...)` + `category_manual` boolean on Transaction |
| 8 | Uncategorized in pie | Render as muted grey slice (call to action) |
| 9 | Backfill | Day-one management command for Teller history |

## Category vocabulary

Defined as constants in a new file `apps/banking/categories.py`.

**Spending (14)** — included in the spending breakdown pie:

`groceries`, `dining`, `transportation`, `utilities`, `bills`, `housing`, `health`, `entertainment`, `shopping`, `software`, `travel`, `personal`, `charity`, `other`

**Income (1)** — excluded from pie; summed for the income-vs-expense bar:

`income`

**Transfer (1)** — excluded from pie AND from income/expense bar (account-to-account movement is not net cash flow):

`transfer`

**Uncategorized (1)** — default for any transaction without a known category. Rendered as a muted grey slice in the pie:

`uncategorized`

Total: **17 category values**.

## Teller → FinLab mapping

```python
TELLER_TO_FINLAB = {
    "groceries":      "groceries",
    "dining":         "dining",
    "bar":            "dining",
    "transport":      "transportation",
    "transportation": "transportation",
    "fuel":           "transportation",
    "utilities":      "utilities",
    "phone":          "bills",
    "insurance":      "bills",
    "loan":           "bills",
    "accommodation":  "housing",
    "home":           "housing",
    "health":         "health",
    "entertainment":  "entertainment",
    "sport":          "entertainment",
    "shopping":       "shopping",
    "clothing":       "shopping",
    "electronics":    "shopping",
    "software":       "software",
    "charity":        "charity",
    "income":         "income",
    # Fall-through to "other":
    "tax":         "other",
    "education":   "other",
    "investment":  "other",
    "service":     "other",
    "general":     "other",
    "office":      "other",
    "advertising": "other",
}
```

Helper:

```python
def map_teller_category(teller_value: str | None) -> str:
    if not teller_value:
        return "uncategorized"
    return TELLER_TO_FINLAB.get(teller_value, "uncategorized")
```

Anything Teller adds in the future that isn't in the dict falls through to `uncategorized` and the mapping can be extended without a migration.

## Data model

Migration adds two columns to `apps.banking.Transaction`:

```python
category = models.CharField(
    max_length=20,
    choices=CATEGORY_CHOICES,
    default="uncategorized",
    db_index=True,
)
category_manual = models.BooleanField(default=False)
```

Existing rows default to `uncategorized` / `category_manual=False` via the migration's `default=` clauses. No data migration step inside the migration itself.

The `category_manual` flag mirrors the `cost_basis_source = "manual"` and `display_name` "never overwritten by sync" patterns already used in the codebase.

## Teller ingestion changes

1. **`apps/providers/base.py`** — `TransactionData` dataclass gains `provider_category: str | None = None`.

2. **`apps/providers/teller.py:_parse_transaction`** — extract the field:

   ```python
   provider_category=details.get("category")
   ```

3. **Sync writer** (the function that turns `TransactionData` → DB rows; in `apps/banking/services.py`) — when upserting:
   - On INSERT: set `category = map_teller_category(payload.provider_category)`, `category_manual = False`.
   - On UPDATE: if existing row has `category_manual=True`, **leave category unchanged**. Otherwise re-apply the mapping.

4. **SimpleFIN parser** — leaves `provider_category=None`. The sync writer then maps it to `uncategorized`.

## Service layer

New functions added to `apps/banking/services.py`:

```python
@dataclass
class CategoryTotal:
    category: str          # the key, e.g., "groceries"
    label: str             # display label, e.g., "Groceries"
    color: str             # CSS color from CATEGORY_COLORS
    total: Decimal         # always positive (abs of display_amount)
    percent: float         # share of total spending

def spending_breakdown(user, start, end) -> list[CategoryTotal]:
    """Per-category spending totals for the date range, descending by total.
    Includes 'uncategorized' as a slice (muted color) so users see their backlog.
    Excludes income and transfer.
    Uses Transaction.display_amount so credit/loan sign-flipping is respected.
    """

def income_expense_summary(user, start, end) -> tuple[Decimal, Decimal]:
    """(income_total, expense_total). Income = sum of display_amount where
    category=='income' (positive). Expense = abs(sum) of display_amount over
    SPENDING_CATEGORIES + uncategorized. Transfers excluded from both."""

def set_category(transaction: Transaction, category: str) -> Transaction:
    """Sets category and category_manual=True. Idempotent. Validates the
    category value is in ALL_CATEGORIES."""
```

All queries scope through `Transaction.objects.for_user(user)` per existing convention.

## UI surfaces

### 1. Dashboard widget — `last 30 days`

New module on the existing dashboard between net-worth sparkline and recent-transactions. Contents:

- Header row: "Spending · last 30 days" + "View all →" link to `/spending/`.
- 100px pie (server-rendered SVG, same approach as the existing sparkline tag).
- Legend listing top 4 categories + uncategorized (if non-zero), each with `$total`.

### 2. `/spending/` page — current month default

New URL: `/spending/`. New view in `apps/banking/views.py`. New template `apps/banking/templates/banking/spending.html`.

Layout (desktop, two-column split):

- Header: "Spending" title + a 30d/Month/YTD toggle (default: current Month).
- Left column: 160px pie chart (server-rendered SVG).
- Right column:
  - "Income vs Expense" bar (horizontal stacked bar, two segments + net figure).
  - "By category" sortable list — pill + `$total` per row, descending. Clicking a row drills into `/banking/transactions/?category=<key>`.

Mobile: vertical stack — toggle, pie, income/expense bar, category list.

### 3. Transactions list — pills + filter

Modify `apps/banking/templates/banking/transactions_list.html`:

- Each row gets a category pill next to the payee. Pill color from `CATEGORY_COLORS`.
- Filter bar above the list: "All" + the 5 spending categories with the most transactions for this user (descending count, computed at request time) as filter pills, rest behind a "More ▾" dropdown. URL query param `?category=<key>` (already used by drill-down). For new users with no data, fall back to a default order: groceries, dining, transportation, utilities, shopping.
- Mobile: horizontal-scroll chip strip; less common categories collapse under "More ▾".

### 4. Inline category picker

**Desktop:** click any pill → small dropdown opens directly below. Top 6 spending categories by transaction count for this user (same logic as the filter bar) + "Show all 14 →" link that expands to a 2-column grid. POST to `/banking/transactions/<id>/set-category/` → server returns the updated pill HTML → client swaps in place. Sets `category_manual=True`.

> **Constraint:** the inline picker must not feel overloaded. If the 14-item desktop popup feels heavy in practice, fall back to grouped sections or a typeahead. Validate during implementation; iterate if needed.

**Mobile:** click pill → bottom drawer slides up with a 2-column grid of all 14 spending categories (income/transfer/uncategorized hidden — those aren't user-assignable in normal flow). Tap outside to dismiss.

## Drill-down behavior

Clicking a wedge in the pie chart, OR a category row in the breakdown list, OR a filter pill on the transactions list — all navigate to `/banking/transactions/?category=<key>` showing only matching transactions. The filter bar reflects the active category.

## Backfill management command

New command `apps/banking/management/commands/categorize_existing_teller.py`:

```
python manage.py categorize_existing_teller [--user <username>]
```

For each Teller institution (optionally scoped to one user):

1. Walk all of the institution's transactions via the existing pagination logic. **No `since` filter** — fetch full history Teller exposes.
2. For each transaction, look up the existing `Transaction` row by `external_id`.
3. If found AND `category_manual=False`: apply `map_teller_category()` and save.
4. If `category_manual=True`: skip (preserve the user's override).
5. Don't insert new rows — this is enrichment only.

SimpleFIN-sourced transactions are not touched.

Run this once after the migration deploys. Idempotent — safe to re-run.

## Testing

New file `apps/banking/tests/test_categories.py`:
- `map_teller_category()` — each Teller value, unknown values, `None`.
- `CATEGORY_CHOICES` shape, `CATEGORY_COLORS` keys cover all categories.

Extend `apps/banking/tests/test_services.py`:
- `spending_breakdown()` — excludes income/transfer, includes uncategorized as a slice, descending order, user-isolation, percent sums to 100, empty-range returns empty list.
- `income_expense_summary()` — correct totals, transfers excluded.
- `set_category()` — sets `category_manual=True`, validates input, idempotent.

Extend `apps/providers/tests/test_teller.py`:
- `_parse_transaction` populates `provider_category` from `details.category`.
- `_parse_transaction` handles missing `details.category` (None).

Extend `apps/banking/tests/test_services.py` (where the existing sync tests live):
- **Critical regression test:** create a `Transaction` with `category_manual=True`. Run a sync that would otherwise rewrite it. Assert category unchanged.
- Without `category_manual`, sync re-applies the mapped value on update.
- New rows from Teller get the mapped category and `category_manual=False`.
- New rows from SimpleFIN get `uncategorized` and `category_manual=False`.

New view tests:
- GET `/spending/` requires login.
- GET `/spending/?period=30d` returns last-30-days totals.
- GET `/banking/transactions/?category=groceries` filters correctly.
- POST `/banking/transactions/<id>/set-category/` requires login, validates input, sets `category_manual=True`, returns updated pill HTML.

Backfill command test:
- Updates Teller transactions where `category_manual=False`.
- Skips rows where `category_manual=True`.
- Doesn't touch SimpleFIN transactions.
- Idempotent: running twice yields the same result.

## Migration & deployment

1. Branch `feature/categories` off master (already done).
2. Implement the changes; commit incrementally.
3. Open PR; review.
4. Merge to master.
5. On the homelab: `git pull && docker compose build web && docker compose up -d` to pick up code changes (per the rebuild constraint in CLAUDE.md).
6. `docker compose exec web python manage.py migrate` to apply the column additions.
7. `docker compose exec web python manage.py categorize_existing_teller` to backfill.
8. Sanity-check the dashboard widget and `/spending/` page in the browser.

## Out of scope (deferred)

- Per-user custom categories (would require swapping `CharField` → FK to a `Category` model). Easy migration path if requested later.
- Auto-categorization rules ("if payee contains X, set category to Y") for SimpleFIN transactions. This was Question 1 option C, explicitly deferred.
- Category-level budgets / alerts.
- Time-series view (spending per category over time, e.g., last 6 months stacked).
- Export of category data via the existing XLSX export.
- Mobile bottom-drawer animation polish.
