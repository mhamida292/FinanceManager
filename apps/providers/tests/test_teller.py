import base64
from decimal import Decimal

import pytest
import responses

from apps.providers.teller import TellerProvider


@pytest.fixture
def teller_settings(settings, tmp_path):
    """Stub TELLER_CERT_PATH/TELLER_KEY_PATH to real (empty) files so requests.Session.cert
    assignment doesn't fail. The HTTP layer is mocked by `responses`, so the cert
    is never actually used during these tests."""
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("dummy")
    key.write_text("dummy")
    settings.TELLER_CERT_PATH = str(cert)
    settings.TELLER_KEY_PATH = str(key)
    return settings


@responses.activate
def test_exchange_setup_token_returns_token_unchanged_on_success(teller_settings):
    """Teller has no token-exchange step; we validate the access token by calling
    GET /accounts and return the token verbatim on a 200."""
    access_token = "test_TELLER_ACCESS_TOKEN_abc"
    responses.add(
        responses.GET,
        "https://api.teller.io/accounts",
        json=[],
        status=200,
    )

    got = TellerProvider().exchange_setup_token(access_token)

    assert got == access_token
    assert len(responses.calls) == 1
    auth = responses.calls[0].request.headers["Authorization"]
    expected = "Basic " + base64.b64encode(f"{access_token}:".encode()).decode()
    assert auth == expected


@responses.activate
def test_exchange_setup_token_raises_on_401(teller_settings):
    responses.add(
        responses.GET,
        "https://api.teller.io/accounts",
        json={"error": {"code": "invalid_credentials", "message": "Bad token"}},
        status=401,
    )

    with pytest.raises(ValueError, match="Teller rejected the access token"):
        TellerProvider().exchange_setup_token("bad_token")


@responses.activate
def test_fetch_accounts_with_transactions_parses_payload(teller_settings):
    """One checking account, one balance call, one transactions page (no pagination)."""
    access_token = "test_TOKEN"

    responses.add(
        responses.GET,
        "https://api.teller.io/accounts",
        json=[
            {
                "id": "acc_test_1",
                "name": "Joint Checking",
                "type": "depository",
                "subtype": "checking",
                "currency": "USD",
                "institution": {"id": "ins_chase", "name": "Chase"},
                "links": {
                    "balances": "https://api.teller.io/accounts/acc_test_1/balances",
                    "transactions": "https://api.teller.io/accounts/acc_test_1/transactions",
                },
            },
        ],
        status=200,
    )

    responses.add(
        responses.GET,
        "https://api.teller.io/accounts/acc_test_1/balances",
        json={"account_id": "acc_test_1", "ledger": "1234.56", "available": "1200.00"},
        status=200,
    )

    responses.add(
        responses.GET,
        "https://api.teller.io/accounts/acc_test_1/transactions",
        json=[
            {
                "id": "txn_test_1",
                "account_id": "acc_test_1",
                "date": "2026-04-15",
                "amount": "-42.18",
                "description": "Starbucks Coffee",
                "details": {
                    "processing_status": "complete",
                    "counterparty": {"name": "Starbucks", "type": "merchant"},
                },
            },
        ],
        status=200,
    )

    payloads = list(TellerProvider().fetch_accounts_with_transactions(access_token))

    assert len(payloads) == 1
    p = payloads[0]
    assert p.account.external_id == "acc_test_1"
    assert p.account.name == "Joint Checking"
    assert p.account.type == "checking"
    assert p.account.balance == Decimal("1234.56")
    assert p.account.currency == "USD"
    assert p.account.org_name == "Chase"

    assert len(p.transactions) == 1
    t = p.transactions[0]
    assert t.external_id == "txn_test_1"
    assert t.amount == Decimal("-42.18")
    assert t.description == "Starbucks Coffee"
    assert t.payee == "Starbucks"
    assert t.memo == ""
    assert t.pending is False
    assert t.posted_at.year == 2026 and t.posted_at.month == 4 and t.posted_at.day == 15
    assert t.posted_at.hour == 0 and t.posted_at.minute == 0
