from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.banking.models import Transaction


class Command(BaseCommand):
    help = (
        "Find pairs of opposite-sign equal-amount transactions within N days "
        "across different accounts of the same user, and mark both as 'transfer'."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user", help="Limit to one user (username). Defaults to all users.",
        )
        parser.add_argument(
            "--window-days", type=int, default=2,
            help="Max date difference (days) to consider two rows a pair. Default: 2.",
        )

    def handle(self, *args, **options):
        username = options.get("user")
        window = timedelta(days=options["window_days"])

        User = get_user_model()
        users = User.objects.all()
        if username:
            users = users.filter(username=username)

        scanned_total = paired_total = 0

        for user in users:
            scanned, paired = self._process_user(user, window)
            scanned_total += scanned
            paired_total += paired
            self.stdout.write(
                f"  {user.username}: scanned {scanned}, paired {paired}"
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done. Scanned {scanned_total} candidates across all users, "
            f"paired {paired_total} (marked {paired_total * 2} transactions as transfer)."
        ))

    def _process_user(self, user, window):
        # Eligible rows: not already 'transfer', not manually overridden.
        rows = list(
            Transaction.objects
            .filter(account__institution__user=user)
            .exclude(category="transfer")
            .filter(category_manual=False)
            .select_related("account")
            .order_by("posted_at")
        )

        # Group by abs(display_amount).
        by_abs: dict[Decimal, list] = defaultdict(list)
        for tx in rows:
            amt = tx.display_amount
            if amt == 0:
                continue
            by_abs[abs(amt)].append(tx)

        marked_ids = set()
        paired = 0

        for amount_key, group in by_abs.items():
            if len(group) < 2:
                continue
            # Greedy: walk in order, pair each unmarked positive with nearest unmarked negative
            # of opposite sign, different account, within window.
            positives = [t for t in group if t.display_amount > 0 and t.id not in marked_ids]
            negatives = [t for t in group if t.display_amount < 0 and t.id not in marked_ids]
            for pos in positives:
                if pos.id in marked_ids:
                    continue
                # find best negative match
                best = None
                best_delta = None
                for neg in negatives:
                    if neg.id in marked_ids:
                        continue
                    if neg.account_id == pos.account_id:
                        continue  # must be different accounts
                    delta = abs(pos.posted_at - neg.posted_at)
                    if delta > window:
                        continue
                    if best is None or delta < best_delta:
                        best = neg
                        best_delta = delta
                if best is not None:
                    pos.category = "transfer"
                    pos.save(update_fields=["category"])
                    best.category = "transfer"
                    best.save(update_fields=["category"])
                    marked_ids.add(pos.id)
                    marked_ids.add(best.id)
                    paired += 1

        return len(rows), paired
