from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction

from apps.banking.categories import map_teller_category
from apps.banking.models import Institution, Transaction
from apps.providers.registry import get as get_provider


class Command(BaseCommand):
    help = "Backfill category on existing Teller-sourced transactions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user", help="Limit to one user (username). Defaults to all users.",
        )

    def handle(self, *args, **options):
        username = options.get("user")
        institutions = Institution.objects.filter(provider="teller")
        if username:
            institutions = institutions.filter(user__username=username)

        teller = get_provider("teller")
        updated_total = skipped_total = 0

        for inst in institutions:
            self.stdout.write(f"Processing institution: {inst.effective_name} ({inst.user.username})")
            account_external_ids = {
                a.external_id: a.id for a in inst.accounts.all()
            }
            tx_index: dict[tuple[int, str], Transaction] = {}
            for tx in Transaction.objects.filter(
                account__institution=inst,
            ).only("id", "account_id", "external_id", "category_manual", "category"):
                tx_index[(tx.account_id, tx.external_id)] = tx

            updated = skipped = 0

            with db_transaction.atomic():
                for payload in teller.fetch_accounts_with_transactions(inst.access_url, since=None):
                    acc_id = account_external_ids.get(payload.account.external_id)
                    if acc_id is None:
                        continue
                    for tx_data in payload.transactions:
                        existing = tx_index.get((acc_id, tx_data.external_id))
                        if existing is None:
                            continue
                        if existing.category_manual:
                            skipped += 1
                            continue
                        new_category = map_teller_category(tx_data.provider_category)
                        if existing.category != new_category:
                            existing.category = new_category
                            existing.save(update_fields=["category"])
                        updated += 1

            self.stdout.write(f"  Updated: {updated}, skipped (manual): {skipped}")
            updated_total += updated
            skipped_total += skipped

        self.stdout.write(self.style.SUCCESS(
            f"Done. {updated_total} updated, {skipped_total} skipped across all Teller institutions.",
        ))
