"""The demonstration door: a world of your own, and the walls around it.

Every test here builds at least one real sandbox — nine months of engine, four thousand events —
because the thing being asserted is what a visitor actually gets. A faked world would prove that
the route returns a token and nothing about whether the token opens somebody else's data.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.demo import sandboxes
from app.demo.operators import INVENTED, VISITOR
from app.demo.sandboxes import open_sandbox, reap
from app.models import AuditLog, DemoSandbox, Role, User
from app.security.ratelimit import DEMO_PER_IP, LOGIN_PER_IP, get_limiter
from app.security.tokens import decode_access_token
from app.worlds.journal import purge_orphans, purge_sandbox
from app.worlds.registry import BASE_WORLD_ID, World, get_registry
from app.worlds.ticker import ticking
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


async def test_the_pass_lasts_as_long_as_the_demonstration_possibly_can(
    client: AsyncClient, base_world: World
) -> None:
    """TO THE CEILING, NOT TO THE SLIDING HOUR, AND THE DIFFERENCE WAS A SILENT SWAP.

    The hour moves forward on every request and a minted pass cannot, so a pass cut to the hour
    died on a world that was still standing.

    The panel answers a 401 by renewing, a renewal presents the expired pass, and an expired pass
    is one the door cannot tell from no pass — so the visitor was handed a brand-new world.

    Minting to the ceiling removes the moment rather than papering it: the world always dies
    first, and a dead world is a refusal the panel has a screen for.
    """
    body = await open_one(client)
    world = world_of(body["accessToken"])

    assert world.expires_at is not None
    assert world.ceiling_at is not None
    assert int(body["expiresIn"]) == pytest.approx(  # type: ignore[call-overload]
        sandboxes.SANDBOX_CEILING.total_seconds(), abs=2
    )
    assert int(body["expiresIn"]) > sandboxes.SANDBOX_TTL.total_seconds()
    assert datetime.fromisoformat(body["endsAt"]) == world.ceiling_at


async def test_a_renewed_pass_still_ends_with_the_world(
    client: AsyncClient, base_world: World
) -> None:
    """The renewal cuts its pass to what is left of the ceiling, not to a fresh two hours.

    Asserted through the route rather than against `World.extend`: what the endpoint mints is the
    half a unit test of the clamp cannot see, and a pass good past the ceiling is a live token for
    a world that has been reaped.
    """
    first = await open_one(client)
    world = world_of(first["accessToken"])
    assert world.ceiling_at is not None

    # Ninety minutes in: over the hour, under the ceiling.
    world.expires_at = datetime.now(UTC) + timedelta(minutes=30)
    world.ceiling_at = datetime.now(UTC) + timedelta(minutes=30)

    second = await open_one(client, first["accessToken"])

    assert int(second["expiresIn"]) == pytest.approx(30 * 60, abs=5)  # type: ignore[call-overload]


async def test_a_press_with_a_pass_into_a_world_that_is_gone_says_so(
    client: AsyncClient, base_world: World
) -> None:
    """THE ORDINARY ENDING, AND THE ONE THE DOOR USED TO ANSWER WITH A DIFFERENT WORLD.

    Handing somebody a fresh sandbox in a 200 is the panel swapping their world under them: the
    month they wound, the subscriptions they cancelled, the colleagues they edited, all replaced
    with no message. The refusal is what the ended screen is for.
    """
    body = await open_one(client)
    world = world_of(body["accessToken"])
    world.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    response = await client.post(SESSION, headers=auth(body))

    assert response.status_code == 410
    assert envelope(response)["code"] == "SANDBOX_GONE"


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


async def test_a_world_cannot_be_held_past_the_ceiling(
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


async def test_a_restart_leaves_nothing_of_a_sandbox_behind(
    client: AsyncClient, base_world: World, session: AsyncSession
) -> None:
    """What a deploy does to every world at once, and the sweep that follows it.

    Sandboxes live in memory, so a restart loses all of them and every row they own becomes an
    orphan. The journal sweep at the next start is the only thing that ever collects those — and
    before this it swept two tables of five, leaving operators and roles to pile up per deploy.
    """
    body = await open_one(client)
    world = world_of(body["accessToken"])
    await _leave_a_trail(client, auth(body))

    # The process comes back holding one world, and it is not this one.
    swept = await purge_orphans(await session.connection(), [BASE_WORLD_ID])

    assert swept > 0
    assert await _rows_for(session, world.id) == {"users": 0, "roles": 0, "audit": 0}
    left = (await session.execute(select(func.count()).select_from(DemoSandbox))).scalar_one()
    assert left == 0


async def test_a_visitor_never_sees_a_real_operators_trail(
    client: AsyncClient, base_world: World, session: AsyncSession, clock: Clock
) -> None:
    """THE FILTER THAT MAKES THE WIDENED DEMO ROLE SAFE, ASSERTED THROUGH THE SCREEN.

    This round gave `demo` all thirteen codes, `audit.read` among them, on the argument that the
    world filter is what makes the grant safe rather than the grant being withheld.

    Removing the filter serves a stranger who pressed a button every real operator's trail, with
    their addresses joined alongside — and the suite passed with it removed.
    """
    operator = await create_account(session, email="auditable@example.com", role_code="admin")
    await audit.record(
        session,
        audit.Entry(
            actor_user_id=operator.id,
            action="role.update",
            target_type="role",
            target_id="admin",
            ip_hash="x",
            payload={},
        ),
        refusal=None,
    )
    await session.commit()
    body = await open_one(client)
    await _leave_a_trail(client, auth(body))

    theirs = (await client.get("/api/audit", headers=auth(body))).json()
    signed_in = await login(client, operator)
    ours = (
        await client.get(
            "/api/audit", headers={"Authorization": f"Bearer {signed_in.json()['accessToken']}"}
        )
    ).json()

    assert theirs["total"] == 1
    assert {row["actor"]["email"] for row in theirs["items"]} == {VISITOR}
    assert ours["total"] == 1
    assert {row["actor"]["email"] for row in ours["items"]} == {"auditable@example.com"}


async def test_a_role_of_another_world_is_not_there_to_edit(
    client: AsyncClient, base_world: World, session: AsyncSession
) -> None:
    """The scoped lookup behind PUT and DELETE, which nothing exercised.

    A demonstration visitor holds `users.write` since this round, and `_refuse_if_system` guards
    only the four built-in roles — so an unscoped lookup by id would let a stranger rename or
    delete this installation's own custom roles.
    """
    ours = Role(code=f"analysts-{uuid.uuid4().hex[:6]}", name="Analysts")
    session.add(ours)
    await session.flush()
    await session.commit()
    body = await open_one(client)

    renamed = await client.put(
        f"/api/roles/{ours.id}", headers=auth(body), json={"name": "Mine now", "permissions": []}
    )
    deleted = await client.delete(f"/api/roles/{ours.id}", headers=auth(body))

    assert renamed.status_code == 404
    assert deleted.status_code == 404


async def test_using_a_sandbox_pushes_its_hour_out(client: AsyncClient, base_world: World) -> None:
    """The sliding TTL, which is the difference between an hour of use and an hour from opening.

    Nothing observed it: the extension happens in memory, inside the identity resolver, and no
    test made a request against a world whose expiry was about to pass.
    """
    body = await open_one(client)
    world = world_of(body["accessToken"])
    world.expires_at = datetime.now(UTC) + timedelta(minutes=1)

    answered = await client.get("/api/clock", headers=auth(body))

    assert answered.status_code == 200
    assert world.expires_at is not None
    assert world.expires_at > datetime.now(UTC) + timedelta(minutes=50)


async def test_the_ticker_is_what_collects_a_lapsed_sandbox(
    client: AsyncClient, base_world: World
) -> None:
    """Through the loop that actually runs it, not through a direct call.

    The reaper lives inside the tick loop so the two cannot race, and the accumulator that decides
    when it runs, the reap-before-tick order and the failure handler were all uncovered — the one
    reaping test called `reap` itself.
    """
    body = await open_one(client)
    world = world_of(body["accessToken"])
    world.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    collected: list[str] = []

    async def purge(world_id: str) -> None:
        collected.append(world_id)

    async with ticking(
        get_registry(),
        None,
        lambda: reap(get_registry(), purge),
        interval=timedelta(seconds=0),
        reap_every=timedelta(seconds=0),
    ):
        for _ in range(50):
            await asyncio.sleep(0)

    assert collected == [world.id]


async def test_an_operator_can_still_sign_in_at_an_address_a_sandbox_invented(
    client: AsyncClient, base_world: World, session: AsyncSession
) -> None:
    """THE COLLISION IS THE DOCUMENTED SETUP, NOT A HYPOTHETICAL.

    A sandbox names its visitor `you@example.com`, and the README's own first command creates an
    operator at exactly that address. Once uniqueness became two partial rules, both rows exist —
    and the login statement's `one_or_none()` sees two of them.

    What that produces is a 500 on the one page a stranger can reach, from the change that was
    made to keep things safer.
    """
    account = await create_account(session, email=VISITOR)
    await session.commit()
    await open_one(client)

    answered = await login(client, account)

    assert answered.status_code == 200, answered.text


async def test_a_sandbox_measures_its_life_on_the_clock_it_was_given(
    client: AsyncClient, base_world: World, session: AsyncSession
) -> None:
    """The `now` a request carries, not the registry's own reading of the wall clock.

    Everything else about a session — the pass's expiry, the rate-limit decision — is measured
    against the injected clock, and a sandbox measured against a different one disagrees with its
    own pass about when it ends.
    """
    moment = datetime(2030, 1, 1, tzinfo=UTC)

    sandbox = await open_sandbox(session, get_registry(), ip_hash="x", now=moment)

    assert sandbox.world.created_at == moment
    assert sandbox.world.expires_at == moment + sandboxes.SANDBOX_TTL
    assert sandbox.world.ceiling_at == moment + sandboxes.SANDBOX_CEILING


async def test_a_world_nobody_can_reach_is_not_left_standing(
    client: AsyncClient, base_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit is a thing that fails, and it happens after the world is in the registry.

    No token is minted, so the world is unreachable — and it would go on holding one of the slots
    under the ceiling and being ticked into a journal it has no sandbox row for.
    """

    async def refuse(self: object) -> None:
        raise RuntimeError("the commit failed")

    monkeypatch.setattr(AsyncSession, "commit", refuse)

    # The transport re-raises what the application did not handle, which is the honest shape of a
    # 500 here: the point is what the registry holds afterwards.
    with pytest.raises(RuntimeError):
        await client.post(SESSION)

    assert get_registry().sandboxes() == ()


async def test_a_purge_that_failed_is_tried_again(client: AsyncClient, base_world: World) -> None:
    """The reaper drops a world from the registry and then deletes its rows, in that order.

    So a purge that fails leaves rows behind AND a world `expired()` will never name again: its
    four thousand journal rows would wait for a restart that might be days away.
    """
    body = await open_one(client)
    world = world_of(body["accessToken"])
    world.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    attempts: list[str] = []

    async def refuses_once(world_id: str) -> None:
        attempts.append(world_id)
        if len(attempts) == 1:
            raise RuntimeError("the database was not there")

    with pytest.raises(RuntimeError):
        await reap(get_registry(), refuses_once)
    collected = await reap(get_registry(), refuses_once)

    assert attempts == [world.id, world.id]
    assert collected == 1
