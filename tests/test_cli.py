import json

import pytest
import requests

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


@pytest.fixture
def no_model_calls(monkeypatch):
    # Belt-and-braces: every test that requests this fixture is guaranteed
    # no network call, even if it forgets --no-llm. Not autouse, because
    # test_runs_with_no_api_key_present must exercise the real build_client.
    monkeypatch.setattr(cli, "build_enricher", lambda *a, **k: _NullEnricher())
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

    def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
        fetcher.get(self.category_url)
        products = [
            Product(
                retailer=self.name,
                category=self.category,
                product_url=f"https://listing.example.test/p/{i}",
                scraped_at="2026-08-28T12:00:00Z",
                name=f"Gin {i}",
                size_raw="70cl",
            )
            for i in range(1, 4)
        ][:limit]
        return products, len(products)


@register
class _PerUrlRetailer:
    """Mimics Morrisons: one request per product page."""

    name = "fake_perurl"
    category = "gin"
    category_url = "https://perurl.example.test/category"

    def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
        fetcher.get(self.category_url)
        urls = [f"https://perurl.example.test/p/{i}" for i in range(1, 4)][:limit]
        products = []
        for url in urls:
            fetcher.get(url)
            products.append(
                Product(
                    retailer=self.name,
                    category=self.category,
                    product_url=url,
                    scraped_at="2026-08-28T12:00:00Z",
                    name=f"Product at {url}",
                    size_raw="70cl",
                )
            )
        return products, len(products)


def test_listing_path_skips_per_product_fetch(monkeypatch, tmp_path, no_model_calls):
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


def test_listing_path_honours_limit(monkeypatch, tmp_path, no_model_calls):
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


def test_per_url_path_fetches_each_product(monkeypatch, tmp_path, no_model_calls):
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


def test_exits_1_when_parse_gate_fails(monkeypatch, tmp_path, no_model_calls):
    @register
    class _MostlyEmptyRetailer:
        name = "fake_gate_fail"
        category = "gin"
        category_url = "https://gate.example.test/category"

        def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
            fetcher.get(self.category_url)
            urls = [f"https://gate.example.test/p/{i}" for i in range(1, 6)][:limit]
            expected = len(urls)
            products = []
            for url in urls:
                fetcher.get(url)
                # Only the first product has a name. The rest fail the parse gate.
                if not url.endswith("/p/1"):
                    continue
                products.append(
                    Product(
                        retailer=self.name,
                        category=self.category,
                        product_url=url,
                        scraped_at="2026-08-28T12:00:00Z",
                        name="Only One",
                    )
                )
            return products, expected

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


def test_exits_2_when_robots_denied(monkeypatch, tmp_path, no_model_calls):
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


def test_robots_denied_from_deep_inside_collect_still_exits_2(monkeypatch, tmp_path, no_model_calls):
    # The category fetch can succeed while a later per-item fetch is denied.
    # RobotsDenied must still escape collect() and reach the CLI, not just
    # in the simple case where the very first fetch is denied.
    @register
    class _DeniedPartwayRetailer:
        name = "fake_denied_partway"
        category = "gin"
        category_url = "https://partway.example.test/category"

        def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
            fetcher.get(self.category_url)
            fetcher.get("https://partway.example.test/p/1")
            return [], 0

    class _PartialDenyFetcher:
        def __init__(self, contact=""):
            pass

        def get(self, url: str) -> str:
            if url.endswith("/category"):
                return "<html></html>"
            raise RobotsDenied(f"robots.txt denies {url}")

    monkeypatch.setattr(cli, "Fetcher", _PartialDenyFetcher)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_denied_partway", "--limit", "25", "--out", str(tmp_path), "--no-llm"],
    )

    exit_code = cli.main()

    assert exit_code == 2


def test_exits_1_when_collect_raises_a_non_robots_exception(monkeypatch, tmp_path, no_model_calls, caplog):
    # This is the live failure that motivated the fix: The Whisky Exchange's
    # category page now returns 403 from a Cloudflare challenge, and
    # requests raises HTTPError out of collect(). That must not escape
    # main() as a traceback; it must degrade to the documented exit 1.
    @register
    class _HttpErrorRetailer:
        name = "fake_http_error"
        category = "gin"
        category_url = "https://error.example.test/category"

        def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
            fetcher.get(self.category_url)
            return [], 0

    class _FailingFetcher:
        def __init__(self, contact=""):
            pass

        def get(self, url: str) -> str:
            raise requests.exceptions.HTTPError(f"403 Client Error: Forbidden for url: {url}")

    monkeypatch.setattr(cli, "Fetcher", _FailingFetcher)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_http_error", "--limit", "25", "--out", str(tmp_path), "--no-llm"],
    )

    with caplog.at_level("ERROR"):
        exit_code = cli.main()

    assert exit_code == 1
    assert "fake_http_error" in caplog.text


def test_listing_path_survives_a_parse_listing_exception(monkeypatch, tmp_path, no_model_calls):
    @register
    class _BrokenListingRetailer:
        name = "fake_broken_listing"
        category = "gin"
        category_url = "https://broken.example.test/category"

        def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
            fetcher.get(self.category_url)
            try:
                raise ValueError("one malformed card broke the whole listing parse")
            except ValueError:
                # A retailer's own collect() must degrade to an empty result,
                # not let an internal parse error escape as a crash.
                return [], 0

    pages = {"https://broken.example.test/category": "<html></html>"}
    _install_fake_fetcher(monkeypatch, pages)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_broken_listing", "--limit", "25", "--out", str(tmp_path), "--no-llm"],
    )

    # A raise here must degrade to the documented parse-rate gate (exit 1),
    # not an unhandled traceback with an undocumented exit code.
    exit_code = cli.main()

    assert exit_code == 1


def test_a_failed_gate_leaves_the_previous_dataset_untouched(monkeypatch, tmp_path, no_model_calls):
    pages = {"https://listing.example.test/category": "<html></html>"}
    _install_fake_fetcher(monkeypatch, pages)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_listing", "--limit", "25", "--out", str(tmp_path), "--no-llm"],
    )

    real_enrich_product = cli.enrich_product

    def flaky_enrich_product(product, enricher):
        if product.name == "Gin 2":
            raise ValueError("this one card cannot be enriched")
        return real_enrich_product(product, enricher)

    monkeypatch.setattr(cli, "enrich_product", flaky_enrich_product)

    # A good dataset from an earlier run sits in the output folder.
    previous = json.dumps([{"name": "From an earlier run"}])
    (tmp_path / "products.json").write_text(previous, "utf-8")
    (tmp_path / "products.csv").write_text("name\nFrom an earlier run\n", "utf-8")

    exit_code = cli.main()

    # 2 of 3 products survive, below the 80% gate. One bad card does not
    # crash the run, and the gate stops the write, so the earlier dataset
    # survives intact. A short file that looks complete is the worse fault.
    assert exit_code == 1
    assert (tmp_path / "products.json").read_text("utf-8") == previous
    assert "From an earlier run" in (tmp_path / "products.csv").read_text("utf-8")


def test_unwritable_out_path_yields_exit_1_not_a_traceback(monkeypatch, tmp_path, no_model_calls):
    pages = {"https://listing.example.test/category": "<html></html>"}
    _install_fake_fetcher(monkeypatch, pages)
    # A plain file sits where --out expects a directory. write_outputs()
    # cannot mkdir over it, so this must degrade to exit 1, not a crash.
    blocked_out = tmp_path / "blocked"
    blocked_out.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_listing", "--limit", "25", "--out", str(blocked_out), "--no-llm"],
    )

    exit_code = cli.main()

    assert exit_code == 1


def test_build_client_returns_none_with_no_api_key_and_the_run_still_succeeds(monkeypatch, tmp_path):
    # Deliberately does NOT request no_model_calls. cli.build_client and
    # cli.GeminiEnricher run for real here, so this proves the no-key path
    # rather than a mock standing in for it.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # build_enricher reads three keys now. Clear them all, or a key in the
    # real environment sends this test to a live provider.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # main() calls load_dotenv() first. A real .env file next to the repo
    # would put the key straight back. Stop that reload so this test stays
    # on the no-key path it means to prove.
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    pages = {"https://listing.example.test/category": "<html></html>"}
    _install_fake_fetcher(monkeypatch, pages)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_listing", "--limit", "25", "--out", str(tmp_path)],
    )

    assert cli.build_client() is None

    exit_code = cli.main()

    assert exit_code == 0


@pytest.mark.parametrize("retailer", ["morrisons", "whisky_exchange"])
def test_default_out_path_nests_under_data_by_retailer_and_category(monkeypatch, retailer):
    # No --out flag given: the default must be data/<retailer>/<category>,
    # built from the adapter's own attributes, not a hard-coded string.
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", retailer, "--no-llm"],
    )
    args = cli.parse_args()
    assert args.out.parts[-3:] == ("data", retailer, "gin")


def test_a_second_category_writes_to_its_own_folder(monkeypatch):
    # Two categories must never share one file.
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "morrisons", "--category", "vodka", "--no-llm"],
    )
    args = cli.parse_args()
    assert args.out.parts[-3:] == ("data", "morrisons", "vodka")


def test_an_unknown_category_exits_1_and_names_the_known_ones(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        "sys.argv",
        # A category this retailer does not carry. It must be rejected before
        # any request is made, or the test suite goes to the network.
        ["scrape", "--retailer", "whisky_exchange", "--category", "tequila",
         "--out", str(tmp_path), "--no-llm"],
    )

    assert cli.main() == 1
    assert "gin" in caplog.text


def test_both_adapters_satisfy_the_collect_contract():
    # Substitutability check: Morrisons and WhiskyExchange behave under one
    # signature, so the CLI never needs to branch on which adapter it holds.
    from scraper.retailers.morrisons import Morrisons
    from scraper.retailers.whisky_exchange import WhiskyExchange

    class _FakeCollectFetcher:
        def __init__(self, pages):
            self.pages = pages

        def get(self, url: str) -> str:
            return self.pages.get(url, "<html></html>")

    for site in (Morrisons(), WhiskyExchange()):
        fetcher = _FakeCollectFetcher({site.category_url: "<html></html>"})
        result = site.collect(fetcher, 5)

        assert isinstance(result, tuple)
        assert len(result) == 2
        products, expected = result
        assert isinstance(products, list)
        assert isinstance(expected, int)


def test_exits_3_when_the_host_serves_a_challenge(monkeypatch, tmp_path, no_model_calls):
    # A challenge is not a refusal and not a rate limit. It gets its own
    # exit code, because the tool will not defeat one by design.
    from scraper.fetch import ChallengeBlocked

    class _ChallengingFetcher:
        def __init__(self, contact=""):
            pass

        def get(self, url: str) -> str:
            raise ChallengeBlocked(f"{url} served a JavaScript challenge")

    monkeypatch.setattr(cli, "Fetcher", _ChallengingFetcher)
    monkeypatch.setattr(
        "sys.argv",
        ["scrape", "--retailer", "fake_listing", "--out", str(tmp_path), "--no-llm"],
    )

    assert cli.main() == 3


def test_list_categories_names_every_retailer(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["scrape", "--list-categories"])

    assert cli.main() == 0

    out = capsys.readouterr().out
    assert "morrisons" in out and "vodka" in out
    # The Whisky Exchange lists only the category that was verified.
    assert "whisky_exchange: gin" in out
