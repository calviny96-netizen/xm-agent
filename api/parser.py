import hashlib
import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from decimal import Decimal


CATEGORY_PATTERNS = {
    "warehouse": (r"\bgudang\b", r"warehouse"),
    "factory": (r"\bpabrik\b", r"factory", r"industri"),
    "shophouse": (r"\bruko\b", r"rumah\s+usaha"),
    "villa": (r"\bvilla?\b",),
    "land": (r"\bkav(?:ling)?\b", r"\blahan\b", r"tanah\s+kosong", r"(?:jual|beli|cari|hanya)\s+tanah", r"hitung\s+tanah"),
    "apartment": (r"apart(?:e)?men", r"\bapartment\b", r"\bcondominium\b", r"\bpenthouse\b", r"\bcondo\b"),
    "office": (r"\bkantor\b", r"office"),
    "hotel": (r"\bhotel\b",),
    "house": (r"\brumah\b", r"hunian"),
    "commercial_building": (r"bangunan komersial", r"gedung"),
}

KNOWN_LOCATIONS = [
    "surabaya barat", "surabaya timur", "surabaya utara", "surabaya selatan", "surabaya pusat",
    "surabaya", "sidoarjo", "gresik", "mojokerto", "pasuruan", "malang", "semarang", "jakarta utara",
    "citraland", "galeria golf", "selat golf", "puncak golf", "graha famili", "pakuwon indah",
    "pakuwon city", "rungkut", "rungkut asri", "mayjen sungkono", "ciputra world", "petra",
    "universitas petra", "ubaya", "universitas surabaya", "its", "unair", "margomulyo", "tanjung perak",
    "sambikerep", "semampir", "wiyung", "darmo", "darmo permai", "manyar", "klampis", "klampis indah",
    "klampis anom", "mulyosari", "sutorejo", "jemursari", "margorejo", "kendangsari", "tenggilis",
    "waru", "krian", "pandaan", "lamongan", "denpasar", "badung", "pondok tjandra", "tunjungan",
    "royal residence", "wisata bukit mas", "grand harvest", "greenlake", "northwest boulevard", "g walk",
    "dharmahusada", "kertajaya", "gayungsari", "graha family", "villa valencia", "prambanan",
]

NOISE_EXACT = {
    "mengirim gambar", "mengirim sticker", "message is deleted by user", "mengirim message_history_notice",
}
REQUEST_MARKERS = (
    "buyer request", "buyer need", "buyer cari", "dicari beli", "dicari sewa", "cari beli", "cari sewa",
    "renter request", "request renter", "request buyer", "investor request", "request gudang",
    "buyer req", "renter req", "investor req", "hot renter", "buyer lama request", "kebutuhan buyer",
)
LISTING_MARKERS = (
    "dijual", "disewakan", "jual cepat", "for sale", "for rent", "listing", "harga jual",
)


@dataclass
class ParsedDocument:
    classification: str
    confidence: float
    transaction_type: str = "unknown"
    categories: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    land_area_min: float | None = None
    land_area_max: float | None = None
    building_area_min: float | None = None
    building_area_max: float | None = None
    price_min: int | None = None
    price_max: int | None = None
    price_basis: str | None = None
    negotiable: bool = False
    facing: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_phones: list[str] = field(default_factory=list)
    normalized_text: str = ""

    def dict(self):
        return asdict(self)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u200b", " ").replace("\ufeff", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", clean_text(text).lower())


DEFAULT_GLOSSARY = {"regensi": "regency", "rgcy": "regency", "nashos": "national hospital", "nathos": "national hospital", "graha family": "graha famili", "bdg": "bukit darmo golf"}
PHONE_PATTERN = r"(?:\+?62|0)8[\d .-]{6,15}\d"

def normalize_phone(value):
    digits = re.sub(r"\D", "", value or "")
    return "62" + digits[1:] if digits.startswith("0") else digits

def split_contact(text):
    # Contact headings work both in multiline bubbles and flattened exports.
    markers = list(re.finditer(r"\b(?:contact|kontak|hubungi|info\s+lanjut|marketing)\s*[:：]?", text, re.I))
    core = r'(?im)^\s*[-*•>_ ]*(?:luas|lt\b|lb\b|budget|harga|hadap|cari beli|cari sewa|kamar|row\b)'
    marker = next((m for m in reversed(markers) if not re.search(core,text[m.end():])),None)
    cut = marker.start() if marker else len(text)
    if not marker:
        phones = list(re.finditer(PHONE_PATTERN, text))
        phone = phones[-1] if phones else None
        if phone and re.search(core,text[phone.end():]):
            return re.sub(r'https?://\S+|wa\.me/\S+|' + PHONE_PATTERN,'',text), ''
        if phone:
            line_start = text.rfind("\n", 0, phone.start()) + 1
            prefix = text[line_start:phone.start()]
            if not re.search(r"\b(?:harga|budget|lt|lb|dijual|dicari)\b", prefix, re.I):
                cut = line_start
            else:
                name = re.search(r"[A-Za-z][A-Za-z ]{2,40}\s*[|:-]\s*$", prefix)
                cut = line_start + name.start() if name else phone.start()
    if not marker and cut < len(text):
        before = text[:cut].rstrip()
        paragraph_start = before.rfind('\n\n') + 2
        if paragraph_start > 1:
            block = before[paragraph_start:]
            if len(block) < 220 and not re.search(r'\b(?:harga|budge[dt]|luas|lt|lb|cari|request|rumah|ruko|tanah|apart(?:e)?men|gudang|kamar|syarat)\b',block,re.I):
                cut = paragraph_start
    return text[:cut].strip(), text[cut:].strip()

def glossary_terms(glossary=None):
    # Descriptions explain a term; they are never evidence from a message.
    return {k.lower(): re.split(r"\s+--\s+", v, maxsplit=1)[0].strip()
            for k,v in {**DEFAULT_GLOSSARY, **(glossary or {})}.items() if k and v}


def apply_glossary(text, glossary=None):
    mappings = glossary_terms(glossary)
    pattern = r"(?<!\w)(?:" + "|".join(re.escape(k) for k in sorted(mappings, key=len, reverse=True)) + r")(?!\w)"
    return re.sub(pattern, lambda m: mappings[m.group(0).lower()], text, flags=re.I)


def message_hash(chat_id: str, timestamp: str, author: str, text: str) -> str:
    value = "|".join((chat_id, timestamp, author, normalized(text)))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _number(value: str) -> float:
    value = value.strip().replace(" ", "")
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        tail = value.rsplit(",", 1)[1]
        value = value.replace(".", "").replace(",", "." if len(tail) <= 2 else "")
    elif value.count(".") == 1 and len(value.rsplit(".", 1)[1]) == 3:
        value = value.replace(".", "")
    return float(value)


def _range_from_line(line: str) -> tuple[float | None, float | None]:
    # An explicitly stated area wins over rounded frontage/depth dimensions.
    explicit = re.search(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:m2|m²)\b", line)
    if explicit and not re.search(r"(?:\d\s*(?:-|–|s/d|sampai|sd)|[<>]|min|max|maks)", line[:explicit.start()]):
        value = _number(explicit.group(1))
        return value, value
    dimension = re.search(r"(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)", line)
    if dimension:
        result = _number(dimension.group(1)) * _number(dimension.group(2))
        return result, result
    minimum = re.search(r"\bmin(?:imal|im)?\.?\s*(\d+(?:[.,]\d+)?)", line)
    maximum = re.search(r"\b(?:maks(?:imal)?|max)\.?\s*(\d+(?:[.,]\d+)?)", line)
    if minimum or maximum:
        return _number(minimum[1]) if minimum else None, _number(maximum[1]) if maximum else None
    ranged = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:-|–|s/d|sampai|sd)\s*(\d+(?:[.,]\d+)?)", line)
    if ranged:
        return _number(ranged.group(1)), _number(ranged.group(2))
    value = re.search(r"(?:>|min(?:imal|im)?\.?|mulai)\s*(\d+(?:[.,]\d+)?)", line)
    if value:
        return _number(value.group(1)), None
    value = re.search(r"(?:<|maks(?:imal)?\.?|max)\s*(\d+(?:[.,]\d+)?)", line)
    if value:
        return None, _number(value.group(1))
    values_with_unit = re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²|meter|mtr)\b", line)
    if values_with_unit:
        parsed = _number(values_with_unit[-1])
        return parsed, parsed
    value = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²|meter|mtr)?", line)
    if value:
        parsed = _number(value.group(1))
        return parsed, parsed
    return None, None


def _areas(text: str, kind: str) -> tuple[float | None, float | None]:
    patterns = {
        "land": r"(?:luas\s+tanah|\blt\b|luasan\s+tanah)",
        "building": r"(?:luas\s+bangunan|\blb\b|bangunan)",
    }
    match = re.search(patterns[kind] + r"\s*[.:=]?\s*((?:(?:min(?:imal|im)?|max|maks(?:imal)?)\.?\s*)?[*+±~\-\s]*[<>]?[\d].*?)(?=\n|\b(?:lt|lb|kt|km|harga|budget|bangunan|sertifikat|hadap)\b|(?<=m2)\s|$)", text.lower())
    if match:
        if re.match(r"[*+±~\-\s]*\d+\s*lantai\b", match.group(1)):
            return None, None
        return _range_from_line(match.group(1))
    return None, None


def _money_value(number: str, unit: str | None) -> int:
    amount = number.strip()
    if amount.count(',') == 1:
        amount = amount.replace('.', '').replace(',', '.')
    value = Decimal(amount) if ',' not in amount and amount.count('.') <= 1 else Decimal(str(_number(amount)))
    unit = (unit or "").lower()
    multiplier = Decimal(1)
    if unit in {"m", "milyar", "milyard", "miliar", "miliard", "b", "bn"}:
        multiplier = Decimal(1_000_000_000)
    elif unit in {"jt", "juta"}:
        multiplier = Decimal(1_000_000)
    elif unit in {"rb", "ribu"}:
        multiplier = Decimal(1_000)
    return int(value * multiplier)


def _price(text: str) -> tuple[int | None, int | None, str | None]:
    text = re.sub(r'\bbugdet\b|\bbudged\b', 'budget', text.lower())
    text = re.sub(r'\bjuta+a+n?\b', 'juta', text)
    text = re.sub(r'(?<=\d)man\b', ' m', text)
    for line in re.split(r"\n|(?=\bharga\b|\bbudget\b)", text):
        if not re.search(r"budge[dt]|harga|sewa|jual|under|di bawah|dibawah", line):
            continue
        line = re.sub(r"(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*(milyard?|miliard?|juta|jt|m)\b", r"\1 \3 - \2 \3", line)
        values = re.findall(r"(?:rp\.?\s*)?(\d+(?:[.,]\d+)?)\s*(milyard?|miliard?|juta|jt|ribu|rb|bn|b|m)?\b", line)
        per_area = re.search(r'(\d+(?:[.,]\d+)?)\s*(milyard?|miliard?|juta|jt|ribu|rb|m)\s*(?:/|per)\s*m(?:2|²)',line)
        if per_area:
            amount=_money_value(per_area[1],per_area[2])
            if re.search(r'\b(?:min(?:imal|im)?|mulai|diatas|di atas)\s*[:=]?\s*$',line[:per_area.start()]):
                return amount,None,'per_m2'
            return (None,amount,'per_m2') if re.search(r'\b(?:max|maks|under)\b',line) else (amount,amount,'per_m2')
        money = [(_money_value(number, unit), unit) for number, unit in values if unit]
        if not money:
            continue
        numbers = [item[0] for item in money]
        basis = "per_m2" if re.search(r"/(?:m2|m²)|per\s*(?:m2|m²|meter)", line) else "per_year" if re.search(r"/th|tahun|per\s*tahun", line) else "total"
        if re.search(r"\b(?:max|maks(?:imal)?|under|dibawah|di bawah)\b", line):
            return None, max(numbers), basis
        if re.search(r"\b(?:min(?:imal|im)?|mulai|diatas|di atas)\b", line):
            return min(numbers), None, basis
        return min(numbers), max(numbers), basis
    return None, None, None


def _categories(text: str) -> list[str]:
    # Intended use and interior amenities are not the asset being requested/sold.
    if re.search(r"\btanah\s+(?:spesifikasi|untuk|buat|guna)\b", text):
        return ["land"]
    text = re.split(r"\b(?:cocok|ideal)\s+(?:untuk|utk|buat)\b", text)[0]
    found = []
    for category, patterns in CATEGORY_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            found.append(category)
    if "factory" in found and "warehouse" in found and "pabrik" in text and "gudang" not in text:
        found.remove("warehouse")
    return found


def _locations(text: str) -> list[str]:
    locations = [location for location in KNOWN_LOCATIONS if re.search(rf"\b{re.escape(location)}\b", text)]
    for line in text.splitlines():
        match = re.search(r"(?:lokasi|area|daerah)\s*[:\-]?\s*(.{3,100})", line)
        if match:
            fragments = re.split(r"[,;/]|\s+atau\s+|\s+dan\s+", match.group(1))
            locations.extend(
                fragment.strip(" .-_()") for fragment in fragments
                if 2 < len(fragment.strip()) < 45 and fragment.strip(" .-_()").lower() not in {"sekitarnya", "dan sekitarnya", "bebas", "mana saja"}
            )
    return list(dict.fromkeys(location.lower() for location in locations))[:16]


def _classification(text: str) -> tuple[str, float]:
    lower = normalized(text)
    if not lower or lower in NOISE_EXACT or len(lower) < 18:
        return "ignored", 0.99
    # WhatsApp emphasis often splits phrases (for example ``dicari * sewa``).
    # Use a punctuation-free signal only for intent detection while preserving
    # the original normalised text for indexing and display.
    signal = re.sub(r"[^a-z0-9]+", " ", lower)
    request_hits = sum(marker in signal for marker in REQUEST_MARKERS)
    request_hits += len(re.findall(
        r"\b(?:masih\s+)?(?:dicari|mencari)\b|\b(?:buyer|renter|investor)\s+(?:need|request|req|cari|butuh|survey)\b|\bkebutuhan\s+(?:buyer|renter)\b|\b(?:butuh|cari)\s+(?:segera\s+)?(?:beli|sewa|rumah|ruko|tanah|kavling|gudang|pabrik|villa|apartemen)\b",
        signal,
    ))
    # Group posts commonly use only "HOT/URGENT REQUEST" as the title.
    if re.search(r"^.{0,80}\brequest\b", signal):
        request_hits += 1
    listing_hits = sum(marker in signal for marker in LISTING_MARKERS)
    property_hits = sum(any(re.search(pattern, lower) for pattern in patterns) for patterns in CATEGORY_PATTERNS.values())
    explicit_request = re.search(r"\b(?:dicari|buyer request|buyer need|request buyer|renter request|cari beli|cari sewa)\b", signal)
    sales_pitch = listing_hits or re.search(r"\b(?:ready|siap huni|bonus|furnished|pilihan yang tepat)\b", signal) or re.search(r"cari[^\n?]{0,100}\?",lower)
    concrete_stock = re.search(r"\bharga\b", signal) and re.search(r"\b(?:lt|luas tanah|lb)\b", signal)
    if concrete_stock and sales_pitch and not explicit_request:
        return "property_listing", 0.95
    if request_hits:
        return "buyer_request", min(0.99, 0.78 + request_hits * 0.06 + property_hits * 0.02)
    if listing_hits and property_hits:
        return "property_listing", min(0.98, 0.72 + listing_hits * 0.06 + property_hits * 0.02)
    if property_hits >= 1 and re.search(r"harga|budget|luas|\blt\b|\blb\b", lower):
        return "property_listing", 0.60
    return "ignored", 0.90


def parse_message(text: str, author: str | None = None, glossary: dict | None = None) -> ParsedDocument:
    original = clean_text(text)
    body, signature = split_contact(original)
    text = apply_glossary(re.sub(r'[*_~]', '', body), glossary)
    lower = text.lower()
    flat = normalized(text)
    classification, confidence = _classification(text)
    categories = _categories(normalized(re.sub(r'[*_~]', '', body)))
    if classification == 'property_listing':
        title = re.split(r'\b(?:luas|lt|lb|kamar|harga|fasilitas)\b', normalized(re.sub(r'[*_~]', '', body)), maxsplit=1)[0]
        title_categories = _categories(title)
        if title_categories:
            categories = title_categories
    if 'shophouse' in categories and re.search(r'rumah\s+usaha',flat) and not re.search(r'\brumah\b(?!\s+usaha)',flat):
        categories = [c for c in categories if c != 'house']
    transaction = "unknown"
    signal = re.sub(r"[^a-z0-9]+", " ", lower)
    if re.search(r"renter|sewa|disewakan|for rent", signal):
        transaction = "rent"
    if re.search(r"buyer|beli|dijual|jual cepat|for sale", signal):
        transaction = "sale"
    land_min, land_max = _areas(text, "land")
    if land_min is None and land_max is None and "land" in categories:
        for line in lower.splitlines():
            if re.search(r"\b(?:uk|ukuran|luas|luasan)\b", line):
                land_min, land_max = _range_from_line(line)
                if land_min is not None or land_max is not None:
                    break
    if land_min is None and land_max is None and classification == 'buyer_request' and 'apartment' not in categories:
        for line in lower.splitlines():
            if re.search(r'\b(?:luas|luasan)\b.*\d',line) and not re.search(r'\b(?:bangunan|lb|parkir)\b',line):
                land_min, land_max = _range_from_line(line)
                if re.search(r'ke atas|keatas',line): land_max=None
                break
    building_min, building_max = _areas(text, "building")
    price_text = text
    if classification == 'property_listing' and re.search(r'turun harga|harga turun', lower):
        current = [line for line in text.splitlines() if re.match(r'\s*harga\s*[:=]?\s*(?:rp\.?\s*)?\d',line,re.I)]
        if current: price_text=current[-1]
    price_min, price_max, price_basis = _price(price_text)
    if classification == 'buyer_request' and price_min == price_max and price_max is not None:
        price_min = None
    facing_text = " ".join(re.findall(r"(?:hadap|facing)\s*[:=-]?\s*([^\n,.]{2,30})", lower))
    facing = [direction for direction in ("utara", "timur", "selatan", "barat") if re.search(rf"\b{direction}\b", facing_text)]
    exclusions = []
    for line in lower.splitlines():
        negative = re.search(r"(?:❌|\bno\b|\bnon\b|tidak mau|gamau|g mau)\s*(.+)",line)
        if negative:
            for expression in re.split(r'[,;/]|\s+atau\s+',negative[1]):
                expression=re.sub(r'^(?:tidak mau|area)\s+', '',expression.strip(' .-_*❌'))
                if expression: exclusions.append(expression)
    requirements = []
    for keyword in ("siap huni", "siap pakai", "akses kontainer", "jalan raya", "hook", "shm", "hgb", "non lsd", "dekat tol", "parkiran luas", "full furnish", "minimalis modern"):
        if keyword in lower:
            requirements.append(keyword)
    phone_match = re.search(PHONE_PATTERN, signature or original)
    phone = re.sub(r"\D", "", phone_match.group(0)) if phone_match else None
    if phone and phone.startswith("0"):
        phone = "62" + phone[1:]
    if transaction == "unknown" and classification == "property_listing" and price_max:
        transaction = "sale"
    contact_name = re.sub(r"^(?:contact|kontak|hubungi)\s*[:：]?", "", signature, flags=re.I)
    contact_name = re.split(PHONE_PATTERN + r"|https?://|wa\.me", contact_name)[0].strip(" *_|:-\n")
    places = set(KNOWN_LOCATIONS) | {'regency', 'national hospital', 'garden mansion', 'kawasan industri gresik', 'sidoarjo rangkah industrial estate', 'padepokan cahaya putra'}
    location_text = '\n'.join(re.split(r'tidak mau|gamau|g mau',line)[0] if classification == 'buyer_request' else re.split(r'\b(?:dekat|tidak jauh|menit dari|akses ke)\b',line)[0] for line in lower.splitlines())
    locations = _locations(location_text)
    locations += [v.lower() for k,v in glossary_terms(glossary).items() if (v.lower() in places or ('--' not in (glossary or {}).get(k,'--') and not re.search(r'kamar|sertifikat|furnish|nego|carport|for sale|for rent|luas tanah|luas bangunan',v))) and re.search(rf'\b{re.escape(v)}\b', location_text)]
    return ParsedDocument(
        classification=classification,
        confidence=confidence,
        transaction_type=transaction,
        categories=categories,
        locations=list(dict.fromkeys(locations)),
        land_area_min=land_min,
        land_area_max=land_max,
        building_area_min=building_min,
        building_area_max=building_max,
        price_min=price_min,
        price_max=price_max,
        price_basis=price_basis,
        negotiable=bool(re.search(r"nego|negotiable|harga bu|butuh uang", lower)),
        facing=facing,
        exclusions=list(dict.fromkeys(exclusions))[:12],
        requirements=requirements,
        contact_name=contact_name[:100] or author,
        contact_phone=phone,
        contact_phones=list(dict.fromkeys(normalize_phone(m.group(0)) for m in re.finditer(PHONE_PATTERN, signature or original))),
        normalized_text=flat,
    )


def score_range(req_min, req_max, listing_min, listing_max, tolerance_pct: float) -> tuple[float, str]:
    # PostgreSQL NUMERIC values arrive as Decimal. Normalise here so the
    # tolerance arithmetic behaves the same for API, worker, and unit inputs.
    req_min = float(req_min) if req_min is not None else None
    req_max = float(req_max) if req_max is not None else None
    listing_min = float(listing_min) if listing_min is not None else None
    listing_max = float(listing_max) if listing_max is not None else None
    if req_min is None and req_max is None:
        return 100.0, "Tidak dibatasi"
    if listing_min is None and listing_max is None:
        return 35.0, "Data listing belum tersedia"
    listing_value = listing_min if listing_min is not None else listing_max
    if req_min is not None and listing_value < req_min:
        lower = req_min * (1 - tolerance_pct / 100)
        if listing_value < lower:
            return 0.0, "Di luar toleransi minimum"
        return max(40.0, 100 - ((req_min - listing_value) / req_min * 100 / tolerance_pct * 50)), "Dalam toleransi bawah"
    if req_max is not None and listing_value > req_max:
        upper = req_max * (1 + tolerance_pct / 100)
        if listing_value > upper:
            return 0.0, "Di luar toleransi maksimum"
        return max(40.0, 100 - ((listing_value - req_max) / req_max * 100 / tolerance_pct * 50)), "Dalam toleransi atas"
    return 100.0, "Sesuai rentang"


def location_score(request_locations: list[str], listing_locations: list[str]) -> float:
    if not request_locations:
        return 70.0
    if not listing_locations:
        return 20.0
    req_tokens = set(" ".join(request_locations).split())
    listing_tokens = set(" ".join(listing_locations).split())
    exact = set(request_locations) & set(listing_locations)
    if exact:
        return 100.0
    overlap = len(req_tokens & listing_tokens) / max(1, len(req_tokens))
    return min(90.0, overlap * 100)
