"""Nine months of a subscription service, produced by running the engine rather than by SQL.

Every number the panel shows has an event behind it. The alternative — inserting rows that look
like a plausible history — produces a demonstration that cannot be wrong, because nothing in it
was ever computed. Here a renewal happened because a payment arrived before a period ended, and
if the engine changes its mind about what that means, this history changes with it.

The run is deterministic: one seed, one sequence of decisions, the same world every time. That is
what lets a test assert on the result at all.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from substate import (
    DuplicateReferralProgram,
    Event,
    Payment,
    ReferralAccrued,
    State,
    SubscriptionEngine,
    SubstateError,
)

from app.seed.catalogue import (
    PARTNERS_PROGRAM,
    PLAN_BY_ID,
    PLAN_WEIGHTS,
    PLANS,
    PROMO_CODES,
    REFERRAL_PROGRAMS,
)

HISTORY_DAYS = 274
"""Nine months, which is long enough for an annual plan to be mid-period and for a weekly one to
have renewed thirty times."""

SEED = 20260826


@dataclass(frozen=True, slots=True)
class Behaviour:
    """How the modelled population behaves.

    These are tuned against the target populations rather than invented: the shape of the table at
    the end is what the panel is judged on, and it is decided here rather than by hope. Every value
    was moved until the snapshot landed inside the ranges the specification fixes, and the test
    asserts the ranges rather than the numbers so that a later change to this model fails only when
    it actually breaks something.
    """

    signups_at_start: float = 0.35
    signups_at_end: float = 2.2
    """Arrivals ramp over the run, because a service that is working acquires people faster than
    it did nine months ago. This is not decoration: the standing TRIAL population is whoever
    signed up within the last two weeks and has not paid yet, so a flat arrival rate puts about
    seven people in trial no matter how long the run is. Getting twenty of them out of a uniform
    rate would need four signups a day and a thousand subscribers, which is neither the volume the
    specification asks for nor a shape any real service has."""

    trial_conversion: float = 0.26
    """How often a trial turns into a first payment."""

    renewal: float = 0.89
    """How often an active subscriber pays for the next period, decided once per renewal.

    Held at a figure a real service would recognise. An earlier calibration reached 0.55 because
    it was the only lever that filled GRACE, and the resulting population told a lie about how
    subscriptions work: the median subscriber renewed twice and seven in ten had expired at least
    once. A demonstration whose numbers are reachable only by making the product fail is not
    demonstrating the product."""

    grace_rescue: float = 0.07
    """Per day, how often somebody in grace pays before it runs out. This sets how long they
    linger, and therefore how many are standing there at any moment: at 0.45 the average stay is
    two days and the snapshot holds three people, which is an empty chip on the one state the
    design says means "call today"."""

    revival: float = 0.07
    """Per day, how often an expired subscriber comes back. Without this the run ends as a
    graveyard — the first calibration had 58% expired, which reads as a product somebody
    abandoned rather than one somebody uses."""

    cancellation: float = 0.005
    """Per active subscriber per day. Cancelling is terminal in the engine, so this accumulates."""

    promo_use: float = 0.22
    referral_use: float = 0.3

    quiet_share: float = 0.18
    """How many subscribers stopped turning up while still paying. The cohort the analytics round
    is built around — people whose money still arrives and whose attention has gone."""

    partner_share: float = 0.12
    """How many referrers are on the partners programme rather than the default. Small on purpose:
    a service has a few people with an audience and a lot of people with a friend, and if the two
    programmes held the same number the screen that shows them would be showing one thing twice."""


class EventTally:
    """Counts what a run produced, and passes every event on.

    The engine takes its sink at construction and has exactly one, so a seeder cannot subscribe
    after the fact. This is the composable shape that leaves the journal writer in place: the
    caller builds the engine with `EventTally(then=write_to_journal)` and hands the same object to
    the seeder, which folds the counts into its report.
    """

    __slots__ = ("_earned_by_referrer", "_then", "accruals_by_program", "events")

    def __init__(self, then: Callable[[Event], None] | None = None) -> None:
        self._then = then
        self.accruals_by_program: dict[str, int] = {}
        self._earned_by_referrer: dict[str, int] = {}
        self.events = 0

    def __call__(self, event: Event) -> None:
        self.events += 1
        if isinstance(event, ReferralAccrued):
            self.accruals_by_program[event.program_id] = (
                self.accruals_by_program.get(event.program_id, 0) + 1
            )
            # `user_id` on this event is the REFERRER, the one whose balance grew;
            # `referred_user_id` is whoever paid.
            self._earned_by_referrer[event.user_id] = (
                self._earned_by_referrer.get(event.user_id, 0) + 1
            )
        if self._then is not None:
            self._then(event)

    @property
    def repeat_earners(self) -> int:
        """Referrers paid more than once. Only EVERY_PAYMENT can produce one."""
        return sum(1 for count in self._earned_by_referrer.values() if count > 1)


@dataclass(frozen=True, slots=True)
class Streams:
    """One random stream per kind of decision, all derived from one seed.

    A single shared stream makes every number in the run depend on how many times anything else
    drew from it, so adding a behaviour reshuffles every decision that comes after it. That is not
    hypothetical: adding the partner assignment moved the standing GRACE population from ten to
    one without a single parameter changing, because GRACE is a small transient population and the
    whole sequence shifted underneath it.

    Separate streams make the calibration survive the next feature. Whoever adds sandbox activity
    or a new promotion in a later round should be able to do it without silently reshaping the
    demonstration.
    """

    activity: random.Random
    arrivals: random.Random
    payments: random.Random
    cancels: random.Random
    promos: random.Random
    referrals: random.Random
    partners: random.Random
    names: random.Random

    @classmethod
    def of(cls, seed: int) -> Streams:
        # Distinct constants rather than sequential ones: neighbouring seeds produce correlated
        # first draws in a Mersenne Twister, and correlated streams would defeat the point.
        return cls(
            activity=random.Random(seed ^ 0x5EED_0008),
            arrivals=random.Random(seed ^ 0x5EED_0001),
            payments=random.Random(seed ^ 0x5EED_0002),
            cancels=random.Random(seed ^ 0x5EED_0003),
            promos=random.Random(seed ^ 0x5EED_0004),
            referrals=random.Random(seed ^ 0x5EED_0005),
            partners=random.Random(seed ^ 0x5EED_0006),
            names=random.Random(seed ^ 0x5EED_0007),
        )


@dataclass(slots=True)
class SeedReport:
    """What the run produced, for the log line and for the test."""

    subscribers: int = 0
    events: int = 0
    ticks: int = 0
    states: dict[str, int] = field(default_factory=dict)
    plans: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0

    subscribers_projection: list[tuple[str, str, datetime]] = field(default_factory=list)
    """The projection rows as (user_id, display_name, last_active_at). Plain tuples rather than the
    persistence type: the seeder produces a history and should not know how it is stored."""

    quiet: int = 0
    """How many landed in the quiet cohort. Measured, because a cohort that is empty and a cohort
    that is the whole table are equally useless and both look fine from the code."""

    accruals_by_program: dict[str, int] = field(default_factory=dict)
    """How many referral payouts each programme produced. Measured rather than assumed: both
    programmes existing in the catalogue proves nothing about either one having been exercised."""

    repeat_earners: int = 0
    """Referrers paid more than once, which only EVERY_PAYMENT can produce. If this is zero the
    two programmes are indistinguishable in the data whatever the catalogue says."""


_FIRST = (
    "Alma",
    "Bo",
    "Cyril",
    "Dara",
    "Emil",
    "Fen",
    "Gita",
    "Hugo",
    "Ines",
    "Jonas",
    "Kira",
    "Lars",
    "Mira",
    "Nils",
    "Odile",
    "Piet",
    "Quinn",
    "Rune",
    "Sanna",
    "Tomas",
    "Ulla",
    "Viggo",
    "Wren",
    "Xenia",
    "Yann",
    "Zora",
)
_LAST = (
    "Aaltonen",
    "Bergman",
    "Cortes",
    "Dubois",
    "Eriksen",
    "Farkas",
    "Gallo",
    "Horvat",
    "Ivanov",
    "Jansen",
    "Kovac",
    "Lindqvist",
    "Moreau",
    "Novak",
    "Olsen",
    "Petrov",
    "Rossi",
    "Salo",
    "Tamm",
    "Virtanen",
    "Weber",
    "Zeman",
)


def display_name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"


async def seed_world(
    engine: SubscriptionEngine,
    advance: Callable[[timedelta], datetime],
    now: Callable[[], datetime],
    *,
    seed: int = SEED,
    days: int = HISTORY_DAYS,
    behaviour: Behaviour | None = None,
    tally: EventTally | None = None,
) -> SeedReport:
    """Run the world forward `days` of model time and report what it became.

    `advance` and `now` are the world's clock, passed in rather than reached for: the caller owns
    it, because the base world and a sandbox move theirs for different reasons, and a seeder that
    read `engine._clock` would be coupled to the engine's private shape for no gain.
    """
    started = time.perf_counter()
    streams = Streams.of(seed)
    how = behaviour if behaviour is not None else Behaviour()
    report = SeedReport()

    for plan in PLANS:
        engine.register_plan(plan)
    for promo in PROMO_CODES:
        engine.register_promo_code(promo)
    for program in REFERRAL_PROGRAMS:
        # The engine registers whatever it was given as `default_program` when it was built, and
        # the caller gives it one of these — so one of them is already there and registering it
        # again is a duplicate rather than a mistake.
        with suppress(DuplicateReferralProgram):
            engine.register_referral_program(program)

    names: dict[str, str] = {}
    living: list[str] = []
    partners: set[str] = set()
    ruled_on: dict[str, datetime] = {}
    """The renewal each subscriber has already been decided about, keyed by its due date.

    Without this a subscriber gets a fresh roll on every day their renewal is imminent — the day
    before it falls due and the day it passes before the tick — so `renewal = 0.78` would actually
    mean a 95% chance of paying eventually, and the parameter would not describe what it is named
    after. That is not a rounding difference: it is the whole reason the standing GRACE population
    came out at two instead of ten."""

    for day in range(days):
        advance(timedelta(days=1))

        rate = how.signups_at_start + (how.signups_at_end - how.signups_at_start) * (day / days)
        arrivals = int(rate) + (1 if streams.arrivals.random() < rate % 1 else 0)
        for _ in range(arrivals):
            user_id = f"sub-{len(names):04d}"
            plan = streams.arrivals.choices(PLANS, weights=PLAN_WEIGHTS, k=1)[0]
            names[user_id] = display_name(streams.names)
            referrer = (
                streams.referrals.choice(living)
                if living and streams.referrals.random() < how.referral_use
                else None
            )
            if (
                referrer is not None
                and referrer not in partners
                and streams.partners.random() < how.partner_share
            ):
                # Somebody with an audience. Assigned once, and from then on their referrals earn
                # on every renewal rather than once.
                with suppress(SubstateError):
                    await engine.assign_program(referrer, PARTNERS_PROGRAM.id)
                    partners.add(referrer)
            try:
                await engine.subscribe(user_id, plan.id, referrer_id=referrer)
            except SubstateError:
                # A refusal is part of the model, not a fault: the engine declining a signup is
                # one of the answers this history is supposed to contain.
                continue
            living.append(user_id)
            if streams.promos.random() < how.promo_use:
                with suppress(SubstateError):
                    # A spent code, or one already bound to this subscriber, is a real answer.
                    await engine.redeem(user_id, streams.promos.choice(PROMO_CODES).code)

        for user_id in list(living):
            subscription = await engine.get_subscription(user_id)
            if subscription is None:
                continue
            state = subscription.state
            if state is State.CANCELLED:
                continue

            chance = {
                State.TRIAL: how.trial_conversion
                / max(PLAN_BY_ID[subscription.plan_id].trial_days, 1),
                State.ACTIVE: how.renewal,
                State.GRACE: how.grace_rescue,
                State.EXPIRED: how.revival,
            }.get(state, 0.0)

            # Cancelling is a decision about the subscription, not about a renewal, so it is
            # available on any day rather than only on the one the money is due.
            if state is State.ACTIVE and streams.cancels.random() < how.cancellation:
                with suppress(SubstateError):
                    await engine.cancel(user_id)
                continue

            due = subscription.due_at
            if state is State.ACTIVE:
                # One decision per renewal, taken when it falls due.
                if due is None or due - now() >= timedelta(days=1):
                    continue
                if ruled_on.get(user_id) == due:
                    continue
                ruled_on[user_id] = due

            if streams.payments.random() < chance:
                plan = PLAN_BY_ID[subscription.plan_id]
                with suppress(SubstateError):
                    await engine.apply_payment(
                        Payment(
                            provider="seed",
                            external_id=f"{user_id}-{day}",
                            user_id=user_id,
                            amount=plan.price,
                        )
                    )

        await engine.tick()
        report.ticks += 1

    QUIET_AFTER = timedelta(days=30)
    """The cohort threshold, from the specification: an active subscription whose owner has not
    turned up in a month."""

    moment = now()
    for user_id in living:
        subscription = await engine.get_subscription(user_id)
        if subscription is None:
            continue
        report.states[subscription.state.value] = report.states.get(subscription.state.value, 0) + 1
        report.plans[subscription.plan_id] = report.plans.get(subscription.plan_id, 0) + 1

        # `last_active_at` is drawn from its own stream and is deliberately NOT derived from the
        # payment dates. If it were, a threshold of thirty days against a monthly plan would
        # collect everybody who simply had not logged in since their last renewal, and "went
        # quiet" would come to mean "pays monthly" — a cohort that is true of most of the table
        # and therefore says nothing about anyone.
        if subscription.state is State.CANCELLED:
            last_seen = moment - timedelta(days=streams.activity.uniform(30, 240))
        elif subscription.state is State.EXPIRED:
            last_seen = moment - timedelta(days=streams.activity.uniform(14, 150))
        elif streams.activity.random() < how.quiet_share:
            # Still paying, stopped coming. The people the quiet cohort exists to find.
            last_seen = moment - timedelta(days=streams.activity.uniform(35, 120))
        else:
            last_seen = moment - timedelta(hours=streams.activity.uniform(0, 22 * 24))

        if subscription.state in (State.TRIAL, State.ACTIVE, State.GRACE) and (
            moment - last_seen > QUIET_AFTER
        ):
            report.quiet += 1

        report.subscribers_projection.append((user_id, names.get(user_id, user_id), last_seen))

    report.subscribers = len(living)
    if tally is not None:
        report.accruals_by_program = dict(tally.accruals_by_program)
        report.repeat_earners = tally.repeat_earners
    report.seconds = time.perf_counter() - started
    return report


def names_for(seed: int, count: int) -> dict[str, str]:
    """The display names the run assigns, reproduced without running it."""
    stream = Streams.of(seed).names
    return {f"sub-{i:04d}": display_name(stream) for i in range(count)}
