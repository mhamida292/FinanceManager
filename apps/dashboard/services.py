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

    Where:
    - cash(day) sums display_balance over checking/savings/other accounts on `day`
    - liabilities(day) sums abs(display_balance) over credit/loan accounts on `day`
      (so that subtracting liabilities pulls them out of net worth)
    - investments(day) and assets(day) come from PortfolioSnapshot / AssetPriceSnapshot

    Days with no snapshot for a given account carry the previous value forward;
    leading days with no data contribute zero.
    """
    cutoff = date.today() - timedelta(days=days - 1)

    # Per-account snapshot timeline for cash/liability accounts.
    # We need the most recent snapshot ON OR BEFORE `cutoff` to seed the
    # carry-forward correctly, otherwise leading days under-count balances.
    from apps.banking.models import Account, AccountBalanceSnapshot

    accounts = list(
        Account.objects.filter(institution__user=user).only("id", "type")
    )
    account_types = {a.id: a.type for a in accounts}

    # Latest snapshot before cutoff per account (the seed).
    seed: dict[int, Decimal] = {}
    for a in accounts:
        last_before = (
            AccountBalanceSnapshot.objects
            .filter(account=a, date__lt=cutoff)
            .order_by("-date")
            .only("balance")
            .first()
        )
        seed[a.id] = last_before.balance if last_before else Decimal("0")

    # Snapshots within the window, grouped by date and account.
    snapshots_in_window: dict[tuple[int, date], Decimal] = {}
    for snap in (
        AccountBalanceSnapshot.objects
        .filter(account__institution__user=user, date__gte=cutoff)
        .only("account_id", "date", "balance")
        .order_by("date")
    ):
        snapshots_in_window[(snap.account_id, snap.date)] = snap.balance

    inv_by_day = {}
    for snap in PortfolioSnapshot.objects.for_user(user).filter(date__gte=cutoff).order_by("date"):
        inv_by_day[snap.date] = inv_by_day.get(snap.date, Decimal("0")) + snap.total_value

    asset_by_day = {}
    for snap in AssetPriceSnapshot.objects.for_user(user).filter(at__date__gte=cutoff).order_by("at"):
        asset_by_day[snap.at.date()] = snap.value

    result: list[Decimal] = []
    last_inv = Decimal("0")
    last_asset = Decimal("0")
    current_account_balance = dict(seed)

    for i in range(days):
        d = cutoff + timedelta(days=i)
        # Update per-account balances with any snapshot from this day.
        for a_id in current_account_balance:
            if (a_id, d) in snapshots_in_window:
                current_account_balance[a_id] = snapshots_in_window[(a_id, d)]
        if d in inv_by_day:
            last_inv = inv_by_day[d]
        if d in asset_by_day:
            last_asset = asset_by_day[d]

        # Sum cash and liabilities from per-account balances.
        cash_total = Decimal("0")
        liability_total = Decimal("0")
        for a_id, raw_balance in current_account_balance.items():
            atype = account_types.get(a_id)
            if atype in ("credit", "loan"):
                liability_total += abs(raw_balance)
            else:
                cash_total += raw_balance

        net_worth = cash_total + last_inv + last_asset - liability_total
        result.append(net_worth)

    return result
