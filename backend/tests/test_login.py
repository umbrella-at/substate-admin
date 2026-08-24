"""POST /api/auth/login.

Two properties are worth more than the happy path here.

The first is that the three ways to fail produce one answer. An unknown address, a wrong password
and a disabled account must be indistinguishable in status, code and sentence, or the only page an
unauthenticated visitor can reach becomes a way to enumerate this panel's operators. The test
below compares the raw bodies rather than the parsed ones: this is about what arrives byte for
byte, and two responses that differ anywhere are not the same answer.

The second is the rate limiter. It is what stands between a public form and an offline guessing
run, and it is state in the process that no rollback restores — which is why the counters are
cleared around every test.
"""

import asyncio
from datetime import timedelta
from typing import Final

import pytest
from argon2 import PasswordHasher, Type
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.db import dispose_engine, get_now
from app.main import app
from app.models import User
from app.routers import auth
from app.security import passwords
from app.security.passwords import verify_password
from app.security.ratelimit import client_ip
from app.security.refresh import COOKIE_PATH, FAMILY_TTL, TOKEN_TTL
from app.security.tokens import ACCESS_TOKEN_TTL, AccessTokenExpired, decode_access_token
from support import (
    BASE_URL,
    LOGIN,
    PASSWORD,
    Clock,
    create_account,
    envelope,
    login,
    refresh_morsel,
    refresh_rows,
)

_WRONG: Final = "not-the-password-at-all"

# The parameters this application used to hash with, as far as any test is concerned: valid
# argon2id, and not what `app.security.passwords` produces today.
_OUTDATED: Final = PasswordHasher(
    time_cost=1, memory_cost=8, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
)


async def test_login_returns_an_access_token_for_the_account(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    account = await create_account(session, email="ada@example.com")

    response = await login(client, account)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"accessToken", "expiresIn"}
    # Fifteen minutes, spelled out in seconds: written as `ACCESS_TOKEN_TTL` this assertion would
    # agree with whatever lifetime that constant were ever given.
    assert body["expiresIn"] == 900

    claims = decode_access_token(body["accessToken"], now=clock)
    assert claims.subject == account.id
    assert claims.typ == "access"
    assert claims.world_id is None


async def test_login_starts_one_family_capped_at_ninety_days(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    account = await create_account(session, email="grace@example.com")

    await login(client, account)

    rows = await refresh_rows(session, account.id)
    assert len(rows) == 1
    assert rows[0].used_at is None
    assert rows[0].revoked_at is None
    assert rows[0].family_expires_at == clock.now + FAMILY_TTL
    assert rows[0].expires_at == clock.now + TOKEN_TTL


async def test_login_records_the_moment_it_happened(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    account = await create_account(session, email="alan@example.com")
    stmt = select(User.last_login_at).where(User.id == account.id)
    assert (await session.execute(stmt)).scalar_one() is None

    await login(client, account)

    assert (await session.execute(stmt)).scalar_one() == clock.now


async def test_the_refresh_cookie_is_host_only_and_scoped_to_the_auth_routes(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await create_account(session, email="cookie@example.com")

    morsel = refresh_morsel(await login(client, account))

    assert morsel.value
    assert morsel["httponly"]
    assert morsel["secure"]
    assert morsel["samesite"].lower() == "lax"
    # Not "/": Path=/ is what the __Host- prefix would require, and it would attach the refresh
    # token to every single request the panel makes rather than to the three that exchange it.
    assert morsel["path"] == COOKIE_PATH
    # No Domain, so the cookie is host-only and no subdomain ever sees it.
    assert morsel["domain"] == ""


async def test_the_address_is_normalised_before_it_is_looked_up(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A stored address is lowercased, so the form has to fold what it was given the same way."""
    await create_account(session, email="Mixed.Case@Example.COM")

    response = await client.post(
        LOGIN, json={"email": "  MIXED.case@example.com  ", "password": PASSWORD}
    )

    assert response.status_code == 200


async def test_the_three_login_failures_are_one_answer(
    client: AsyncClient, session: AsyncSession
) -> None:
    await create_account(session, email="present@example.com")
    await create_account(session, email="disabled@example.com", is_active=False)

    answers = [
        await client.post(LOGIN, json={"email": "absent@example.com", "password": PASSWORD}),
        await client.post(LOGIN, json={"email": "present@example.com", "password": _WRONG}),
        await client.post(LOGIN, json={"email": "disabled@example.com", "password": PASSWORD}),
    ]

    assert {answer.status_code for answer in answers} == {401}
    assert len({answer.text for answer in answers}) == 1
    assert envelope(answers[0]) == {
        "code": "INVALID_CREDENTIALS",
        "message": "Email or password is incorrect.",
        "field": None,
    }
    for answer in answers:
        assert "set-cookie" not in answer.headers
        lowered = answer.text.lower()
        for leak in ("disabled", "inactive", "no such", "not found", "unknown"):
            assert leak not in lowered


class _CountingHasher:
    """The module's hasher, wrapped so a test can count the argon2 operations a login spends.

    Counted rather than timed: the operations are what the stopwatch is measuring, and a test that
    measured milliseconds would fail on a busy machine instead of on a regression.
    """

    def __init__(self, real: PasswordHasher) -> None:
        self._real = real
        self.operations = 0

    def hash(self, password: str) -> str:
        self.operations += 1
        return self._real.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        self.operations += 1
        return self._real.verify(encoded, password)

    def check_needs_rehash(self, encoded: str) -> bool:
        # Reads the parameters out of the encoded hash. No argon2 work, nothing to count.
        return self._real.check_needs_rehash(encoded)


async def test_a_disabled_account_costs_exactly_what_a_wrong_password_costs(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The three failures answering identically is half of it; the clock is the other half.

    Upgrading a stored hash is a second argon2 operation, and it is spent only when the password
    was right. Computed while the answer is still "correct password" — before `is_active` is
    read — it is spent on the way to a refusal, and the disabled account becomes the slowest of
    the three failures by the width of a whole argon2 hash. Both accounts below carry a hash
    written with parameters this module has moved on from, which is the only state in which the
    upgrade happens at all.
    """
    live = await create_account(session, email="live@example.com", password="a-real-password")
    frozen = await create_account(
        session, email="frozen-and-stale@example.com", password="a-real-password", is_active=False
    )
    for account in (live, frozen):
        await session.execute(
            update(User)
            .where(User.id == account.id)
            .values(password_hash=_OUTDATED.hash(account.password))
        )
    await session.commit()

    counting = _CountingHasher(passwords._hasher)
    monkeypatch.setattr(passwords, "_hasher", counting)

    spent = []
    for account, password in ((live, _WRONG), (frozen, frozen.password)):
        counting.operations = 0
        assert (await login(client, account, password=password)).status_code == 401
        spent.append(counting.operations)

    assert spent[0] == spent[1]


async def test_a_disabled_account_starts_no_session(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await create_account(session, email="frozen@example.com", is_active=False)

    response = await login(client, account)

    assert response.status_code == 401
    assert await refresh_rows(session, account.id) == []


async def test_a_successful_login_upgrades_a_hash_made_with_weaker_parameters(
    client: AsyncClient, session: AsyncSession
) -> None:
    """check_needs_rehash, exercised at the one moment the plaintext exists to act on it."""
    account = await create_account(session, email="legacy@example.com", password="a-real-password")
    stale = _OUTDATED.hash(account.password)
    await session.execute(update(User).where(User.id == account.id).values(password_hash=stale))
    await session.commit()

    response = await login(client, account)

    assert response.status_code == 200
    stored = (
        await session.execute(select(User.password_hash).where(User.id == account.id))
    ).scalar_one()
    assert stored != stale
    # Verified rather than parsed: what matters is that the stored hash still accepts the password
    # and that this module no longer wants to replace it.
    replaced = verify_password(account.password, stored)
    assert replaced.ok
    assert not replaced.outdated


async def test_five_failures_against_one_address_refuse_the_sixth(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await create_account(session, email="target@example.com")

    for _ in range(5):
        assert (await login(client, account, password=_WRONG)).status_code == 401

    # The correct password, and still refused: the counter is what answers, not the credential.
    refused = await login(client, account)

    assert refused.status_code == 429
    assert envelope(refused)["code"] == "RATE_LIMITED"
    assert 0 < int(refused.headers["Retry-After"]) <= 15 * 60


async def test_fifty_simultaneous_attempts_get_one_allowance_between_them(
    clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ceiling of five has to be five whether the attempts arrive one after another or all at
    once, and it is the second case an attacker chooses.

    Reading the counter before the password is checked and recording the failure afterwards leaves
    the lookup and one argon2 verification between the two, and fifty requests in flight together
    all read a counter none of them has written to yet — fifty guesses against an address whose
    allowance is five, and fifty argon2 verifications spent on them.

    Every attempt arrives from an address of its own, so the per-address ceiling of twenty cannot
    be what refuses them. They all name the same account that does not exist, which is the path
    that needs no row and so no database write to race over.

    Driven against the application's own session dependency rather than the suite's shared
    connection: these requests really are concurrent, and one connection cannot serve two of them
    at the same time.
    """
    verifications = 0

    def counted(password: str) -> None:
        nonlocal verifications
        verifications += 1

    monkeypatch.setattr(auth, "verify_dummy_password", counted)

    app.dependency_overrides[get_now] = lambda: clock
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as burst:
            answers = await asyncio.gather(
                *(
                    burst.post(
                        LOGIN,
                        json={"email": "swarm@example.com", "password": PASSWORD},
                        headers={"X-Forwarded-For": f"203.0.113.{index}"},
                    )
                    for index in range(50)
                )
            )
    finally:
        app.dependency_overrides.clear()
        # Nothing may leave a pool bound to an event loop that is about to close.
        await dispose_engine()

    assert sorted(answer.status_code for answer in answers) == [401] * 5 + [429] * 45
    assert verifications == 5
    for answer in answers:
        if answer.status_code == 429:
            assert int(answer.headers["Retry-After"]) > 0


async def test_the_address_counter_does_not_touch_another_address(
    client: AsyncClient, session: AsyncSession
) -> None:
    blocked = await create_account(session, email="blocked@example.com")
    other = await create_account(session, email="other@example.com")

    for _ in range(5):
        await login(client, blocked, password=_WRONG)

    assert (await login(client, blocked)).status_code == 429
    assert (await login(client, other)).status_code == 200


async def test_a_successful_login_clears_the_address_counter(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Four typos and then the right password must not leave someone one mistake from a lockout."""
    account = await create_account(session, email="fumbling@example.com")

    for _ in range(4):
        assert (await login(client, account, password=_WRONG)).status_code == 401
    assert (await login(client, account)).status_code == 200

    for _ in range(4):
        assert (await login(client, account, password=_WRONG)).status_code == 401


async def test_twenty_attempts_from_one_address_refuse_the_twenty_first(
    client: AsyncClient,
) -> None:
    """The counter an attacker spraying a list of addresses actually meets.

    Every attempt below names a different account, so the per-address counter never reaches its
    five and the only thing that can refuse the twenty-first is the per-ip ceiling.
    """
    here = {"X-Forwarded-For": "203.0.113.9"}

    for index in range(20):
        response = await client.post(
            LOGIN, json={"email": f"sprayed{index}@example.com", "password": PASSWORD}, headers=here
        )
        assert response.status_code == 401

    refused = await client.post(
        LOGIN, json={"email": "sprayed20@example.com", "password": PASSWORD}, headers=here
    )
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0

    elsewhere = await client.post(
        LOGIN,
        json={"email": "sprayed20@example.com", "password": PASSWORD},
        headers={"X-Forwarded-For": "198.51.100.4"},
    )
    assert elsewhere.status_code == 401


def test_a_forwarded_header_is_believed_only_from_the_proxy_on_this_machine() -> None:
    """Which address a request is counted against.

    Trusting X-Forwarded-For from any peer would let a client choose its own rate-limit bucket by
    writing a new address into the header on every attempt.
    """

    def asking(peer: str, forwarded: str) -> Request:
        return Request(
            {
                "type": "http",
                "headers": [(b"x-forwarded-for", forwarded.encode())],
                "client": (peer, 4000),
            }
        )

    assert client_ip(asking("127.0.0.1", "203.0.113.7")) == "203.0.113.7"
    # The dual-stack spelling of the same loopback peer is still the proxy.
    assert client_ip(asking("::ffff:127.0.0.1", "203.0.113.7")) == "203.0.113.7"
    # A peer that is not the proxy: the socket wins and the header is discarded.
    assert client_ip(asking("198.51.100.4", "203.0.113.7")) == "198.51.100.4"
    # Caddy sets rather than appends, so the last hop is the only hop worth reading.
    assert client_ip(asking("127.0.0.1", "1.2.3.4, 203.0.113.7")) == "203.0.113.7"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"password": PASSWORD}, "email"),
        ({"email": "someone@example.com"}, "password"),
        ({"email": "", "password": PASSWORD}, "email"),
        ({"email": "someone@example.com", "password": ""}, "password"),
        ({"email": "someone@example.com", "password": "x" * 129}, "password"),
    ],
)
async def test_login_names_the_field_it_refused(
    client: AsyncClient, body: dict[str, str], field: str
) -> None:
    response = await client.post(LOGIN, json=body)

    assert response.status_code == 422
    assert envelope(response) == {
        "code": "VALIDATION_ERROR",
        "message": "The submitted data is invalid.",
        "field": field,
    }


async def test_an_enormous_password_is_refused_before_it_is_hashed(client: AsyncClient) -> None:
    """The ceiling on the field is what stops one CPU being spent by an anonymous request."""
    response = await client.post(
        LOGIN, json={"email": "someone@example.com", "password": "x" * 10_000}
    )

    assert response.status_code == 422


async def test_the_access_token_stops_working_after_fifteen_minutes(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    account = await create_account(session, email="ticking@example.com")

    token = (await login(client, account)).json()["accessToken"]

    clock.advance(ACCESS_TOKEN_TTL - timedelta(seconds=1))
    assert decode_access_token(token, now=clock).subject == account.id

    clock.advance(timedelta(seconds=2))
    with pytest.raises(AccessTokenExpired):
        decode_access_token(token, now=clock)
