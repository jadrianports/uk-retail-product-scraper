import logging
import os

from pydantic import BaseModel

log = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"


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
    def __init__(self, client=None):
        self.client = client

    def build_prompt(self, name: str, text: str) -> str:
        # Do not restate the schema here. The SDK sends the schema separately.
        # The Google documentation states that a repeated schema lowers quality.
        return (
            "You read product text from a UK drinks retailer.\n"
            "Use only the text below. Do not use other knowledge.\n"
            "If the text does not state a value, leave that value empty.\n"
            "For the style, write four words or fewer.\n\n"
            f"Product: {name}\n"
            f"Text: {text}"
        )

    def derive(self, name: str, text: str) -> Derived:
        if self.client is None:
            return Derived()

        from google.genai import types

        for attempt in (1, 2):
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
                continue

            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, Derived):
                if parsed.abv_percent is not None and not 0 <= parsed.abv_percent <= 100:
                    parsed.abv_percent = None
                return parsed
            log.warning("The model reply did not validate for %s on attempt %s", name, attempt)

        return Derived()
