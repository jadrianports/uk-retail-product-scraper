from scraper.enrich import enrich_product
from scraper.llm import Derived
from scraper.models import Product


class _Enricher:
    def __init__(self, derived=None):
        self.derived = derived or Derived()
        self.calls = 0

    def derive(self, name, text):
        self.calls += 1
        return self.derived


def _product(**kwargs):
    return Product(
        retailer="morrisons",
        category="gin",
        product_url="https://example.test/products/x/1",
        scraped_at="2026-08-28T12:00:00Z",
        name="Test Gin",
        size_raw="70cl",
        **kwargs,
    )


def test_regex_wins_and_is_marked():
    product = _product()
    product.detail_text = "Package Type Glass Bottle Alcohol By Volume 40.3"
    enrich_product(product, _Enricher(Derived(flavour_style="Juniper led")))
    assert product.abv_percent == 40.3
    assert product.field_sources["abv_percent"] == "regex"
    assert product.size_ml == 700.0
    assert product.pack_type == "Glass Bottle"


def test_model_fills_only_the_gap():
    product = _product()
    product.detail_text = "No strength is stated."
    enricher = _Enricher(Derived(flavour_style="Floral", abv_percent=41.0))
    enrich_product(product, enricher)
    assert enricher.calls == 1
    assert product.abv_percent == 41.0
    assert product.field_sources["abv_percent"] == "llm"
    assert product.field_sources["flavour_style"] == "llm"


def test_absent_value_is_marked_missing():
    product = _product()
    product.detail_text = "No strength is stated."
    enrich_product(product, _Enricher(Derived()))
    assert product.abv_percent is None
    assert product.field_sources["abv_percent"] == "missing"
