import pytest

from scraper.fetch import Fetcher, RobotsGate

MORRISONS_ROBOTS = """
User-agent: *
Disallow: /sso-login
Disallow: /api/
Sitemap: https://groceries.morrisons.com/sitemaps/sitemap_index.xml
"""


def test_gate_allows_the_category_path():
    gate = RobotsGate.from_text("https://groceries.morrisons.com", MORRISONS_ROBOTS)
    assert gate.allows("https://groceries.morrisons.com/categories/gin/151526") is True


def test_gate_denies_the_api_path():
    gate = RobotsGate.from_text("https://groceries.morrisons.com", MORRISONS_ROBOTS)
    assert gate.allows("https://groceries.morrisons.com/api/products") is False


def test_gate_fails_closed_when_robots_is_unreadable():
    gate = RobotsGate.unreadable("https://www.tesco.com")
    assert gate.allows("https://www.tesco.com/groceries/gin") is False


class StubResponse:
    def __init__(self, text: str):
        self.status_code = 200
        self.text = text
        self.headers: dict[str, str] = {}

    def raise_for_status(self):
        pass


class StubSession:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        return StubResponse(self.text)


def test_get_returns_cached_text_and_makes_no_second_request(tmp_path):
    fetcher = Fetcher("test@example.test", cache_dir=tmp_path, delay=0)
    stub = StubSession("hello gin")
    fetcher.session = stub
    fetcher._gates["https://example.test"] = RobotsGate.from_text(
        "https://example.test", "User-agent: *\nDisallow: /nope\n"
    )

    first = fetcher.get("https://example.test/gin")
    assert first == "hello gin"
    assert stub.calls == 1

    second = fetcher.get("https://example.test/gin")
    assert second == "hello gin"
    assert stub.calls == 1
