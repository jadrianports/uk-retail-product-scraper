import pytest

from scraper.retailers.base import REGISTRY, register, get_retailer
from scraper.models import Product


# Dummy retailer for testing
@register
class DummyRetailer:
    name = "dummy"
    category = "test"
    category_url = "http://example.com"

    def find_product_urls(self, listing_html: str) -> list[str]:
        return []

    def parse_product(self, html: str, url: str) -> Product:
        return Product(
            retailer=self.name,
            category=self.category,
            product_url=url,
            scraped_at="2024-01-01",
        )


@pytest.fixture(autouse=True)
def preserve_registry():
    """Snapshot and restore REGISTRY to prevent test leakage."""
    original = REGISTRY.copy()
    yield
    REGISTRY.clear()
    REGISTRY.update(original)


def test_register_adds_class_to_registry():
    """Test that register puts a class in REGISTRY and get_retailer returns an instance."""
    assert "dummy" in REGISTRY
    retailer = get_retailer("dummy")
    assert isinstance(retailer, DummyRetailer)


def test_unknown_retailer_raises_key_error_with_known_names():
    """Test that get_retailer raises KeyError and lists known retailer names."""
    with pytest.raises(KeyError) as excinfo:
        get_retailer("nope")
    error_msg = str(excinfo.value)
    assert "dummy" in error_msg
    assert "Unknown retailer" in error_msg
