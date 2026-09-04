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

from datetime import datetime, timedelta

import pytest
from substate import MemoryStorage, SubscriptionEngine

from app.seed.catalogue import PLANS, PROMO_CODES, REFERRAL_PROGRAMS, USERS_PROGRAM
from app.seed.run import HISTORY_DAYS, SEED, EventTally, SeedReport, seed_world
from app.subscribers.query import QUIET_AFTER
from app.worlds.clock import OffsetClock

# From the specification. The upper bounds matter as much as the lower ones: more than half the
# table expired reads as a product somebody abandoned.

# GRACE IS NOT HERE, and that is the correction rather than an omission. It is the one population
# in single digits, so its value on any one day is a draw rather than a size: over 120 landing
# days it ran 1 to 11 around a mean of 5.6.

# A floor asserted per day is a coin weighted against whoever runs the suite. The test below
# asserts the size instead.
POPULATIONS: dict[str, tuple[int | None, int | None]] = {
    "active": (150, None),
    "expired": (None, 90),
    "trial": (20, None),
    "cancelled": (25, None),
}

GRACE: tuple[int, int] = (3, 8)
"""What a standing grace of this world's size comes to, as decision 101 derives it arithmetically:
arrivals into grace times how long they stay. It describes the mean, which is what the test asserts
it of."""

LANDING_DAYS = 7
"""How many end-dates the grace test builds. The seed fixes the history relative to its own end and
the world is built ending now, so the calendar moves under it; one landing day is one sample."""


async def run_once(
    seed: int = SEED, *, ending_days_ago: int = 0
) -> tuple[SeedReport, OffsetClock, EventTally]:
    """One run of the seeder. `ending_days_ago` lands the same history on an earlier calendar."""
    clock = OffsetClock(timedelta(days=-(HISTORY_DAYS + ending_days_ago)))
    tally = EventTally()
    engine = SubscriptionEngine(
        MemoryStorage(), clock=clock, on_event=tally, default_program=USERS_PROGRAM
    )
    report, _ = await seed_world(engine, clock.advance, clock.now, seed=seed, tally=tally)
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


async def test_grace_is_a_handful_on_any_day_and_a_size_across_a_week() -> None:
    """The state the design calls "call today", asserted as a size rather than as a draw.

    A single-digit count read once is a sample. A floor of three, asserted per day, sat below its
    own mean and failed on 38% of landing days.

    So the mean over a week of them carries the range, and the property the range exists for — the
    filter is never empty — is asserted of every day in that week.
    """
    held = [
        (await run_once(ending_days_ago=day))[0].states.get("grace", 0)
        for day in range(LANDING_DAYS)
    ]
    low, high = GRACE

    assert low <= sum(held) / len(held) <= high, f"grace averaged {held} over {LANDING_DAYS} days"
    # The one this is all for. Measured at zero empty days in 120, and it was three before.
    assert all(count > 0 for count in held), f"the grace filter was empty on a day: {held}"


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


async def test_the_top_of_the_scale_is_used(
    seeded: tuple[SeedReport, OffsetClock, EventTally],
) -> None:
    """Somebody was here today.

    Without this the column opens on "9 days ago" with the whole recent end of its scale unused,
    which reads as a service nobody uses rather than as a scale that stops where honesty stops.
    """
    report, _, _ = seeded
    assert report.ended_at is not None

    within_a_day = sum(
        1
        for *_, seen in report.subscribers_projection
        if report.ended_at - seen < timedelta(days=1)
    )
    assert within_a_day > 0, "nobody was active in the last day, so the top of the scale is unused"


# Several seeds, not the one the demonstration ships. The floor is a bound on a distribution, and
# on the shipping seed the freshest draw lands at nine hours whether or not the floor is there —
# a single-seed assertion would pass with the floor deleted and prove nothing. Across these five
# it does not: the third puts somebody at thirty-seven minutes the moment the bound is removed.
@pytest.mark.parametrize("seed", [SEED, SEED + 1, SEED + 2, SEED + 3, SEED + 4])
async def test_no_seed_puts_activity_inside_the_minutes(seed: int) -> None:
    """These timestamps are written once and then stand still while somebody looks at the panel,
    and the table renders them as "how long ago". A subscriber seeded four minutes back reads as
    "4 minutes ago" on the first screen and "44 minutes ago" half an hour later, having done
    nothing — the demonstration claiming an activity it has no source for, in a number that
    visibly decays. An hour is where that claim stops being made."""
    report, _, _ = await run_once(seed)
    assert report.ended_at is not None

    freshest = min(report.ended_at - seen for *_, seen in report.subscribers_projection)
    assert freshest >= timedelta(hours=1), (
        f"seed {seed} put somebody at {freshest}, inside the minutes the scale cannot honestly hold"
    )


async def test_nobody_was_active_before_they_existed() -> None:
    """The larger of the two honesty problems in this column, and the one a date column hid.

    Every activity window is a fixed span measured back from the end of the run, while arrivals
    ramp up across the history, so most subscribers are younger than the window they are drawn
    from. Unclipped, that credited 87 of 351 rows with activity from before they subscribed — the
    worst by 181 days — and nineteen of the twenty-four trials, including a fourteen-day trial two
    days old whose owner was last seen three months earlier and who was returned by the Quiet
    cohort. "17 Aug 2026" made that invisible; "3 months ago" beside a trial that started on
    Tuesday does not.

    The two rows this still allows are the residue of the freshness floor, which wins where the
    two rules disagree: somebody who arrived on the last simulated day has no age to spare, and is
    credited with an hour they did not have. Two rows wrong by an hour against 87 wrong by months.
    """
    clock = OffsetClock(timedelta(days=-HISTORY_DAYS))
    tally = EventTally()

    first_event: dict[str, datetime] = {}

    def watch(event: object) -> None:
        user_id = getattr(event, "user_id", None)
        occurred_at = getattr(event, "occurred_at", None)
        if isinstance(user_id, str) and isinstance(occurred_at, datetime):
            first_event.setdefault(user_id, occurred_at)
        tally(event)

    engine = SubscriptionEngine(
        MemoryStorage(), clock=clock, on_event=watch, default_program=USERS_PROGRAM
    )
    report, _ = await seed_world(engine, clock.advance, clock.now, tally=tally)

    impossible = [
        (user_id, first_event[user_id] - seen)
        for user_id, _, seen in report.subscribers_projection
        if user_id in first_event and seen < first_event[user_id]
    ]

    assert len(impossible) <= 2, (
        f"{len(impossible)} subscribers were active before they subscribed: "
        + ", ".join(f"{user_id} by {gap}" for user_id, gap in impossible[:5])
    )
    for user_id, gap in impossible:
        assert gap <= timedelta(hours=1), (
            f"{user_id} was active {gap} before subscribing, which is not the hour the freshness "
            f"floor accounts for"
        )


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


async def test_the_report_counts_the_events_the_run_produced(
    seeded: tuple[SeedReport, OffsetClock, EventTally],
) -> None:
    """`events` was declared and never assigned, so it read zero for a run that made thousands.

    It survived because both callers sidestepped it — one logs the COPY's own count, the other the
    subscriber count — which is exactly how a field stays wrong.
    """
    report, _, tally = seeded

    assert report.events == tally.events
    assert report.events > 0
