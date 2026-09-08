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
    return psycopg.connect(database_url(), row_factory=dict_row)


def ensure_schema() -> None:
    sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connect() as conn:
        conn.execute(sql)
        conn.commit()

