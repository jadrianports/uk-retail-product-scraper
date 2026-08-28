from pathlib import Path

from scraper.retailers.morrisons import Morrisons

FIXTURES = Path(__file__).parent / "fixtures"
PRODUCT_URL = "https://groceries.morrisons.com/products/ableforth-s-bathtub-gin/113183042"


def test_find_product_urls_is_absolute_and_unique():
    html = (FIXTURES / "morrisons_listing.html").read_text("utf-8")
    urls = Morrisons().find_product_urls(html)
    assert urls == [
        PRODUCT_URL,
        "https://groceries.morrisons.com/products/aviation-american-gin/111765786",
    ]


def test_parse_product_reads_the_json_ld():
    html = (FIXTURES / "morrisons_product.html").read_text("utf-8")
    product = Morrisons().parse_product(html, PRODUCT_URL)
    assert product.name == "Ableforth's Bathtub Gin"
    assert product.brand == "Ableforth's"
    assert product.price_gbp == 20.00
    assert product.size_raw == "70cl"
    assert product.sku == "113183042"
    assert product.availability == "InStock"
    assert product.field_sources["name"] == "jsonld"


def test_strikethrough_price_is_read_as_price_was():
    html = (FIXTURES / "morrisons_product.html").read_text("utf-8")
    product = Morrisons().parse_product(html, PRODUCT_URL)
    assert product.price_was == 30.50
    assert product.is_on_promotion is True
    assert product.field_sources["price_was"] == "css"
    assert product.field_sources["is_on_promotion"] == "css"


def test_strikethrough_unit_price_is_not_mistaken_for_price_was():
    html = """<html><head>
    <script type="application/ld+json">
    {"@type":"Product","offers":{"price":"20.00"}}
    </script></head><body>
    <span class="_text--strikethrough_x">(&pound;43.57/litre)</span>
    </body></html>"""
    product = Morrisons().parse_product(html, PRODUCT_URL)
    assert product.price_was is None
    assert product.is_on_promotion is False
    assert product.field_sources["price_was"] == "missing"


def test_no_strikethrough_gives_no_promotion():
    html = """<html><head>
    <script type="application/ld+json">
    {"@type":"Product","offers":{"price":"20.00"}}
    </script></head><body>
    <div>Nothing struck through here.</div>
    </body></html>"""
    product = Morrisons().parse_product(html, PRODUCT_URL)
    assert product.price_was is None
    assert product.is_on_promotion is False
    assert product.field_sources["price_was"] == "missing"


def test_detail_text_excludes_script_content():
    html = (FIXTURES / "morrisons_product.html").read_text("utf-8")
    product = Morrisons().parse_product(html, PRODUCT_URL)
    # The translation blob holds the words "Country of origin". It must not leak
    # into the text that the regex extractors read.
    assert "countryOfOrigin" not in product.detail_text
    assert "Alcohol By Volume 40.3" in product.detail_text


def test_missing_json_ld_gives_nulls_and_does_not_raise():
    product = Morrisons().parse_product("<html><body>nothing</body></html>", PRODUCT_URL)
    assert product.name is None
    assert product.price_gbp is None
