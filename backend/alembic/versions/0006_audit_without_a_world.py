"""audit without a world

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-03

Editing a role is not a fact about a world. Every row until now was an operation on a subscription
and therefore happened somewhere; a grant taken away from a role happened to the panel itself, and
naming a world for it would be filing it under a place it has nothing to do with.

Nullable rather than a sentinel string, so the screen can ask "which world" and get no answer
instead of an answer that is not true.

Spelled out rather than imported from app.models, for the reason 0001 gives.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "admin"


def upgrade() -> None:
    op.alter_column("audit_log", "world_id", existing_type=sa.Text(), nullable=True, schema=SCHEMA)


def downgrade() -> None:
    # Rows with no world cannot be made to have one, and inventing a world id for them would put
    # them under a world that never saw them. They go, which is what a downgrade of this is.
    audit_log = sa.table("audit_log", sa.column("world_id"), schema=SCHEMA)
    op.execute(audit_log.delete().where(audit_log.c.world_id.is_(None)))
    op.alter_column("audit_log", "world_id", existing_type=sa.Text(), nullable=False, schema=SCHEMA)
