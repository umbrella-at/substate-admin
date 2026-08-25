"""auth tables

Revision ID: 0001
Revises:
Create Date: 2026-08-24

The schema and the five tables authentication runs on. No data: the permission catalogue and the
four system roles are written by `substate-admin sync-permissions`, which runs on every deploy
right after this. A migration that seeds rows can only ever seed the catalogue as it was on the
day it was written.

Everything here is spelled out rather than imported from app.models. A revision is a historical
record of what was done to a database, and it has to keep meaning that after the models it was
generated from have moved on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateSchema

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "admin"


def upgrade() -> None:
    # Provisioning deliberately does not create this, so that a laptop, CI and the server all
    # bootstrap through the same code path.
    op.execute(CreateSchema(SCHEMA, if_not_exists=True))

    op.create_table(
        "roles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
        schema=SCHEMA,
    )

    op.create_table(
        "permissions",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_permissions"),
        schema=SCHEMA,
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Lowercased by the application before it gets here, so a plain btree unique index is
        # enough and citext — an extension, therefore a superuser step in provisioning — is not
        # needed.
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.ForeignKeyConstraint(
            ["role_id"],
            [f"{SCHEMA}.roles.id"],
            name="fk_users_role_id_roles",
            # RESTRICT: deleting a role with users attached must fail, not quietly take the users
            # with it or leave them with no permissions.
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            [f"{SCHEMA}.roles.id"],
            name="fk_role_permissions_role_id_roles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["permission_code"],
            [f"{SCHEMA}.permissions.code"],
            name="fk_role_permissions_permission_code_permissions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_code", name="pk_role_permissions"),
        schema=SCHEMA,
    )

    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # sha256 hex of the cookie value. Unique, because rotation looks a token up by hash on
        # every refresh and two rows with the same hash would make that lookup ambiguous.
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("family_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        # Why the row was revoked: superseded, logout, inactive, reuse, family_revoked. The
        # classifier answers a presented token by this value, and answering "the session ended"
        # where the truth is "this token was copied" is the difference between one refusal and
        # revoking every family the user has.
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        # Neither column is meaningful alone. A revoked row with no reason could only be guessed
        # at, and a reason on a live row would be a lie about a token that still works.
        #
        # The name is the bare one, unlike every other constraint in this file: the `ck` naming
        # convention interpolates `%(constraint_name)s`, so it is applied to check constraints
        # that already have a name. Spelling the prefix out here would produce
        # `ck_refresh_tokens_ck_refresh_tokens_...`, truncated to 63 characters — a name no
        # downgrade could find again. The DDL this emits is
        # `CONSTRAINT ck_refresh_tokens_revoked_reason_set_with_revoked_at`.
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_reason IS NULL)",
            name="revoked_reason_set_with_revoked_at",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA}.users.id"],
            name="fk_refresh_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        schema=SCHEMA,
    )

    # Reuse detection revokes every token in a family, and every family of a user: both are
    # writes across a set of rows selected by these two columns, on the login path.
    op.create_index(
        "ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"], unique=False, schema=SCHEMA
    )
    op.create_index(
        "ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False, schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens", schema=SCHEMA)
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens", schema=SCHEMA)
    op.drop_table("refresh_tokens", schema=SCHEMA)
    op.drop_table("role_permissions", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
    op.drop_table("permissions", schema=SCHEMA)
    op.drop_table("roles", schema=SCHEMA)

    # The schema itself stays. Alembic keeps alembic_version inside it and is holding this
    # revision's row open while this function runs: a plain DROP SCHEMA would fail on a schema
    # that is not empty, and a CASCADE would take alembic's own bookkeeping with it and leave the
    # run updating a table it had just deleted. An empty schema costs nothing and downgrading to
    # base leaves a database with no admin tables in it, which is what base means.
