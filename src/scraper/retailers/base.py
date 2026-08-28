from typing import Protocol

from scraper.models import Product


class Retailer(Protocol):
    name: str
    category: str
    category_url: str

    def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
        """Gather this retailer's own products. Each adapter picks its own route.

        This is the contract the CLI uses. Each adapter reaches its products
        by a different method, so the interface promises the result and not
        the route. Each implementation owns find_product_urls and parse_product
        as its own internal strategy.

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
