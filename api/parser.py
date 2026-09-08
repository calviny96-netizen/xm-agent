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
    marker = re.search(r"\b(?:contact|kontak|hubungi|info\s+lanjut|marketing)\s*[:：]?", text, re.I)
    cut = marker.start() if marker else len(text)
    if not marker:
        phone = re.search(PHONE_PATTERN, text)
        if phone:
            line_start = text.rfind("\n", 0, phone.start()) + 1
            prefix = text[line_start:phone.start()]
            if not re.search(r"\b(?:harga|budget|lt|lb|dijual|dicari)\b", prefix, re.I):
                cut = line_start
            else:
                name = re.search(r"[A-Za-z][A-Za-z ]{2,40}\s*[|:-]\s*$", prefix)
                cut = line_start + name.start() if name else phone.start()
    return text[:cut].strip(), text[cut:].strip()

def apply_glossary(text, glossary=None):
    mappings = {**DEFAULT_GLOSSARY, **(glossary or {})}
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
    dimension = re.search(r"(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)", line)
    if dimension:
        result = _number(dimension.group(1)) * _number(dimension.group(2))
        return result, result
    ranged = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:-|–|s/d|sampai|sd)\s*(\d+(?:[.,]\d+)?)", line)
    if ranged:
        return _number(ranged.group(1)), _number(ranged.group(2))
    value = re.search(r"(?:>|min(?:imal)?\.?|mulai)\s*(\d+(?:[.,]\d+)?)", line)
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
    match = re.search(patterns[kind] + r"\s*[:=]?\s*([+~\-\s]*[<>]?[\d].*?)(?=\n|\b(?:lt|lb|kt|km|harga|budget|bangunan|sertifikat|hadap)\b|(?<=m2)\s|$)", text.lower())
    if match:
        return _range_from_line(match.group(1))
    return None, None


def _money_value(number: str, unit: str | None) -> int:
    value = Decimal(str(_number(number)))
    unit = (unit or "").lower()
    multiplier = Decimal(1)
    if unit in {"m", "milyar", "miliar", "b", "bn"}:
        multiplier = Decimal(1_000_000_000)
    elif unit in {"jt", "juta"}:
        multiplier = Decimal(1_000_000)
    elif unit in {"rb", "ribu"}:
        multiplier = Decimal(1_000)
    return int(value * multiplier)


def _price(text: str) -> tuple[int | None, int | None, str | None]:
    for line in re.split(r"\n|(?=\bharga\b|\bbudget\b)", text.lower()):
        if not re.search(r"budge[dt]|harga|sewa|jual", line):
            continue
        line = re.sub(r"(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*(milyar|miliar|juta|jt|m)\b", r"\1 \3 - \2 \3", line)
        values = re.findall(r"(?:rp\.?\s*)?(\d+(?:[.,]\d+)?)\s*(milyar|miliar|juta|jt|ribu|rb|bn|b|m)?\b", line)
        money = [(_money_value(number, unit), unit) for number, unit in values if unit]
        if not money:
            continue
        numbers = [item[0] for item in money]
        basis = "per_m2" if re.search(r"/(?:m2|m²)|per\s*(?:m2|m²|meter)", line) else "per_year" if re.search(r"/th|tahun|per\s*tahun", line) else "total"
        if re.search(r"\b(?:max|maks(?:imal)?|under|dibawah|di bawah)\b", line):
            return None, max(numbers), basis
        if re.search(r"\b(?:min(?:imal)?|mulai|diatas|di atas)\b", line):
            return min(numbers), None, basis
        return min(numbers), max(numbers), basis
    return None, None, None


def _categories(text: str) -> list[str]:
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
    sales_pitch = listing_hits or re.search(r"\b(?:ready|siap huni|bonus|furnished)\b", signal)
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
    text = apply_glossary(body, glossary)
    lower = text.lower()
    flat = normalized(text)
    classification, confidence = _classification(text)
    categories = _categories(flat)
    transaction = "unknown"
    signal = re.sub(r"[^a-z0-9]+", " ", lower)
    if re.search(r"renter|sewa|disewakan|for rent", signal):
        transaction = "rent"
    if re.search(r"buyer|beli|dijual|jual cepat|for sale", signal):
        transaction = "sale"
    land_min, land_max = _areas(text, "land")
    if land_min is None and land_max is None and "land" in categories:
        for line in lower.splitlines():
            if re.search(r"\b(?:uk|ukuran|luas)\b", line):
                land_min, land_max = _range_from_line(line)
                if land_min is not None or land_max is not None:
                    break
    building_min, building_max = _areas(text, "building")
    price_min, price_max, price_basis = _price(text)
    facing_text = " ".join(re.findall(r"(?:hadap|facing)\s*[:=-]?\s*([^\n,.]{2,30})", lower))
    facing = [direction for direction in ("utara", "timur", "selatan", "barat") if re.search(rf"\b{direction}\b", facing_text)]
    exclusions = []
    for expression in re.findall(r"(?:❌|\bno\b|\bnon\b|tidak mau)\s*([^,;\n]{2,35})", lower):
        exclusions.append(expression.strip(" .-_"))
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
    return ParsedDocument(
        classification=classification,
        confidence=confidence,
        transaction_type=transaction,
        categories=categories,
        locations=list(dict.fromkeys(_locations(lower) + [v.lower() for v in {**DEFAULT_GLOSSARY, **(glossary or {})}.values() if re.search(rf"\b{re.escape(v)}\b", lower)])),
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
