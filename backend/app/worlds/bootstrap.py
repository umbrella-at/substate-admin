"""Building the base world and putting its history in the database.

Rebuilt at every start, from the seeder, deterministically. The purge is part of that rather than
a command somebody runs: the base world produces about four thousand events each time it is built,
and restarts happen for reasons nobody plans — a deploy, an OOM, a kernel upgrade. An append-only
journal would hold half a million rows of dead history within a month of ordinary operation, and
the first person to notice would be a visitor waiting on a slow feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from app.seed.catalogue import USERS_PROGRAM
from app.seed.run import HISTORY_DAYS, EventTally, seed_world
from app.worlds.journal import (
    ProjectedSubscriber,
    purge_orphans,
    purge_world,
    write_events,
    write_projection,
)
from app.worlds.registry import BASE_WORLD_ID, World, WorldRegistry

_log = structlog.get_logger(__name__)


@dataclass(slots=True)
class BaseWorldStatus:
    """Whether the demonstration has a world behind it, and what it cost to build.

    Reported by GET /api/health. A world that failed to seed is a bad shop window, not an outage:
    signing in works, permissions work, the panel serves. Answering 503 for it would make a deploy
    roll itself back over a cosmetic problem.
    """

    seeded: bool = False
    subscribers: int = 0
    events: int = 0
    seconds: float = 0.0
    error: str | None = None


async def build_base_world(
    registry: WorldRegistry, engine: AsyncEngine, *, days: int = HISTORY_DAYS
) -> tuple[World, BaseWorldStatus]:
    """Create the base world, run nine months through it, and record what happened.

    Never raises. The unit restarts on failure, so an exception here would be a crash loop that
    can only be broken from the provider's console; a panel with an empty world can be repaired by
    reading the journal.
    """
    status = BaseWorldStatus()
    tally = EventTally()

    # Nine months behind, stepping forward to exactly zero. A negative starting offset is not a
    # backwards move — see OffsetClock — which is why the seeder needs no clock of its own and the
    # fast-forward is exercised nine months' worth before anyone builds a control for it.
    world = registry.create(
        BASE_WORLD_ID,
        on_event=tally,
        offset=timedelta(days=-days),
        default_program=USERS_PROGRAM,
    )
    try:
        report, population = await seed_world(
            world.engine, world.clock.advance, world.clock.now, days=days, tally=tally
        )
        if not world.clock.is_live:
            raise RuntimeError(f"the base world finished at offset {world.clock.offset}, not zero")

        async with engine.begin() as connection:
            # Purge and write in ONE transaction: a crash between them would leave the journal
            # empty against a world that has a history, which reads as data loss rather than as a
            # restart.
            await purge_world(connection, BASE_WORLD_ID)
            await purge_orphans(connection, [w.id for w in registry.all()])
            written = await write_events(connection, BASE_WORLD_ID, world.sink.drain())
            await write_projection(
                connection,
                BASE_WORLD_ID,
                [
                    ProjectedSubscriber(user_id=uid, display_name=name, last_active_at=seen)
                    for uid, name, seen in report.subscribers_projection
                ],
            )

        # The tally has counted what it was built to count. Left attached it would go on counting
        # every tick and every operation into a report nobody asks for again.
        world.sink.then = None
        world.seeded = True
        world.population = population
        status = BaseWorldStatus(
            seeded=True,
            subscribers=report.subscribers,
            events=written,
            seconds=report.seconds,
        )
        _log.info(
            "base_world_seeded",
            subscribers=report.subscribers,
            events=written,
            quiet=report.quiet,
            seconds=round(report.seconds, 3),
            states=report.states,
        )
    except Exception as failure:  # deliberately total: see the docstring
        status = BaseWorldStatus(seeded=False, error=type(failure).__name__)
        _log.error(
            "base_world_seed_failed",
            error=type(failure).__name__,
            detail=str(failure),
            exc_info=True,
        )
    return world, status


_status = BaseWorldStatus()


def set_base_world_status(status: BaseWorldStatus) -> None:
    """Record what the last build produced, for `GET /api/health` to report."""
    global _status
    _status = status


def base_world_status() -> BaseWorldStatus:
    return _status
