from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.banking.models import Account, AccountBalanceSnapshot, Transaction


class Command(BaseCommand):
    help = (
        "Backfill AccountBalanceSnapshot rows by walking transaction history "
        "backwards from each account's current balance."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user", help="Limit to one user (username). Defaults to all users.",
        )
        parser.add_argument(
            "--days", type=int, default=90,
            help="How many days of history to reconstruct. Default: 90.",
        )

    def handle(self, *args, **options):
        username = options.get("user")
        days = options["days"]
        today = timezone.localdate()
        cutoff = today - timedelta(days=days - 1)

        accounts = Account.objects.all()
        if username:
            accounts = accounts.filter(institution__user__username=username)

        total_snapshots = 0

        for account in accounts:
            snapshots_written = self._backfill_account(account, today, cutoff)
            total_snapshots += snapshots_written

        self.stdout.write(self.style.SUCCESS(
            f"Done. Wrote {total_snapshots} balance snapshots across "
            f"{accounts.count()} accounts."
        ))

    def _backfill_account(self, account, today, cutoff):
        """Walk this account's transactions backwards from `today` to `cutoff`,
        computing the end-of-day balance for each date. Idempotent —
        update_or_create replaces existing rows."""
        # Group transactions by their posted date, summing raw amounts.
        # We walk backwards: balance(day-1) = balance(day) - sum(txns on day).
        txns_by_day: dict = defaultdict(lambda: Decimal("0"))
        txns = (
            Transaction.objects
            .filter(account=account, posted_at__gte=cutoff)
            .only("posted_at", "amount")
        )
        for tx in txns:
            tx_day = tx.posted_at.date()
            txns_by_day[tx_day] += tx.amount

        balance = account.balance  # current (end of today)
        written = 0

        with db_transaction.atomic():
            for i in range(0, (today - cutoff).days + 1):
                day = today - timedelta(days=i)
                AccountBalanceSnapshot.objects.update_or_create(
                    account=account,
                    date=day,
                    defaults={"balance": balance},
                )
                written += 1
                # Move to end of (day - 1) by subtracting today's transactions.
                balance -= txns_by_day.get(day, Decimal("0"))

        return written
