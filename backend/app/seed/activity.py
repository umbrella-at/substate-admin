"""When somebody last turned up, and what the time machine does to that.

`last_active_at` is the one column the engine has never heard of. It is not traffic and not a
counter: it is the mark that a person came back, and the Quiet cohort is the whole reason it
exists — an active subscription whose owner has not.

WHICH IS WHY IT CANNOT STAND STILL WHILE THE CLOCK MOVES.

Wind a demonstration forward a month with the column frozen and every paying subscriber is a month
silent: measured on the base world, the cohort goes from 46 of 272 to 272 of 272.

The figure that says "paid for and unused" comes to say "everybody", at exactly the moment a
visitor pressed the button to see what changed.

So an advance re-draws the column from the same windows the history used, and two rules hold it
honest. Being one of the quiet ones is drawn once and kept, which is what leaves the cohort a
share rather than emptying it as the clock is pressed again.

And the mark only ever moves forward: without that, a re-draw could file a subscriber as three
months silent who was here yesterday, and the panel would show activity un-happening.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Final

from substate import State

from app.subscribers.query import QUIET_AFTER

__all__ = ["FRESHEST", "LIVE", "QUIET_AFTER", "last_seen_at", "window_for"]

FRESHEST: Final = timedelta(hours=1)
"""How recent the most recently active subscriber is allowed to be.

These timestamps are written once and then stand still while the panel is looked at, and the
column renders them as "how long ago". A subscriber seeded at four minutes reads as "4 minutes
ago" on the first screen and "44 minutes ago" half an hour later, having done nothing.

An hour is where that claim stops being made: the value still ages, but by a unit slow enough that
a session's worth of drift is indistinguishable from the truth.
"""

LIVE: Final = (State.TRIAL, State.ACTIVE, State.GRACE)
"""The states an advance re-draws activity for. Somebody whose subscription ended stopped turning
up when it ended, and moving their mark forward would say otherwise."""

# Measured back from the moment the world is at. The four are not interchangeable: the gap between
# a cancelled subscriber and a quiet one is what makes the cohort mean anything.
QUIET_WINDOW: Final = (timedelta(days=35), timedelta(days=120))
PRESENT_WINDOW: Final = (FRESHEST, timedelta(days=22))
EXPIRED_WINDOW: Final = (timedelta(days=14), timedelta(days=150))
CANCELLED_WINDOW: Final = (timedelta(days=30), timedelta(days=240))


def window_for(state: State, *, quiet: bool) -> tuple[timedelta, timedelta]:
    """How long ago somebody in this state was last here, as a range to draw from.

    `quiet` is a fact about the person rather than about the subscription, which is why it is
    passed in: it is drawn once and remembered, so that winding the clock twice does not
    eventually rescue everybody who had gone quiet.
    """
    if state is State.CANCELLED:
        return CANCELLED_WINDOW
    if state is State.EXPIRED:
        return EXPIRED_WINDOW
    return QUIET_WINDOW if quiet else PRESENT_WINDOW


def last_seen_at(
    stream: random.Random,
    window: tuple[timedelta, timedelta],
    *,
    moment: datetime,
    age: timedelta,
) -> datetime:
    """One draw from `window`, clipped to a life and floored at an hour.

    BOUNDED BY THE SUBSCRIBER'S OWN AGE, WHICH IS THE LARGER OF THE TWO HONESTY PROBLEMS HERE.

    Each window is a fixed span measured back from now, and arrivals ramp up over a history, so
    most subscribers are younger than the window they are drawn from.

    Left alone that produced activity from before the person existed: measured on the base seed,
    87 of 351 rows, the worst by 181 days, and nineteen of the twenty-four trials.

    A fourteen-day trial two days old reporting its owner last seen three months ago, in a cohort
    somebody is invited to click. A date column hid that; a column saying "3 months ago" next to a
    trial that started on Tuesday does not.

    Where the whole window falls outside that life it collapses to its end, which reads as "last
    seen when they signed up" — true, and the most that can be said. The floor wins over the clip
    when the two disagree, which they do only for somebody who arrived within the last hour.
    """
    low, high = window
    high = min(high, age)
    low = min(low, high)
    gap = low + (high - low) * stream.random()
    return moment - max(gap, FRESHEST)
