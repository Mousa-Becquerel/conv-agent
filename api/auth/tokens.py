"""JWT issue + decode.

Two token types share the same `JWT_SECRET` and HS256 signature; they differ
only by `type` claim and TTL:
  - access:  short-lived (~30 min), sent on every request as `Authorization: Bearer`.
  - refresh: long-lived (~14 days), exchanged at /auth/refresh for a new access.

Storing refresh tokens client-side is fine for invite-only single-tenant; the
revocation strategy is "rotate JWT_SECRET to log everyone out". When we add
multi-tenant or session management later, refresh tokens move to a DB-backed
allowlist.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

import jwt


JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "14"))


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or signature-invalid.

    The endpoint translates this into 401; the message is kept generic to
    avoid leaking which specific failure mode occurred.
    """


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(payload: dict[str, Any]) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not configured")
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_access_token(user_id: UUID) -> str:
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": _now(),
        "exp": _now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return _encode(payload)


def create_refresh_token(user_id: UUID) -> str:
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": _now(),
        "exp": _now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return _encode(payload)


def decode_token(token: str, expected_type: Literal["access", "refresh"]) -> UUID:
    """Verify signature + expiry + token type; return the user id.

    Raises TokenError on any failure. The expected_type guard prevents a
    refresh token from being accepted where an access token is required
    (and vice versa).
    """
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not configured")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise TokenError("token expired")
    except jwt.InvalidTokenError:
        raise TokenError("invalid token")

    if payload.get("type") != expected_type:
        raise TokenError("wrong token type")

    sub = payload.get("sub")
    if not sub:
        raise TokenError("token missing subject")
    try:
        return UUID(sub)
    except (TypeError, ValueError):
        raise TokenError("malformed subject")
