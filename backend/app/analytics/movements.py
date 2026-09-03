"""What happened: the funnel, the flow of arrivals against departures, and the money.

All three read the event journal, which is the only record of the past — the engine holds a state,
not a history. So every number here counts events, and a count of expiries is not the size of the
EXPIRED row on the table. Each figure says which it is; that is what its caption is for.

The buckets are dense. A week with nothing in it is a zero rather than a gap, because the journal
is the complete record of its world: absence here is knowledge, not ignorance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

from sqlalchemy import BigInteger, ColumnElement, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EventJournal
from app.seed.catalogue import CURRENCY

CREATED: Final = "subscription.created"
ACTIVATED: Final = "subscription.activated"
RENEWED: Final = "subscription.renewed"
CANCELLED: Final = "subscription.cancelled"
EXPIRED: Final = "subscription.expired"
PAYMENT: Final = "payment.recorded"

CANCELLED_REASON: Final = "cancelled"
"""The `ExpiryReason` a cancelled subscription reaches when its paid period runs out.

It is the tail of a `subscription.cancelled` that has already been counted, so the flow figure
excludes it. A departure is counted once, at the moment it was decided.
"""

Grain = Literal["week", "month"]


@dataclass(frozen=True, slots=True)
class Funnel:
    """Of the people who arrived in the window, how many got further. Nested, so never rising."""

    arrived: int
    paid: int
    renewed: int
    started_a_trial: int
    """How many of the arrivals began on a plan that offers one.

    Not a stage. A plan with no trial days puts a new subscriber straight in front of the first
    payment, so this is a fact about how they arrived rather than a step they all take.
    """


@dataclass(frozen=True, slots=True)
class FlowPoint:
    starts_at: datetime
    joined: int
    left: int


@dataclass(frozen=True, slots=True)
class Flow:
    granularity: Grain
    points: tuple[FlowPoint, ...]


@dataclass(frozen=True, slots=True)
class RevenueMonth:
    starts_at: datetime
    amount: int


@dataclass(frozen=True, slots=True)
class Revenue:
    currency: str
    months: tuple[RevenueMonth, ...]


def floor_to(moment: datetime, granularity: Grain) -> datetime:
    """The start of the bucket a moment falls in, matching Postgres `date_trunc`.

    IN UTC FIRST, because that is the zone the SQL groups in. Floored in the caller's zone instead,
    a `from` carrying any other offset produced keys that matched none of Postgres's — and the
    figure answered 200 with a dense series of zeros over a journal full of events.
    """
    at = moment.astimezone(UTC)
    if granularity == "month":
        return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    midnight = at.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())


def next_bucket(start: datetime, granularity: Grain) -> datetime:
    """The bucket after this one. A month step lands on the first, whatever the month's length."""
    if granularity == "month":
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start + timedelta(days=7)


LAST_BUCKET: Final = datetime.max.replace(tzinfo=UTC) - timedelta(days=62)
"""Where the walk stops rather than stepping off the calendar, which used to be an OverflowError.

It truncates the series, and what is lost is provably zeros: no row can have occurred at an
instant later than this one. `PeriodParams` bounds the span, so reaching it needs a `to` inside
two months of the end of the calendar.
"""


def buckets(since: datetime, until: datetime, granularity: Grain) -> tuple[datetime, ...]:
    """Every bucket start from `since` up to `until`, so the answer has no holes in it."""
    starts: list[datetime] = []
    cursor = floor_to(since, granularity)
    while cursor < until and cursor < LAST_BUCKET:
        starts.append(cursor)
        cursor = next_bucket(cursor, granularity)
    return tuple(starts)


def _bucket_column(granularity: Grain) -> ColumnElement[datetime]:
    """The bucket a row falls in, computed in UTC rather than in the session's own time zone.

    `date_trunc` over a `timestamptz` reads the connection's `TimeZone`, so without this the week
    a row lands in would depend on who was asking.
    """
    return func.date_trunc(granularity, func.timezone("UTC", EventJournal.occurred_at))


def _by_start[T](rows: list[tuple[datetime, T]]) -> dict[datetime, T]:
    """Rows keyed by their bucket. `date_trunc` drops the zone, and this puts UTC back on."""
    return {start.replace(tzinfo=UTC): value for start, value in rows}


async def funnel(session: AsyncSession, world_id: str, since: datetime, until: datetime) -> Funnel:
    """Where the people who arrived in this window stopped.

    The later stages are deliberately not bounded by the window. A cohort is followed forward:
    somebody who arrived on the last day of it has not had time to renew, and cutting them off at
    `until` would report that as a loss.
    """
    arrivals = (
        select(
            EventJournal.user_id.label("user_id"),
            func.bool_or(EventJournal.payload_json["state"].astext == "trial").label("trialled"),
        )
        .where(
            EventJournal.world_id == world_id,
            EventJournal.type == CREATED,
            EventJournal.occurred_at >= since,
            EventJournal.occurred_at < until,
        )
        .group_by(EventJournal.user_id)
        .subquery()
    )

    def ever(event_type: str) -> ColumnElement[bool]:
        return exists(
            select(1).where(
                EventJournal.world_id == world_id,
                EventJournal.type == event_type,
                EventJournal.user_id == arrivals.c.user_id,
            )
        )

    paid, renewed = ever(ACTIVATED), ever(RENEWED)
    row = (
        await session.execute(
            select(
                func.count().label("arrived"),
                func.count().filter(arrivals.c.trialled).label("trialled"),
                func.count().filter(paid).label("paid"),
                # Nested inside `paid` rather than counted beside it, so the last bar cannot stand
                # taller than the one above it whatever the journal turns out to hold.
                func.count().filter(and_(paid, renewed)).label("renewed"),
            ).select_from(arrivals)
        )
    ).one()

    return Funnel(
        arrived=row.arrived, paid=row.paid, renewed=row.renewed, started_a_trial=row.trialled
    )


async def flow(
    session: AsyncSession, world_id: str, since: datetime, until: datetime, granularity: Grain
) -> Flow:
    """Arrivals against departures, one point per bucket."""
    since, until = since.astimezone(UTC), until.astimezone(UTC)
    departure = or_(
        EventJournal.type == CANCELLED,
        and_(
            EventJournal.type == EXPIRED,
            # `IS DISTINCT FROM`, so an expiry carrying no reason still counts as a departure. A
            # plain `!=` compares against NULL there and drops the row without saying so.
            EventJournal.payload_json["reason"].astext.is_distinct_from(CANCELLED_REASON),
        ),
    )
    column = _bucket_column(granularity)
    rows = (
        await session.execute(
            select(
                column.label("starts_at"),
                func.count().filter(EventJournal.type == CREATED).label("joined"),
                func.count().filter(departure).label("left"),
            )
            .where(
                EventJournal.world_id == world_id,
                EventJournal.type.in_([CREATED, CANCELLED, EXPIRED]),
                EventJournal.occurred_at >= since,
                EventJournal.occurred_at < until,
            )
            .group_by(column)
        )
    ).all()

    counted = _by_start([(row.starts_at, (row.joined, row.left)) for row in rows])
    return Flow(
        granularity=granularity,
        points=tuple(
            FlowPoint(
                starts_at=start,
                joined=counted.get(start, (0, 0))[0],
                left=counted.get(start, (0, 0))[1],
            )
            for start in buckets(since, until, granularity)
        ),
    )


async def revenue(session: AsyncSession, world_id: str, now: datetime, months: int) -> Revenue:
    """What arrived, by calendar month, ending with the month `now` falls in."""
    this_month = floor_to(now, "month")
    first = this_month
    for _ in range(months - 1):
        first = (first - timedelta(days=1)).replace(day=1)

    column = _bucket_column("month")
    rows = (
        await session.execute(
            select(
                column.label("starts_at"),
                func.sum(EventJournal.payload_json["amount"].astext.cast(BigInteger)).label(
                    "taken"
                ),
            )
            .where(
                EventJournal.world_id == world_id,
                EventJournal.type == PAYMENT,
                EventJournal.occurred_at >= first,
            )
            .group_by(column)
        )
    ).all()

    taken = _by_start([(row.starts_at, int(row.taken or 0)) for row in rows])
    return Revenue(
        currency=CURRENCY,
        months=tuple(
            RevenueMonth(starts_at=start, amount=taken.get(start, 0))
            for start in buckets(first, next_bucket(this_month, "month"), "month")
        ),
    )
