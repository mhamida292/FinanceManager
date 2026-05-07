"""Sync orchestration for the top-bar ⟳ button.

The view calls `start_sync(user)` which creates a SyncRun row and dispatches
the actual refresh work to a background thread. The thread invokes the
existing per-domain refresh services (manual prices, scraped assets) and
writes the final status back to the SyncRun row.

Tests pass `runner=` to skip the thread and run synchronously.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Callable

from django.contrib.auth import get_user_model
from django.db import connections
from django.utils import timezone

from apps.assets.services import refresh_scraped_assets
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
    threading.Thread(target=_run_sync, args=(user_id, run_id), daemon=True).start()


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
        connections.close_all()


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
