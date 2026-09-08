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

@router.get('/workspace')
def workspace(direction: Literal['buyer','property']='buyer', search: str='', phones: str='', statuses: str='hot,warm,unmatched', date_from: str='', date_to: str='', offset: int=0):
    kind, relation = ('buyer_request','buyer_request_id') if direction=='buyer' else ('property_listing','property_listing_id')
    query = f'''SELECT d.*,r.raw_text,r.chat_name,r.sent_at,
       count(m.id) FILTER(WHERE m.score>=60) match_count,
       count(m.id) FILTER(WHERE m.score>=80) hot_count,
       count(m.id) FILTER(WHERE m.score>=60 AND m.score<80) warm_count
       FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id
       LEFT JOIN xm.matches m ON m.{relation}=d.id
       WHERE d.company_id='xm' AND d.active AND d.document_type=%s'''
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
    from datetime import date
    for value, op in [(date_from,'>='),(date_to,'<=')]:
        if value:
            try: parsed_date=date.fromisoformat(value)
            except ValueError: raise HTTPException(400,'Tanggal tidak valid')
            query+=f' AND r.sent_at::date {op} %s'
            params.append(parsed_date)
    query+=' GROUP BY d.id,r.id HAVING ('
    filters=[]
    selected=set(statuses.split(','))
    if 'hot' in selected: filters.append('count(m.id) FILTER(WHERE m.score>=80)>0')
    if 'warm' in selected: filters.append('count(m.id) FILTER(WHERE m.score>=60 AND m.score<80)>0')
    if 'unmatched' in selected: filters.append('count(m.id) FILTER(WHERE m.score>=60)=0')
    query+=' OR '.join(filters or ['false'])+') ORDER BY r.sent_at DESC NULLS LAST,d.id LIMIT 201 OFFSET %s'
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
        sources=conn.execute('''SELECT d.*,r.raw_text,r.chat_name,r.sent_at FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id WHERE d.company_id='xm' AND d.active AND d.id=ANY(%s) AND d.document_type=%s''',(ids,kind)).fetchall()
        rows=conn.execute(f'''SELECT m.id match_id,m.{relation} source_id,m.score,m.explanation,d.*,r.raw_text,r.chat_name,r.sent_at FROM xm.matches m JOIN xm.documents d ON d.id=m.{other} JOIN xm.raw_messages r ON r.id=d.raw_message_id WHERE m.company_id='xm' AND d.active AND m.{relation}=ANY(%s) AND m.score>=60 ORDER BY m.score DESC''',(ids,)).fetchall()
    return {'groups':[{'source':s,'recommendations':[r for r in rows if r['source_id']==s['id']]} for s in sources]}

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
