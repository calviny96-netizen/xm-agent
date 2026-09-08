import json
import uuid

from db import connect
from embedding import embed
from parser import location_score, score_range
from qdrant import query as qdrant_query


def _row_range(row, prefix):
    return row.get(f"{prefix}_min"), row.get(f"{prefix}_max")


def _near_duplicate(left_tokens: set[str], right_tokens: set[str]) -> bool:
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens) >= 0.70


def _price_basis_compatible(request, listing) -> bool:
    request_basis = request.get("price_basis")
    listing_basis = listing.get("price_basis")
    return not request_basis or not listing_basis or request_basis == listing_basis


def _price_score(request, listing, tolerance_pct: float) -> tuple[float, str]:
    if request.get("price_min") is None and request.get("price_max") is None:
        return 100.0, "Tidak dibatasi"
    if listing.get("price_min") is None and listing.get("price_max") is None:
        return 35.0, "Harga listing belum tersedia"
    if not _price_basis_compatible(request, listing):
        return 0.0, "Basis harga berbeda"
    # A listing may exceed the buyer's maximum only when explicitly negotiable.
    effective_tolerance = tolerance_pct if listing.get("negotiable") else 0.0
    return score_range(
        request.get("price_min"), request.get("price_max"),
        listing.get("price_min"), listing.get("price_max"),
        effective_tolerance,
    )


def _has_exclusion_conflict(request, listing) -> str | None:
    facing = set(listing.get("facing") or [])
    requirements = " ".join(listing.get("requirements") or [])
    listing_text = f"{listing.get('normalized_text') or ''} {requirements}"
    for excluded in request.get("exclusions") or []:
        token = excluded.strip().strip("*_")
        if not token:
            continue
        if token in facing or (len(token) >= 3 and token in listing_text):
            return token
    return None


def recompute_matches(company_id: str = "xm", limit_per_request: int | None = None) -> int:
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(9042026)")
        settings = conn.execute(
            "SELECT * FROM xm.match_settings WHERE company_id = %s", (company_id,)
        ).fetchone()
        requests = conn.execute(
            "SELECT * FROM xm.documents WHERE company_id=%s AND document_type='buyer_request' AND active",
            (company_id,),
        ).fetchall()
        listings = conn.execute(
            "SELECT * FROM xm.documents WHERE company_id=%s AND document_type='property_listing' AND active AND review_status='auto'",
            (company_id,),
        ).fetchall()
        listings_by_id = {str(row["id"]): row for row in listings}
        listing_tokens = {str(row["id"]): set(row["normalized_text"].split()) for row in listings}
        listings_by_category = {}
        listings_by_category_location = {}
        for listing in listings:
            for category in listing["categories"] or []:
                listings_by_category.setdefault(category, []).append(listing)
                for location in listing["locations"] or []:
                    listings_by_category_location.setdefault((category, location), []).append(listing)
        conn.execute("DELETE FROM xm.matches WHERE company_id=%s", (company_id,))
        inserted = 0
        for request in requests:
            request_categories = set(request["categories"] or [])
            request_tokens = set(request["normalized_text"].split())
            request_vector = embed(request["normalized_text"])
            candidate_rows = {}
            try:
                categories_to_query = list(request_categories) or [None]
                for category in categories_to_query:
                    for hit in qdrant_query(request_vector, document_type="property_listing", category=category, limit=150):
                        postgres_id = hit.get("payload", {}).get("postgres_id")
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
                    for listing in listings_by_category_location.get((category, location), [])[:300]:
                        structured_candidates[str(listing["id"])] = listing
                for listing_id, listing in list(structured_candidates.items())[:300]:
                    candidate_rows.setdefault(listing_id, (listing, None))
            candidates = []
            for listing, qdrant_semantic in candidate_rows.values():
                # Forwarded request posts can appear in multiple WhatsApp
                # groups. Never recommend the same text back as a property.
                if _near_duplicate(listing_tokens[str(listing["id"])], request_tokens):
                    continue
                listing_categories = set(listing["categories"] or [])
                if not request_categories or not listing_categories or not request_categories.intersection(listing_categories):
                    continue
                if request["transaction_type"] != "unknown" and listing["transaction_type"] != "unknown" and request["transaction_type"] != listing["transaction_type"]:
                    continue
                exclusion_conflict = _has_exclusion_conflict(request, listing)
                if exclusion_conflict:
                    continue
                loc = location_score(request["locations"] or [], listing["locations"] or [])
                land, land_reason = score_range(*_row_range(request, "land_area"), *_row_range(listing, "land_area"), float(settings["land_tolerance_pct"]))
                building, building_reason = score_range(*_row_range(request, "building_area"), *_row_range(listing, "building_area"), float(settings["building_tolerance_pct"]))
                price, price_reason = _price_score(request, listing, float(settings["price_tolerance_pct"]))
                if land == 0 or building == 0 or price == 0:
                    continue
                # Exact-location candidates outside Qdrant's top-K receive a
                # neutral semantic value; structured constraints still decide.
                semantic = max(0.0, qdrant_semantic) * 100 if qdrant_semantic is not None else 50.0
                quality = (float(request["extraction_confidence"]) + float(listing["extraction_confidence"])) * 50
                score = (
                    loc * float(settings["location_weight_pct"]) / 100
                    + land * float(settings["land_weight_pct"]) / 100
                    + building * float(settings["building_weight_pct"]) / 100
                    + price * float(settings["price_weight_pct"]) / 100
                    + semantic * float(settings["semantic_weight_pct"]) / 100
                    + quality * float(settings["data_quality_weight_pct"]) / 100
                )
                missing_critical = (
                    ((request["land_area_min"] is not None or request["land_area_max"] is not None) and listing["land_area_min"] is None and listing["land_area_max"] is None)
                    or ((request["building_area_min"] is not None or request["building_area_max"] is not None) and listing["building_area_min"] is None and listing["building_area_max"] is None)
                    or ((request["price_min"] is not None or request["price_max"] is not None) and listing["price_min"] is None and listing["price_max"] is None)
                )
                if missing_critical:
                    score = min(score, 79.0)
                if score < 55:
                    continue
                explanation = [
                    f"Kategori cocok: {', '.join(sorted(request_categories.intersection(listing_categories)))}",
                    f"Lokasi {loc:.0f}%",
                    f"Luas tanah: {land_reason}",
                    f"Luas bangunan: {building_reason}",
                    f"Harga: {price_reason}",
                    f"Kualitas data {quality:.0f}%",
                ]
                candidates.append((score, listing, loc, land, building, price, semantic, explanation))
            candidates.sort(key=lambda item: item[0], reverse=True)
            unique_candidates = []
            seen_listing_texts = set()
            for candidate in candidates:
                listing_text = candidate[1]["normalized_text"]
                if listing_text in seen_listing_texts:
                    continue
                seen_listing_texts.add(listing_text)
                unique_candidates.append(candidate)
                if limit_per_request is not None and len(unique_candidates) >= limit_per_request:
                    break
            for score, listing, loc, land, building, price, semantic, explanation in unique_candidates:
                conn.execute(
                    """
                    INSERT INTO xm.matches(id, company_id, buyer_request_id, property_listing_id, score,
                        location_score, land_score, building_score, price_score, semantic_score, explanation)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    """,
                    (uuid.uuid4(), company_id, request["id"], listing["id"], round(score, 2), round(loc, 2),
                     round(land, 2), round(building, 2), round(price, 2), round(semantic, 2), json.dumps(explanation)),
                )
                inserted += 1
        conn.execute(
            "INSERT INTO xm.audit_events(event_type, entity_type, details) VALUES ('matching_completed','match',%s::jsonb)",
            (json.dumps({"matches": inserted, "requests": len(requests), "listings": len(listings)}),),
        )
        conn.commit()
        return inserted
