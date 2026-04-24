from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.providers.prices.yahoo import YahooFinancePriceProvider


def _fake_ticker(price):
    t = MagicMock()
    t.fast_info = {"last_price": price}
    return t


@patch("apps.providers.prices.yahoo.yf.Tickers")
def test_fetch_quotes_maps_prices(mock_tickers_cls):
    mock_bundle = MagicMock()
    mock_bundle.tickers = {
        "AAPL": _fake_ticker(182.47),
        "MSFT": _fake_ticker(410.1),
    }
    mock_tickers_cls.return_value = mock_bundle

    quotes = YahooFinancePriceProvider().fetch_quotes(["AAPL", "msft"])

    symbols = {q.symbol: q.price for q in quotes}
    assert symbols["AAPL"] == Decimal("182.4700")
    assert symbols["MSFT"] == Decimal("410.1000")


@patch("apps.providers.prices.yahoo.yf.Tickers")
def test_fetch_quotes_skips_unknown_symbol(mock_tickers_cls):
    t_good = _fake_ticker(100.0)
    t_bad = MagicMock()
    t_bad.fast_info = {}

    mock_bundle = MagicMock()
    mock_bundle.tickers = {"AAPL": t_good, "NOPE": t_bad}
    mock_tickers_cls.return_value = mock_bundle

    quotes = YahooFinancePriceProvider().fetch_quotes(["AAPL", "NOPE"])
    assert len(quotes) == 1
    assert quotes[0].symbol == "AAPL"


def test_fetch_quotes_empty_input_returns_empty():
    assert YahooFinancePriceProvider().fetch_quotes([]) == []
    assert YahooFinancePriceProvider().fetch_quotes(["", "   "]) == []
