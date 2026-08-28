import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from scraper import retailers  # noqa: F401  registers the adapters
from scraper.export import check_parse_rate, write_outputs
from scraper.fetch import Fetcher, RobotsDenied
from scraper.llm import GeminiEnricher, build_client
from scraper.pipeline import enrich_product
from scraper.retailers.base import REGISTRY, get_retailer

log = logging.getLogger("scraper")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Capture product attributes from a UK retailer.")
    parser.add_argument("--retailer", default="morrisons", choices=sorted(REGISTRY))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--no-llm", action="store_true", help="Skip the model step.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    site = get_retailer(args.retailer)
    fetcher = Fetcher(contact=os.environ.get("SCRAPER_CONTACT", ""))
    enricher = GeminiEnricher(client=None if args.no_llm else build_client())

    try:
        collected, expected = site.collect(fetcher, args.limit)
    except RobotsDenied as exc:
        log.error("%s", exc)
        return 2

    products = []
    for index, product in enumerate(collected, start=1):
        try:
            enrich_product(product, enricher)
        except Exception as exc:
            log.warning("Cannot enrich product %s of %s (%s): %s", index, expected, product.name, exc)
            continue
        products.append(product)
        log.info("%s/%s %s", index, expected, product.name)

    write_outputs(products, args.out)
    log.info("Wrote %s products to %s", len(products), args.out)

    if not check_parse_rate(parsed=len(products), expected=expected):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
