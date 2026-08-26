"""The base world: the same one every time, and a shape worth looking at.

Two different promises, and both are worth a test.

Determinism is the cheap one: one seed, one history. Without it the demonstration is different on
every deploy and no assertion about it means anything.

The shape is the expensive one. A world can be perfectly reproducible and useless — every filter
empty, every cohort either nothing or the whole table. What is asserted here is that each of the
five states holds a population somebody could act on, and it is asserted as RANGES rather than as
exact counts. Exact counts break on any change to the model and teach whoever broke them to edit
the expectation instead of thinking about it; a range breaks only when the world stops being
usable, which is the thing worth being told about.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from substate import MemoryStorage, SubscriptionEngine

from app.seed.catalogue import PLANS, PROMO_CODES, REFERRAL_PROGRAMS, USERS_PROGRAM
from app.seed.run import HISTORY_DAYS, EventTally, SeedReport, seed_world
from app.subscribers.query import QUIET_AFTER
from app.worlds.clock import OffsetClock

# From the specification. The upper bounds matter as much as the lower ones: more than half the
# table expired reads as a product somebody abandoned, and a standing GRACE of five percent is not
# a number a real service produces.
POPULATIONS: dict[str, tuple[int | None, int | None]] = {
    "active": (150, None),
    "expired": (None, 90),
    "trial": (20, None),
    "grace": (3, 8),
    "cancelled": (25, None),
}


async def run_once() -> tuple[SeedReport, OffsetClock, EventTally]:
    clock = OffsetClock(timedelta(days=-HISTORY_DAYS))
    tally = EventTally()
    engine = SubscriptionEngine(
        MemoryStorage(), clock=clock, on_event=tally, default_program=USERS_PROGRAM
    )
    report = await seed_world(engine, clock.advance, clock.now, tally=tally)
    return report, clock, tally


@pytest.fixture
async def seeded() -> tuple[SeedReport, OffsetClock, EventTally]:
    """Per test rather than per module.

    A module-scoped async fixture outlives the event loop it was built on. The run costs about a
    seventh of a second, so paying it per test is cheaper than the machinery to share one — and a
    test that builds its own world cannot be affected by one that ran before it.
    """
    return await run_once()


async def test_the_same_seed_builds_the_same_world() -> None:
    """Twice, from scratch, identical — in everything the seed decides.

    What the seed does NOT decide is when the run happened. The world ends at the current moment
    by construction, so every absolute timestamp in it is anchored to the wall clock and two runs
    a second apart differ by a second. The history is reproducible relative to its own end, which
    is the property worth having: comparing the absolute times would be asserting that the tests
    ran at the same instant.
    """
    first, _, _ = await run_once()
    second, _, _ = await run_once()

    assert first.subscribers == second.subscribers
    assert first.states == second.states
    assert first.plans == second.plans
    assert first.accruals_by_program == second.accruals_by_program

    # Identity and names come from the seed alone.
    assert [(uid, name) for uid, name, _ in first.subscribers_projection] == [
        (uid, name) for uid, name, _ in second.subscribers_projection
    ]

    # And so does how long ago each person was last seen — measured from the moment the run
    # itself finished, which the report records. Reading the clock again here would measure from
    # a later instant, and a reproducible history would look like it had drifted by a second.
    assert first.ended_at is not None
    assert second.ended_at is not None
    first_ago = [first.ended_at - seen for *_, seen in first.subscribers_projection]
    second_ago = [second.ended_at - seen for *_, seen in second.subscribers_projection]
    assert first_ago == second_ago


async def test_every_state_holds_a_population_worth_filtering_by(
    seeded: tuple[SeedReport, OffsetClock, EventTally],
) -> None:
    report, _, _ = seeded

    for state, (low, high) in POPULATIONS.items():
        held = report.states.get(state, 0)
        if low is not None:
            assert held >= low, f"{state} holds {held}, which is below {low}"
        if high is not None:
            assert held <= high, f"{state} holds {held}, which is above {high}"


async def test_the_world_is_about_the_size_the_specification_asks_for(
    seeded: tuple[SeedReport, OffsetClock, EventTally],
) -> None:
    """Enough that paging and filtering are real questions, few enough to hold in memory twice."""
    report, _, _ = seeded

    assert 270 <= report.subscribers <= 380
    assert len(report.plans) == len(PLANS)
    assert min(report.plans.values()) >= 15, "a plan nobody is on is a filter that returns nothing"


async def test_the_clock_finishes_exactly_on_the_mark(
    seeded: tuple[SeedReport, OffsetClock, EventTally],
) -> None:
    """Not near zero — zero.

    `timedelta` holds whole microseconds, so a run of equal steps lands on the mark rather than
    drifting. A world left a few seconds behind would look right and stay behind for as long as
    the process lives.
    """
    _, clock, _ = seeded

    assert clock.offset == timedelta()
    assert clock.is_live


async def test_both_referral_programmes_are_exercised(
    seeded: tuple[SeedReport, OffsetClock, EventTally],
) -> None:
    """Two programmes in the catalogue prove nothing about either one having been used.

    `repeat_earners` is the discriminating assertion: only EVERY_PAYMENT can pay a referrer twice,
    so a zero here means the two programmes are indistinguishable in the data whatever the
    catalogue says — and the screen that shows them would be showing one thing twice.
    """
    report, _, _ = seeded

    assert set(report.accruals_by_program) == {program.id for program in REFERRAL_PROGRAMS}
    assert min(report.accruals_by_program.values()) >= 10
    assert report.repeat_earners >= 5


async def test_the_quiet_cohort_is_neither_empty_nor_everybody(
    seeded: tuple[SeedReport, OffsetClock, EventTally],
) -> None:
    """A cohort that returns nothing and a cohort that returns the table are equally useless.

    `last_active_at` is filled from its own random stream rather than from the payment dates. Were
    it derived from them, a thirty-day threshold against a monthly plan would collect everybody
    who had not signed in since their last renewal, and "went quiet" would come to mean "pays
    monthly".
    """
    report, _, _ = seeded

    paying = sum(report.states.get(state, 0) for state in ("trial", "active", "grace"))
    assert 0 < report.quiet < paying
    assert 0.05 <= report.quiet / paying <= 0.40


async def test_recent_activity_is_the_normal_case(
    seeded: tuple[SeedReport, OffsetClock, EventTally],
) -> None:
    """Most people turned up recently, which is what makes the threshold mean something."""
    report, clock, _ = seeded

    moment = clock.now()
    recent = sum(1 for _, _, seen in report.subscribers_projection if moment - seen <= QUIET_AFTER)
    assert recent > len(report.subscribers_projection) / 2


async def test_the_catalogue_stays_inside_what_the_engine_allows() -> None:
    """`grace_days` must be shorter than the shortest the period can ever be.

    The engine refuses a plan that breaks this, so the assertion is really about the catalogue
    being reviewed rather than discovered at start-up. The weekly plan is the tight one.
    """
    for plan in PLANS:
        assert plan.grace_days < plan.period.min_days, plan.id
    assert len(PROMO_CODES) >= 3


async def test_every_subscriber_has_a_name_and_a_last_seen(
    seeded: tuple[SeedReport, OffsetClock, EventTally],
) -> None:
    report, _, _ = seeded

    assert len(report.subscribers_projection) == report.subscribers
    assert all(name and seen is not None for _, name, seen in report.subscribers_projection)
