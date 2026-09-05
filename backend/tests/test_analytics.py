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
from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise
from typing import Any, Final, cast

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
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

from app.analytics import movements, standing
from app.models import EventJournal
from app.schemas import FlowParams, PeriodParams, RevenueParams
from app.seed.catalogue import PLANS, USERS_PROGRAM
from app.seed.run import HISTORY_DAYS, EventTally, seed_world
from app.subscribers.query import STATE_URGENCY
from app.worlds.journal import ProjectedSubscriber, write_events, write_projection
from app.worlds.registry import BASE_WORLD_ID, World, get_registry, reset_registry
from support import Account, Clock, bearer, create_account, envelope

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
    report, _ = await seed_world(world.engine, world.clock.advance, world.clock.now, tally=tally)
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


async def test_the_flow_route_answers_a_dense_week_by_week_series(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """The endpoint nothing called. Its arithmetic had three defects and no test could see them."""
    figure = await _json(
        client, FLOW, operator, clock, **{"from": _long_ago(), "to": _now(), "granularity": "week"}
    )
    starts = [datetime.fromisoformat(point["startsAt"]) for point in figure["points"]]

    assert figure["granularity"] == "week"
    assert len(starts) > 4
    assert all(later - earlier == timedelta(days=7) for earlier, later in pairwise(starts))
    assert all(start.weekday() == 0 for start in starts), "date_trunc('week') runs Monday to Monday"
    assert sum(point["joined"] for point in figure["points"]) > 0


async def test_the_same_instants_answer_the_same_whatever_offset_they_arrive_in(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """A `from` in another zone was floored in that zone while Postgres grouped in UTC.

    The keys then matched nothing and the figure answered 200 with a dense series of zeros over a
    journal full of events — the most confident way this endpoint could be wrong.
    """
    until = datetime.now(UTC)
    since = until - timedelta(days=60)
    elsewhere = timezone(timedelta(hours=3))

    utc = await _json(
        client, FLOW, operator, clock, **{"from": since.isoformat(), "to": until.isoformat()}
    )
    shifted = await _json(
        client,
        FLOW,
        operator,
        clock,
        **{
            "from": since.astimezone(elsewhere).isoformat(),
            "to": until.astimezone(elsewhere).isoformat(),
        },
    )

    assert utc["points"] == shifted["points"]
    assert sum(point["joined"] for point in utc["points"]) > 0, (
        "a period with nothing in it proves nothing"
    )


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"from": "2026-06-01T00:00:00"}, "from"),
        ({"to": "2026-06-01T12:00:00"}, "to"),
        ({"from": "2000-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"}, None),
        ({"from": "2026-01-01T00:00:00Z", "to": "2025-01-01T00:00:00Z"}, None),
    ],
)
async def test_a_period_this_endpoint_cannot_answer_is_refused_rather_than_guessed(
    client: AsyncClient,
    seeded: World,
    operator: Account,
    clock: Clock,
    params: dict[str, str],
    field: str | None,
) -> None:
    """Naive, backwards, or longer than the bucket walk can carry.

    A naive value has no instant; twenty-six years of weeks is a quarter of a million marks on a
    plot. Both used to be a 200 or a 500 rather than a sentence naming the parameter.
    """
    response = await client.get(FLOW, headers=_headers(operator, clock), params=params)

    assert response.status_code == 422, response.text
    assert envelope(response)["code"] == "VALIDATION_ERROR"


async def test_a_bucket_walk_stops_rather_than_stepping_off_the_calendar() -> None:
    """`PeriodParams` bounds the span, so no route reaches this — a caller in-process can, and the
    step past `datetime.max` used to be an OverflowError rather than the end of a list."""
    walked = movements.buckets(
        datetime(9999, 1, 1, tzinfo=UTC), datetime(9999, 12, 31, tzinfo=UTC), "week"
    )
    assert walked, "the walk must still produce the buckets it can"
    assert all(start.weekday() == 0 for start in walked)
    assert walked[-1] < datetime.max.replace(tzinfo=UTC) - timedelta(days=7)


@pytest.fixture
async def three_quiet_subscribers() -> AsyncIterator[tuple[World, standing.Projection, datetime]]:
    """A world of exactly three, silent for 40, 60 and 200 days at one fixed moment.

    Hand-built rather than seeded: the band arithmetic is the half of that figure a reader looks
    at, and the seeder's population cannot pin a boundary.
    """
    reset_registry()
    world = get_registry().create("a-world-of-three")
    for plan in PLANS:
        world.engine.register_plan(plan)
    for user_id in ("quiet-40", "quiet-60", "quiet-200"):
        await world.engine.subscribe(user_id, "monthly")

    now = world.clock.now()
    projection: standing.Projection = {
        "quiet-40": ("Forty", now - timedelta(days=40)),
        "quiet-60": ("Sixty", now - timedelta(days=60)),
        "quiet-200": ("Two hundred", now - timedelta(days=200)),
    }
    yield world, projection, now
    reset_registry()


async def test_a_subscriber_lands_in_the_band_their_silence_is_long_enough_for(
    three_quiet_subscribers: tuple[World, standing.Projection, datetime],
) -> None:
    """One in each band, and the middle one sits exactly on an edge.

    Sixty days belongs to 60-90 rather than to 30-60: a band is closed at its lower edge, and
    that is the only place the arithmetic can be off by one.
    """
    world, projection, now = three_quiet_subscribers
    found = await standing.quiet(world, projection, now=now)

    assert [band.count for band in found.bands] == [1, 1, 1]
    assert found.total == 3
    assert [(band.from_days, band.to_days) for band in found.bands] == [
        (30, 60),
        (60, 90),
        (90, None),
    ]


async def test_a_subscriber_seen_within_the_month_is_in_no_band_at_all(
    three_quiet_subscribers: tuple[World, standing.Projection, datetime],
) -> None:
    """The cohort opens at thirty days, so the figure has to be empty below it."""
    world, _, now = three_quiet_subscribers
    fresh: standing.Projection = {
        user_id: (user_id, now - timedelta(days=29)) for user_id in world.subscribers
    }
    found = await standing.quiet(world, fresh, now=now)

    assert [band.count for band in found.bands] == [0, 0, 0]
    assert found.total == 0


async def test_the_snapshot_names_a_state_nobody_is_in(
    three_quiet_subscribers: tuple[World, standing.Projection, datetime],
) -> None:
    """Three subscribers on one plan occupy one state; the other four are zeros, not absences."""
    world, _, _ = three_quiet_subscribers
    found = await standing.snapshot(world)

    assert len(found.states) == 5
    assert found.total == 3
    assert sorted(entry.count for entry in found.states) == [0, 0, 0, 0, 3]


async def test_the_quiet_figure_and_the_cohort_still_agree_after_the_world_moves(
    client: AsyncClient, seeded: World, operator: Account, clock: Clock
) -> None:
    """The figure asked the world's clock and the table asked the wall's.

    They agreed while the offset was zero, which is every world this round ships — and stopped
    the moment one was wound forward, which is what the next round is for.
    """
    seeded.clock.advance(timedelta(days=45))
    await seeded.engine.tick()

    figure = await _json(client, QUIET, operator, clock)
    cohort = await _json(client, SUBSCRIBERS, operator, clock, pageSize=1, cohort="quiet")

    assert figure["total"] == cohort["total"]
    assert sum(band["count"] for band in figure["bands"]) == figure["total"]


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
    ("granularity", "expected"),
    [("week", datetime(2026, 2, 23, tzinfo=UTC)), ("month", datetime(2026, 2, 1, tzinfo=UTC))],
)
def test_a_moment_floors_in_utc_whatever_zone_it_arrived_in(
    granularity: movements.Grain, expected: datetime
) -> None:
    """A Monday the first of March in Moscow is a Sunday the first in UTC, and Postgres groups in
    UTC — so the instant is converted before it is truncated, not after."""
    elsewhere = timezone(timedelta(hours=3))
    monday_there = datetime(2026, 3, 2, 1, tzinfo=elsewhere)
    first_there = datetime(2026, 3, 1, 1, tzinfo=elsewhere)

    at = monday_there if granularity == "week" else first_there
    assert movements.floor_to(at, granularity) == expected


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


class TestTheFigureRefusesWhatItsWrapperRefuses:
    """`PeriodParams`, `FlowParams` and `RevenueParams` reject these before a handler is entered.

    Behind them the same values used to be answered: a naive end floored in the host's zone, a
    backwards period as an empty series, an unknown grain walked by weeks while Postgres grouped
    by days, and a window of no months quietly served as one.
    """

    async def test_a_period_needs_an_instant_at_both_ends(self, session: AsyncSession) -> None:
        aware = datetime(2026, 2, 1, tzinfo=UTC)
        naive = datetime(2026, 1, 1)
        with pytest.raises(ValidationError):
            PeriodParams(**{"from": naive, "to": aware})
        with pytest.raises(ValueError, match="time zone"):
            await movements.flow(session, OTHER_WORLD, naive, aware, "week")
        with pytest.raises(ValueError, match="time zone"):
            await movements.flow(session, OTHER_WORLD, aware, naive, "week")

    async def test_a_period_runs_forwards(self, session: AsyncSession) -> None:
        since = datetime(2026, 2, 1, tzinfo=UTC)
        with pytest.raises(ValidationError):
            PeriodParams(**{"from": since, "to": since - timedelta(days=1)})
        with pytest.raises(ValueError, match="forwards"):
            await movements.flow(session, OTHER_WORLD, since, since - timedelta(days=1), "week")
        with pytest.raises(ValueError, match="forwards"):
            await movements.flow(session, OTHER_WORLD, since, since, "week")

    @pytest.mark.parametrize("granularity", ["day", "quarter", "year", ""])
    async def test_a_grain_this_cannot_walk_is_refused(
        self, session: AsyncSession, granularity: str
    ) -> None:
        """`date_trunc` accepts all of these, and the walk here would step by weeks regardless —
        so every bucket that did not land on a Monday came back zero."""
        with pytest.raises(ValidationError):
            FlowParams(granularity=granularity)
        at = datetime(2026, 2, 3, tzinfo=UTC)
        with pytest.raises(ValueError, match="weeks or months"):
            movements.floor_to(at, cast(Any, granularity))
        with pytest.raises(ValueError, match="weeks or months"):
            movements.next_bucket(at, cast(Any, granularity))

    @pytest.mark.parametrize("months", [0, -5])
    async def test_a_window_of_no_months_is_refused(
        self, session: AsyncSession, months: int
    ) -> None:
        """The loop's range was empty, so it returned the current month and called that success."""
        with pytest.raises(ValidationError):
            RevenueParams(months=months)
        with pytest.raises(ValueError, match="at least one month"):
            await movements.revenue(session, BASE_WORLD_ID, datetime.now(UTC), months)

    @pytest.mark.parametrize("granularity", ["week", "month"])
    async def test_the_grains_it_does_walk_are_served(self, granularity: str) -> None:
        at = datetime(2026, 2, 3, tzinfo=UTC)
        assert movements.next_bucket(movements.floor_to(at, granularity), granularity) > at


async def test_the_quiet_figure_dates_the_silence_by_the_worlds_clock_by_default(
    three_quiet_subscribers: tuple[World, standing.Projection, datetime],
) -> None:
    """The route reads the moment off the world, so the default is for the callers nobody watches.

    It used to be `datetime.now(UTC)`. Wound 200 days on, the three silences are 240, 260 and 400
    days long and belong in one band; the wall clock still reads 40, 60 and 200 and spreads them
    across three. Both are well-formed answers and only one is about this world.
    """
    world, projection, wall = three_quiet_subscribers
    world.clock.advance(timedelta(days=200))

    by_default = await standing.quiet(world, projection)
    by_the_wall = await standing.quiet(world, projection, now=wall)

    assert [band.count for band in by_default.bands] == [0, 0, 3]
    assert [band.count for band in by_the_wall.bands] == [1, 1, 1]
