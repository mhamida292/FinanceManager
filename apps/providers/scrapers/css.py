import re
from datetime import datetime, timezone
from decimal import Decimal

import requests
from bs4 import BeautifulSoup

from .base import PriceScraper, ScrapedPrice
from .registry import register

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_PRICE_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
_HEURISTIC_CLASS_HINTS = ("current-price", "price-current", "product-price", "price", "amount")


@register
class CSSSelectorScraper:
    name = "css"

    def __init__(self, http: requests.Session | None = None, timeout: float = 20.0) -> None:
        self._http = http or requests.Session()
        self._timeout = timeout

    def fetch(self, url: str, selector: str = "") -> ScrapedPrice:
        response = self._http.get(url, headers={"User-Agent": _USER_AGENT}, timeout=self._timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        text, match = self._extract(soup, selector)
        if match is None:
            raise RuntimeError(f"No $-prefixed price found at {url} (selector={selector!r})")

        price_str = match.group(1).replace(",", "")
        return ScrapedPrice(
            source_url=url,
            price=Decimal(price_str),
            at=datetime.now(tz=timezone.utc),
            raw_text=text[:200],
        )

    def _extract(self, soup: BeautifulSoup, selector: str) -> tuple[str, re.Match | None]:
        if selector:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(" ", strip=True)
                match = _PRICE_RE.search(text)
                if match:
                    return text, match

        for hint in _HEURISTIC_CLASS_HINTS:
            for element in soup.select(f"[class*={hint}]"):
                text = element.get_text(" ", strip=True)
                match = _PRICE_RE.search(text)
                if match:
                    return text, match

        text = soup.get_text(" ", strip=True)
        return text, _PRICE_RE.search(text)
