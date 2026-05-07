# Seamless Refresh + Last-Synced Indicator — Design Spec

**Date:** 2026-05-07
**Status:** Approved
**Branch:** TBD (likely `feature/seamless-refresh`)

## Goal

Today the top-bar ⟳ button POSTs to `sync_all` (`apps/accounts/views.py:64`) which runs synchronously. With multiple institutions and a handful of scraped assets, the request commonly exceeds the proxy/gunicorn timeout: the browser shows an "internal server error", but the worker keeps running, so a reload a minute later "works." This is annoying and obscures whether anything actually refreshed.

The user also wants a visible "last synced" stamp in the top bar so they know when data is fresh without having to click anything.

This spec covers three coupled changes:
1. **Make refresh asynchronous** — fire-and-forget background work + a status endpoint, so the request returns instantly and the UI reflects in-flight state.
2. **Speed up the work itself** — parallelize the per-symbol Stooq fetches and the per-asset web scrapes.
3. **Show last-synced** in the top bar, relative time with absolute on hover, with a spinner while a sync is running.

SimpleFIN is currently unused, so it is dropped from the `sync_all` flow for now (services left intact for future re-enable).

## Decisions summary

| # | Decision | Choice |
|---|----------|--------|
| 1 | Async strategy | `threading.Thread` background worker (no Redis/Celery) |
| 2 | Persistence of sync state | New `SyncRun` model, history retained, latest row drives UI |
| 3 | While a sync is running, repeat clicks | Button disabled in UI; view rejects duplicate runs as defense-in-depth |
| 4 | Top-bar timestamp format | Relative ("5m ago") with absolute on `title=` hover |
| 5 | SimpleFIN handling | Stop calling from `sync_all`; leave services in place |
| 6 | Speed up Stooq | `ThreadPoolExecutor(max_workers=8)` over per-symbol HTTP |
| 7 | Speed up scraped assets | `ThreadPoolExecutor(max_workers=8)` over per-asset HTTP; DB writes serialized after futures resolve |
| 8 | Stuck-run recovery | Status endpoint coerces `running` rows older than 5 minutes to `error` |

## Model change

**File:** `apps/accounts/models.py`

New model:

```python
class SyncRun(models.Model):
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "running"),
        (STATUS_SUCCESS, "success"),
        (STATUS_ERROR, "error"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sync_runs")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    summary = models.TextField(blank=True, default="")
    errors_text = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["user", "-started_at"])]
        ordering = ["-started_at"]
```

A new migration creates the table. No data backfill needed — first refresh after deploy creates the first row.

## Background worker

**New file:** `apps/accounts/services.py`

```python
def start_sync(user) -> SyncRun:
    """Create a SyncRun row and spawn a worker thread. Returns immediately."""
    run = SyncRun.objects.create(user=user, status=SyncRun.STATUS_RUNNING)
    t = threading.Thread(target=_run_sync, args=(user.id, run.id), daemon=True)
    t.start()
    return run

def _run_sync(user_id: int, run_id: int) -> None:
    """Worker body. Runs in a fresh thread; closes its DB connections at the end."""
    try:
        user = User.objects.get(pk=user_id)
        refreshed_holdings = refresh_manual_prices(user=user)
        asset_result = refresh_scraped_assets(user=user)
        summary = (
            f"{refreshed_holdings} manual price(s), "
            f"{asset_result.updated} asset(s)."
        )
        errors = "; ".join(f"asset {aid}: {msg}" for aid, msg in asset_result.failed)
        SyncRun.objects.filter(pk=run_id).update(
            status=SyncRun.STATUS_SUCCESS,
            summary=summary,
            errors_text=errors,
            finished_at=timezone.now(),
        )
    except Exception as exc:
        SyncRun.objects.filter(pk=run_id).update(
            status=SyncRun.STATUS_ERROR,
            errors_text=str(exc),
            finished_at=timezone.now(),
        )
    finally:
        from django.db import connections
        connections.close_all()
```

`daemon=True` so the thread doesn't block process shutdown. `connections.close_all()` releases the per-thread DB connection.

For testability, `start_sync` accepts an optional `runner=` kwarg defaulting to the threaded runner; tests pass a synchronous runner.

## View changes

**File:** `apps/accounts/views.py`

`sync_all` becomes:

```python
@login_required
@require_http_methods(["POST"])
def sync_all(request):
    user = request.user
    if SyncRun.objects.filter(user=user, status=SyncRun.STATUS_RUNNING).exists():
        # Defense-in-depth: UI button is disabled, but a stale tab could still POST.
        messages.info(request, "A sync is already in progress.")
    else:
        start_sync(user)
        messages.success(request, "Sync started.")

    next_url = request.POST.get("next") or reverse("home")
    if not next_url.startswith("/"):
        next_url = reverse("home")
    return HttpResponseRedirect(next_url)
```

SimpleFIN and the inline `refresh_manual_prices`/`refresh_scraped_assets` calls are gone from this view. `views.py` drops its imports of `sync_institution`, `sync_simplefin_investments`, `refresh_manual_prices`, `refresh_scraped_assets`, `Institution`, and `Asset`. The worker (`apps/accounts/services.py`) imports `refresh_manual_prices` and `refresh_scraped_assets`. The SimpleFIN service functions remain in their existing modules untouched, ready for future re-enable.

## Status endpoint

**File:** `apps/accounts/views.py`

```python
STALE_RUN_AFTER = timedelta(minutes=5)

@login_required
@require_http_methods(["GET"])
def sync_status(request):
    run = SyncRun.objects.filter(user=request.user).order_by("-started_at").first()
    if run is None:
        return JsonResponse({"status": "idle", "summary": "", "finished_at_iso": None,
                             "finished_at_absolute": None, "finished_at_relative": None,
                             "errors": ""})

    # Coerce stuck "running" rows so a process restart doesn't leave the UI spinning.
    if run.status == SyncRun.STATUS_RUNNING and timezone.now() - run.started_at > STALE_RUN_AFTER:
        SyncRun.objects.filter(pk=run.pk, status=SyncRun.STATUS_RUNNING).update(
            status=SyncRun.STATUS_ERROR,
            errors_text="sync interrupted",
            finished_at=timezone.now(),
        )
        run.refresh_from_db()

    return JsonResponse({
        "status": run.status,
        "summary": run.summary,
        "errors": run.errors_text,
        "finished_at_iso": run.finished_at.isoformat() if run.finished_at else None,
        "finished_at_absolute": format_absolute(run.finished_at) if run.finished_at else None,
        "finished_at_relative": format_relative(run.finished_at) if run.finished_at else None,
    })
```

URL: `path("sync-status/", views.sync_status, name="sync_status")` in `apps/accounts/urls.py`.

`format_absolute` returns `"May 7, 2026, 3:42 PM"` in the user's local time (best-effort: server timezone is fine for a personal homelab tool). `format_relative` returns `"just now"` / `"Xm ago"` / `"Xh ago"` / `"Xd ago"`.

## Parallelization

**File:** `apps/providers/prices/stooq.py`

```python
def fetch_quotes(self, symbols: Iterable[str]) -> list[PriceQuote]:
    normalized = [s.strip().upper() for s in symbols if s and s.strip()]
    if not normalized:
        return []
    now = datetime.now(tz=timezone.utc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(self._safe_fetch_one, s, now): s for s in normalized}
        return [q for f in concurrent.futures.as_completed(futures)
                if (q := f.result()) is not None]

def _safe_fetch_one(self, symbol, at):
    try:
        return self._fetch_one(symbol, at)
    except Exception:
        return None
```

The old `# Stooq is fast and lightweight, the cost is negligible` comment is removed (no longer accurate at scale).

**File:** `apps/assets/services.py`

```python
def refresh_scraped_assets(*, user) -> RefreshResult:
    assets = list(Asset.objects.for_user(user).filter(kind="scraped"))
    scraper = get_scraper("css")

    fetched: list[tuple[Asset, ScrapeResult | None, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        future_to_asset = {
            pool.submit(_safe_scrape, scraper, a): a for a in assets if a.source_url
        }
        for fut in concurrent.futures.as_completed(future_to_asset):
            a = future_to_asset[fut]
            result, err = fut.result()
            fetched.append((a, result, err))

    updated = 0
    failed: list[tuple[int, str]] = [(a.id, "no source_url") for a in assets if not a.source_url]

    with transaction.atomic():
        for a, result, err in fetched:
            if err:
                failed.append((a.id, err))
                continue
            a.last_unit_price = result.price.quantize(Decimal("0.0001"))
            a.current_value = (result.price * a.quantity).quantize(Decimal("0.01"))
            a.last_priced_at = result.at
            a.save(update_fields=["last_unit_price", "current_value", "last_priced_at"])
            _snapshot(a)
            updated += 1

    return RefreshResult(updated=updated, failed=failed)
```

DB writes happen serially after futures resolve, inside one `transaction.atomic()`. This matches the existing semantics (one transaction per refresh) without trying to share a Django connection across threads.

## Frontend

**File:** `apps/accounts/templates/base.html`

The current top-bar block (around line 55) becomes:

```html
<div id="sync-bar" class="flex items-center gap-2"
     data-status-url="{% url 'sync_status' %}"
     data-sync-url="{% url 'sync_all' %}">
  <span class="text-xs" style="color: var(--muted);">
    Last synced
    <time id="sync-time" datetime=""
          title="">never</time>
  </span>
  <form id="sync-form" action="{% url 'sync_all' %}" method="post" class="m-0">
    {% csrf_token %}
    <input type="hidden" name="next" value="{{ request.get_full_path }}">
    <button id="sync-btn" type="submit" class="p-1 text-sm" style="color: var(--muted);"
            aria-label="Sync everything"
            title="Sync everything (manual prices + scraped assets)">⟳</button>
  </form>
</div>
```

Inline JS (sketch — actual file lives in a `<script>` block at the bottom of `base.html`):

```js
(function () {
  const bar = document.getElementById("sync-bar");
  if (!bar) return;
  const btn = document.getElementById("sync-btn");
  const form = document.getElementById("sync-form");
  const timeEl = document.getElementById("sync-time");
  const statusUrl = bar.dataset.statusUrl;

  let polling = false;

  function applyStatus(s) {
    if (s.finished_at_iso) {
      timeEl.dateTime = s.finished_at_iso;
      timeEl.title = s.finished_at_absolute;
      timeEl.textContent = s.finished_at_relative;
    }
    if (s.status === "running") {
      btn.disabled = true;
      btn.textContent = "…"; // simple spinner
      if (!polling) startPolling();
    } else {
      btn.disabled = false;
      btn.textContent = "⟳";
      polling = false;
    }
  }

  async function fetchStatus() {
    const r = await fetch(statusUrl, {credentials: "same-origin"});
    if (r.ok) applyStatus(await r.json());
  }

  function startPolling() {
    polling = true;
    const tick = async () => {
      if (!polling) return;
      await fetchStatus();
      if (polling) setTimeout(tick, 2000);
    };
    tick();
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    btn.disabled = true;
    btn.textContent = "…";
    const r = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
    });
    // The view returns a redirect to the same page; fetch follows it automatically.
    // We discard the response body and just begin polling.
    startPolling();
  });

  // Refresh relative text every 30s without re-fetching the server.
  setInterval(() => {
    if (timeEl.dateTime) {
      timeEl.textContent = humanizeRelative(new Date(timeEl.dateTime));
    }
  }, 30000);

  fetchStatus();
})();

function humanizeRelative(d) {
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 45) return "just now";
  if (s < 60 * 60) return `${Math.round(s / 60)}m ago`;
  if (s < 60 * 60 * 24) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
```

Errors from a finished run surface via the existing Django messages flash on the next navigation. (Stretch: render `s.errors` directly in a tooltip on the time element if non-empty. Not required for this spec.)

## URL changes

**File:** `apps/accounts/urls.py`

Add:

```python
path("sync-status/", views.sync_status, name="sync_status"),
```

`sync-all/` keeps its existing path.

## Middleware

`LoginRequiredMiddleware` already gates these — both `sync_all` and `sync_status` use `@login_required`. No `EXEMPT_PATH_PREFIXES` change needed.

## Testing

**File:** `apps/accounts/tests/test_sync.py` (new)

- `test_sync_all_creates_running_run_and_redirects` — POST creates a `SyncRun(status=running)` and redirects.
- `test_sync_all_rejects_when_already_running` — second POST while a running row exists does not create a new run.
- `test_run_sync_success_marks_complete` — invoke `_run_sync` synchronously with mocked services; assert `status=success`, `summary` populated, `finished_at` set.
- `test_run_sync_error_marks_failed` — service raises; `status=error`, `errors_text` populated.
- `test_sync_status_returns_latest` — JSON shape matches contract.
- `test_sync_status_coerces_stale_running` — running row >5 min old is flipped to error on read.
- `test_sync_status_idle_when_no_runs` — first-ever load returns `status=idle`.

**File:** `apps/providers/prices/tests/test_stooq.py` (extend)

- `test_fetch_quotes_parallel_returns_same_shape` — 5 mocked symbols, asserts result count + types match the old sequential output.
- `test_fetch_quotes_individual_failure_does_not_kill_batch` — one mock raises, others succeed.

**File:** `apps/assets/tests/test_services.py` (extend)

- `test_refresh_scraped_assets_parallel` — 4 mocked assets, all succeed; assert `updated=4`.
- `test_refresh_scraped_assets_partial_failure` — one mock raises; assert it appears in `failed` and the others still update.
- `test_refresh_scraped_assets_no_source_url_still_reported` — assets with empty `source_url` appear in `failed` with `"no source_url"`.

## Out of scope

- Streaming progress (current X of N) — overkill for a sub-5s sync.
- Per-institution refresh status in the settings page — that flow is unchanged.
- Re-enabling SimpleFIN. When that comes back, add it to `_run_sync` and (probably) a separate sub-summary line.
- Any Celery / Redis / Django-Q migration — explicitly rejected as overkill.

## Risk notes

- **Threading + Django ORM:** safe as long as each thread calls `connections.close_all()` at the end. The worker does.
- **Process restart mid-sync:** the SyncRun row stays `running` until the 5-minute stale-coerce kicks in. Acceptable for a homelab tool.
- **Concurrent writes within `transaction.atomic()` from the worker thread:** writes happen after the parallel HTTP work resolves, on a single thread, so there's no cross-thread ORM access during the transaction.
