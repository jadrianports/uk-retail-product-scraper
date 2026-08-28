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
    ],
)
def test_extract_abv(text, expected):
    assert extract_abv(text) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("70cl", 700.0), ("1L", 1000.0), ("1.5 litres", 1500.0), ("750ml", 750.0), ("", None), (None, None)],
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
