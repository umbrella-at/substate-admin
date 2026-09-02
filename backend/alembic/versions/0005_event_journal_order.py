"""event journal order

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02

Every event one engine call emits carries the same `occurred_at` — the call reads the clock once —
so a feed ordered by that instant and tie-broken by a random uuid shows "Renewed" above the payment
that caused it about half the time. `seq` is the order the rows were written in, which is the order
the engine produced them in.

`bigserial` rather than a column the writer sets: the journal is written with COPY from more than
one place, and a sequence is the one ordering nothing has to remember to maintain.

Spelled out rather than imported from app.models, for the reason 0001 gives.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "admin"


def upgrade() -> None:
    op.add_column(
        "event_journal",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        schema=SCHEMA,
    )
    # The feed's order, made an index rather than a sort: one subscriber's page is
    # `WHERE world_id = ? AND user_id = ? ORDER BY occurred_at DESC, seq DESC`, and the existing
    # two-column index cannot serve the ordering.
    op.execute(
        f"CREATE INDEX ix_event_journal_world_id_user_id_occurred_at_seq "
        f"ON {SCHEMA}.event_journal (world_id, user_id, occurred_at DESC, seq DESC)"
    )
    op.drop_index("ix_event_journal_world_id_user_id", table_name="event_journal", schema=SCHEMA)


def downgrade() -> None:
    op.create_index(
        "ix_event_journal_world_id_user_id",
        "event_journal",
        ["world_id", "user_id"],
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_event_journal_world_id_user_id_occurred_at_seq",
        table_name="event_journal",
        schema=SCHEMA,
    )
    op.drop_column("event_journal", "seq", schema=SCHEMA)
