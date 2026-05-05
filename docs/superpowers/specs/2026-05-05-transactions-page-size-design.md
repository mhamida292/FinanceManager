# Transactions Page-Size Selector — Design Spec

**Date:** 2026-05-05
**Status:** Approved
**Branch:** `master` (small enough to ship direct)

## Goal

Let the user choose how many transactions appear on each page of `/transactions/`. Today the page size is hard-coded at 50; we want a dropdown next to the pagination that offers 25 / 50 / 100 / 200 / All.

## Decisions summary

| # | Decision | Choice |
|---|----------|--------|
| 1 | Sizes offered | `25, 50, 100, 200, All` |
| 2 | "All" cap | 1000 (paginator backstop, not a hard error) |
| 3 | Persistence | URL param only (`?size=`); no cookie/profile storage |
| 4 | UI placement | Bottom of page, paired with pagination links |
| 5 | Page reset on size change | Always jump to page 1 |
| 6 | Default | 50 (preserves existing behavior) |
| 7 | Invalid input | Silently fall back to 50 |

## Backend changes

**File:** `apps/banking/views.py`

Add a module-level helper:

```python
ALLOWED_PAGE_SIZES = {"25": 25, "50": 50, "100": 100, "200": 200, "all": 1000}
DEFAULT_PAGE_SIZE_KEY = "50"

def _resolve_page_size(request) -> tuple[str, int]:
    """Returns (raw_key_for_template, integer_per_page)."""
    raw = (request.GET.get("size") or "").strip().lower()
    if raw in ALLOWED_PAGE_SIZES:
        return raw, ALLOWED_PAGE_SIZES[raw]
    return DEFAULT_PAGE_SIZE_KEY, ALLOWED_PAGE_SIZES[DEFAULT_PAGE_SIZE_KEY]
```

In `transactions_list` view, replace `paginator = Paginator(qs, 50)` with:

```python
size_key, per_page = _resolve_page_size(request)
paginator = Paginator(qs, per_page)
```

Add `size_key` to the `qs_params` dict only when it's non-default:

```python
if size_key != DEFAULT_PAGE_SIZE_KEY:
    qs_params["size"] = size_key
```

That single line makes every existing pagination link, category-pill link, and filter link carry the size through automatically — `filter_qs` and `filter_qs_no_category` are already built from `qs_params`.

Add `selected_size` to the render context (value: `size_key`) so the template can mark the active option.

## Template changes

**File:** `apps/banking/templates/banking/transactions_list.html`

Insert a `<form method="get">` adjacent to the pagination block at the bottom of the page (around line 187). Layout: pagination centered, page-size selector to its right.

The form contains hidden inputs for every active filter (`account`, `range`, `q`, `category`) so submitting preserves them. **No `page` hidden input** — submitting drops `page`, which is the desired "reset to page 1" behavior. The `<select>` auto-submits on change via `onchange="this.form.submit()"`.

```django
<form method="get" class="flex items-center gap-2 text-xs">
  {% if selected_account %}<input type="hidden" name="account" value="{{ selected_account }}">{% endif %}
  {% if selected_range %}<input type="hidden" name="range" value="{{ selected_range }}">{% endif %}
  {% if search %}<input type="hidden" name="q" value="{{ search }}">{% endif %}
  {% if selected_category %}<input type="hidden" name="category" value="{{ selected_category }}">{% endif %}
  <label for="size" style="color: var(--muted);">Show</label>
  <select name="size" id="size" onchange="this.form.submit()"
          class="num rounded px-2 py-1"
          style="background: var(--surface); border: 1px solid var(--border); color: var(--text);">
    <option value="25"  {% if selected_size == '25'  %}selected{% endif %}>25</option>
    <option value="50"  {% if selected_size == '50'  %}selected{% endif %}>50</option>
    <option value="100" {% if selected_size == '100' %}selected{% endif %}>100</option>
    <option value="200" {% if selected_size == '200' %}selected{% endif %}>200</option>
    <option value="all" {% if selected_size == 'all' %}selected{% endif %}>All</option>
  </select>
</form>
```

**Layout:** the pagination block and the size form sit together at the bottom inside a single flex container — pagination centered (existing behavior), size form right-aligned via `ml-auto` or a `justify-between` parent. When there's only one page (`page_obj.has_other_pages` is false), the pagination links don't render but the size selector still does, so users with 30 transactions can still switch to "All" and back.

## Edge cases

- **`?size=all` with >1000 rows:** Paginator returns 2 pages. Acceptable; flag for revisit only if a user actually accumulates >1000 transactions and complains.
- **`?size=foo` / `?size=99`:** falls through to default 50, no error message.
- **Existing bookmarks / links:** unchanged (no `size` param means default 50, identical to current behavior).
- **Filter changes:** category-pill links and the search/range form already build from `qs_params`/`filter_qs`, so adding `size` to that dict propagates it through every filter UI without further template edits.

## Testing

One new test in `apps/banking/tests/`:

```python
def test_transactions_size_param(client, user_with_data):
    client.force_login(user_with_data.user)
    # default
    r = client.get("/transactions/")
    assert r.context["page_obj"].paginator.per_page == 50
    # explicit
    r = client.get("/transactions/?size=100")
    assert r.context["page_obj"].paginator.per_page == 100
    # all → 1000 cap
    r = client.get("/transactions/?size=all")
    assert r.context["page_obj"].paginator.per_page == 1000
    # invalid → default
    r = client.get("/transactions/?size=garbage")
    assert r.context["page_obj"].paginator.per_page == 50
```

Existing pagination tests should keep passing unchanged.

## Out of scope

- No persistence (cookie / user profile). Pure URL param.
- No "remember last size" behavior.
- No application elsewhere (the only paginated page in FinLab today is `/transactions/`; if/when others gain pagination, this pattern can be lifted into a shared helper).
- No telemetry / analytics on which size users pick.
