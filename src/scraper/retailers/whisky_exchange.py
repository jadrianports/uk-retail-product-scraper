import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.enrich import extract_abv
from scraper.models import Product
from scraper.retailers.base import register

BASE = "https://www.thewhiskyexchange.com"
_SIZE_IN_META = re.compile(r"^\s*([\d.]+\s*(?:cl|ml|l))\b", re.I)


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
    category_url = f"{BASE}/c/40/gin"

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
            brand=name.split(" ")[0] if name else None,
            price_gbp=price,
            size_raw=size_raw,
            abv_percent=extract_abv(meta),
        )
        product.detail_text = meta
        for field in ("name", "brand", "price_gbp", "size_raw", "abv_percent"):
            if getattr(product, field) is not None:
                product.field_sources[field] = "css"
        # The listing card does not show a struck-through price. Do not guess one.
        product.field_sources["price_was"] = "missing"
        return product
