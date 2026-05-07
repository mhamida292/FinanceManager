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
