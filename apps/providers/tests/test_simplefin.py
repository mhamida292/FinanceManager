import base64
from decimal import Decimal

import pytest
import responses

from apps.providers.simplefin import SimpleFINProvider


def _encode_setup_url(url: str) -> str:
    return base64.b64encode(url.encode()).decode()


@responses.activate
def test_exchange_setup_token_returns_access_url():
    setup_url = "https://bridge.simplefin.org/simplefin/claim/ABCDEF"
    access_url = "https://USER:TOKEN@bridge.simplefin.org/simplefin"
    responses.add(responses.POST, setup_url, body=access_url, status=200)

    got = SimpleFINProvider().exchange_setup_token(_encode_setup_url(setup_url))
    assert got == access_url


@responses.activate
def test_exchange_setup_token_rejects_non_base64():
    with pytest.raises(ValueError, match="not valid base64"):
        SimpleFINProvider().exchange_setup_token("not!!base64!!")


@responses.activate
def test_exchange_setup_token_rejects_non_https_decoded():
    with pytest.raises(ValueError, match="not an HTTPS URL"):
        SimpleFINProvider().exchange_setup_token(_encode_setup_url("ftp://evil.example/x"))


@responses.activate
def test_fetch_accounts_parses_payload():
    access_url = "https://USER:TOKEN@bridge.simplefin.org/simplefin"
    accounts_url = f"{access_url}/accounts?start-date=0"
    responses.add(
        responses.GET,
        accounts_url,
        json={
            "errors": [],
            "accounts": [
                {
                    "id": "ACC-1",
                    "name": "Joint Checking",
                    "currency": "USD",
                    "balance": "1234.56",
                    "org": {"name": "Chase"},
                    "transactions": [
                        {
                            "id": "TXN-1",
                            "posted": 1706000000,
                            "amount": "-42.18",
                            "description": "Coffee shop",
                            "payee": "Starbucks",
                            "memo": "",
                            "pending": False,
                        }
                    ],
                }
            ],
        },
        status=200,
    )

    payloads = list(SimpleFINProvider().fetch_accounts_with_transactions(access_url))

    assert len(payloads) == 1
    p = payloads[0]
    assert p.account.external_id == "ACC-1"
    assert p.account.name == "Joint Checking"
    assert p.account.type == "checking"
    assert p.account.balance == Decimal("1234.56")
    assert p.account.org_name == "Chase"
    assert len(p.transactions) == 1
    assert p.transactions[0].external_id == "TXN-1"
    assert p.transactions[0].payee == "Starbucks"
    assert p.transactions[0].amount == Decimal("-42.18")


@responses.activate
def test_fetch_raises_when_errors_and_no_accounts():
    access_url = "https://U:T@bridge.simplefin.org/simplefin"
    responses.add(
        responses.GET,
        f"{access_url}/accounts?start-date=0",
        json={"errors": ["broken"], "accounts": []},
        status=200,
    )
    with pytest.raises(RuntimeError, match="errors and no accounts"):
        list(SimpleFINProvider().fetch_accounts_with_transactions(access_url))


@responses.activate
def test_fetch_investment_accounts_parses_holdings():
    access_url = "https://U:T@bridge.simplefin.org/simplefin"
    responses.add(
        responses.GET,
        f"{access_url}/accounts?start-date=0",
        json={
            "errors": [],
            "accounts": [
                {
                    "id": "BANK-1", "name": "Checking", "currency": "USD", "balance": "500",
                    "org": {"name": "Chase"},
                    "transactions": [],
                },
                {
                    "id": "INV-1", "name": "Roth IRA", "currency": "USD", "balance": "10000",
                    "org": {"name": "Robinhood"},
                    "holdings": [
                        {
                            "id": "H-1", "symbol": "AAPL", "description": "Apple Inc.",
                            "shares": "10", "price": "180.00",
                            "market_value": "1800.00", "cost_basis": "1500.00",
                        },
                        {
                            "id": "H-2", "symbol": "VTI", "description": "Vanguard Total Stock",
                            "shares": "40", "price": "250.50",
                            "market_value": "10020.00",
                        },
                    ],
                },
            ],
        },
        status=200,
    )

    provider = SimpleFINProvider()

    bank_payloads = list(provider.fetch_accounts_with_transactions(access_url))
    assert len(bank_payloads) == 1
    assert bank_payloads[0].account.external_id == "BANK-1"

    inv_payloads = list(provider.fetch_investment_accounts(access_url))
    assert len(inv_payloads) == 1
    inv = inv_payloads[0]
    assert inv.external_id == "INV-1"
    assert inv.broker == "Robinhood"
    assert len(inv.holdings) == 2

    aapl = inv.holdings[0]
    assert aapl.symbol == "AAPL"
    assert aapl.shares == Decimal("10")
    assert aapl.current_price == Decimal("180.00")
    assert aapl.market_value == Decimal("1800.00")
    assert aapl.cost_basis == Decimal("1500.00")

    vti = inv.holdings[1]
    assert vti.cost_basis is None
