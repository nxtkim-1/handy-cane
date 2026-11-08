from __future__ import annotations

import uuid
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.core.db import get_db
from backend.app.core.security import (create_access_token, create_refresh_token, decode_token, hash_secret,
                                       verify_secret)
from backend.app.deps import ApiError, audit
from backend.app.models import RefreshToken, User
from backend.app.schemas import LoginIn, RefreshIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the email is unknown so response time does not reveal which emails exist.
_DUMMY_HASH = hash_secret("not-a-real-password")


def _issue(db: Session, user: User) -> TokenOut:
    refresh, exp, jti = create_refresh_token(str(user.user_id))
    db.add(RefreshToken(jti=jti, user_id=user.user_id, expires_at=exp))
    return TokenOut(access_token=create_access_token(str(user.user_id)), refresh_token=refresh)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    rl_key = f"{body.email.strip().lower()}|{request.client.host if request.client else '?'}"
    if ratelimit.login_failures.blocked(rl_key):
        raise ApiError(429, "rate_limited", "Too many failed logins; try again in a few minutes")
    user = db.scalars(select(User).where(User.email == body.email.strip().lower())).first()
    ok = verify_secret(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or user.disabled_at is not None:
        ratelimit.login_failures.hit(rl_key)
        raise ApiError(401, "invalid_credentials", "Incorrect email or password")
    ratelimit.login_failures.clear(rl_key)
    out = _issue(db, user)
    audit(db, user.user_id, "login")
    db.commit()
    return out


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, "refresh")
        uid = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise ApiError(401, "invalid_token", "Invalid or expired refresh token")
    row = db.get(RefreshToken, payload["jti"])
    if row is None or row.revoked_at is not None:
        # Reuse of a rotated token: revoke the whole family for this user.
        if row is not None:
            for r in db.scalars(select(RefreshToken).where(RefreshToken.user_id == uid,
                                                            RefreshToken.revoked_at.is_(None))):
                r.revoked_at = datetime.now(timezone.utc)
            db.commit()
        raise ApiError(401, "invalid_token", "Refresh token revoked")
    user = db.get(User, uid)
    if user is None or user.disabled_at is not None:
        raise ApiError(401, "invalid_token", "Unknown or disabled user")
    row.revoked_at = datetime.now(timezone.utc)  # rotation
    out = _issue(db, user)
    db.commit()
    return out
