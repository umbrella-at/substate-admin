"""One subscriber's feed, read out of the journal.

ONE STATEMENT PER PAGE, NEVER ONE PER ROW. The count and the rows come back together through a
window function rather than through a COUNT followed by a SELECT: two statements would be two
snapshots, and a tick landing between them is a pager whose last page is empty. It also keeps the
promise the table already makes — a feed that issued a query per event would not be noticed on a
subscriber with ten of them and would be the first thing anybody notices while paging.

The predicate and the ordering are one index. Newest first, tie-broken by the write sequence
rather than by the primary key: one engine call reads the clock once, so every event it emits
shares an instant, and a random uuid put "Renewed" above the payment that caused it about half the
time. A tiebreaker is needed at all because an order with none lets a row appear on two pages and
on neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EventJournal


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One event as the feed shows it."""

    id: str
    type: str
    occurred_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EventPage:
    items: tuple[JournalEntry, ...]
    total: int
    page: int
    page_size: int


async def list_events(
    session: AsyncSession, world_id: str, user_id: str, *, page: int = 1, page_size: int = 25
) -> EventPage:
    """One page of what happened to this subscriber, newest first.

    The size the caller asks for is `PageParams`', which is bounded where it is declared; it is
    clamped again here so that a caller who is not a route cannot ask for the whole journal.
    """
    size = max(1, min(page_size, 100))
    offset = (max(1, page) - 1) * size

    rows = (
        await session.execute(
            select(
                EventJournal.id,
                EventJournal.type,
                EventJournal.occurred_at,
                EventJournal.payload_json,
                func.count().over().label("total"),
            )
            .where(EventJournal.world_id == world_id, EventJournal.user_id == user_id)
            .order_by(EventJournal.occurred_at.desc(), EventJournal.seq.desc())
            .limit(size)
            .offset(offset)
        )
    ).all()

    return EventPage(
        items=tuple(
            JournalEntry(
                id=str(row.id),
                type=row.type,
                occurred_at=row.occurred_at,
                payload=row.payload_json,
            )
            for row in rows
        ),
        # A page past the end returns nothing, and nothing carries no count. Zero would say the
        # subscriber has no history, so the pager would erase itself rather than offer the way back.
        total=rows[0].total if rows else await _count(session, world_id, user_id),
        page=page,
        page_size=size,
    )


async def _count(session: AsyncSession, world_id: str, user_id: str) -> int:
    """How many events this subscriber has. Only asked when the page came back empty."""
    return (
        await session.execute(
            select(func.count())
            .select_from(EventJournal)
            .where(EventJournal.world_id == world_id, EventJournal.user_id == user_id)
        )
    ).scalar_one()
