"""Sync orchestration for the top-bar ⟳ button.

The view calls `start_sync(user)` which creates a SyncRun row and dispatches
the actual refresh work to a background thread. The thread invokes the
existing per-domain refresh services (Teller bank sync, manual investment
prices, scraped assets) and writes the final status back to the SyncRun row.

SimpleFIN institutions are deliberately skipped here — they're handled by
the nightly cron and the per-institution button on the settings page. To
re-include them, drop the `.exclude(provider="simplefin")` filter below.

Tests pass `runner=` to skip the thread and run synchronously.
"""
from __future__ import annotations

import concurrent.futures
import threading
from datetime import datetime
from typing import Callable

from django.contrib.auth import get_user_model
from django.db import connections
from django.utils import timezone

from apps.assets.services import refresh_scraped_assets
from apps.banking.models import Institution
from apps.banking.services import sync_institution
from apps.investments.services import refresh_manual_prices

from .models import SyncRun

User = get_user_model()

Runner = Callable[[int, int], None]


def start_sync(user, *, runner: Runner | None = None) -> SyncRun:
    """Create a SyncRun and kick off the worker.

    Returns the SyncRun row immediately. The default runner spawns a daemon
    thread; tests pass a synchronous runner.
    """
    run = SyncRun.objects.create(user=user, status=SyncRun.STATUS_RUNNING)
    (runner or _spawn_thread)(user.id, run.id)
    return run


def _spawn_thread(user_id: int, run_id: int) -> None:
    """Spawn a daemon thread that runs the worker and closes its DB connection on exit.

    Connection cleanup lives here (not inside `_run_sync`) so the worker function
    is thread-agnostic — tests can call `_run_sync` directly on the main thread
    without inadvertently closing pytest-django's connection.
    """
    def _target() -> None:
        try:
            _run_sync(user_id, run_id)
        finally:
            connections.close_all()

    threading.Thread(target=_target, daemon=True).start()


def _run_sync(user_id: int, run_id: int) -> None:
    """Worker body — pure logic, no thread-lifecycle concerns.

    Safe to call synchronously from tests. Connection cleanup is the
    responsibility of the caller that put us on a thread (see `_spawn_thread`).

    Per-institution failures are isolated: a single bad Teller cert doesn't
    abort the rest of the sync. Institution-level errors are joined with any
    per-asset scrape errors into `errors_text`; the overall run is still
    reported as `success` so the UI doesn't scream when one corner is broken.
    """
    try:
        user = User.objects.get(pk=user_id)

        institutions = list(Institution.objects.for_user(user).exclude(provider="simplefin"))
        institution_errors: list[str] = []
        transactions_total = 0

        def _sync_one(inst):
            try:
                return inst, sync_institution(inst), None
            except Exception as exc:
                return inst, None, exc
            finally:
                connections.close_all()  # each pool thread owns its own DB connection

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for inst, result, exc in pool.map(_sync_one, institutions):
                if exc:
                    institution_errors.append(f"{inst.effective_name}: {exc}")
                else:
                    transactions_total += result.transactions_created

        refreshed_holdings = refresh_manual_prices(user=user)
        asset_result = refresh_scraped_assets(user=user)

        summary = (
            f"{transactions_total} transaction(s), "
            f"{refreshed_holdings} manual price(s), "
            f"{asset_result.updated} asset(s)."
        )
        asset_errors = [f"asset {aid}: {msg}" for aid, msg in asset_result.failed]
        errors = "; ".join(institution_errors + asset_errors)

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


# ---------- Timestamp formatting (used by sync_status endpoint) ----------

def format_absolute(dt: datetime) -> str:
    """e.g. 'May 7, 2026, 3:42 PM' — server-local time is fine for a personal homelab tool.

    Avoids the POSIX-only ``%-d`` (no-leading-zero day) directive so the same code
    works on Windows hosts during local development.
    """
    local = timezone.localtime(dt) if timezone.is_aware(dt) else dt
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local.strftime('%b')} {local.day}, {local.year}, {hour}:{local.strftime('%M %p')}"


def format_relative(dt: datetime, *, now: datetime | None = None) -> str:
    """e.g. 'just now', '5m ago', '3h ago', '2d ago'.

    Boundaries: < 45s → 'just now', < 1h → minutes, < 24h → hours, otherwise days.
    All boundaries use rounding (`round(...)`) — matches the JS `Math.round` in the
    top-bar poller so server- and client-rendered text agree.
    """
    now = now or timezone.now()
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 45:
        return "just now"
    if seconds < 60 * 60:
        return f"{round(seconds / 60)}m ago"
    if seconds < 60 * 60 * 24:
        return f"{round(seconds / 3600)}h ago"
    return f"{round(seconds / 86400)}d ago"
