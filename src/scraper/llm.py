import json
import logging
import os
import re
import time

import requests
from pydantic import BaseModel

log = logging.getLogger(__name__)

# One provider per key. The tool uses whichever key it finds, so an
# evaluator is not forced to open an account with one named vendor.
GEMINI_MODEL = "gemini-3.5-flash-lite"
OPENAI_MODEL = "gpt-4o-mini"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

# Kept for the import path that existed before the other providers.
MODEL = GEMINI_MODEL

# Space calls so the tool does not provoke the per-minute limit.
MIN_CALL_INTERVAL = 6.0

# A 429 reply can ask for a long wait. Cap it so one reply cannot
# stall the run for an unreasonable time.
RETRY_DELAY_CAP = 60.0

# Wait this long on a rate-limit error when the API gives no delay.
DEFAULT_RETRY_DELAY = 2.0

HTTP_TIMEOUT = 60

_RETRY_DELAY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")
_FENCE_RE = re.compile(r"^`{3}(?:json)?\s*|\s*`{3}$", re.M)


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
    # The model has no field for country of origin. A past reply named a
    # country the text stated for an ingredient, not for the product. A
    # null is better than that guess. Origin comes from the regex only.


def build_client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        log.warning("GEMINI_API_KEY is not set. The tool writes null for the derived fields.")
        return None
    from google import genai

    return genai.Client(api_key=key)


class _Enricher:
    """Shared prompt, spacing and range check. One subclass per provider."""

    def __init__(self, min_interval: float = MIN_CALL_INTERVAL):
        self.min_interval = min_interval
        self._last_call = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def build_prompt(self, name: str, text: str) -> str:
        # Do not restate the schema here. The Gemini SDK sends the schema
        # separately, and the Google documentation states that a repeated
        # schema lowers quality.
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

    def _schema_prompt(self, name: str, text: str) -> str:
        """The prompt for a provider that has no separate schema channel."""
        shape = '{"flavour_style": string or null, "abv_percent": number or null}'
        return (
            self.build_prompt(name, text)
            + "\n\nReply with only this object and no other text:\n"
            + shape
        )

    @staticmethod
    def _checked(flavour_style, abv_percent) -> Derived:
        """Range-check the strength. 0.0 is a real reading, so test the range."""
        if abv_percent is not None and not 0 <= abv_percent <= 100:
            abv_percent = None
        return Derived(flavour_style=flavour_style, abv_percent=abv_percent)

    def _from_json_text(self, raw: str) -> Derived:
        data = json.loads(_FENCE_RE.sub("", raw).strip())
        abv = data.get("abv_percent")
        return self._checked(data.get("flavour_style"), float(abv) if abv is not None else None)

    def derive(self, name: str, text: str) -> Derived:
        raise NotImplementedError


class NullEnricher(_Enricher):
    """No key was found. Every derived field stays null and the run goes on."""

    def derive(self, name: str, text: str) -> Derived:
        return Derived()


class GeminiEnricher(_Enricher):
    def __init__(self, client=None, min_interval: float = MIN_CALL_INTERVAL):
        super().__init__(min_interval)
        self.client = client
        # Set once the daily quota reports as spent. Stops all further
        # API calls for the rest of this run.
        self._daily_quota_exhausted = False

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
                    model=GEMINI_MODEL,
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
                return self._checked(parsed.flavour_style, parsed.abv_percent)
            log.warning("The model reply did not validate for %s on attempt %s", name, attempt)

        return Derived()


class _HttpEnricher(_Enricher):
    """A provider reached over plain HTTP, so it needs no extra dependency."""

    provider = ""

    def __init__(self, api_key: str, min_interval: float = MIN_CALL_INTERVAL):
        super().__init__(min_interval)
        self.api_key = api_key

    def _request(self, prompt: str) -> str:
        raise NotImplementedError

    def derive(self, name: str, text: str) -> Derived:
        for attempt in (1, 2):
            self._throttle()
            try:
                return self._from_json_text(self._request(self._schema_prompt(name, text)))
            except Exception as exc:
                log.warning(
                    "The %s call failed for %s on attempt %s: %s",
                    self.provider, name, attempt, exc,
                )
                if _is_rate_limited(str(exc)):
                    time.sleep(retry_delay_seconds(str(exc)))
        return Derived()


class OpenAIEnricher(_HttpEnricher):
    provider = "openai"

    def _request(self, prompt: str) -> str:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": OPENAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


class AnthropicEnricher(_HttpEnricher):
    provider = "anthropic"

    def _request(self, prompt: str) -> str:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 256,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["content"][0]["text"]


def build_enricher(min_interval: float = MIN_CALL_INTERVAL) -> _Enricher:
    """Pick the provider from whichever key is set. Gemini wins a tie.

    An evaluator who holds an OpenAI or an Anthropic key can run the model
    step without opening a Google account.
    """
    if os.environ.get("GEMINI_API_KEY"):
        return GeminiEnricher(client=build_client(), min_interval=min_interval)
    for env_name, cls in (
        ("OPENAI_API_KEY", OpenAIEnricher),
        ("ANTHROPIC_API_KEY", AnthropicEnricher),
    ):
        key = os.environ.get(env_name)
        if key:
            log.info("Using %s for the derived fields.", cls.provider)
            return cls(api_key=key, min_interval=min_interval)
    log.warning(
        "No model key was found. Set GEMINI_API_KEY, OPENAI_API_KEY or "
        "ANTHROPIC_API_KEY. The derived fields stay null and the run goes on."
    )
    return NullEnricher(min_interval=min_interval)
