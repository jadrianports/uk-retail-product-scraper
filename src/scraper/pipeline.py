from scraper.enrich import extract_abv, extract_origin, extract_pack_type, size_to_ml


def enrich_product(product, enricher) -> None:
    """Fill the hard attributes. Try regex first, then the model."""
    text = product.detail_text or product.description or ""

    # An adapter can set size_ml before enrich_product runs. Only fill it
    # when it is still empty, or the regex overwrites a correct value and
    # its true source is lost.
    if product.size_ml is None:
        product.size_ml = size_to_ml(product.size_raw)
        product.field_sources["size_ml"] = "regex" if product.size_ml is not None else "missing"

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

    derived = enricher.derive(product.name or "", (product.description or text)[:1500])

    for field in ("flavour_style", "abv_percent"):
        if getattr(product, field) is not None:
            continue
        value = getattr(derived, field)
        setattr(product, field, value)
        product.field_sources[field] = "llm" if value is not None else "missing"
