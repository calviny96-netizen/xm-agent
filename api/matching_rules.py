"""Eligibility before ranking. Unknown evidence can never certify a HOT match."""
import re
from functools import lru_cache
from parser import _number, location_score, score_range, split_contact, clean_text


def _range(row, prefix):
    return row.get(prefix + '_min'), row.get(prefix + '_max')


@lru_cache(maxsize=32768)
def _count(text, unit):
    number = r'(?<![\d.,])(\d+(?:[.,]\d+)?)(?:\s*[-–/]\s*(\d+(?:[.,]\d+)?))?'
    if unit == 'bedrooms':
        pattern = rf'(?:\bkt\b|kamar(?: tidur)?|bedrooms?|\bbr\b)\s*(?:(?:min(?:imal|im)?|max|maks(?:imal)?|lebih dari|di atas|diatas|kurang dari)\s*)?[:=]?\s*{number}|{number}\s*(?:bedrooms?|kamar tidur|br)\b'
        m = re.search(pattern, text)
        if not m:
            return None
        values = [_number(v) for v in m.groups() if v is not None]
    else:
        # "lantai 20" in apartments describes unit elevation, not storey count.
        candidates = re.finditer(number + r'(?:[ \t]*lt|\s*(?:lantai|storeys?|floors?))\b', text)
        # LT at the start of the next line means land area, not floors.
        m = next((v for v in candidates if not v[0].endswith('lt') or max(_number(n) for n in v.groups() if n is not None) <= 20), None)
        if not m:
            return None
        values = [_number(v) for v in m.groups() if v is not None]
    qualifier = text[max(0,m.start()-15):m.end()]
    if re.search(r'\b(?:lebih dari|di atas|diatas)\b',qualifier):
        return min(values) + 0.01, float('inf')
    if re.search(r'\bkurang dari\b',qualifier):
        return 0, max(values) - 0.01
    if re.search(r'\bmin(?:imal|im)?\b',qualifier):
        return min(values), float('inf')
    if re.search(r'\b(?:max|maks(?:imal)?)\b',qualifier):
        return 0, max(values)
    return min(values), max(values)


def prepare_document(row, location_index=None):
    text = re.sub(r'[*_~]', '', split_contact(clean_text(row.get('raw_text') or row.get('normalized_text') or ''))[0]).lower()
    row['_rule_text'] = text
    if location_index:
        wanted = re.sub(r'[^\n]*(?:tidak mau|gamau|g mau|❌)[^\n]*','',text)
        row['_geo_ids'] = location_index.resolve(wanted if row.get('document_type') == 'buyer_request' else text,
                                                 listing=row.get('document_type')=='property_listing')
    return row


def assess_pair(request, listing, settings, semantic=50.0, location_index=None):
    if request.get('document_type', request.get('classification', 'buyer_request')) != 'buyer_request':
        return None
    if listing.get('document_type', listing.get('classification', 'property_listing')) != 'property_listing':
        return None
    req_categories = set(request.get('categories') or [])
    categories = req_categories & set(listing.get('categories') or [])
    if not categories:
        return None
    reasons, unknown = [], []
    if request.get('review_status', 'auto') != 'auto' or listing.get('review_status', 'auto') != 'auto':
        unknown.append('Ekstraksi perlu diperiksa')
    req_transaction, transaction = request.get('transaction_type'), listing.get('transaction_type')
    if req_transaction not in (None, 'unknown') and transaction not in (None, 'unknown') and req_transaction != transaction:
        return None
    if req_transaction in (None, 'unknown') or transaction in (None, 'unknown'):
        unknown.append('Jenis transaksi belum terverifikasi')
    req_text = request.get('_rule_text') or re.sub(r'[*_~]', '', split_contact(clean_text(request.get('raw_text') or request.get('normalized_text') or ''))[0]).lower()
    text = listing.get('_rule_text') or re.sub(r'[*_~]', '', split_contact(clean_text(listing.get('raw_text') or listing.get('normalized_text') or ''))[0]).lower()
    if len(re.findall(r'\b(?:dijual|disewakan|harga)\b', text)) >= 4:
        unknown.append('Pesan berisi beberapa penawaran/harga; spesifikasi perlu dipisahkan')
    for excluded in request.get('exclusions') or []:
        token = excluded.strip(' *_')
        if token and re.search(r'(?<!\w)' + re.escape(token) + r'(?!\w)', text):
            return None
    # Mandatory conditions that need evidence cannot disappear from the score.
    if re.search(r'tidak mau|gamau|g mau|\bno\b|❌', req_text):
        unknown.append('Larangan buyer perlu diverifikasi seluruhnya')
    if re.search(r'(?:murah|\bbu\b|bawah pasar|dibawah pasaran|di bawah pasaran)', req_text):
        unknown.append('Harga murah/BU perlu pembanding pasar; harga nego bukan bukti')
    if re.search(r'parkir|parkiran', req_text):
        unknown.append('Ketersediaan dan ketentuan parkir perlu diverifikasi')
    if re.search(r'banjir|macet|residensial|zona|zoning', req_text):
        unknown.append('Kondisi lingkungan/zona perlu diverifikasi')
    if re.search(r'marmer|rumah baru|rumah gress|rumah jelek|rumah lama|bisa di\s*bongkar|hitung tanah', req_text):
        unknown.append('Kondisi bangunan yang diminta perlu diverifikasi')
    if re.search(r'peruntukan|tempat les|usaha|untuk kantor', req_text):
        unknown.append('Kesesuaian penggunaan bangunan perlu diverifikasi')
    if re.search(r'untuk dibuat kantor|akses.*(?:truk|cdd|kontainer)|bisa kpr|rencana kpr|\bkpr\b',req_text):
        unknown.append('Akses/penggunaan atau pembiayaan khusus perlu dikonfirmasi')
    if re.search(r'carport|garasi|tidak ada tetangga|jangan|ga mau',req_text):
        unknown.append('Fasilitas atau larangan tambahan buyer perlu diverifikasi')
    if len(re.findall(r'\b(?:request|renter|buyer)\b',req_text)) >= 5:
        unknown.append('Pesan berisi beberapa kebutuhan; perlu dipisahkan')
    for refinement in re.findall(r'\bdistrict\s+\w+',req_text):
        if refinement not in text: unknown.append('Lokasi spesifik ' + refinement + ' belum terkonfirmasi')
    if re.search(r'tengah kota|pusat kota',req_text) and not re.search(r'tengah kota|pusat kota',text):
        unknown.append('Lokasi pusat kota belum terkonfirmasi')
    if re.search(r'sudah tersewa|masih tersewa|masih disewa|sedang disewa',text):
        unknown.append('Properti masih tersewa; waktu penyerahan perlu dikonfirmasi')
    if re.search(r'proses finishing|proses renovasi|sedang dibangun|belum selesai|sebelum renovasi selesai|setelah renovasi selesai',text):
        unknown.append('Kondisi/harga setelah pekerjaan bangunan selesai perlu dikonfirmasi')
    for requirement in ('berpagar', 'kontainer', 'container', '40 feet', 'marmer'):
        if requirement in req_text and requirement not in text:
            unknown.append('Belum ada bukti: ' + requirement)
    if 'citraland utama' in req_text and 'citraland utama' not in text:
        unknown.append('Batas area Citraland Utama belum terkonfirmasi')
    if re.search(r'(?:hanya|only|wajib|harus).{0,30}(?:raya|jalan)|(?:raya|jalan).{0,30}(?:only|hanya)',req_text):
        unknown.append('Alamat/jalan wajib buyer perlu dikonfirmasi')
    for label, pattern in [
        ('Lebar', r'\blebar\s*(?:(min(?:imal|im)?|maks(?:imal)?|max)\.?\s*)?[:=]?\s*(\d+(?:[.,]\d+)?)'),
        ('ROW jalan', r'\brow\s*(?:jalan\s*)?(?:(min(?:imal|im)?|maks(?:imal)?|max)\.?\s*)?[:=]?\s*(\d+(?:[.,]\d+)?)\s*(mobil|mbl|m(?:eter)?)?')]:
        need = re.search(pattern,req_text)
        if not need: continue
        have = re.search(pattern,text)
        value = _number(have[2]) if have else None
        if label == 'Lebar' and value is None:
            dims = re.search(r'(\d+(?:[.,]\d+)?)\s*[x×]\s*\d',text)
            if dims: value=_number(dims[1])
        if label == 'ROW jalan' and have and (need[3] or '') != (have[3] or ''):
            value=None
        if value is None:
            unknown.append(label + ' belum tersedia dalam satuan yang sesuai')
        elif (need[1] in {'max','maks','maksimal'} and value > _number(need[2])) or (need[1] not in {'max','maks','maksimal'} and value < _number(need[2])):
            return None
        else: reasons.append(label + ' sesuai')
    facing = set(request.get('facing') or [])
    if facing:
        available = set(listing.get('facing') or [])
        if available and not facing.intersection(available):
            return None
        if not available:
            unknown.append('Hadap belum tersedia')
        else:
            reasons.append('Hadap sesuai')
    view = re.search(r'\bview\s+([a-z]+(?:\s+[a-z]+){0,2})(?=[,()\n]|$)', req_text)
    if view and view.group(1).strip() not in text:
        unknown.append('View ' + view.group(1).strip() + ' belum terverifikasi')
    dimension_pattern = r'(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)'
    need_dimensions = re.search(dimension_pattern, req_text)
    if need_dimensions:
        dimensions = re.search(dimension_pattern, text)
        if not dimensions:
            unknown.append('Dimensi lebar × panjang belum tersedia')
        else:
            for need, have in zip(need_dimensions.groups(), dimensions.groups()):
                value, _ = score_range(_number(need), _number(need), _number(have), _number(have), float(settings['land_tolerance_pct']))
                if value == 0:
                    return None
                if value < 100:
                    unknown.append('Dimensi masih memerlukan toleransi')
    for unit, label in [('bedrooms', 'Kamar tidur'), ('floors', 'Jumlah lantai')]:
        need, have = _count(req_text, unit), _count(text, unit)
        if not need:
            continue
        if unit == 'bedrooms' and have is None and 'apartment' in categories and re.search(r'\b(?:tipe|type|unit)\s+studio\b', text):
            have = (0, 0)
        if unit == 'floors' and req_categories == {'land'}:
            unknown.append(f'Kelayakan pembangunan {need[0]:g} lantai perlu verifikasi')
            continue
        if have and (have[1] < need[0] or have[0] > need[1]):
            return None
        if have is None:
            unknown.append(label + ' belum tersedia')
        else:
            reasons.append(label + ' sesuai')
    if re.search(r'\b(?:row|akses|jalan)\b.{0,20}\b(?:besar|lebar)\b', req_text):
        unknown.append('Lebar akses jalan perlu verifikasi')
    for requirement in request.get('requirements') or []:
        if requirement not in (listing.get('requirements') or []):
            unknown.append('Belum terverifikasi: ' + requirement)
    req_locations, locations = request.get('locations') or [], listing.get('locations') or []
    wanted_text = re.sub(r'[^\n]*(?:tidak mau|gamau|g mau|❌)[^\n]*','',req_text)
    proximity = location_index.compare(wanted_text, text, request.get('_geo_ids'), listing.get('_geo_ids')) if location_index else {'kind': 'unindexed'}
    if proximity['kind'] == 'excluded':
        return None
    loc = location_score(req_locations, locations)
    if proximity['kind'] in {'exact', 'nearby'}:
        loc = proximity['score']
        reasons.insert(0, proximity['reason'])
        if proximity['kind'] == 'nearby':
            unknown.insert(0, 'Alternatif dalam 4 km; perlu persetujuan lokasi buyer')
    elif proximity['kind'] == 'unknown':
        unknown.append(proximity['reason'])
    if proximity['kind'] == 'unindexed' and req_locations and locations and loc == 0:
        return None
    # City-level overlap cannot confirm a named district, cluster, or tower.
    regions = {'surabaya barat', 'surabaya timur', 'surabaya utara', 'surabaya selatan', 'surabaya pusat'}
    if proximity['kind'] == 'unindexed' and set(req_locations) & regions and set(locations) & regions and not set(req_locations).intersection(locations).intersection(regions):
        return None
    specific = [v for v in req_locations if v != 'surabaya' and v not in regions]
    # A shared parent word is not proof of a requested neighbourhood/street.
    specific = [v for v in specific if not any(v != other and v in other for other in specific)]
    available_specific = [v for v in locations if not any(v != other and v in other for other in locations)]
    if not specific:
        specific = [v for v in req_locations if v != 'surabaya']
    if proximity['kind'] == 'unindexed' and (not req_locations or not locations or not set(specific or req_locations).intersection(locations)):
        unknown.append('Lokasi kebutuhan belum terkonfirmasi')
    if proximity['kind'] == 'unindexed' and specific and not set(specific).intersection(available_specific):
        unknown.append('Kawasan/alamat spesifik belum terkonfirmasi')
    # A named apartment tower is more specific than a development/city.
    tower = re.search(r'\bapart(?:e)?men\s+([a-z]+)', req_text)
    if tower and tower.group(1) not in {'di', 'daerah', 'area', 'surabaya', 'yang'} and not re.search(r'\b' + re.escape(tower.group(1)) + r'\b', text):
        named_tower = re.search(r'\btower\s+([a-z]+)\b', text)
        named_apartment = re.search(r'\bapart(?:e)?men\s+([a-z]+)\b', text)
        generic = {'di', 'daerah', 'area', 'surabaya', 'yang', 'mewah', 'murah', 'full', 'baru', 'siap', 'luas', 'type', 'tipe', 'studio', 'the'}
        named_conflict = named_tower and len(named_tower.group(1)) > 1 and named_tower.group(1) != tower.group(1)
        if named_apartment and named_apartment.group(1) not in generic and named_apartment.group(1) not in req_text:
            named_conflict = True
        if named_conflict:
            return None
        unknown.append('Nama apartemen/tower belum terkonfirmasi')
    values = {'location': loc, 'semantic': semantic,
              'data_quality': (float(request.get('extraction_confidence', 0)) + float(listing.get('extraction_confidence', 0))) * 50}
    active = {'location', 'semantic', 'data_quality'}
    details = []
    for prefix, factor, label in [('land_area', 'land', 'Luas tanah'), ('building_area', 'building', 'Luas bangunan'), ('price', 'price', 'Harga')]:
        need, have = _range(request, prefix), _range(listing, prefix)
        if need == (None, None):
            values[factor] = 0.0
            details.append(label + ': tidak diminta (tidak menambah skor)')
            continue
        active.add(factor)
        tolerance = float(settings[factor + '_tolerance_pct'])
        if factor == 'price':
            if request.get('price_basis') and listing.get('price_basis') and request['price_basis'] != listing['price_basis']:
                return None
            if not request.get('price_basis') or not listing.get('price_basis'):
                unknown.append('Basis harga belum terverifikasi')
            if not listing.get('negotiable'):
                tolerance = 0
            if need[1] is not None and have[0] is not None and float(have[0]) >= float(need[1]) and re.search(r'\bunder\b|di bawah|dibawah',req_text):
                if listing.get('negotiable'):
                    unknown.append('Harga harus di bawah batas buyer; perlu negosiasi')
                else:
                    return None
        value, reason = score_range(*need, *have, tolerance)
        if value == 0:
            return None
        values[factor] = value
        details.append(label + ': ' + reason)
        if have == (None, None):
            unknown.append(label + ' listing belum tersedia')
        elif value < 100:
            unknown.append(label + ' masih memerlukan toleransi')
    weight = sum(float(settings[k + '_weight_pct']) for k in active)
    score = sum(values[k] * float(settings[k + '_weight_pct']) for k in active) / weight if weight else 0
    if unknown:
        score = min(score, 79.0)
    if re.search(r'(?:budget|budged|budjet|bugdet|harga|under).{0,20}\d',req_text) and request.get('price_min') is None and request.get('price_max') is None:
        unknown.append('Angka budget belum terbaca lengkap; pasangan ditahan')
        score=min(score,59.0)
    if len(re.findall(r'(?m)^\s*\d+[.)]\s*(?:dijual|disewakan)\b',text)) >= 2:
        unknown.append('Beberapa listing dalam satu pesan; ditahan sampai spesifikasi tiap properti dipisahkan')
        score=min(score,59.0)
    if proximity['kind'] == 'nearby':
        # Preserve distance ordering within the WARM band, even when other
        # factors would otherwise push all nearby alternatives to the same cap.
        score = min(score, 79.0 - proximity['distance_km'] * 3)
    explanation = reasons + list(dict.fromkeys(unknown)) + ['Kategori aset cocok: ' + ', '.join(sorted(categories)), f'Lokasi {loc:.0f}%'] + details
    return {'score': round(score, 2), **values, 'explanation': explanation}
