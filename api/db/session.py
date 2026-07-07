"""Engine + session factory.

We use sync SQLAlchemy here (not async) to match the existing API pattern —
the chat path is already CPU/IO mixed with `asyncio.to_thread`, and adding
async DB on top adds complexity without much win for our request rates.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://conv_agent:conv_agent_dev@postgres:5432/conv_agent",
)

# pool_pre_ping: validates connections before use, transparently reconnects
# after a Postgres restart. pool_recycle keeps connections fresh under
# managed-Postgres providers that drop idle ones.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency: yields a session, closes it on response end."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
