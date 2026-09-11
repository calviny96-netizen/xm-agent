"""Imported, direct cluster distances. No geocoding or inferred paths."""
import csv
import io
import math
import re
import unicodedata
from collections import defaultdict


def key(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    return re.sub(r'[^\w]+', ' ', value).strip()


def parse_table(text, existing=None):
    text = text.lstrip('\ufeff').strip()
    if not text:
        raise ValueError('Tabel kosong.')
    delimiter = '\t' if '\t' in text.splitlines()[0] else ','
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    nearby = next((h for h in headers if h and h.startswith('Cluster Terdekat')), None)
    if not {'Cluster', 'Alias', 'Area/Development'}.issubset(headers) or not nearby:
        raise ValueError('Gunakan kolom Cluster, Alias, Area/Development, dan Cluster Terdekat (dalam radius 4 km).')
    existing = existing or {'clusters': [], 'edges': []}
    clusters = {c['id']: {**c, 'aliases': list(c['aliases'])} for c in existing['clusters']}
    seen, links = set(), []
    for line, row in enumerate(reader, 2):
        if None in row:
            raise ValueError(f'Baris {line}: jumlah kolom berlebih. Gunakan CSV dengan tanda kutip untuk sel yang memuat koma.')
        if not any(row.values()):
            continue
        name = (row.get('Cluster') or '').strip()
        ident = key(name)
        if not ident or len(name) > 200 or ident in seen:
            raise ValueError(f'Baris {line}: nama cluster kosong, terlalu panjang, atau duplikat.')
        seen.add(ident)
        aliases = [s.strip() for s in (row.get('Alias') or '').split(';') if s.strip()]
        area = (row.get('Area/Development') or '').strip()
        if ident in clusters:
            old = clusters[ident]
            if area and old['area'] and key(area) != key(old['area']):
                raise ValueError(f'Baris {line}: area cluster berbeda dari data tersimpan: {name}')
            old['aliases'] = list({key(a): a for a in [*old['aliases'], *aliases]}.values())
            old['area'] = old['area'] or area
        else:
            clusters[ident] = {'id': ident, 'name': name, 'aliases': aliases, 'area': area}
        for part in (row.get(nearby) or '').split(';'):
            if not part.strip():
                continue
            match = re.fullmatch(r'\s*(.+)\s+\((\d+(?:[.,]\d+)?)\)\s*', part)
            if not match:
                raise ValueError(f'Baris {line}: jarak tidak valid: {part[:100]}')
            distance = float(match[2].replace(',', '.'))
            if not math.isfinite(distance) or not 0 <= distance <= 4:
                raise ValueError(f'Baris {line}: jarak harus 0–4 km.')
            links.append((ident, key(match[1]), distance, line))
    if not clusters or len(clusters) > 5000:
        raise ValueError('Isi 1–5.000 cluster.')
    if len(links) > 100000:
        raise ValueError('Maksimal 100.000 hubungan lokasi.')
    edges = {tuple(sorted((e['a'], e['b']))): e['distance_km'] for e in existing['edges']}
    for a, b, distance, line in links:
        if b not in clusters:
            raise ValueError(f'Baris {line}: cluster tujuan belum ada dalam tabel: {b}')
        if a == b:
            raise ValueError(f'Baris {line}: hubungan ke cluster sendiri tidak diperlukan.')
        pair = tuple(sorted((a, b)))
        if pair in edges and edges[pair] != distance:
            raise ValueError(f'Baris {line}: jarak berbeda dari catatan lain/tersimpan untuk {clusters[a]["name"]} dan {clusters[b]["name"]}.')
        edges[pair] = distance
    # Explicit aliases must identify one cluster. Optional abbreviated base names
    # are added by the resolver only when unambiguous.
    terms = {}
    for ident, cluster in clusters.items():
        for alias in [cluster['name'], *cluster['aliases']]:
            term = key(alias)
            if not term or len(alias) > 200 or (term in terms and terms[term] != ident):
                raise ValueError(f'Alias tidak unik atau tidak valid: {alias}')
            terms[term] = ident
    return {'clusters': list(clusters.values()), 'edges': [{'a': a, 'b': b, 'distance_km': d} for (a, b), d in sorted(edges.items())]}


class LocationIndex:
    def __init__(self, data=None):
        data = data or {'clusters': [], 'edges': []}
        self.clusters = {c['id']: c for c in data['clusters']}
        self.neighbors = defaultdict(dict)
        for edge in data['edges']:
            self.neighbors[edge['a']][edge['b']] = edge['distance_km']
            self.neighbors[edge['b']][edge['a']] = edge['distance_km']
        terms = defaultdict(set)
        for ident, c in self.clusters.items():
            for name in [c['name'], *c['aliases']]:
                terms[key(name)].add(ident)
            base = re.sub(r'\s*\([^)]*\)', '', c['name']).strip()
            terms[key(base)].add(ident)
        self.terms = {t: next(iter(ids)) for t, ids in terms.items() if len(ids) == 1}
        self.pattern = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(t) for t in sorted(self.terms, key=len, reverse=True)) + r')(?!\w)') if self.terms else None

    def resolve(self, text, listing=False):
        if not self.pattern:
            return []
        value = key(text)
        found = []
        for m in self.pattern.finditer(value):
            # A nearby landmark is not evidence that the property is IN it.
            if listing and re.search(r'\b(?:dekat|near|menuju|dari|sekitar)\s+(?:\w+\s+){0,2}$', value[max(0,m.start()-40):m.start()]):
                continue
            found.append(self.terms[m.group()])
        return list(dict.fromkeys(found))

    def compare(self, request, listing, request_ids=None, listing_ids=None):
        buyers = request_ids if request_ids is not None else self.resolve(request)
        properties = listing_ids if listing_ids is not None else self.resolve(listing, listing=True)
        if not buyers:
            return {'kind': 'unindexed'}
        if len(properties) != 1:
            return {'kind': 'unknown', 'reason': 'Cluster listing belum teridentifikasi tunggal dalam indeks lokasi'}
        target = properties[0]
        if target in buyers:
            return {'kind': 'exact', 'score': 100.0, 'reason': 'Cluster sama menurut indeks: ' + self.clusters[target]['name']}
        if re.search(r'\b(?:(?:hanya|wajib|harus|khusus|only)\s+(?:di|area|lokasi|cluster|kawasan|in)|tidak mau lokasi lain)\b', request, re.I):
            return {'kind': 'excluded'}
        distances = [(self.neighbors[b][target], b) for b in buyers if target in self.neighbors[b] and self.neighbors[b][target] <= 4]
        if not distances:
            # Missing edges mean unknown, not proven >4 km. Do not offer an
            # unverified alternative under a bounded-radius policy.
            return {'kind': 'excluded'}
        distance, source = min(distances)
        number = f'{distance:g}'.replace('.', ',')
        return {'kind': 'nearby', 'score': 100 - distance * 10, 'distance_km': distance,
                'source': self.clusters[source]['name'], 'target': self.clusters[target]['name'],
                'reason': f'Alternatif lokasi: {self.clusters[source]["name"]} → {self.clusters[target]["name"]} · {number} km menurut data impor (batas 4 km)'}


def load_index(conn, company_id='xm'):
    row = conn.execute('SELECT data FROM xm.location_indexes WHERE company_id=%s', (company_id,)).fetchone()
    return LocationIndex(row['data'] if row else None)
