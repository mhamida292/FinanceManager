from django.core.management.base import BaseCommand

from apps.banking.categories import is_likely_transfer
from apps.banking.models import Transaction


class Command(BaseCommand):
    help = "Auto-detect transfers in existing uncategorized transactions using payee/description patterns."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user", help="Limit to one user (username). Defaults to all users.",
        )

    def handle(self, *args, **options):
        username = options.get("user")
        qs = Transaction.objects.filter(
            category="uncategorized", category_manual=False,
        )
        if username:
            qs = qs.filter(account__institution__user__username=username)

        scanned = 0
        updated = 0
        for tx in qs.iterator(chunk_size=500):
            scanned += 1
            if is_likely_transfer(tx.payee, tx.description):
                tx.category = "transfer"
                tx.save(update_fields=["category"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Scanned {scanned} uncategorized transactions, marked {updated} as transfer."
        ))
