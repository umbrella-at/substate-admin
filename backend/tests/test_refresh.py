"""POST /api/auth/refresh.

Rotation, reuse detection and the grace window are one mechanism, and every test here asserts
against the `refresh_tokens` table as well as against the response. The response says what the
client was told; the table says whether the sessions that had to end actually ended. A 401 that
revoked nothing looks exactly like a 401 that revoked everything from outside.

Time is moved rather than waited for. The grace window is thirty seconds and a family lasts
ninety days, and neither is a thing a test suite can sit through.

`revoked_reason` is asserted on wherever a row is revoked, because the reason is not a label: it
is what the next presentation of that row is judged by, and a row revoked with the wrong one
either ends sessions that should have survived or fails to end the one that leaked.
"""

import uuid
from datetime import timedelta
from typing import Final

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken, User
from app.security.refresh import (
    COOKIE_NAME,
    COOKIE_PATH,
    FAMILY_TTL,
    GRACE_PERIOD,
    PRUNE_RETENTION,
    TOKEN_TTL,
    hash_refresh_token,
    prune_expired,
)
from support import (
    REFRESH,
    Clock,
    cookie_was_cleared,
    create_account,
    envelope,
    login,
    logout_with,
    refresh_rows,
    refresh_value,
    refresh_with,
    token_row,
)

_A_MOMENT: Final = timedelta(seconds=1)


async def test_the_cookie_alone_rotates_a_session(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The browser's own path: log in, then refresh with whatever the jar kept."""
    account = await create_account(session, email="browser@example.com")
    presented = refresh_value(await login(client, account))

    response = await client.post(REFRESH)

    assert response.status_code == 200
    assert set(response.json()) == {"accessToken", "expiresIn"}
    assert client.cookies[COOKIE_NAME] != presented


async def test_rotation_consumes_the_presented_token_and_issues_its_successor(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    account = await create_account(session, email="rotating@example.com")
    first = refresh_value(await login(client, account))

    clock.advance(timedelta(minutes=5))
    response = await refresh_with(client, first)
    second = refresh_value(response)

    assert response.status_code == 200
    assert second != first

    consumed = await token_row(session, first)
    successor = await token_row(session, second)
    assert consumed.used_at == clock.now
    assert consumed.revoked_at is None
    assert successor.used_at is None
    # Same family: rotation is a link in one device's chain, not a new session.
    assert successor.family_id == consumed.family_id
    # Sliding, and the ceiling untouched.
    assert successor.expires_at == clock.now + TOKEN_TTL
    assert successor.family_expires_at == consumed.family_expires_at


async def test_the_successor_is_the_token_that_works_next(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await create_account(session, email="chained@example.com")
    first = refresh_value(await login(client, account))
    second = refresh_value(await refresh_with(client, first))

    third = await refresh_with(client, second)

    assert third.status_code == 200
    assert refresh_value(third) not in {first, second}


async def test_presenting_a_consumed_token_after_the_window_ends_every_session(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """Reuse detection. A token that turned up twice was copied, so no device is trusted."""
    account = await create_account(session, email="leaked@example.com")
    laptop = refresh_value(await login(client, account))
    phone = refresh_value(await login(client, account))
    await refresh_with(client, laptop)

    clock.advance(GRACE_PERIOD + _A_MOMENT)
    refused = await refresh_with(client, laptop)

    assert refused.status_code == 401
    assert envelope(refused)["code"] == "REFRESH_TOKEN_REUSED"
    assert cookie_was_cleared(refused)

    rows = await refresh_rows(session, account.id)
    # The laptop's original and its successor, and the phone's: three rows in two families.
    assert len(rows) == 3
    assert len({row.family_id for row in rows}) == 2
    assert all(row.revoked_at == clock.now for row in rows)

    # One row is the token that was replayed; the other two are collateral, and say so. The
    # distinction is what stops the phone's next refresh from starting a second cascade.
    assert await _reason(session, laptop) == "reuse"
    assert await _reason(session, phone) == "family_revoked"

    # The other device is genuinely signed out, not merely marked so in a column — and it is told
    # that its session ended, not that it stole something.
    elsewhere = await refresh_with(client, phone)
    assert elsewhere.status_code == 401
    assert envelope(elsewhere)["code"] == "REFRESH_TOKEN_INVALID"


async def test_presenting_a_consumed_token_inside_the_window_rotates_again(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """A reload with a request in flight, a second tab, a retry after the wifi dropped.

    Strict reuse detection would sign that person out; the thirty-second window is what separates
    an honest race from a copy of a secret.
    """
    account = await create_account(session, email="racing@example.com")
    first = refresh_value(await login(client, account))
    consumed_at = clock.now
    second = refresh_value(await refresh_with(client, first))

    clock.advance(timedelta(seconds=10))
    response = await refresh_with(client, first)

    assert response.status_code == 200
    third = refresh_value(response)
    assert third not in {first, second}

    rows = await refresh_rows(session, account.id)
    assert len(rows) == 3
    assert len({row.family_id for row in rows}) == 1
    # The family was not condemned: nothing here is a cascade.
    assert await _reason(session, first) is None
    assert await _reason(session, second) == "superseded"
    assert await _reason(session, third) is None
    # The presented token keeps the moment it was actually consumed.
    assert (await token_row(session, first)).used_at == consumed_at

    # And the token the grace rotation handed out is usable.
    assert (await refresh_with(client, third)).status_code == 200


async def test_the_window_is_thirty_seconds_wide_and_measured_from_the_use(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """Twenty-nine seconds after the token was consumed is a race; thirty-one is a copy.

    Written in seconds rather than in terms of GRACE_PERIOD: a test that measures the window
    against the constant that sets it agrees with any value that constant is ever given, including
    zero, and would have nothing to say about a window that quietly closed.
    """
    account = await create_account(session, email="boundary@example.com")
    first = refresh_value(await login(client, account))
    await refresh_with(client, first)

    clock.advance(timedelta(seconds=29))
    assert (await refresh_with(client, first)).status_code == 200

    # A grace rotation does not consume the token it was given, so the window is still measured
    # from the first exchange: this is thirty-one seconds after it.
    clock.advance(timedelta(seconds=2))
    refused = await refresh_with(client, first)
    assert envelope(refused)["code"] == "REFRESH_TOKEN_REUSED"


def test_the_lifetimes_are_the_ones_the_specification_fixed() -> None:
    """Every test above is written in terms of these, so the numbers themselves are pinned once,
    here. Each is a decision — thirty seconds of grace, a thirty-day token inside a ninety-day
    family — rather than a knob to be turned when a test proves inconvenient.
    """
    assert GRACE_PERIOD.total_seconds() == 30
    assert TOKEN_TTL.days == 30
    assert FAMILY_TTL.days == 90
    assert COOKIE_NAME == "sa_refresh"
    # Not "/", which is what the __Host- prefix would demand.
    assert COOKIE_PATH == "/api/auth"


async def test_an_unknown_token_is_refused_and_the_cookie_cleared(client: AsyncClient) -> None:
    refused = await refresh_with(client, "a-token-this-service-never-issued")

    assert refused.status_code == 401
    assert envelope(refused)["code"] == "REFRESH_TOKEN_INVALID"
    assert cookie_was_cleared(refused)


async def test_no_cookie_at_all_is_refused_and_the_cookie_cleared(client: AsyncClient) -> None:
    """Cleared even when there was nothing to clear: what is there may be a cookie this route
    cannot read, and it would otherwise be replayed on every load."""
    refused = await refresh_with(client, None)

    assert refused.status_code == 401
    assert envelope(refused)["code"] == "REFRESH_TOKEN_INVALID"
    assert cookie_was_cleared(refused)


async def test_an_expired_token_is_refused_without_revoking_anything(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """A laptop that slept for a month is not evidence of theft."""
    account = await create_account(session, email="asleep@example.com")
    presented = refresh_value(await login(client, account))

    clock.advance(TOKEN_TTL + timedelta(minutes=1))
    refused = await refresh_with(client, presented)

    assert refused.status_code == 401
    assert envelope(refused)["code"] == "REFRESH_TOKEN_INVALID"
    assert cookie_was_cleared(refused)
    assert all(row.revoked_at is None for row in await refresh_rows(session, account.id))


async def test_the_family_ceiling_caps_a_token_and_then_ends_the_session(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """Sliding expiry inside a hard ninety days, which no amount of rotating extends."""
    account = await create_account(session, email="ninety@example.com")
    presented = refresh_value(await login(client, account))
    ceiling = (await token_row(session, presented)).family_expires_at
    assert ceiling == clock.now + FAMILY_TTL

    clock.advance(timedelta(days=29))
    presented = refresh_value(await refresh_with(client, presented))
    # Day twenty-nine: a full thirty days ahead again, still well inside the ceiling.
    assert (await token_row(session, presented)).expires_at == clock.now + TOKEN_TTL

    # Rotating every twenty-nine days is what keeps a session alive for months.
    for _ in range(2):
        clock.advance(timedelta(days=29))
        rotated = await refresh_with(client, presented)
        assert rotated.status_code == 200
        presented = refresh_value(rotated)

    # Day eighty-seven, and the token just issued expires with the family rather than thirty days
    # after it. The ceiling itself has not moved since login.
    capped = await token_row(session, presented)
    assert capped.expires_at == ceiling
    assert capped.family_expires_at == ceiling
    assert ceiling < clock.now + TOKEN_TTL

    clock.advance(timedelta(days=3, minutes=1))
    dead = await refresh_with(client, presented)
    assert dead.status_code == 401
    assert envelope(dead)["code"] == "REFRESH_TOKEN_INVALID"
    assert cookie_was_cleared(dead)


async def test_a_deactivated_user_loses_the_family_at_the_next_exchange(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """The family dies with the account.

    Otherwise a disabled user holding a live refresh token keeps minting access tokens that the
    request path then refuses one at a time, and the session never actually ends.
    """
    account = await create_account(session, email="dismissed@example.com")
    presented = refresh_value(await login(client, account))
    await session.execute(update(User).where(User.id == account.id).values(is_active=False))
    await session.commit()

    refused = await refresh_with(client, presented)

    assert refused.status_code == 401
    assert envelope(refused)["code"] == "USER_INACTIVE"
    assert cookie_was_cleared(refused)
    assert all(row.revoked_at == clock.now for row in await refresh_rows(session, account.id))
    # Ended by the account, not by a copy of a token: presenting it again refuses rather than
    # cascading through families the person may have signed back into.
    assert await _reason(session, presented) == "inactive"


async def test_a_grace_rotation_ends_the_leaf_it_replaced(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """One live token per family, through a grace hit as well as a normal one.

    Without this the family forks at the first grace hit: the successor the original rotation
    handed out and the one the grace rotation handed out are both unused, both rotate forever as
    fresh tokens, and because they never collide, reuse detection can never fire on that family
    again. A single glimpse of a refresh token would become a permanent second session.
    """
    account = await create_account(session, email="forked@example.com")
    first = refresh_value(await login(client, account))
    second = refresh_value(await refresh_with(client, first))

    clock.advance(timedelta(seconds=10))
    third = refresh_value(await refresh_with(client, first))

    superseded = await token_row(session, second)
    assert superseded.revoked_at == clock.now
    assert await _reason(session, second) == "superseded"

    # Exactly one row in that family is live, and it is the one the grace rotation issued.
    family = await refresh_rows(session, account.id)
    assert [row.token_hash for row in family if row.revoked_at is None and row.used_at is None] == [
        hash_refresh_token(third)
    ]


async def test_a_grace_rotation_does_not_reopen_the_window_on_a_spent_ancestor(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """Superseding the leaves must not touch the tokens further back up the chain.

    A consumed ancestor is refused by its own `used_at`, and outside the window that refusal is
    reuse detection. Revoking it as superseded would replace the only record of when it was
    consumed with the time of somebody else's rotation — and since a superseded row is judged
    against `revoked_at`, a token spent a week ago would get a brand-new thirty-second window in
    which it rotates instead of raising the alarm.
    """
    account = await create_account(session, email="ancestor@example.com")
    spent = refresh_value(await login(client, account))
    second = refresh_value(await refresh_with(client, spent))

    # Far enough on that `spent` is unambiguously reuse rather than an honest double submit.
    clock.advance(GRACE_PERIOD + _A_MOMENT)
    await refresh_with(client, second)

    # A grace rotation elsewhere in the same family, while `spent` sits three tokens back.
    clock.advance(timedelta(seconds=10))
    await refresh_with(client, second)

    assert await _reason(session, spent) is None

    caught = await refresh_with(client, spent)

    assert caught.status_code == 401
    assert envelope(caught)["code"] == "REFRESH_TOKEN_REUSED"
    assert await _reason(session, spent) == "reuse"


async def test_the_replayed_token_is_caught_by_the_victims_next_refresh(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """Theft inside the window is visible rather than silent.

    An attacker who sees a refresh token once and replays it within thirty seconds gets a working
    token — that is the price of the window. What must not happen is that the theft then goes
    unnoticed forever. The victim's browser is holding the successor the honest rotation handed
    out, which the attacker's grace rotation superseded, and the victim presents it fifteen
    minutes later when the access token expires. That is the alarm.
    """
    account = await create_account(session, email="glimpsed@example.com")
    stolen = refresh_value(await login(client, account))
    victim_holds = refresh_value(await refresh_with(client, stolen))

    clock.advance(timedelta(seconds=5))
    attacker_holds = refresh_value(await refresh_with(client, stolen))

    clock.advance(timedelta(minutes=15))
    caught = await refresh_with(client, victim_holds)

    assert caught.status_code == 401
    assert envelope(caught)["code"] == "REFRESH_TOKEN_REUSED"

    # And the session the attacker built is over with everything else.
    assert all(row.revoked_at is not None for row in await refresh_rows(session, account.id))
    assert (await refresh_with(client, attacker_holds)).status_code == 401


async def test_a_second_device_survives_a_cascade_it_had_no_part_in(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """Revocation is not theft, and a cascade must not be self-perpetuating.

    After a cascade every other device is holding a token that is revoked and unused. Reading
    that as evidence of a copy would mean each of those devices starts a cascade of its own on its
    next refresh — taking with it whatever the person has signed back into in the meantime, and
    logging an alarm that names a family which leaked nothing.
    """
    account = await create_account(session, email="innocent@example.com")
    laptop = refresh_value(await login(client, account))
    phone = refresh_value(await login(client, account))
    await refresh_with(client, laptop)
    clock.advance(GRACE_PERIOD + _A_MOMENT)
    await refresh_with(client, laptop)

    # The person signs in again on the laptop, and only then does the phone wake up and present
    # the cookie it has been holding since before the cascade.
    signed_back_in = refresh_value(await login(client, account))
    stale = await refresh_with(client, phone)

    assert stale.status_code == 401
    assert envelope(stale)["code"] == "REFRESH_TOKEN_INVALID"

    # The new session is untouched: no second cascade, and nothing new was revoked.
    assert (await refresh_with(client, signed_back_in)).status_code == 200


async def test_two_devices_stay_signed_in_after_one_cascade(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """The end state of the same scenario, from the person's side.

    They were signed out everywhere, they signed back in on both devices, and both devices keep
    working — including after the phone's pre-cascade cookie is replayed by a tab that had been
    left open. That replay is the whole point: it is the one a cascade leaves lying in every
    browser the person owns, and treating it as theft is what makes one cascade the first of an
    endless series.
    """
    account = await create_account(session, email="both-again@example.com")
    laptop = refresh_value(await login(client, account))
    stale_phone = refresh_value(await login(client, account))
    await refresh_with(client, laptop)
    clock.advance(GRACE_PERIOD + _A_MOMENT)
    await refresh_with(client, laptop)

    laptop_again = refresh_value(await login(client, account))
    phone_again = refresh_value(await login(client, account))

    # The tab that slept through all of it wakes up and presents what it still has.
    assert (await refresh_with(client, stale_phone)).status_code == 401

    assert (await refresh_with(client, laptop_again)).status_code == 200
    assert (await refresh_with(client, phone_again)).status_code == 200


async def test_a_token_revoked_by_a_logout_is_a_plain_refusal(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The session is over. Saying so is correct, and it revokes nothing further."""
    account = await create_account(session, email="signed-off@example.com")
    laptop = refresh_value(await login(client, account))
    phone = refresh_value(await login(client, account))
    await logout_with(client, laptop)

    refused = await refresh_with(client, laptop)

    assert refused.status_code == 401
    assert envelope(refused)["code"] == "REFRESH_TOKEN_INVALID"
    assert await _reason(session, laptop) == "logout"
    # Logging out of one device did not escalate into revoking every family the person has.
    assert (await refresh_with(client, phone)).status_code == 200


async def test_a_revoked_row_with_no_reason_is_refused_without_a_cascade(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """Nothing writes such a row — the table forbids it — but the classifier is asked anyway.

    Inventing evidence of theft out of a missing value is the one mistake with a blast radius, so
    a revocation this code cannot account for ends that session and no other.
    """
    account = await create_account(session, email="mystery@example.com")
    laptop = refresh_value(await login(client, account))
    phone = refresh_value(await login(client, account))
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(laptop))
        # Both columns, because the check constraint refuses one without the other; the reason is
        # a value from no version of this application.
        .values(revoked_at=clock.now, revoked_reason="a-reason-from-somewhere-else")
    )
    await session.commit()

    refused = await refresh_with(client, laptop)

    assert refused.status_code == 401
    assert envelope(refused)["code"] == "REFRESH_TOKEN_INVALID"
    assert (await refresh_with(client, phone)).status_code == 200


async def test_a_revoked_row_must_say_why(session: AsyncSession, clock: Clock) -> None:
    """The pairing is a constraint, not a convention: the classifier reads that column."""
    account = await create_account(session, email="unexplained@example.com")
    row = RefreshToken(
        user_id=account.id,
        token_hash=hash_refresh_token("a-value-no-cookie-ever-carried"),
        family_id=uuid.uuid4(),
        issued_at=clock.now,
        expires_at=clock.now + TOKEN_TTL,
        family_expires_at=clock.now + FAMILY_TTL,
        revoked_at=clock.now,
    )
    session.add(row)

    with pytest.raises(IntegrityError, match="revoked_reason_set_with_revoked_at"):
        await session.commit()
    await session.rollback()


async def test_sixty_refreshes_a_minute_refuse_the_sixty_first(client: AsyncClient) -> None:
    """A loose ceiling on a runaway client.

    Every attempt below fails on its own merits; what is under test is that the counter answers
    before the presented token is looked at at all.
    """
    here = {"X-Forwarded-For": "203.0.113.30"}

    for _ in range(60):
        response = await refresh_with(client, "not-a-token", headers=here)
        assert response.status_code == 401

    refused = await refresh_with(client, "not-a-token", headers=here)

    assert refused.status_code == 429
    assert envelope(refused)["code"] == "RATE_LIMITED"
    assert 0 < int(refused.headers["Retry-After"]) <= 60


async def test_the_reaper_deletes_what_can_no_longer_answer_anything(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """This table grows with traffic rather than with the number of people using the panel."""
    account = await create_account(session, email="reaped@example.com")
    await login(client, account)

    # Thirty-seven days on: that token expired a week ago, and no presentation of it can produce
    # anything but "expired" ever again.
    clock.advance(TOKEN_TTL + PRUNE_RETENTION + _A_MOMENT)
    live = refresh_value(await login(client, account))

    assert await prune_expired(session, now=clock.now) == 1

    # The session that is still running was not touched — not the row, and not the session.
    rows = await refresh_rows(session, account.id)
    assert [row.token_hash for row in rows] == [hash_refresh_token(live)]
    assert (await refresh_with(client, live)).status_code == 200


async def test_the_reaper_keeps_an_expired_row_that_was_revoked_recently(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """Retention runs from the last thing that happened to the row, not from its expiry.

    Logging out of a laptop that has been shut for a month writes `revoked_at` onto rows that
    expired weeks ago, and that revocation is the informative part.
    """
    account = await create_account(session, email="late-logout@example.com")
    presented = refresh_value(await login(client, account))
    clock.advance(TOKEN_TTL + PRUNE_RETENTION + _A_MOMENT)
    await logout_with(client, presented)

    assert await prune_expired(session, now=clock.now) == 0
    assert len(await refresh_rows(session, account.id)) == 1

    clock.advance(PRUNE_RETENTION + _A_MOMENT)
    assert await prune_expired(session, now=clock.now) == 1


async def test_the_reaper_keeps_a_revoked_row_that_is_still_presentable(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """A row deleted early turns a session that ended for a known reason into an unknown token.

    The client is told the same thing either way; the journal is not, and the reason is the whole
    of what separates a logout from a theft.
    """
    account = await create_account(session, email="yesterday@example.com")
    presented = refresh_value(await login(client, account))
    await logout_with(client, presented)

    clock.advance(timedelta(days=1))

    assert await prune_expired(session, now=clock.now) == 0
    assert len(await refresh_rows(session, account.id)) == 1


async def _reason(session: AsyncSession, value: str) -> str | None:
    """The `revoked_reason` behind one plaintext token.

    Asked with a select of its own rather than through `support.token_row`, which returns a fixed
    set of columns — and asserting on the row's absence separately, because a missing row and a
    row whose reason is null both come back as None.
    """
    found = (
        await session.execute(
            select(RefreshToken.revoked_reason).where(
                RefreshToken.token_hash == hash_refresh_token(value)
            )
        )
    ).one_or_none()
    assert found is not None, "no refresh_tokens row for that value"
    reason: str | None = found[0]
    return reason
