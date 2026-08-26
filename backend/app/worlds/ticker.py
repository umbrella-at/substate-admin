"""The background task that keeps worlds moving.

`substate` has no scheduler by design: it advances a subscription when somebody asks about it, and
leaves the asking to the application. That is the right split — a library that ran its own timer
would be a library you cannot test in a millisecond — but it means a world nobody visits stands
still, and a demonstration nobody has opened in an hour would show yesterday.

Thirty seconds, and the interval is not load-bearing: nothing in the panel is wrong between ticks,
it is only late, and every read asks the engine for the current state anyway.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta

import structlog

from app.worlds.registry import WorldRegistry

_log = structlog.get_logger(__name__)

TICK_INTERVAL = timedelta(seconds=30)


async def tick_once(
    registry: WorldRegistry,
    publish: Callable[[str, list[object]], Awaitable[None]] | None = None,
) -> int:
    """Advance every live world once. Returns how many events the round produced.

    One world failing does not stop the others: a sandbox that has got itself into a state the
    engine refuses is a reason to lose that sandbox, not everybody's.
    """
    produced = 0
    for world in registry.live():
        try:
            events = await world.engine.tick()
        except Exception as failure:  # deliberately total: one world must not stop the rest
            _log.error(
                "world_tick_failed",
                world_id=world.id,
                error=type(failure).__name__,
                detail=str(failure),
                exc_info=True,
            )
            continue
        if events:
            produced += len(events)
            if publish is not None:
                await publish(world.id, list(events))
    return produced


async def run_ticker(
    registry: WorldRegistry,
    publish: Callable[[str, list[object]], Awaitable[None]] | None = None,
    *,
    interval: timedelta = TICK_INTERVAL,
) -> None:
    """Tick every `interval` until cancelled.

    Cancellation is the normal way this ends — the lifespan cancels it on shutdown — so it is
    allowed through rather than logged as a failure.
    """
    _log.info("ticker_started", interval_seconds=interval.total_seconds())
    try:
        while True:
            await asyncio.sleep(interval.total_seconds())
            produced = await tick_once(registry, publish)
            if produced:
                _log.info("worlds_ticked", events=produced, worlds=len(registry.live()))
    except asyncio.CancelledError:
        _log.info("ticker_stopped")
        raise


@contextlib.asynccontextmanager
async def ticking(
    registry: WorldRegistry,
    publish: Callable[[str, list[object]], Awaitable[None]] | None = None,
    *,
    interval: timedelta = TICK_INTERVAL,
) -> AsyncIterator[asyncio.Task[None]]:
    """Run the ticker for the lifetime of the block, and make sure it is gone afterwards.

    The await on cancellation is not ceremony: without it the task can outlive the loop it was
    started on, and the process holds a reference to a world that is being torn down.
    """
    task = asyncio.create_task(run_ticker(registry, publish, interval=interval))
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
