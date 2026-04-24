"""Stooq price provider — free, no API key, doesn't block data-center IPs the
way Yahoo Finance has been doing.

Wire format:
    GET https://stooq.com/q/l/?s=gldm.us,aapl.us&i=d&f=sd2t2ohlcvn&h

Returns CSV:
    Symbol,Date,Time,Open,High,Low,Close,Volume,Name
    GLDM.US,2026-04-24,22:00:19,92.93,93.79,92.81,93.33,1960402,SPDR GOLD MINISHARES TRUST

Stooq uses lowercase symbols with a ``.us`` suffix for US tickers. We normalize
on the way in (symbol → ``<symbol>.us``) and strip the ``.US`` suffix off the
response so the caller sees the symbol they passed in.
"""
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Iterable

import requests

from .base import PriceProvider, PriceQuote
from .registry import register


@register
class StooqPriceProvider:
    name = "stooq"

    def __init__(self, http: requests.Session | None = None, timeout: float = 15.0) -> None:
        self._http = http or requests.Session()
        self._timeout = timeout

    def fetch_quotes(self, symbols: Iterable[str]) -> list[PriceQuote]:
        # Stooq's /q/l endpoint doesn't reliably batch comma-separated symbols
        # (the response collapses them into one malformed row). Do one request
        # per symbol — Stooq is fast and lightweight, the cost is negligible.
        normalized = [s.strip().upper() for s in symbols if s and s.strip()]
        if not normalized:
            return []

        now = datetime.now(tz=timezone.utc)
        quotes: list[PriceQuote] = []

        for symbol in normalized:
            try:
                quote = self._fetch_one(symbol, now)
            except Exception:
                continue
            if quote is not None:
                quotes.append(quote)

        return quotes

    def _fetch_one(self, symbol: str, at: datetime) -> PriceQuote | None:
        url = f"https://stooq.com/q/l/?s={symbol.lower()}.us&i=d&f=sd2t2ohlcvn&h"
        response = self._http.get(url, timeout=self._timeout)
        response.raise_for_status()

        reader = csv.DictReader(StringIO(response.text))
        for row in reader:
            close = (row.get("Close") or "").strip()
            if not close or close == "N/D":
                return None
            try:
                price = Decimal(close).quantize(Decimal("0.0001"))
            except (InvalidOperation, ValueError):
                return None
            return PriceQuote(symbol=symbol, price=price, at=at)
        return None
