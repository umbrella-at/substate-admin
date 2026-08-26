"""GET /api/health.

The only endpoint whose value depends entirely on it not lying. A probe that answers 200 because
the process is up would let the deploy's smoke check pass over a release whose database is
unreachable, so both tests here are about the database rather than about the route: one with a
real Postgres answering, one with the engine pointed somewhere nothing is listening.

The second is not a mock. `check_database` is asked to connect to a closed port, which is the
failure it actually swallows in production.
"""

import os
from collections.abc import AsyncIterator
from typing import Final

import pytest
from httpx import AsyncClient

from app import __version__
from app.config import get_settings
from app.db import dispose_engine
from support import HEALTH

# Port 1 on the loopback interface: nothing listens there, and the refusal comes back immediately
# rather than after a connect timeout.
_UNREACHABLE: Final = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nowhere"


@pytest.fixture(autouse=True)
async def _forget_the_engine() -> AsyncIterator[None]:
    """Drop the process-wide engine around every test in this module.

    `check_database` is the one code path that builds it, and its pooled connections belong to the
    event loop of the test that opened them. Left in place, they would be handed to the next test
    under a loop that has already closed.
    """
    await dispose_engine()
    yield
    await dispose_engine()


async def test_health_reports_the_release_and_a_database_that_answers(client: AsyncClient) -> None:
    response = await client.get(HEALTH)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        # The deploy writes this, and the smoke check compares it against the commit it just
        # pushed. A health endpoint that reported only a status could be answered by the SPA
        # fallback with a cheerful 200 and nothing behind it.
        "commit": os.environ["APP_COMMIT"],
        "db": True,
        # Beside `db`, not folded into `status`. A world that failed to seed is an empty shop
        # window while the panel keeps serving, and a smoke check that read it as an outage would
        # roll a good deploy back over it.
        "world": {"seeded": False, "subscribers": 0, "events": 0},
    }


async def test_health_reports_503_when_the_database_does_not_answer(client: AsyncClient) -> None:
    original = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = _UNREACHABLE
    get_settings.cache_clear()
    await dispose_engine()
    try:
        response = await client.get(HEALTH)
    finally:
        os.environ["DATABASE_URL"] = original
        get_settings.cache_clear()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] is False

    # Still the same fields, not the error envelope: a deploy comparing commits has to be able to
    # tell "the new release is up and its database is down" from "the old release is still there".
    assert set(body) == {"status", "version", "commit", "db", "world"}

    # The DSN carries the password, and a driver's connection error quotes the DSN it tried.
    assert "nothing" not in response.text
    assert "127.0.0.1" not in response.text
