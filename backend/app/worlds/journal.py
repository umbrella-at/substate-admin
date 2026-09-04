"""Persisting a world's events and its subscriber projection.

Two rules hold this table down, and both are here rather than in a command somebody has to
remember to run.

A world's rows are deleted as part of seeding it, in the same transaction that writes the new
ones. The base world is rebuilt at every start and produces about four thousand events each time;
restarts are more frequent than they feel, so an append-only journal reaches half a million rows
of dead history in a month of ordinary deploys. The first person to notice would not be us — it
would be a visitor waiting on a slow feed.

Rows are written with COPY. Measured on the deployment host, 3327 rows: 53 ms by COPY, 226 ms by
executemany, 3317 ms one INSERT at a time. The last one is a third of the smoke check's window
spent on a task that has nothing to do with serving anybody, and it grows with the world.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from substate import Event

from app.worlds.registry import World

# Spelled out rather than interpolated. The schema is fixed, the migrations hardcode it for
# the same reason, and a table name built by an f-string is a table name a reader has to
# reconstruct before they can be sure what it is.


@dataclass(frozen=True, slots=True)
class ProjectedSubscriber:
    """One row of the projection: what the panel knows and the engine does not."""

    user_id: str
    display_name: str
    last_active_at: datetime | None


def payload_of(event: Event) -> dict[str, object]:
    """Whatever the event carried beyond the columns that index it.

    Read off the dataclass rather than enumerated per event type: a new event in a later version
    of the engine should land in the journal complete, not silently trimmed to the fields this
    function happened to know about.
    """
    fields = {
        key: value
        for key, value in vars(event).items()
        if key not in {"user_id", "occurred_at"} and not key.startswith("_")
    }
    return {key: _plain(value) for key, value in fields.items()}


def _plain(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, str | int | float | bool):
        return value.value
    return value


async def purge_world(connection: AsyncConnection, world_id: str) -> int:
    """Delete everything recorded for a world. Returns how many journal rows went."""
    result = await connection.execute(
        text("DELETE FROM admin.event_journal WHERE world_id = :world"), {"world": world_id}
    )
    await connection.execute(
        text("DELETE FROM admin.subscriber_view WHERE world_id = :world"), {"world": world_id}
    )
    return result.rowcount or 0


async def purge_orphans(connection: AsyncConnection, live_world_ids: Sequence[str]) -> int:
    """Delete rows belonging to worlds that no longer exist.

    A world that went away without being purged — a sandbox whose process died, a world whose id
    changed between releases — leaves rows nothing will ever read and nothing will ever delete.
    Cheap to run at start-up, and the only thing standing between this table and rows from worlds
    nobody remembers.
    """
    if not live_world_ids:
        return 0
    ids = list(live_world_ids)

    # The same order purge_sandbox keeps, and for the same two RESTRICT keys. A restart is where
    # this matters most: sandboxes live in memory, so every one of them is an orphan by the time
    # this runs, and their operators would otherwise pile up across deploys.
    await connection.execute(
        text(
            "DELETE FROM admin.audit_log WHERE actor_user_id IN "
            "(SELECT id FROM admin.users WHERE world_id IS NOT NULL AND world_id <> ALL(:ids))"
        ),
        {"ids": ids},
    )
    await connection.execute(
        text("DELETE FROM admin.users WHERE world_id IS NOT NULL AND world_id <> ALL(:ids)"),
        {"ids": ids},
    )
    await connection.execute(
        text("DELETE FROM admin.roles WHERE world_id IS NOT NULL AND world_id <> ALL(:ids)"),
        {"ids": ids},
    )
    result = await connection.execute(
        text("DELETE FROM admin.event_journal WHERE world_id <> ALL(:ids)"), {"ids": ids}
    )
    await connection.execute(
        text("DELETE FROM admin.subscriber_view WHERE world_id <> ALL(:ids)"), {"ids": ids}
    )
    await connection.execute(
        text("DELETE FROM admin.demo_sandboxes WHERE world_id <> ALL(:ids)"), {"ids": ids}
    )
    return result.rowcount or 0


async def write_events(connection: AsyncConnection, world_id: str, events: Iterable[Event]) -> int:
    """COPY a world's events into the journal. Returns how many rows were written."""
    driver = (await connection.get_raw_connection()).driver_connection
    if driver is None:  # pragma: no cover - a live AsyncConnection always has one
        raise RuntimeError("no driver connection to COPY through")
    written = 0
    statement = (
        "COPY admin.event_journal (world_id, type, user_id, occurred_at, payload_json) FROM STDIN"
    )
    async with driver.cursor() as cursor, cursor.copy(statement) as copy:
        for event in events:
            await copy.write_row(
                (
                    world_id,
                    type(event).name,
                    event.user_id,
                    event.occurred_at,
                    json.dumps(payload_of(event)),
                )
            )
            written += 1
    return written


async def flush_world(connection: AsyncConnection, world: World) -> int:
    """Write whatever a world has emitted since the last flush. Returns how many rows went.

    Called after every operation and after every tick, so the feed on a subscriber's card shows
    what just happened rather than what happened before the service last restarted. Draining
    first and writing second means a failed write loses those rows; the alternative is a buffer
    that grows for as long as the database is unreachable, and this journal is rebuilt from the
    seeder at every start anyway.
    """
    events = world.sink.drain()
    if not events:
        return 0
    return await write_events(connection, world.id, events)


async def write_projection(
    connection: AsyncConnection, world_id: str, subscribers: Iterable[ProjectedSubscriber]
) -> int:
    """COPY the subscriber projection for a world."""
    driver = (await connection.get_raw_connection()).driver_connection
    if driver is None:  # pragma: no cover - a live AsyncConnection always has one
        raise RuntimeError("no driver connection to COPY through")
    written = 0
    statement = (
        "COPY admin.subscriber_view (world_id, user_id, display_name, last_active_at) FROM STDIN"
    )
    async with driver.cursor() as cursor, cursor.copy(statement) as copy:
        for subscriber in subscribers:
            await copy.write_row(
                (world_id, subscriber.user_id, subscriber.display_name, subscriber.last_active_at)
            )
            written += 1
    return written


async def rewrite_projection(
    connection: AsyncConnection, world_id: str, subscribers: Iterable[ProjectedSubscriber]
) -> int:
    """Replace a world's projection with this one.

    Delete and COPY rather than an upsert, because COPY cannot carry ON CONFLICT and this table
    is a few hundred rows.

    The pair has to be one transaction: between them the world has no names and no activity at
    all, and every reader treats a missing row as "never here".

    Not `purge_world`, which would take the event journal with it — and the funnel, the flow and
    the revenue figures are read from that journal.
    """
    await connection.execute(
        text("DELETE FROM admin.subscriber_view WHERE world_id = :world"), {"world": world_id}
    )
    return await write_projection(connection, world_id, subscribers)


async def purge_sandbox(connection: AsyncConnection, world_id: str) -> None:
    """Delete everything one sandbox owns, in the only order the foreign keys allow.

    `audit_log.actor_user_id` and `users.role_id` are both ON DELETE RESTRICT, so the audit goes
    before its actors and the operators before their roles.

    Nothing in the database enforces the sequence — there is no worlds table to hang a cascade off
    — so it is four statements somebody keeps in order, which is why they are here and not spread
    across callers.

    THE AUDIT DIES WITH THE WORLD, WHICH IS THE OPPOSITE OF THE RULE FOR EVERY OTHER ROW IN IT.

    That table is a record of people and is deliberately not purged with the base world. A demo
    actor is not a person: they are invented at the door and gone in an hour.

    Keeping their rows would mean keeping the `users` row each one points at, forever, for every
    passer-by who pressed a button, and the audit would fill with operators who never existed.
    """
    await connection.execute(
        text(
            "DELETE FROM admin.audit_log WHERE actor_user_id IN "
            "(SELECT id FROM admin.users WHERE world_id = :world)"
        ),
        {"world": world_id},
    )
    await connection.execute(
        text("DELETE FROM admin.users WHERE world_id = :world"), {"world": world_id}
    )
    await connection.execute(
        text("DELETE FROM admin.roles WHERE world_id = :world"), {"world": world_id}
    )
    await purge_world(connection, world_id)
    await connection.execute(
        text("DELETE FROM admin.demo_sandboxes WHERE world_id = :world"), {"world": world_id}
    )
