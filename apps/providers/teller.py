import base64
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Iterable

import requests
from django.conf import settings

from .base import (
    AccountData, AccountSyncPayload, FinancialProvider, HoldingData,
    InvestmentAccountSyncPayload, TransactionData,
)
from .registry import register

# Teller's `subtype` field maps directly to our Account.type values.
_TELLER_SUBTYPE_MAP = {
    "checking": "checking",
    "savings": "savings",
    "credit_card": "credit",
    "mortgage": "loan",
    "auto_loan": "loan",
    "student_loan": "loan",
    "personal_loan": "loan",
}


def _map_subtype(subtype: str) -> str:
    return _TELLER_SUBTYPE_MAP.get(subtype, "other")


@register
class TellerProvider:
    name = "teller"

    def __init__(self, http: requests.Session | None = None, timeout: float = 30.0) -> None:
        self._http = http or requests.Session()
        if settings.TELLER_CERT_PATH and settings.TELLER_KEY_PATH:
            self._http.cert = (settings.TELLER_CERT_PATH, settings.TELLER_KEY_PATH)
        self._timeout = timeout
        self._base = "https://api.teller.io"

    def _auth_header(self, access_token: str) -> dict[str, str]:
        encoded = base64.b64encode(f"{access_token}:".encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def exchange_setup_token(self, setup_token: str) -> str:
        """For Teller, the 'setup token' is already the long-lived access token
        (Connect hands it back via `onSuccess`). We validate it by calling
        GET /accounts. Returns the token unchanged on success."""
        response = self._http.get(
            f"{self._base}/accounts",
            headers=self._auth_header(setup_token),
            timeout=self._timeout,
        )
        if response.status_code == 401:
            raise ValueError("Teller rejected the access token.")
        if not response.ok:
            body = (response.text or "")[:500]
            raise ValueError(
                f"Teller /accounts returned {response.status_code}: {body}"
            )
        return setup_token

    def fetch_accounts_with_transactions(
        self, access_url: str, *, since: "datetime | None" = None,
    ) -> Iterable[AccountSyncPayload]:
        access_token = access_url   # For Teller, the "URL" stored is the access token.
        headers = self._auth_header(access_token)

        accounts_resp = self._http.get(
            f"{self._base}/accounts", headers=headers, timeout=self._timeout,
        )
        accounts_resp.raise_for_status()

        for raw_account in accounts_resp.json():
            yield self._fetch_one_account(raw_account, headers, since)

    def _fetch_one_account(
        self, raw_account: dict, headers: dict[str, str], since: "datetime | None",
    ) -> AccountSyncPayload:
        account_id = raw_account["id"]

        bal_resp = self._http.get(
            f"{self._base}/accounts/{account_id}/balances",
            headers=headers, timeout=self._timeout,
        )
        bal_resp.raise_for_status()
        balance = Decimal(str(bal_resp.json().get("ledger", "0")))

        institution = raw_account.get("institution") or {}
        account = AccountData(
            external_id=str(account_id),
            name=str(raw_account.get("name", "Unnamed Account")),
            type=_map_subtype(str(raw_account.get("subtype", ""))),
            balance=balance,
            currency=str(raw_account.get("currency", "USD")),
            org_name=str(institution.get("name", "")),
        )

        transactions = tuple(self._fetch_transactions(account_id, headers, since))
        return AccountSyncPayload(account=account, transactions=transactions)

    def _fetch_transactions(
        self, account_id: str, headers: dict[str, str], since: "datetime | None",
    ) -> Iterable[TransactionData]:
        """Paginate via from_id. Stops when:
           - the API returns an empty page, OR
           - `since` is provided and the oldest transaction on the current page
             is older than `since`."""
        url = f"{self._base}/accounts/{account_id}/transactions"
        params: dict[str, str] = {}

        while True:
            resp = self._http.get(url, headers=headers, params=params, timeout=self._timeout)
            resp.raise_for_status()
            page = resp.json()
            if not page:
                return

            oldest_on_page: datetime | None = None
            for raw in page:
                tx = self._parse_transaction(raw)
                yield tx
                if oldest_on_page is None or tx.posted_at < oldest_on_page:
                    oldest_on_page = tx.posted_at

            if since is not None and oldest_on_page is not None and oldest_on_page < since:
                return

            params = {"from_id": str(page[-1]["id"])}

    def _parse_transaction(self, raw: dict) -> TransactionData:
        details = raw.get("details") or {}
        counterparty = details.get("counterparty") or {}
        posted_at = datetime.combine(
            datetime.strptime(str(raw["date"]), "%Y-%m-%d").date(),
            time.min, tzinfo=timezone.utc,
        )
        return TransactionData(
            external_id=str(raw["id"]),
            posted_at=posted_at,
            amount=Decimal(str(raw.get("amount", "0"))),
            description=str(raw.get("description", "")),
            payee=str(counterparty.get("name") or raw.get("description", "")),
            memo="",
            pending=str(details.get("processing_status", "")) == "pending",
        )

    def fetch_investment_accounts(self, access_url: str) -> Iterable[InvestmentAccountSyncPayload]:
        # Teller has no investments API.
        return iter(())
