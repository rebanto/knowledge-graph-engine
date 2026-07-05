import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Response


AUTH_SECRET_KEY = os.environ.get("AUTH_SECRET_KEY")
if not AUTH_SECRET_KEY:
    raise RuntimeError("AUTH_SECRET_KEY is required for authentication")

ACCESS_COOKIE = "kgre_access"
REFRESH_COOKIE = "kgre_refresh"
ALGORITHM = "HS256"

_password_hasher = PasswordHasher()


def _access_ttl() -> timedelta:
    return timedelta(minutes=int(os.environ.get("ACCESS_TOKEN_TTL_MIN", "30")))


def refresh_ttl() -> timedelta:
    return timedelta(days=int(os.environ.get("REFRESH_TOKEN_TTL_DAYS", "14")))


def _cookie_secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "false").lower() == "true"


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: str) -> str:
    now = _now()
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + _access_ttl()).timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, AUTH_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Wrong token type")
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise jwt.InvalidTokenError("Missing subject")
    return user_id


def new_refresh_token() -> tuple[str, str]:
    opaque = secrets.token_urlsafe(48)
    return opaque, refresh_token_hash(opaque)


def refresh_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    flags = {
        "httponly": True,
        "secure": _cookie_secure(),
        "samesite": "lax",
    }
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=int(_access_ttl().total_seconds()),
        path="/",
        **flags,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=int(refresh_ttl().total_seconds()),
        path="/api/auth",
        **flags,
    )


def clear_auth_cookies(response: Response) -> None:
    for name, path in ((ACCESS_COOKIE, "/"), (REFRESH_COOKIE, "/api/auth")):
        response.delete_cookie(
            name,
            path=path,
            httponly=True,
            secure=_cookie_secure(),
            samesite="lax",
        )


TokenType = Literal["access"]
