"""A clock that runs, with an offset laid on top."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class OffsetClock:
    """Real time plus an offset that only ever moves forward.

    Not a frozen clock. A demonstration whose clock stands still reads as a broken service — the
    relative times stop updating, "3 minutes ago" stays 3 minutes ago, and the visitor concludes
    the page is stale rather than that they are looking at a model. The world keeps running on its
    own; fast-forwarding is laid over the top of that.

    Backwards is refused rather than clamped. `substate` is built for monotonic time: a
    subscription's due date is compared against now, and moving now backwards produces states the
    engine could never have reached by itself — a renewed period that has not been paid for, a
    grace that ends before it began. A refusal is a bug report; a clamp is the same bug arriving
    later and somewhere else.

    **A negative starting offset is not a backwards move, and the distinction is the whole reason
    the seeder needs no second clock.** Starting nine months behind and stepping forward to zero
    never moves time backwards even once: the offset only ever increases. What is forbidden is
    `advance` with a negative delta, and that stays forbidden. Reading this class as "offsets are
    always positive" is the mistake this paragraph exists to prevent — it would push the seeder
    onto a simulation clock of its own, and then the nine months of history would be produced by
    code that no visitor ever runs.

    Seeding on the same clock the time machine uses means the fast-forward is exercised nine
    months' worth before anyone builds a control for it.
    """

    __slots__ = ("_offset",)

    def __init__(self, offset: timedelta = timedelta()) -> None:
        self._offset = offset

    @property
    def offset(self) -> timedelta:
        return self._offset

    def now(self) -> datetime:
        return datetime.now(UTC) + self._offset

    def advance(self, delta: timedelta) -> datetime:
        """Move the world forward by `delta` and report the new moment."""
        if delta < timedelta():
            raise ValueError("time in a world only moves forward")
        self._offset += delta
        return self.now()

    @property
    def is_live(self) -> bool:
        """Whether this world is caught up with real time.

        The seeder finishes at exactly zero, not near it. `timedelta` arithmetic is exact — it
        holds whole microseconds — so a run of equal steps lands on the mark rather than drifting,
        and the seeder asserts it. A world left a few seconds behind would look right and would
        stay behind for as long as the process lives.
        """
        return self._offset == timedelta()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(offset={self._offset!r})"
