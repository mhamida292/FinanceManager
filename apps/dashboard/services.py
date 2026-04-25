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
    """Return a list of length ``days`` with end-of-day net-worth values
    (investments + assets), most-recent last. Days with no data carry forward
    the previous value so the line is continuous; leading days with no data
    return 0.
    """
    cutoff = date.today() - timedelta(days=days - 1)

    inv_by_day = {}
    for snap in PortfolioSnapshot.objects.for_user(user).filter(date__gte=cutoff).order_by("date"):
        inv_by_day[snap.date] = inv_by_day.get(snap.date, Decimal("0")) + snap.total_value

    asset_by_day = {}
    for snap in AssetPriceSnapshot.objects.for_user(user).filter(at__date__gte=cutoff).order_by("at"):
        asset_by_day[snap.at.date()] = snap.value

    result: list[Decimal] = []
    last_inv = Decimal("0")
    last_asset = Decimal("0")
    for i in range(days):
        d = cutoff + timedelta(days=i)
        if d in inv_by_day:
            last_inv = inv_by_day[d]
        if d in asset_by_day:
            last_asset = asset_by_day[d]
        result.append(last_inv + last_asset)

    return result
