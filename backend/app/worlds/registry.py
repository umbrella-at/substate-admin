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
class World:
    """One isolated instance of the subscription engine: its own storage, its own clock.

    `expires_at` is None for the base world and set for a sandbox, which is what the reaper reads.
    """

    id: str
    engine: SubscriptionEngine
    clock: OffsetClock
    storage: MemoryStorage
    created_at: datetime
    expires_at: datetime | None = None
    seeded: bool = False

    subscribers: set[str] = field(default_factory=set)
    """Who exists in this world.

    The panel keeps this itself because the storage protocol has no way to ask. `substate` offers
    `get_subscription(user_id)` and `iter_due(now)` and nothing that lists — reasonable for an
    engine, useless for a table of everybody. The alternative was reaching into
    `MemoryStorage._subscriptions`, which is a private field that would keep working right up
    until it silently did not.

    Only identity lives here. The state of a subscription is asked of the engine every time, so
    this index cannot drift into being a second, wrong answer to a question `substate` already
    answers. When the SQLAlchemy storage arrives with a real query interface, this goes.
    """


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
        """Build a world and put it in the registry, replacing any world of the same id."""
        identifier = world_id if world_id is not None else str(uuid.uuid4())
        clock = OffsetClock(offset)
        storage = MemoryStorage()
        now = datetime.now(UTC)
        world = World(
            id=identifier,
            engine=SubscriptionEngine(
                storage, clock=clock, on_event=on_event, default_program=default_program
            ),
            clock=clock,
            storage=storage,
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
