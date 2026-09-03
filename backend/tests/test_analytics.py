"""The five figures, and the one number that has to agree with the table.

THE SNAPSHOT AND THE TABLE ARE ONE CLAIM. A reader opens the states figure beside the subscriber
list and compares them, so `sum(states) == states.total == subscribers.total` is asserted here
rather than left to two pieces of code walking the engine the same way by habit.

It is asserted twice: on a freshly seeded world, and after the clock has been wound forward and
the engine ticked. The second run also asserts that the distribution MOVED, without which it
would pass against a world that had stopped — the shape of a check that proves nothing.

The three journal figures answer a different question and are not compared with the table. What
is asserted about them is the arithmetic that would otherwise be silently wrong: a funnel that
rises, a departure counted twice, and a period that returns holes instead of zeros.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from httpx import AsyncClient
from sqlalchemy import BigInteger, func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from substate import (
    State,
    SubscriptionActivated,
    SubscriptionCancelled,
    SubscriptionCreated,
    SubscriptionExpired,
    SubscriptionRenewed,
)

from app.analytics import movements
from app.models import EventJournal
from app.seed.catalogue import USERS_PROGRAM
from app.seed.run import HISTORY_DAYS, EventTally, seed_world
from app.subscribers.query import STATE_URGENCY
from app.worlds.journal import ProjectedSubscriber, write_events, write_projection
from app.worlds.registry import BASE_WORLD_ID, World, get_registry, reset_registry
from support import Account, Clock, bearer, create_account

FUNNEL: Final = "/api/analytics/funnel"
FLOW: Final = "/api/analytics/flow"
STATES: Final = "/api/analytics/states"
QUIET: Final = "/api/analytics/quiet"
REVENUE: Final = "/api/analytics/revenue"
SUBSCRIBERS: Final = "/api/subscribers"

OTHER_WORLD: Final = "a-world-of-its-own"
FUNNEL_WORLD: Final = "a-world-with-four-arrivals"
WINDOW_WORLD: Final = "a-world-either-side-of-a-window"
"""Where the hand-built journals go, so an assertion about four rows is not asking the seeder.

One world per scenario: they share a transaction, and a second test's rows landing in the first
test's counts is the kind of failure that looks like an arithmetic bug.
"""


@pytest.fixture
async def seeded(connection: AsyncConnection) -> AsyncIterator[World]:
    """The real base world in the registry the routes read, with its history in this transaction.

    Built the way `build_base_world` builds it rather than faked: a figure asserted against a
    hand-made world would agree with a hand-made idea of what the engine does.
    """
    reset_registry()
    tally = EventTally()
    world = get_registry().create(
        BASE_WORLD_ID,
        on_event=tally,
        offset=timedelta(days=-HISTORY_DAYS),
        default_program=USERS_PROGRAM,
    )
    report = await seed_world(world.engine, world.clock.advance, world.clock.now, tally=tally)
    await write_events(connection, BASE_WORLD_ID, world.sink.drain())
    await write_projection(
        connection,
        BASE_WORLD_ID,
        [
            ProjectedSubscriber(user_id=uid, display_name=name, last_active_at=seen)
            for uid, name, seen in report.subscribers_projection
        ],
    )
    world.sink.then = None
    world.seeded = True
    yield world
    reset_registry()


@pytest.fixture
async def operator(session: AsyncSession) -> Account:
    return await create_account(session, email="analyst@example.com", role_code="admin")


def _headers(operator: Account, clock: Clock) -> dict[str, str]:
    return bearer(operator, now=clock.now)


async def _json(client: AsyncClient, url: str, operator: Account, clock: Clock, **params: Any):
    response = await client.get(url, headers=_headers(operator, clock), params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_snapshot_totals_the_subscriber_table(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """The one number two screens show, asked of both."""
    snapshot = await _json(client, STATES, operator, clock)
    table = await _json(client, SUBSCRIBERS, operator, clock, pageSize=1)

    assert sum(entry["count"] for entry in snapshot["states"]) == snapshot["total"]
    assert snapshot["total"] == table["total"]
    assert snapshot["total"] > 0


async def test_the_snapshot_still_totals_the_table_after_the_world_moves(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """Wound forward and ticked, which is what the background task does on its own schedule.

    The second half is what makes the first mean anything: a world that had stopped would pass the
    comparison while proving that nothing moves.
    """
    before = await _json(client, STATES, operator, clock)

    seeded.clock.advance(timedelta(days=45))
    await seeded.engine.tick()

    after = await _json(client, STATES, operator, clock)
    table = await _json(client, SUBSCRIBERS, operator, clock, pageSize=1)

    assert sum(entry["count"] for entry in after["states"]) == after["total"] == table["total"]
    assert after["total"] == before["total"], "a tick moves subscriptions, it does not create them"
    assert after["states"] != before["states"], "forty-five days moved nobody; the world is stuck"


async def test_every_state_is_named_even_when_nobody_is_in_it(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """A state missing from the answer would draw as a gap, and a gap is not a zero."""
    snapshot = await _json(client, STATES, operator, clock)
    assert [entry["state"] for entry in snapshot["states"]] == [
        state.value for state in sorted(STATE_URGENCY, key=STATE_URGENCY.__getitem__)
    ]


async def test_the_snapshot_is_ordered_by_urgency_and_that_is_not_alphabetical(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """Asserting the domain order, and that the domain order is a claim at all.

    Without the second half this would pass against any ordering that happened to differ from the
    letters, which is what a test of "not alphabetical" actually says.
    """
    snapshot = await _json(client, STATES, operator, clock)
    named = [entry["state"] for entry in snapshot["states"]]

    assert named == [
        State.GRACE.value,
        State.TRIAL.value,
        State.ACTIVE.value,
        State.CANCELLED.value,
        State.EXPIRED.value,
    ]
    assert named != sorted(named)


async def test_the_quiet_bands_total_the_quiet_cohort(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """The figure and the chip are the same predicate, so they are the same number."""
    figure = await _json(client, QUIET, operator, clock)
    cohort = await _json(client, SUBSCRIBERS, operator, clock, pageSize=1, cohort="quiet")

    assert sum(band["count"] for band in figure["bands"]) == figure["total"]
    assert figure["total"] == cohort["total"]
    assert figure["total"] > 0, "a seeded world with nobody quiet makes this figure meaningless"


async def test_the_quiet_bands_start_where_the_cohort_starts(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """The first band opens at the cohort's own threshold, and the last one has no upper edge."""
    figure = await _json(client, QUIET, operator, clock)
    bands = figure["bands"]

    assert bands[0]["fromDays"] == 30
    assert [band["toDays"] for band in bands] == [60, 90, None]
    assert [band["fromDays"] for band in bands[1:]] == [60, 90]


async def test_the_funnel_never_rises(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """Each stage is a subset of the one above it, so the bars can only shorten.

    The trial count is beside the stages rather than among them: a plan with no trial days puts a
    new subscriber straight in front of the first payment, and on this catalogue some do.
    """
    figure = await _json(client, FUNNEL, operator, clock, **{"from": _long_ago(), "to": _now()})
    counts = [stage["count"] for stage in figure["stages"]]

    assert [stage["stage"] for stage in figure["stages"]] == ["arrived", "paid", "renewed"]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] > 0
    assert 0 < figure["startedATrial"] < counts[0], "every arrival trialled, or none did"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _long_ago() -> str:
    return (datetime.now(UTC) - timedelta(days=HISTORY_DAYS * 2)).isoformat()


async def test_the_funnel_counts_a_stage_only_inside_the_one_above_it(
    session: AsyncSession, connection: AsyncConnection
) -> None:
    """Four arrivals, hand-built, and the fourth is the one that matters.

    `late` renewed without ever having activated, which the engine does not do — but the funnel's
    nesting is what makes the bars readable, and a shape that only holds because the data happens
    to be tidy is not a shape.
    """
    at = datetime(2026, 4, 1, 10, tzinfo=UTC)
    await write_events(
        connection,
        FUNNEL_WORLD,
        [
            SubscriptionCreated("all-three", at, "monthly", State.TRIAL),
            SubscriptionActivated("all-three", at, "monthly", at + timedelta(days=30)),
            SubscriptionRenewed("all-three", at, "monthly", at + timedelta(days=60)),
            SubscriptionCreated("paid-once", at, "monthly", State.TRIAL),
            SubscriptionActivated("paid-once", at, "monthly", at + timedelta(days=30)),
            SubscriptionCreated("no-trial", at, "weekly", State.EXPIRED),
            SubscriptionCreated("late", at, "monthly", State.TRIAL),
            SubscriptionRenewed("late", at, "monthly", at + timedelta(days=60)),
        ],
    )

    found = await movements.funnel(
        session, FUNNEL_WORLD, at - timedelta(days=1), at + timedelta(days=1)
    )
    assert (found.arrived, found.paid, found.renewed) == (4, 2, 1)
    assert found.started_a_trial == 3


async def test_the_window_bounds_the_arrivals_and_nothing_after_them(
    session: AsyncSession, connection: AsyncConnection
) -> None:
    """A cohort is followed forward. Cutting the later stages at `to` would report a loss.

    `early` arrived before the window and is not in it at all; `slow` arrived inside it and paid
    afterwards, which is somebody the funnel is supposed to keep.
    """
    at = datetime(2026, 6, 10, 12, tzinfo=UTC)
    await write_events(
        connection,
        WINDOW_WORLD,
        [
            SubscriptionCreated("early", at - timedelta(days=40), "monthly", State.TRIAL),
            SubscriptionActivated("early", at, "monthly", at + timedelta(days=30)),
            SubscriptionCreated("slow", at, "monthly", State.TRIAL),
            SubscriptionActivated("slow", at + timedelta(days=40), "monthly", at),
        ],
    )

    found = await movements.funnel(
        session, WINDOW_WORLD, at - timedelta(days=1), at + timedelta(days=1)
    )
    assert (found.arrived, found.paid) == (1, 1)


async def test_a_departure_is_counted_once(
    session: AsyncSession, connection: AsyncConnection
) -> None:
    """A cancellation and the expiry that follows it are one person leaving, not two.

    `substate` gives that expiry the reason `cancelled`, which is what the flow figure excludes.
    Counting both would inflate the outflow line by every cancellation the world has ever had.
    """
    at = datetime(2026, 3, 4, 12, tzinfo=UTC)
    await write_events(
        connection,
        OTHER_WORLD,
        [
            SubscriptionCancelled("sub-1", at, access_until=at + timedelta(days=20)),
            SubscriptionExpired("sub-1", at + timedelta(days=20), reason="cancelled"),
            SubscriptionExpired("sub-2", at, reason="grace_ended"),
        ],
    )

    found = await movements.flow(
        session, OTHER_WORLD, at - timedelta(days=7), at + timedelta(days=60), "month"
    )
    assert sum(point.left for point in found.points) == 2


async def test_an_expiry_with_no_reason_is_still_a_departure(
    session: AsyncSession, connection: AsyncConnection
) -> None:
    """`IS DISTINCT FROM`, not `!=`: comparing NULL with a string drops the row silently."""
    at = datetime(2026, 5, 6, 9, tzinfo=UTC)
    await write_events(
        connection, OTHER_WORLD, [SubscriptionCreated("sub-3", at, "monthly", State.TRIAL)]
    )
    await connection.execute(
        EventJournal.__table__.insert().values(
            world_id=OTHER_WORLD,
            type=movements.EXPIRED,
            user_id="sub-4",
            occurred_at=at,
            payload_json={},
        )
    )

    found = await movements.flow(
        session, OTHER_WORLD, at - timedelta(days=1), at + timedelta(days=1), "week"
    )
    assert sum(point.left for point in found.points) == 1


async def test_a_period_with_nothing_in_it_is_zeros_rather_than_holes(
    session: AsyncSession,
) -> None:
    """Absence in the journal is knowledge: that world had no events that week."""
    since = datetime(2020, 1, 6, tzinfo=UTC)
    found = await movements.flow(session, OTHER_WORLD, since, since + timedelta(days=28), "week")

    assert [point.starts_at for point in found.points] == [
        since + timedelta(days=7 * step) for step in range(4)
    ]
    assert all(point.joined == 0 and point.left == 0 for point in found.points)


async def test_revenue_covers_every_month_it_was_asked_for(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """Twelve bars over a world nine months old. The two empty ones are zeros, not missing bars."""
    figure = await _json(client, REVENUE, operator, clock, months=12)
    months = figure["months"]

    assert len(months) == 12
    assert [month["startsAt"] for month in months] == sorted(month["startsAt"] for month in months)
    assert all(month["amount"] >= 0 for month in months)
    assert sum(month["amount"] for month in months) > 0
    assert figure["currency"] == "USD"


async def test_revenue_is_the_sum_of_the_payments_recorded(
    session: AsyncSession, seeded: World, connection: AsyncConnection
) -> None:
    """Cross-checked against the rows themselves, so the grouping cannot quietly drop a month."""
    now = seeded.clock.now()
    figure = await movements.revenue(session, BASE_WORLD_ID, now, 24)
    recorded = (
        await session.execute(
            select(func.sum(EventJournal.payload_json["amount"].astext.cast(BigInteger)))
            .where(EventJournal.world_id == BASE_WORLD_ID)
            .where(EventJournal.type == movements.PAYMENT)
        )
    ).scalar_one()

    assert sum(month.amount for month in figure.months) == int(recorded)


@pytest.mark.parametrize(
    ("moment", "granularity", "expected"),
    [
        (datetime(2026, 3, 4, 23, 59, tzinfo=UTC), "week", datetime(2026, 3, 2, tzinfo=UTC)),
        (datetime(2026, 3, 2, 0, 0, tzinfo=UTC), "week", datetime(2026, 3, 2, tzinfo=UTC)),
        (datetime(2026, 3, 31, 18, tzinfo=UTC), "month", datetime(2026, 3, 1, tzinfo=UTC)),
    ],
)
def test_a_moment_floors_to_the_bucket_postgres_would_put_it_in(
    moment: datetime, granularity: movements.Grain, expected: datetime
) -> None:
    assert movements.floor_to(moment, granularity) == expected


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
        (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)),
        (datetime(2026, 12, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    ],
)
def test_a_month_step_lands_on_the_first_whatever_the_month_is_long(
    start: datetime, expected: datetime
) -> None:
    """February and a year boundary, because both are where day arithmetic goes wrong."""
    assert movements.next_bucket(start, "month") == expected
