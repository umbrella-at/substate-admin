"""The registry: world_id -> World, held in memory."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from substate import Event, MemoryStorage, ReferralProgram, SubscriptionEngine

from app.worlds.clock import OffsetClock

BASE_WORLD_ID = "base"


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
    seeded: bool = False

    @property
    def subscribers(self) -> set[str]:
        """Who exists in this world, as the sink has seen them."""
        return self.sink.subscribers


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

    def create(
        self,
        world_id: str | None = None,
        *,
        on_event: Callable[[Event], None] | None = None,
        ttl: timedelta | None = None,
        offset: timedelta = timedelta(),
        default_program: ReferralProgram | None = None,
    ) -> World:
        """Build a world and put it in the registry, replacing any world of the same id.

        `on_event` is passed through the sink rather than to the engine: the engine accepts one
        sink and accepts it once, so anything that wants to watch a world has to go through the
        one object that already does.
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
        return self._worlds.pop(world_id, None) is not None

    def live(self) -> tuple[World, ...]:
        """Every world that has not expired, base first."""
        now = datetime.now(UTC)
        alive = [w for w in self._worlds.values() if w.expires_at is None or w.expires_at > now]
        alive.sort(key=lambda w: (w.id != BASE_WORLD_ID, w.created_at))
        return tuple(alive)

    def expired(self) -> tuple[World, ...]:
        now = datetime.now(UTC)
        return tuple(
            w for w in self._worlds.values() if w.expires_at is not None and w.expires_at <= now
        )

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
