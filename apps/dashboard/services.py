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
