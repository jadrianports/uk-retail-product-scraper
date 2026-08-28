import csv
import json
import logging
from pathlib import Path

from scraper.models import COLUMNS, Product

log = logging.getLogger(__name__)

MIN_PARSE_RATE = 0.8


def write_outputs(products: list[Product], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [p.to_row() for p in products]

    with (out_dir / "products.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})

    with (out_dir / "products.json").open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, ensure_ascii=False)


def check_parse_rate(parsed: int, expected: int) -> bool:
    """Report whether enough products parsed. A quiet partial result is a fault."""
    if expected <= 0:
        log.error("No products were found on the category page.")
        return False
    rate = parsed / expected
    if rate < MIN_PARSE_RATE:
        log.error(
            "Only %s of %s products parsed (%.0f%%). The minimum is %.0f%%.",
            parsed, expected, rate * 100, MIN_PARSE_RATE * 100,
        )
        return False
    return True
