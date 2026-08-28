import json

import pytest

from scraper import cli
from scraper.fetch import RobotsDenied
from scraper.llm import Derived
from scraper.models import Product
from scraper.retailers.base import REGISTRY, register


@pytest.fixture(autouse=True)
def preserve_registry():
    """Snapshot and restore REGISTRY to prevent test leakage between adapters."""
    original = REGISTRY.copy()
    yield
    REGISTRY.clear()
    REGISTRY.update(original)


class _NullEnricher:
    """Stands in for GeminiEnricher. No network, no API key needed."""

    def derive(self, name, text):
        return Derived()


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch):
    # enrich_product must never need the network for this test file.
    monkeypatch.setattr(cli, "GeminiEnricher", lambda client=None: _NullEnricher())
    monkeypatch.setattr(cli, "build_client", lambda: None)


class _FakeFetcher:
    """Replaces Fetcher. Records every URL it was asked for."""

    def __init__(self, pages, contact=""):
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str) -> str:
        self.requested.append(url)
        if url not in self.pages:
            raise AssertionError(f"Unexpected fetch of {url}")
        return self.pages[url]


def _install_fake_fetcher(monkeypatch, pages):
    fetcher = _FakeFetcher(pages)
    monkeypatch.setattr(cli, "Fetcher", lambda contact="": fetcher)
    return fetcher


@register
class _ListingRetailer:
    """Mimics The Whisky Exchange: the listing page holds every field."""

    name = "fake_listing"
    category = "gin"
    category_url = "https://listing.example.test/category"

    def find_product_urls(self, listing_html: str) -> list[str]:
        raise AssertionError("the listing path must not call find_product_urls")

    def parse_listing(self, listing_html: str) -> list[Product]:
        return [
            Product(
                retailer=self.name,
                category=self.category,
                product_url=f"https://listing.example.test/p/{i}",
                scraped_at="2026-08-28T12:00:00Z",
                name=f"Gin {i}",
                size_raw="70cl",
            )
            for i in range(1, 4)
        ]

    def parse_product(self, html: str, url: str) -> Product:
        raise AssertionError("the listing path must not fetch or parse per-product pages")


@register
class _PerUrlRetailer:
    """Mimics Morrisons: one request per product page."""

    name = "fake_perurl"
    category = "gin"
    category_url = "https://perurl.example.test/category"

    def find_product_urls(self, listing_html: str) -> list[str]:
        return [f"https://perurl.example.test/p/{i}" for i in range(1, 4)]

    def parse_product(self, html: str, url: str) -> Product:
        return Product(
            retailer=self.name,
            category=self.category,
            product_url=url,
            scraped_at="2026-08-28T12:00:00Z",
            name=f"Product at {url}",
            size_raw="70cl",
        )


def test_listing_path_skips_per_product_fetch(monkeypatch, tmp_path):
    pages = {"https://listing.example.test/category": "<html></html>"}
    fetcher = _install_fake_fetcher(monkeypatch, pages)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_listing", "--limit", "25", "--out", str(tmp_path), "--no-llm"],
    )

    exit_code = cli.main()

    assert exit_code == 0
    assert fetcher.requested == ["https://listing.example.test/category"]
    data = json.loads((tmp_path / "products.json").read_text("utf-8"))
    assert len(data) == 3
    assert data[0]["field_sources"]


def test_listing_path_honours_limit(monkeypatch, tmp_path):
    pages = {"https://listing.example.test/category": "<html></html>"}
    _install_fake_fetcher(monkeypatch, pages)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_listing", "--limit", "2", "--out", str(tmp_path), "--no-llm"],
    )

    exit_code = cli.main()

    assert exit_code == 0
    data = json.loads((tmp_path / "products.json").read_text("utf-8"))
    assert len(data) == 2


def test_per_url_path_fetches_each_product(monkeypatch, tmp_path):
    pages = {
        "https://perurl.example.test/category": "<html></html>",
        "https://perurl.example.test/p/1": "<html></html>",
        "https://perurl.example.test/p/2": "<html></html>",
        "https://perurl.example.test/p/3": "<html></html>",
    }
    fetcher = _install_fake_fetcher(monkeypatch, pages)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_perurl", "--limit", "25", "--out", str(tmp_path), "--no-llm"],
    )

    exit_code = cli.main()

    assert exit_code == 0
    assert fetcher.requested == [
        "https://perurl.example.test/category",
        "https://perurl.example.test/p/1",
        "https://perurl.example.test/p/2",
        "https://perurl.example.test/p/3",
    ]
    data = json.loads((tmp_path / "products.json").read_text("utf-8"))
    assert len(data) == 3


def test_exits_1_when_parse_gate_fails(monkeypatch, tmp_path):
    @register
    class _MostlyEmptyRetailer:
        name = "fake_gate_fail"
        category = "gin"
        category_url = "https://gate.example.test/category"

        def find_product_urls(self, listing_html: str) -> list[str]:
            return [f"https://gate.example.test/p/{i}" for i in range(1, 6)]

        def parse_product(self, html: str, url: str) -> Product:
            # Only the first product has a name. The rest fail the parse gate.
            name = "Only One" if url.endswith("/p/1") else None
            return Product(
                retailer=self.name,
                category=self.category,
                product_url=url,
                scraped_at="2026-08-28T12:00:00Z",
                name=name,
            )

    pages = {"https://gate.example.test/category": "<html></html>"}
    for i in range(1, 6):
        pages[f"https://gate.example.test/p/{i}"] = "<html></html>"
    _install_fake_fetcher(monkeypatch, pages)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_gate_fail", "--limit", "25", "--out", str(tmp_path), "--no-llm"],
    )

    exit_code = cli.main()

    assert exit_code == 1


def test_exits_2_when_robots_denied(monkeypatch, tmp_path):
    class _DenyingFetcher:
        def __init__(self, contact=""):
            pass

        def get(self, url: str) -> str:
            raise RobotsDenied(f"robots.txt denies {url}")

    monkeypatch.setattr(cli, "Fetcher", _DenyingFetcher)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_listing", "--limit", "25", "--out", str(tmp_path), "--no-llm"],
    )

    exit_code = cli.main()

    assert exit_code == 2


def test_runs_with_no_api_key_present(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    pages = {"https://listing.example.test/category": "<html></html>"}
    _install_fake_fetcher(monkeypatch, pages)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_listing", "--limit", "25", "--out", str(tmp_path)],
    )

    exit_code = cli.main()

    assert exit_code == 0
