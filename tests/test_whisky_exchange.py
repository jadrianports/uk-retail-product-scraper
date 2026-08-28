from pathlib import Path

import pytest

from scraper.retailers.whisky_exchange import WhiskyExchange, brand_from_name

FIXTURES = Path(__file__).parent / "fixtures"


def _cards():
    html = (FIXTURES / "twe_listing.html").read_text("utf-8")
    return html, WhiskyExchange()


def test_find_product_urls():
    html, site = _cards()
    assert site.find_product_urls(html) == [
        "https://www.thewhiskyexchange.com/p/43556/lagavulin-12-year-old",
        "https://www.thewhiskyexchange.com/p/12345/sipsmith-london-dry-gin",
    ]


def test_parse_products_from_the_listing():
    html, site = _cards()
    products = site.parse_listing(html)
    first = products[0]
    assert first.name == "Lagavulin 12 Year Old Special Releases 2018"
    assert first.price_gbp == 199.0
    assert first.size_raw == "70cl"
    assert first.abv_percent == 57.8
    assert first.field_sources["name"] == "css"
    assert products[1].price_gbp == 1299.50


def test_category_url_points_to_gin_category():
    site = WhiskyExchange()
    assert site.category_url.endswith("/c/338/gin")


@pytest.mark.parametrize(
    "name, expected",
    [
        ("The Botanist Islay Dry Gin", "The Botanist"),
        ("Gin Mare Capri Mediterranean Gin", "Gin Mare"),
        ("Gin Del Professore Monsieur", "Gin Del Professore Monsieur"),
        ("Ki No Bi Kyoto Dry Gin", "Ki No Bi"),
        ("Isle of Harris Gin", "Isle of Harris"),
        ("Papa Salt Coastal Gin", "Papa Salt"),
        ("Monkey 47 Schwarzwald Dry Gin", "Monkey 47"),
        ("Tanqueray London Dry Gin (41.3%)", "Tanqueray"),
        ("Hendrick's Gin", "Hendrick's"),
        ("Plymouth Gin", "Plymouth"),
        ("Fords London Dry Gin", "Fords"),
        ("Edinburgh Gin The Classic", "Edinburgh"),
        ("Xoriguer Gin Mahon", "Xoriguer"),
    ],
)
def test_brand_from_name(name, expected):
    assert brand_from_name(name) == expected
