"""Run every refresh path: SimpleFIN bank sync, SimpleFIN investment sync,
yfinance price refresh on manual investments, scraped asset refresh.

Runs across ALL users in one shot. Designed for nightly host-crontab invocation:
    0 3 * * * cd /opt/finance && docker compose exec -T web python manage.py sync_all
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.assets.services import refresh_scraped_assets
from apps.banking.models import Institution
from apps.banking.services import sync_institution
from apps.investments.services import refresh_manual_prices, sync_simplefin_investments

User = get_user_model()


class Command(BaseCommand):
    help = "Refresh all bank data, investment data, manual investment prices, and scraped asset prices."

    def handle(self, *args, **options):
        # 1. SimpleFIN: banking
        for inst in Institution.objects.all():
            try:
                result = sync_institution(inst)
                self.stdout.write(f"[bank] {inst}: {result.transactions_created} new txns, {result.accounts_updated} accounts updated")
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"[bank] {inst} FAILED: {exc}"))

        # 2. SimpleFIN: investments
        for inst in Institution.objects.all():
            try:
                result = sync_simplefin_investments(inst)
                self.stdout.write(f"[invest] {inst}: {result.holdings_updated} holdings updated, {result.holdings_manual_basis_preserved} manual basis preserved")
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"[invest] {inst} FAILED: {exc}"))

        # 3. yfinance: manual investment prices, per user
        for user in User.objects.all():
            try:
                n = refresh_manual_prices(user=user)
                if n:
                    self.stdout.write(f"[prices] {user.username}: refreshed {n} manual holding(s)")
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"[prices] {user.username} FAILED: {exc}"))

        # 4. Scraped assets, per user
        for user in User.objects.all():
            try:
                result = refresh_scraped_assets(user=user)
                if result.updated or result.failed:
                    self.stdout.write(f"[assets] {user.username}: refreshed {result.updated}, failed {len(result.failed)}")
                    for asset_id, err in result.failed:
                        self.stderr.write(self.style.WARNING(f"  asset {asset_id}: {err}"))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"[assets] {user.username} FAILED: {exc}"))

        self.stdout.write(self.style.SUCCESS("[sync_all] done"))
