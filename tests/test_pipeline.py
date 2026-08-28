from scraper.llm import Derived
from scraper.models import Product
from scraper.pipeline import enrich_product


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


def test_adapter_set_provenance_survives_the_regex_pass():
    # The Whisky Exchange sets abv_percent from the listing card and tags
    # the source "css". detail_text holds the same figure, so the regex
    # would derive it again. The adapter's source must not be overwritten.
    product = _product(abv_percent=40.0, country_of_origin="England", flavour_style="Juniper led")
    product.field_sources["abv_percent"] = "css"
    product.detail_text = "Alcohol By Volume 40.0"
    enricher = _Enricher()
    enrich_product(product, enricher)
    assert product.abv_percent == 40.0
    assert product.field_sources["abv_percent"] == "css"
    assert enricher.calls == 0


def test_adapter_set_size_ml_survives_the_regex_pass():
    # An adapter can set size_ml itself before enrich_product runs. detail_text
    # holds a size too, so the regex would derive it again. The adapter's
    # value and its source tag must not be overwritten.
    product = _product(abv_percent=40.0, country_of_origin="England", flavour_style="Juniper led")
    product.size_ml = 500.0
    product.field_sources["size_ml"] = "css"
    product.detail_text = "70cl bottle, Alcohol By Volume 40.0"
    enricher = _Enricher()
    enrich_product(product, enricher)
    assert product.size_ml == 500.0
    assert product.field_sources["size_ml"] == "css"


def test_pack_type_missing_is_tagged_even_on_the_early_return_path():
    # abv, origin and flavour are all already filled, so enrich_product
    # returns before the model step. pack_type must still get a source.
    product = _product(abv_percent=40.0, country_of_origin="England", flavour_style="Juniper led")
    product.detail_text = "Alcohol By Volume 40.0"
    enricher = _Enricher()
    enrich_product(product, enricher)
    assert product.pack_type is None
    assert product.field_sources["pack_type"] == "missing"
    assert enricher.calls == 0
