# Transactions Page-Size Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded `Paginator(qs, 50)` on the transactions page with a user-controllable page size (25/50/100/200/All) selectable via a `?size=` URL parameter and a dropdown next to the pagination links.

**Architecture:** Module-level helper `_resolve_page_size(request)` in `apps/banking/views.py` that whitelists allowed sizes (anything else → default 50). The selected size flows into the existing `qs_params` dict, which means it propagates through filter/category/pagination links automatically via `filter_qs`. Template adds a `<form method="get">` with hidden inputs for active filters and a `<select onchange="this.form.submit()">` — submitting drops the `page` param so size changes always reset to page 1.

**Tech Stack:** Django 5.1, pytest-django. Tests run via `docker compose exec web pytest` per CLAUDE.md (Dockerfile uses `COPY . .`, no bind mount).

**Spec:** `docs/superpowers/specs/2026-05-05-transactions-page-size-design.md`

---

## File Structure

**Modify:**
- `apps/banking/views.py` — add `_resolve_page_size` helper, wire it into `transactions_list` view, add `size` to `qs_params`, pass `selected_size` to template context
- `apps/banking/templates/banking/transactions_list.html` — add page-size form near the pagination block

**Test:**
- `apps/banking/tests/test_views.py` — extend with page-size cases

---

## Task 1: Add `_resolve_page_size` helper with tests

**Files:**
- Modify: `apps/banking/views.py` (add helper near other module-level helpers ~line 25)
- Test: `apps/banking/tests/test_views.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/banking/tests/test_views.py`:

```python
from apps.banking.views import _resolve_page_size, ALLOWED_PAGE_SIZES


class _FakeReq:
    """Minimal stand-in for Django HttpRequest — only `.GET` is used by the helper."""
    def __init__(self, get_params):
        self.GET = get_params


def test_resolve_page_size_default_when_missing():
    key, n = _resolve_page_size(_FakeReq({}))
    assert key == "50"
    assert n == 50


def test_resolve_page_size_explicit_known_values():
    for raw, expected_n in [("25", 25), ("50", 50), ("100", 100), ("200", 200)]:
        key, n = _resolve_page_size(_FakeReq({"size": raw}))
        assert key == raw
        assert n == expected_n


def test_resolve_page_size_all_caps_at_1000():
    key, n = _resolve_page_size(_FakeReq({"size": "all"}))
    assert key == "all"
    assert n == 1000


def test_resolve_page_size_invalid_falls_back():
    for raw in ["foo", "99", "0", "-50", "1000", " "]:
        key, n = _resolve_page_size(_FakeReq({"size": raw}))
        assert key == "50"
        assert n == 50


def test_resolve_page_size_case_insensitive_for_all():
    key, n = _resolve_page_size(_FakeReq({"size": "ALL"}))
    assert key == "all"
    assert n == 1000


def test_allowed_page_sizes_constants():
    assert set(ALLOWED_PAGE_SIZES.keys()) == {"25", "50", "100", "200", "all"}
    assert ALLOWED_PAGE_SIZES["all"] == 1000
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec web pytest apps/banking/tests/test_views.py -v -k "resolve_page_size or allowed_page_sizes"
```

Expected: 6 failures with `ImportError: cannot import name '_resolve_page_size' ...`

- [ ] **Step 3: Implement the helper**

In `apps/banking/views.py`, add after the existing imports and before `_page_window` (around line 23, immediately after the imports block ending at line 22):

```python
ALLOWED_PAGE_SIZES: dict[str, int] = {"25": 25, "50": 50, "100": 100, "200": 200, "all": 1000}
DEFAULT_PAGE_SIZE_KEY = "50"


def _resolve_page_size(request) -> tuple[str, int]:
    """Map ?size= query param to (raw_key_for_template, integer_per_page).
    Unknown / missing values fall back to the default (50)."""
    raw = (request.GET.get("size") or "").strip().lower()
    if raw in ALLOWED_PAGE_SIZES:
        return raw, ALLOWED_PAGE_SIZES[raw]
    return DEFAULT_PAGE_SIZE_KEY, ALLOWED_PAGE_SIZES[DEFAULT_PAGE_SIZE_KEY]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec web pytest apps/banking/tests/test_views.py -v -k "resolve_page_size or allowed_page_sizes"
```

Expected: 6 passes.

- [ ] **Step 5: Commit**

```bash
git add apps/banking/views.py apps/banking/tests/test_views.py
git commit -m "feat(transactions): add _resolve_page_size helper

Whitelist of 25/50/100/200/all (capped at 1000) with safe fallback
to the existing default of 50 on missing or invalid input."
```

---

## Task 2: Wire helper into `transactions_list` view

**Files:**
- Modify: `apps/banking/views.py` (the `transactions_list` view, around line 318)
- Test: `apps/banking/tests/test_views.py`

- [ ] **Step 1: Write the failing integration tests**

Append to `apps/banking/tests/test_views.py`:

```python
from datetime import date as _date
from decimal import Decimal as _D


@pytest.fixture
def alice_with_60_transactions(alice):
    """Give Alice 60 transactions on a single account so we can exercise pagination."""
    inst = Institution.objects.create(user=alice, name="A Bank", access_url="https://a.example")
    acct = Account.objects.create(
        institution=inst, name="Checking", type="checking",
        balance=_D("1000.00"), external_id="A-1",
    )
    for i in range(60):
        Transaction.objects.create(
            account=acct,
            external_id=f"T-{i}",
            posted_at=_date(2026, 4, 1),
            amount=_D("-10.00"),
            description=f"tx-{i}",
        )
    return alice


def test_transactions_default_page_size_is_50(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("banking:transactions"))
    assert r.status_code == 200
    assert r.context["page_obj"].paginator.per_page == 50
    assert r.context["selected_size"] == "50"


def test_transactions_size_100_loads_all_60(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("banking:transactions") + "?size=100")
    assert r.status_code == 200
    assert r.context["page_obj"].paginator.per_page == 100
    assert r.context["selected_size"] == "100"
    # All 60 fit on one page now.
    assert len(r.context["page_obj"].object_list) == 60


def test_transactions_size_all_caps_at_1000(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("banking:transactions") + "?size=all")
    assert r.context["page_obj"].paginator.per_page == 1000
    assert r.context["selected_size"] == "all"


def test_transactions_size_invalid_falls_back_to_50(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("banking:transactions") + "?size=garbage")
    assert r.context["page_obj"].paginator.per_page == 50
    assert r.context["selected_size"] == "50"


def test_transactions_size_propagates_through_filter_qs(alice_with_60_transactions, alice_client):
    """filter_qs must include `size` so pagination/category links carry it through."""
    r = alice_client.get(reverse("banking:transactions") + "?size=100&q=tx")
    filter_qs = r.context["filter_qs"]
    assert "size=100" in filter_qs
    assert "q=tx" in filter_qs


def test_transactions_default_size_omitted_from_filter_qs(alice_with_60_transactions, alice_client):
    """When size is at default, don't pollute filter_qs with `size=50`."""
    r = alice_client.get(reverse("banking:transactions") + "?q=tx")
    filter_qs = r.context["filter_qs"]
    assert "size=" not in filter_qs
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec web pytest apps/banking/tests/test_views.py -v -k "transactions_default_page_size or transactions_size or transactions_default_size"
```

Expected: 6 failures (most will fail with `KeyError: 'selected_size'` or `assert 50 == 100` etc.).

- [ ] **Step 3: Wire the helper into the view**

In `apps/banking/views.py`, edit the `transactions_list` view. Find (around line 318):

```python
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
```

Replace with:

```python
    size_key, per_page = _resolve_page_size(request)
    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))
```

Then find (around line 324):

```python
    qs_params: dict[str, object] = {}
    if account_id and account_id.isdigit():
        qs_params["account"] = int(account_id)
    if preset:
        qs_params["range"] = preset
    if search:
        qs_params["q"] = search
    if selected_category:
        qs_params["category"] = selected_category
    filter_qs = urlencode(qs_params)
```

After the `if selected_category` block (and before `filter_qs = urlencode(qs_params)`), add:

```python
    if size_key != DEFAULT_PAGE_SIZE_KEY:
        qs_params["size"] = size_key
```

So the block becomes:

```python
    qs_params: dict[str, object] = {}
    if account_id and account_id.isdigit():
        qs_params["account"] = int(account_id)
    if preset:
        qs_params["range"] = preset
    if search:
        qs_params["q"] = search
    if selected_category:
        qs_params["category"] = selected_category
    if size_key != DEFAULT_PAGE_SIZE_KEY:
        qs_params["size"] = size_key
    filter_qs = urlencode(qs_params)
```

Finally, find the `return render(request, "banking/transactions_list.html", { ... })` block (around line 356). Add `"selected_size": size_key,` to the context dict — placement doesn't matter functionally; put it next to `"search": search,`:

```python
    return render(request, "banking/transactions_list.html", {
        "page_obj": page_obj,
        "accounts": accounts,
        "selected_account": selected_account,
        "selected_range": preset,
        "search": search,
        "selected_size": size_key,
        "filter_qs": filter_qs,
        "filter_qs_no_category": filter_qs_no_category,
        "page_window": _page_window(page_obj.number, paginator.num_pages),
        "selected_category": selected_category,
        "top_categories": top_categories,
        "other_categories": other_categories,
        "category_labels": CATEGORY_LABELS,
        "has_any_filter": has_any_filter,
        "filtered_count": filtered_count,
        "pickable_categories": pickable_categories,
    })
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec web pytest apps/banking/tests/test_views.py -v -k "transactions_default_page_size or transactions_size or transactions_default_size"
```

Expected: 6 passes.

- [ ] **Step 5: Run the full banking test suite to catch regressions**

```bash
docker compose exec web pytest apps/banking/ -q
```

Expected: all pass. Existing pagination tests should be unaffected (default behavior preserved when `?size=` is absent).

- [ ] **Step 6: Commit**

```bash
git add apps/banking/views.py apps/banking/tests/test_views.py
git commit -m "feat(transactions): honor ?size= URL param for page size

Pulls the size out of the request via _resolve_page_size and threads it
through both the Paginator and qs_params (so pagination/filter links
preserve it). Default 50 stays absent from the query string to keep
URLs clean for users who never touch the selector."
```

---

## Task 3: Add the page-size selector UI to the template

**Files:**
- Modify: `apps/banking/templates/banking/transactions_list.html` (around the pagination block at line 185-200)

- [ ] **Step 1: Wrap the pagination block and add the selector form**

In `apps/banking/templates/banking/transactions_list.html`, find this block (lines 185-200):

```django
  {# Pagination — numbered links with ellipsis windowing for long ranges #}
  {% if page_obj.has_other_pages %}
  <div class="mt-4 flex flex-wrap items-center justify-center gap-1 text-sm">
    {% for p in page_window %}
      {% if p %}
        {% if p == page_obj.number %}
          <span class="num font-bold px-2.5 py-1 rounded" style="background: var(--tint-positive); color: var(--accent-positive);">{{ p }}</span>
        {% else %}
          <a class="num px-2.5 py-1 rounded hover:underline" href="?{% if filter_qs %}{{ filter_qs }}&{% endif %}page={{ p }}" style="color: var(--muted);">{{ p }}</a>
        {% endif %}
      {% else %}
        <span class="px-1" style="color: var(--dim);">…</span>
      {% endif %}
    {% endfor %}
  </div>
  {% endif %}
```

Replace it with:

```django
  {# Pagination + page-size selector — pagination only renders when there are multiple pages, but the size selector is always available so users with <50 rows can still pick "All" or step down. #}
  <div class="mt-4 flex flex-wrap items-center justify-center gap-3 text-sm">
    {% if page_obj.has_other_pages %}
    <div class="flex flex-wrap items-center justify-center gap-1">
      {% for p in page_window %}
        {% if p %}
          {% if p == page_obj.number %}
            <span class="num font-bold px-2.5 py-1 rounded" style="background: var(--tint-positive); color: var(--accent-positive);">{{ p }}</span>
          {% else %}
            <a class="num px-2.5 py-1 rounded hover:underline" href="?{% if filter_qs %}{{ filter_qs }}&{% endif %}page={{ p }}" style="color: var(--muted);">{{ p }}</a>
          {% endif %}
        {% else %}
          <span class="px-1" style="color: var(--dim);">…</span>
        {% endif %}
      {% endfor %}
    </div>
    {% endif %}

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
  </div>
```

- [ ] **Step 2: Add a template smoke test**

Append to `apps/banking/tests/test_views.py`:

```python
def test_transactions_page_renders_size_selector(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("banking:transactions"))
    assert b'name="size"' in r.content
    # Default option must be marked selected.
    assert b'value="50"' in r.content
    # The marker for "selected" should be on 50, not on 100 (regression check).
    body = r.content.decode()
    assert 'value="50"  selected' in body or 'selected{% endif %}>50' not in body
    # All five options should render.
    for opt in (b'value="25"', b'value="50"', b'value="100"', b'value="200"', b'value="all"'):
        assert opt in r.content


def test_transactions_size_100_marks_correct_option(alice_with_60_transactions, alice_client):
    r = alice_client.get(reverse("banking:transactions") + "?size=100")
    body = r.content.decode()
    # The 100 option should be marked selected; the 50 option should not be.
    import re
    m_100 = re.search(r'value="100"\s*selected', body)
    m_50 = re.search(r'value="50"\s*selected', body)
    assert m_100, "size=100 not marked selected"
    assert not m_50, "size=50 incorrectly marked selected when ?size=100"
```

- [ ] **Step 3: Run the new template tests**

```bash
docker compose exec web pytest apps/banking/tests/test_views.py -v -k "renders_size_selector or marks_correct_option"
```

Expected: 2 passes.

- [ ] **Step 4: Run the full banking test suite as a regression check**

```bash
docker compose exec web pytest apps/banking/ -q
```

Expected: all pass.

- [ ] **Step 5: Rebuild the Docker image and restart the web container**

Per CLAUDE.md: the Dockerfile uses `COPY . .` with no bind mount, so template/static changes don't hot-reload.

```bash
docker compose build web && docker compose up -d
```

- [ ] **Step 6: Manual smoke test in browser**

1. Navigate to `/transactions/` — confirm the dropdown appears below the transactions list, "Show 50" selected by default.
2. Select "100" — page reloads with `?size=100`, dropdown shows "100" selected, more rows visible.
3. Apply a category filter (click any category pill) — confirm `?size=100&category=...` in URL, dropdown still shows 100.
4. Click into page 2 of pagination, then change size to "25" — confirm URL drops the `page` param and lands on page 1.
5. Select "All" — confirm up to 1000 rows render on a single page.
6. Manually edit URL to `?size=garbage` and reload — confirm fallback to default 50 (no error).

- [ ] **Step 7: Commit**

```bash
git add apps/banking/templates/banking/transactions_list.html apps/banking/tests/test_views.py
git commit -m "feat(transactions): page-size selector dropdown next to pagination

Show 25/50/100/200/All. Always visible (even when there's only one page)
so users with few transactions can still expand. Form omits the page
param so changing size always returns to page 1."
```

---

## Done

- All transactions-page tests pass: `docker compose exec web pytest apps/banking/ -q`
- Manual flows verified in browser
- Three commits on branch
