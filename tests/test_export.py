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


def test_combine_joins_every_retailer_into_one_file(tmp_path):
    from scraper.export import COLUMNS, combine_datasets, write_outputs
    from scraper.models import Product

    def row(retailer, category, name):
        return Product(
            retailer=retailer,
            category=category,
            product_url=f"https://example.test/{name}",
            scraped_at="2026-08-29T00:00:00Z",
            name=name,
        )

    write_outputs([row("morrisons", "gin", "A Gin")], tmp_path / "morrisons" / "gin")
    write_outputs([row("morrisons", "vodka", "A Vodka")], tmp_path / "morrisons" / "vodka")
    write_outputs([row("whisky_exchange", "gin", "B Gin")], tmp_path / "whisky_exchange" / "gin")

    assert combine_datasets(tmp_path) == 3

    import csv

    with (tmp_path / "all_products.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    # One schema for every retailer is what makes the files concatenate.
    assert list(rows[0]) == COLUMNS
    assert {r["retailer"] for r in rows} == {"morrisons", "whisky_exchange"}
    assert {r["category"] for r in rows} == {"gin", "vodka"}


def test_combine_reports_an_empty_data_directory(tmp_path):
    from scraper.export import combine_datasets

    # Nothing to join is a fault worth reporting, not a silent empty file.
    assert combine_datasets(tmp_path) == 0
    assert not (tmp_path / "all_products.csv").exists()


def _sample_rows(count):
    from scraper.models import Product

    return [
        Product(
            retailer="morrisons",
            category="gin",
            product_url=f"https://example.test/{i}",
            scraped_at="2026-08-29T00:00:00Z",
            name=f"Gin {i}",
        )
        for i in range(count)
    ]


def test_a_shorter_run_warns_before_it_replaces_a_longer_dataset(tmp_path, caplog):
    import logging

    from scraper.export import write_outputs

    write_outputs(_sample_rows(25), tmp_path)
    with caplog.at_level(logging.WARNING):
        write_outputs(_sample_rows(3), tmp_path)

    # A --limit run parses everything it asked for, so the parse gate passes
    # and cannot catch this. Without the warning the loss is silent.
    assert "replaces 25 rows with 3" in caplog.text


def test_a_longer_run_writes_without_a_warning(tmp_path, caplog):
    import logging

    from scraper.export import write_outputs

    write_outputs(_sample_rows(1), tmp_path)
    with caplog.at_level(logging.WARNING):
        write_outputs(_sample_rows(2), tmp_path)

    assert "replaces" not in caplog.text
