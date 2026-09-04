"""The registry: world_id -> World, held in memory."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from substate import Event, MemoryStorage, ReferralProgram, SubscriptionEngine

from app.worlds.clock import OffsetClock

if TYPE_CHECKING:
    # Type-only, because the seeder imports the subscriber query, which imports this module. The
    # world holds the population; it does not know how one is produced.
    from app.seed.run import Population

BASE_WORLD_ID = "base"

_collector: ContextVar[list[Event] | None] = ContextVar("world_event_collector", default=None)


@contextmanager
def collecting() -> Iterator[list[Event]]:
    """Gather the events emitted inside this block, and only those.

    A context variable rather than a field on the sink, because the sink belongs to the world and
    the world is shared: the ticker runs as its own task and fills the same buffer, so a request
    that read the buffer would report another subscriber's expiry as something it had just done.
    asyncio copies the context per task, so the ticker's events land in the ticker's collector —
    which is nobody's — and this one sees its own call.
    """
    gathered: list[Event] = []
    token = _collector.set(gathered)
    try:
        yield gathered
    finally:
        _collector.reset(token)


@dataclass(slots=True)
class EventSink:
    """Everything a world emits, on its way to being written down.

    The engine takes its sink once, at construction, and has exactly one — so this is the only
    place a world can watch itself from, and it has to serve every reader rather than the one that
    happened to be built first. Seeding drains it in a single COPY; afterwards the ticker and the
    operation endpoints drain it per round and per request.

    A sink that only collected would be a list that grows for as long as the process lives. That
    is what this replaces: the seeder's closure stayed wired after the seed and every tick for the
    life of the service appended to it, where nothing ever read it again.
    """

    then: Callable[[Event], None] | None = None
    """The seeder's tally, which folds counts into its report. None once the seeding is over."""

    subscribers: set[str] = field(default_factory=set)
    """Who exists in this world.

    The panel keeps this itself because the storage protocol has no way to ask. `substate` offers
    `get_subscription(user_id)` and `iter_due(now)` and nothing that lists — reasonable for an
    engine, useless for a table of everybody. The alternative was reaching into
    `MemoryStorage._subscriptions`, which is a private field that would keep working right up
    until it silently did not.

    Identity only, and it is read off the events rather than guessed from their types: every event
    names its subscriber. The state of a subscription is asked of the engine every time, so this
    index cannot drift into being a second, wrong answer to a question `substate` already answers.
    """

    pending: list[Event] = field(default_factory=list)
    """Emitted, not yet in the journal. Drained by whoever is in an async context to write it."""

    def __call__(self, event: Event) -> None:
        self.subscribers.add(event.user_id)
        self.pending.append(event)
        collector = _collector.get()
        if collector is not None:
            collector.append(event)
        if self.then is not None:
            self.then(event)

    def drain(self) -> list[Event]:
        """Take everything pending and leave the sink empty.

        Synchronous and complete, so two flushes racing each other take disjoint halves rather
        than writing the same event twice.
        """
        taken = self.pending
        self.pending = []
        return taken


@dataclass(slots=True)
class World:
    """One isolated instance of the subscription engine: its own storage, its own clock.

    `expires_at` is None for the base world and set for a sandbox, which is what the reaper reads.
    """

    id: str
    engine: SubscriptionEngine
    clock: OffsetClock
    storage: MemoryStorage
    sink: EventSink
    created_at: datetime
    expires_at: datetime | None = None

    ceiling_at: datetime | None = None
    """The far end, set once. A sandbox is extended by being used, and this is what it is extended
    towards rather than past — without it, a visitor who keeps a tab open keeps a world forever."""

    seeded: bool = False

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """Held by whatever winds this world's clock, so that two presses cannot interleave.

    Measured: two overlapping advances take the second's projection rewrite into a duplicate key
    — its DELETE never saw the first's rows — and the rollback loses the events the advance had
    already drained out of the sink.

    The world moves; a month of its journal does not exist, and the flow and revenue figures read
    flat over months the table says grew.
    """

    population: Population | None = None
    """The seeder's memory of this world, kept so the clock control can go on running it.

    None until the world has been seeded, and for a world that failed to seed. Everything that
    winds the clock has to hold that possibility rather than assume a history.
    """

    @property
    def subscribers(self) -> set[str]:
        """Who exists in this world, as the sink has seen them."""
        return self.sink.subscribers

    @property
    def is_sandbox(self) -> bool:
        """Whether this world is somebody's demonstration rather than the one everybody reads."""
        return self.expires_at is not None

    def alive_at(self, moment: datetime) -> bool:
        return self.expires_at is None or self.expires_at > moment

    def extend(self, *, ttl: timedelta, now: datetime) -> datetime:
        """Push the expiry out to `now + ttl`, never past the ceiling and never backwards.

        Both guards earn their place. Without the ceiling a tab left open holds a world for as long
        as the process lives; without the second, a request arriving late behind a slower one would
        pull the expiry back in and reap a session somebody is using.

        A world with no expiry is the base world, and extending it is a programming error rather
        than a request anybody can make — so it raises instead of quietly doing nothing.
        """
        if self.expires_at is None:
            raise ValueError("the base world does not expire")
        wanted = now + ttl
        if self.ceiling_at is not None:
            wanted = min(wanted, self.ceiling_at)
        self.expires_at = max(self.expires_at, wanted)
        return self.expires_at


@dataclass(slots=True)
class WorldRegistry:
    """Worlds by key, in the memory of one process.

    Every read of subscription data goes through a world, from the first day and not from the day
    sandboxes arrive. Today that is a dictionary lookup; when the storage moves to SQLAlchemy it
    becomes a filter on a `world_id` column. Writing it later would mean rewriting the sandboxes
    rather than swapping a configuration line, and the promise that they are swappable would have
    been untrue in the only way that matters.

    One process, one registry: the unit pins uvicorn to a single worker (decision 48), so there is
    no second copy of this to disagree with.
    """

    _worlds: dict[str, World] = field(default_factory=dict)

    _unpurged: set[str] = field(default_factory=set)
    """Dropped, not yet deleted. On the registry rather than in the module, so that a second
    registry — a test's, or a second process one day — does not inherit the first one's debts."""

    def create(
        self,
        world_id: str | None = None,
        *,
        on_event: Callable[[Event], None] | None = None,
        ttl: timedelta | None = None,
        ceiling: timedelta | None = None,
        offset: timedelta = timedelta(),
        default_program: ReferralProgram | None = None,
    ) -> World:
        """Build a world and put it in the registry, replacing any world of the same id.

        `on_event` is passed through the sink rather than to the engine: the engine accepts one
        sink and accepts it once, so anything that wants to watch a world has to go through the
        one object that already does.

        Replacing rather than refusing is what the base world's rebuild at every start needs, and
        it is a trap for everything else: extending a sandbox means `extend`, because a second
        `create` under the same id silently throws away the world somebody is looking at.
        """
        identifier = world_id if world_id is not None else str(uuid.uuid4())
        clock = OffsetClock(offset)
        storage = MemoryStorage()
        sink = EventSink(then=on_event)
        now = datetime.now(UTC)
        world = World(
            id=identifier,
            engine=SubscriptionEngine(
                storage, clock=clock, on_event=sink, default_program=default_program
            ),
            clock=clock,
            storage=storage,
            sink=sink,
            created_at=now,
            expires_at=None if ttl is None else now + ttl,
            ceiling_at=None if ceiling is None else now + ceiling,
        )
        self._worlds[identifier] = world
        return world

    def get(self, world_id: str) -> World | None:
        return self._worlds.get(world_id)

    def require(self, world_id: str) -> World:
        world = self._worlds.get(world_id)
        if world is None:
            raise KeyError(world_id)
        return world

    def drop(self, world_id: str) -> bool:
        """Take a world out of the process, and remember that its rows are still on disk.

        Dropping and purging are two steps and the second can fail, so the registry keeps the
        list: without it a dropped world is one `expired()` never names again, and its four
        thousand journal rows wait for a restart that might be days away.
        """
        gone = self._worlds.pop(world_id, None) is not None
        if gone:
            self._unpurged.add(world_id)
        return gone

    def unpurged(self) -> tuple[str, ...]:
        """Worlds this process has dropped whose rows nobody has deleted yet."""
        return tuple(sorted(self._unpurged))

    def purged(self, world_id: str) -> None:
        self._unpurged.discard(world_id)

    def all(self) -> tuple[World, ...]:
        """Every world this process holds, expired ones included.

        What a purge of rows belonging to worlds nobody remembers has to be given. Handing it
        `live()` instead deletes the journal of a sandbox that has lapsed but not yet been reaped
        — out from under a visitor who is still holding a token for it.
        """
        return tuple(self._worlds.values())

    def live(self, now: datetime | None = None) -> tuple[World, ...]:
        """Every world that has not expired, base first."""
        moment = now if now is not None else datetime.now(UTC)
        alive = [w for w in self._worlds.values() if w.alive_at(moment)]
        alive.sort(key=lambda w: (w.id != BASE_WORLD_ID, w.created_at))
        return tuple(alive)

    def expired(self, now: datetime | None = None) -> tuple[World, ...]:
        moment = now if now is not None else datetime.now(UTC)
        return tuple(w for w in self._worlds.values() if not w.alive_at(moment))

    def sandboxes(self) -> tuple[World, ...]:
        """Every world that is somebody's demonstration. What the ceiling is counted against."""
        return tuple(w for w in self._worlds.values() if w.is_sandbox)

    def __len__(self) -> int:
        return len(self._worlds)


_registry: WorldRegistry | None = None


def get_registry() -> WorldRegistry:
    """The process's registry, built on first use for the same reason the engine is."""
    global _registry
    if _registry is None:
        _registry = WorldRegistry()
    return _registry


def reset_registry() -> None:
    """Drop the registry. For tests, which must not inherit another test's worlds."""
    global _registry
    _registry = None
