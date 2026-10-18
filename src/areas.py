import re
from collections import Counter

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
SKIP = {"karachi", "sindh", "sindhi", "pakistan", "city", "province", "unknown",
        "south", "east", "west", "central", "north", "green",
        # districts are not used as areas
        "karachi central", "karachi east", "karachi south", "karachi west",
        # two different places share this name, so it cannot link events safely
        "bilal colony",
        # roads
        "shahrah-e-faisal", "sharah-e-faisal", "shara-e-faisal", "shahra-e-faisal",
        } | set(MONTHS) | set(DAYS)
SKIP_PREFIX = ("sector", "block", "phase", "street", "road", "lane", "house", "flat", "plot")
SKIP_SUFFIX = ("police station", "police precinct", "police", "road", "highway", "avenue", "street")
SUFFIX = re.compile(r"\s+(?:town|area|neighbou?rhood|district|locality|city|province|state)$", re.I)

WORD = r"[A-Z][A-Za-z0-9'’\-]*"
PLACE = re.compile(
    r"(?i:\b(?:in|at|near|on|of|from)\b)\s+(?:(?i:the)\s+)?"
    rf"({WORD}(?:\s+(?:{WORD}|(?:of|e|i)(?=\s+[A-Z0-9])|\d+[A-Z\-]*))*)"
)
SUMMARY_PLACE = re.compile(
    rf"(?i:\bin\b)\s+(?:(?i:the)\s+)?({WORD}(?:\s+(?:{WORD}|(?:e|i)(?=\s+[A-Z])))*)"
    r"\s+(?i:neighbou?rhood|area|town|locality)\b"
)
BARE = re.compile(rf"\s*({WORD}(?:\s+{WORD})*)(?:\s+(?i:area|neighbou?rhood|town))?\s*\.?\s*")
FACILITY_WORD = "Consulate|Embassy|Dockyard|Headquarters|Airport|Airbase|Cantonment"
FACILITY = re.compile(rf"\b((?:(?:U\.S\.|{WORD})\s+){{1,3}}(?i:{FACILITY_WORD}))\b")

# Spelling variants of the same place (lower-case variant -> canonical name)
AREA_ALIASES = {
    # Typos of Orangi
    "organi": "Orangi", "oranti": "Orangi", "organgi": "Orangi",
    # Typos and variants of other places
    "landhi-89": "Landhi", "korangi 5": "Korangi", "nazimabad no": "Nazimabad",
    "site-a": "SITE", "site": "SITE", "sindh industrial trading estate": "SITE",
    "monimabad": "Mominabad", "momin abad": "Mominabad",
    # Gulshan-e-Iqbal (Gulshan Town is the same place)
    "gulshan": "Gulshan-e-Iqbal", "gullshan": "Gulshan-e-Iqbal", "gulshen": "Gulshan-e-Iqbal",
    "gulshan-i-iqbal": "Gulshan-e-Iqbal", "gulshane iqbal": "Gulshan-e-Iqbal",
    "gulshan-e iqbal": "Gulshan-e-Iqbal", "gulshan e iqbal": "Gulshan-e-Iqbal",
    "gulshen e iqbal": "Gulshan-e-Iqbal", "gulshan-e-iqba": "Gulshan-e-Iqbal",
    "gulshan iqbal": "Gulshan-e-Iqbal",
    # Gulshan-e-Maymar and Gulshan-e-Hadeed (separate areas)
    "gulshan maymar": "Gulshan-e-Maymar", "gulshan-e maymar": "Gulshan-e-Maymar",
    "gulshan e maymar": "Gulshan-e-Maymar", "gulshan-i-maymar": "Gulshan-e-Maymar",
    "gulshan-e-maymar mor": "Gulshan-e-Maymar",
    "gulshan hadeed": "Gulshan-e-Hadeed", "gulshan-i-hadeed": "Gulshan-e-Hadeed",
    # Gulistan-e-Jauhar (a separate area)
    "gulistan-e-johar": "Gulistan-e-Jauhar", "gulistan-i-johar": "Gulistan-e-Jauhar",
    "gulistan e johar": "Gulistan-e-Jauhar", "gulistan-e johar": "Gulistan-e-Jauhar",
    # Defence Housing Authority
    "defense housing authority": "Defence Housing Authority",
    "defense house authority": "Defence Housing Authority",
    "defense housing": "Defence Housing Authority",
    "defense": "Defence Housing Authority", "defence": "Defence Housing Authority",
    "dha": "Defence Housing Authority",
    # Single-spelling fixes
    "layari": "Lyari", "mailir": "Malir", "sadar": "Saddar",
    "liaqatabad": "Liaquatabad", "qasbah colony": "Qasba Colony",
    "oasba colony": "Qasba Colony", "sohraab goth": "Sohrab Goth",
    "sorab goth": "Sohrab Goth", "cliffton": "Clifton", "bin qassim": "Bin Qasim",
    "sarjani": "Surjani", "suranji": "Surjani", "peerabad": "Pirabad",
    "karadar": "Kharadar", "maripur": "Mauripur",
    "federal-b": "Federal B", "fb": "Federal B", "papoosh nagar": "Paposh Nagar",
    "fronteir colony": "Frontier Colony", "nagan chorangi": "Nagan Chowrangi",
    "metrovillare": "Metroville", "ranchore lane": "Ranchore Line",
    "ibrahim haideri": "Ibrahim Hyderi", "kiamari": "Keamari",
    "gurumandir": "Guru Mandir", "issa nagri": "Essa Nagri",
    "pahar gunj": "Pahar Ganj", "ram swami": "Ramaswami", "ramswami": "Ramaswami",
    "lea market": "Lee Market", "kali pahari": "Kati Pahari",
    "sochal goth": "Sachal Goth", "aladin park": "Aladdin Park",
}

# Sub-areas that count as part of a bigger area (decided by the project author)
AREA_PARENT = {
    "Mominabad": "Orangi", "Frontier Colony": "Orangi", "Chisti Nagar": "Orangi",
    "Zaman": "Korangi",
    "Azizabad": "Gulberg", "Ayesha Manzil": "Gulberg", "Federal B": "Gulberg",
    "Paposh Nagar": "Nazimabad", "Chandni Chowk": "Nazimabad", "Urdu Bazar": "Nazimabad",
    "Five Star Chowrangi": "North Nazimabad", "People's Colony": "North Nazimabad",
    "Shadman": "North Nazimabad",
    "Power House": "North Karachi",
    "Safari Park": "Gulshan-e-Iqbal", "Aladdin Park": "Gulshan-e-Iqbal",
    "Maskan Chowrangi": "Gulshan-e-Iqbal", "Sachal": "Gulshan-e-Iqbal",
    "Sachal Goth": "Gulshan-e-Iqbal", "Essa Nagri": "Gulshan-e-Iqbal",
    "Shanti Nagar": "Gulshan-e-Iqbal",
    "Saudabad": "Malir", "Ibrahim Hyderi": "Malir",
    "Sohrab Goth": "Malir", "Ahsanabad": "Gadap",
    "Aram Bagh": "Saddar",
    "Bihar Colony": "Lyari", "Chakiwara": "Lyari", "Lee Market": "Lyari",
    "Qasba Colony": "SITE", "Pak Colony": "SITE", "Metroville": "SITE",
    "Islamia Colony": "SITE",
    "Ramaswami": "Garden",
    "Taiser": "Gadap", "Gulshan-e-Maymar": "Gadap",
    "Gulshan-e-Ghazi": "Baldia",
    "Safoora Chowrangi": "Gulistan-e-Jauhar",
    "Khyber Chowk": "Ittehad",
    "Saudi Arabian Consulate": "Clifton",
    "Gulbahar": "Liaquatabad",
    "Khayaban-e-Ittehad": "Defence Housing Authority",
    "Manghopir": "Orangi",
}


def clean_name(name):
    """Tidy a name and fix its spelling, without rolling it up into a bigger area."""
    name = " ".join(str(name).replace("\u2019", "'").split())
    while True:
        shorter = SUFFIX.sub("", name)
        if shorter == name:
            break
        name = shorter
    name = name.strip(" .,-")
    return AREA_ALIASES.get(name.lower(), name)


def roll_up(name):
    """Follow AREA_PARENT upwards (Chandni Chowk -> Nazimabad)."""
    seen = set()
    while name in AREA_PARENT and name not in seen:
        seen.add(name)
        name = AREA_PARENT[name]
    return name


def normalise(name):
    return roll_up(clean_name(name))


def valid(name):
    low = name.lower()
    return (len(name) >= 3 and low not in SKIP
            and not low.startswith(SKIP_PREFIX) and not low.endswith(SKIP_SUFFIX))


def _pair(raw):
    """(specific name, area) for a raw name, or None if it is not a usable place."""
    specific = clean_name(raw)
    area = roll_up(specific)
    if valid(specific) and valid(area):
        return specific, area
    return None


def candidate_pairs(text):
    """(specific name, area) pairs in a location text, in order of appearance."""
    found = []
    if not isinstance(text, str):
        return found
    for match in PLACE.finditer(text):
        for part in re.split(r"\s+of\s+", match.group(1)):
            pair = _pair(part)
            if pair:
                found.append(pair)
    if not found:
        bare = BARE.fullmatch(text)
        if bare:
            pair = _pair(bare.group(1))
            if pair:
                found.append(pair)
    return found


def summary_pairs(text):
    """High-precision places from a summary: named facilities and 'in X area/town'."""
    found = []
    if isinstance(text, str):
        for match in FACILITY.finditer(text):
            pair = _pair(" ".join(match.group(1).split()).title())
            if pair:
                found.append(pair)
        for match in SUMMARY_PLACE.finditer(text):
            pair = _pair(match.group(1))
            if pair:
                found.append(pair)
    return found


def candidates(text):
    return [area for _, area in candidate_pairs(text)]


def summary_candidates(text):
    return [area for _, area in summary_pairs(text)]


def build_gazetteer(df, min_events=2):
    """Areas that appear in at least min_events events."""
    counts = Counter()
    for location, city_raw, summary in zip(df["location"], df["city_raw"], df["summary_clean"]):
        names = set(candidates(location)) | set(summary_candidates(summary))
        if isinstance(city_raw, str):
            pair = _pair(city_raw)
            if pair:
                names.add(pair[1])
        counts.update(names)
    return {name: n for name, n in counts.items() if n >= min_events}


_SCAN_CACHE = {}


def _scan_names(gazetteer):
    """Every surface name worth searching for in a summary, with the area it belongs to."""
    key = (id(gazetteer), len(gazetteer))
    if key not in _SCAN_CACHE:
        names = {name: name for name in gazetteer}
        for child in AREA_PARENT:
            area = roll_up(child)
            if area in gazetteer and valid(child):
                names.setdefault(child, area)
        _SCAN_CACHE[key] = list(names.items())
    return _SCAN_CACHE[key]


def _locality(specific, area):
    return specific if specific != area else None


def extract_area_detail(location, summary, city_raw, gazetteer):
    """Return (area, locality, method). The locality is the more specific place, if any."""
    for specific, area in candidate_pairs(location):
        if area in gazetteer:
            return area, _locality(specific, area), "location_pattern"

    if isinstance(city_raw, str):
        pair = _pair(city_raw)
        if pair and pair[1] in gazetteer:
            return pair[1], _locality(*pair), "city_field"

    for specific, area in summary_pairs(summary):
        if area in gazetteer:
            return area, _locality(specific, area), "summary_pattern"

    if isinstance(summary, str):
        hits = []
        for name, area in _scan_names(gazetteer):
            for m in re.finditer(rf"\b{re.escape(name)}\b", summary):
                before = summary[max(0, m.start() - 12):m.start()].lower()
                if re.search(r"\b(?:in|at|near|on|within|of)\s+(?:the\s+)?$", before):
                    hits.append((m.start(), -len(name), name, area))
                    break
        if hits:
            _, _, name, area = min(hits)
            return area, _locality(name, area), "summary_gazetteer"

    return None, None, None


def extract_area(location, summary, city_raw, gazetteer):
    """Return (area, method), or (None, None) when nothing reliable is found."""
    area, _, method = extract_area_detail(location, summary, city_raw, gazetteer)
    return area, method