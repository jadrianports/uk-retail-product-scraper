import json
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.models import Product
from scraper.retailers.base import register

BASE = "https://groceries.morrisons.com"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _detail_text(soup: BeautifulSoup) -> str:
    # The page holds a large translation blob inside script tags. Remove all
    # script and style tags first, or the extractors match the wrong words.
    copy = BeautifulSoup(str(soup), "lxml")
    for tag in copy(["script", "style"]):
        tag.decompose()
    return copy.get_text(" ", strip=True)


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
    category = "gin"
    category_url = f"{BASE}/categories/beer-wines-spirits/spirits-liqueurs/gin/151526"

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

        product = Product(
            retailer=self.name,
            category=self.category,
            product_url=url,
            scraped_at=_now(),
            sku=data.get("sku"),
            name=data.get("name"),
            brand=brand,
            price_gbp=price,
            size_raw=data.get("size"),
            availability=availability,
            description=data.get("description"),
        )
        for field in ("sku", "name", "brand", "price_gbp", "size_raw", "availability", "description"):
            if getattr(product, field) is not None:
                product.field_sources[field] = "jsonld"

        product.detail_text = _detail_text(soup)
        return product
