"""audit order

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-04

`now()` is the transaction's timestamp rather than the statement's, so every row written inside one
transaction shares an `occurred_at` — and the reader tie-broke on a random uuid, which orders rows
arbitrarily. Three edits to one role came back delete, update, create.

The same defect 0005 fixed for the event journal, and the same remedy: a sequence is the one
ordering nothing has to remember to maintain. The audit is the second of the two journals and had
been left with the first one's bug.

Spelled out rather than imported from app.models, for the reason 0001 gives.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "admin"


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        schema=SCHEMA,
    )
    # The screen's own order, made an index rather than a sort: one world newest first, and the
    # existing two-column index cannot serve the tie-break.
    op.execute(
        f"CREATE INDEX ix_audit_log_world_id_occurred_at_seq "
        f"ON {SCHEMA}.audit_log (world_id, occurred_at DESC, seq DESC)"
    )
    op.drop_index("ix_audit_log_world_id_occurred_at", table_name="audit_log", schema=SCHEMA)


def downgrade() -> None:
    op.create_index(
        "ix_audit_log_world_id_occurred_at",
        "audit_log",
        ["world_id", sa.text("occurred_at DESC")],
        schema=SCHEMA,
    )
    op.drop_index("ix_audit_log_world_id_occurred_at_seq", table_name="audit_log", schema=SCHEMA)
    op.drop_column("audit_log", "seq", schema=SCHEMA)
