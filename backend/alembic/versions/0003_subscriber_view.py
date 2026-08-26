"""subscriber view

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-26

A projection, never a source of truth. The state of a subscription is whatever the engine says it
is; what lives here is the pair of facts the engine has no business holding — when somebody last
turned up, and what to call them on screen.

`last_active_at` has no unit. It is not traffic, not a counter, not a volume.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "admin"


def upgrade() -> None:
    op.create_table(
        "subscriber_view",
        sa.Column("world_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("world_id", "user_id", name="pk_subscriber_view"),
        schema=SCHEMA,
    )
    # The quiet cohort is "an active subscription whose last_active_at is older than the
    # threshold", answered one world at a time.
    op.create_index(
        "ix_subscriber_view_world_id_last_active_at",
        "subscriber_view",
        ["world_id", "last_active_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscriber_view_world_id_last_active_at", table_name="subscriber_view", schema=SCHEMA
    )
    op.drop_table("subscriber_view", schema=SCHEMA)
