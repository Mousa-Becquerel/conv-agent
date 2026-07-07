"""drop FKs on users — users now live in the shared apps_shared_pg DB

After Phase 2 of the multi-app deployment, the `users` table moved out of
each app's local Postgres and into the shared `apps_shared_pg` container
(`AUTH_DATABASE_URL`). The FK constraints on `conversations.user_id` and
`qa_log.user_id` still point at THIS DB's `users` table, which is now
empty — every INSERT into `conversations` fails with a
`ForeignKeyViolation`.

The correct model post-Phase-2: `user_id` is a "loose reference" —
validated by `current_user_required` at auth time via the shared DB, not
by the local DB engine. This migration drops the two constraints and
leaves the columns untouched.

We deliberately DO NOT drop the local `users` table itself — Alembic's
schema history stays intact, and if someone ever wants to run this app
in single-tenant mode (without a shared users DB) the local table is
still there.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Both constraints are optional — if the DB was created after some future
# migration removed them, DROP CONSTRAINT IF EXISTS keeps the operation
# idempotent so re-running never errors.
_FKS_TO_DROP = [
    ("conversations", "fk_conversations_user_id_users"),
    ("qa_log",        "fk_qa_log_user_id_users"),
]


def upgrade() -> None:
    for table, name in _FKS_TO_DROP:
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}";')


def downgrade() -> None:
    # Restore the FKs at their original ondelete behaviour. Requires the
    # shared users table to be reachable at the same location the app was
    # originally configured with — otherwise the constraint check fails
    # on any existing row.
    op.create_foreign_key(
        "fk_conversations_user_id_users",
        "conversations", "users",
        ["user_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_qa_log_user_id_users",
        "qa_log", "users",
        ["user_id"], ["id"],
        ondelete="SET NULL",
    )
