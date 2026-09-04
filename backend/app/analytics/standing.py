"""What is true right now: the state snapshot, and how long the quiet have been quiet.

Both read the engine, because a current state has no other source, and both reach it through
`live_subscriptions`. That is what makes the snapshot's total the table's total by construction
rather than by two pieces of code happening to agree.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from substate import State

from app.subscribers.projection import Projection
from app.subscribers.query import (
    QUIET_AFTER,
    STATE_URGENCY,
    Cohort,
    build_row,
    in_cohort,
    live_subscriptions,
)
from app.worlds.registry import World

QUIET_BANDS: Final[tuple[timedelta, ...]] = (timedelta(days=60), timedelta(days=90))
"""Where the tail is cut, after `QUIET_AFTER` has opened it.

Two months is a subscription that has been paid for without being used; three is somebody who has
almost certainly gone. The figure exists to tell those apart, which a single count cannot.
"""


@dataclass(frozen=True, slots=True)
class StateCount:
    state: State
    count: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Every subscription the engine holds, counted by the state it is in."""

    states: tuple[StateCount, ...]
    total: int


@dataclass(frozen=True, slots=True)
class Band:
    """One stretch of silence. `to_days` is None for the last band, which has no upper edge."""

    from_days: int
    to_days: int | None
    count: int


@dataclass(frozen=True, slots=True)
class Quiet:
    bands: tuple[Band, ...]
    total: int


async def snapshot(world: World) -> Snapshot:
    """The five states and how many subscriptions are in each.

    Every state appears, including the ones nobody is in: a state missing from the answer would
    draw as a gap in the figure, and a gap means "not measured" where zero is the measurement.
    """
    counts: Counter[State] = Counter()
    async for subscription in live_subscriptions(world):
        counts[subscription.state] += 1

    ordered = sorted(STATE_URGENCY, key=STATE_URGENCY.__getitem__)
    return Snapshot(
        states=tuple(StateCount(state=state, count=counts[state]) for state in ordered),
        total=sum(counts.values()),
    )


async def quiet(world: World, projection: Projection, *, now: datetime | None = None) -> Quiet:
    """The quiet cohort, split by how long the silence has run.

    The membership test is the table's own, so the total here is the number of rows the cohort
    chip returns. A second predicate would be a second definition of "quiet".
    """
    moment = now if now is not None else datetime.now(UTC)
    edges = (QUIET_AFTER, *QUIET_BANDS)
    counts = [0] * len(edges)

    async for subscription in live_subscriptions(world):
        user_id = subscription.user_id
        display_name, last_active_at = projection.get(user_id, (user_id, None))
        row = build_row(subscription, display_name, last_active_at)
        # The None check is the cohort's own condition, restated where the subtraction below needs
        # it: never having turned up is not a length of silence, it is an unknown one.
        if row.last_active_at is None or not in_cohort(row, Cohort.QUIET, moment):
            continue
        silence = moment - row.last_active_at
        counts[sum(1 for edge in edges if silence >= edge) - 1] += 1

    return Quiet(
        bands=tuple(
            Band(
                from_days=edge.days,
                to_days=edges[index + 1].days if index + 1 < len(edges) else None,
                count=count,
            )
            for index, (edge, count) in enumerate(zip(edges, counts, strict=True))
        ),
        total=sum(counts),
    )
