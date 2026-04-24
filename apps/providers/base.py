from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Protocol


@dataclass(frozen=True)
class AccountData:
    external_id: str
    name: str
    type: str            # "checking" | "savings" | "credit" | "loan" | "other"
    balance: Decimal
    currency: str
    org_name: str


@dataclass(frozen=True)
class TransactionData:
    external_id: str
    posted_at: datetime
    amount: Decimal
    description: str
    payee: str
    memo: str
    pending: bool


@dataclass(frozen=True)
class AccountSyncPayload:
    """What a provider returns from a sync call: each account with its own recent transactions."""
    account: AccountData
    transactions: tuple[TransactionData, ...]


class FinancialProvider(Protocol):
    """Contract every aggregator implementation must satisfy.

    Keep provider code pure: no Django model imports, no DB writes. The
    service layer in apps/banking/services.py takes provider output and
    upserts it into the domain models.
    """

    name: str  # "simplefin", "plaid", ...

    def exchange_setup_token(self, setup_token: str) -> str:
        """Convert a one-time setup token into a long-lived access URL."""
        ...

    def fetch_accounts_with_transactions(self, access_url: str) -> Iterable[AccountSyncPayload]:
        """Pull every account + its recent transactions in one call."""
        ...
