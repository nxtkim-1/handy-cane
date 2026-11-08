from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from backend.app.core.config import settings

_ph = PasswordHasher()  # argon2id


def hash_secret(plain: str) -> str:
    return _ph.hash(plain)


def verify_secret(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _encode(sub: str, kind: str, ttl: timedelta) -> tuple[str, datetime, str]:
    now = datetime.now(timezone.utc)
    exp = now + ttl
    jti = uuid.uuid4().hex
    token = jwt.encode(
        {"sub": sub, "typ": kind, "jti": jti, "iat": now, "exp": exp},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    return token, exp, jti


def create_access_token(user_id: str) -> str:
    return _encode(user_id, "access", timedelta(minutes=settings.access_token_minutes))[0]


def create_refresh_token(user_id: str) -> tuple[str, datetime, str]:
    """Returns (token, expires_at, jti)."""
    return _encode(user_id, "refresh", timedelta(days=settings.refresh_token_days))


def decode_token(token: str, expected_type: str) -> dict:
    """Raises jwt.PyJWTError on any problem."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload
