from dataclasses import dataclass, field
from decimal import Decimal

from apps.assets.models import Asset
from apps.banking.models import Account, Transaction
from apps.investments.models import Holding


@dataclass
class NetWorthSummary:
    cash: Decimal = Decimal("0")
    investments: Decimal = Decimal("0")
    assets: Decimal = Decimal("0")
    cash_account_count: int = 0
    investment_holding_count: int = 0
    asset_count: int = 0
    recent_transactions: list = field(default_factory=list)

    @property
    def net_worth(self) -> Decimal:
        return self.cash + self.investments + self.assets


def net_worth_summary(user, recent_txn_limit: int = 10) -> NetWorthSummary:
    """Aggregate everything visible to this user into a single dashboard payload."""
    summary = NetWorthSummary()

    # Cash: bank-account balances. Treat credit-card balances (negative balance OR type='credit') as debt.
    for acc in Account.objects.for_user(user):
        if acc.type == "credit":
            summary.cash -= abs(acc.balance)
        else:
            summary.cash += acc.balance
        summary.cash_account_count += 1

    # Investments: sum of holdings' market_value
    for h in Holding.objects.for_user(user):
        summary.investments += h.market_value
        summary.investment_holding_count += 1

    # Assets: sum of current_value
    for a in Asset.objects.for_user(user):
        summary.assets += a.current_value
        summary.asset_count += 1

    summary.recent_transactions = list(
        Transaction.objects.for_user(user)
        .select_related("account", "account__institution")
        .order_by("-posted_at", "-id")[:recent_txn_limit]
    )

    return summary
