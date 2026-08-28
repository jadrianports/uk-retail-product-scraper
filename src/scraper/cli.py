import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from scraper import retailers  # noqa: F401  registers the adapters
from scraper.enrich import enrich_product
from scraper.export import check_parse_rate, write_outputs
from scraper.fetch import Fetcher, RobotsDenied
from scraper.llm import GeminiEnricher, build_client
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
        listing = fetcher.get(site.category_url)
    except RobotsDenied as exc:
        log.error("%s", exc)
        return 2

    # The Whisky Exchange lists every hard attribute on the listing page
    # itself. Its detail page holds no product card for itself, so a
    # per-URL fetch loop returns null names there. Parse the listing
    # straight through instead, and skip the per-product fetch entirely.
    if hasattr(site, "parse_listing"):
        try:
            products_raw = site.parse_listing(listing)[: args.limit]
        except Exception as exc:
            log.warning("Cannot read the listing page at %s: %s", site.name, exc)
            products_raw = []
        expected = len(products_raw)
        log.info("Found %s products on the listing page at %s", expected, site.name)

        products = []
        for index, product in enumerate(products_raw, start=1):
            if product.name is None:
                log.warning("No name found for product %s of %s. The page layout may have changed.", index, expected)
                continue
            try:
                enrich_product(product, enricher)
            except Exception as exc:
                log.warning("Cannot enrich product %s of %s (%s): %s", index, expected, product.name, exc)
                continue
            products.append(product)
            log.info("%s/%s %s", index, expected, product.name)
    else:
        urls = site.find_product_urls(listing)[: args.limit]
        expected = len(urls)
        log.info("Found %s product pages at %s", expected, site.name)

        products = []
        for index, url in enumerate(urls, start=1):
            try:
                product = site.parse_product(fetcher.get(url), url)
            except RobotsDenied as exc:
                log.error("%s", exc)
                return 2
            except Exception as exc:
                log.warning("Cannot read product %s of %s at %s: %s", index, expected, url, exc)
                continue

            if product.name is None:
                log.warning("No name found at %s. The page layout may have changed.", url)
                continue

            enrich_product(product, enricher)
            products.append(product)
            log.info("%s/%s %s", index, expected, product.name)

    write_outputs(products, args.out)
    log.info("Wrote %s products to %s", len(products), args.out)

    if not check_parse_rate(parsed=len(products), expected=expected):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
