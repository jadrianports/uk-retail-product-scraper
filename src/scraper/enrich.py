import re

# Two formats occur on one live Morrisons page. A third occurs on the
# Whisky Exchange listing. Try each in turn.
# The first pattern uses {1,3}, not {1,2}. A 3-digit reading like "400"
# must match whole, so the range check below can reject it. {1,2} would
# cut it to "40" and let a bad value pass as a good one.
_ABV_PATTERNS = [
    re.compile(r"alcohol\s*by\s*volume\s*:?\s*(\d{1,3}(?:\.\d+)?)\s*%?", re.I),
    re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%\s*(?:abv|vol)", re.I),
    re.compile(r"\babv\b\s*:?\s*(\d{1,2}(?:\.\d+)?)\s*%?", re.I),
    re.compile(r"/\s*(\d{1,2}(?:\.\d+)?)\s*%", re.I),
]

_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(cl|ml|l|litre|litres)\b", re.I)
_TO_ML = {"cl": 10.0, "ml": 1.0, "l": 1000.0, "litre": 1000.0, "litres": 1000.0}

# A closed list keeps the match safe. Free text after "Package Type" runs
# straight into the next label, so an open pattern captures rubbish.
_PACK_TYPES = ["Glass Bottle", "Plastic Bottle", "Gift Box", "Carton", "Pouch", "Bottle", "Can", "Tin"]

_ORIGIN_PATTERNS = [
    re.compile(r"country\s*of\s*origin\s*:?\s*([A-Za-z][A-Za-z ,.'()-]{2,40}?)(?=\s{2,}|[.;]|$)", re.I),
    re.compile(r"produce of\s+([A-Za-z][A-Za-z ]{2,30}?)(?=\s{2,}|[.;]|$)", re.I),
]


def extract_abv(text: str | None) -> float | None:
    if not text:
        return None
    for pattern in _ABV_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = float(match.group(1))
        if 0 < value <= 100:
            return value
    return None


def size_to_ml(raw: str | None) -> float | None:
    if not raw:
        return None
    match = _SIZE.search(raw)
    if not match:
        return None
    return float(match.group(1)) * _TO_ML[match.group(2).lower()]


def extract_pack_type(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    if "package type" not in lowered:
        return None
    tail = lowered.split("package type", 1)[1][:60]
    for pack in _PACK_TYPES:
        if pack.lower() in tail:
            return pack
    return None


def extract_origin(text: str | None) -> str | None:
    if not text:
        return None
    for pattern in _ORIGIN_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None
