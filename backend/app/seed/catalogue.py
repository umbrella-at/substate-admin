"""What the base world sells: plans, promo codes, referral programs.

Fixed rather than generated. These are the axes the table filters on, so they have to be stable
enough to write a test against and varied enough that filtering by one of them is a real question.
"""

from __future__ import annotations

from typing import Final

from substate import Accrual, Period, Plan, PromoCode, PromoKind, ReferralProgram

# Prices are integers in minor units, as the engine requires: cents here, so 1350 is $13.50.
# `currency` is a label the engine never reads — it is stored on the plan and travels beside a
# payment, and `Payment` has no currency field at all — so it is the panel that has to keep it
# honest.
PLANS: Final[tuple[Plan, ...]] = (
    Plan(
        id="weekly",
        price=200,
        currency="USD",
        period=Period.days(7),
        trial_days=0,
        grace_days=2,
    ),
    Plan(
        id="monthly",
        price=500,
        currency="USD",
        period=Period.months(1),
        trial_days=14,
        grace_days=5,
    ),
    Plan(
        id="quarterly",
        price=1350,
        currency="USD",
        period=Period.months(3),
        trial_days=14,
        grace_days=7,
    ),
    Plan(
        id="semiannual",
        price=2400,
        currency="USD",
        period=Period.months(6),
        trial_days=14,
        grace_days=7,
    ),
    Plan(
        id="annual",
        price=4200,
        currency="USD",
        period=Period.months(12),
        trial_days=30,
        grace_days=7,
    ),
)
"""One product, five commitments, priced as a ladder: $8.67 a month if you pay weekly, $3.50 if
you pay for a year. The short end being the expensive one is how real subscription pricing works —
you pay a premium for not committing — and it is legible from the table without a word of
explanation.

Five durations rather than four tiers also puts `Period.months(n)` under load. A catalogue of
monthly plans never touches the billing anchor; a subscription that renews on the 31st of January
and has to land somewhere in February does, and now the demonstration contains some.

`grace_days` is bounded by the engine: it raises unless `grace_days < period.min_days`, where
`min_days` is the count for a days-period and 28 per month for a months-period. Two days of grace
on a weekly plan is the tight one, and it is the right shape anyway — a week late on a weekly plan
is not late, it is a skipped period.
"""

PROMO_CODES: Final[tuple[PromoCode, ...]] = (
    PromoCode(code="LAUNCH20", kind=PromoKind.PERCENT, value=20, max_redemptions=120),
    PromoCode(code="WELCOME5", kind=PromoKind.FIXED, value=500, max_redemptions=80),
    PromoCode(code="PLUS14", kind=PromoKind.PLUS_DAYS, value=14, max_redemptions=60),
)

# Two programs, and the pair is the point: they differ on exactly the two knobs `substate` gives a
# referral program, so a screen showing them side by side shows two different things rather than
# two columns of the same number.
#
# `users` is what an ordinary subscriber is on when they bring a friend: ten percent, once, on
# that friend's first payment. `partners` is what somebody with an audience is on: thirty percent,
# on every renewal for as long as the person they brought keeps paying.
USERS_PROGRAM: Final = ReferralProgram(id="users", percent=10, accrual=Accrual.FIRST_PAYMENT_ONLY)
PARTNERS_PROGRAM: Final = ReferralProgram(id="partners", percent=30, accrual=Accrual.EVERY_PAYMENT)

REFERRAL_PROGRAMS: Final[tuple[ReferralProgram, ...]] = (USERS_PROGRAM, PARTNERS_PROGRAM)
"""`USERS_PROGRAM` is the engine's default: a referrer nobody assigned is on it."""

PLAN_BY_ID: Final[dict[str, Plan]] = {plan.id: plan for plan in PLANS}

CURRENCY: Final = PLANS[0].currency
"""What this world sells in, and the reason the revenue figure may add its payments up.

A payment carries no currency — `Payment` has no such field — so a sum over them is only a sum of
money while every plan agrees. The guard below is what keeps that from becoming untrue quietly.
"""

if {plan.currency for plan in PLANS} != {CURRENCY}:
    raise RuntimeError("the catalogue sells in more than one currency; revenue cannot be summed")

# How often each commitment is chosen. The weighting toward short periods is load-bearing rather
# than decorative: GRACE is fed by renewal frequency, and an annual subscriber contributes one
# chance to fall behind per year. A table where most people renew twice a year has nobody in
# arrears to look at on any given day, and the state the design calls "call today" is an empty
# filter.
PLAN_WEIGHTS: Final[tuple[float, ...]] = (0.20, 0.42, 0.19, 0.11, 0.08)
"""In the order of `PLANS`: weekly, monthly, quarterly, semiannual, annual.

Calibrated at exactly these two-decimal values rather than rounded afterwards.
Rounding them changed the standing GRACE population from six to two: `random.choices`
draws the same numbers and maps them differently, so every plan assignment shifts.
What is measured has to be what ships."""
