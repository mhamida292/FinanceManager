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


@dataclass(frozen=True)
class HoldingData:
    external_id: str
    symbol: str
    description: str
    shares: Decimal
    current_price: Decimal
    market_value: Decimal
    cost_basis: Decimal | None   # None = provider didn't return it


@dataclass(frozen=True)
class InvestmentAccountSyncPayload:
    external_id: str
    name: str
    broker: str                   # SimpleFIN's "org.name" if present
    currency: str
    holdings: tuple[HoldingData, ...]


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

    def fetch_accounts_with_transactions(
        self, access_url: str, *, since: "datetime | None" = None,
    ) -> Iterable[AccountSyncPayload]:
        """Pull every account + its recent transactions in one call.

        `since`, when provided, is a hint to providers that support incremental
        pagination (e.g. Teller's `from_id`) — they may stop fetching transactions
        older than this datetime. Providers that fetch all data in one call
        (e.g. SimpleFIN) accept and ignore the kwarg. None means "fetch everything".
        """
        ...

    def fetch_investment_accounts(self, access_url: str) -> Iterable[InvestmentAccountSyncPayload]:
        """Investment accounts and their current holdings.

        Implementations may share an underlying API call with
        fetch_accounts_with_transactions — callers should not rely on whether
        or not two HTTP calls happen.
        """
        ...
