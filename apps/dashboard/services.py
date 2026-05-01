from dataclasses import dataclass, field
from decimal import Decimal

from apps.assets.models import Asset
from apps.banking.models import Account, Transaction
from apps.investments.models import Holding, InvestmentAccount
from apps.liabilities.services import total_liabilities


@dataclass
class NetWorthSummary:
    cash: Decimal = Decimal("0")
    investments: Decimal = Decimal("0")
    assets: Decimal = Decimal("0")
    liabilities: Decimal = Decimal("0")
    cash_account_count: int = 0
    investment_holding_count: int = 0
    asset_count: int = 0
    recent_transactions: list = field(default_factory=list)

    @property
    def net_worth(self) -> Decimal:
        return self.cash + self.investments + self.assets - self.liabilities


def net_worth_summary(user, recent_txn_limit: int = 10) -> NetWorthSummary:
    summary = NetWorthSummary()

    # Cash: bank accounts EXCLUDING credit/loan (those are liabilities, not negative cash).
    for acc in Account.objects.for_user(user).exclude(type__in=["credit", "loan"]):
        summary.cash += acc.balance
        summary.cash_account_count += 1

    # Investments: holdings market value + uninvested cash on each investment account.
    for h in Holding.objects.for_user(user):
        summary.investments += h.market_value
        summary.investment_holding_count += 1
    for inv in InvestmentAccount.objects.for_user(user):
        summary.investments += inv.cash_balance

    # Assets
    for a in Asset.objects.for_user(user):
        summary.assets += a.current_value
        summary.asset_count += 1

    # Liabilities (combined: bank credit/loan + manual)
    summary.liabilities = total_liabilities(user)

    summary.recent_transactions = list(
        Transaction.objects.for_user(user)
        .select_related("account", "account__institution")
        .order_by("-posted_at", "-id")[:recent_txn_limit]
    )

    return summary


from datetime import date, timedelta

from apps.assets.models import AssetPriceSnapshot
from apps.investments.models import PortfolioSnapshot


def net_worth_history(user, days: int = 30) -> list[Decimal]:
    """Return a list of length ``days`` with end-of-day net-worth values,
    most-recent last.

    net_worth(day) = cash(day) + investments(day) + assets(day) - liabilities(day)

    Each account, investment account, and asset is tracked independently. Each
    one's value on each day is determined by:
      1. The most recent snapshot ON or BEFORE that day, if one exists.
      2. Otherwise (no pre-cutoff snapshot AND no in-window snapshot yet on
         this day), the FIRST in-window snapshot value — applied retroactively.
         This avoids fake jumps when a user newly-connects an account: the
         chart treats the account as if it always had its first-known value.

    Days with no snapshot for any source contribute 0.
    """
    cutoff = date.today() - timedelta(days=days - 1)

    from apps.banking.models import Account, AccountBalanceSnapshot

    # ---------- Cash / liability accounts (existing logic, unchanged) ----------
    accounts = list(
        Account.objects.filter(institution__user=user).only("id", "type")
    )
    account_types = {a.id: a.type for a in accounts}

    seed: dict[int, Decimal] = {}
    for a in accounts:
        last_before = (
            AccountBalanceSnapshot.objects
            .filter(account=a, date__lt=cutoff)
            .order_by("-date").only("balance").first()
        )
        if last_before:
            seed[a.id] = last_before.balance
        else:
            first_in = (
                AccountBalanceSnapshot.objects
                .filter(account=a, date__gte=cutoff)
                .order_by("date").only("balance").first()
            )
            seed[a.id] = first_in.balance if first_in else Decimal("0")

    snapshots_in_window: dict[tuple[int, date], Decimal] = {}
    for snap in (
        AccountBalanceSnapshot.objects
        .filter(account__institution__user=user, date__gte=cutoff)
        .only("account_id", "date", "balance")
        .order_by("date")
    ):
        snapshots_in_window[(snap.account_id, snap.date)] = snap.balance

    # ---------- Investments (per-account treatment) ----------
    inv_accounts = list(
        InvestmentAccount.objects.filter(user=user).only("id")
    )
    inv_seed: dict[int, Decimal] = {}
    for ia in inv_accounts:
        last_before = (
            PortfolioSnapshot.objects
            .filter(investment_account=ia, date__lt=cutoff)
            .order_by("-date").only("total_value").first()
        )
        if last_before:
            inv_seed[ia.id] = last_before.total_value
        else:
            first_in = (
                PortfolioSnapshot.objects
                .filter(investment_account=ia, date__gte=cutoff)
                .order_by("date").only("total_value").first()
            )
            inv_seed[ia.id] = first_in.total_value if first_in else Decimal("0")

    inv_snapshots_in_window: dict[tuple[int, date], Decimal] = {}
    for snap in (
        PortfolioSnapshot.objects.for_user(user)
        .filter(date__gte=cutoff)
        .only("investment_account_id", "date", "total_value")
        .order_by("date")
    ):
        inv_snapshots_in_window[(snap.investment_account_id, snap.date)] = snap.total_value

    # ---------- Assets (per-asset treatment) ----------
    user_assets = list(Asset.objects.filter(user=user).only("id"))
    asset_seed: dict[int, Decimal] = {}
    for asset in user_assets:
        last_before = (
            AssetPriceSnapshot.objects
            .filter(asset=asset, at__date__lt=cutoff)
            .order_by("-at").only("value").first()
        )
        if last_before:
            asset_seed[asset.id] = last_before.value
        else:
            first_in = (
                AssetPriceSnapshot.objects
                .filter(asset=asset, at__date__gte=cutoff)
                .order_by("at").only("value").first()
            )
            asset_seed[asset.id] = first_in.value if first_in else Decimal("0")

    asset_snapshots_in_window: dict[tuple[int, date], Decimal] = {}
    for snap in (
        AssetPriceSnapshot.objects.for_user(user)
        .filter(at__date__gte=cutoff)
        .only("asset_id", "at", "value")
        .order_by("at")
    ):
        # Multiple snapshots per day per asset are possible; latest wins.
        asset_snapshots_in_window[(snap.asset_id, snap.at.date())] = snap.value

    # ---------- Walk the days ----------
    result: list[Decimal] = []
    current_account_balance = dict(seed)
    current_inv_per_acct = dict(inv_seed)
    current_asset_per_id = dict(asset_seed)

    for i in range(days):
        d = cutoff + timedelta(days=i)

        # Update per-source values from any in-window snapshot on this day.
        for a_id in current_account_balance:
            if (a_id, d) in snapshots_in_window:
                current_account_balance[a_id] = snapshots_in_window[(a_id, d)]
        for ia_id in current_inv_per_acct:
            if (ia_id, d) in inv_snapshots_in_window:
                current_inv_per_acct[ia_id] = inv_snapshots_in_window[(ia_id, d)]
        for asset_id in current_asset_per_id:
            if (asset_id, d) in asset_snapshots_in_window:
                current_asset_per_id[asset_id] = asset_snapshots_in_window[(asset_id, d)]

        # Sum cash and liabilities from per-account balances.
        cash_total = Decimal("0")
        liability_total = Decimal("0")
        for a_id, raw_balance in current_account_balance.items():
            atype = account_types.get(a_id)
            if atype in ("credit", "loan"):
                liability_total += abs(raw_balance)
            else:
                cash_total += raw_balance

        inv_total = sum(current_inv_per_acct.values(), Decimal("0"))
        asset_total = sum(current_asset_per_id.values(), Decimal("0"))

        net_worth = cash_total + inv_total + asset_total - liability_total
        result.append(net_worth)

    return result
