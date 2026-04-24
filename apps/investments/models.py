from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.banking.models import Institution

from .managers import HoldingQuerySet, InvestmentAccountQuerySet, PortfolioSnapshotQuerySet


class InvestmentAccount(models.Model):
    """A brokerage account. May be SimpleFIN-sourced or user-entered."""

    SOURCE_CHOICES = [
        ("simplefin", "SimpleFIN"),
        ("manual", "Manual entry"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="investment_accounts")
    # Only set when source='simplefin'. Manual accounts have no institution parent.
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="investment_accounts",
        null=True, blank=True,
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    broker = models.CharField(max_length=200, blank=True, help_text="e.g., Fidelity, Robinhood. Free text.")
    name = models.CharField(max_length=200, help_text="Provider name for SimpleFIN accounts; user-entered for manual.")
    display_name = models.CharField(max_length=200, blank=True, default="", help_text="UI override; never overwritten by sync.")
    external_id = models.CharField(max_length=200, blank=True, default="", help_text="Provider's account ID (SimpleFIN only).")
    currency = models.CharField(max_length=8, default="USD")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    objects = InvestmentAccountQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Uniqueness only applies when external_id is non-blank (SimpleFIN accounts).
            models.UniqueConstraint(
                fields=["institution", "external_id"],
                name="uniq_inv_account_per_institution",
                condition=~models.Q(external_id=""),
            ),
        ]

    @property
    def effective_name(self) -> str:
        return self.display_name or self.name

    def __str__(self):
        return f"{self.broker or self.effective_name} ({self.get_source_display()})"


class Holding(models.Model):
    """One position (ticker + share count) inside an InvestmentAccount."""

    COST_BASIS_SOURCE_CHOICES = [
        ("auto", "Auto (from provider)"),
        ("manual", "Manual (user-entered)"),
    ]

    investment_account = models.ForeignKey(InvestmentAccount, on_delete=models.CASCADE, related_name="holdings")
    symbol = models.CharField(max_length=20)
    description = models.CharField(max_length=200, blank=True, default="", help_text="Human-readable name, e.g. 'Apple Inc.'")
    shares = models.DecimalField(max_digits=16, decimal_places=6)
    current_price = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    market_value = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0"))
    cost_basis = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cost_basis_source = models.CharField(max_length=10, choices=COST_BASIS_SOURCE_CHOICES, default="auto")
    external_id = models.CharField(max_length=200, blank=True, default="", help_text="Provider's holding ID (SimpleFIN); blank for manual.")
    last_priced_at = models.DateTimeField(null=True, blank=True)

    objects = HoldingQuerySet.as_manager()

    class Meta:
        ordering = ["investment_account", "symbol"]
        constraints = [
            # For SimpleFIN holdings: external_id unique per account.
            models.UniqueConstraint(
                fields=["investment_account", "external_id"],
                name="uniq_holding_per_account_by_external_id",
                condition=~models.Q(external_id=""),
            ),
            # For manual holdings: one row per symbol per account (no lot tracking).
            models.UniqueConstraint(
                fields=["investment_account", "symbol"],
                name="uniq_manual_holding_per_symbol",
                condition=models.Q(external_id=""),
            ),
        ]

    @property
    def gain_loss(self) -> Decimal | None:
        if self.cost_basis is None:
            return None
        return self.market_value - self.cost_basis

    @property
    def gain_loss_percent(self) -> Decimal | None:
        if self.cost_basis is None or self.cost_basis == 0:
            return None
        return ((self.market_value - self.cost_basis) / self.cost_basis) * Decimal("100")

    def recompute_market_value(self) -> None:
        self.market_value = (self.shares * self.current_price).quantize(Decimal("0.01"))

    def __str__(self):
        return f"{self.symbol} × {self.shares}"


class PortfolioSnapshot(models.Model):
    investment_account = models.ForeignKey(InvestmentAccount, on_delete=models.CASCADE, related_name="snapshots")
    date = models.DateField(db_index=True)
    total_value = models.DecimalField(max_digits=18, decimal_places=2)

    objects = PortfolioSnapshotQuerySet.as_manager()

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["investment_account", "date"], name="uniq_snapshot_per_account_per_day"),
        ]

    def __str__(self):
        return f"{self.investment_account_id} on {self.date}: {self.total_value}"
