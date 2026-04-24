from dataclasses import dataclass
from decimal import Decimal

from apps.banking.models import Account

from .models import Liability


@dataclass
class LiabilityRow:
    """Display-layer representation of a liability from any source."""
    name: str
    balance: Decimal
    source: str           # "bank" | "manual"
    edit_url: str | None  # set for manual; None for bank-sourced
    bank_account_id: int | None = None
    liability_id: int | None = None


def liabilities_for(user) -> list[LiabilityRow]:
    """Combined list: bank credit/loan accounts + manual Liability rows.
    Sorted by descending balance."""
    rows: list[LiabilityRow] = []

    for acc in Account.objects.for_user(user).filter(type__in=["credit", "loan"]):
        # For credit cards SimpleFIN reports balance as a positive number = what's owed.
        rows.append(LiabilityRow(
            name=acc.effective_name,
            balance=abs(acc.balance),
            source="bank",
            edit_url=None,
            bank_account_id=acc.id,
        ))

    for lia in Liability.objects.for_user(user):
        rows.append(LiabilityRow(
            name=lia.name,
            balance=lia.balance,
            source="manual",
            edit_url=None,
            liability_id=lia.id,
        ))

    rows.sort(key=lambda r: r.balance, reverse=True)
    return rows


def total_liabilities(user) -> Decimal:
    return sum((r.balance for r in liabilities_for(user)), Decimal("0"))
