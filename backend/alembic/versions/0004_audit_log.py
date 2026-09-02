"""audit log

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-02

What an operator did, as opposed to what the engine did about it. Deliberately not the same table
as the event journal: one is a record of people and survives the world it happened in, the other
is a record of a world and dies with it.

Spelled out rather than imported from app.models, for the reason 0001 gives.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "admin"


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("world_id", sa.Text(), nullable=False),
        sa.Column("ip_hash", sa.Text(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        # A refusal with no code says only that something failed, which is the one thing an audit
        # row must never say. Paired in the database for the same reason revoked_reason is.
        sa.CheckConstraint(
            "(outcome = 'refused') = (error_code IS NOT NULL)",
            # Bare, like 0001: the metadata naming convention adds the ck_<table>_ prefix.
            name="error_code_set_when_refused",
        ),
        # RESTRICT, so an operator with a history cannot be deleted out from under it. An audit
        # row whose actor is gone answers nothing, which is the one thing this table exists to do.
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            [f"{SCHEMA}.users.id"],
            name="fk_audit_log_actor_user_id_users",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    # Two access patterns, both newest first, so DESC is in the index rather than left to the
    # planner: the screen reads a world, and a subscriber's own trail reads one target.
    op.execute(
        f"CREATE INDEX ix_audit_log_world_id_occurred_at "
        f"ON {SCHEMA}.audit_log (world_id, occurred_at DESC)"
    )
    op.execute(
        f"CREATE INDEX ix_audit_log_target_id_occurred_at "
        f"ON {SCHEMA}.audit_log (target_id, occurred_at DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_target_id_occurred_at", table_name="audit_log", schema=SCHEMA)
    op.drop_index("ix_audit_log_world_id_occurred_at", table_name="audit_log", schema=SCHEMA)
    op.drop_table("audit_log", schema=SCHEMA)
