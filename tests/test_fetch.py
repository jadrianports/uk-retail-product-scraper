from scraper.fetch import Fetcher, RobotsGate, retry_wait

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


def test_retry_wait_honours_a_numeric_retry_after():
    assert retry_wait({"Retry-After": "5"}, attempt=1) == 5.0


def test_retry_wait_falls_back_to_backoff_for_an_http_date():
    headers = {"Retry-After": "Fri, 28 Aug 2026 12:00:00 GMT"}
    assert retry_wait(headers, attempt=2) == 4.0


def test_retry_wait_falls_back_to_backoff_when_header_is_absent():
    assert retry_wait({}, attempt=3) == 8.0


def test_formatted_user_agent_is_browser_compatible_and_identifies_tool(tmp_path):
    contact = "test@example.com"
    fetcher = Fetcher(contact, cache_dir=tmp_path)
    user_agent = fetcher.session.headers["User-Agent"]

    assert user_agent.startswith("Mozilla/5.0"), "User-Agent must start with Mozilla/5.0 for browser compatibility"
    assert "uk-retail-product-scraper/0.1" in user_agent, "Tool name and version must be present"
    assert contact in user_agent, "Contact address must be present"
