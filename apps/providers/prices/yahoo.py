from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

import yfinance as yf

from .base import PriceProvider, PriceQuote
from .registry import register


@register
class YahooFinancePriceProvider:
    name = "yahoo"

    def fetch_quotes(self, symbols: Iterable[str]) -> list[PriceQuote]:
        symbols = [s.strip().upper() for s in symbols if s and s.strip()]
        if not symbols:
            return []

        tickers = yf.Tickers(" ".join(symbols))
        now = datetime.now(tz=timezone.utc)
        quotes: list[PriceQuote] = []

        for symbol in symbols:
            try:
                info = tickers.tickers[symbol].fast_info
                price = info.get("last_price") or info.get("regular_market_price")
            except Exception:
                price = None
            if price is None:
                continue
            quotes.append(PriceQuote(
                symbol=symbol,
                price=Decimal(str(price)).quantize(Decimal("0.0001")),
                at=now,
            ))

        return quotes
