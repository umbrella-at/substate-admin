"""What the table asks for, and what it gets back.

The sort tests are the reason this file exists. A sort that puts absent values first is not a
crash and not a wrong number — it is a table that opens with the forty people who have no expiry
date when somebody asked for the ones expiring soonest, and it looks like an ordering choice
rather than a defect. It survived a full suite because the field that is usually sorted by has no
absent values at all, so reversing the order never had anything to float to the top.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from substate import MemoryStorage, State, SubscriptionEngine

from app.seed.catalogue import USERS_PROGRAM
from app.seed.run import HISTORY_DAYS, EventTally, seed_world
from app.subscribers.query import Cohort, SubscriberQuery, list_subscribers
from app.worlds.clock import OffsetClock
from app.worlds.registry import World


@pytest.fixture
async def world() -> tuple[World, dict[str, tuple[str, object]]]:
    """A seeded world and its projection, the pair every query needs."""
    clock = OffsetClock(timedelta(days=-HISTORY_DAYS))
    tally = EventTally()
    storage = MemoryStorage()
    engine = SubscriptionEngine(storage, clock=clock, on_event=tally, default_program=USERS_PROGRAM)
    report = await seed_world(engine, clock.advance, clock.now, tally=tally)
    built = World(
        id="test",
        engine=engine,
        clock=clock,
        storage=storage,
        created_at=clock.now(),
        seeded=True,
        subscribers={user_id for user_id, *_ in report.subscribers_projection},
    )
    projection = {
        user_id: (display_name, last_active_at)
        for user_id, display_name, last_active_at in report.subscribers_projection
    }
    return built, projection


async def _all(world, projection, sort: str) -> list:
    """Every row for one sort, gathered a page at a time the way the table does."""
    rows = []
    page = 1
    while True:
        answer = await list_subscribers(
            world, projection, SubscriberQuery(sort=sort, page=page, page_size=100)
        )
        rows.extend(answer.items)
        if len(rows) >= answer.total:
            return rows
        page += 1


@pytest.mark.parametrize("sort", ["expiresAt", "-expiresAt"])
async def test_rows_with_no_value_stay_at_the_bottom(world, sort: str) -> None:
    """Whichever way the order runs.

    Carrying a "present" flag in the sort key does not achieve this: `reverse=True` reverses the
    flag along with the value.
    """
    built, projection = world
    rows = await _all(built, projection, sort)
    absent = [index for index, row in enumerate(rows) if row.expires_at is None]
    assert absent, "this world no longer has rows without an expiry; the test proves nothing"
    assert min(absent) == len(rows) - len(absent)


@pytest.mark.parametrize("sort", ["expiresAt", "-expiresAt"])
async def test_the_rows_that_do_have_a_value_are_in_order(world, sort: str) -> None:
    built, projection = world
    rows = await _all(built, projection, sort)
    values = [row.expires_at for row in rows if row.expires_at is not None]
    assert values == sorted(values, reverse=sort.startswith("-"))


@pytest.mark.parametrize("sort", ["lastActiveAt", "-lastActiveAt"])
async def test_activity_is_ordered_by_the_instant_and_not_by_how_it_reads(world, sort: str) -> None:
    """The table draws this column as "9 days ago" and "2 months ago".

    Those phrases do not order themselves — alphabetically "2 months" precedes "9 days" while the
    instant behind it is four times older. So the order has to come from the timestamp, and the
    second assertion is what makes the first mean something: it fails if this world ever stops
    containing a pair the text would sort the wrong way round, at which point the test would be
    proving nothing.
    """
    built, projection = world
    rows = await _all(built, projection, sort)
    values = [row.last_active_at for row in rows if row.last_active_at is not None]
    assert values == sorted(values, reverse=sort.startswith("-"))

    newest, oldest = max(values), min(values)
    assert (oldest - newest).days < -30, (
        "this world no longer spans days and months at once, so ordering by the phrase and "
        "ordering by the instant would agree and this test would prove nothing"
    )


async def test_paging_covers_everybody_once(world) -> None:
    """The property that makes paging trustworthy: no row seen twice, none missed."""
    built, projection = world
    rows = await _all(built, projection, "displayName")
    ids = [row.user_id for row in rows]
    assert len(ids) == len(set(ids))
    assert set(ids) == built.subscribers


async def test_a_state_filter_returns_that_state_and_nothing_else(world) -> None:
    built, projection = world
    for state in State:
        answer = await list_subscribers(
            built, projection, SubscriberQuery(states=(state,), page_size=100)
        )
        assert {row.state for row in answer.items} <= {state}


async def test_every_cohort_holds_somebody(world) -> None:
    """A cohort nobody is in is a filter that looks broken to whoever tries it."""
    built, projection = world
    for cohort in Cohort:
        answer = await list_subscribers(
            built, projection, SubscriberQuery(cohort=cohort, page_size=1)
        )
        assert answer.total > 0, f"nobody is in {cohort.value}"


def test_the_default_order_is_the_one_the_table_draws_an_arrow_for() -> None:
    """The frontend mirrors this value so the header can explain the order on the first screen,
    where the address carries no sort at all. If it moves here without moving there, the table
    goes back to showing a real order with nothing on screen to account for it — which is not a
    failure any other test can see."""
    assert SubscriberQuery().sort == "-lastActiveAt"


async def test_search_matches_a_name_somebody_can_see(world) -> None:
    built, projection = world
    first = (await list_subscribers(built, projection, SubscriberQuery(page_size=1))).items[0]
    fragment = first.display_name.split()[0]
    answer = await list_subscribers(
        built, projection, SubscriberQuery(search=fragment, page_size=100)
    )
    assert answer.total > 0
    assert all(
        fragment.casefold() in row.display_name.casefold()
        or fragment.casefold() in row.user_id.casefold()
        for row in answer.items
    )
