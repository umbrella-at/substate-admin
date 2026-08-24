"""GET /api/auth/me, and everything the bearer token has to survive to reach it.

The body is asserted key by key rather than field by field. The frontend is generated from this
shape, and a response that grew a key is as much a break as one that lost a key — a stray
`passwordHash` would be a leak nobody notices until it is in someone's browser devtools.

The rest of this module is the request path itself: what the token must be, what the account must
be, and where the permissions in the answer actually come from.
"""

import uuid
from datetime import timedelta

import jwt
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import PERMISSION_CACHE_TTL, invalidate_permission_cache
from app.models import RolePermission, User
from app.permissions import SYSTEM_ROLES
from app.security.tokens import ACCESS_TOKEN_TTL, ALGORITHM
from support import ME, Clock, bearer, create_account, envelope, role_id_for


async def test_me_describes_the_session_and_nothing_else(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    account = await create_account(session, email="support@example.com", role_code="support")

    response = await client.get(ME, headers=bearer(account, now=clock.now))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"user", "role", "permissions", "kind", "worldId"}
    assert set(body["user"]) == {"id", "email", "isActive", "createdAt", "lastLoginAt"}
    assert body["user"]["id"] == str(account.id)
    assert body["user"]["email"] == "support@example.com"
    assert body["user"]["isActive"] is True
    assert body["user"]["lastLoginAt"] is None
    assert body["role"] == {"code": "support", "name": "Support"}
    assert body["permissions"] == sorted(SYSTEM_ROLES["support"].permissions)
    # No route in this service mints a demo token, so a session is always a user's.
    assert body["kind"] == "user"
    assert body["worldId"] is None


async def test_me_never_carries_the_password_hash_or_the_role_id(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    account = await create_account(session, email="opaque@example.com")
    stored = (
        await session.execute(select(User.password_hash).where(User.id == account.id))
    ).scalar_one()
    role_id = await role_id_for(session, "admin")

    response = await client.get(ME, headers=bearer(account, now=clock.now))

    assert stored not in response.text
    assert str(role_id) not in response.text
    for forbidden in ("passwordHash", "password_hash", "roleId", "role_id", "argon2"):
        assert forbidden not in response.text


async def test_the_permission_list_is_flat_sorted_and_free_of_duplicates(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    account = await create_account(session, email="admin@example.com", role_code="admin")

    permissions = (await client.get(ME, headers=bearer(account, now=clock.now))).json()[
        "permissions"
    ]

    assert permissions == sorted(permissions)
    assert len(permissions) == len(set(permissions))
    assert all(isinstance(code, str) for code in permissions)


async def test_permissions_are_read_from_the_database_not_from_the_token(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """A role edited at ten o'clock stops granting what it granted at five to."""
    account = await create_account(session, email="viewer@example.com", role_code="viewer")
    headers = bearer(account, now=clock.now)
    assert "plans.read" in (await client.get(ME, headers=headers)).json()["permissions"]

    await session.execute(
        delete(RolePermission).where(
            RolePermission.role_id == await role_id_for(session, "viewer"),
            RolePermission.permission_code == "plans.read",
        )
    )
    await session.commit()
    invalidate_permission_cache()

    # The same token, minted before the edit.
    assert "plans.read" not in (await client.get(ME, headers=headers)).json()["permissions"]


async def test_the_role_snapshot_is_held_for_thirty_seconds_and_no_longer(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """The cache exists so a burst of requests costs one read; it expires so a hand-edited role
    takes effect while the person who edited it is still watching."""
    account = await create_account(session, email="cached@example.com", role_code="viewer")
    headers = bearer(account, now=clock.now)
    assert "plans.read" in (await client.get(ME, headers=headers)).json()["permissions"]

    await session.execute(
        delete(RolePermission).where(
            RolePermission.role_id == await role_id_for(session, "viewer"),
            RolePermission.permission_code == "plans.read",
        )
    )
    await session.commit()

    # Nothing invalidated: within the window the snapshot still answers.
    assert "plans.read" in (await client.get(ME, headers=headers)).json()["permissions"]

    clock.advance(PERMISSION_CACHE_TTL + timedelta(seconds=1))
    assert "plans.read" not in (await client.get(ME, headers=headers)).json()["permissions"]


async def test_me_refuses_a_request_with_no_credential(client: AsyncClient) -> None:
    response = await client.get(ME)

    assert response.status_code == 401
    assert envelope(response)["code"] == "NOT_AUTHENTICATED"
    # RFC 6750: a 401 refusing a bearer token names the scheme it wanted.
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_me_refuses_a_credential_that_is_not_a_bearer_token(client: AsyncClient) -> None:
    response = await client.get(ME, headers={"Authorization": "Basic YWRtaW46YWRtaW4="})

    assert response.status_code == 401
    assert envelope(response)["code"] == "NOT_AUTHENTICATED"


async def test_me_refuses_a_token_that_has_expired(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """TOKEN_EXPIRED and nothing else: it is the one code the frontend answers by refreshing."""
    account = await create_account(session, email="stale@example.com")
    headers = bearer(account, now=clock.now)

    clock.advance(ACCESS_TOKEN_TTL + timedelta(seconds=1))
    response = await client.get(ME, headers=headers)

    assert response.status_code == 401
    assert envelope(response)["code"] == "TOKEN_EXPIRED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_me_refuses_a_demo_token(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """No route mints one. Refusing by type is what keeps that true if one is ever minted."""
    account = await create_account(session, email="demo@example.com", role_code="demo")

    response = await client.get(
        ME, headers=bearer(account, now=clock.now, typ="demo", world_id=uuid.uuid4())
    )

    assert response.status_code == 401
    assert envelope(response)["code"] == "NOT_AUTHENTICATED"


async def test_me_refuses_a_token_signed_with_another_key(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    account = await create_account(session, email="forged@example.com")
    forged = jwt.encode(
        {
            "sub": str(account.id),
            "iat": int(clock.now.timestamp()),
            "exp": int((clock.now + ACCESS_TOKEN_TTL).timestamp()),
            "jti": str(uuid.uuid4()),
            "typ": "access",
        },
        "a-key-this-service-does-not-hold",
        algorithm=ALGORITHM,
    )

    response = await client.get(ME, headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401
    assert envelope(response)["code"] == "NOT_AUTHENTICATED"


async def test_me_refuses_a_token_whose_subject_no_longer_exists(
    client: AsyncClient, clock: Clock
) -> None:
    response = await client.get(ME, headers=bearer(uuid.uuid4(), now=clock.now))

    assert response.status_code == 401
    assert envelope(response)["code"] == "NOT_AUTHENTICATED"


async def test_me_refuses_an_account_that_has_been_deactivated(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """No token_version column: deactivation takes effect on the very next request."""
    account = await create_account(session, email="dismissed@example.com")
    headers = bearer(account, now=clock.now)
    assert (await client.get(ME, headers=headers)).status_code == 200

    await session.execute(update(User).where(User.id == account.id).values(is_active=False))
    await session.commit()

    response = await client.get(ME, headers=headers)

    assert response.status_code == 401
    assert envelope(response)["code"] == "USER_INACTIVE"
    # No challenge: the credential was fine, and presenting another one will not help.
    assert "WWW-Authenticate" not in response.headers
