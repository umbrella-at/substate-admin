"""The `subscriber_view` rows for a world, read in one statement.

Its own module because two routers load it and `query.py` deliberately touches no database — it
is handed the projection so that the filtering and sorting stay next to the subscriptions they
are about.

One statement rather than one per row, which is the same rule the subscriber's feed follows: a
table of three hundred rows issuing three hundred queries is a table that gets rewritten the
first time anybody looks at it under load.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SubscriberView

Projection = dict[str, tuple[str, datetime | None]]
"""Display name and last activity, by user id. What the engine does not hold and should not."""


async def load(session: AsyncSession, world_id: str) -> Projection:
    rows = (
        await session.execute(
            select(
                SubscriberView.user_id,
                SubscriberView.display_name,
                SubscriberView.last_active_at,
            ).where(SubscriberView.world_id == world_id)
        )
    ).all()
    return {row.user_id: (row.display_name, row.last_active_at) for row in rows}
