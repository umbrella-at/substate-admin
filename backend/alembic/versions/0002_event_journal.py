"""event journal

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-26

Every event the engine emitted, in the world that emitted it. Its own revision rather than one
shared with the projection: the two tables answer different questions, arrive for different
reasons, and a revision that creates both would have to be reverted as a pair.

Spelled out rather than imported from app.models, for the reason 0001 gives.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "admin"


def upgrade() -> None:
    op.create_table(
        "event_journal",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("world_id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event_journal"),
        schema=SCHEMA,
    )
    # The panel reads one world's events newest first. That is the only access pattern this table
    # has, and DESC is part of the index rather than left to the planner because the ordering is
    # the query.
    op.execute(
        f"CREATE INDEX ix_event_journal_world_id_occurred_at "
        f"ON {SCHEMA}.event_journal (world_id, occurred_at DESC)"
    )
    op.create_index(
        "ix_event_journal_world_id_user_id",
        "event_journal",
        ["world_id", "user_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_event_journal_world_id_user_id", table_name="event_journal", schema=SCHEMA)
    op.drop_index(
        "ix_event_journal_world_id_occurred_at", table_name="event_journal", schema=SCHEMA
    )
    op.drop_table("event_journal", schema=SCHEMA)
