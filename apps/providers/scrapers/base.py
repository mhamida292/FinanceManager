from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class ScrapedPrice:
    source_url: str
    price: Decimal
    at: datetime
    raw_text: str = ""


class PriceScraper(Protocol):
    """Fetches a single price from a URL. Keep pure: no DB, no model imports."""
    name: str

    def fetch(self, url: str, selector: str = "") -> ScrapedPrice:
        ...
