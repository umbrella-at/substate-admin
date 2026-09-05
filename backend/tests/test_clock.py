"""The time machine, from outside.

The world these tests wind is a real sandbox, opened through the door a visitor presses, because
winding is the one thing the demonstration exists for and the world it winds has to be one
somebody could actually be looking at.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from test_demo import auth, open_one, world_of

from app.routers import clock as clock_module
from app.routers.clock import MAX_WIND
from app.seed.run import SeedReport
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

    # Bounded on both sides. `now` is the field the endpoint is named for, and a one-sided
    # comparison passes for a moment a decade in the past as happily as for the right one.
    assert abs(datetime.fromisoformat(reading["now"]) - datetime.now(UTC)) < timedelta(seconds=5)


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
    was = await _states(client, auth(body))

    await client.post(ADVANCE, headers=auth(body), json={"days": 30})
    after = (await client.get("/api/subscribers", headers=auth(body))).json()

    assert after["total"] > before["total"]
    standing = await _states(client, auth(body))

    # Against the world's own census before the press, not against one page of it: a page holds
    # twenty-five rows, and "86 >= 16" is satisfied by the very collapse this test is named after.
    assert standing["active"] >= was["active"]
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


async def _states(client: AsyncClient, headers: dict[str, str]) -> dict[str, int]:
    """The whole world's census, which is what the figure reports and what the assertion needs.

    A page of the table is not one: it holds twenty-five rows however large the world is, so a
    comparison against it survives the population collapsing by two thirds.
    """
    answer = (await client.get("/api/analytics/states", headers=headers)).json()
    return {entry["state"]: entry["count"] for entry in answer["states"]}


async def test_a_world_cannot_be_wound_without_end(client: AsyncClient, base_world: World) -> None:
    """THE VALVE THE CEILING DOES NOT COVER, WHICH A MEASUREMENT FOUND RATHER THAN A REVIEW.

    The ceiling bounds how many sandboxes stand and the rate limit bounds how fast they are built.
    Neither bounds how large one of them grows.

    A year of winding takes a world from 3773 journal rows to 31026, at 1.8 seconds of the only
    CPU per press — for as long as somebody keeps pressing.
    """
    body = await open_one(client)

    spent = await client.post(ADVANCE, headers=auth(body), json={"days": MAX_WIND.days})
    refused = await client.post(ADVANCE, headers=auth(body), json={"days": 1})

    assert spent.status_code == 200
    assert refused.status_code == 409
    envelope_ = envelope(refused)
    # Its own code and 409: the body is well formed, and the world is what will not have it.
    assert envelope_["code"] == "WORLD_FULLY_WOUND"
    assert envelope_["field"] is None
    assert "0 of its 365 days are left" in envelope_["message"]


async def test_what_is_left_is_what_the_refusal_says(
    client: AsyncClient, base_world: World
) -> None:
    """A visitor who has spent most of the allowance is told how much of it is left, not merely
    that they may not. The number is the only thing that lets them choose a smaller step."""
    body = await open_one(client)
    await client.post(ADVANCE, headers=auth(body), json={"days": 300})

    refused = await client.post(ADVANCE, headers=auth(body), json={"days": 100})

    assert refused.status_code == 409
    assert "65 of its 365 days are left" in envelope(refused)["message"]
    # And said before the press, too: the control can offer what the world will accept.
    reading = (await client.get(CLOCK, headers=auth(body))).json()
    assert reading["daysLeft"] == 65


async def test_a_second_press_never_enters_the_world_the_first_is_in(
    client: AsyncClient, base_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MEASURED, NOT IMAGINED: two overlapping advances used to cost a month of history.

    `flush_world` drains the sink before it writes, so a rollback loses those events for good.

    The second advance's projection rewrite hit a duplicate key — its DELETE was taken before the
    first committed — and the world moved on with a hole in its journal, which the flow and
    revenue figures read as flat months beside a table that had grown.

    Asserted on the world rather than by racing a second request: this suite gives every test one
    connection with a savepoint on it, so two requests at once corrupt the savepoint long before
    they reach the defect — and a cancelled one goes on logging into a closed capture.
    """
    body = await open_one(client)
    world = world_of(body["accessToken"])
    started = asyncio.Event()
    held = asyncio.Event()
    living = clock_module.carry_on

    async def parked(*args: object, **kwargs: object) -> SeedReport:
        started.set()
        await held.wait()
        return await living(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(clock_module, "carry_on", parked)
    first = asyncio.create_task(client.post(ADVANCE, headers=auth(body), json={"days": 1}))
    await started.wait()

    assert world.lock.locked(), "the press did not hold the world it was changing"

    held.set()
    assert (await first).status_code == 200
    assert not world.lock.locked()


async def test_no_chip_comes_back_empty_after_the_clock_is_pressed(
    client: AsyncClient, base_world: World
) -> None:
    """Decision 95 under the feature that can break it: every chip returns a list to work with.

    The clock is the one control that can empty one. A world that is only ticked loses its
    payers, and a projection that stands still puts every payer in the quiet cohort — so this
    asserts the whole row of chips, not the one that failed last.

    Measured over thirty presses of Day: none of the four came back empty on any of them.
    """
    body = await open_one(client)
    await client.post(ADVANCE, headers=auth(body), json={"days": 30})

    for cohort in ("quiet", "trial-ending", "cancelled-losing-access"):
        listed = (
            await client.get(f"/api/subscribers?cohort={cohort}&pageSize=1", headers=auth(body))
        ).json()
        assert listed["total"] > 0, f"the {cohort} chip was empty after a press"

    standing = await _states(client, auth(body))
    for state, held in standing.items():
        assert held > 0, f"the {state} chip was empty after a press"
