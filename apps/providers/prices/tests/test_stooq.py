from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from apps.providers.prices.stooq import StooqPriceProvider


def _csv_response(symbol: str, price: str) -> MagicMock:
    body = f"Symbol,Date,Time,Open,High,Low,Close,Volume,Name\n{symbol.upper()}.US,2026-05-07,22:00:00,1,1,1,{price},100,Test\n"
    r = MagicMock()
    r.text = body
    r.raise_for_status = MagicMock()
    return r


def test_fetch_quotes_returns_one_quote_per_symbol():
    http = MagicMock()
    http.get.side_effect = lambda url, timeout: _csv_response(_symbol_from_url(url), "10.00")
    provider = StooqPriceProvider(http=http)

    quotes = provider.fetch_quotes(["AAPL", "MSFT", "GOOG", "AMZN", "META"])

    assert {q.symbol for q in quotes} == {"AAPL", "MSFT", "GOOG", "AMZN", "META"}
    assert all(q.price == Decimal("10.0000") for q in quotes)
    assert http.get.call_count == 5


def test_fetch_quotes_isolates_individual_failures():
    """One symbol raising must not kill the batch — the others still resolve."""
    def maybe_fail(url, timeout):
        if "fail" in url:
            raise RuntimeError("boom")
        return _csv_response(_symbol_from_url(url), "5.00")

    http = MagicMock()
    http.get.side_effect = maybe_fail
    provider = StooqPriceProvider(http=http)

    quotes = provider.fetch_quotes(["GOOD1", "FAIL", "GOOD2"])

    assert {q.symbol for q in quotes} == {"GOOD1", "GOOD2"}


def test_fetch_quotes_empty_input_returns_empty_list():
    http = MagicMock()
    provider = StooqPriceProvider(http=http)
    assert provider.fetch_quotes([]) == []
    assert provider.fetch_quotes(["", "  "]) == []
    http.get.assert_not_called()


def _symbol_from_url(url: str) -> str:
    # URL is "...?s=<sym>.us&..."; pull out the lowercase symbol before ".us".
    after_s = url.split("s=", 1)[1]
    sym_lower = after_s.split(".us", 1)[0]
    return sym_lower
