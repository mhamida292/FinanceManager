from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice", password="correct-horse-battery-staple")


@pytest.mark.django_db
def test_syncrun_defaults_and_persistence(alice):
    from apps.accounts.models import SyncRun

    run = SyncRun.objects.create(user=alice)
    assert run.status == SyncRun.STATUS_RUNNING
    assert run.started_at is not None
    assert run.finished_at is None
    assert run.summary == ""
    assert run.errors_text == ""

    # Latest-first ordering and per-user index.
    older = SyncRun.objects.create(user=alice)
    older.started_at = timezone.now() - timedelta(hours=1)
    older.save(update_fields=["started_at"])
    latest = SyncRun.objects.filter(user=alice).first()
    assert latest.pk == run.pk


@pytest.mark.django_db
def test_run_sync_marks_success_with_summary(alice, monkeypatch):
    """Worker invokes the two refresh services and writes a summary."""
    from apps.accounts import services as accounts_services
    from apps.accounts.models import SyncRun

    captured = {}

    def fake_refresh_manual_prices(*, user):
        captured["user_for_manual"] = user
        return 3

    class _Result:
        updated = 5
        failed = []

    def fake_refresh_scraped(*, user):
        captured["user_for_scraped"] = user
        return _Result()

    monkeypatch.setattr(accounts_services, "refresh_manual_prices", fake_refresh_manual_prices)
    monkeypatch.setattr(accounts_services, "refresh_scraped_assets", fake_refresh_scraped)

    run = SyncRun.objects.create(user=alice)
    accounts_services._run_sync(alice.id, run.id)

    run.refresh_from_db()
    assert run.status == SyncRun.STATUS_SUCCESS
    assert run.finished_at is not None
    assert "3 manual" in run.summary
    assert "5 asset" in run.summary
    assert run.errors_text == ""
    assert captured["user_for_manual"] == alice
    assert captured["user_for_scraped"] == alice


@pytest.mark.django_db
def test_run_sync_records_per_asset_failures_in_errors_text(alice, monkeypatch):
    from apps.accounts import services as accounts_services
    from apps.accounts.models import SyncRun

    class _Result:
        updated = 1
        failed = [(42, "boom"), (43, "no source_url")]

    monkeypatch.setattr(accounts_services, "refresh_manual_prices", lambda *, user: 0)
    monkeypatch.setattr(accounts_services, "refresh_scraped_assets", lambda *, user: _Result())

    run = SyncRun.objects.create(user=alice)
    accounts_services._run_sync(alice.id, run.id)

    run.refresh_from_db()
    assert run.status == SyncRun.STATUS_SUCCESS  # partial-failure is still "success" overall
    assert "asset 42: boom" in run.errors_text
    assert "asset 43: no source_url" in run.errors_text


@pytest.mark.django_db
def test_run_sync_marks_error_when_service_raises(alice, monkeypatch):
    from apps.accounts import services as accounts_services
    from apps.accounts.models import SyncRun

    def boom(*, user):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(accounts_services, "refresh_manual_prices", boom)
    # Never reached (manual_prices raises first); patched only for isolation in case of refactor.
    monkeypatch.setattr(accounts_services, "refresh_scraped_assets", lambda *, user: None)

    run = SyncRun.objects.create(user=alice)
    accounts_services._run_sync(alice.id, run.id)

    run.refresh_from_db()
    assert run.status == SyncRun.STATUS_ERROR
    assert "kaboom" in run.errors_text
    assert run.finished_at is not None


@pytest.mark.django_db
def test_start_sync_returns_running_run_and_uses_injected_runner(alice):
    """start_sync supports a runner= kwarg so tests can run synchronously."""
    from apps.accounts.services import start_sync
    from apps.accounts.models import SyncRun

    calls = []

    def sync_runner(user_id, run_id):
        calls.append((user_id, run_id))
        SyncRun.objects.filter(pk=run_id).update(status=SyncRun.STATUS_SUCCESS)

    run = start_sync(alice, runner=sync_runner)

    assert isinstance(run, SyncRun)
    assert calls == [(alice.id, run.id)]
    run.refresh_from_db()
    assert run.status == SyncRun.STATUS_SUCCESS


from django.test import Client
from django.urls import reverse


@pytest.fixture
def alice_client(alice):
    c = Client()
    c.force_login(alice)
    return c


def test_sync_all_creates_running_run_and_redirects(alice, alice_client, monkeypatch):
    """POST /sync-all/ creates a SyncRun(status=running) and redirects.

    The default runner would spawn a thread; we replace it with a no-op so the test
    doesn't kick off real network calls.
    """
    from apps.accounts import views as accounts_views
    from apps.accounts.models import SyncRun

    monkeypatch.setattr(
        accounts_views, "_default_runner", lambda user_id, run_id: None
    )

    response = alice_client.post(reverse("sync_all"), {"next": "/"})

    assert response.status_code == 302
    assert response["Location"] == "/"
    runs = list(SyncRun.objects.filter(user=alice))
    assert len(runs) == 1
    assert runs[0].status == SyncRun.STATUS_RUNNING


def test_sync_all_does_not_create_second_run_when_one_is_already_running(alice, alice_client, monkeypatch):
    from apps.accounts import views as accounts_views
    from apps.accounts.models import SyncRun

    monkeypatch.setattr(
        accounts_views, "_default_runner", lambda user_id, run_id: None
    )

    SyncRun.objects.create(user=alice, status=SyncRun.STATUS_RUNNING)

    response = alice_client.post(reverse("sync_all"), {"next": "/"})

    assert response.status_code == 302
    assert SyncRun.objects.filter(user=alice).count() == 1


def test_sync_all_rejects_anonymous(client):
    response = client.post(reverse("sync_all"))
    assert response.status_code in (302, 403)  # LoginRequiredMiddleware redirects to login
