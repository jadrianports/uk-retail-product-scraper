import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from scraper import retailers  # noqa: F401  registers the adapters
from scraper.export import check_parse_rate, combine_datasets, write_outputs
from scraper.fetch import ChallengeBlocked, Fetcher, RobotsDenied
from scraper.llm import NullEnricher, build_client, build_enricher  # noqa: F401
from scraper.pipeline import enrich_product
from scraper.retailers.base import REGISTRY, categories_for, get_retailer

log = logging.getLogger("scraper")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture product attributes from a UK retailer.")
    parser.add_argument("--retailer", default="morrisons", choices=sorted(REGISTRY))
    parser.add_argument(
        "--category",
        default=None,
        help="A category the retailer supports. Use --list-categories to see them.",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="Print the categories each retailer supports, then stop.",
    )
    parser.add_argument(
        "--combine",
        action="store_true",
        help="Join every dataset under data/ into one CSV, then stop.",
    )
    parser.add_argument("--limit", type=int, default=25)
    # No fixed default here. An explicit --out must win as-is; with no flag,
    # the default depends on --retailer and --category, so it is filled in
    # after parsing.
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-llm", action="store_true", help="Skip the model step.")
    args = parser.parse_args()
    if args.out is None:
        # One folder per category. Two categories must not overwrite one file.
        category = args.category or getattr(REGISTRY[args.retailer], "DEFAULT_CATEGORY", "")
        args.out = Path("data") / args.retailer / category
    return args


def main() -> int:
    load_dotenv()
    args = parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.combine:
        return 0 if combine_datasets(Path("data")) else 1

    if args.list_categories:
        for name in sorted(REGISTRY):
            print(f"{name}: {', '.join(categories_for(name))}")
        return 0

    try:
        site = get_retailer(args.retailer, args.category)
    except KeyError as exc:
        log.error("%s", exc)
        return 1
    fetcher = Fetcher(contact=os.environ.get("SCRAPER_CONTACT", ""))

    if args.no_llm:
        enricher = NullEnricher()
    else:
        try:
            enricher = build_enricher()
        except Exception as exc:
            log.error("Cannot build the model client: %s", exc)
            return 1

    try:
        collected, expected = site.collect(fetcher, args.limit)
    except RobotsDenied as exc:
        log.error("%s", exc)
        return 2
    except ChallengeBlocked as exc:
        log.error("%s", exc)
        return 3
    except Exception as exc:
        log.error("Cannot collect %s: %s", args.retailer, exc)
        return 1

    products = []
    for index, product in enumerate(collected, start=1):
        try:
            enrich_product(product, enricher)
        except Exception as exc:
            log.warning("Cannot enrich product %s of %s (%s): %s", index, expected, product.name, exc)
            continue
        products.append(product)
        log.info("%s/%s %s", index, expected, product.name)

    # Check before the write. A short run must not overwrite a good
    # dataset with a shorter one. The previous file stays untouched.
    if not check_parse_rate(parsed=len(products), expected=expected):
        log.error("The dataset in %s was left unchanged.", args.out)
        return 1

    try:
        write_outputs(products, args.out)
    except Exception as exc:
        log.error("Cannot write output to %s: %s", args.out, exc)
        return 1
    log.info("Wrote %s products to %s", len(products), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
