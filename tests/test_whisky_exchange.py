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
        "https://www.thewhiskyexchange.com/p/55123/withers-g1-gin",
        "https://www.thewhiskyexchange.com/p/61234/tanqueray-no-ten-gin-litre",
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


def test_money_flash_gives_price_was_and_promotion():
    html, site = _cards()
    products = site.parse_listing(html)
    withers = next(p for p in products if p.name == "Withers G1 Gin")
    assert withers.price_gbp == 20.00
    assert withers.price_was == 25.00
    assert withers.is_on_promotion is True
    assert withers.field_sources["price_was"] == "css"
    assert withers.field_sources["is_on_promotion"] == "css"


def test_non_money_flash_gives_promotion_but_no_price_was():
    html, site = _cards()
    products = site.parse_listing(html)
    tanqueray = next(p for p in products if p.name == "Tanqueray No.Ten Gin Litre")
    assert tanqueray.is_on_promotion is True
    assert tanqueray.price_was is None
    assert tanqueray.field_sources["is_on_promotion"] == "css"
    assert tanqueray.field_sources["price_was"] == "missing"


def test_no_flash_gives_no_promotion_and_no_price_was():
    html, site = _cards()
    products = site.parse_listing(html)
    sipsmith = next(p for p in products if p.name == "Sipsmith London Dry Gin")
    assert sipsmith.is_on_promotion is False
    assert sipsmith.price_was is None
    assert sipsmith.field_sources["is_on_promotion"] == "missing"
    assert sipsmith.field_sources["price_was"] == "missing"


def test_button_present_gives_in_stock():
    html, site = _cards()
    products = site.parse_listing(html)
    lagavulin = next(p for p in products if p.name.startswith("Lagavulin"))
    assert lagavulin.availability == "InStock"
    assert lagavulin.field_sources["availability"] == "css"


def test_button_absent_gives_no_availability():
    html, site = _cards()
    products = site.parse_listing(html)
    sipsmith = next(p for p in products if p.name == "Sipsmith London Dry Gin")
    assert sipsmith.availability is None
    assert sipsmith.field_sources["availability"] == "missing"


def test_field_sources_carry_every_new_field_on_every_card():
    html, site = _cards()
    products = site.parse_listing(html)
    for product in products:
        for field in ("price_was", "is_on_promotion", "availability"):
            assert field in product.field_sources


def test_sku_extracted_from_product_url():
    html, site = _cards()
    products = site.parse_listing(html)
    lagavulin = next(p for p in products if p.name.startswith("Lagavulin"))
    assert lagavulin.sku == "43556"
    assert lagavulin.field_sources["sku"] == "css"


def test_sku_tagged_missing_when_url_does_not_match_pattern():
    site = WhiskyExchange()
    from bs4 import BeautifulSoup
    html = '<a href="/something-else" class="product-card"><p class="product-card__name">Test</p></a>'
    soup = BeautifulSoup(html, "lxml")
    card = soup.select_one("a.product-card")
    product = site._from_card(card, "https://www.thewhiskyexchange.com/something-else")
    assert product.sku is None
    assert product.field_sources["sku"] == "missing"


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


def _detail_html():
    return (FIXTURES / "twe_product.html").read_text("utf-8")


def _card(brand="Hendrick"):
    from scraper.models import Product

    return Product(
        retailer="whisky_exchange",
        category="gin",
        product_url="https://www.thewhiskyexchange.com/p/2261/hendricks-gin",
        scraped_at="2026-08-29T00:00:00Z",
        name="Hendrick's Gin",
        brand=brand,
        field_sources={"brand": "css"},
    )


def test_detail_page_replaces_the_brand_read_from_the_name():
    from scraper.retailers.whisky_exchange import WhiskyExchange

    product = _card(brand="Hendrick")
    WhiskyExchange().parse_detail(_detail_html(), product)

    # The retailer states the brand, so the guess from the name goes.
    assert product.brand == "Hendrick's"
    assert product.field_sources["brand"] == "jsonld"


def test_detail_page_fills_the_description():
    from scraper.retailers.whisky_exchange import WhiskyExchange

    product = _card()
    WhiskyExchange().parse_detail(_detail_html(), product)

    assert "pink-tinged gin" in product.description
    assert product.field_sources["description"] == "jsonld"
    # The extractors read detail_text, so it has to carry the prose too.
    assert "pink-tinged gin" in product.detail_text


def test_description_falls_back_to_the_page_when_there_is_no_json_ld():
    from scraper.retailers.whisky_exchange import WhiskyExchange

    html = _detail_html()
    start = html.index("<script type=")
    end = html.index("</script>") + len("</script>")
    product = _card()

    WhiskyExchange().parse_detail(html[:start] + html[end:], product)

    assert "pink-tinged gin" in product.description
    assert product.field_sources["description"] == "css"
    # No Product schema means no brand, so the listing value survives.
    assert product.brand == "Hendrick"


def test_a_failed_detail_page_keeps_the_listing_values():
    from scraper.retailers.base import REGISTRY
    from scraper.retailers.whisky_exchange import WhiskyExchange

    listing = (FIXTURES / "twe_listing.html").read_text("utf-8")
    site = WhiskyExchange()

    class _HalfBrokenFetcher:
        def get(self, url):
            if url == site.category_url:
                return listing
            raise RuntimeError("the detail page is unreachable")

    products, expected = site.collect(_HalfBrokenFetcher(), limit=3)

    # A detail page that fails must not drop the product.
    assert len(products) == expected > 0
    assert all(p.name for p in products)
    assert REGISTRY["whisky_exchange"] is WhiskyExchange


def test_detail_page_fills_the_country_from_the_facts_list():
    from scraper.retailers.whisky_exchange import WhiskyExchange

    product = _card()
    WhiskyExchange().parse_detail(_detail_html(), product)

    assert product.country_of_origin == "Scotland"
    assert product.field_sources["country_of_origin"] == "css"


def test_the_country_is_recorded_as_the_retailer_publishes_it():
    from scraper.retailers.whisky_exchange import WhiskyExchange

    # This site files some products under a blend rather than a country.
    # Recording it as published keeps the page and the row in agreement.
    html = _detail_html().replace(
        '<p class="product-facts__data">Scotland</p>',
        '<p class="product-facts__data">Caribbean Blend</p>',
    )
    product = _card()
    WhiskyExchange().parse_detail(html, product)

    assert product.country_of_origin == "Caribbean Blend"


def test_a_page_with_no_facts_list_leaves_the_country_null():
    from scraper.retailers.whisky_exchange import WhiskyExchange

    html = _detail_html()
    start = html.index('<ul class="product-facts">')
    end = html.index("</ul>") + len("</ul>")
    product = _card()

    WhiskyExchange().parse_detail(html[:start] + html[end:], product)

    assert product.country_of_origin is None
