from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Protocol


@dataclass(frozen=True)
class PriceQuote:
    symbol: str
    price: Decimal
    at: datetime


class PriceProvider(Protocol):
    """Fetches current prices for one or more ticker symbols.

    Keep pure: no DB access. Callers are responsible for persistence.
    """

    name: str  # "yahoo", "polygon", ...

    def fetch_quotes(self, symbols: Iterable[str]) -> list[PriceQuote]:
        ...
