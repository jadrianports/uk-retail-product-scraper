import pytest

from scraper.enrich import extract_abv, extract_origin, extract_pack_type, size_to_ml


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Package Type Glass Bottle Alcohol By Volume 40.3 Manufacturer Atom", 40.3),
        ("Additional Information: Alcohol By Volume: 40.3%", 40.3),
        ("70cl / 57.8%", 57.8),
        ("A London dry gin, 40% ABV, from England", 40.0),
        ("No strength is stated here", None),
        ("Alcohol By Volume 400", None),
        ("Alcohol By Volume 1000", None),
        ("abv 400", None),
        ("Alcohol By Volume 0", 0.0),
    ],
)
def test_extract_abv(text, expected):
    assert extract_abv(text) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("70cl", 700.0),
        ("1L", 1000.0),
        ("1.5 litres", 1500.0),
        ("750ml", 750.0),
        ("", None),
        (None, None),
        ("8 x 150ml", 1200.0),
        ("12 x 330ml", 3960.0),
        ("4x250ml", 1000.0),
        ("6 X 1L", 6000.0),
        # A product name can hold a letter x with no digit before it.
        # That must not read as a multiplier.
        ("Explorer Gin 70cl", 700.0),
    ],
)
def test_size_to_ml(raw, expected):
    assert size_to_ml(raw) == expected


def test_extract_pack_type():
    assert extract_pack_type("Package Type Glass Bottle Alcohol By Volume 40.3") == "Glass Bottle"
    assert extract_pack_type("nothing here") is None


def test_extract_origin():
    assert extract_origin("Country of Origin: United Kingdom") == "United Kingdom"
    assert extract_origin("Produce of Scotland") == "Scotland"
    assert extract_origin("nothing here") is None


def test_extract_origin_stops_before_the_next_label():
    # A country name can run straight into the next label with one space.
    # The capture must stop at the country name, not run into the label.
    assert (
        extract_origin("Country of Origin: United Kingdom Brand J Smith Ltd")
        == "United Kingdom"
    )
    assert (
        extract_origin("Country of Origin: Italy Manufacturer Engine Srl")
        == "Italy"
    )


def test_price_per_litre_normalises_across_sizes():
    from scraper.enrich import price_per_litre

    # A 50cl bottle at 26.50 is dearer per litre than a 70cl at 23.50,
    # and the raw price says the opposite. That is the whole point.
    assert price_per_litre(23.5, 700.0) == 33.57
    assert price_per_litre(26.5, 500.0) == 53.0
    assert price_per_litre(30.0, 1000.0) == 30.0


def test_price_per_litre_returns_null_rather_than_a_guess():
    from scraper.enrich import price_per_litre

    assert price_per_litre(None, 700.0) is None
    assert price_per_litre(23.5, None) is None
    # A zero size would divide by zero. A null is the honest answer.
    assert price_per_litre(23.5, 0.0) is None
