"""The error envelope, including on the failures nobody raises on purpose.

The frontend switches on `code`, shows `message`, and attaches the message to the input named by
`field`. That contract holds only if it holds everywhere, so what is tested here is the four
replies FastAPI would otherwise write itself: a 404 from the router, a 405 from a mistyped
method, a 422 from pydantic, and a 500 from a bug. Each of FastAPI's own answers is `{"detail":
...}` in a different shape, and a client generated from them would be wrong about every failure
it ever sees.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any, Final

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.deps import Public
from app.errors import field_from_loc
from app.main import create_app
from support import LOGIN, USERS, Clock, api_client, bearer, create_account, envelope

_GENERIC_500: Final = (
    "The service failed to handle this request. Try again; the request id in the "
    "response headers identifies it in the log."
)
"""Written out rather than imported from the catalogue it is asserting.

A test that reads its expectation from the code under test passes on any sentence that code
happens to hold, including the one the rules forbid. This one is here so that changing the
sentence is a decision somebody makes twice.
"""


@pytest.fixture
async def broken_client(connection: AsyncConnection, clock: Clock) -> AsyncIterator[AsyncClient]:
    """A copy of the application with one route that raises, and a transport that does not re-raise.

    Starlette's ServerErrorMiddleware hands the exception to the registered handler and then
    re-raises it, so with the default transport the exception reaches the test rather than the
    envelope the client would have been sent.
    """
    application: FastAPI = create_app()

    @application.get("/api/boom", dependencies=[Public()])
    async def boom() -> None:
        raise RuntimeError("the connection string is postgres://admin:hunter2@db/substate")

    async with api_client(
        application, connection=connection, clock=clock, raise_app_exceptions=False
    ) as opened:
        yield opened


async def test_a_path_that_matches_nothing(client: AsyncClient) -> None:
    response = await client.get("/api/nothing-is-here")

    assert response.status_code == 404
    assert envelope(response) == {
        "code": "NOT_FOUND",
        # The catalogue's sentence, not Starlette's reason phrase: "Not Found" is not something a
        # person should read in a toast.
        "message": "The requested resource does not exist.",
        "field": None,
    }


async def test_a_method_the_route_does_not_answer(client: AsyncClient) -> None:
    response = await client.post("/api/health")

    assert response.status_code == 405
    assert envelope(response)["code"] == "METHOD_NOT_ALLOWED"
    # The protocol's own answer survives the reshaping of the body.
    assert "GET" in response.headers["Allow"]


async def test_a_body_that_is_not_an_object_names_no_field(client: AsyncClient) -> None:
    response = await client.post(LOGIN, json="just a string")

    assert response.status_code == 422
    assert envelope(response) == {
        "code": "VALIDATION_ERROR",
        "message": "The submitted data is invalid.",
        # The failure is about the payload as a whole, and `null` rather than a missing key: a key
        # that comes and goes is a key every consumer has to test for.
        "field": None,
    }


async def test_a_key_this_api_does_not_accept_is_named_back(client: AsyncClient) -> None:
    response = await client.post(
        LOGIN, json={"email": "a@example.com", "password": "x" * 12, "rememberMe": True}
    )

    assert response.status_code == 422
    assert envelope(response)["field"] == "rememberMe"


async def test_a_query_parameter_is_named_in_the_case_the_form_uses(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """`page_size` in Python, `pageSize` on the wire, and `pageSize` in the error: the name has to
    map straight onto the input the person is looking at."""
    account = await create_account(session, email="pager@example.com", role_code="admin")

    response = await client.get(f"{USERS}?pageSize=0", headers=bearer(account, now=clock.now))

    assert response.status_code == 422
    assert envelope(response)["field"] == "pageSize"


async def test_a_bug_answers_with_the_envelope_and_keeps_the_traceback_out_of_it(
    broken_client: AsyncClient,
) -> None:
    response = await broken_client.get("/api/boom")

    assert response.status_code == 500
    assert envelope(response) == {
        "code": "INTERNAL_ERROR",
        "message": _GENERIC_500,
        "field": None,
    }
    # An exception's message is as likely to be a DSN as it is to be useful.
    assert "Traceback" not in response.text
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text
    # And the id that makes the failure findable in the journal, written by the handler because
    # the middleware that stamps it never saw a response to stamp.
    assert response.headers["X-Request-Id"]


@pytest.mark.parametrize(
    ("loc", "expected"),
    [
        (("body", "email"), "email"),
        (("body", "page_size"), "pageSize"),
        (("query", "pageSize"), "pageSize"),
        (("path", "user_id"), "userId"),
        (("body", "filters", 0, "op"), "filters.0.op"),
        (("body",), None),
        ((), None),
        # Not a location prefix, so nothing is stripped: a bare name stays a bare name.
        (("email",), "email"),
    ],
)
def test_a_pydantic_location_becomes_a_form_field(loc: Sequence[Any], expected: str | None) -> None:
    assert field_from_loc(loc) == expected
