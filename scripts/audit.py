"""Audit a dataset for wrong values that still look right.

The test suite proves the parsers do what they were told. It cannot prove the
result means what the column says, because a fixture agrees with the code that
made it. These checks run against real output instead.

    uv run python scripts/audit.py            # the committed datasets
    uv run python scripts/audit.py out/try1   # any run

Exits 1 if anything is found.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# A row labelled one category must not be named as another. The tool once
# collected single malt scotch whisky from a path that redirected, and
# labelled all of it gin.
OTHER_CATEGORY = {
    "gin": ["whisky", "whiskey", "vodka", "rum", "brandy", "tequila", "cognac"],
    "vodka": ["whisky", "whiskey", "gin", "rum", "brandy", "tequila", "cognac"],
    "whisky": ["vodka", "gin", "rum", "brandy", "tequila"],
    "rum": ["whisky", "whiskey", "vodka", "gin", "brandy", "tequila"],
    "brandy": ["whisky", "whiskey", "vodka", "gin", "rum", "tequila"],
    "tequila": ["whisky", "whiskey", "vodka", "gin", "rum", "brandy"],
}

# Bounds wide enough that a real product never trips them. A hit is a defect,
# not an unusual product.
ABV_RANGE = (0.0, 80.0)
SIZE_ML_RANGE = (20.0, 4500.0)
PRICE_PER_LITRE_RANGE = (1.0, 400.0)
MAX_LABEL_WORDS = 4


def brand_key(value: str | None) -> str:
    """Reduce a brand to letters and digits, so Fever-Tree meets Fever Tree."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


# A note is true of the retailer's own data, so it is not a parse defect. It
# is something a reader of the dataset has to handle. A finding is a defect.
NOTE_KINDS = {"BRAND_SPELLING"}


def check_rows(rows: list[dict]) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []

    def report(kind: str, detail: str) -> None:
        findings.append((kind, detail))

    for row in rows:
        name = (row.get("name") or "").strip()
        lowered = name.lower()
        sources = json.loads(row.get("field_sources") or "{}")

        for word in OTHER_CATEGORY.get(row.get("category", ""), []):
            if re.search(rf"\b{word}\b", lowered):
                report("CATEGORY", f"{name!r} is labelled {row['category']} and names {word}")

        abv = row.get("abv_percent")
        if abv is not None and not ABV_RANGE[0] <= float(abv) <= ABV_RANGE[1]:
            report("ABV", f"{name!r} abv_percent={abv}")

        size_ml = row.get("size_ml")
        if size_ml is not None and not SIZE_ML_RANGE[0] <= float(size_ml) <= SIZE_ML_RANGE[1]:
            report("SIZE", f"{name!r} size_ml={size_ml}")

        price = row.get("price_gbp")
        per_litre = row.get("price_per_litre")
        if per_litre is not None:
            if not PRICE_PER_LITRE_RANGE[0] <= float(per_litre) <= PRICE_PER_LITRE_RANGE[1]:
                report("PRICE_PER_LITRE", f"{name!r} price_per_litre={per_litre}")
            # Recompute the derived column from its inputs. This catches a
            # value that was correct when written and is now stale.
            if price is not None and size_ml:
                expected = round(float(price) / (float(size_ml) / 1000.0), 2)
                if abs(expected - float(per_litre)) > 0.01:
                    report("DERIVED", f"{name!r} price_per_litre={per_litre}, expected {expected}")

        # A label runs into the next label in real page text, so an
        # over-captured value is long. "United Kingdom Brand J" was one.
        for field in ("country_of_origin", "pack_type"):
            value = row.get(field)
            if value and len(str(value).split()) > MAX_LABEL_WORDS:
                report("OVER_CAPTURE", f"{name!r} {field}={value!r}")

        # A brand the retailer published is authoritative even when it differs
        # from the name. A brand this tool read out of the name is not, so
        # only that case is suspicious.
        brand = row.get("brand")
        if brand and sources.get("brand") != "jsonld" and brand.lower() not in lowered:
            report("BRAND", f"{name!r} has a derived brand {brand!r} that is not in the name")

        was = row.get("price_was")
        if was is not None and price is not None and float(was) <= float(price):
            report("PROMOTION", f"{name!r} price_was={was} is not above price_gbp={price}")

    skus = [r.get("sku") for r in rows if r.get("sku")]
    for sku in {s for s in skus if skus.count(s) > 1}:
        report("DUPLICATE", f"sku {sku} appears {skus.count(sku)} times")

    # Two spellings of one brand inflate a count of distinct brands.
    by_key: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("brand"):
            by_key[brand_key(row["brand"])].add(row["brand"])
    for spellings in by_key.values():
        if len(spellings) > 1:
            report("BRAND_SPELLING", f"one brand, {len(spellings)} spellings: {sorted(spellings)}")

    return findings


def main(root: Path) -> int:
    paths = sorted(root.glob("**/products.json"))
    if not paths:
        print(f"No products.json was found under {root}.")
        return 1

    total = 0
    defects: list[tuple[str, str, str]] = []
    notes: list[tuple[str, str, str]] = []
    for path in paths:
        rows = json.loads(path.read_text(encoding="utf-8"))
        total += len(rows)
        label = f"{rows[0].get('retailer')}/{rows[0].get('category')}" if rows else str(path)
        for kind, detail in check_rows(rows):
            target = notes if kind in NOTE_KINDS else defects
            target.append((label, kind, detail))
        print(f"{label:28} {len(rows):>3} rows")

    print(f"\n{total} rows across {len(paths)} datasets.")
    for heading, items in (("Notes", notes), ("Defects", defects)):
        if items:
            print(f"\n{heading}:")
            for label, kind, detail in items:
                print(f"  [{kind:15}] {label:24} {detail}")
    if defects:
        return 1
    print("\nNo defects.")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")))
