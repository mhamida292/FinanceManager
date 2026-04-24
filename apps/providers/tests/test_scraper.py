from decimal import Decimal

import pytest
import responses

from apps.providers.scrapers.css import CSSSelectorScraper


_HTML_WITH_EXPLICIT_PRICE = """
<!doctype html>
<html><body>
  <div class="product-price"><span class="amount">$2,734.50</span></div>
</body></html>
"""

_HTML_NO_MATCHING_SELECTOR_BUT_HEURISTIC = """
<!doctype html>
<html><body>
  <div class="some-wrapper"><span class="price">Our price: $1,099.99</span></div>
</body></html>
"""

_HTML_ONLY_FULL_PAGE = """
<!doctype html>
<html><body>
  <p>Shipping from $9.99 and available for $87.42 today only.</p>
</body></html>
"""

_HTML_NO_PRICE = "<html><body><p>Out of stock</p></body></html>"


@responses.activate
def test_scraper_uses_explicit_selector_when_given():
    responses.add(responses.GET, "https://example.com/p1", body=_HTML_WITH_EXPLICIT_PRICE, status=200)
    got = CSSSelectorScraper().fetch("https://example.com/p1", selector=".product-price .amount")
    assert got.price == Decimal("2734.50")
    assert got.source_url == "https://example.com/p1"


@responses.activate
def test_scraper_falls_back_to_heuristic_when_no_selector():
    responses.add(responses.GET, "https://example.com/p2", body=_HTML_NO_MATCHING_SELECTOR_BUT_HEURISTIC, status=200)
    got = CSSSelectorScraper().fetch("https://example.com/p2")
    assert got.price == Decimal("1099.99")


@responses.activate
def test_scraper_last_resort_full_page_text():
    responses.add(responses.GET, "https://example.com/p3", body=_HTML_ONLY_FULL_PAGE, status=200)
    got = CSSSelectorScraper().fetch("https://example.com/p3")
    assert got.price == Decimal("9.99")


@responses.activate
def test_scraper_raises_when_no_price_anywhere():
    responses.add(responses.GET, "https://example.com/p4", body=_HTML_NO_PRICE, status=200)
    with pytest.raises(RuntimeError, match="No \\$-prefixed price"):
        CSSSelectorScraper().fetch("https://example.com/p4")


@responses.activate
def test_scraper_handles_comma_thousands():
    responses.add(responses.GET, "https://example.com/p5",
                  body='<div class="price">$12,345.67</div>', status=200)
    got = CSSSelectorScraper().fetch("https://example.com/p5")
    assert got.price == Decimal("12345.67")
