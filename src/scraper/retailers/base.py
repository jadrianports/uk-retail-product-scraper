from typing import Protocol

from scraper.models import Product


class Retailer(Protocol):
    name: str
    category: str
    category_url: str

    def find_product_urls(self, listing_html: str) -> list[str]: ...

    def parse_product(self, html: str, url: str) -> Product: ...

    def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
        """Gather this retailer's own products. Each adapter picks its own route.

        Return the parsed products and the expected count (the number of
        products the listing offered, capped at limit). A RobotsDenied
        error must pass through, not be caught here.
        """
        ...


REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    REGISTRY[cls.name] = cls
    return cls


def get_retailer(name: str) -> Retailer:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"Unknown retailer '{name}'. Known retailers: {known}")
    return REGISTRY[name]()
