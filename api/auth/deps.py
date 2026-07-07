"""FastAPI dependencies for resolving the authenticated user from the
incoming request's `Authorization: Bearer ...` header.

Three flavours:
  - current_user_required: 401 if missing/invalid token. Use on protected endpoints.
  - current_user: alias of `current_user_required` — sugar for readability.
  - optional_user: returns None if no token; doesn't 401. Use on endpoints
    that show different content for anon vs logged-in users.

User accounts marked `is_active = false` are rejected as if their token
were invalid (no special error, to avoid enumeration).
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from db.auth_session import get_auth_db
from db.models import User
from logging_setup import user_id_var
from sentry_setup import set_user as sentry_set_user

from .tokens import TokenError, decode_token


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def current_user_required(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_auth_db),
) -> User:
    """Required auth dependency. 401 on any missing/invalid/inactive case.

    Async-typed (despite doing no awaits internally) so FastAPI runs us in
    the request's event loop rather than a threadpool — that way the
    `user_id_var.set(...)` below propagates into the endpoint's log context.
    """
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = decode_token(token, expected_type="access")
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        # Same message either way — don't help token attackers distinguish
        # "user deleted" from "user disabled" from "wrong user id signed".
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Bind user identity into the per-request log context + Sentry scope.
    # Every log line from here on includes user_id automatically.
    user_id_var.set(str(user.id))
    sentry_set_user(str(user.id), user.email)
    return user


# Alias for readability at call sites: `Depends(current_user)`.
current_user = current_user_required


async def optional_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_auth_db),
) -> Optional[User]:
    """Optional auth — returns None instead of raising when there's no token."""
    if not authorization:
        return None
    try:
        return await current_user_required(authorization=authorization, db=db)
    except HTTPException:
        return None


async def admin_required(user: User = Depends(current_user_required)) -> User:
    """Adds an is_admin check on top of current_user_required."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin required",
        )
    return user
