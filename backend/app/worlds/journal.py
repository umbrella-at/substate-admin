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

# Spelled out rather than interpolated. The schema is fixed, the migrations hardcode it for
# the same reason, and a table name built by an f-string is a table name a reader has to
# reconstruct before they can be sure what it is.


@dataclass(frozen=True, slots=True)
class ProjectedSubscriber:
    """One row of the projection: what the panel knows and the engine does not."""

    user_id: str
    display_name: str
    last_active_at: datetime | None


def _payload(event: Event) -> dict[str, object]:
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
    result = await connection.execute(
        text("DELETE FROM admin.event_journal WHERE world_id <> ALL(:ids)"), {"ids": ids}
    )
    await connection.execute(
        text("DELETE FROM admin.subscriber_view WHERE world_id <> ALL(:ids)"), {"ids": ids}
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
                    json.dumps(_payload(event)),
                )
            )
            written += 1
    return written


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
