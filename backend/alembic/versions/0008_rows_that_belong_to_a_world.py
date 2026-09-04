"""rows that belong to a world

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-04

An operator and a role are facts about this installation. A sandbox needs its own, because the
demonstration includes the screen that edits them, and a visitor editing the real ones would take
`users.write` off `admin` for everybody until the next restart.

So both tables gain a nullable `world_id`: NULL is the real thing, a value is a copy that lives
and dies with one sandbox. Every query over either table is scoped to the caller's world from this
revision onwards.

WHICH BREAKS BOTH UNIQUE CONSTRAINTS, AND NOT IN THE WAY A COMPOSITE KEY WOULD FIX.

`UNIQUE (world_id, email)` is not the rule wanted here: Postgres treats NULLs as distinct, so
every real operator would be unique against nobody and two rows could share an address.

The rule is two rules — one address per installation, one address per sandbox — written as two
partial indexes, which is the only shape that says exactly that.

Spelled out rather than imported from app.models, for the reason 0001 gives.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "admin"


def upgrade() -> None:
    for table in ("users", "roles"):
        op.add_column(table, sa.Column("world_id", sa.Text(), nullable=True), schema=SCHEMA)

    op.drop_constraint("uq_users_email", "users", type_="unique", schema=SCHEMA)
    op.drop_constraint("uq_roles_code", "roles", type_="unique", schema=SCHEMA)

    for table, column in (("users", "email"), ("roles", "code")):
        op.create_index(
            f"ix_{table}_{column}",
            table,
            [column],
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text("world_id IS NULL"),
        )
        op.create_index(
            f"ix_{table}_world_id_{column}",
            table,
            ["world_id", column],
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text("world_id IS NOT NULL"),
        )

    op.create_table(
        "demo_sandboxes",
        # The world's key, which is also the key of every row it owns elsewhere. Text, like the
        # other three tables that carry one, because the base world's id is the word `base`.
        sa.Column("world_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Pushed forward by activity, and never past `ceiling_at`. The reaper reads the first and
        # the session endpoint enforces the second.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ceiling_at", sa.DateTime(timezone=True), nullable=False),
        # HMAC, never the address, exactly as the audit stores it.
        sa.Column("ip_hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("world_id", name="pk_demo_sandboxes"),
        sa.CheckConstraint("expires_at <= ceiling_at", name="ck_demo_sandboxes_within_the_ceiling"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("demo_sandboxes", schema=SCHEMA)

    for table, column in (("users", "email"), ("roles", "code")):
        op.drop_index(f"ix_{table}_world_id_{column}", table_name=table, schema=SCHEMA)
        op.drop_index(f"ix_{table}_{column}", table_name=table, schema=SCHEMA)

    # Rows belonging to a sandbox cannot survive a column that no longer exists, and leaving them
    # would make the constraint below fail on a duplicate address nobody can see.
    op.execute(sa.text("DELETE FROM admin.users WHERE world_id IS NOT NULL"))
    op.execute(sa.text("DELETE FROM admin.roles WHERE world_id IS NOT NULL"))

    op.create_unique_constraint("uq_users_email", "users", ["email"], schema=SCHEMA)
    op.create_unique_constraint("uq_roles_code", "roles", ["code"], schema=SCHEMA)

    for table in ("users", "roles"):
        op.drop_column(table, "world_id", schema=SCHEMA)
