from scraper.llm import Derived, GeminiEnricher, retry_delay_seconds


class _FakeModels:
    def __init__(self, parsed=None, raises=False):
        self._parsed = parsed
        self._raises = raises

    def generate_content(self, **kwargs):
        if self._raises:
            raise RuntimeError("model unavailable")
        return type("R", (), {"parsed": self._parsed})()


class _FakeClient:
    def __init__(self, parsed=None, raises=False):
        self.models = _FakeModels(parsed, raises)


class _FakeModelsDailyQuotaExhausted:
    """Raises a per-day quota error on every call. Counts calls."""

    def __init__(self):
        self.call_count = 0

    def generate_content(self, **kwargs):
        self.call_count += 1
        raise RuntimeError(
            "429 RESOURCE_EXHAUSTED. quotaId: "
            "GenerateRequestsPerDayPerProjectPerModel-FreeTier, "
            "quotaValue: '20', retryDelay: '59s'"
        )


class _FakeClientDailyQuotaExhausted:
    def __init__(self):
        self.models = _FakeModelsDailyQuotaExhausted()


class _FakeModelsPerMinuteThenSuccess:
    """Raises a per-minute quota error once, then returns a parsed reply."""

    def __init__(self, parsed):
        self.call_count = 0
        self._parsed = parsed

    def generate_content(self, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError(
                "429 RESOURCE_EXHAUSTED. quotaId: "
                "GenerateRequestsPerMinutePerProjectPerModel-FreeTier, "
                "quotaValue: '5', retryDelay: '0s'"
            )
        return type("R", (), {"parsed": self._parsed})()


class _FakeClientPerMinuteThenSuccess:
    def __init__(self, parsed):
        self.models = _FakeModelsPerMinuteThenSuccess(parsed)


def test_derive_returns_the_model_values():
    enricher = GeminiEnricher(client=_FakeClient(Derived(flavour_style="Citrus led London dry")), min_interval=0)
    result = enricher.derive("Ableforth's Bathtub Gin", "Orange peel and juniper.")
    assert result.flavour_style == "Citrus led London dry"


def test_model_failure_gives_nulls_and_does_not_raise():
    enricher = GeminiEnricher(client=_FakeClient(raises=True), min_interval=0)
    result = enricher.derive("A Gin", "Some text.")
    assert result.flavour_style is None
    assert result.abv_percent is None


def test_no_key_gives_nulls():
    enricher = GeminiEnricher(client=None, min_interval=0)
    result = enricher.derive("A Gin", "Some text.")
    assert result.flavour_style is None


def test_prompt_does_not_restate_the_schema():
    enricher = GeminiEnricher(client=None, min_interval=0)
    prompt = enricher.build_prompt("A Gin", "Some text.")
    assert "flavour_style" not in prompt
    assert "json" not in prompt.lower()


def test_prompt_does_not_ask_for_origin():
    enricher = GeminiEnricher(client=None, min_interval=0)
    prompt = enricher.build_prompt("A Gin", "Some text.").lower()
    assert "origin" not in prompt
    assert "country" not in prompt


def test_prompt_tells_the_model_not_to_repeat_the_product_name():
    enricher = GeminiEnricher(client=None, min_interval=0)
    prompt = enricher.build_prompt("A Gin", "Some text.")
    assert "do not repeat the product name" in prompt.lower()


def test_out_of_range_abv_is_nulled_and_the_rest_of_the_reply_survives():
    parsed = Derived(flavour_style="Juniper led", abv_percent=150.0)
    enricher = GeminiEnricher(client=_FakeClient(parsed), min_interval=0)
    result = enricher.derive("A Gin", "Some text.")
    assert result.abv_percent is None
    assert result.flavour_style == "Juniper led"


def test_zero_abv_survives_as_a_legitimate_value():
    parsed = Derived(flavour_style="Juniper led", abv_percent=0.0)
    enricher = GeminiEnricher(client=_FakeClient(parsed), min_interval=0)
    result = enricher.derive("A Gin", "Some text.")
    assert result.abv_percent == 0.0


def test_derived_has_no_country_of_origin_field():
    # The model must never be asked for origin: it has misattributed a
    # country that the text mentions for another reason. Origin is
    # regex-only now.
    assert "country_of_origin" not in Derived.model_fields


def test_retry_delay_seconds_parses_the_quoted_retry_delay():
    message = (
        "429 RESOURCE_EXHAUSTED. ... \"retryDelay\": \"50s\" ... "
        "Quota exceeded for metric: generate_content_free_tier_requests"
    )
    assert retry_delay_seconds(message) == 50.0


def test_retry_delay_seconds_caps_an_absurdly_large_value():
    message = "429 RESOURCE_EXHAUSTED ... 'retryDelay': '999999s' ..."
    assert retry_delay_seconds(message) == 60.0


def test_retry_delay_seconds_returns_a_small_default_when_no_delay_is_present():
    assert retry_delay_seconds("model unavailable") == 2.0


def test_daily_quota_error_trips_the_breaker_and_returns_an_empty_result():
    client = _FakeClientDailyQuotaExhausted()
    enricher = GeminiEnricher(client=client, min_interval=0)

    result = enricher.derive("A Gin", "Some text.")

    assert result == Derived()
    assert client.models.call_count == 1


def test_tripped_breaker_stops_all_further_api_calls():
    client = _FakeClientDailyQuotaExhausted()
    enricher = GeminiEnricher(client=client, min_interval=0)

    enricher.derive("A Gin", "Some text.")
    calls_after_first_product = client.models.call_count

    second_result = enricher.derive("Another Gin", "Some text.")

    assert second_result == Derived()
    assert client.models.call_count == calls_after_first_product


def test_tripped_breaker_does_not_call_the_retry_delay_helper(monkeypatch):
    import scraper.llm as llm_module

    def _fail_if_called(error_text):
        raise AssertionError("retry_delay_seconds must not run once the breaker is tripped")

    client = _FakeClientDailyQuotaExhausted()
    enricher = GeminiEnricher(client=client, min_interval=0)
    enricher.derive("A Gin", "Some text.")

    monkeypatch.setattr(llm_module, "retry_delay_seconds", _fail_if_called)

    result = enricher.derive("Another Gin", "Some text.")
    assert result == Derived()


def test_per_minute_quota_error_does_not_trip_the_breaker(monkeypatch):
    import scraper.llm as llm_module

    monkeypatch.setattr(llm_module.time, "sleep", lambda seconds: None)
    parsed = Derived(flavour_style="Juniper led")
    client = _FakeClientPerMinuteThenSuccess(parsed)
    enricher = GeminiEnricher(client=client, min_interval=0)

    result = enricher.derive("A Gin", "Some text.")

    assert result.flavour_style == "Juniper led"
    assert client.models.call_count == 2
    assert enricher._daily_quota_exhausted is False

    later_result = enricher.derive("Another Gin", "Some text.")
    assert client.models.call_count == 3
    assert later_result.flavour_style == "Juniper led"
