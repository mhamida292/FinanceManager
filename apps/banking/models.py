from django.conf import settings
from django.db import models

from .fields import EncryptedTextField
from .managers import UserScopedQuerySet


class InstitutionQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(user=user)


class Institution(models.Model):
    """One SimpleFIN Access URL per row. May back multiple Accounts."""

    PROVIDER_CHOICES = [
        ("simplefin", "SimpleFIN"),
        # ("plaid", "Plaid"),  # future
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="institutions")
    name = models.CharField(max_length=200, help_text="User-friendly label for this connection.")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default="simplefin")
    access_url = EncryptedTextField(help_text="Provider access URL. Encrypted at rest.")
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    objects = InstitutionQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_provider_display()})"


class AccountQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(institution__user=user)


class Account(models.Model):
    """A bank account exposed via a SimpleFIN Institution."""

    TYPE_CHOICES = [
        ("checking", "Checking"),
        ("savings", "Savings"),
        ("credit", "Credit Card"),
        ("loan", "Loan"),
        ("other", "Other"),
    ]

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="accounts")
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="other")
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="USD")
    org_name = models.CharField(max_length=200, blank=True, help_text="Institution name from provider (e.g., 'Chase').")
    external_id = models.CharField(max_length=200, help_text="Provider's account ID; used as the upsert key.")
    last_synced_at = models.DateTimeField(null=True, blank=True)

    objects = AccountQuerySet.as_manager()

    class Meta:
        ordering = ["institution", "name"]
        constraints = [
            models.UniqueConstraint(fields=["institution", "external_id"], name="uniq_account_per_institution"),
        ]

    def __str__(self):
        return f"{self.org_name or self.institution.name} · {self.name}"


class TransactionQuerySet(UserScopedQuerySet):
    def for_user(self, user):
        return self.filter(account__institution__user=user)


class Transaction(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="transactions")
    posted_at = models.DateTimeField(db_index=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    description = models.CharField(max_length=500, blank=True)
    payee = models.CharField(max_length=200, blank=True)
    memo = models.CharField(max_length=500, blank=True)
    pending = models.BooleanField(default=False)
    external_id = models.CharField(max_length=200, help_text="Provider's txn ID; upsert key.")

    objects = TransactionQuerySet.as_manager()

    class Meta:
        ordering = ["-posted_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["account", "external_id"], name="uniq_txn_per_account"),
        ]

    def __str__(self):
        return f"{self.posted_at:%Y-%m-%d} {self.amount} {self.payee or self.description}"
