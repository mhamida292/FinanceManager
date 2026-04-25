"""Seed a user's account with realistic-looking demo data.

    docker compose exec web python manage.py seed_demo --user testuser
    docker compose exec web python manage.py seed_demo --user testuser --clear

`--clear` wipes only seed-tagged rows (external_id starts with "demo-"). Real
SimpleFIN data is left alone so it's safe to run on a mixed account.
"""
import random
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.assets.models import Asset
from apps.banking.models import Account, Institution, Transaction
from apps.investments.models import Holding, InvestmentAccount
from apps.liabilities.models import Liability


PAYEE_POOL = {
    "groceries": [("Trader Joe's", 30, 120), ("Whole Foods", 50, 180), ("Aldi", 25, 90), ("Costco", 80, 300)],
    "dining": [("Chipotle", 12, 25), ("Sweetgreen", 14, 22), ("Local Sushi", 25, 70), ("Five Guys", 14, 35), ("Coffee Shop", 4, 12)],
    "gas": [("Shell", 35, 70), ("BP", 35, 70), ("Costco Gas", 28, 60)],
    "shopping": [("Amazon", 15, 220), ("Target", 25, 180), ("Best Buy", 30, 600), ("REI", 40, 200)],
    "subscription": [("Spotify", 10.99, 10.99), ("Netflix", 15.49, 15.49), ("iCloud", 2.99, 2.99), ("NYT", 4.00, 4.00)],
    "utility": [("ConEd", 80, 140), ("Verizon", 85, 95), ("Internet", 70, 70)],
    "fun": [("AMC Theatres", 18, 50), ("Steam", 20, 60), ("Bookshop", 18, 45)],
}


class Command(BaseCommand):
    help = "Seed a user account with realistic demo data (banks, transactions, investments, assets, liabilities)."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username to seed")
        parser.add_argument("--clear", action="store_true", help="Delete existing seed data (external_id starts with 'demo-') before reseeding")
        parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")

    def handle(self, *args, **opts):
        User = get_user_model()
        try:
            user = User.objects.get(username=opts["user"])
        except User.DoesNotExist:
            raise CommandError(f"No user named {opts['user']!r}")

        random.seed(opts["seed"])

        with transaction.atomic():
            if opts["clear"]:
                self._clear(user)
            self._seed(user)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded demo data for {user.username}. "
            f"Visit / to see it, or run with --clear to wipe and reseed."
        ))

    def _clear(self, user):
        """Remove only demo-tagged rows. Leaves real SimpleFIN data intact."""
        Transaction.objects.filter(account__institution__user=user, external_id__startswith="demo-").delete()
        Account.objects.filter(institution__user=user, external_id__startswith="demo-").delete()
        Institution.objects.filter(user=user, name__startswith="Demo ").delete()
        Holding.objects.filter(investment_account__user=user, external_id__startswith="demo-").delete()
        InvestmentAccount.objects.filter(user=user, name__startswith="Demo ").delete()
        Asset.objects.filter(user=user, name__startswith="Demo ").delete()
        Liability.objects.filter(user=user, name__startswith="Demo ").delete()

    def _seed(self, user):
        now = datetime.now(dt_tz.utc)

        # ---------- Bank ----------
        inst = Institution.objects.create(
            user=user,
            name="Demo Bank Connection",
            display_name="My Bank",
            provider="simplefin",
            access_url="https://demo:demo@example.invalid/seed",
            last_synced_at=now,
        )

        checking = Account.objects.create(
            institution=inst, name="Demo Checking", display_name="Everyday Checking",
            type="checking", balance=Decimal("0"), org_name="Chase",
            external_id="demo-checking", last_synced_at=now,
        )
        savings = Account.objects.create(
            institution=inst, name="Demo Savings", display_name="High-Yield Savings",
            type="savings", balance=Decimal("18250.00"), org_name="Chase",
            external_id="demo-savings", last_synced_at=now,
        )
        credit = Account.objects.create(
            institution=inst, name="Demo Credit Card", display_name="Sapphire Preferred",
            type="credit", balance=Decimal("0"), org_name="Chase",
            external_id="demo-credit", last_synced_at=now,
        )

        # ---------- Transactions: 6 months of activity ----------
        tx_id = 0
        start = now - timedelta(days=180)

        # Bi-weekly payroll → checking
        d = start
        while d <= now:
            self._tx(checking, d, Decimal("2412.50"), payee="Payroll · Acme Corp", desc="Direct Deposit", external_id=f"demo-tx-{tx_id}")
            tx_id += 1
            d += timedelta(days=14)

        # Monthly rent on the 1st → checking
        d = start.replace(day=1) + timedelta(days=32)
        d = d.replace(day=1)
        while d <= now:
            self._tx(checking, d, Decimal("-1850.00"), payee="Apartment Rent", desc="Rent payment", external_id=f"demo-tx-{tx_id}")
            tx_id += 1
            # next month
            year, month = d.year, d.month + 1
            if month > 12: year, month = year + 1, 1
            d = d.replace(year=year, month=month)

        # Recurring monthly utilities + subscriptions across both accounts
        for category, account in [("utility", checking), ("subscription", credit)]:
            for d_month in self._month_starts(start, now):
                for payee, lo, hi in PAYEE_POOL[category]:
                    amt = -Decimal(str(round(random.uniform(lo, hi), 2)))
                    day = d_month + timedelta(days=random.randint(0, 25))
                    if day > now: continue
                    self._tx(account, day, amt, payee=payee, desc=f"{category}", external_id=f"demo-tx-{tx_id}")
                    tx_id += 1

        # Random discretionary spend over the period
        days = (now - start).days
        for _ in range(140):
            d = start + timedelta(days=random.randint(0, days), hours=random.randint(0, 23))
            category = random.choice(["groceries", "dining", "gas", "shopping", "fun"])
            payee, lo, hi = random.choice(PAYEE_POOL[category])
            amt = -Decimal(str(round(random.uniform(lo, hi), 2)))
            account = credit if random.random() < 0.55 else checking
            self._tx(account, d, amt, payee=payee, desc=category, external_id=f"demo-tx-{tx_id}")
            tx_id += 1

        # A couple of transfers to savings
        for d_month in list(self._month_starts(start, now))[::2]:
            d = d_month + timedelta(days=random.randint(8, 20))
            if d > now: continue
            self._tx(checking, d, Decimal("-500.00"), payee="Transfer to Savings", desc="transfer", external_id=f"demo-tx-{tx_id}")
            tx_id += 1
            self._tx(savings, d, Decimal("500.00"), payee="Transfer from Checking", desc="transfer", external_id=f"demo-tx-{tx_id}")
            tx_id += 1

        # Recompute account balances from transactions so dashboards match
        for acct in (checking, credit):
            total = sum((t.amount for t in acct.transactions.all()), Decimal("0"))
            acct.balance = total
            acct.save(update_fields=["balance"])
        # savings balance was set explicitly to 18250 + transferred amount over time
        savings.balance = Decimal("18250.00") + sum((t.amount for t in savings.transactions.all()), Decimal("0"))
        savings.save(update_fields=["balance"])

        # ---------- Investments ----------
        brokerage = InvestmentAccount.objects.create(
            user=user, source="manual", broker="Robinhood", name="Demo Brokerage",
            display_name="Robinhood", cash_balance=Decimal("1250.50"), notes="Demo data",
        )
        holdings = [
            ("AAPL",  "Apple Inc.",         Decimal("12"),    Decimal("228.40"), Decimal("2050.00")),
            ("GOOGL", "Alphabet Inc.",      Decimal("8"),     Decimal("184.20"), Decimal("1320.00")),
            ("MSFT",  "Microsoft Corp.",    Decimal("6"),     Decimal("442.80"), Decimal("2280.00")),
            ("NVDA",  "NVIDIA Corp.",       Decimal("4"),     Decimal("138.65"), Decimal("315.00")),
            ("VTI",   "Vanguard Total Mkt", Decimal("35"),    Decimal("288.40"), Decimal("8560.00")),
            ("BND",   "Vanguard Total Bond", Decimal("20"),    Decimal("72.85"),  Decimal("1500.00")),
        ]
        for sym, desc, sh, price, cost in holdings:
            mv = (sh * price).quantize(Decimal("0.01"))
            Holding.objects.create(
                investment_account=brokerage,
                symbol=sym, description=desc, shares=sh,
                current_price=price, market_value=mv,
                cost_basis=cost, cost_basis_source="manual",
                external_id=f"demo-{sym}",
                last_priced_at=now,
            )

        # ---------- Assets ----------
        Asset.objects.create(
            user=user, kind="scraped", name="Demo Gold (1 oz)",
            quantity=Decimal("1"), unit="oz",
            source_url="https://example.invalid/gold",
            current_value=Decimal("2485.00"), last_priced_at=now,
            notes="Demo asset",
        )
        Asset.objects.create(
            user=user, kind="manual", name="Demo Cash on Hand",
            quantity=Decimal("1"), current_value=Decimal("500.00"),
            notes="Demo asset",
        )

        # ---------- Liabilities ----------
        Liability.objects.create(
            user=user, name="Demo Student Loan", balance=Decimal("24500.00"),
            notes="Demo liability",
        )

    def _tx(self, account, posted_at, amount, *, payee, desc, external_id):
        Transaction.objects.create(
            account=account, posted_at=posted_at, amount=amount,
            description=desc, payee=payee, memo="",
            pending=False, external_id=external_id,
        )

    def _month_starts(self, start, end):
        d = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while d <= end:
            yield d
            year, month = d.year, d.month + 1
            if month > 12: year, month = year + 1, 1
            d = d.replace(year=year, month=month)
