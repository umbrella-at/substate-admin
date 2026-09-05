"""Winding a seeded world forward, and what has to remain true of it afterwards.

The time machine is the reason the demonstration exists, so the thing it must not do is turn the
demonstration into a graveyard. A world that is only ticked has nobody paying in it: measured, one
month of that takes ACTIVE from 248 to 86 and leaves every paying subscriber in the Quiet cohort.

So an advance runs the same modelled life the history was made of. These are the properties that
buys, asserted rather than described — the population survives, the cohort stays a share, and no
subscriber's activity moves backwards or lands somewhere they could not have been.
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from substate import MemoryStorage, SubscriptionEngine

from app.schemas import AdvanceRequest
from app.seed.activity import FRESHEST, LIVE, QUIET_AFTER
from app.seed.catalogue import USERS_PROGRAM
from app.seed.run import HISTORY_DAYS, EventTally, Population, SeedReport, carry_on, seed_world
from app.worlds.clock import OffsetClock

type Wound = tuple[SubscriptionEngine, OffsetClock, Population, SeedReport]

# Long enough that every plan has had a renewal fall due, and long enough that a frozen projection
# would have put the whole table in the Quiet cohort.
A_MONTH = 30


async def seed() -> Wound:
    """One world, nine months of history, ending now."""
    clock = OffsetClock(timedelta(days=-HISTORY_DAYS))
    tally = EventTally()
    engine = SubscriptionEngine(
        MemoryStorage(), clock=clock, on_event=tally, default_program=USERS_PROGRAM
    )
    report, population = await seed_world(engine, clock.advance, clock.now, tally=tally)
    return engine, clock, population, report


async def wind(wound: Wound, days: int) -> SeedReport:
    engine, clock, population, _ = wound
    return await carry_on(engine, population, clock.advance, clock.now, days=days)


@pytest.fixture
async def seeded() -> Wound:
    return await seed()


async def test_the_world_goes_on_acquiring_and_churning(seeded: Wound) -> None:
    """The failure this exists to prevent, stated as an assertion.

    Ticking alone leaves 86 active and 211 expired after a month, because nobody in a ticked world
    ever pays. Running the same behaviour keeps the shape the calibration was tuned for.
    """
    before = seeded[3]
    after = await wind(seeded, A_MONTH)

    assert after.subscribers > before.subscribers
    assert after.states["active"] >= before.states["active"]
    # The upper bound is the half of this that a growing population does not give for free: a
    # month of arrivals with nobody leaving would be a different lie.
    assert after.states["cancelled"] > before.states["cancelled"]
    assert after.states["expired"] < before.states["active"] / 2


async def test_the_quiet_cohort_stays_a_share_however_the_clock_is_pressed(seeded: Wound) -> None:
    """A month in one press and a month in thirty, against the same range.

    Both halves matter. One press is where a frozen projection reads 100%; thirty presses is where
    a cohort re-drawn from scratch each time drains to nothing, because nobody stays quiet through
    thirty independent chances to come back.
    """
    at_once = await wind(seeded, A_MONTH)
    assert 0.05 <= _share(at_once) <= 0.40

    day_by_day = await seed()
    for _ in range(A_MONTH):
        last = await wind(day_by_day, 1)
    assert 0.05 <= _share(last) <= 0.40


async def test_activity_never_moves_backwards(seeded: Wound) -> None:
    """Nothing enforces this in the database, and the redraw is what would break it.

    A quiet subscriber's window reaches 120 days back, so a re-draw that simply took what it drew
    would file somebody as three months silent who was here yesterday — and the panel would show
    activity un-happening between two presses of the same button.
    """
    _, _, population, _ = seeded
    before = dict(population.last_active)

    await wind(seeded, A_MONTH)

    moved_back = {
        user_id: (was, population.last_active[user_id])
        for user_id, was in before.items()
        if population.last_active[user_id] < was
    }
    assert moved_back == {}


async def test_nobody_is_credited_with_activity_before_they_arrived(seeded: Wound) -> None:
    """The clip, still holding after an advance.

    Subscribers who arrive during the advance are the ones at risk: the windows are fixed spans
    measured back from the new moment, and somebody two days old would otherwise be drawn from a
    span reaching four months into a life they did not have.
    """
    _, clock, population, _ = seeded
    arrived_during = set(population.arrived)

    await wind(seeded, A_MONTH)

    newcomers = [uid for uid in population.arrived if uid not in arrived_during]
    assert newcomers, "the advance produced no arrivals, so this asserts nothing"
    for user_id in newcomers:
        born = clock.now() - population.age_of(user_id) - timedelta(days=1)
        assert population.last_active[user_id] >= born


async def test_nobody_is_fresher_than_the_floor(seeded: Wound) -> None:
    """The floor is what stops the column claiming an activity it has no source for."""
    _, clock, population, _ = seeded
    await wind(seeded, A_MONTH)

    moment = clock.now()
    freshest = max(population.last_active.values())
    assert moment - freshest >= FRESHEST


async def test_a_wound_world_reports_its_own_moment_not_the_wall_clock(seeded: Wound) -> None:
    """`ended_at` is what every last_active_at is measured back from, and what the panel renders
    relative times against. Read from the wall clock it would be a month out."""
    _, clock, _, _ = seeded
    after = await wind(seeded, A_MONTH)

    assert after.ended_at == pytest.approx(clock.now(), abs=timedelta(seconds=1))  # type: ignore[call-overload]
    assert after.ended_at is not None
    assert after.ended_at - datetime.now(UTC) > timedelta(days=A_MONTH - 1)


async def test_the_same_world_wound_the_same_way_lands_in_the_same_place() -> None:
    """Determinism is what lets any of the above be asserted at all, and an advance is part of the
    run rather than a separate thing with a stream of its own.

    Compared as gaps rather than as instants: the world ends at the real clock plus an offset, so
    two runs a second apart hold different absolute times and the same history.
    """
    first, second = await seed(), await seed()
    one = await wind(first, A_MONTH)
    two = await wind(second, A_MONTH)

    assert first[2].arrived == second[2].arrived
    assert first[2].quiet == second[2].quiet
    assert one.states == two.states

    # To the second, not to the microsecond: the two runs are minted against the real clock at
    # different instants, and a run takes a seventh of a second to produce.
    here, there = _gaps(first, one), _gaps(second, two)
    assert here.keys() == there.keys()
    assert max(abs(here[uid] - there[uid]) for uid in here) <= 1


def _gaps(wound: Wound, report: SeedReport) -> dict[str, int]:
    """Every subscriber's activity, in whole seconds before the moment the run reached."""
    ended = report.ended_at
    assert ended is not None
    return {
        user_id: round((ended - at).total_seconds()) for user_id, at in wound[2].last_active.items()
    }


def _share(report: SeedReport) -> float:
    live = sum(count for state, count in report.states.items() if state in _LIVE_NAMES)
    assert live > 0
    return report.quiet / live


_LIVE_NAMES = frozenset(state.value for state in LIVE)


async def test_the_threshold_is_the_panels_own(seeded: Wound) -> None:
    """One definition of quiet, not two. The seeder used to keep a private copy of the threshold,
    and a report counted against a copy is a number that can drift from the screen it explains."""
    engine, clock, population, _ = seeded
    after = await wind(seeded, A_MONTH)

    moment = clock.now()
    counted = 0
    for user_id in population.arrived:
        subscription = await engine.get_subscription(user_id)
        if subscription is not None and subscription.state in LIVE:
            counted += moment - population.last_active[user_id] > QUIET_AFTER
    assert counted == after.quiet


async def test_a_subscription_that_is_over_keeps_the_mark_it_had(seeded: Wound) -> None:
    """Somebody whose subscription ended stopped turning up when it ended.

    Re-drawing them would let a subscriber cancelled eight months ago be credited with a visit
    last week, because their window starts thirty days back from whatever the moment now is.

    The ones who come back are excluded on purpose: a cancelled subscription reaches expiry and
    can be revived from there, and somebody paying again is somebody here again.
    """
    engine, _, population, _ = seeded
    over = {
        user_id: population.last_active[user_id]
        for user_id in population.arrived
        if (subscription := await engine.get_subscription(user_id)) is not None
        and subscription.state not in LIVE
    }
    assert over, "nobody had finished, so this asserts nothing"

    await wind(seeded, A_MONTH)

    still_over = {}
    for user_id, was in over.items():
        subscription = await engine.get_subscription(user_id)
        if subscription is not None and subscription.state not in LIVE:
            still_over[user_id] = was
    # Most of them do come back — a month is long enough that a revival rate of 0.07 a day
    # reaches nine in ten — so the ones that did not are the sample, and there have to be some.
    assert len(still_over) > 10, "everybody came back, so this asserts nothing"
    assert {uid: population.last_active[uid] for uid in still_over} == still_over


@pytest.mark.parametrize("days", [0, -30])
async def test_a_wind_of_no_days_is_refused_rather_than_reported(seeded: Wound, days: int) -> None:
    """`AdvanceRequest` bounds the number, so this arrives only from a test or a capture.

    It used to return a full report with the clock exactly where it was — and `_take_stock` drew
    from the activity stream on the way, so the "no-op" moved every later draw and the history
    stopped reproducing. The stream's state is asserted alongside the clock for that reason.
    """
    _, clock, population, _ = seeded
    stood_at, stream = clock.offset, population.streams.activity.getstate()

    with pytest.raises(ValidationError):
        AdvanceRequest(days=days)
    with pytest.raises(ValueError, match="at least one day"):
        await wind(seeded, days)

    assert clock.offset == stood_at
    assert population.streams.activity.getstate() == stream
