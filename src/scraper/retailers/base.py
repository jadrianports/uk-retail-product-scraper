from typing import Protocol

from scraper.models import Product


class Retailer(Protocol):
    name: str
    category: str
    category_url: str

    def find_product_urls(self, listing_html: str) -> list[str]: ...

    def parse_product(self, html: str, url: str) -> Product: ...


REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    REGISTRY[cls.name] = cls
    return cls


def get_retailer(name: str) -> Retailer:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"Unknown retailer '{name}'. Known retailers: {known}")
    return REGISTRY[name]()
