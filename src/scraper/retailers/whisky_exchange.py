import json
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
# A flash reading "Save £N" states a money saving. A flash like "Free Gift"
# does not, so it must not feed a price_was guess.
_SAVING_IN_FLASH = re.compile(r"^save\s*£\s*(\d+(?:\.\d{1,2})?)$", re.I)
# Extract product id from URL path like /p/14553/product-name
_SKU_IN_URL = re.compile(r"/p/(\d+)/")

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


def _extract_sku_from_url(url: str) -> str | None:
    """Extract product id from URL path like /p/14553/product-name."""
    match = _SKU_IN_URL.search(url)
    return match.group(1) if match else None


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



def _product_json_ld(soup: BeautifulSoup) -> dict:
    """Read the Product schema from a detail page.

    The listing page carries none. An earlier version of this adapter said
    the whole site carried none, on evidence from the listing alone.
    """
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
    return {}


def _product_facts(soup: BeautifulSoup) -> dict[str, str]:
    """Read the labelled facts list on a detail page.

    An earlier version of this adapter said the words Country and Distillery
    on these pages belonged to the navigation. They are a labelled list, one
    label and one value per item. That claim was written without fetching a
    detail page, because every attempt met a challenge.
    """
    facts: dict[str, str] = {}
    for item in soup.select(".product-facts__item"):
        label = item.select_one(".product-facts__type")
        value = item.select_one(".product-facts__data")
        if label and value:
            facts[label.get_text(strip=True)] = value.get_text(" ", strip=True)
    return facts

@register
class WhiskyExchange:
    name = "whisky_exchange"

    # This site has no JSON-LD. The listing page already holds the size and the
    # strength, so the adapter does not need a second request for each product.
    # The path holds the gin and jenever category.
    #
    # Every path was fetched and counted before it was added. A category URL
    # that nobody checked is how this tool once labelled whisky as gin.
    # Each returns 24 cards and a title that matches the category.
    CATEGORIES = {
        "gin": f"{BASE}/c/338/gin",
        "vodka": f"{BASE}/c/335/vodka",
        "rum": f"{BASE}/c/339/rum",
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

        flash_tag = card.select_one(".product-extras-flash__content")
        flash_text = flash_tag.get_text(strip=True) if flash_tag else ""
        is_on_promotion = bool(flash_text)

        price_was = None
        saving_match = _SAVING_IN_FLASH.match(flash_text) if flash_text else None
        if saving_match and price is not None:
            price_was = round(price + float(saving_match.group(1)), 2)

        button_tag = card.select_one(".product-card__button")
        button_text = button_tag.get_text(strip=True) if button_tag else ""
        availability = "InStock" if "add to basket" in button_text.lower() else None

        sku = _extract_sku_from_url(url)

        product = Product(
            retailer=self.name,
            category=self.category,
            product_url=url,
            scraped_at=_now(),
            sku=sku,
            name=name,
            brand=brand_from_name(name) if name else None,
            price_gbp=price,
            price_was=price_was,
            is_on_promotion=is_on_promotion,
            size_raw=size_raw,
            abv_percent=extract_abv(meta),
            availability=availability,
        )
        product.detail_text = meta
        for field in ("name", "brand", "price_gbp", "size_raw", "abv_percent"):
            # Guard against an empty string, not just a missing value, the
            # same way the Morrisons adapter does for its JSON-LD fields.
            value = getattr(product, field)
            product.field_sources[field] = "css" if value not in (None, "") else "missing"
        # The flash element states the promotion. Its absence is a fact too.
        product.field_sources["is_on_promotion"] = "css" if flash_text else "missing"
        # Only a money flash gives a price_was. A non-money flash, like
        # "Free Gift", must not feed a guessed value.
        product.field_sources["price_was"] = "css" if price_was is not None else "missing"
        # A missing button is not proof of no stock. Tag it missing, not a guess.
        product.field_sources["availability"] = "css" if availability is not None else "missing"
        # The product id sits in the product URL.
        product.field_sources["sku"] = "css" if sku is not None else "missing"
        return product

    def parse_detail(self, html: str, product: Product) -> None:
        """Fill the fields the listing card cannot carry.

        The card gives the size, the strength and the promotion cheaply. The
        detail page gives the real brand and the description, and the
        description is what the pack type, the origin and the flavour need.
        """
        soup = BeautifulSoup(html, "lxml")
        data = _product_json_ld(soup)

        brand = data.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        if brand:
            # The retailer states the brand, so the guess from the name goes.
            product.brand = brand
            product.field_sources["brand"] = "jsonld"

        description = data.get("description")
        source = "jsonld"
        if not description:
            element = soup.select_one(".product-main__description")
            description = element.get_text(" ", strip=True) if element else None
            source = "css"
        if description:
            product.description = description
            product.detail_text = description
            product.field_sources["description"] = source

        # The facts list states the country. It is the retailer's own label,
        # so it is recorded as published: "Caribbean Blend" is a blend and not
        # a country, and normalising it here would lose what the page said.
        country = _product_facts(soup).get("Country")
        if country:
            product.country_of_origin = country
            product.field_sources["country_of_origin"] = "css"

    def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
        # The listing gives the size, the strength and the promotion. The
        # detail page gives the brand and the description, so it is worth one
        # request per product. A detail page that fails leaves the card values
        # in place rather than dropping the product.
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
            try:
                self.parse_detail(fetcher.get(product.product_url), product)
            except Exception as exc:
                log.warning(
                    "Cannot read the detail page for %s: %s. The listing values stay.",
                    product.name, exc,
                )
            products.append(product)
        return products, expected
