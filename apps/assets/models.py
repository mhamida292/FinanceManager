from decimal import Decimal

from django.conf import settings
from django.db import models

from .managers import AssetPriceSnapshotQuerySet, AssetQuerySet


class Asset(models.Model):
    """A user-tracked asset. Either scraped from a URL or manually valued."""

    KIND_CHOICES = [
        ("scraped", "Scraped from URL"),
        ("manual", "Manual value"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assets")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    name = models.CharField(max_length=200)
    notes = models.TextField(blank=True, default="")

    # Quantity is meaningful for scraped (multiplied by per-unit scrape), ignored for manual.
    quantity = models.DecimalField(max_digits=16, decimal_places=6, default=Decimal("1"))
    unit = models.CharField(max_length=20, blank=True, default="", help_text="'oz', 'each', etc. Optional.")

    # Scraped-only fields.
    source_url = models.URLField(blank=True, default="")
    css_selector = models.CharField(max_length=500, blank=True, default="",
                                     help_text="Optional. Blank = auto-detect first $-prefixed price on the page.")

    # Current total value. For scraped: last_scraped_unit_price × quantity. For manual: user-entered directly.
    current_value = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0"))
    last_priced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AssetQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_kind_display()})"


class AssetPriceSnapshot(models.Model):
    """Daily (or on-refresh) value record. Enables history charts later; unused in Phase 4 UI."""
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="snapshots")
    at = models.DateTimeField(db_index=True)
    value = models.DecimalField(max_digits=18, decimal_places=2)

    objects = AssetPriceSnapshotQuerySet.as_manager()

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"{self.asset_id} @ {self.at:%Y-%m-%d}: {self.value}"
