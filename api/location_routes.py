import hashlib
import json
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from db import connect
from location_index import parse_table, LocationIndex, key

router = APIRouter(prefix='/location-index')
EMPTY = {'clusters': [], 'edges': []}


def current(conn):
    row = conn.execute("SELECT * FROM xm.location_indexes WHERE company_id='xm'").fetchone()
    data = row['data'] if row else EMPTY
    revision = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return data, revision, row


class ImportLocations(BaseModel):
    text: str = Field(min_length=1, max_length=3000000)
    source_name: str = Field(default='CSV lokasi', min_length=1, max_length=200)
    revision: str | None = None


def prepare(payload, existing):
    try:
        data = parse_table(payload.text, existing)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return data


def summary(data, previous):
    return {'clusters':len(data['clusters']), 'pairs':len(data['edges']),
            'new_clusters':len(data['clusters'])-len(previous['clusters']),
            'new_pairs':len(data['edges'])-len(previous['edges']),
            'new_aliases':sum(len(c['aliases']) for c in data['clusters'])-sum(len(c['aliases']) for c in previous['clusters'])}


@router.get('')
def list_locations(search: str='', offset: int=0):
    with connect() as conn:
        data, revision, row = current(conn)
    index=LocationIndex(data)
    clusters=[{**c,'neighbor_count':len(index.neighbors[c['id']])} for c in data['clusters'] if not search.strip() or key(search) in key(' '.join([c['name'],c['area'],*c['aliases']]))]
    clusters.sort(key=lambda c:c['name'])
    start=max(0,offset)
    return {'clusters':clusters[start:start+30],'has_more':len(clusters)>start+30,'total':len(data['clusters']),
            'pairs':len(data['edges']),'filtered_total':len(clusters),'revision':revision,
            'updated_at':row['updated_at'] if row else None,'sources':row['sources'] if row else []}


@router.get('/neighbors')
def neighbors(cluster: str):
    with connect() as conn:
        data, _, _ = current(conn)
    index=LocationIndex(data)
    ident=cluster if cluster in index.clusters else index.terms.get(key(cluster))
    if ident not in index.clusters:
        raise HTTPException(404,'Cluster tidak ditemukan.')
    return {'cluster':index.clusters[ident], 'neighbors':sorted([
        {**index.clusters[target], 'distance_km':distance} for target,distance in index.neighbors[ident].items()
    ],key=lambda c:(c['distance_km'],c['name']))}


@router.post('/preview')
def preview(payload: ImportLocations):
    with connect() as conn:
        previous, revision, _ = current(conn)
    data=prepare(payload,previous)
    return {**summary(data,previous),'revision':revision,'source_name':payload.source_name}


@router.post('/import')
def import_locations(payload: ImportLocations):
    with connect() as conn:
        # Shared with matching/reindex: a running recompute cannot observe half
        # of an import, or finish after the new import and publish stale results.
        conn.execute('SELECT pg_advisory_xact_lock(9042026)')
        conn.execute('SELECT pg_advisory_xact_lock(9042027)')
        previous, revision, row = current(conn)
        if payload.revision != revision:
            raise HTTPException(409,'Indeks berubah. Periksa preview terbaru sebelum menyimpan.')
        data=prepare(payload,previous)
        result=summary(data,previous)
        if data == previous:
            return {**result,'unchanged':True,'job':None}
        job=conn.execute("SELECT * FROM xm.maintenance_jobs WHERE status IN ('queued','processing') LIMIT 1").fetchone()
        if job and job['status'] == 'processing':
            raise HTTPException(409,'Proses ulang masih berjalan. Tunggu selesai, lalu periksa penambahan kembali.')
        sources=list(dict.fromkeys([*(row['sources'] if row else []),payload.source_name]))
        conn.execute("""INSERT INTO xm.location_indexes(company_id,data,sources) VALUES('xm',%s::jsonb,%s::jsonb)
          ON CONFLICT(company_id) DO UPDATE SET data=excluded.data,sources=excluded.sources,updated_at=now()""",(json.dumps(data),json.dumps(sources)))
        if not job:
            job=conn.execute('INSERT INTO xm.maintenance_jobs(id) VALUES(%s) RETURNING *',(uuid.uuid4(),)).fetchone()
        conn.execute("INSERT INTO xm.audit_events(event_type,entity_type,details) VALUES('locations_imported','location_index',%s::jsonb)",(json.dumps(result),))
        conn.commit()
    return {**result,'unchanged':False,'job':job}
