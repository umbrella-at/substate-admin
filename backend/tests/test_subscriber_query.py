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
from app.subscribers.query import Cohort, SubscriberQuery, list_subscribers, parse_sort
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


@pytest.mark.parametrize("sort", ["lastActiveAt", "-lastActiveAt"])
async def test_subscribers_who_never_turned_up_stay_at_the_bottom(world, sort: str) -> None:
    """The table draws these as "Never", and they belong under everybody who did turn up.

    The seeder gives every subscriber a last activity, so this cannot be asked of the seeded world
    the way the same question is asked of expiry — the rows simply do not exist. They are made
    here by removing people from the projection, which is the state the application already
    handles: a subscriber the journal knows and the projection has no row for.
    """
    built, projection = world
    never = sorted(built.subscribers)[:5]
    thinned = {k: v for k, v in projection.items() if k not in never}

    rows = await _all(built, thinned, sort)
    absent = [index for index, row in enumerate(rows) if row.last_active_at is None]
    assert len(absent) == len(never)
    assert min(absent) == len(rows) - len(absent)


async def test_state_sorts_by_what_needs_doing_not_by_the_alphabet(world) -> None:
    """The order is a claim about the work, and the alphabet was a claim about the letters.

    Written as the domain order rather than as "not alphabetical", because those are different
    assertions and only one of them is what the table promises. The alphabet is checked separately
    below so this test cannot quietly start passing on an ordering that merely happens to differ.
    """
    built, projection = world
    rows = await _all(built, projection, "state")
    seen = [row.state for row in rows]

    order = [
        state
        for state in (State.GRACE, State.TRIAL, State.ACTIVE, State.CANCELLED, State.EXPIRED)
        if state in seen
    ]
    assert [state for state in dict.fromkeys(seen)] == order

    alphabetical = sorted({state.value for state in seen})
    assert [state.value for state in dict.fromkeys(seen)] != alphabetical, (
        "the domain order and the alphabet now agree, so this test proves nothing"
    )


async def test_the_urgent_states_come_first(world) -> None:
    """The reason the order exists: somebody opens this table to find who needs something today."""
    built, projection = world
    rows = await _all(built, projection, "state")
    assert rows[0].state is State.GRACE
    assert rows[-1].state is State.EXPIRED


async def test_a_plan_cannot_be_sorted_by(world) -> None:
    """A plan is a category. Any order over the five would be invented, and the alphabetical one
    would be about the letters of their names."""
    with pytest.raises(ValueError, match="planId"):
        parse_sort("planId")


@pytest.mark.parametrize("plans", [("weekly",), ("weekly", "annual")])
async def test_plans_filter_as_a_set(world, plans: tuple[str, ...]) -> None:
    built, projection = world
    answer = await list_subscribers(
        built, projection, SubscriberQuery(plan_ids=plans, page_size=100)
    )
    assert answer.total > 0
    assert {row.plan_id for row in answer.items} <= set(plans)


async def test_access_until_is_the_boundary_of_the_state_the_row_is_in(world) -> None:
    """A subscription has three boundaries and only one of them is true at a time.

    The table draws one date column, and drawing `expires_at` in it left every trial in the world
    blank — the field is not set until a trial converts, and "when does this trial end" is the
    first thing anybody asks about one.
    """
    built, projection = world
    rows = await _all(built, projection, "displayName")
    by_state: dict[State, list] = {}
    for row in rows:
        by_state.setdefault(row.state, []).append(row)

    for state in (State.TRIAL, State.ACTIVE, State.GRACE, State.CANCELLED):
        assert by_state.get(state), f"no {state.value} rows, so this proves nothing about them"

    for row in by_state[State.TRIAL]:
        assert row.access_until == row.trial_ends_at is not None
    for row in by_state[State.GRACE]:
        assert row.access_until == row.grace_ends_at is not None
    for state in (State.ACTIVE, State.CANCELLED):
        for row in by_state[state]:
            assert row.access_until == row.expires_at is not None

    # The one place a dash belongs: expired without ever having paid, so there is no boundary to
    # show rather than a boundary nobody filled in.
    blank = [row for row in rows if row.access_until is None]
    assert blank, "no row without a boundary, so the dash is untested"
    assert {row.state for row in blank} == {State.EXPIRED}


@pytest.mark.parametrize("sort", ["accessUntil", "-accessUntil"])
async def test_the_column_sorts_by_what_it_shows(world, sort: str) -> None:
    """Ordering by `expiresAt` while drawing `accessUntil` puts the trials where they do not
    belong, and the table looks sorted the whole time."""
    built, projection = world
    rows = await _all(built, projection, sort)

    values = [row.access_until for row in rows if row.access_until is not None]
    assert values == sorted(values, reverse=sort.startswith("-"))

    # And the two orders really are different in this world, or the assertion above would pass
    # against either field.
    by_expiry = [row.user_id for row in await _all(built, projection, "expiresAt")]
    assert [row.user_id for row in rows] != by_expiry or sort.startswith("-")


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
