import json
import uuid

from db import connect
from embedding import embed
from qdrant import query as qdrant_query
from matching_rules import assess_pair, prepare_document
from workspace_cache import refresh_workspace_cache
from location_index import load_index


def _near_duplicate(left_tokens: set[str], right_tokens: set[str]) -> bool:
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens) >= 0.70


def recompute_matches(company_id: str = "xm", limit_per_request: int | None = None) -> int:
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(9042026)")
        settings = conn.execute(
            "SELECT * FROM xm.match_settings WHERE company_id = %s", (company_id,)
        ).fetchone()
        requests = conn.execute(
            "SELECT d.*,r.raw_text FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id WHERE d.company_id=%s AND d.document_type='buyer_request' AND d.active ORDER BY d.id",
            (company_id,),
        ).fetchall()
        listings = conn.execute(
            "SELECT d.*,r.raw_text FROM xm.documents d JOIN xm.raw_messages r ON r.id=d.raw_message_id WHERE d.company_id=%s AND d.document_type='property_listing' AND d.active AND d.review_status='auto' ORDER BY d.id",
            (company_id,),
        ).fetchall()
        location_index = load_index(conn, company_id)
        # Exact source texts share one evaluation; membership preserves every
        # posting/contact and both directions resolve through the group cache.
        unique_listings = {}
        canonical_by_id = {}
        for row in listings:
            canonical = unique_listings.setdefault(row['raw_text'],row)
            canonical_by_id[str(row['id'])] = str(canonical['id'])
        listings = list(unique_listings.values())
        requests = list({r['raw_text']:r for r in requests}.values())
        for row in requests + listings:
            prepare_document(row,location_index)
        listings_by_id = {str(row['id']):row for row in listings}
        listing_tokens = {str(row["id"]): set(row["normalized_text"].split()) for row in listings}
        listings_by_category = {}
        listings_by_category_location = {}
        listings_by_cluster = {}
        for listing in listings:
            for cluster in listing['_geo_ids']:
                for category in listing['categories'] or []:
                    listings_by_cluster.setdefault((category, cluster), []).append(listing)
            for category in listing["categories"] or []:
                listings_by_category.setdefault(category, []).append(listing)
                for location in listing["locations"] or []:
                    listings_by_category_location.setdefault((category, location), []).append(listing)
        conn.execute("DELETE FROM xm.matches WHERE company_id=%s", (company_id,))
        inserted = 0
        pending = []
        insert_sql = """INSERT INTO xm.matches(id,company_id,buyer_request_id,property_listing_id,score,
            location_score,land_score,building_score,price_score,semantic_score,explanation)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)"""
        for request_number, request in enumerate(requests,1):
            request_categories = set(request["categories"] or [])
            request_tokens = set(request["normalized_text"].split())
            request_vector = embed(request["normalized_text"])
            candidate_rows = {}
            try:
                categories_to_query = list(request_categories) or [None]
                for category in categories_to_query:
                    for hit in qdrant_query(request_vector, document_type="property_listing", category=category, limit=150):
                        postgres_id = canonical_by_id.get(hit.get("payload", {}).get("postgres_id"))
                        if postgres_id in listings_by_id:
                            candidate_rows[postgres_id] = (listings_by_id[postgres_id], float(hit.get("score", 0)))
            except Exception:
                for category in request_categories:
                    for listing in listings_by_category.get(category, [])[:250]:
                        candidate_rows[str(listing["id"])] = (listing, None)
            # Structured retrieval guarantees that exact-location candidates
            # are considered even when they are outside Qdrant's semantic top-K.
            for category in request_categories:
                structured_candidates = {}
                for location in request["locations"] or []:
                    for listing in listings_by_category_location.get((category, location), []):
                        structured_candidates[str(listing["id"])] = listing
                for listing_id, listing in structured_candidates.items():
                    candidate_rows.setdefault(listing_id, (listing, None))
            candidates = []
            # Direct imported edges also retrieve candidates outside semantic top-K.
            for cluster in request['_geo_ids']:
                nearby = {cluster, *location_index.neighbors[cluster]}
                for category in request_categories:
                    for target in nearby:
                        for listing in listings_by_cluster.get((category, target), []):
                            candidate_rows.setdefault(str(listing['id']), (listing, None))
            for listing, qdrant_semantic in candidate_rows.values():
                # Forwarded request posts can appear in multiple WhatsApp
                # groups. Never recommend the same text back as a property.
                if _near_duplicate(listing_tokens[str(listing["id"])], request_tokens):
                    continue
                semantic = max(0.0, qdrant_semantic) * 100 if qdrant_semantic is not None else 50.0
                result = assess_pair(request, listing, settings, semantic, location_index)
                if result is None or result['score'] < 55:
                    continue
                candidates.append((result['score'], listing, result['location'], result['land'],
                                   result['building'], result['price'], result['semantic'], result['explanation']))
            candidates.sort(key=lambda item: item[0], reverse=True)
            unique_candidates = candidates if limit_per_request is None else candidates[:limit_per_request]
            for score, listing, loc, land, building, price, semantic, explanation in unique_candidates:
                pending.append((uuid.uuid4(),company_id,request['id'],listing['id'],round(score,2),round(loc,2),
                                round(land,2),round(building,2),round(price,2),round(semantic,2),json.dumps(explanation)))
                inserted += 1
            if len(pending)>=1000:
                with conn.cursor() as cur: cur.executemany(insert_sql,pending)
                pending=[]
            if request_number % 100 == 0:
                print(f'Matching {request_number}/{len(requests)} unique buyers; {inserted} pairs',flush=True)
        if pending:
            with conn.cursor() as cur: cur.executemany(insert_sql,pending)
        refresh_workspace_cache(conn,company_id)
        conn.execute(
            "INSERT INTO xm.audit_events(event_type, entity_type, details) VALUES ('matching_completed','match',%s::jsonb)",
            (json.dumps({"matches": inserted, "requests": len(requests), "listings": len(listings)}),),
        )
        conn.commit()
        return inserted
