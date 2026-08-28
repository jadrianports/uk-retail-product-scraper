import csv
import json

from scraper.export import check_parse_rate, write_outputs
from scraper.models import COLUMNS, Product


def _product(name=None):
    return Product(
        retailer="morrisons",
        category="gin",
        product_url="https://example.test/products/x/1",
        scraped_at="2026-08-28T12:00:00Z",
        name=name,
    )


def test_write_outputs_uses_the_column_contract(tmp_path):
    write_outputs([_product("Test Gin")], tmp_path)

    with (tmp_path / "products.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == COLUMNS

    data = json.loads((tmp_path / "products.json").read_text("utf-8"))
    assert list(data[0]) == COLUMNS
    assert data[0]["brand"] is None


def test_missing_values_are_empty_cells(tmp_path):
    write_outputs([_product()], tmp_path)
    with (tmp_path / "products.csv").open(encoding="utf-8", newline="") as handle:
        row = list(csv.DictReader(handle))[0]
    assert row["name"] == ""


def test_parse_rate_gate():
    assert check_parse_rate(parsed=20, expected=25) is True
    assert check_parse_rate(parsed=19, expected=25) is False
    assert check_parse_rate(parsed=0, expected=0) is False
