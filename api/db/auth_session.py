"""Dedicated SQLAlchemy engine for the users table.

When `AUTH_DATABASE_URL` is set, users live in a SHARED Postgres DB that
every Regalgrid-family app connects to for auth (single sign-on). When
unset, we fall back to `DATABASE_URL` so single-app / dev deployments keep
working.

Everything auth-related — login, refresh, `current_user_required` reads,
`scripts.create_user` writes — routes through the session yielded by
`get_auth_db()`. Domain tables (conversations, messages, qa_log) still use
the main `get_db()` in `db.session`.
"""
import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .session import DATABASE_URL as _MAIN_URL

log = logging.getLogger("conv_agent.auth_db")

_AUTH_URL = os.getenv("AUTH_DATABASE_URL") or _MAIN_URL
_IS_SHARED = os.getenv("AUTH_DATABASE_URL") is not None

if _IS_SHARED:
    log.info(
        "auth backend: shared users DB at %s",
        _AUTH_URL.split("@")[-1] if "@" in _AUTH_URL else _AUTH_URL,
    )
else:
    log.info("auth backend: main database (single-app mode)")

auth_engine = create_engine(
    _AUTH_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,
    future=True,
)

AuthSessionLocal = sessionmaker(bind=auth_engine, autoflush=False, expire_on_commit=False)


def get_auth_db():
    """FastAPI dependency for the SHARED users DB (or main DB in single-app mode)."""
    db: Session = AuthSessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_shared_auth() -> bool:
    return _IS_SHARED
