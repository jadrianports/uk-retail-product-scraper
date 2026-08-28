import hashlib
import logging
import random
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger(__name__)

# Retailers apply WAF protection to product pages and reject unknown
# clients. The user agent must look like a browser. We retain the tool
# name and contact so the site operator can identify this traffic.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 "
    "uk-retail-product-scraper/0.1 (+contact: {contact})"
)

# A site can send a very large Retry-After value. Cap the wait so one
# response cannot stall the run for an unreasonable time.
MAX_RETRY_WAIT = 120.0


def retry_wait(headers, attempt: int) -> float:
    backoff = float(2**attempt)
    raw = headers.get("Retry-After")
    if raw is None:
        wait = backoff
    else:
        try:
            wait = float(raw)
        except ValueError:
            # Retry-After can also be an HTTP-date (RFC 7231). Date parsing
            # is not worth a dependency here, so fall back to the backoff.
            wait = backoff
    if wait > MAX_RETRY_WAIT:
        log.warning("Retry-After of %ss exceeds the cap. Wait %ss instead", wait, MAX_RETRY_WAIT)
        wait = MAX_RETRY_WAIT
    # A malformed or hostile Retry-After header can be negative. time.sleep
    # rejects a negative value, so a wait can never go below zero.
    return max(wait, 0.0)


class RobotsDenied(Exception):
    """The site rules deny this path."""


class RobotsGate:
    def __init__(self, base_url: str, parser: RobotFileParser | None):
        self.base_url = base_url
        self._parser = parser

    @classmethod
    def from_text(cls, base_url: str, text: str) -> "RobotsGate":
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        return cls(base_url, parser)

    @classmethod
    def unreadable(cls, base_url: str) -> "RobotsGate":
        # You cannot read the rules, so you must not scrape the site.
        return cls(base_url, None)

    def allows(self, url: str) -> bool:
        if self._parser is None:
            return False
        return self._parser.can_fetch("*", url)


def load_robots(base_url: str, session: requests.Session) -> RobotsGate:
    robots_url = urljoin(base_url, "/robots.txt")
    try:
        response = session.get(robots_url, timeout=20)
    except requests.RequestException:
        return RobotsGate.unreadable(base_url)
    if response.status_code != 200 or not response.text.strip():
        log.warning("robots.txt is unreadable at %s (HTTP %s)", robots_url, response.status_code)
        return RobotsGate.unreadable(base_url)
    return RobotsGate.from_text(base_url, response.text)


class Fetcher:
    def __init__(
        self,
        contact: str,
        cache_dir: Path = Path(".cache"),
        delay: float = 1.0,
        max_attempts: int = 3,
    ):
        self.cache_dir = cache_dir
        self.delay = delay
        self.max_attempts = max_attempts
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT.format(contact=contact or "not supplied"),
                "Accept-Language": "en-GB,en;q=0.9",
            }
        )
        self._gates: dict[str, RobotsGate] = {}
        self._last_request = 0.0

    def _gate_for(self, url: str) -> RobotsGate:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._gates:
            self._gates[base] = load_robots(base, self.session)
        return self._gates[base]

    def _cache_path(self, url: str) -> Path:
        host = urlparse(url).netloc
        digest = hashlib.sha256(url.encode()).hexdigest()[:20]
        return self.cache_dir / host / f"{digest}.html"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = self.delay + random.uniform(0, 0.4) - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def get(self, url: str) -> str:
        if not self._gate_for(url).allows(url):
            raise RobotsDenied(f"robots.txt denies {url}")

        path = self._cache_path(url)
        if path.exists():
            return path.read_text("utf-8")

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            is_last_attempt = attempt == self.max_attempts
            try:
                response = self.session.get(url, timeout=30)
            except requests.RequestException as exc:
                last_error = exc
                # No point waiting out a backoff when no retry follows it.
                if not is_last_attempt:
                    time.sleep(2**attempt)
                continue

            if response.status_code == 200:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(response.text, "utf-8")
                return response.text

            if response.status_code in (429, 500, 502, 503, 504):
                last_error = requests.HTTPError(f"HTTP {response.status_code}")
                if is_last_attempt:
                    continue
                wait = retry_wait(response.headers, attempt)
                log.warning("HTTP %s for %s. Wait %ss", response.status_code, url, wait)
                time.sleep(wait)
                continue

            response.raise_for_status()

        raise RuntimeError(f"Cannot fetch {url}") from last_error
