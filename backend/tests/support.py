"""What the tests say instead of repeating themselves.

Nothing here asserts anything about behaviour. It is the vocabulary the suite is written in: the
paths, one account factory, a bearer header, and the three ways a test needs to look at a
`Set-Cookie` — because a refresh cookie is checked for its attributes, for its value, and for
having been deleted, and parsing that header by hand in twenty places is how one of those twenty
ends up asserting nothing.

The client this module builds is the one the whole suite uses: an ASGI transport with no port and
no server, a session bound to the connection the test will roll back, and a clock the test moves
by hand.
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.cookies import Morsel, SimpleCookie
from typing import Any, Final

import httpx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.db import get_now, get_session, make_sessionmaker
from app.models import RefreshToken, Role, User, normalize_email
from app.security.passwords import hash_password
from app.security.refresh import COOKIE_NAME, hash_refresh_token
from app.security.tokens import ACCESS_TOKEN_TTL, TokenType, encode_access_token

# https, not http: the refresh cookie is Secure — the production setting — and http.cookiejar,
# which httpx uses, refuses to send a Secure cookie over a plaintext URL. Testing against http
# would mean setting COOKIE_SECURE=false, and then nothing in the suite would ever see the
# attribute that keeps the token off a plaintext hop.
BASE_URL: Final = "https://testserver"

HEALTH: Final = "/api/health"
LOGIN: Final = "/api/auth/login"
REFRESH: Final = "/api/auth/refresh"
LOGOUT: Final = "/api/auth/logout"
ME: Final = "/api/auth/me"
USERS: Final = "/api/users"

PASSWORD: Final = "correct-horse-battery-staple"

# argon2 is deliberately slow — about twenty-five milliseconds per hash, which is the point of it.
# Every account that does not care what its password hashes to gets this one, computed once, so
# that a suite creating fifty users spends twenty-five milliseconds on hashing rather than a
# second and a quarter. An account that needs a hash of its own asks for a different password.
_SHARED_HASH: Final = hash_password(PASSWORD)


class Clock:
    """The instant every route in the application believes it is.

    Bound to the `get_now` dependency, so a test that needs a token to have expired moves the
    clock instead of sleeping or monkeypatching `datetime`. Both alternatives are worse than they
    look: sleeping thirty seconds for the refresh grace window would make the suite unusable, and
    a patched `datetime` module is a global that leaks into whatever runs next.
    """

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    @property
    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        self._now += delta
        return self._now


@dataclass(frozen=True, slots=True)
class Account:
    """An account a test created, and the password it can sign in with."""

    id: uuid.UUID
    email: str
    password: str
    role_code: str


async def role_id_for(session: AsyncSession, code: str) -> uuid.UUID:
    """The id of a seeded role. Fails loudly rather than returning None: the roles are fixtures."""
    found = (
        await session.execute(select(Role.id).where(Role.code == code, Role.world_id.is_(None)))
    ).scalar_one_or_none()
    assert found is not None, f"no role {code!r} — the session-scoped seed did not run"
    return found


async def create_account(
    session: AsyncSession,
    *,
    email: str,
    role_code: str = "admin",
    password: str = PASSWORD,
    is_active: bool = True,
) -> Account:
    """Insert one user and commit, so the request under test can see it.

    The commit ends a SAVEPOINT inside the transaction the test will roll back, which is what
    makes the row visible to the application's own session on the same connection without
    surviving the test.
    """
    user = User(
        email=normalize_email(email),
        password_hash=_SHARED_HASH if password == PASSWORD else hash_password(password),
        role_id=await role_id_for(session, role_code),
        is_active=is_active,
    )
    session.add(user)
    await session.commit()
    return Account(id=user.id, email=user.email, password=password, role_code=role_code)


def bearer(
    account: Account | uuid.UUID,
    *,
    now: datetime,
    typ: TokenType = "access",
    world_id: uuid.UUID | None = None,
    ttl: timedelta = ACCESS_TOKEN_TTL,
) -> dict[str, str]:
    """An Authorization header carrying a token this service would have minted itself."""
    subject = account if isinstance(account, uuid.UUID) else account.id
    issued = encode_access_token(user_id=subject, now=now, typ=typ, world_id=world_id, ttl=ttl)
    return {"Authorization": f"Bearer {issued.token}"}


def envelope(response: httpx.Response) -> dict[str, Any]:
    """The error object out of a failure, asserting on the way that there was one."""
    body = response.json()
    assert set(body) == {"error"}, f"not an error envelope: {body}"
    error = body["error"]
    assert set(error) == {"code", "message", "field"}, f"wrong envelope shape: {error}"
    return dict(error)


def refresh_morsel(response: httpx.Response) -> Morsel[str]:
    """The `sa_refresh` cookie this response set, with its attributes."""
    jar: SimpleCookie = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        jar.load(header)
    morsel = jar.get(COOKIE_NAME)
    assert morsel is not None, "the response set no refresh cookie"
    return morsel


def refresh_value(response: httpx.Response) -> str:
    """The plaintext refresh token this response handed out."""
    value = refresh_morsel(response).value
    assert value, "the response cleared the refresh cookie instead of setting one"
    return value


def cookie_was_cleared(response: httpx.Response) -> bool:
    """Whether this response told the browser to delete the refresh cookie.

    An empty value alone is not deletion — Max-Age=0 is what makes the browser drop it rather than
    keep an empty one until the tab closes.
    """
    morsel = refresh_morsel(response)
    return morsel.value == "" and morsel["max-age"] == "0"


async def login(
    client: AsyncClient, account: Account, *, password: str | None = None
) -> httpx.Response:
    """Sign in as an account, optionally with a password that is not its own."""
    sent = account.password if password is None else password
    return await client.post(LOGIN, json={"email": account.email, "password": sent})


async def refresh_with(
    client: AsyncClient, value: str | None, *, headers: dict[str, str] | None = None
) -> httpx.Response:
    """Present exactly one refresh token — or none — to the refresh endpoint.

    The cookie jar is emptied first and the header written by hand, because a test about which
    token was presented must not depend on what the jar happened to have kept from the last
    response.
    """
    client.cookies.clear()
    sent = dict(headers or {})
    if value is not None:
        sent["Cookie"] = f"{COOKIE_NAME}={value}"
    return await client.post(REFRESH, headers=sent)


async def logout_with(client: AsyncClient, value: str | None) -> httpx.Response:
    """Log out presenting exactly one refresh token, or none."""
    client.cookies.clear()
    headers = {"Cookie": f"{COOKIE_NAME}={value}"} if value is not None else {}
    return await client.post(LOGOUT, headers=headers)


async def refresh_rows(session: AsyncSession, user_id: uuid.UUID) -> Sequence[Row[Any]]:
    """Every refresh-token row a user owns, oldest first.

    Columns rather than ORM objects on purpose: the application has been writing to this table
    through a session of its own, and an ORM object the test session loaded earlier would answer
    from its identity map with whatever it knew before the request.
    """
    result = await session.execute(
        select(
            RefreshToken.token_hash,
            RefreshToken.family_id,
            RefreshToken.issued_at,
            RefreshToken.expires_at,
            RefreshToken.family_expires_at,
            RefreshToken.used_at,
            RefreshToken.revoked_at,
        )
        .where(RefreshToken.user_id == user_id)
        .order_by(RefreshToken.issued_at, RefreshToken.token_hash)
    )
    return result.all()


async def token_row(session: AsyncSession, value: str) -> Row[Any]:
    """The row behind one plaintext refresh token."""
    result = await session.execute(
        select(
            RefreshToken.token_hash,
            RefreshToken.family_id,
            RefreshToken.expires_at,
            RefreshToken.family_expires_at,
            RefreshToken.used_at,
            RefreshToken.revoked_at,
        ).where(RefreshToken.token_hash == hash_refresh_token(value))
    )
    row = result.one_or_none()
    assert row is not None, "no refresh_tokens row for that value"
    return row


@asynccontextmanager
async def api_client(
    application: FastAPI,
    *,
    connection: AsyncConnection,
    clock: Clock,
    raise_app_exceptions: bool = True,
) -> AsyncIterator[AsyncClient]:
    """Drive an application in-process, over the test's own database connection.

    Every request gets a fresh session bound to `connection` — the one holding the transaction the
    test rolls back — so a route may commit and the test still leaves nothing behind.

    `raise_app_exceptions=False` is what the forced-500 test needs: ServerErrorMiddleware re-raises
    after handing the exception to its handler, so with the default the exception reaches the test
    instead of the envelope the client would have received.
    """

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with make_sessionmaker(connection)() as request_session:
            yield request_session

    application.dependency_overrides[get_session] = session_override
    application.dependency_overrides[get_now] = lambda: clock
    transport = ASGITransport(app=application, raise_app_exceptions=raise_app_exceptions)
    try:
        async with AsyncClient(transport=transport, base_url=BASE_URL) as opened:
            yield opened
    finally:
        application.dependency_overrides.clear()
