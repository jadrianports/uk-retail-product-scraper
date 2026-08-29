from scraper.enrich import (
    extract_abv,
    extract_origin,
    extract_pack_type,
    price_per_litre,
    size_to_ml,
)

# A short text has no room for real prose. The model has nothing to read.
MIN_TEXT_FOR_MODEL = 20


def _has_letters(text: str) -> bool:
    """Tell a measurement string apart from real prose."""
    return any(char.isalpha() for char in text)


def enrich_product(product, enricher) -> None:
    """Fill the hard attributes. Try regex first, then the model."""
    text = product.detail_text or product.description or ""

    # An adapter can set size_ml before enrich_product runs. Only fill it
    # when it is still empty, or the regex overwrites a correct value and
    # its true source is lost.
    if product.size_ml is None:
        product.size_ml = size_to_ml(product.size_raw)
        product.field_sources["size_ml"] = "regex" if product.size_ml is not None else "missing"

    # Normalise price by volume. One category sells several sizes, so
    # price alone cannot rank it. Both inputs are already on the product.
    product.price_per_litre = price_per_litre(product.price_gbp, product.size_ml)
    product.field_sources["price_per_litre"] = (
        "derived" if product.price_per_litre is not None else "missing"
    )

    # An adapter can set a field before enrich_product runs (Whisky Exchange
    # sets abv_percent from the listing card). Only fill a field still empty,
    # or the regex overwrites a correct value and its true source is lost.
    for field, extractor in (
        ("abv_percent", extract_abv),
        ("pack_type", extract_pack_type),
        ("country_of_origin", extract_origin),
    ):
        value = extractor(text)
        if getattr(product, field) is None and value is not None:
            setattr(product, field, value)
            product.field_sources[field] = "regex"

    # Tag pack_type and country_of_origin now. needs_model can return early
    # below, and a field this function touches must always end up with a
    # source. The model never fills country_of_origin — see llm.py for why.
    if product.pack_type is None:
        product.field_sources["pack_type"] = "missing"
    if product.country_of_origin is None:
        product.field_sources["country_of_origin"] = "missing"

    needs_model = product.abv_percent is None or product.flavour_style is None
    if not needs_model:
        return

    model_text = (product.description or text)[:1500]

    # A call that cannot succeed is worse than no call. A text this short,
    # or with no letters at all, gives the model nothing to read.
    if len(model_text.strip()) < MIN_TEXT_FOR_MODEL or not _has_letters(model_text):
        for field in ("flavour_style", "abv_percent"):
            if getattr(product, field) is None:
                product.field_sources[field] = "missing"
        return

    derived = enricher.derive(product.name or "", model_text)

    for field in ("flavour_style", "abv_percent"):
        if getattr(product, field) is not None:
            continue
        value = getattr(derived, field)
        setattr(product, field, value)
        product.field_sources[field] = "llm" if value is not None else "missing"
