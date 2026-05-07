from django.conf import settings
from django.db import models


class SyncRun(models.Model):
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "running"),
        (STATUS_SUCCESS, "success"),
        (STATUS_ERROR, "error"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sync_runs",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    summary = models.TextField(blank=True, default="")
    errors_text = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["user", "-started_at"])]
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"SyncRun(user={self.user_id}, status={self.status}, started_at={self.started_at:%Y-%m-%d %H:%M})"
