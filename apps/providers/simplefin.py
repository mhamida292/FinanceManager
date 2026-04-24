import base64
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

import requests

from .base import (
    AccountData, AccountSyncPayload, FinancialProvider, HoldingData,
    InvestmentAccountSyncPayload, TransactionData,
)
from .registry import register

_SIMPLEFIN_TYPE_HINTS = {
    # SimpleFIN doesn't have a standard account-type field, so we guess from the account name.
    "checking": ("checking", "chk"),
    "savings": ("savings", "sav"),
    "credit": ("credit", "card", "visa", "mastercard", "amex"),
    "loan": ("loan", "mortgage", "auto"),
}


def _guess_type(name: str) -> str:
    lower = name.lower()
    for typ, hints in _SIMPLEFIN_TYPE_HINTS.items():
        if any(h in lower for h in hints):
            return typ
    return "other"


@register
class SimpleFINProvider:
    name = "simplefin"

    def __init__(self, http: requests.Session | None = None, timeout: float = 30.0) -> None:
        self._http = http or requests.Session()
        self._timeout = timeout

    def exchange_setup_token(self, setup_token: str) -> str:
        """POST to the decoded setup-token URL; response body is the access URL."""
        try:
            decoded = base64.b64decode(setup_token.strip(), validate=True).decode().strip()
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Setup token is not valid base64.") from exc
        if not decoded.startswith("https://"):
            raise ValueError("Decoded setup token is not an HTTPS URL.")
        response = self._http.post(decoded, timeout=self._timeout)
        response.raise_for_status()
        access_url = response.text.strip()
        if not access_url.startswith("https://"):
            raise ValueError(f"Unexpected setup-exchange response: {access_url[:80]!r}")
        return access_url

    def fetch_accounts_with_transactions(self, access_url: str) -> Iterable[AccountSyncPayload]:
        url = f"{access_url.rstrip('/')}/accounts?start-date=0"
        response = self._http.get(url, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()

        errors = payload.get("errors") or []
        if errors:
            # Errors are usually per-institution and don't fail the whole call — surface them but keep going.
            # For Phase 2 we just log via exception message if there's nothing usable.
            if not payload.get("accounts"):
                raise RuntimeError(f"SimpleFIN returned errors and no accounts: {errors}")

        for raw_account in payload.get("accounts", []):
            if raw_account.get("holdings"):
                continue  # investment account — handled by fetch_investment_accounts
            yield self._parse_account(raw_account)

    def _parse_account(self, raw: dict) -> AccountSyncPayload:
        org = raw.get("org", {}) or {}
        account = AccountData(
            external_id=str(raw["id"]),
            name=str(raw.get("name", "Unnamed Account")),
            type=_guess_type(str(raw.get("name", ""))),
            balance=Decimal(str(raw.get("balance", "0"))),
            currency=str(raw.get("currency", "USD")),
            org_name=str(org.get("name", "")),
        )
        transactions = tuple(self._parse_transaction(t) for t in raw.get("transactions", []))
        return AccountSyncPayload(account=account, transactions=transactions)

    def _parse_transaction(self, raw: dict) -> TransactionData:
        posted = datetime.fromtimestamp(int(raw["posted"]), tz=timezone.utc)
        return TransactionData(
            external_id=str(raw["id"]),
            posted_at=posted,
            amount=Decimal(str(raw.get("amount", "0"))),
            description=str(raw.get("description", "")),
            payee=str(raw.get("payee", "")),
            memo=str(raw.get("memo", "")),
            pending=bool(raw.get("pending", False)),
        )

    def fetch_investment_accounts(self, access_url: str) -> Iterable[InvestmentAccountSyncPayload]:
        url = f"{access_url.rstrip('/')}/accounts?start-date=0"
        response = self._http.get(url, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()

        for raw_account in payload.get("accounts", []):
            holdings = raw_account.get("holdings") or []
            if not holdings:
                continue  # bank account, skip
            yield self._parse_investment_account(raw_account)

    def _parse_investment_account(self, raw: dict) -> InvestmentAccountSyncPayload:
        org = raw.get("org", {}) or {}
        holdings = tuple(self._parse_holding(h) for h in raw.get("holdings", []))
        return InvestmentAccountSyncPayload(
            external_id=str(raw["id"]),
            name=str(raw.get("name", "Unnamed Account")),
            broker=str(org.get("name", "")),
            currency=str(raw.get("currency", "USD")),
            holdings=holdings,
        )

    def _parse_holding(self, raw: dict) -> HoldingData:
        shares = Decimal(str(raw.get("shares", "0")))

        price_raw = raw.get("price")
        price = Decimal(str(price_raw)) if price_raw not in (None, "") else Decimal("0")

        market_value_raw = raw.get("market_value")
        if market_value_raw not in (None, ""):
            market_value = Decimal(str(market_value_raw)).quantize(Decimal("0.01"))
        else:
            market_value = (shares * price).quantize(Decimal("0.01"))

        # Back-compute price from market_value / shares when the provider omits `price`
        # (some brokerages, notably Robinhood via SimpleFIN, don't include it).
        if price == 0 and shares > 0 and market_value > 0:
            price = (market_value / shares).quantize(Decimal("0.0001"))

        # Cost basis: treat explicit 0 as "unknown" (e.g., Robinhood doesn't license the
        # real value to aggregators and returns "0.00"). Fall back to purchase_price × shares
        # when the provider gives us a per-share cost but not a total.
        cost_basis_raw = raw.get("cost_basis")
        if cost_basis_raw in (None, ""):
            cost_basis = None
        else:
            cost_basis = Decimal(str(cost_basis_raw))
            if cost_basis == 0:
                cost_basis = None

        if cost_basis is None:
            purchase_price_raw = raw.get("purchase_price")
            if purchase_price_raw not in (None, ""):
                purchase_price = Decimal(str(purchase_price_raw))
                if purchase_price != 0 and shares > 0:
                    cost_basis = (purchase_price * shares).quantize(Decimal("0.01"))

        return HoldingData(
            external_id=str(raw["id"]),
            symbol=str(raw.get("symbol", "")).upper(),
            description=str(raw.get("description", "")),
            shares=shares,
            current_price=price,
            market_value=market_value,
            cost_basis=cost_basis,
        )
