import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.fetch import RobotsDenied
from scraper.models import Product
from scraper.retailers.base import register

log = logging.getLogger(__name__)

BASE = "https://groceries.morrisons.com"

# Matches a bare pound amount, e.g. "£30.50". A struck-through unit price
# like "(£43.57/litre)" has trailing text, so it does not match.
_BARE_PRICE = re.compile(r"£\s?(\d+(?:\.\d{2})?)")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _detail_text(soup: BeautifulSoup) -> str:
    # The page holds a large translation blob inside script tags. Remove all
    # script and style tags first, or the extractors match the wrong words.
    copy = BeautifulSoup(str(soup), "lxml")
    for tag in copy(["script", "style"]):
        tag.decompose()
    return copy.get_text(" ", strip=True)


def _price_was(soup: BeautifulSoup) -> float | None:
    # The JSON-LD offers.price is the current price only. The pre-promotion
    # price is not in the JSON-LD, so read it from the strikethrough element.
    for element in soup.select('[class*="strikethrough"]'):
        text = element.get_text(strip=True)
        match = re.fullmatch(_BARE_PRICE, text)
        if match:
            return float(match.group(1))
    return None


def _product_json_ld(soup: BeautifulSoup) -> dict:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return {}


@register
class Morrisons:
    name = "morrisons"

    # Every entry was fetched and checked for products before it was added.
    # A category is a real URL on the site, not a name this tool invents.
    _SPIRITS = f"{BASE}/categories/beer-wines-spirits/spirits-liqueurs"
    CATEGORIES = {
        "gin": f"{_SPIRITS}/gin/151526",
        "vodka": f"{_SPIRITS}/vodka/151525",
        "whisky": f"{_SPIRITS}/whisky/151509",
        "rum": f"{_SPIRITS}/rum/151520",
        "brandy": f"{_SPIRITS}/brandy/151517",
        "tequila": f"{_SPIRITS}/tequila/191961",
    }
    DEFAULT_CATEGORY = "gin"

    def __init__(self, category: str | None = None) -> None:
        self.category = category or self.DEFAULT_CATEGORY
        if self.category not in self.CATEGORIES:
            known = ", ".join(sorted(self.CATEGORIES))
            raise KeyError(
                f"{self.name} has no category '{self.category}'. Known: {known}"
            )
        self.category_url = self.CATEGORIES[self.category]

    def find_product_urls(self, listing_html: str) -> list[str]:
        soup = BeautifulSoup(listing_html, "lxml")
        urls: list[str] = []
        for anchor in soup.select('a[href^="/products/"]'):
            url = urljoin(BASE, anchor["href"])
            if url not in urls:
                urls.append(url)
        return urls

    def parse_product(self, html: str, url: str) -> Product:
        soup = BeautifulSoup(html, "lxml")
        data = _product_json_ld(soup)
        offers = data.get("offers") or {}

        brand = data.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")

        price = offers.get("price")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None

        availability = offers.get("availability")
        if isinstance(availability, str):
            availability = availability.rsplit("/", 1)[-1]

        price_was = _price_was(soup)
        is_on_promotion = price_was is not None and price is not None and price_was > price

        product = Product(
            retailer=self.name,
            category=self.category,
            product_url=url,
            scraped_at=_now(),
            sku=data.get("sku"),
            name=data.get("name"),
            brand=brand,
            price_gbp=price,
            price_was=price_was,
            is_on_promotion=is_on_promotion,
            size_raw=data.get("size"),
            availability=availability,
            description=data.get("description"),
        )
        for field in ("sku", "name", "brand", "price_gbp", "size_raw", "availability", "description"):
            # JSON-LD can give an empty string, not just a missing key. An
            # empty value is not a sourced value, so tag it missing too.
            value = getattr(product, field)
            product.field_sources[field] = "jsonld" if value not in (None, "") else "missing"

        if price_was is not None:
            product.field_sources["price_was"] = "css"
            product.field_sources["is_on_promotion"] = "css"
        else:
            product.field_sources["price_was"] = "missing"

        product.detail_text = _detail_text(soup)
        return product

    def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
        listing = fetcher.get(self.category_url)
        urls = self.find_product_urls(listing)[:limit]
        expected = len(urls)
        log.info("Found %s product pages at %s", expected, self.name)

        products: list[Product] = []
        for index, url in enumerate(urls, start=1):
            try:
                product = self.parse_product(fetcher.get(url), url)
            except RobotsDenied:
                raise
            except Exception as exc:
                log.warning("Cannot read product %s of %s at %s: %s", index, expected, url, exc)
                continue

            if product.name is None:
                log.warning("No name found at %s. The page layout may have changed.", url)
                continue

            products.append(product)
        return products, expected
