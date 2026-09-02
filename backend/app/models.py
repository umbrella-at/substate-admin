"""Every table this panel owns.

Five of them are authentication, and the rest are what the panel knows that `substate` does not:
a world's events, the projection beside them, and the record of what operators did.

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
        # Two access patterns. The general feed reads one world newest first, so the ordering is
        # in the index; a subscriber's card reads one subscriber, and `occurred_at` is deliberately
        # NOT in that second index — at a mean of eleven events per subscriber the sort is a few
        # dozen rows in memory, and an index widened for a cost nobody can measure is an index
        # somebody has to maintain.
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


class AuditLog(Base):
    """What an operator did, and how it went.

    Narrow on purpose: operations over subscriptions and, later, edits to roles. Signing in,
    signing out and changing a filter are not here — those are authentication and navigation, and
    they belong in the structured log, where they do not bury the handful of rows that say
    somebody changed something.

    It records ATTEMPTS, not successes. A refusal is the row an investigation is most likely to be
    looking for — somebody tried to cancel this subscription and was told no — and a log that kept
    only what worked could not answer that question. It is also the only way the two journals stay
    consistent: the engine catches a subscription up with the clock BEFORE it decides to refuse, so
    a refused operation can be the cause of a state change the event journal does record.

    Not purged with the world, unlike the event journal. That journal is a record of a world and
    dies with it; this is a record of people, and the base world being rebuilt at every restart is
    no reason to forget who did what.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # RESTRICT: an operator with a history cannot be deleted out from under it.
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[str] = mapped_column(Text)

    # "ok" or "refused", with the ErrorCode beside it. Two columns rather than one holding both,
    # so the screen's filter is a two-value question and not a string comparison against "ok".
    outcome: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text, default=None)

    # The arguments of the operation. Never its result: what happened is in the event journal, and
    # a copy here would be a second answer to a question `substate` already answers.
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    world_id: Mapped[str] = mapped_column(Text)
    # HMAC, never the address. The pepper is what stops the whole IPv4 space being a lookup table,
    # and no response carries this column: a truncated HMAC on a screen is not evidence.
    ip_hash: Mapped[str] = mapped_column(Text)
    # `now()` is the transaction's timestamp, not the statement's, and each operation is its own
    # request — so rows written together are simultaneous by construction, which is what the id
    # tie-break in the reader's ORDER BY exists for.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # A refusal with no code says only that something failed, which is the one thing an audit
        # row must never say.
        CheckConstraint(
            "(outcome = 'refused') = (error_code IS NOT NULL)",
            name="error_code_set_when_refused",
        ),
        # The screen reads one world newest first; a subscriber's own trail reads one target.
        Index("ix_audit_log_world_id_occurred_at", "world_id", occurred_at.desc()),
        Index("ix_audit_log_target_id_occurred_at", "target_id", occurred_at.desc()),
        {"schema": SCHEMA},
    )
