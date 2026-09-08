import os
import time

from db import connect, ensure_schema
from ingest import process_import


def claim_job():
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM xm.imports
            WHERE company_id='xm' AND status='queued'
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED LIMIT 1
            """
        ).fetchone()
        if row:
            conn.execute("UPDATE xm.imports SET status='processing', started_at=now() WHERE id=%s", (row["id"],))
            conn.commit()
            return str(row["id"])
    return None


def process_maintenance():
    import json
    from reindex import reindex_documents
    from matcher import recompute_matches
    with connect() as conn:
        row=conn.execute("SELECT id FROM xm.maintenance_jobs WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if not row: return False
        conn.execute("UPDATE xm.maintenance_jobs SET status='processing' WHERE id=%s",(row['id'],))
        conn.commit()
    try:
        count=reindex_documents()
        matches=recompute_matches()
        with connect() as conn:
            conn.execute("UPDATE xm.maintenance_jobs SET status='completed',result=%s::jsonb,finished_at=now() WHERE id=%s",(json.dumps({'documents':count,'matches':matches}),row['id']))
            conn.commit()
    except Exception as exc:
        with connect() as conn:
            conn.execute("UPDATE xm.maintenance_jobs SET status='failed',error=%s,finished_at=now() WHERE id=%s",(str(exc),row['id']))
            conn.commit()
    return True


if __name__ == "__main__":
    ensure_schema()
    with connect() as conn:
        conn.execute("UPDATE xm.maintenance_jobs SET status='queued' WHERE status='processing'")
        conn.commit()
    while True:
        if process_maintenance():
            continue
        job_id = claim_job()
        if job_id:
            try:
                process_import(job_id)
            except Exception as exc:
                print(f"Import {job_id} failed: {exc}", flush=True)
        else:
            time.sleep(float(os.getenv("WORKER_POLL_SECONDS", "2")))

