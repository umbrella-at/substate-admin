"""The subscriber table, assembled from two sources that must not be confused.

State, plan, dates and promo code come from `substate` and are asked of it every time; the
display name and `last_active_at` come from the projection. Nothing caches the first into the
second — a projection answering "what state is this" would be a second answer to a settled question.

Filtering and sorting happen here rather than in Postgres because the subscriptions are here. The
shape of the answer survives the move to SQLAlchemy storage, which is what the world key on
everything is for.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from substate import State, Subscription

from app.worlds.registry import World

QUIET_AFTER: Final = timedelta(days=30)
"""An active subscription whose owner has not turned up in a month.

Deliberately not the length of a billing period. If the threshold matched the period, everybody
who simply had not signed in since their last renewal would land in the cohort, and "went quiet"
would come to mean "pays monthly" — true of most of the table and therefore useless.
"""

LOSING_ACCESS_WITHIN: Final = timedelta(days=7)
"""How soon a cancelled subscriber has to be losing access to be worth a call today.

A week, and the number is measured rather than chosen: over 120 landing days the window holds 1 to
12 people and is never empty, where three days would be empty on six of those days.

Fourteen and thirty are never empty either and hold more — but "this week" is the question somebody
actually acts on, and a list of thirty is a report rather than a call sheet.
"""

MAX_PAGE_SIZE: Final = 100
DEFAULT_PAGE_SIZE: Final = 25


class Cohort(StrEnum):
    """Lists to act on, not numbers to look at.

    Each one answers a question somebody has already asked themselves: who is about to lapse, who
    is paying without turning up, who cancelled but is still inside a period they paid for.

    Every one is a question the state filter cannot ask, and that is the entry condition: a
    cohort whose predicate is `row.state is X` is a second vocabulary for `?state=x`.

    THE THIRD ONE FAILED THAT CONDITION WITHOUT LOOKING LIKE IT, AND IT TOOK A MEASUREMENT TO SEE.

    It asked for a cancelled subscription still inside the period it was paid for — which reads
    like a narrowing and is not one. The engine moves a cancelled subscription to EXPIRED at the
    moment its period runs out, so `state is CANCELLED` already means the period is live.

    Measured: over nine landing days and after winding a world 30, 90 and 180 days, not one
    cancelled row was ever past its period. The chip returned exactly what `?state=cancelled`
    returned, which is what happened to `in-grace` before it and why that one was removed.
    """

    QUIET = "quiet"
    TRIAL_ENDING = "trial-ending"
    CANCELLED_LOSING_ACCESS = "cancelled-losing-access"


class SortField(StrEnum):
    """What the table can be ordered by.

    `planId` is deliberately absent. A plan is a category, not a quantity: putting the five in any
    order at all would be inventing one, and alphabetical would be the letters of their names
    rather than anything about the plans. Categories are filtered, not sorted.

    `state` is the exception, because states DO have an order — see `STATE_URGENCY`.

    `accessUntil` and `expiresAt` are both here and are not the same question. The table sorts by
    the first, because that is the column it draws; the second orders by the paid period alone and
    is what a report about billing would want.
    """

    USER_ID = "userId"
    DISPLAY_NAME = "displayName"
    STATE = "state"
    ACCESS_UNTIL = "accessUntil"
    EXPIRES_AT = "expiresAt"
    LAST_ACTIVE_AT = "lastActiveAt"


STATE_URGENCY: Final[dict[State, int]] = {
    State.GRACE: 0,
    State.TRIAL: 1,
    State.ACTIVE: 2,
    State.CANCELLED: 3,
    State.EXPIRED: 4,
}
"""The order sorting by state produces. A claim about the work, not about the words.

Ordered by what needs doing today, not by the letters: a failed payment runs out today, a trial
is the only window there is, and an expiry is already history. A sixth state takes the rank its
urgency earns, not the next number.

It lives on this side because sorting is server-side, so the order is part of what the API
promises rather than a rendering choice — a second client would otherwise invent its own.
"""


@dataclass(frozen=True, slots=True)
class SubscriberRow:
    """One row of the table, from both sources."""

    user_id: str
    display_name: str
    state: State
    plan_id: str
    access_until: datetime | None
    """When access ends in the state this row is in, whichever field that happens to be.

    `substate` computes it: a trial ends at `trial_ends_at`, a grace at `grace_ends_at`, anything
    else at `expires_at`. The three are kept alongside rather than replaced — they are different
    questions, and one date column has to show the one that is true right now.
    """
    expires_at: datetime | None
    trial_ends_at: datetime | None
    grace_ends_at: datetime | None
    cancelled_at: datetime | None
    """When somebody stopped the renewals. Filtered to CANCELLED like the two boundaries above:
    the engine keeps it after a restart, and a cancellation date on an ACTIVE row is history
    presented as a fact about now."""
    pending_plan_id: str | None
    """The plan the next payment will buy, if a change is waiting. Not filtered by state — it is
    None unless a change was scheduled, and `_begin_cycle` wipes it when a cycle restarts."""
    last_active_at: datetime | None
    promo_code: str | None
    referrer_id: str | None


@dataclass(frozen=True, slots=True)
class SubscriberQuery:
    """What the table was asked for. Every field maps to one query parameter."""

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    sort: str = "-lastActiveAt"
    states: tuple[State, ...] = ()
    plan_ids: tuple[str, ...] = ()
    cohort: Cohort | None = None
    search: str | None = None


@dataclass(frozen=True, slots=True)
class Page:
    items: tuple[SubscriberRow, ...]
    total: int
    page: int
    page_size: int


def build_row(
    subscription: Subscription,
    display_name: str,
    last_active_at: datetime | None,
) -> SubscriberRow:
    return SubscriberRow(
        user_id=subscription.user_id,
        display_name=display_name,
        state=subscription.state,
        plan_id=subscription.plan_id,
        # Not filtered by state the way the two below are, because this one is already the answer
        # for the state it is in — that is what the property is for.
        access_until=subscription.access_until,
        expires_at=subscription.expires_at,
        # Filtered by state because `substate` answers historically: `trial_ends_at` survives the
        # conversion that ended the trial, and `grace_ends_at` is computed whatever the state is.
        # Unfiltered, an ACTIVE row carries a trial end — a tagged union whose tag decides nothing.
        trial_ends_at=(subscription.trial_ends_at if subscription.state is State.TRIAL else None),
        grace_ends_at=(subscription.grace_ends_at if subscription.state is State.GRACE else None),
        cancelled_at=(subscription.cancelled_at if subscription.state is State.CANCELLED else None),
        pending_plan_id=subscription.pending_plan_id,
        last_active_at=last_active_at,
        promo_code=subscription.promo_code,
        referrer_id=subscription.referrer_id,
    )


def _matches(row: SubscriberRow, query: SubscriberQuery, now: datetime) -> bool:
    if query.states and row.state not in query.states:
        return False
    if query.plan_ids and row.plan_id not in query.plan_ids:
        return False
    if query.search:
        needle = query.search.casefold()
        if needle not in row.display_name.casefold() and needle not in row.user_id.casefold():
            return False
    return query.cohort is None or in_cohort(row, query.cohort, now)


def live_subscriptions(world: World) -> AsyncIterator[Subscription]:
    """Every subscription the engine still has, for the ids this world knows about.

    The one walk behind both the table's total and the analytics snapshot. Two walks would be two
    answers to how many subscribers there are, on two screens a reader opens side by side.
    """

    async def walk() -> AsyncIterator[Subscription]:
        for user_id in world.subscribers:
            subscription = await world.engine.get_subscription(user_id)
            # Known to the journal, gone from the engine. Not an error: an event names a
            # subscriber, and a subscription can be removed while its history stays.
            if subscription is not None:
                yield subscription

    return walk()


def in_cohort(row: SubscriberRow, cohort: Cohort, now: datetime) -> bool:
    match cohort:
        case Cohort.QUIET:
            return (
                row.state in (State.TRIAL, State.ACTIVE, State.GRACE)
                and row.last_active_at is not None
                and now - row.last_active_at > QUIET_AFTER
            )
        case Cohort.TRIAL_ENDING:
            return (
                row.state is State.TRIAL
                and row.trial_ends_at is not None
                and now <= row.trial_ends_at <= now + timedelta(days=3)
            )
        case Cohort.CANCELLED_LOSING_ACCESS:
            return (
                row.state is State.CANCELLED
                and row.expires_at is not None
                and now <= row.expires_at <= now + LOSING_ACCESS_WITHIN
            )


def _sortable(row: SubscriberRow, field: SortField) -> str | datetime | int | None:
    """The value a row is ordered by, or None when the row has none."""
    match field:
        case SortField.USER_ID:
            return row.user_id
        case SortField.DISPLAY_NAME:
            return row.display_name.casefold()
        case SortField.STATE:
            return STATE_URGENCY[row.state]
        case SortField.ACCESS_UNTIL:
            return row.access_until
        case SortField.EXPIRES_AT:
            return row.expires_at
        case SortField.LAST_ACTIVE_AT:
            return row.last_active_at


def parse_sort(sort: str) -> tuple[SortField, bool]:
    """`-field` is descending, `field` ascending. Unknown fields are a refusal, not a default:
    silently sorting by something else is a table that lies about what it is showing."""
    descending = sort.startswith("-")
    name = sort[1:] if descending else sort
    return SortField(name), descending


async def list_subscribers(
    world: World,
    projection: dict[str, tuple[str, datetime | None]],
    query: SubscriberQuery,
    *,
    now: datetime | None = None,
) -> Page:
    """Answer the table for one world.

    `projection` is the world's `subscriber_view` rows, already loaded: display name and last
    activity by user id.

    A PAGE THIS CANNOT SERVE IS REFUSED, NOT QUIETLY CORRECTED.

    `SubscriberQueryParams` bounds both numbers, so a request out of range is a 422 and never
    arrives here. Everything that does arrive with one is a test, a capture or a measurement — the
    callers a silent correction hurts most, because nothing else is watching them.

    It cost a round: a census asked for a thousand rows, was handed the first hundred without a
    word, and reported a population it had never counted. Bounds the wrapper keeps for reasons of
    its own are not copied — only what would otherwise be corrected here.
    """
    if not 1 <= query.page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"a page holds 1 to {MAX_PAGE_SIZE} rows, not {query.page_size}")
    if query.page < 1:
        raise ValueError(f"pages are numbered from 1, so there is no page {query.page}")

    moment = now if now is not None else world.clock.now()
    field, descending = parse_sort(query.sort)

    rows: list[SubscriberRow] = []
    async for subscription in live_subscriptions(world):
        user_id = subscription.user_id
        display_name, last_active_at = projection.get(user_id, (user_id, None))
        row = build_row(subscription, display_name, last_active_at)
        if _matches(row, query, moment):
            rows.append(row)

    # Rows with no value are appended rather than keyed, so they stay at the bottom whichever way
    # the order runs: a "present" flag in the key is reversed along with the value. The user id is
    # the secondary key, so equal rows do not swap places between requests.
    present = [row for row in rows if _sortable(row, field) is not None]
    absent = [row for row in rows if _sortable(row, field) is None]
    present.sort(key=lambda r: (_sortable(r, field), r.user_id), reverse=descending)
    absent.sort(key=lambda r: r.user_id)
    rows = present + absent

    total = len(rows)
    start = (query.page - 1) * query.page_size
    return Page(
        items=tuple(rows[start : start + query.page_size]),
        total=total,
        page=query.page,
        page_size=query.page_size,
    )
