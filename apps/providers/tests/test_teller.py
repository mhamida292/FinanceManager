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
