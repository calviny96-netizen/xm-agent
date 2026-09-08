import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr

from db import connect


router = APIRouter(prefix="/auth")
COOKIE_NAME = "xm_session"
SESSION_DAYS = 7


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def _password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def seed_admin() -> None:
    email = os.getenv("XM_ADMIN_EMAIL", "admin@autoaudit.id").strip().lower()
    password = os.getenv("XM_ADMIN_PASSWORD", "admin")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO xm.users(id, email, display_name, password_hash)
            VALUES (%s, %s, 'Administrator', %s)
            ON CONFLICT (email) DO NOTHING
            """,
            (uuid.uuid4(), email, _password_hash(password)),
        )
        conn.commit()


def current_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connect() as conn:
        return conn.execute(
            """
            SELECT u.id, u.email, u.display_name
            FROM xm.sessions s JOIN xm.users u ON u.id=s.user_id
            WHERE s.token_hash=%s AND s.expires_at > now()
            """,
            (token_hash,),
        ).fetchone()


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    email = payload.email.strip().lower()
    with connect() as conn:
        user = conn.execute("SELECT * FROM xm.users WHERE email=%s", (email,)).fetchone()
        if not user or not _password_matches(payload.password, user["password_hash"]):
            raise HTTPException(401, "Email atau password tidak sesuai")
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        conn.execute("DELETE FROM xm.sessions WHERE expires_at <= now()")
        conn.execute(
            "INSERT INTO xm.sessions(id,user_id,token_hash,expires_at) VALUES(%s,%s,%s,%s)",
            (uuid.uuid4(), user["id"], hashlib.sha256(token.encode()).hexdigest(), expires_at),
        )
        conn.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="strict",
        secure=os.getenv("XM_COOKIE_SECURE", "0") == "1",
        path="/",
    )
    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}


@router.get("/me")
def me(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Sesi login diperlukan")
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with connect() as conn:
            conn.execute(
                "DELETE FROM xm.sessions WHERE token_hash=%s",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
            conn.commit()
    response.delete_cookie(COOKIE_NAME, path="/")

