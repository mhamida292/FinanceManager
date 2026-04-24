from decimal import Decimal

import pytest
import responses

from apps.providers.prices.stooq import StooqPriceProvider


_REAL_RESPONSE_GLDM = """Symbol,Date,Time,Open,High,Low,Close,Volume,Name
GLDM.US,2026-04-24,22:00:19,92.93,93.79,92.81,93.33,1960402,SPDR GOLD MINISHARES TRUST
"""

_BATCH_RESPONSE = """Symbol,Date,Time,Open,High,Low,Close,Volume,Name
AAPL.US,2026-04-24,22:00:19,180.00,182.50,179.50,182.47,12345678,APPLE INC
MSFT.US,2026-04-24,22:00:19,408.00,411.00,407.50,410.10,4567890,MICROSOFT CORP
"""

_UNKNOWN_SYMBOL_RESPONSE = """Symbol,Date,Time,Open,High,Low,Close,Volume,Name
NOPE.US,N/D,N/D,N/D,N/D,N/D,N/D,N/D,
"""


def _matches_url(prefix: str):
    """Match any GET URL that starts with the given prefix (Stooq URL has variable symbol list)."""
    import re
    return re.compile(re.escape(prefix) + r".*")


@responses.activate
def test_stooq_parses_single_symbol():
    responses.add(
        responses.GET,
        _matches_url("https://stooq.com/q/l/?s=gldm.us"),
        body=_REAL_RESPONSE_GLDM,
        status=200,
    )
    quotes = StooqPriceProvider().fetch_quotes(["GLDM"])
    assert len(quotes) == 1
    assert quotes[0].symbol == "GLDM"
    assert quotes[0].price == Decimal("93.3300")


@responses.activate
def test_stooq_parses_batch():
    responses.add(
        responses.GET,
        _matches_url("https://stooq.com/q/l/?s=aapl.us,msft.us"),
        body=_BATCH_RESPONSE,
        status=200,
    )
    quotes = StooqPriceProvider().fetch_quotes(["aapl", "msft"])
    by_symbol = {q.symbol: q.price for q in quotes}
    assert by_symbol == {"AAPL": Decimal("182.4700"), "MSFT": Decimal("410.1000")}


@responses.activate
def test_stooq_skips_unknown_symbols():
    responses.add(
        responses.GET,
        _matches_url("https://stooq.com/q/l/?s=nope.us"),
        body=_UNKNOWN_SYMBOL_RESPONSE,
        status=200,
    )
    quotes = StooqPriceProvider().fetch_quotes(["NOPE"])
    assert quotes == []


def test_stooq_empty_input_returns_empty():
    assert StooqPriceProvider().fetch_quotes([]) == []
    assert StooqPriceProvider().fetch_quotes(["", "   "]) == []
