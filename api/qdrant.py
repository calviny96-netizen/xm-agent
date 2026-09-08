import json
import os
import urllib.error
import urllib.request
import time

from embedding import VECTOR_SIZE


QDRANT_URL = os.getenv("QDRANT_URL", "http://host.docker.internal:6333").rstrip("/")
COLLECTION = os.getenv("QDRANT_COLLECTION", "xm_rag")


def _request(method: str, path: str, payload=None, timeout: int = 20):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{QDRANT_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    last_error = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt < 4:
                time.sleep(2 ** attempt)
    raise last_error


def ensure_collection() -> None:
    created = False
    try:
        _request("GET", f"/collections/{COLLECTION}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        _request(
            "PUT",
            f"/collections/{COLLECTION}",
            {"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}, "on_disk_payload": True},
        )
        created = True
    if created:
        for field, schema in (("company_id", "keyword"), ("document_type", "keyword"), ("categories", "keyword"), ("active", "bool"), ("agent_name", "keyword")):
            _request("PUT", f"/collections/{COLLECTION}/index?wait=true", {"field_name": field, "field_schema": schema})


def upsert(points: list[dict]) -> int:
    if not points:
        return 0
    ensure_collection()
    _request("PUT", f"/collections/{COLLECTION}/points?wait=true", {"points": points}, timeout=90)
    return len(points)


def status() -> dict:
    try:
        result = _request("GET", f"/collections/{COLLECTION}", timeout=3).get("result", {})
        return {
            "ok": True,
            "collection": COLLECTION,
            "points": result.get("points_count", 0),
            "status": result.get("status", "unknown"),
        }
    except Exception as exc:
        return {"ok": False, "collection": COLLECTION, "error": str(exc)}


def query(vector: list[float], document_type: str | None = None, category: str | None = None, limit: int = 10) -> list[dict]:
    conditions = [{"key": "company_id", "match": {"value": "xm"}}, {"key": "active", "match": {"value": True}}]
    if document_type:
        conditions.append({"key": "document_type", "match": {"value": document_type}})
    if category:
        conditions.append({"key": "categories", "match": {"value": category}})
    result = _request(
        "POST",
        f"/collections/{COLLECTION}/points/query",
        {"query": vector, "filter": {"must": conditions}, "limit": min(limit, 50), "with_payload": True},
    ).get("result", {})
    return result.get("points", result if isinstance(result, list) else [])
