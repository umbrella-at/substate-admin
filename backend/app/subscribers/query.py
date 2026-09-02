"""The subscriber table, assembled from two sources that must not be confused.

The state of a subscription, its plan, its dates and its promo code come from `substate` and are
asked of it every time. The display name and `last_active_at` come from the projection, because
the engine has never heard of them. Nothing here caches the first kind into the second: a
projection that started answering "what state is this subscription in" would be a second answer to
a question that already has one, and the two would disagree on the day it mattered.

Filtering and sorting happen in this process rather than in Postgres, because the subscriptions
are in this process. The base world holds a few hundred of them, so the cost is a few hundred
dictionary lookups per request. When the SQLAlchemy storage lands this becomes a query, and the
shape of the answer stays the same — which is the point of putting the world key on everything
from the first day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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

MAX_PAGE_SIZE: Final = 100
DEFAULT_PAGE_SIZE: Final = 25


class Cohort(StrEnum):
    """Lists to act on, not numbers to look at.

    Each one answers a question somebody has already asked themselves: who is about to lapse, who
    is paying without turning up, who cancelled but is still inside a period they paid for.

    Every one of them is a question the state filter cannot ask, and that is the entry condition.
    There was a fourth, `in-grace`, whose predicate was `row.state is State.GRACE` — the same
    question as `?state=grace`, in a second vocabulary. Two names for one question is worse than
    one name, because the reader has to work out whether the difference means something.
    """

    QUIET = "quiet"
    TRIAL_ENDING = "trial-ending"
    CANCELLED_STILL_ACTIVE = "cancelled-still-active"


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

Alphabetical put ACTIVE, CANCELLED, EXPIRED, GRACE, TRIAL at the top of the table in that order,
which is the order of the letters and of nothing else. What an administrator opens this table to
find is who needs something done today, so that is the order:

    GRACE      a paying customer whose payment failed. Today, or they are gone.
    TRIAL      deciding right now whether to pay. The only window there is.
    ACTIVE     paying and fine. Nothing to do.
    CANCELLED  said no, still inside a period they paid for. Worth a call, not an urgent one.
    EXPIRED    already gone. Nothing here is time-critical.

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

    `substate` computes it: a trial ends at `trial_ends_at`, a grace period at `grace_ends_at`,
    everything else at `expires_at`. The three are kept alongside it rather than replaced, because
    they are different questions and the subscriber card asks all of them — but a table with one
    date column has to show the one that is true right now, and `expires_at` alone was empty on
    every trial in the world.
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
        # Read from the model, then shown only in the state that owns them.
        #
        # Both halves matter. Deriving these from `expires_at` and `due_at` got the trial wrong
        # and left a cohort that always returned nothing — `substate` answers both questions and
        # its answer is the one that stays right. But its answers are historical: `trial_ends_at`
        # survives the conversion that ended the trial, and `grace_ends_at` is computed from the
        # expiry whatever state the subscription is in. Passing them through unfiltered puts a
        # trial end and a grace end on an ACTIVE row, which is a tagged union whose tag does not
        # decide what is in it — exactly the type that lies.
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
    return query.cohort is None or _in_cohort(row, query.cohort, now)


def _in_cohort(row: SubscriberRow, cohort: Cohort, now: datetime) -> bool:
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
        case Cohort.CANCELLED_STILL_ACTIVE:
            return (
                row.state is State.CANCELLED and row.expires_at is not None and row.expires_at > now
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
    """
    moment = now if now is not None else datetime.now(UTC)
    field, descending = parse_sort(query.sort)

    rows: list[SubscriberRow] = []
    for user_id in world.subscribers:
        subscription = await world.engine.get_subscription(user_id)
        if subscription is None:
            # Known to the journal, gone from the engine. Not an error: an event names a
            # subscriber, and a subscription can be removed while its history stays.
            continue
        display_name, last_active_at = projection.get(user_id, (user_id, None))
        row = build_row(subscription, display_name, last_active_at)
        if _matches(row, query, moment):
            rows.append(row)

    # Rows with no value are sorted apart from the rest and appended, so that they stay at the
    # bottom whichever way the order runs. Carrying a "present" flag in the sort key does not do
    # this: `reverse=True` reverses the flag along with the value, and a table sorted by newest
    # expiry opens with the forty people who have no expiry at all.
    #
    # The secondary key is the user id, so two rows with the same state or the same plan do not
    # swap places between requests and make the table look unstable while paging through it.
    present = [row for row in rows if _sortable(row, field) is not None]
    absent = [row for row in rows if _sortable(row, field) is None]
    present.sort(key=lambda r: (_sortable(r, field), r.user_id), reverse=descending)
    absent.sort(key=lambda r: r.user_id)
    rows = present + absent

    total = len(rows)
    size = max(1, min(query.page_size, MAX_PAGE_SIZE))
    start = (max(1, query.page) - 1) * size
    return Page(
        items=tuple(rows[start : start + size]), total=total, page=query.page, page_size=size
    )
