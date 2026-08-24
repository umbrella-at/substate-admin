"""The application object: what is mounted, what is not, and what every response carries.

Three things are checked here because each of them is invisible until it is wrong. The /api prefix
belongs to this application rather than to Caddy, and the refresh cookie's Path is written against
it. The interactive docs are gated on APP_ENV, and an unset variable must not be what publishes a
map of an admin panel. And every response carries a request id, which is the only thing connecting
a failure somebody saw to a line in the journal.

Nothing here touches Postgres, deliberately: these are properties of the process, and asking the
database about them would only make the tests slower and their failures harder to read.
"""

import os
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Final

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app import __version__
from app.config import get_settings
from app.db import dispose_engine, get_engine
from app.logging import REQUEST_ID_HEADER
from app.main import create_app, lifespan
from support import LOGIN, Clock, api_client

_DOCS: Final = "/api/docs"
_SCHEMA: Final = "/api/openapi.json"
_MISSING: Final = "/api/nothing-is-here"

# Enough to be routed and rejected by validation, which is all these tests need from it.
_EMPTY_LOGIN: Final[dict[str, str]] = {}


@pytest.fixture
def production() -> Iterator[None]:
    """The environment a deployed host actually has."""
    original = os.environ["APP_ENV"]
    os.environ["APP_ENV"] = "production"
    get_settings.cache_clear()
    try:
        yield
    finally:
        os.environ["APP_ENV"] = original
        get_settings.cache_clear()


@pytest.fixture
async def production_client(
    production: None, connection: AsyncConnection, clock: Clock
) -> AsyncIterator[AsyncClient]:
    """A second application, built while APP_ENV says production."""
    async with api_client(create_app(), connection=connection, clock=clock) as opened:
        yield opened


async def test_every_route_is_mounted_under_the_api_prefix(client: AsyncClient) -> None:
    """Caddy proxies /api/* with `handle`, not `handle_path`, so the prefix survives the hop and
    this application owns it."""
    assert (await client.post(LOGIN, json=_EMPTY_LOGIN)).status_code == 422
    assert (await client.post("/auth/login", json=_EMPTY_LOGIN)).status_code == 404


async def test_the_docs_are_published_outside_production(client: AsyncClient) -> None:
    assert (await client.get(_DOCS)).status_code == 200

    schema = await client.get(_SCHEMA)

    assert schema.status_code == 200
    assert LOGIN in schema.json()["paths"]


async def test_the_docs_are_absent_in_production(production_client: AsyncClient) -> None:
    """An interactive console enumerating every route of an admin panel is a map that helps
    nobody who is supposed to be here."""
    assert (await production_client.get(_DOCS)).status_code == 404
    assert (await production_client.get(_SCHEMA)).status_code == 404
    # The same application in every other respect.
    assert (await production_client.post(LOGIN, json=_EMPTY_LOGIN)).status_code == 422


async def test_the_published_schema_describes_failures_as_the_envelope(
    client: AsyncClient,
) -> None:
    """A client generated from a schema promising `{"detail": ...}` would be wrong about every
    failure it will ever see."""
    schema = (await client.get(_SCHEMA)).json()

    unauthorised = schema["paths"][LOGIN]["post"]["responses"]["401"]
    reference = unauthorised["content"]["application/json"]["schema"]["$ref"]

    assert reference.endswith("/ErrorEnvelope")


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    response = await client.get(_SCHEMA)

    assert uuid.UUID(response.headers[REQUEST_ID_HEADER])


async def test_a_failure_carries_a_request_id_too(client: AsyncClient) -> None:
    response = await client.get(_MISSING)

    assert response.status_code == 404
    assert uuid.UUID(response.headers[REQUEST_ID_HEADER])


async def test_an_inbound_request_id_is_carried_through(client: AsyncClient) -> None:
    """One id across the proxy, this service and the journal is what makes a report traceable."""
    response = await client.get(_MISSING, headers={REQUEST_ID_HEADER: "abc-123_XYZ.7"})

    assert response.headers[REQUEST_ID_HEADER] == "abc-123_XYZ.7"


@pytest.mark.parametrize("forged", ["with a space", "x" * 65, "", "one;two"])
async def test_an_unusable_inbound_request_id_is_replaced(client: AsyncClient, forged: str) -> None:
    """The value is echoed in a header and written into the journal, so it is checked before it is
    trusted: what a client sends must not be able to forge a log line."""
    response = await client.get(_MISSING, headers={REQUEST_ID_HEADER: forged})

    echoed = response.headers[REQUEST_ID_HEADER]

    assert echoed != forged
    assert uuid.UUID(echoed)


def test_the_service_reports_one_version() -> None:
    """`app.__version__` is the only version string: the package's, the schema's, and health's."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    assert create_app().version == __version__


async def test_the_lifespan_connects_to_nothing_and_hands_the_pool_back() -> None:
    """The served life of the process, bracketed.

    The database URL below names a port nothing listens on, so anything that tried to connect
    during startup would fail here. That is the design: the unit orders itself after
    postgresql.service, which on Debian returns before the cluster accepts connections, and a
    startup that required the database would turn a slow Postgres into a restart loop. It costs
    one 503 from /api/health instead.

    Shutdown is the other half. The pool is handed back rather than left for Postgres to time out
    backends nothing is ever going to speak to again — which is visible as the engine being built
    afresh on the next request.
    """
    original = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = "postgresql+psycopg://nobody@127.0.0.1:1/nowhere"
    get_settings.cache_clear()
    try:
        before = get_engine()
        async with lifespan(create_app()):
            pass
        assert get_engine() is not before
    finally:
        os.environ["DATABASE_URL"] = original
        get_settings.cache_clear()
        await dispose_engine()
