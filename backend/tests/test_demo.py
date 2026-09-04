"""The demonstration door: a world of your own, and the walls around it.

Every test here builds at least one real sandbox — nine months of engine, four thousand events —
because the thing being asserted is what a visitor actually gets. A faked world would prove that
the route returns a token and nothing about whether the token opens somebody else's data.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.demo import sandboxes
from app.demo.operators import INVENTED, VISITOR
from app.models import AuditLog, DemoSandbox, Role, User
from app.security.ratelimit import DEMO_PER_IP, LOGIN_PER_IP, get_limiter
from app.security.tokens import decode_access_token
from app.worlds.journal import purge_sandbox
from app.worlds.registry import BASE_WORLD_ID, World, get_registry
from support import Clock, create_account, envelope, login

SESSION = "/api/demo/session"

# The sandbox's own operators: the invented colleagues plus the visitor.
OPERATORS = INVENTED + 1


async def open_one(client: AsyncClient, token: str | None = None) -> dict[str, str]:
    """Press the button, and fail loudly rather than returning something unusable."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    response = await client.post(SESSION, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, str] = response.json()
    return body


def world_of(token: str) -> World:
    claims = decode_access_token(token, now=lambda: datetime.now(UTC))
    assert claims.world_id is not None
    world = get_registry().get(str(claims.world_id))
    assert world is not None
    return world


def auth(body: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['accessToken']}"}


async def test_a_press_with_no_credential_builds_a_world_and_opens_it(
    client: AsyncClient, base_world: World
) -> None:
    """The whole point, end to end: no account, no password, a panel with data in it."""
    body = await open_one(client)

    subscribers = await client.get("/api/subscribers", headers=auth(body))
    assert subscribers.status_code == 200
    assert subscribers.json()["total"] > 0

    world = world_of(body["accessToken"])
    assert world.id != BASE_WORLD_ID
    assert world.seeded


async def test_the_pass_lasts_as_long_as_the_world_and_not_a_minute_longer(
    client: AsyncClient, base_world: World
) -> None:
    """A token outliving its sandbox is a session that fails on the next click; a sandbox
    outliving its token is a slot under the ceiling nobody can reach."""
    body = await open_one(client)
    world = world_of(body["accessToken"])

    assert world.expires_at is not None
    assert world.ceiling_at is not None
    assert int(body["expiresIn"]) == pytest.approx(  # type: ignore[call-overload]
        sandboxes.SANDBOX_TTL.total_seconds(), abs=2
    )
    assert datetime.fromisoformat(body["endsAt"]) == world.ceiling_at


async def test_pressing_again_keeps_the_same_world(client: AsyncClient, base_world: World) -> None:
    """The renewal, and the reason it is not a refresh: no cookie, no family, one world.

    A second `create` would have been the easy mistake — the registry replaces a world of the same
    id without complaining, and the visitor's month of wound-forward history would be gone.
    """
    first = await open_one(client)
    world = world_of(first["accessToken"])

    second = await open_one(client, first["accessToken"])

    assert world_of(second["accessToken"]) is world
    assert second["accessToken"] != first["accessToken"]
    assert len(get_registry().sandboxes()) == 1


async def test_a_pass_cannot_be_renewed_past_the_ceiling(
    client: AsyncClient, base_world: World, session: AsyncSession
) -> None:
    """Two hours is absolute. Without it, a tab left open holds a world for as long as the
    process lives, and the ceiling on how many may stand becomes a ceiling on nothing."""
    body = await open_one(client)
    world = world_of(body["accessToken"])
    assert world.ceiling_at is not None

    # Ninety minutes in: over the hour, under the ceiling.
    later = datetime.now(UTC) + timedelta(minutes=90)
    world.expires_at = later
    world.extend(ttl=sandboxes.SANDBOX_TTL, now=later)

    assert world.expires_at == world.ceiling_at


async def test_a_full_house_is_refused_with_something_a_screen_can_say(
    client: AsyncClient, base_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ceiling, and the shape of hitting it. Lowered for the test rather than built up to:
    thirty-two seeded worlds is five seconds of one CPU to assert one status code."""
    monkeypatch.setattr(sandboxes, "MAX_SANDBOXES", 1)
    await open_one(client)

    response = await client.post(SESSION)

    assert response.status_code == 503
    assert envelope(response)["code"] == "SANDBOX_FULL"


async def test_building_worlds_is_rate_limited_by_address(
    client: AsyncClient, base_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valve on the seventh of a second each world costs the only CPU there is."""
    monkeypatch.setattr(sandboxes, "MAX_SANDBOXES", DEMO_PER_IP.limit + 1)
    for _ in range(DEMO_PER_IP.limit):
        await open_one(client)

    response = await client.post(SESSION)

    assert response.status_code == 429
    assert envelope(response)["code"] == "RATE_LIMITED"


async def test_a_demonstration_does_not_spend_an_operators_allowance_to_sign_in(
    client: AsyncClient, base_world: World, session: AsyncSession, clock: Clock
) -> None:
    """DECISION 146, CHECKED RATHER THAN ASSUMED.

    The login limiter is keyed by address and never refunded, so an office watching the panel
    together shares one bucket with the people who work there. A demonstration that went through
    `/api/auth/login`, or reused that rule for its own ceiling, would lock the staff out.
    """
    account = await create_account(session, email="staff@example.com")
    await session.commit()
    limiter = get_limiter()

    await open_one(client)

    assert limiter.hit(LOGIN_PER_IP, "unknown", now=clock.now).allowed
    assert (await login(client, account)).status_code == 200


async def test_a_sandbox_holds_operators_of_its_own_and_shows_nobody_elses(
    client: AsyncClient, base_world: World, session: AsyncSession
) -> None:
    """Decision 85, which is what the whole `world_id` column was for.

    Both halves: the visitor sees invented colleagues, and the real operator on this installation
    is not among them. The roles are copies too, and editable — a system role is refused by the
    application, and a demonstration of a read-only editor demonstrates nothing.
    """
    await create_account(session, email="real-operator@example.com")
    await session.commit()
    body = await open_one(client)

    users = (await client.get("/api/users", headers=auth(body))).json()
    roles = (await client.get("/api/roles", headers=auth(body))).json()

    addresses = {row["email"] for row in users["items"]}
    assert users["total"] == OPERATORS
    assert VISITOR in addresses
    assert "real-operator@example.com" not in addresses
    assert {role["code"] for role in roles["items"]} == {"admin", "support", "viewer", "demo"}
    assert not any(role["isSystem"] for role in roles["items"])


async def test_an_operator_never_sees_a_sandboxs_people(
    client: AsyncClient, base_world: World, session: AsyncSession, clock: Clock
) -> None:
    """The other direction, which is the one that would leak quietly: a visitor's invented
    colleagues appearing on the real users screen, in a pager nobody rereads."""
    account = await create_account(session, email="operator@example.com", role_code="admin")
    await session.commit()
    await open_one(client)

    signed_in = await login(client, account)
    headers = {"Authorization": f"Bearer {signed_in.json()['accessToken']}"}
    users = (await client.get("/api/users", headers=headers)).json()
    roles = (await client.get("/api/roles", headers=headers)).json()

    assert {row["email"] for row in users["items"]} == {"operator@example.com"}
    assert all(role["isSystem"] for role in roles["items"])


async def test_a_world_that_is_gone_takes_its_rows_with_it(
    client: AsyncClient, base_world: World, session: AsyncSession
) -> None:
    """The reaper, and the order the foreign keys force on it.

    `audit_log.actor_user_id` and `users.role_id` are both RESTRICT, so a sandbox whose visitor
    did anything at all cannot be deleted operators-first — the transaction rolls back and the
    reaper retries the same failure every minute for as long as the process lives.
    """
    body = await open_one(client)
    world = world_of(body["accessToken"])
    await _leave_a_trail(client, auth(body))
    assert await _rows_for(session, world.id) == {"users": OPERATORS, "roles": 4, "audit": 1}

    world.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    async def purge(world_id: str) -> None:
        await purge_sandbox(await session.connection(), world_id)

    collected = await sandboxes.reap(get_registry(), purge)

    assert collected == 1
    assert await _rows_for(session, world.id) == {"users": 0, "roles": 0, "audit": 0}
    assert get_registry().get(world.id) is None


async def test_a_pass_into_a_reaped_world_is_told_the_demonstration_ended(
    client: AsyncClient, base_world: World, session: AsyncSession
) -> None:
    """One code for both endings — the hour ran out, or a deploy restarted the process under
    them. From outside they are the same event, and inventing a difference would be a guess."""
    body = await open_one(client)
    world = world_of(body["accessToken"])
    world.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    response = await client.get("/api/subscribers", headers=auth(body))

    assert response.status_code == 410
    assert envelope(response)["code"] == "SANDBOX_GONE"


async def test_the_row_that_outlives_the_process_says_which_world_it_was(
    client: AsyncClient, base_world: World, session: AsyncSession
) -> None:
    """Worlds live in memory, so every one of them is an orphan after a restart. The row is what
    a later sweep has to work from — and what says the visitor's address was never stored."""
    body = await open_one(client)
    world = world_of(body["accessToken"])

    row = (
        await session.execute(select(DemoSandbox).where(DemoSandbox.world_id == world.id))
    ).scalar_one()

    assert row.expires_at == world.expires_at
    assert row.ceiling_at == world.ceiling_at
    assert row.ip_hash and "." not in row.ip_hash


async def _leave_a_trail(client: AsyncClient, headers: dict[str, str]) -> None:
    """One audited action, so the reaper has the foreign key it would trip over."""
    page = (await client.get("/api/subscribers?pageSize=1", headers=headers)).json()
    subscriber = page["items"][0]["userId"]
    response = await client.post(f"/api/subscribers/{subscriber}/cancel", headers=headers, json={})
    assert response.status_code in (200, 409), response.text


async def _rows_for(session: AsyncSession, world_id: str) -> dict[str, int]:
    async def count(statement: object) -> int:
        found: int = (await session.execute(statement)).scalar_one()  # type: ignore[arg-type]
        return found

    return {
        "users": await count(
            select(func.count()).select_from(User).where(User.world_id == world_id)
        ),
        "roles": await count(
            select(func.count()).select_from(Role).where(Role.world_id == world_id)
        ),
        "audit": await count(
            select(func.count())
            .select_from(AuditLog)
            .join(User, User.id == AuditLog.actor_user_id)
            .where(User.world_id == world_id)
        ),
    }


async def test_the_sandbox_id_is_not_something_a_caller_can_choose(
    client: AsyncClient, base_world: World
) -> None:
    """A world is named by this service and named nowhere else. The token carries it; no request
    body, query string or path anywhere in the API reads one — asserted route by route in
    tests/test_world_scoping.py, and asserted here as the thing that makes that matter."""
    body = await open_one(client)
    claims = decode_access_token(body["accessToken"], now=lambda: datetime.now(UTC))

    assert claims.typ == "demo"
    assert claims.world_id is not None
    assert uuid.UUID(str(claims.world_id))
