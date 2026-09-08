import hashlib
import json
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import connect, ensure_schema
from embedding import embed
from matcher import recompute_matches
from parser import parse_message
from qdrant import ensure_collection
from qdrant import query as qdrant_query
from qdrant import status as qdrant_status
from auth import current_user, router as auth_router, seed_admin


UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class BuyerBatchRequest(BaseModel):
    buyer_ids: list[uuid.UUID]
    limit_per_buyer: int = 20


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    seed_admin()
    try:
        ensure_collection()
    except Exception as exc:
        print(f"Qdrant collection initialization deferred: {exc}", flush=True)
    yield


app = FastAPI(title="XM Auto Audit API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:9004", "http://localhost:9004"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_login(request: Request, call_next):
    public_paths = {"/health", "/auth/login"}
    if request.url.path not in public_paths and not current_user(request):
        return JSONResponse({"detail": "Sesi login diperlukan"}, status_code=401)
    return await call_next(request)


app.include_router(auth_router)


@app.get("/health")
def health():
    postgres_ok = False
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
            postgres_ok = True
    except Exception:
        pass
    return {"ok": postgres_ok, "postgres": postgres_ok, "qdrant": qdrant_status()}


@app.get("/stats")
def stats():
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM xm.raw_messages WHERE company_id='xm') raw_messages,
              (SELECT count(*) FROM xm.documents WHERE company_id='xm' AND active AND document_type='buyer_request') buyer_requests,
              (SELECT count(*) FROM xm.documents WHERE company_id='xm' AND active AND document_type='property_listing') listings,
              (SELECT count(*) FROM xm.matches WHERE company_id='xm') matches,
              (SELECT count(*) FROM xm.documents WHERE company_id='xm' AND active AND review_status='review') needs_review
            """
        ).fetchone()
    return {**row, "qdrant": qdrant_status()}


@app.get("/imports")
def imports():
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM xm.imports WHERE company_id='xm' ORDER BY created_at DESC LIMIT 30"
        ).fetchall()


@app.post("/imports", status_code=202)
async def upload_import(file: UploadFile = File(...), agent_name: str | None = Form(default=None)):
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(400, "Gunakan file JSON")
    import_id = uuid.uuid4()
    destination = UPLOAD_DIR / f"{import_id}.json"
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 100 * 1024 * 1024:
                destination.unlink(missing_ok=True)
                raise HTTPException(413, "Ukuran file maksimum 100 MB")
            digest.update(chunk)
            output.write(chunk)
    try:
        with destination.open("r", encoding="utf-8") as handle:
            header = json.load(handle)
        if not isinstance(header.get("chats"), dict):
            raise ValueError("Field chats tidak ditemukan")
        resolved_agent = (agent_name or header.get("salesName") or "Tidak diketahui").strip()
        if not resolved_agent or len(resolved_agent) > 100:
            raise ValueError("Nama agent tidak valid")
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, f"Format JSON tidak dikenali: {exc}") from exc
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, status FROM xm.imports WHERE company_id='xm' AND agent_name=%s AND file_sha256=%s",
            (resolved_agent, digest.hexdigest()),
        ).fetchone()
        if existing:
            destination.unlink(missing_ok=True)
            return {"id": existing["id"], "status": existing["status"], "duplicate": True}
        conn.execute(
            "INSERT INTO xm.imports(id, agent_name, file_name, file_path, file_sha256) VALUES (%s,%s,%s,%s,%s)",
            (import_id, resolved_agent, file.filename, str(destination), digest.hexdigest()),
        )
        conn.commit()
    return {"id": import_id, "status": "queued", "duplicate": False, "agent_name": resolved_agent}


@app.get("/documents")
def documents(document_type: str | None = None, limit: int = 50, offset: int = 0):
    limit = min(max(limit, 1), 200)
    query = """
      SELECT d.*, r.chat_name, r.sent_at, r.raw_text, r.author
      FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id
      WHERE d.company_id='xm' AND d.active
    """
    params = []
    if document_type in {"buyer_request", "property_listing"}:
        query += " AND d.document_type=%s"
        params.append(document_type)
    query += " ORDER BY d.created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    with connect() as conn:
        return conn.execute(query, params).fetchall()


@app.get("/matches")
def matches(limit: int = 50):
    with connect() as conn:
        return conn.execute(
            """
            SELECT m.*, br.normalized_text buyer_text, pl.normalized_text listing_text,
                   br.categories buyer_categories, pl.categories listing_categories,
                   br.locations buyer_locations, pl.locations listing_locations,
                   br.contact_name buyer_contact, pl.contact_name listing_contact
            FROM xm.matches m
            JOIN xm.documents br ON br.id=m.buyer_request_id
            JOIN xm.documents pl ON pl.id=m.property_listing_id
            WHERE m.company_id='xm'
            ORDER BY m.score DESC LIMIT %s
            """, (min(max(limit, 1), 200),)
        ).fetchall()


@app.get("/buyers")
def buyers(
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    agent_name: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    query = """
      SELECT d.id, d.agent_name, d.transaction_type, d.categories, d.locations,
             d.land_area_min, d.land_area_max, d.building_area_min, d.building_area_max,
             d.price_min, d.price_max, d.price_basis, d.facing, d.exclusions,
             d.contact_name, d.contact_phone, d.normalized_text, d.extraction_confidence,
             r.chat_name, r.sent_at, r.author, r.raw_text,
             count(m.id) FILTER (WHERE m.score >= 60) AS match_count,
             count(m.id) FILTER (WHERE m.score >= 80) AS hot_count,
             count(m.id) FILTER (WHERE m.score >= 60 AND m.score < 80) AS warm_count,
             max(m.score) AS best_score
      FROM xm.documents d
      JOIN xm.raw_messages r ON r.id=d.raw_message_id
      LEFT JOIN xm.matches m ON m.buyer_request_id=d.id
      WHERE d.company_id='xm' AND d.document_type='buyer_request' AND d.active
    """
    params = []
    if search:
        query += """ AND (d.normalized_text ILIKE %s OR coalesce(d.contact_name,'') ILIKE %s
                       OR coalesce(r.chat_name,'') ILIKE %s OR array_to_string(d.locations, ' ') ILIKE %s
                       OR array_to_string(d.categories, ' ') ILIKE %s)"""
        term = f"%{search.strip()}%"
        params.extend([term, term, term, term, term])
    if date_from:
        query += " AND r.sent_at::date >= %s"
        params.append(date_from)
    if date_to:
        query += " AND r.sent_at::date <= %s"
        params.append(date_to)
    if agent_name:
        query += " AND d.agent_name=%s"
        params.append(agent_name)
    query += """ GROUP BY d.id, r.id
                 ORDER BY r.sent_at DESC NULLS LAST
                 LIMIT %s OFFSET %s"""
    params.extend([min(max(limit, 1), 300), max(offset, 0)])
    with connect() as conn:
        return conn.execute(query, params).fetchall()


@app.get("/buyers/{buyer_id}/recommendations")
def buyer_recommendations(buyer_id: uuid.UUID, limit: int = 50):
    with connect() as conn:
        buyer = conn.execute(
            """SELECT d.*, r.chat_name, r.sent_at, r.author, r.raw_text
               FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id
               WHERE d.id=%s AND d.company_id='xm' AND d.document_type='buyer_request'""",
            (buyer_id,),
        ).fetchone()
        if not buyer:
            raise HTTPException(404, "Buyer request tidak ditemukan")
        rows = conn.execute(
            """SELECT m.id, m.score, m.location_score, m.land_score, m.building_score,
                      m.price_score, m.semantic_score, m.explanation,
                      pl.id property_id, pl.agent_name, pl.transaction_type, pl.categories,
                      pl.locations, pl.land_area_min, pl.land_area_max,
                      pl.building_area_min, pl.building_area_max, pl.price_min, pl.price_max,
                      pl.price_basis, pl.negotiable, pl.facing, pl.requirements,
                      pl.contact_name, pl.contact_phone, raw.raw_text property_text,
                      raw.chat_name, raw.sent_at, raw.author
               FROM xm.matches m
               JOIN xm.documents pl ON pl.id=m.property_listing_id
               JOIN xm.raw_messages raw ON raw.id=pl.raw_message_id
               WHERE m.company_id='xm' AND m.buyer_request_id=%s AND m.score >= 60
               ORDER BY m.score DESC LIMIT %s""",
            (buyer_id, min(max(limit, 1), 100)),
        ).fetchall()
    for row in rows:
        row["temperature"] = "hot" if float(row["score"]) >= 80 else "warm"
    return {"buyer": buyer, "recommendations": rows}


@app.post("/buyers/recommendations/batch")
def batch_buyer_recommendations(payload: BuyerBatchRequest):
    buyer_ids = list(dict.fromkeys(payload.buyer_ids))
    if not buyer_ids:
        return {"groups": []}
    if len(buyer_ids) > 50:
        raise HTTPException(400, "Maksimum 50 buyer dalam satu pencocokan")
    limit_per_buyer = min(max(payload.limit_per_buyer, 1), 50)
    with connect() as conn:
        buyers = conn.execute(
            """SELECT d.id, d.agent_name, d.categories, d.locations, d.contact_name, d.contact_phone,
                      d.normalized_text, r.raw_text, r.chat_name, r.sent_at
               FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id
               WHERE d.id = ANY(%s::uuid[]) AND d.company_id='xm'
                 AND d.document_type='buyer_request'""",
            ([str(item) for item in buyer_ids],),
        ).fetchall()
        matches = conn.execute(
            """WITH ranked AS (
                 SELECT m.*, row_number() OVER (PARTITION BY m.buyer_request_id ORDER BY m.score DESC) AS rank
                 FROM xm.matches m
                 WHERE m.company_id='xm' AND m.buyer_request_id = ANY(%s::uuid[]) AND m.score >= 60
               )
               SELECT ranked.buyer_request_id, ranked.id, ranked.score, ranked.location_score,
                      ranked.land_score, ranked.building_score, ranked.price_score,
                      ranked.semantic_score, ranked.explanation,
                      pl.id property_id, pl.agent_name, pl.categories, pl.locations,
                      pl.land_area_min, pl.land_area_max, pl.building_area_min, pl.building_area_max,
                      pl.price_min, pl.price_max, pl.price_basis, pl.negotiable, pl.facing,
                      pl.contact_name, pl.contact_phone, raw.raw_text property_text,
                      raw.chat_name, raw.sent_at
               FROM ranked JOIN xm.documents pl ON pl.id=ranked.property_listing_id
               JOIN xm.raw_messages raw ON raw.id=pl.raw_message_id
               WHERE ranked.rank <= %s ORDER BY ranked.buyer_request_id, ranked.score DESC""",
            ([str(item) for item in buyer_ids], limit_per_buyer),
        ).fetchall()
    by_buyer = {str(item): [] for item in buyer_ids}
    for row in matches:
        row["temperature"] = "hot" if float(row["score"]) >= 80 else "warm"
        by_buyer[str(row["buyer_request_id"])].append(row)
    buyer_map = {str(row["id"]): row for row in buyers}
    groups = [
        {"buyer": buyer_map[str(item)], "recommendations": by_buyer[str(item)]}
        for item in buyer_ids if str(item) in buyer_map
    ]
    return {"groups": groups}


@app.get("/settings")
def get_settings():
    with connect() as conn:
        return conn.execute("SELECT * FROM xm.match_settings WHERE company_id='xm'").fetchone()


@app.post("/matches/recompute")
def recompute():
    return {"matches": recompute_matches()}


@app.get("/agent/search")
def agent_search(q: str, document_type: str | None = None, limit: int = 10):
    if len(q.strip()) < 3:
        raise HTTPException(400, "Pertanyaan terlalu pendek")
    parsed = parse_message(q)
    category = parsed.categories[0] if len(parsed.categories) == 1 else None
    try:
        hits = qdrant_query(embed(q), document_type=document_type, category=category, limit=limit)
        ids = [hit.get("payload", {}).get("postgres_id") for hit in hits]
        score_map = {hit.get("payload", {}).get("postgres_id"): hit.get("score", 0) for hit in hits}
    except Exception:
        ids, score_map = [], {}
    with connect() as conn:
        if ids:
            rows = conn.execute(
                """SELECT d.*, r.chat_name, r.sent_at, r.raw_text, r.author FROM xm.documents d
                   JOIN xm.raw_messages r ON r.id=d.raw_message_id WHERE d.company_id='xm' AND d.active AND d.id = ANY(%s::uuid[])""", (ids,)
            ).fetchall()
        else:
            term = f"%{q.strip()}%"
            rows = conn.execute(
                """SELECT d.*, r.chat_name, r.sent_at, r.raw_text, r.author FROM xm.documents d
                   JOIN xm.raw_messages r ON r.id=d.raw_message_id
                   WHERE d.company_id='xm' AND d.active AND (%s IS NULL OR d.document_type=%s)
                     AND (d.normalized_text ILIKE %s OR %s = ANY(d.categories))
                   ORDER BY d.created_at DESC LIMIT %s""",
                (document_type, document_type, term, category or "", min(limit, 50)),
            ).fetchall()
    for row in rows:
        row["semantic_score"] = round(float(score_map.get(str(row["id"]), 0)) * 100, 2)
    rows.sort(key=lambda row: row["semantic_score"], reverse=True)
    return {"query": q, "parsed": parsed.dict(), "results": rows[:limit]}


@app.get("/agent/matches")
def agent_matches(contact: str | None = None, min_score: float = 60, limit: int = 20):
    with connect() as conn:
        base = """SELECT m.score, m.explanation, br.contact_name buyer_contact, br.normalized_text buyer_request,
                         pl.contact_name listing_contact, pl.normalized_text property_listing
                  FROM xm.matches m JOIN xm.documents br ON br.id=m.buyer_request_id
                  JOIN xm.documents pl ON pl.id=m.property_listing_id
                  WHERE m.company_id='xm' AND m.score >= %s"""
        if contact:
            term = f"%{contact}%"
            rows = conn.execute(
                base + " AND (br.contact_name ILIKE %s OR pl.contact_name ILIKE %s) ORDER BY m.score DESC LIMIT %s",
                (min_score, term, term, min(max(limit, 1), 100)),
            ).fetchall()
        else:
            rows = conn.execute(
                base + " ORDER BY m.score DESC LIMIT %s",
                (min_score, min(max(limit, 1), 100)),
            ).fetchall()
    return {"results": rows}

from workspace import router as workspace_router
app.include_router(workspace_router)
