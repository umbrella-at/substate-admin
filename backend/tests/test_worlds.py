"""What a world emits, and where it ends up.

The engine takes its sink once and keeps it for life, so whatever is handed over at construction
is what the world is watched by forever. The seeder used to hand over a closure that appended to a
list on its own stack: correct while the seed ran, and afterwards a list that every tick for the
rest of the process appended to and nothing ever read. Two failures in one, and neither of them
looks like anything — the journal simply stops growing while the process quietly does.

So the sink is a thing rather than a closure, and these tests are about the two halves of that:
what it holds, and who empties it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from conftest import TEST_DATABASE_URL
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool
from substate import Event, Period, Plan, State, SubscriptionCreated

from app.worlds.bootstrap import build_base_world
from app.worlds.journal import flush_world, purge_world
from app.worlds.registry import BASE_WORLD_ID, EventSink, World, WorldRegistry, collecting
from app.worlds.ticker import tick_once

MONTHLY = Plan(
    id="monthly",
    price=500,
    currency="USD",
    period=Period.months(1),
    trial_days=14,
    grace_days=5,
)
"""A trial is what makes a subscription able to move on its own: without one `subscribe` starts
the record already expired, and a tick has nothing left to do to it."""


def _event(user_id: str) -> Event:
    return SubscriptionCreated(user_id, datetime.now(UTC), plan_id="monthly", state=State.TRIAL)


async def _world_with_one_subscriber(world_id: str = "test") -> World:
    """A world holding exactly one live subscription, and nothing left to write down."""
    world = WorldRegistry().create(world_id)
    world.engine.register_plan(MONTHLY)
    await world.engine.subscribe("sub-0001", "monthly")
    world.sink.drain()
    return world


def test_the_sink_records_who_the_event_names_and_keeps_the_event() -> None:
    sink = EventSink()
    sink(_event("sub-0001"))
    sink(_event("sub-0002"))

    assert sink.subscribers == {"sub-0001", "sub-0002"}
    assert len(sink.pending) == 2


def test_draining_the_sink_hands_over_everything_and_leaves_it_empty() -> None:
    """Both halves. A drain that copied rather than took would write every event twice from the
    second flush onwards, and the feed would read as a service doing everything in duplicate."""
    sink = EventSink()
    sink(_event("sub-0001"))

    taken = sink.drain()

    assert len(taken) == 1
    assert sink.pending == []
    assert sink.drain() == []


def test_the_sink_passes_the_event_on_to_whoever_asked_to_see_it() -> None:
    seen: list[Event] = []
    sink = EventSink(then=seen.append)

    sink(_event("sub-0001"))

    assert len(seen) == 1
    # The index is not the observer's job, and an observer that failed to be attached must not
    # take it down with it.
    assert sink.subscribers == {"sub-0001"}


async def test_a_world_built_by_the_registry_is_watched_by_its_own_sink() -> None:
    """The registry is the only place a world is constructed, so this is the only place the sink
    can be attached — the engine will not accept a second one later."""
    world = WorldRegistry().create("test")
    world.engine.register_plan(MONTHLY)

    await world.engine.subscribe("sub-0001", "monthly")

    assert world.subscribers == {"sub-0001"}
    assert [type(event).name for event in world.sink.pending] == ["subscription.created"]


async def test_what_a_world_emits_after_it_was_seeded_reaches_the_journal(
    connection: AsyncConnection,
) -> None:
    """The operation endpoints and the ticker both go through this, and it is the whole reason the
    card's feed shows what somebody just did rather than what the last restart left behind."""
    world = await _world_with_one_subscriber()

    await world.engine.cancel("sub-0001")
    written = await flush_world(connection, world)

    types = (
        await connection.execute(
            text(
                "SELECT type FROM admin.event_journal "
                "WHERE world_id = :world AND user_id = :user ORDER BY occurred_at"
            ),
            {"world": world.id, "user": "sub-0001"},
        )
    ).scalars()
    assert written == 1
    assert list(types) == ["subscription.cancelled"]
    assert world.sink.pending == []


async def test_a_world_with_nothing_to_say_writes_no_rows(connection: AsyncConnection) -> None:
    """A flush on an idle world is a no-op rather than an empty COPY: the ticker calls this every
    thirty seconds for the life of the process."""
    world = await _world_with_one_subscriber()

    assert await flush_world(connection, world) == 0


async def test_the_ticker_hands_over_only_a_world_that_has_something_pending() -> None:
    recorded: list[str] = []

    async def record(world: World) -> None:
        recorded.append(world.id)

    registry = WorldRegistry()
    quiet = registry.create("quiet")
    quiet.engine.register_plan(MONTHLY)

    assert await tick_once(registry, record) == 0
    assert recorded == []

    await quiet.engine.subscribe("sub-0001", "monthly")
    await tick_once(registry, record)

    assert recorded == ["quiet"]


async def test_seeding_leaves_the_sink_empty_and_the_tally_detached() -> None:
    """The seed's own events are written in one COPY and the tally has finished counting. Anything
    still attached afterwards is something that grows for as long as the service runs.

    Its own engine rather than the suite's connection: `build_base_world` opens a transaction of
    its own and commits it, which is the behaviour under test, so the rows are purged by hand.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    registry = WorldRegistry()
    try:
        world, status = await build_base_world(registry, engine, days=2)

        assert status.seeded is True
        assert world.sink.then is None
        assert world.sink.pending == []
        assert status.events > 0
        # The index is filled off the events, so it is complete before the first tick rather than
        # filling up as one.
        assert len(world.subscribers) == status.subscribers
    finally:
        async with engine.begin() as connection:
            await purge_world(connection, BASE_WORLD_ID)
        await engine.dispose()


async def test_a_world_that_ticks_after_seeding_keeps_filling_the_journal() -> None:
    """The failure this whole file is about: the sink stayed wired to the seeder's list, so every
    event after the seed went somewhere nothing would ever read again."""
    world = await _world_with_one_subscriber()

    world.clock.advance(timedelta(days=400))
    await world.engine.tick()

    assert [type(event).name for event in world.sink.pending] == ["subscription.expired"]


async def test_events_from_another_task_are_not_reported_as_this_call() -> None:
    """The sink is one buffer per world and the ticker fills it too.

    An operation that read the buffer would hand its caller another subscriber's expiry and
    narrate it as something the operator had just done. The collector is a context variable, and
    the ticker's task is created at start-up — outside any request — so its context carries none.
    """
    world = await _world_with_one_subscriber()
    world.engine.register_plan(Plan(id="weekly", price=200, currency="USD", period=Period.days(7)))
    await world.engine.subscribe("sub-0002", "weekly")
    world.sink.drain()

    running = asyncio.Event()
    finished = asyncio.Event()

    async def elsewhere() -> None:
        await running.wait()
        await world.engine.cancel("sub-0002")
        finished.set()

    # Created BEFORE the block, which is the whole mechanism: a task copies the context it was
    # created in, so this one carries no collector however long it runs inside the block.
    task = asyncio.create_task(elsewhere())
    try:
        with collecting() as mine:
            running.set()
            await finished.wait()
            await world.engine.cancel("sub-0001")
    finally:
        await task

    assert [event.user_id for event in mine] == ["sub-0001"]
    # Both are still in the journal's queue: the other task's event is somebody's row, it is only
    # not this call's answer.
    assert {event.user_id for event in world.sink.pending} == {"sub-0001", "sub-0002"}
