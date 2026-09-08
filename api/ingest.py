import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path

from db import connect
from embedding import embed
from matcher import recompute_matches
from parser import message_hash, parse_message
from qdrant import upsert
from reindex import glossary_values


def _count_messages(payload: dict) -> int:
    return sum(len(chat.get("messages", [])) for chat in payload.get("chats", {}).values())


def process_import(import_id: str) -> None:
    qdrant_batch = []
    qdrant_count = 0
    try:
        with connect() as conn:
            job = conn.execute("SELECT * FROM xm.imports WHERE id=%s", (import_id,)).fetchone()
            conn.execute("UPDATE xm.imports SET status='processing', started_at=now(), error=NULL WHERE id=%s", (import_id,))
            conn.commit()
        payload = json.loads(Path(job["file_path"]).read_text(encoding="utf-8"))
        total = _count_messages(payload)
        with connect() as conn:
            conn.execute("UPDATE xm.imports SET total_messages=%s WHERE id=%s", (total, import_id))
            conn.commit()
        counters = {
            "buyer_request": int(job["request_count"]), "property_listing": int(job["listing_count"]),
            "ignored": int(job["ignored_count"]), "duplicate": int(job["duplicate_count"]),
        }
        processed = int(job["processed_messages"])
        qdrant_count = int(job["qdrant_points"])
        with connect() as conn:
            conn.execute("SELECT pg_advisory_lock(9042026)")
            glossary = glossary_values(conn)
            for chat_id, chat in payload.get("chats", {}).items():
                for position, message in enumerate(chat.get("messages", [])):
                    existing_position = conn.execute(
                        "SELECT id FROM xm.raw_messages WHERE import_id=%s AND chat_id=%s AND message_position=%s",
                        (import_id, chat_id, position),
                    ).fetchone()
                    if existing_position:
                        continue
                    timestamp = str(message[0]) if len(message) > 0 else ""
                    text = str(message[1]) if len(message) > 1 else ""
                    author = str(message[2]) if len(message) > 2 else ""
                    digest = message_hash(chat_id, timestamp, author, text)
                    previous = conn.execute(
                        "SELECT id FROM xm.raw_messages WHERE company_id='xm' AND agent_name=%s AND message_hash=%s LIMIT 1",
                        (job["agent_name"], digest),
                    ).fetchone()
                    parsed = parse_message(text, author, glossary)
                    raw_id = uuid.uuid4()
                    duplicate_of = previous["id"] if previous else None
                    classification = "duplicate" if duplicate_of else parsed.classification
                    conn.execute(
                        """
                        INSERT INTO xm.raw_messages(id, import_id, agent_name, chat_id, chat_name, is_group, message_position,
                          sent_at, author, raw_text, message_hash, classification, confidence, duplicate_of, extracted)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                        """,
                        (raw_id, import_id, job["agent_name"], chat_id, chat.get("name", "Tanpa nama"), bool(chat.get("is_group")), position,
                         datetime.fromisoformat(timestamp) if timestamp else None, author, text, digest, classification,
                         parsed.confidence, duplicate_of, json.dumps(parsed.dict())),
                    )
                    if duplicate_of:
                        counters["duplicate"] += 1
                    elif parsed.classification in ("buyer_request", "property_listing"):
                        doc_id = uuid.uuid4()
                        point_id = uuid.uuid5(uuid.NAMESPACE_URL, f"xm:{doc_id}")
                        # A bubble with many property categories usually holds
                        # several listings. Keep it searchable, but do not let
                        # merged specs create false automatic matches.
                        review_status = "review" if parsed.confidence < 0.7 or not parsed.categories or len(parsed.categories) > 2 else "auto"
                        conn.execute(
                            """
                            INSERT INTO xm.documents(id, raw_message_id, import_id, agent_name, document_type, transaction_type,
                              categories, primary_category, locations, land_area_min, land_area_max,
                              building_area_min, building_area_max, price_min, price_max, price_basis, negotiable,
                              facing, exclusions, requirements, contact_name, contact_phone, normalized_text,
                              extraction_confidence, review_status, qdrant_point_id, contact_phones)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            """,
                            (doc_id, raw_id, import_id, job["agent_name"], parsed.classification, parsed.transaction_type, parsed.categories,
                             parsed.categories[0] if parsed.categories else None, parsed.locations, parsed.land_area_min,
                             parsed.land_area_max, parsed.building_area_min, parsed.building_area_max, parsed.price_min,
                             parsed.price_max, parsed.price_basis, parsed.negotiable, parsed.facing, parsed.exclusions,
                             parsed.requirements, parsed.contact_name, parsed.contact_phone, parsed.normalized_text,
                             parsed.confidence, review_status, point_id, parsed.contact_phones),
                        )
                        qdrant_batch.append({
                            "id": str(point_id),
                            "vector": embed(parsed.normalized_text),
                            "payload": {
                                "company_id": "xm", "postgres_id": str(doc_id), "document_type": parsed.classification,
                                "agent_name": job["agent_name"],
                                "transaction_type": parsed.transaction_type, "categories": parsed.categories,
                                "locations": parsed.locations, "active": True,
                            },
                        })
                        counters[parsed.classification] += 1
                    else:
                        counters["ignored"] += 1
                    processed += 1
                    if len(qdrant_batch) >= 128:
                        qdrant_count += upsert(qdrant_batch)
                        qdrant_batch = []
                    if processed % 250 == 0:
                        conn.execute(
                            """UPDATE xm.imports SET processed_messages=%s, request_count=%s, listing_count=%s,
                               ignored_count=%s, duplicate_count=%s, qdrant_points=%s WHERE id=%s""",
                            (processed, counters["buyer_request"], counters["property_listing"], counters["ignored"],
                             counters["duplicate"], qdrant_count, import_id),
                        )
                        conn.commit()
            if qdrant_batch:
                qdrant_count += upsert(qdrant_batch)
            conn.execute(
                """UPDATE xm.imports SET processed_messages=%s, request_count=%s, listing_count=%s,
                   ignored_count=%s, duplicate_count=%s, qdrant_points=%s WHERE id=%s""",
                (processed, counters["buyer_request"], counters["property_listing"], counters["ignored"],
                 counters["duplicate"], qdrant_count, import_id),
            )
            conn.commit()
        match_count = recompute_matches()
        with connect() as conn:
            conn.execute("UPDATE xm.imports SET status='completed', finished_at=now() WHERE id=%s", (import_id,))
            conn.execute(
                "INSERT INTO xm.audit_events(event_type, entity_type, entity_id, details) VALUES ('import_completed','import',%s,%s::jsonb)",
                (import_id, json.dumps({**counters, "qdrant_points": qdrant_count, "matches": match_count})),
            )
            conn.commit()
    except Exception as exc:
        with connect() as conn:
            conn.execute("UPDATE xm.imports SET status='failed', error=%s, finished_at=now() WHERE id=%s", (str(exc), import_id))
            conn.commit()
        raise
