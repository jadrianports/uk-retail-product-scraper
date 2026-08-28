import re

# Two formats occur on one live Morrisons page. A third occurs on the
# Whisky Exchange listing. Try each in turn.
# Each number group ends in (?!\d). Without it, a long run of digits
# like "1000" lets the group match a short prefix, "100", and that
# prefix can sit inside the valid range and pass as a real reading.
# The lookahead stops any match short of the full digit run.
_ABV_PATTERNS = [
    re.compile(r"alcohol\s*by\s*volume\s*:?\s*(\d{1,3}(?:\.\d+)?)(?!\d)\s*%?", re.I),
    re.compile(r"(\d{1,2}(?:\.\d+)?)(?!\d)\s*%\s*(?:abv|vol)", re.I),
    re.compile(r"\babv\b\s*:?\s*(\d{1,2}(?:\.\d+)?)(?!\d)\s*%?", re.I),
    re.compile(r"/\s*(\d{1,2}(?:\.\d+)?)(?!\d)\s*%", re.I),
]

# A pack count can lead the size, e.g. "8 x 150ml". The multiplier group
# only matches when a digit sits right before the x, so a name like
# "Explorer Gin" never reads as a multiplier.
_SIZE = re.compile(r"(?:(\d+)\s*[xX]\s*)?(\d+(?:\.\d+)?)\s*(cl|ml|l|litre|litres)\b", re.I)
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
        # 0.0% is a real reading — low-and-no-alcohol spirits exist in
        # this category. Only reject outside the physical range.
        if 0 <= value <= 100:
            return value
    return None


def size_to_ml(raw: str | None) -> float | None:
    if not raw:
        return None
    match = _SIZE.search(raw)
    if not match:
        return None
    pack_count = float(match.group(1)) if match.group(1) else 1.0
    return pack_count * float(match.group(2)) * _TO_ML[match.group(3).lower()]


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
