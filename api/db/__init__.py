"""Relational-state layer: SQLAlchemy models, session factory, and Alembic
migrations live under this package.

The vector store (Qdrant) is unchanged — Postgres is strictly for users,
conversations, messages, and the append-only `qa_log` audit table.
"""

from .base import Base
from .session import SessionLocal, engine, get_db

__all__ = ["Base", "SessionLocal", "engine", "get_db"]
