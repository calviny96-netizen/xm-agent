import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def database_url() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    host = os.getenv("DATABASE_HOST", "host.docker.internal")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    database = os.getenv("POSTGRES_DB", "postgres")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def connect():
    # Docker's shared PostgreSQL has a small /dev/shm. Concurrent parallel
    # aggregates can exhaust it on the full archive; scope this to XM sessions.
    return psycopg.connect(database_url(), row_factory=dict_row,
                            options='-c max_parallel_workers_per_gather=0 -c work_mem=32MB')


def ensure_schema() -> None:
    sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connect() as conn:
        conn.execute(sql)
        conn.commit()
