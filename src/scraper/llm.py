import logging
import os
import re
import time

from pydantic import BaseModel

log = logging.getLogger(__name__)

MODEL = "gemini-3.5-flash-lite"

# Space calls so the tool does not provoke the per-minute limit.
MIN_CALL_INTERVAL = 6.0

# A 429 reply can ask for a long wait. Cap it so one reply cannot
# stall the run for an unreasonable time.
RETRY_DELAY_CAP = 60.0

# Wait this long on a rate-limit error when the API gives no delay.
DEFAULT_RETRY_DELAY = 2.0

_RETRY_DELAY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")


def retry_delay_seconds(error_text: str) -> float:
    """Read the wait time a 429 reply asks for. Return a capped float."""
    match = _RETRY_DELAY_RE.search(error_text)
    delay = float(match.group(1)) if match else DEFAULT_RETRY_DELAY
    return min(delay, RETRY_DELAY_CAP)


def _is_rate_limited(error_text: str) -> bool:
    return (
        "retryDelay" in error_text
        or "RESOURCE_EXHAUSTED" in error_text
        or "429" in error_text
    )


def _is_daily_quota_exhausted(error_text: str) -> bool:
    """Tell a spent daily quota from a per-minute limit.

    Match on the quota name, not the numeric quota value. The value
    changes per model; the name does not.
    """
    return "PerDay" in error_text or "GenerateRequestsPerDayPerProject" in error_text


class Derived(BaseModel):
    flavour_style: str | None = None
    abv_percent: float | None = None
    country_of_origin: str | None = None


def build_client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        log.warning("GEMINI_API_KEY is not set. The tool writes null for the derived fields.")
        return None
    from google import genai

    return genai.Client(api_key=key)


class GeminiEnricher:
    def __init__(self, client=None, min_interval: float = MIN_CALL_INTERVAL):
        self.client = client
        self.min_interval = min_interval
        self._last_call = 0.0
        # Set once the daily quota reports as spent. Stops all further
        # API calls for the rest of this run.
        self._daily_quota_exhausted = False

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def build_prompt(self, name: str, text: str) -> str:
        # Do not restate the schema here. The SDK sends the schema separately.
        # The Google documentation states that a repeated schema lowers quality.
        return (
            "You read product text from a UK drinks retailer.\n"
            "Use only the text below. Do not use other knowledge.\n"
            "If the text does not state a value, leave that value empty.\n"
            "Describe the flavour or style using words found in the text.\n"
            "Do not repeat the product name in your answer.\n"
            "Do not guess a flavour or style from the product name alone.\n"
            "For the style, write four words or fewer.\n\n"
            f"Product: {name}\n"
            f"Text: {text}"
        )

    def derive(self, name: str, text: str) -> Derived:
        if self.client is None:
            return Derived()

        # The breaker is tripped. Do not call the API or sleep again
        # this run; the daily quota does not reset until tomorrow.
        if self._daily_quota_exhausted:
            return Derived()

        from google.genai import types

        for attempt in (1, 2):
            self._throttle()
            try:
                response = self.client.models.generate_content(
                    model=MODEL,
                    contents=self.build_prompt(name, text),
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=Derived,
                    ),
                )
            except Exception as exc:
                log.warning("The model call failed for %s on attempt %s: %s", name, attempt, exc)
                error_text = str(exc)
                if _is_daily_quota_exhausted(error_text):
                    self._daily_quota_exhausted = True
                    log.warning(
                        "The daily Gemini quota is spent. The remaining products get "
                        "null derived fields. The quota resets the next day."
                    )
                    return Derived()
                if _is_rate_limited(error_text):
                    wait = retry_delay_seconds(error_text)
                    log.warning("The API reports a limit. Wait %ss before the retry.", wait)
                    time.sleep(wait)
                continue

            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, Derived):
                if parsed.abv_percent is not None and not 0 <= parsed.abv_percent <= 100:
                    parsed.abv_percent = None
                return parsed
            log.warning("The model reply did not validate for %s on attempt %s", name, attempt)

        return Derived()
