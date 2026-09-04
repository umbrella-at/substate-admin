"""A world of somebody's own: how one is built, how long it lives, and what dies with it.

WHAT A SANDBOX COSTS, MEASURED RATHER THAN GUESSED.

Half a megabyte of memory, held flat over thirty worlds in one process. A seventh of a second of
one CPU to seed, which is a seventh of a second the single worker is not answering anybody else.

About four thousand journal rows and three hundred and fifty projection rows, written by COPY and
deleted again when the world ends.

So memory is not the constraint, and that is the finding: the ceiling below is set by the database
churn and by the fact that seeding blocks the loop, not by the two gigabytes on the box.

Thirty-two worlds is eighteen megabytes and a hundred and twenty thousand journal rows — the base
world writes four thousand of those at every restart, so it is thirty-two restarts' worth at once.

The ceiling is the bound that matters; the rate limit on creation is what stops one address from
spending it in a second. A third valve counting live worlds per address was considered and left
out: it would bound nothing these two do not, at the cost of a third place to be wrong.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.demo.operators import populate
from app.models import DemoSandbox
from app.seed.catalogue import USERS_PROGRAM
from app.seed.run import HISTORY_DAYS, SEED, seed_world
from app.worlds.journal import ProjectedSubscriber, purge_sandbox, write_events, write_projection
from app.worlds.registry import World, WorldRegistry

_log = structlog.get_logger(__name__)

SANDBOX_TTL: Final = timedelta(minutes=60)
"""How long a sandbox has left after the last time it was used."""

SANDBOX_CEILING: Final = timedelta(hours=2)
"""And how long it may have from the moment it was built, whatever it does with the hour above."""

MAX_SANDBOXES: Final = 32
"""How many may stand at once. See the module docstring for what one costs and why this number."""


class SandboxesAreFull(Exception):
    """The ceiling is reached. The caller answers with the base world on offer instead."""


@dataclass(frozen=True, slots=True)
class Sandbox:
    """A world somebody may drive, and the account they drive it as."""

    world: World
    user_id: uuid.UUID
    expires_at: datetime


async def open_sandbox(
    session: AsyncSession, registry: WorldRegistry, *, ip_hash: str, now: datetime
) -> Sandbox:
    """Build a world, run its history through it, and give it operators of its own.

    Everything here rides on the caller's transaction, including the two COPYs — so a sandbox that
    fails halfway leaves no rows at all, rather than a journal with nobody to read it. The world
    itself is not transactional, which is what the registry drop below is for.
    """
    if len(registry.sandboxes()) >= MAX_SANDBOXES:
        raise SandboxesAreFull

    world = registry.create(
        str(uuid.uuid4()),
        ttl=SANDBOX_TTL,
        ceiling=SANDBOX_CEILING,
        offset=timedelta(days=-HISTORY_DAYS),
        default_program=USERS_PROGRAM,
    )
    try:
        report, population = await seed_world(
            world.engine, world.clock.advance, world.clock.now, days=HISTORY_DAYS
        )
        world.population = population
        world.seeded = True

        connection = await session.connection()
        await write_events(connection, world.id, world.sink.drain())
        await write_projection(
            connection,
            world.id,
            [
                ProjectedSubscriber(user_id=uid, display_name=name, last_active_at=seen)
                for uid, name, seen in report.subscribers_projection
            ],
        )
        session.add(
            DemoSandbox(
                world_id=world.id,
                expires_at=world.expires_at,
                ceiling_at=world.ceiling_at,
                ip_hash=ip_hash,
            )
        )
        user_id = await populate(session, world_id=world.id, seed=SEED)
    except Exception:
        # A world left in the registry after a failed build is one nobody can reach and nothing
        # will collect until its hour is up, and it spends a slot under the ceiling meanwhile.
        registry.drop(world.id)
        raise

    expires_at = world.expires_at
    if expires_at is None:  # pragma: no cover - create() was given a ttl twenty lines above
        raise RuntimeError("a sandbox was built without an expiry")

    _log.info(
        "sandbox_opened",
        world_id=world.id,
        subscribers=report.subscribers,
        seconds=round(report.seconds, 3),
        standing=len(registry.sandboxes()),
    )
    return Sandbox(world=world, user_id=user_id, expires_at=expires_at)


async def extend_sandbox(session: AsyncSession, world: World, *, now: datetime) -> datetime:
    """Push a sandbox's expiry out, and record where it was pushed to.

    The row is the half of this that outlives the process, and it is written here rather than on
    every request: extending in the identity resolver would be a write riding on whatever
    transaction the request happened to have, rolled back by every refusal.
    """
    expires_at = world.extend(ttl=SANDBOX_TTL, now=now)
    await session.execute(
        update(DemoSandbox).where(DemoSandbox.world_id == world.id).values(expires_at=expires_at)
    )
    return expires_at


async def reap(registry: WorldRegistry, engine: AsyncEngine, *, now: datetime | None = None) -> int:
    """Collect every sandbox whose time is up. Returns how many went.

    Dropped from the registry first and purged second, so that nothing can read or write for a
    world while its rows are being deleted.

    A purge that fails then leaves rows behind and no world, which the orphan sweep at the next
    start collects — the alternative is a visitor reading a table halfway through being emptied.
    """
    moment = now if now is not None else datetime.now(UTC)
    doomed = [world for world in registry.expired(moment) if world.is_sandbox]
    for world in doomed:
        registry.drop(world.id)
        async with engine.begin() as connection:
            await purge_sandbox(connection, world.id)
        _log.info("sandbox_reaped", world_id=world.id, standing=len(registry.sandboxes()))
    return len(doomed)
