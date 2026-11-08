"""Auth dependencies. All patient-scoped endpoints go through require_care_team (MASTER 16.1)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.core.security import decode_token
from backend.app.models import AuditLog, CareTeam, User

bearer = HTTPBearer(auto_error=False)


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(status_code=status, detail={"code": code, "message": message})


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise ApiError(401, "not_authenticated", "Missing bearer token")
    try:
        payload = decode_token(creds.credentials, "access")
        uid = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise ApiError(401, "invalid_token", "Invalid or expired token")
    user = db.get(User, uid)
    if user is None or user.disabled_at is not None:
        raise ApiError(401, "invalid_token", "Unknown or disabled user")
    return user


@dataclass
class Access:
    user: User
    patient_id: uuid.UUID
    relation: str
    can_dismiss_events: bool


def get_membership(db: Session, user: User, patient_id: uuid.UUID,
                   relations: tuple[str, ...] | None = None) -> Access:
    """Single place where care-team access is decided. 403 for anything that is not an active membership."""
    row = db.scalars(select(CareTeam).where(
        CareTeam.patient_id == patient_id, CareTeam.user_id == user.user_id, CareTeam.revoked_at.is_(None))).first()
    if row is None or (relations is not None and row.relation not in relations):
        raise ApiError(403, "forbidden", "You do not have access to this patient")
    return Access(user, patient_id, row.relation, row.can_dismiss_events)


def require_care_team(*relations: str):
    """Dependency factory for routes with a `{patient_id}` path parameter."""
    def dep(patient_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Access:
        return get_membership(db, user, patient_id, relations or None)
    return dep


def audit(db: Session, user_id, action: str, patient_id=None, detail: dict | None = None) -> None:
    db.add(AuditLog(at=datetime.now(timezone.utc), user_id=user_id, action=action, patient_id=patient_id,
                    detail=detail))
