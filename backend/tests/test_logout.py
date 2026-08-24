"""POST /api/auth/logout.

Logout takes no access token, always answers 204, and always clears the cookie. Each of those is
a decision rather than an omission: a tab left open over lunch has an access token fifteen minutes
dead, and requiring a live one would mean refreshing a session in order to end it.

What it must not do is end anyone else's session. Revoking every family — which is what reuse
detection does — would mean signing out of the panel on a laptop also signed out the phone.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers import auth
from app.security.refresh import hash_refresh_token
from support import (
    Clock,
    cookie_was_cleared,
    create_account,
    login,
    logout_with,
    refresh_rows,
    refresh_value,
    refresh_with,
)


async def test_logout_revokes_this_device_and_leaves_the_others_alone(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    account = await create_account(session, email="two-devices@example.com")
    laptop = refresh_value(await login(client, account))
    phone = refresh_value(await login(client, account))

    response = await logout_with(client, phone)

    assert response.status_code == 204
    assert response.content == b""
    assert cookie_was_cleared(response)

    rows = {row.token_hash: row for row in await refresh_rows(session, account.id)}
    assert rows[hash_refresh_token(phone)].revoked_at == clock.now
    assert rows[hash_refresh_token(laptop)].revoked_at is None

    # The surviving family is not merely unrevoked in a column; it still refreshes.
    assert (await refresh_with(client, laptop)).status_code == 200


async def test_logout_needs_no_access_token(client: AsyncClient, session: AsyncSession) -> None:
    """No Authorization header anywhere below, and the family still ends."""
    account = await create_account(session, email="expired-tab@example.com")
    presented = refresh_value(await login(client, account))

    response = await logout_with(client, presented)

    assert response.status_code == 204
    assert (await refresh_with(client, presented)).status_code == 401


async def test_logout_without_a_cookie_still_answers_204_and_clears(client: AsyncClient) -> None:
    response = await logout_with(client, None)

    assert response.status_code == 204
    assert cookie_was_cleared(response)


async def test_logout_with_a_token_nobody_issued_answers_204(client: AsyncClient) -> None:
    response = await logout_with(client, "a-token-this-service-never-issued")

    assert response.status_code == 204
    assert cookie_was_cleared(response)


async def test_logging_out_twice_is_not_an_error(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A caller who is already logged out has got what they asked for."""
    account = await create_account(session, email="again@example.com")
    presented = refresh_value(await login(client, account))

    assert (await logout_with(client, presented)).status_code == 204
    assert (await logout_with(client, presented)).status_code == 204


async def test_logout_keeps_its_promise_when_the_database_does_not(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 500 here would leave the cookie in the browser, which is the opposite of logging out.

    The panel would look signed in, replay the token on every load, and the person would have no
    way to end the session from the client at all. The database being down is exactly when
    somebody is most likely to be trying to get out of the panel.
    """
    account = await create_account(session, email="database-down@example.com")
    presented = refresh_value(await login(client, account))

    async def refuse(*_: object, **__: object) -> bool:
        raise OperationalError("UPDATE admin.refresh_tokens", {}, Exception("connection lost"))

    monkeypatch.setattr(auth, "revoke_family_for_token", refuse)
    response = await logout_with(client, presented)

    assert response.status_code == 204
    assert response.content == b""
    assert cookie_was_cleared(response)


async def test_logout_of_an_unknown_token_revokes_nothing(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A cookie from another deployment, or one a person edited, is not an instruction."""
    account = await create_account(session, email="bystander@example.com")
    presented = refresh_value(await login(client, account))

    await logout_with(client, "a-token-this-service-never-issued")

    assert all(row.revoked_at is None for row in await refresh_rows(session, account.id))
    assert (await refresh_with(client, presented)).status_code == 200


async def test_logout_revokes_the_whole_chain_not_just_the_token_presented(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The family is what ends. Revoking only the presented row would leave its successor live."""
    account = await create_account(session, email="chain@example.com")
    first = refresh_value(await login(client, account))
    second = refresh_value(await refresh_with(client, first))

    await logout_with(client, first)

    assert all(row.revoked_at is not None for row in await refresh_rows(session, account.id))
    assert (await refresh_with(client, second)).status_code == 401
