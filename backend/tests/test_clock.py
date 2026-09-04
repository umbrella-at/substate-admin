"""The time machine, from outside.

The world these tests wind is a real sandbox, opened through the door a visitor presses, because
winding is the one thing the demonstration exists for and the world it winds has to be one
somebody could actually be looking at.
"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from test_demo import auth, open_one

from app.worlds.registry import World
from support import Clock, bearer, create_account, envelope

CLOCK = "/api/clock"
ADVANCE = "/api/clock/advance"


async def test_a_fresh_world_reports_the_time_it_is(client: AsyncClient, base_world: World) -> None:
    """Model time, not a frozen clock. A demonstration whose clock stands still reads as a broken
    service: relative times stop updating and the visitor concludes the page is stale."""
    body = await open_one(client)

    reading = (await client.get(CLOCK, headers=auth(body))).json()

    assert reading["offsetSeconds"] == 0
    assert reading["isSandbox"] is True
    assert datetime.fromisoformat(reading["now"]) - datetime.now(UTC) < timedelta(seconds=5)


async def test_winding_moves_the_clock_by_what_was_asked(
    client: AsyncClient, base_world: World
) -> None:
    body = await open_one(client)

    wound = await client.post(ADVANCE, headers=auth(body), json={"days": 30})

    assert wound.status_code == 200
    assert wound.json()["offsetSeconds"] == int(timedelta(days=30).total_seconds())


async def test_the_clock_only_goes_forward(client: AsyncClient, base_world: World) -> None:
    """Refused at the edge of the API rather than inside the engine.

    `substate` compares a due date against now, so moving now backwards produces states it could
    never reach by itself — a renewed period nobody paid for, a grace ending before it began.
    """
    body = await open_one(client)

    for days in (0, -1, -30):
        refused = await client.post(ADVANCE, headers=auth(body), json={"days": days})
        assert refused.status_code == 422
        assert envelope(refused)["code"] == "VALIDATION_ERROR"


async def test_the_world_keeps_living_while_the_clock_moves(
    client: AsyncClient, base_world: World
) -> None:
    """THE DIFFERENCE BETWEEN A DEMONSTRATION AND A GRAVEYARD, ASSERTED ON THE TABLE ITSELF.

    A world that is only ticked has nobody paying in it: a month takes ACTIVE from 248 to 86 and
    EXPIRED from 45 to 211. Running the same modelled life instead keeps the shape a visitor came
    to look at, and the table is where they look at it.
    """
    body = await open_one(client)
    before = (await client.get("/api/subscribers", headers=auth(body))).json()

    await client.post(ADVANCE, headers=auth(body), json={"days": 30})
    after = (await client.get("/api/subscribers", headers=auth(body))).json()

    assert after["total"] > before["total"]
    states = (await client.get("/api/analytics/states", headers=auth(body))).json()
    standing = {entry["state"]: entry["count"] for entry in states["states"]}
    assert standing["active"] >= _count(before, "active")
    assert standing["expired"] < standing["active"]


async def test_the_figures_still_agree_with_the_table_after_the_clock_moves(
    client: AsyncClient, base_world: World
) -> None:
    """The rule the analytics round was built on, re-asserted where it was most at risk.

    The snapshot comes from the engine and the table comes from the engine, but the projection
    beside them is rewritten by the advance — and a figure read from before that write against a
    table read from after it is two numbers on one screen that do not match.
    """
    body = await open_one(client)
    await client.post(ADVANCE, headers=auth(body), json={"days": 45})

    states = (await client.get("/api/analytics/states", headers=auth(body))).json()
    table = (await client.get("/api/subscribers", headers=auth(body))).json()

    assert sum(entry["count"] for entry in states["states"]) == states["total"] == table["total"]


async def test_the_quiet_cohort_survives_the_clock(client: AsyncClient, base_world: World) -> None:
    """Decision 131, from the screen rather than from the seeder.

    With the projection frozen, a month forward puts every paying subscriber in this cohort: the
    figure meaning "paid for and unused" comes to mean "everybody", at the moment somebody pressed
    the button to see what changed.

    Both halves are asserted: the figure, and the list the chip opens, which must still be a slice
    rather than the whole table.
    """
    body = await open_one(client)
    await client.post(ADVANCE, headers=auth(body), json={"days": 30})

    quiet = (await client.get("/api/analytics/quiet", headers=auth(body))).json()
    listed = (await client.get("/api/subscribers?cohort=quiet", headers=auth(body))).json()
    table = (await client.get("/api/subscribers", headers=auth(body))).json()

    assert 0 < quiet["total"] < table["total"] / 2
    assert listed["total"] == quiet["total"]


async def test_winding_is_refused_to_whoever_may_not_drive(
    client: AsyncClient, base_world: World, session: AsyncSession, clock: Clock
) -> None:
    """`demo.control` is the one code that separates looking from changing what everybody in a
    world sees, and support holds every other write there is."""
    for role in ("viewer", "support"):
        account = await create_account(
            session, email=f"{role}-at-the-wheel@example.com", role_code=role
        )
        refused = await client.post(
            ADVANCE, headers=bearer(account, now=clock.now), json={"days": 1}
        )
        assert refused.status_code == 403
        assert envelope(refused)["code"] == "PERMISSION_DENIED"


async def test_reading_the_clock_takes_a_session_and_no_more(
    client: AsyncClient, base_world: World, session: AsyncSession, clock: Clock
) -> None:
    """Every screen renders times measured against this clock. A viewer who cannot read it
    renders them against the browser's, and a wound world then reads "just now" for everybody."""
    account = await create_account(session, email="viewer-reading@example.com", role_code="viewer")

    reading = await client.get(CLOCK, headers=bearer(account, now=clock.now))

    assert reading.status_code == 200
    assert reading.json()["isSandbox"] is False


def _count(page: dict[str, object], state: str) -> int:
    """How many rows on the first page carry one state. A floor, not a census — enough to say the
    population did not collapse."""
    items = page["items"]
    assert isinstance(items, list)
    return sum(1 for row in items if row["state"] == state)
