import json
from scraper.models import COLUMNS, Product


def test_product_allows_missing_attributes():
    p = Product(
        retailer="morrisons",
        category="gin",
        product_url="https://example.test/products/x/1",
        scraped_at="2026-08-28T12:00:00Z",
    )
    assert p.name is None
    assert p.abv_percent is None
    assert p.field_sources == {}


def test_row_matches_column_contract():
    p = Product(
        retailer="morrisons",
        category="gin",
        product_url="https://example.test/products/x/1",
        scraped_at="2026-08-28T12:00:00Z",
        name="Test Gin",
        field_sources={"name": "jsonld"},
    )
    row = p.to_row()
    assert list(row.keys()) == COLUMNS
    assert json.loads(row["field_sources"]) == {"name": "jsonld"}
