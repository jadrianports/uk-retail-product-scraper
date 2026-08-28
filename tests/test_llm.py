from scraper.llm import Derived, GeminiEnricher


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


def test_derive_returns_the_model_values():
    enricher = GeminiEnricher(client=_FakeClient(Derived(flavour_style="Citrus led London dry")))
    result = enricher.derive("Ableforth's Bathtub Gin", "Orange peel and juniper.")
    assert result.flavour_style == "Citrus led London dry"


def test_model_failure_gives_nulls_and_does_not_raise():
    enricher = GeminiEnricher(client=_FakeClient(raises=True))
    result = enricher.derive("A Gin", "Some text.")
    assert result.flavour_style is None
    assert result.abv_percent is None


def test_no_key_gives_nulls():
    enricher = GeminiEnricher(client=None)
    result = enricher.derive("A Gin", "Some text.")
    assert result.flavour_style is None


def test_prompt_does_not_restate_the_schema():
    enricher = GeminiEnricher(client=None)
    prompt = enricher.build_prompt("A Gin", "Some text.")
    assert "flavour_style" not in prompt
    assert "json" not in prompt.lower()


def test_out_of_range_abv_is_nulled_and_the_rest_of_the_reply_survives():
    parsed = Derived(flavour_style="Juniper led", abv_percent=150.0, country_of_origin="England")
    enricher = GeminiEnricher(client=_FakeClient(parsed))
    result = enricher.derive("A Gin", "Some text.")
    assert result.abv_percent is None
    assert result.flavour_style == "Juniper led"
    assert result.country_of_origin == "England"


def test_zero_abv_survives_as_a_legitimate_value():
    parsed = Derived(flavour_style="Juniper led", abv_percent=0.0, country_of_origin="England")
    enricher = GeminiEnricher(client=_FakeClient(parsed))
    result = enricher.derive("A Gin", "Some text.")
    assert result.abv_percent == 0.0
