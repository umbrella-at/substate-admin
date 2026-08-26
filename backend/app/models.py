"""The five tables behind authentication.

Every table lives in the `admin` schema; nothing is ever created in `public`. There are no soft
deletes: a row that is gone is gone, and a user that must stop working is `is_active = false`.
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SCHEMA = "admin"


class Base(DeclarativeBase):
    """Declarative base for every table in this application."""

    # The naming convention is fixed here, before the first migration, so that autogenerate
    # emits names that a downgrade can find again. Alembic drops constraints by name; a
    # constraint Postgres named itself is a constraint no later revision can reliably remove.
    metadata = MetaData(
        schema=SCHEMA,
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )

    # Mapping the annotations once is what makes "every timestamp is timestamptz" structural
    # rather than a rule somebody has to remember on the next column. A naive timestamp in an
    # authentication table is an outage waiting for a daylight-saving boundary.
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
        uuid.UUID: UUID(as_uuid=True),
        str: Text(),
        bool: Boolean(),
    }


def normalize_email(raw: str) -> str:
    """Fold an address to the form stored in `users.email`.

    The unique index is a plain btree over a text column — no citext — so the lowercasing has to
    happen here, on every path that reads or writes an address: login, the CLI, and the rate
    limiter that counts failures per address.
    """
    return raw.strip().lower()


class Role(Base):
    """A named bundle of permissions."""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]

    # System roles are force-synced from app.permissions on every deploy and may not be deleted;
    # that rule is enforced in the application, not by a constraint, because it is about who may
    # issue the DELETE rather than about what the row contains.
    is_system: Mapped[bool] = mapped_column(default=False, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Permission(Base):
    """One permission code, keyed by the code itself.

    The code is the primary key: it is the value that travels, it is what a route asks for, and a
    surrogate id would only add a join to every question anyone asks of this table.
    """

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[str]


class RolePermission(Base):
    """Which permissions a role grants."""

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.permissions.code", ondelete="CASCADE"), primary_key=True
    )


class User(Base):
    """An operator of the admin panel."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())

    # Stored lowercased by normalize_email() above.
    email: Mapped[str] = mapped_column(unique=True)

    # argon2id. It never leaves the process: no schema exposes it and no log line may contain it.
    password_hash: Mapped[str]

    # RESTRICT, not CASCADE or SET NULL: deleting a role out from under its users would either
    # delete the users or leave them with no permissions at all, and both are silent. The delete
    # fails instead, and whoever wants the role gone reassigns its users first.
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.roles.id", ondelete="RESTRICT")
    )

    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    last_login_at: Mapped[datetime | None]

    # Eager and inner-joined, because the FK is NOT NULL and every authenticated request needs
    # role.code: selecting a user is the one joined query the request path is allowed. A lazy
    # load here would not be a slow query, it would be a MissingGreenlet at runtime — the ORM
    # cannot emit SQL from an attribute access inside a coroutine.
    role: Mapped[Role] = relationship(lazy="joined", innerjoin=True)


class RefreshToken(Base):
    """One issued refresh token.

    Rows are never deleted on rotation or logout — `used_at`, `revoked_at` and `revoked_reason`
    are what make reuse detectable at all. A token that vanished on use would be indistinguishable
    from a token that was never issued. They are deleted by the reaper, long after the token they
    describe stopped being exchangeable.
    """

    __tablename__ = "refresh_tokens"

    # The reason is what separates "this session ended" from "this token was copied", and the two
    # answers are not interchangeable: one is a refusal, the other revokes every family the user
    # has. A revoked row with no reason would have to be guessed at, so the pairing is a
    # constraint rather than a convention.
    __table_args__ = (
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_reason IS NULL)",
            name="revoked_reason_set_with_revoked_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), index=True
    )

    # sha256 hex of the value in the cookie, under a unique index. Not argon2: a salted hash
    # cannot be looked up by value, and every refresh would spend 50-100 ms of the single CPU
    # this box has. The token is 256 bits of `secrets.token_urlsafe` output, so there is no
    # dictionary to attack and nothing for a slow hash to buy.
    token_hash: Mapped[str] = mapped_column(unique=True)

    # One family per login, minted at login and never re-parented. No foreign key: the family is
    # an identifier for a device's chain of tokens, not a row in a table of its own.
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)

    issued_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # min(issued_at + 30 days, family_expires_at): sliding, but capped by the family.
    expires_at: Mapped[datetime]

    # Set once, at login, and never extended. This is the hard end of a session.
    family_expires_at: Mapped[datetime]

    used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]

    # One of app.security.refresh.RevocationReason, written in the same statement that sets
    # `revoked_at`. Text and not an enum type: the vocabulary belongs to the application, and a
    # Postgres enum would make adding a reason a migration and a lock on this table.
    revoked_reason: Mapped[str | None]


class EventJournal(Base):
    """Every event `substate` emitted, in the world that emitted it.

    Rows belong to a world and die with it. The base world is rebuilt from the seeder at every
    start, so its journal is deleted and rewritten each time — a journal that outlived its world
    would reference subscribers who no longer exist, which is worse than no journal at all.

    `payload_json` holds whatever the event carried beyond the columns above it. The columns are
    the ones the panel filters and sorts on; the payload is the rest, and reading it back is a
    detail view rather than a query.
    """

    __tablename__ = "event_journal"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    world_id: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # The panel reads one world's events newest first, which is the only access pattern this
        # table has and the only index it gets.
        Index("ix_event_journal_world_id_occurred_at", "world_id", occurred_at.desc()),
        Index("ix_event_journal_world_id_user_id", "world_id", "user_id"),
        {"schema": SCHEMA},
    )


class SubscriberView(Base):
    """What the panel knows about a subscriber that the engine does not.

    A projection, never a source of truth: the state of a subscription is whatever `substate` says
    it is, and nothing here may be read as an answer to that. What lives here is the pair of facts
    the engine has no business holding — when the person last used the service, and what to call
    them on screen.

    `last_active_at` has no unit. It is not traffic, not a counter, not a volume: it is the mark
    that somebody turned up. The application writes it; the engine has never heard of it.
    """

    __tablename__ = "subscriber_view"

    world_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        # The quiet cohort is "active subscription, last_active_at older than the threshold", and
        # it is answered per world.
        Index("ix_subscriber_view_world_id_last_active_at", "world_id", "last_active_at"),
        {"schema": SCHEMA},
    )
