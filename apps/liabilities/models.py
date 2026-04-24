from decimal import Decimal

from django.conf import settings
from django.db import models

from .managers import LiabilityQuerySet


class Liability(models.Model):
    """A user-tracked debt that doesn't come through SimpleFIN —
    student loans, mortgage balance, IOUs, anything you maintain by hand.

    Bank-sourced credit cards / loans stay as banking Account rows; the
    liabilities VIEW unions the two.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="liabilities")
    name = models.CharField(max_length=200)
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0"),
                                   help_text="Current amount owed.")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)

    objects = LiabilityQuerySet.as_manager()

    class Meta:
        ordering = ["-balance"]

    def __str__(self):
        return f"{self.name}: ${self.balance}"
