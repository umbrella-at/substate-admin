"""Engine, session factory, database probe, and the clock.

The engine is built on first use and never at import time. That is a constraint, not a
preference: `import app.db` has to work on a machine with no database and no DATABASE_URL, or
else alembic, the CLI, and collecting a test module all need a live Postgres before they can do
anything at all.
"""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy import text as sql_text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_log = structlog.get_logger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

# A callable rather than a call, so a test can hand a token service its own clock instead of
# monkeypatching datetime for the whole process.
NowProvider = Callable[[], datetime]


def utc_now() -> datetime:
    """The current instant, always aware, always UTC.

    Authentication never runs on a shifted clock. A demo token names a world that may believe it
    is any date it likes; the token's own `exp` is measured against this.
    """
    return datetime.now(UTC)


def get_now() -> NowProvider:
    """FastAPI dependency yielding the clock. Override it to control token expiry in a test."""
    return utc_now


def get_engine() -> AsyncEngine:
    """The process-wide async engine, constructed on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url.get_secret_value(),
            # Ten connections at most against a Postgres sharing 2 GB with this process. The
            # ceiling is the box, not the traffic.
            pool_size=5,
            max_overflow=5,
            # Without this SQLAlchemy renders the bound parameters into the message of any DBAPI
            # error, and that message is what the 500 handler and the request line both write
            # down. One deadlock or one dropped connection during a login would put the operator's
            # address and their argon2 hash in the journal — twice — after the rest of this
            # service has gone to some trouble to keep both out of it.
            hide_parameters=True,
            # The box sleeps its idle connections through a nightly restart of nothing in
            # particular; pre_ping turns "server closed the connection unexpectedly" into one
            # extra round trip.
            pool_pre_ping=True,
        )
    return _engine


def make_sessionmaker(bind: AsyncConnection | AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build a session factory over an explicit bind.

    Tests bind to the connection that owns the outer transaction and roll it back afterwards, so
    no test leaves a row behind. `create_savepoint` is what makes that work when the code under
    test commits: the session's commit ends a SAVEPOINT rather than the enclosing transaction.
    """
    return async_sessionmaker(
        bind=bind,
        # Attributes must survive a commit. Expiring them means the next attribute access emits
        # SQL, and SQL from an attribute access in a coroutine is a MissingGreenlet.
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """The process-wide session factory, bound to the lazy engine."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = make_sessionmaker(get_engine())
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session for one request.

    Nothing is committed here. A route that writes says so; leaving the commit to the dependency
    would make every read path a potential writer.
    """
    async with get_sessionmaker()() as session:
        yield session


async def check_database() -> bool:
    """Ask Postgres to answer SELECT 1. The health endpoint's only source of truth."""
    try:
        async with get_engine().connect() as connection:
            await connection.execute(sql_text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        # The type and nothing else. A psycopg connection error carries the DSN it failed to
        # connect with, and the DSN carries the password.
        _log.warning("database_probe_failed", error=type(exc).__name__)
        return False
    return True


async def dispose_engine() -> None:
    """Close every pooled connection and forget the engine. Called on application shutdown."""
    global _engine, _sessionmaker
    engine, _engine, _sessionmaker = _engine, None, None
    if engine is not None:
        await engine.dispose()
