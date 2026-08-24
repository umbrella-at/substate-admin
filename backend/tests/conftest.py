"""The fixtures the suite is built on.

The strategy is one decision repeated everywhere: the database is migrated and seeded once, and
then no test writes anything that outlives it. Each test opens its own connection, begins a
transaction, hands that connection to both itself and the application, and rolls it back at
teardown. There is no TRUNCATE between tests and no second migration — a suite that rebuilds the
schema per test spends its time on DDL, and one that cleans up with DELETE statements eventually
forgets a table.

Requests never leave the process. `httpx.ASGITransport` calls the application directly, so there
is no port to allocate, no server to wait for, and no chance of a test passing against a stale
process someone left running.

The environment is written below rather than expected: importing `app.main` builds the
application, which reads the settings, and a suite that only runs for whoever exported the right
three variables is a suite that fails differently on every machine.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Final

# The application refuses to start without these three, which is the point of them. A test run is
# still a run of that application, so they are set here — before anything from `app` is imported —
# rather than demanded from whoever typed `pytest`.
TEST_DATABASE_URL: Final = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/substate_admin_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("JWT_SECRET", "a-signing-secret-that-exists-only-in-this-process")
os.environ.setdefault("IP_HASH_PEPPER", "a-pepper-that-exists-only-in-this-process")
os.environ.setdefault("APP_COMMIT", "0f1e2d3")
os.environ["APP_ENV"] = "test"

# ruff: noqa: E402

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.cli import sync_permissions
from app.db import make_sessionmaker, utc_now
from app.deps import invalidate_permission_cache
from app.main import app
from app.security.ratelimit import get_limiter
from support import Clock, api_client

_BACKEND: Final = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def database() -> str:
    """Bring the test database to head and seed the catalogue, once for the whole run.

    `sync-permissions` rather than a fixture of its own: the roles a test signs in as are the
    roles the deploy creates, produced by the same code. A hand-written INSERT here would let the
    permission matrix pass against a catalogue the application no longer agrees with.
    """
    _refuse_without_a_database()
    _upgrade_to_head()
    _seed()
    return TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def _process_state() -> Iterator[None]:
    """Reset what lives in the process rather than in the database.

    The rate limiter's counters and the role→permission snapshot are module-level and survive a
    rollback, so without this a test that spent a login allowance would hand the next test a
    smaller one, and a test that edited a role would be answered from the previous test's cache.
    """
    get_limiter().clear()
    invalidate_permission_cache()
    yield
    get_limiter().clear()
    invalidate_permission_cache()


@pytest.fixture
async def connection() -> AsyncIterator[AsyncConnection]:
    """One connection holding one transaction, rolled back when the test ends.

    NullPool because each test builds its own engine: pytest-asyncio gives every test a new event
    loop, and a pooled connection opened under a loop that has since closed is not a connection
    any more.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as open_connection:
            transaction = await open_connection.begin()
            try:
                yield open_connection
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """The test's own session on the test's connection.

    It shares the connection with the application's sessions, so a commit here is a SAVEPOINT
    release the request can see, and a commit there is one this can see. Both die with the
    rollback above.
    """
    async with make_sessionmaker(connection)() as open_session:
        yield open_session


@pytest.fixture
def clock() -> Clock:
    """The clock the application reads, starting at the real one."""
    return Clock(utc_now())


@pytest.fixture
async def client(connection: AsyncConnection, clock: Clock) -> AsyncIterator[AsyncClient]:
    """A client for the application the systemd unit runs — the module-level `app` itself.

    Not a fresh `create_app()`: the route-declaration test and the permission matrix walk this
    object, and a suite that exercised a copy could pass while the served application had a route
    nobody had decided about.
    """
    async with api_client(app, connection=connection, clock=clock) as opened:
        yield opened


def _refuse_without_a_database() -> None:
    """Stop the run, with the URL that failed, rather than skipping the suite.

    Skipping would be worse than failing: an authentication suite that quietly reports "no tests
    ran" on a machine with no Postgres is a green build that proved nothing.
    """
    engine = create_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        # The URL with its password masked: this message goes to a terminal and to CI logs.
        safe = make_url(TEST_DATABASE_URL).render_as_string(hide_password=True)
        pytest.exit(
            f"No database at {safe} ({type(exc).__name__}). "
            "Start Postgres, or point TEST_DATABASE_URL somewhere that answers.",
            returncode=1,
        )
    finally:
        engine.dispose()


def _upgrade_to_head() -> None:
    """Run the real migrations, through alembic, against the test database.

    Built without an ini file so that alembic's own `fileConfig` never runs: it would reconfigure
    the standard library's logging, and everything this application logs goes through one handler
    that `configure_logging` installs.
    """
    config = Config()
    config.set_main_option("script_location", str(_BACKEND / "alembic"))
    command.upgrade(config, "head")


def _seed() -> None:
    """Empty the tables that hold test data, then write the catalogue and the system roles.

    The delete is for what an interrupted earlier run could have left committed. Everything a test
    writes is rolled back, so on a clean database these two statements touch nothing.
    """

    async def work() -> None:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("DELETE FROM admin.refresh_tokens"))
                await connection.execute(text("DELETE FROM admin.users"))
            async with make_sessionmaker(engine)() as session:
                await sync_permissions(session)
        finally:
            await engine.dispose()

    # Its own loop, and nothing is kept from it: the engine above is disposed before it closes, so
    # no connection outlives the loop that opened it.
    asyncio.run(work())
