import json
import uuid
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from db import connect
from parser import normalize_phone
from reindex import glossary_values
from auth import current_user

router = APIRouter()

class Settings(BaseModel):
    land_tolerance_pct: float = Field(ge=0, le=100)
    building_tolerance_pct: float = Field(ge=0, le=100)
    price_tolerance_pct: float = Field(ge=0, le=100)
    location_weight_pct: float = Field(ge=0, le=100)
    land_weight_pct: float = Field(ge=0, le=100)
    building_weight_pct: float = Field(ge=0, le=100)
    price_weight_pct: float = Field(ge=0, le=100)
    semantic_weight_pct: float = Field(ge=0, le=100)
    data_quality_weight_pct: float = Field(ge=0, le=100)

    def validate_weights(self):
        total = sum((
            self.location_weight_pct,
            self.land_weight_pct,
            self.building_weight_pct,
            self.price_weight_pct,
            self.semantic_weight_pct,
            self.data_quality_weight_pct,
        ))
        if abs(total - 100) > 0.001:
            raise HTTPException(400, "Total bobot pencocokan harus 100%")

class Glossary(BaseModel):
    entries: dict[str, str]

@router.put('/settings')
def save_settings(payload: Settings):
    payload.validate_weights()
    with connect() as conn:
        conn.execute(
            '''UPDATE xm.match_settings SET land_tolerance_pct=%s, building_tolerance_pct=%s,
               price_tolerance_pct=%s, location_weight_pct=%s, land_weight_pct=%s,
               building_weight_pct=%s, price_weight_pct=%s, semantic_weight_pct=%s,
               data_quality_weight_pct=%s, updated_at=now() WHERE company_id='xm' ''',
            tuple(payload.model_dump().values()),
        )
        conn.commit()
    return payload

@router.get('/glossary')
def get_glossary():
    with connect() as conn:
        return glossary_values(conn)


class Preferences(BaseModel):
    direction: Literal['buyer', 'property'] = 'buyer'
    statuses: list[Literal['hot', 'warm', 'unmatched']] = ['hot', 'warm', 'unmatched']


@router.get('/preferences')
def get_preferences(request: Request):
    user = current_user(request)
    with connect() as conn:
        row = conn.execute(
            'SELECT preferences FROM xm.user_preferences WHERE user_id=%s',
            (user['id'],),
        ).fetchone()
    return row['preferences'] if row else Preferences().model_dump()


@router.put('/preferences')
def save_preferences(payload: Preferences, request: Request):
    user = current_user(request)
    with connect() as conn:
        conn.execute(
            '''INSERT INTO xm.user_preferences(user_id, preferences) VALUES(%s,%s::jsonb)
               ON CONFLICT(user_id) DO UPDATE SET preferences=excluded.preferences, updated_at=now()''',
            (user['id'], json.dumps(payload.model_dump())),
        )
        conn.commit()
    return payload

@router.put('/glossary')
def save_glossary(payload: Glossary):
    entries = {k.strip().lower():v.strip().lower() for k,v in payload.entries.items()}
    if len(entries) > 500 or any(not k or not v or len(k)>100 or len(v)>100 for k,v in entries.items()):
        raise HTTPException(400, 'Istilah dan nama baku wajib diisi (maks. 100 karakter, 500 istilah).')
    with connect() as conn:
        conn.execute('DELETE FROM xm.glossary')
        for k,v in entries.items():
            conn.execute('INSERT INTO xm.glossary(alias,canonical) VALUES(%s,%s)',(k,v))
        conn.commit()
    return entries

@router.post('/index/recompute', status_code=202)
def rebuild_index():
    with connect() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(9042027)')
        current=conn.execute("SELECT * FROM xm.maintenance_jobs WHERE status IN ('queued','processing') LIMIT 1").fetchone()
        if current: return current
        row=conn.execute('INSERT INTO xm.maintenance_jobs(id) VALUES(%s) RETURNING *',(uuid.uuid4(),)).fetchone()
        conn.commit()
        return row

@router.get('/index/status')
def index_status():
    with connect() as conn:
        return conn.execute('SELECT * FROM xm.maintenance_jobs ORDER BY created_at DESC LIMIT 1').fetchone()

def date_filter(date_from, date_to, time_from='00:00', time_to='23:59'):
    from datetime import date, time, datetime, timedelta
    import re
    if any(not re.fullmatch(r'\d{2}:\d{2}', v) for v in (time_from,time_to)):
        raise HTTPException(400,'Jam tidak valid; gunakan HH:MM.')
    try:
        lower = datetime.combine(date.fromisoformat(date_from),time.fromisoformat(time_from)) if date_from else None
        upper = datetime.combine(date.fromisoformat(date_to),time.fromisoformat(time_to)) if date_to else None
    except ValueError:
        raise HTTPException(400,'Tanggal atau jam tidak valid.')
    if lower and upper and lower > upper:
        raise HTTPException(400,'Awal rentang tidak boleh melewati akhir rentang.')
    clause, params = '', []
    if lower:
        clause += ' AND r.sent_at >= %s'
        params.append(lower)
    if upper:
        clause += ' AND r.sent_at < %s'
        params.append(upper + timedelta(minutes=1))
    return clause, params


@router.get('/workspace/dates')
def workspace_dates(direction: Literal['buyer','property']='buyer', date_from: str='', date_to: str=''):
    from datetime import date
    try:
        start,end=date.fromisoformat(date_from),date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(400,'Tanggal tidak valid.')
    if not 0 < (end-start).days <= 93:
        raise HTTPException(400,'Rentang kalender maksimal 93 hari.')
    kind='buyer_request' if direction=='buyer' else 'property_listing'
    with connect() as conn:
        import workspace_cache
        if workspace_cache.ready(conn):
            latest=conn.execute("SELECT max(last_seen_at)::date latest_date FROM xm.document_groups WHERE company_id='xm' AND document_type=%s",(kind,)).fetchone()
            rows=conn.execute('''SELECT r.sent_at::date posted_day,count(DISTINCT gm.group_id) count
              FROM xm.document_group_members gm JOIN xm.document_groups g ON g.group_id=gm.group_id
              JOIN xm.documents d ON d.id=gm.document_id JOIN xm.raw_messages r ON r.id=d.raw_message_id
              WHERE g.company_id='xm' AND g.document_type=%s AND r.sent_at >= %s AND r.sent_at < %s
              GROUP BY r.sent_at::date''',(kind,start,end)).fetchall()
            return {'counts':{str(row['posted_day'])[:10]:int(row['count']) for row in rows},
                    'latest_date':str(latest['latest_date'])[:10] if latest['latest_date'] else None}
        latest=conn.execute("""SELECT max(r.sent_at)::date AS latest_date
          FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id
          WHERE d.company_id='xm' AND d.active AND d.document_type=%s""",(kind,)).fetchone()
        rows=conn.execute("""SELECT r.sent_at::date AS posted_day,count(DISTINCT r.raw_text) AS count
          FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id
          WHERE d.company_id='xm' AND d.active AND d.document_type=%s
            AND r.sent_at >= %s AND r.sent_at < %s GROUP BY r.sent_at::date""",(kind,start,end)).fetchall()
    return {'counts': {str(row['posted_day'])[:10]:int(row['count']) for row in rows},
            'latest_date': str(latest['latest_date'])[:10] if latest['latest_date'] else None}


@router.get('/workspace')
def workspace(direction: Literal['buyer','property']='buyer', search: str='', phones: str='', statuses: str='hot,warm,unmatched', date_from: str='', date_to: str='', offset: int=0, time_from: str='00:00', time_to: str='23:59'):
    import workspace_cache
    clause, date_params = date_filter(date_from,date_to,time_from,time_to)
    with connect() as conn:
        if workspace_cache.ready(conn):
            return workspace_cache.sources(conn,direction,search,phones,statuses,clause,date_params,offset)
    kind, relation = ('buyer_request','buyer_request_id') if direction=='buyer' else ('property_listing','property_listing_id')
    other = 'property_listing_id' if direction == 'buyer' else 'buyer_request_id'
    selected=set(statuses.split(','))
    all_statuses={'hot','warm','unmatched'}.issubset(selected)
    # With every status included, paginate groups before counting their matches.
    # This avoids aggregating the entire match archive just to show 200 cards.
    page_cte = ''
    if all_statuses:
        page_cte = '''), page AS (
          SELECT * FROM ranked WHERE group_rank=1
          ORDER BY sent_at DESC NULLS LAST,id LIMIT 201 OFFSET %s'''
    query = """WITH eligible AS (
       SELECT d.*,r.raw_text,r.chat_name,r.sent_at
       FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id
       WHERE d.company_id='xm' AND d.active AND d.document_type=%s"""
    params=[kind]
    if search.strip():
        query += " AND (d.normalized_text ILIKE %s OR coalesce(d.contact_name,'') ILIKE %s)"
        params += ['%'+search.strip()+'%']*2
    if phones.strip() and direction=='property':
        import re
        numbers=[normalize_phone(v) for v in re.split(r'[,;\n]+',phones) if v.strip()]
        if any(not n.startswith('628') or not 10<=len(n)<=15 for n in numbers):
            raise HTTPException(400,'Nomor tidak valid. Pisahkan beberapa nomor dengan koma atau baris baru.')
        # Read all contact numbers in a signature, including second/alternate numbers.
        query += " AND (d.contact_phones && %s::text[] OR d.contact_phone = ANY(%s))"
        params.extend([numbers,numbers])
    clause, date_params = date_filter(date_from,date_to,time_from,time_to)
    query += clause
    params.extend(date_params)
    query += f"""), ranked AS (
       SELECT eligible.*, row_number() OVER(PARTITION BY raw_text ORDER BY sent_at DESC NULLS LAST,id) group_rank,
              count(*) OVER(PARTITION BY raw_text) duplicate_count
       FROM eligible
    {page_cte}
    ), pairs AS (
       SELECT e.raw_text, tr.raw_text target_text, max(m.score) score
       FROM (SELECT DISTINCT raw_text FROM {'page' if all_statuses else 'eligible'}) e
       JOIN xm.raw_messages sr ON sr.company_id='xm' AND md5(sr.raw_text)=md5(e.raw_text) AND sr.raw_text=e.raw_text
       JOIN xm.documents source ON source.raw_message_id=sr.id AND source.company_id='xm' AND source.active
           AND source.document_type='{kind}'
       JOIN xm.matches m ON m.{relation}=source.id AND m.company_id='xm'
       JOIN xm.documents t ON t.id=m.{other} AND t.active AND t.company_id='xm'
       JOIN xm.raw_messages tr ON tr.id=t.raw_message_id
       WHERE m.score>=60 GROUP BY e.raw_text,tr.raw_text
    ), counts AS (
       SELECT raw_text,count(*) match_count,count(*) FILTER(WHERE score>=80) hot_count,
              count(*) FILTER(WHERE score<80) warm_count FROM pairs GROUP BY raw_text
    ) SELECT d.*,coalesce(c.match_count,0) match_count,coalesce(c.hot_count,0) hot_count,
             coalesce(c.warm_count,0) warm_count
      FROM {'page' if all_statuses else 'ranked'} d LEFT JOIN counts c USING(raw_text) WHERE group_rank=1 AND ("""
    filters=[]
    if 'hot' in selected: filters.append('coalesce(c.hot_count,0)>0')
    if 'warm' in selected: filters.append('coalesce(c.warm_count,0)>0')
    if 'unmatched' in selected: filters.append('coalesce(c.match_count,0)=0')
    query+=' OR '.join(filters or ['false'])+') ORDER BY d.sent_at DESC NULLS LAST,d.id'
    if not all_statuses:
        query+=' LIMIT 201 OFFSET %s'
    params.append(max(0,offset))
    with connect() as conn: rows=conn.execute(query,params).fetchall()
    return {'rows':rows[:200],'has_more':len(rows)>200}

class Batch(BaseModel):
    direction: Literal['buyer','property']='buyer'
    ids: list[uuid.UUID] = Field(max_length=50)

@router.post('/workspace/recommendations')
def recommendations(payload: Batch):
    relation, other, kind = ('buyer_request_id','property_listing_id','buyer_request') if payload.direction=='buyer' else ('property_listing_id','buyer_request_id','property_listing')
    ids=list(dict.fromkeys(payload.ids))
    with connect() as conn:
        import workspace_cache
        if workspace_cache.ready(conn):
            return workspace_cache.recommendations(conn,payload.direction,ids)
        sources=conn.execute('''SELECT d.*,r.raw_text,r.chat_name,r.sent_at FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id WHERE d.company_id='xm' AND d.active AND d.id=ANY(%s) AND d.document_type=%s''',(ids,kind)).fetchall()
        # Resolve all copies of a selected source; aggregate before rendering so
        # copies with different historic candidate edges do not lose matches.
        rows=conn.execute(f'''WITH source_copies AS (
          SELECT chosen.id source_id, copy.id copy_id
          FROM xm.documents chosen JOIN xm.raw_messages cr ON cr.id=chosen.raw_message_id
          JOIN xm.raw_messages rr ON md5(rr.raw_text)=md5(cr.raw_text) AND rr.raw_text=cr.raw_text AND rr.company_id=chosen.company_id
          JOIN xm.documents copy ON copy.raw_message_id=rr.id AND copy.active
             AND copy.company_id=chosen.company_id AND copy.document_type=chosen.document_type
          WHERE chosen.company_id='xm' AND chosen.active AND chosen.id=ANY(%s) AND chosen.document_type=%s
        ) SELECT m.id match_id,s.source_id,m.score,m.explanation,d.*,r.raw_text,r.chat_name,r.sent_at
          FROM source_copies s JOIN xm.matches m ON m.{relation}=s.copy_id
          JOIN xm.documents d ON d.id=m.{other} JOIN xm.raw_messages r ON r.id=d.raw_message_id
          WHERE m.company_id='xm' AND d.company_id='xm' AND d.active AND m.score>=60
          ORDER BY m.score DESC,r.sent_at DESC NULLS LAST,d.id''',(ids,kind)).fetchall()
    return {'groups':[{'source':s,'recommendations':group_identical([r for r in rows if r['source_id']==s['id']])} for s in sources]}


def group_identical(rows):
    """Full raw text equality only; never merge different contact signatures."""
    groups = {}
    for row in rows:
        key = row['raw_text']
        if key not in groups:
            groups[key] = {**row, 'duplicate_count': 0, '_ids': set(), 'last_seen_at': row.get('sent_at')}
        group = groups[key]
        if row.get('sent_at') and (not group['last_seen_at'] or row['sent_at'] > group['last_seen_at']):
            group['last_seen_at'] = row['sent_at']
        group['_ids'].add(row['id'])
        group['duplicate_count'] = len(group['_ids'])
    return [{k: v for k, v in row.items() if k != '_ids'} for row in groups.values()]


class ExportPair(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID | None=None

class Export(BaseModel):
    direction: Literal['buyer','property']='buyer'
    pairs: list[ExportPair] = Field(min_length=1,max_length=200)

@router.post('/export/pdf')
def export_pdf(payload: Export):
    from report import build_report
    groups=recommendations(Batch(direction=payload.direction,ids=list(dict.fromkeys(p.source_id for p in payload.pairs))))['groups']
    selected=[]
    for p in payload.pairs:
        group=next((g for g in groups if g['source']['id']==p.source_id),None)
        if group is None: raise HTTPException(404,'Data pilihan tidak ditemukan')
        target=next((r for r in group['recommendations'] if r['id']==p.target_id),None)
        if p.target_id and target is None: raise HTTPException(409,'Hasil pencocokan berubah. Muat ulang lalu pilih kembali.')
        if not p.target_id and group['recommendations']: raise HTTPException(409,'Data sudah memiliki kecocokan. Muat ulang hasil.')
        selected.append((group['source'],target))
    return Response(build_report(selected,payload.direction),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="XM-Matching-Report.pdf"'})
