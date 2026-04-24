import base64
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

import requests

from .base import AccountData, AccountSyncPayload, FinancialProvider, TransactionData
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
