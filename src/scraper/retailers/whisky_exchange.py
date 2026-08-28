import logging
import re
import string
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.enrich import extract_abv
from scraper.models import Product
from scraper.retailers.base import register

log = logging.getLogger(__name__)

BASE = "https://www.thewhiskyexchange.com"
_SIZE_IN_META = re.compile(r"^\s*([\d.]+\s*(?:cl|ml|l))\b", re.I)

# Category, style and place words. A brand name does not stop here when it
# leads the product name, so "Gin Mare" still reads as a brand.
_BRAND_STOP_WORDS = {
    "gin", "jenever", "vodka", "dry", "london", "old", "tom", "navy", "strength", "sloe", "pink",
    "organic", "premium", "classic", "edition", "gift", "box", "half", "litre", "litres", "cl", "ml",
    "islay", "kyoto", "schwarzwald", "coastal", "mediterranean", "capri", "scottish", "cornish",
    "american", "japanese", "italian", "german", "spanish", "french", "garden", "botanical",
    "botanicals", "distilled", "handcrafted", "small", "batch", "reserve", "original",
}
_BRAND_MAX_WORDS = 4


def brand_from_name(name: str) -> str:
    """Guess a brand from a product name. The site publishes no brand field."""
    words = name.split()
    if not words:
        return ""
    picked: list[str] = []
    for index, word in enumerate(words):
        bare = word.strip(string.punctuation).lower()
        if index and bare in _BRAND_STOP_WORDS:
            break
        picked.append(word)
        if len(picked) >= _BRAND_MAX_WORDS:
            break
    brand = " ".join(picked).strip(string.punctuation)
    return brand or words[0]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _price(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return None


@register
class WhiskyExchange:
    name = "whisky_exchange"
    category = "gin"
    # This site has no JSON-LD. The listing page already holds the size and the
    # strength, so the adapter does not need a second request for each product.
    # The path holds the gin and jenever category.
    category_url = f"{BASE}/c/338/gin"

    def find_product_urls(self, listing_html: str) -> list[str]:
        soup = BeautifulSoup(listing_html, "lxml")
        urls: list[str] = []
        for card in soup.select("a.product-card[href]"):
            url = urljoin(BASE, card["href"])
            if url not in urls:
                urls.append(url)
        return urls

    def parse_listing(self, listing_html: str) -> list[Product]:
        soup = BeautifulSoup(listing_html, "lxml")
        products = []
        for card in soup.select("a.product-card[href]"):
            products.append(self._from_card(card, urljoin(BASE, card["href"])))
        return products

    def parse_product(self, html: str, url: str) -> Product:
        soup = BeautifulSoup(html, "lxml")
        card = soup.select_one("a.product-card[href]")
        if card is None:
            return Product(
                retailer=self.name, category=self.category, product_url=url, scraped_at=_now()
            )
        return self._from_card(card, url)

    def _from_card(self, card, url: str) -> Product:
        name_tag = card.select_one("p.product-card__name")
        name = name_tag.get_text(" ", strip=True) if name_tag else None

        meta_tag = card.select_one("p.product-card__meta")
        meta = meta_tag.get_text(" ", strip=True) if meta_tag else ""

        price_tag = card.select_one("p.product-card__price")
        price = _price(price_tag.get_text(strip=True) if price_tag else None)

        size_match = _SIZE_IN_META.search(meta)
        size_raw = size_match.group(1).replace(" ", "") if size_match else None

        product = Product(
            retailer=self.name,
            category=self.category,
            product_url=url,
            scraped_at=_now(),
            name=name,
            brand=brand_from_name(name) if name else None,
            price_gbp=price,
            size_raw=size_raw,
            abv_percent=extract_abv(meta),
        )
        product.detail_text = meta
        for field in ("name", "brand", "price_gbp", "size_raw", "abv_percent"):
            # Guard against an empty string, not just a missing value, the
            # same way the Morrisons adapter does for its JSON-LD fields.
            value = getattr(product, field)
            product.field_sources[field] = "css" if value not in (None, "") else "missing"
        # The listing card does not show a struck-through price. Do not guess one.
        product.field_sources["price_was"] = "missing"
        return product

    def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
        # This site lists every hard attribute on the listing page itself.
        # Its detail page holds no product card for itself, so a per-URL
        # fetch loop would return null names. Read the listing page and
        # stop there; do not fetch each product page.
        listing = fetcher.get(self.category_url)
        try:
            cards = self.parse_listing(listing)
        except Exception as exc:
            log.warning("Cannot read the listing page at %s: %s", self.name, exc)
            cards = []

        cards = cards[:limit]
        expected = len(cards)
        log.info("Found %s products on the listing page at %s", expected, self.name)

        products: list[Product] = []
        for index, product in enumerate(cards, start=1):
            if product.name is None:
                log.warning(
                    "No name found for product %s of %s. The page layout may have changed.",
                    index, expected,
                )
                continue
            products.append(product)
        return products, expected
