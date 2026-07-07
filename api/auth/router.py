"""Auth endpoints: login, me, refresh.

Invite-only — there's intentionally no /register. New accounts are created
via the `scripts.create_user` admin CLI (see api/scripts/create_user.py).

Login error messages are deliberately vague ("invalid credentials") to avoid
account-enumeration probes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_db
from db.models import User
from rate_limit import login_rate_limit

from .deps import current_user_required
from .passwords import hash_password, needs_rehash, verify_password
from .tokens import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)


router = APIRouter(prefix="/auth", tags=["Auth"])


# ---------- Request / response shapes ----------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds — convenience for clients


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    is_admin: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


# ---------- POST /auth/login ----------
# Rate-limited per-IP because the caller is not yet authenticated. Protects
# against credential-stuffing / password-guessing.
@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    _rl: None = Depends(login_rate_limit),
) -> TokenResponse:
    user = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()

    # Same generic error for unknown email AND wrong password, AND inactive.
    # Burns ~one argon2 verification cycle on the no-user path to keep
    # timing roughly equal — defeats trivial enumeration via response time.
    if user is None:
        # Run a dummy verify to roughly equalize timing.
        verify_password(payload.password, "$argon2id$v=19$m=65536,t=3,p=4$invalid$invalid")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )

    # Transparent password-hash upgrade: if argon2 params have changed since
    # this hash was stored, rebuild with current params now that we have the
    # plaintext.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------- GET /auth/me ----------
@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user_required)) -> UserOut:
    return _user_out(user)


# ---------- POST /auth/refresh ----------
@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> AccessTokenResponse:
    """Exchange a refresh token for a fresh access token. Does NOT rotate
    the refresh token — clients hold a single long-lived refresh until it
    expires, then have to re-login. Add rotation later if needed."""
    try:
        user_id = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )

    return AccessTokenResponse(
        access_token=create_access_token(user.id),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
