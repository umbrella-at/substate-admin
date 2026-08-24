"""The engine, the session dependency, and the clock.

The lazy engine is the one property here that is a constraint rather than a preference: alembic,
the CLI and a bare test collection all import this package on machines that have no database and
no DATABASE_URL, and an engine built at import would stop all three.

The session dependency is exercised for real because the rest of the suite overrides it. A
dependency nothing ever runs is a dependency that can be wrong for a year.
"""

import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import (
    check_database,
    dispose_engine,
    get_engine,
    get_now,
    get_session,
    get_sessionmaker,
    utc_now,
)


@pytest.fixture(autouse=True)
async def _forget_the_engine() -> AsyncIterator[None]:
    """Nothing in this module may leave a pool bound to an event loop that is about to close."""
    await dispose_engine()
    yield
    await dispose_engine()


def test_importing_the_package_needs_no_configuration_and_no_database() -> None:
    """Run in a process of its own with the three required variables removed. Importing
    `app.models` in the same process the rest of the suite runs in would prove nothing: the
    modules are already imported and the settings are already cached."""
    program = (
        "import os, sys\n"
        "for name in ('DATABASE_URL', 'JWT_SECRET', 'IP_HASH_PEPPER'):\n"
        "    os.environ.pop(name, None)\n"
        "import app.db, app.models, app.permissions, app.cli\n"
        "assert app.db._engine is None\n"
        "print('imported')\n"
    )

    finished = subprocess.run(  # noqa: S603
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parent.parent,
    )

    assert finished.returncode == 0, finished.stderr
    assert "imported" in finished.stdout


async def test_the_engine_is_built_once_and_forgotten_on_shutdown() -> None:
    engine = get_engine()

    assert isinstance(engine, AsyncEngine)
    assert get_engine() is engine
    # Ten connections at most against a Postgres sharing 2 GB with this process.
    assert engine.pool.size() == 5
    assert get_sessionmaker() is get_sessionmaker()

    await dispose_engine()

    assert get_engine() is not engine


async def test_the_session_dependency_yields_a_working_session() -> None:
    """The dependency every route depends on, run against the real engine rather than the
    override the rest of the suite installs."""
    sessions = get_session()

    session = await anext(sessions)
    assert (await session.execute(text("SELECT 1"))).scalar_one() == 1

    # The generator finishing is the `async with` closing the session and handing its connection
    # back, rather than leaving one out for the pool to miss.
    with pytest.raises(StopAsyncIteration):
        await anext(sessions)


async def test_a_failed_statement_does_not_carry_its_parameters() -> None:
    """SQLAlchemy renders bound parameters into the message of any DBAPI error by default, and
    that message is what the 500 handler and the request line both write down. One deadlock or one
    dropped connection during a login would therefore put the operator's address and their argon2
    hash in the journal — twice — after the rest of this service has gone to some trouble to keep
    both out of it."""
    email = "operator@example.com"
    stored = "$argon2id$v=19$m=19456,t=2,p=1$c2FsdHNhbHRzYWx0cw$bm90YXJlYWxoYXNoYXRhbGw"

    async with get_engine().connect() as connection:
        with pytest.raises(SQLAlchemyError) as failure:
            await connection.execute(
                text("SELECT :email, :password_hash FROM admin.no_such_table"),
                {"email": email, "password_hash": stored},
            )

    message = str(failure.value)
    assert email not in message
    assert stored not in message
    # Hidden rather than absent: the line still says a statement had parameters, which is the
    # difference between reading a journal and guessing at one.
    assert "hide_parameters=True" in message


async def test_the_probe_answers_yes_when_postgres_does() -> None:
    assert await check_database() is True


def test_the_clock_is_always_utc_and_always_aware() -> None:
    """Authentication never runs on a shifted clock. A demo world may believe it is any date it
    likes; a token's `exp` is measured against this."""
    now = utc_now()

    assert now.tzinfo is UTC
    assert get_now() is utc_now
