"""The journal: one JSON object per line, and the things that must never be in one.

`journalctl -u substate-admin-api -o cat | jq` is the whole log tooling this service has, so a
line that is not parseable JSON is a line nobody reads. What is absent is as fixed as what is
present: no Authorization header, no cookie in either direction, no password, no refresh token,
and no raw client address. Addresses appear only as `ip_hash` — the rate limiter needs to count
them, the journal does not need to keep them.

What is read below is the service's own handler with its stream swapped for one this module can
see. Reading pytest's captured output instead would test whatever pytest last did to `sys.stdout`
rather than what the formatter wrote.
"""

import io
import json
import logging
from collections.abc import Iterator
from typing import Any, Final

import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Receive, Scope, Send

from app.logging import RequestContextMiddleware, configure_logging, get_logger, get_request_id
from support import LOGIN, PASSWORD, create_account, login, refresh_value, refresh_with

_ATTACKER: Final = "203.0.113.44"

# Answered without touching Postgres, so nothing in this module builds the process-wide engine.
_SCHEMA: Final = "/api/openapi.json"

_HEX: Final = frozenset("0123456789abcdef")


class Journal:
    """What the service has written, as the journal would hold it."""

    def __init__(self, stream: io.StringIO) -> None:
        self._stream = stream

    @property
    def text(self) -> str:
        return self._stream.getvalue()

    def lines(self) -> list[dict[str, Any]]:
        """Every line, parsed. A line that is not one JSON object fails here, which is the point."""
        written = [line for line in self.text.splitlines() if line.strip()]
        assert written, "nothing was logged"
        return [json.loads(line) for line in written]

    def event(self, name: str) -> dict[str, Any]:
        """The single line reporting one event."""
        found = [line for line in self.lines() if line.get("event") == name]
        assert len(found) == 1, f"expected one {name!r} line, found {len(found)}"
        return found[0]


def _json_handler() -> logging.StreamHandler[Any]:
    """The one handler this application installs, found by its formatter rather than its position:
    pytest attaches handlers of its own to the same logger."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and isinstance(
            handler.formatter, structlog.stdlib.ProcessorFormatter
        ):
            return handler
    raise AssertionError("configure_logging installed no JSON handler")


@pytest.fixture
def journal() -> Iterator[Journal]:
    """Divert the handler `configure_logging` installs, and put its stream back afterwards."""
    configure_logging()
    handler = _json_handler()
    original = handler.stream
    stream = io.StringIO()
    handler.setStream(stream)
    try:
        yield Journal(stream)
    finally:
        handler.setStream(original)


def test_a_line_is_one_json_object_with_the_fields_the_journal_is_read_by(
    journal: Journal,
) -> None:
    get_logger("probe").info("something_happened", detail="worth keeping")

    line = journal.event("something_happened")

    assert line["level"] == "info"
    assert line["logger"] == "probe"
    assert line["detail"] == "worth keeping"
    assert line["ts"].endswith("Z")


@pytest.mark.parametrize(
    "field",
    ["authorization", "cookie", "set-cookie", "password", "token", "refresh_token", "ip"],
)
def test_a_forbidden_field_is_replaced_rather_than_dropped(journal: Journal, field: str) -> None:
    """A backstop, not the rule. The rule is that nothing logs these; this is what happens when a
    later keyword argument is named `password` anyway — and the mistake stays visible in the
    journal instead of becoming silently invisible."""
    get_logger("probe").warning("careless", **{field: "hunter2"})

    line = journal.event("careless")

    assert line[field] == "[redacted]"
    assert "hunter2" not in journal.text


async def test_a_request_is_one_line_naming_what_it_was_and_how_long_it_took(
    client: AsyncClient, journal: Journal
) -> None:
    await client.get(_SCHEMA)

    line = journal.event("request")

    assert line["method"] == "GET"
    assert line["path"] == _SCHEMA
    assert line["status"] == 200
    assert isinstance(line["duration_ms"], float)
    assert line["request_id"]


async def test_a_failure_is_logged_at_a_level_that_stands_out(
    client: AsyncClient, journal: Journal
) -> None:
    await client.get("/api/nothing-is-here")

    line = journal.event("request")

    assert line["status"] == 404
    assert line["level"] == "warning"


async def test_the_bootstrap_refusal_is_not_shouted(client: AsyncClient, journal: Journal) -> None:
    """A browser holding no cookie asking to refresh is the first request of every visit, and its
    401 is the expected answer. If that is a warning, the most common request on the only public
    page is the loudest line in the journal and the level stops meaning anything. The things worth
    hearing — a failed password, a burst — write their own warnings with a reason attached."""
    await client.post("/api/auth/refresh")

    line = journal.event("request")

    assert line["status"] == 401
    assert line["level"] == "info"


async def test_a_query_string_is_not_kept(client: AsyncClient, journal: Journal) -> None:
    """The path, not the full URL: a query string is client-supplied text, and nothing this API
    reads from one is worth keeping in the journal."""
    await client.get(f"{_SCHEMA}?secret=hunter2")

    assert journal.event("request")["path"] == _SCHEMA


async def test_who_was_asking_is_attached_to_every_line_of_their_request(
    client: AsyncClient, session: AsyncSession, journal: Journal
) -> None:
    """The middleware runs before anyone has been identified, so the dependency that resolves the
    user and the rate limiter bind what they learn onto the rest of the request."""
    account = await create_account(session, email="logged@example.com")

    await login(client, account)

    line = journal.event("request")
    assert line["user_id"] == str(account.id)
    assert len(line["ip_hash"]) == 64
    assert set(line["ip_hash"]) <= _HEX


async def test_the_journal_never_holds_a_credential(
    client: AsyncClient, session: AsyncSession, journal: Journal
) -> None:
    """A whole session, start to finish, and then a search for every secret that passed through
    it — the client's address included."""
    account = await create_account(session, email="private@example.com")

    presented = refresh_value(await login(client, account))
    rotated = await refresh_with(client, presented, headers={"X-Forwarded-For": _ATTACKER})
    successor = refresh_value(rotated)
    await client.post(LOGIN, json={"email": account.email, "password": "the-wrong-one"})

    for secret in (presented, successor, PASSWORD, "the-wrong-one", _ATTACKER, "sa_refresh"):
        assert secret not in journal.text
    # The reason a login failed is in here, where it is useful and unreachable.
    assert "bad_password" in journal.text


async def test_the_reason_a_login_failed_is_written_down_and_not_sent_back(
    client: AsyncClient, session: AsyncSession, journal: Journal
) -> None:
    await create_account(session, email="dormant@example.com", is_active=False)

    response = await client.post(LOGIN, json={"email": "dormant@example.com", "password": PASSWORD})

    assert journal.event("login_failed")["reason"] == "disabled"
    assert "disabled" not in response.text.lower()


def test_the_request_id_is_readable_without_a_request() -> None:
    """An exception handler running above the middleware still has to be able to name it."""
    assert get_request_id() is None


async def test_a_scope_that_is_not_http_passes_straight_through() -> None:
    """The middleware answers requests. A lifespan message is not one, and wrapping it would mean
    minting a request id for the process's own startup."""
    seen: list[Scope] = []

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope)

    scope: Scope = {"type": "lifespan"}
    await RequestContextMiddleware(application)(scope, _never_receives, _never_sends)

    assert seen == [scope]
    assert "substate.request_id" not in scope


async def _never_receives() -> Any:
    raise AssertionError("nothing should be received")


async def _never_sends(message: Any) -> None:
    raise AssertionError("nothing should be sent")
