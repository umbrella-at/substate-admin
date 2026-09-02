"""The subscriber table and one subscriber's card.

Both routes answer from two sources and never confuse them: `substate` for the state of a
subscription, the projection for the display name and the last time somebody turned up. The
projection is loaded per request in one statement rather than per row — a table of three hundred
rows that issues three hundred queries is a table that will be rewritten the first time anybody
looks at it under load.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from substate import Subscription

from app.db import get_session
from app.deps import RequirePermission
from app.errors import ApiError, ErrorCode
from app.models import SubscriberView
from app.routers import error_responses
from app.routers.plans import plan_summary
from app.schemas import (
    PageParams,
    SubscriberDetail,
    SubscriberEvent,
    SubscriberEventPage,
    SubscriberPage,
    SubscriberQueryParams,
    SubscriberSummary,
)
from app.seed.catalogue import PLAN_BY_ID
from app.subscribers.events import JournalEntry, list_events
from app.subscribers.query import SubscriberRow, build_row, list_subscribers
from app.worlds.registry import BASE_WORLD_ID, World, WorldRegistry, get_registry

router = APIRouter(prefix="/subscribers", tags=["subscribers"])


def _world() -> World:
    """The world this request reads.

    Always the base world today. It is a function rather than a constant because the world will
    eventually be read out of the token, once a visitor can have a sandbox of their own, and every
    caller here already goes through it — which is the whole point of putting the world key on
    everything from the first day rather than the last.
    """
    registry: WorldRegistry = get_registry()
    world = registry.get(BASE_WORLD_ID)
    if world is None:
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            message="The demonstration world is not available.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return world


async def _require(world: World, user_id: str) -> Subscription:
    """The subscription this request is about, or a 404.

    One place, so the card and its feed agree about who exists. A feed that answered an unknown id
    with an empty page would say the subscriber has no history rather than that there is no such
    subscriber, and the two look identical on screen.
    """
    subscription = await world.engine.get_subscription(user_id)
    if subscription is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return subscription


async def _projection(
    session: AsyncSession, world_id: str
) -> dict[str, tuple[str, datetime | None]]:
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


def _event(entry: JournalEntry) -> SubscriberEvent:
    """One journal row as the wire describes it.

    The payload's keys are camelCased here like every other key this API sends. They are the
    engine's field names in the database, which is where Python's spelling belongs; a response
    carrying `external_id` beside `occurredAt` would make the frontend hold two conventions.
    """
    return SubscriberEvent(
        id=entry.id,
        type=entry.type,
        occurred_at=entry.occurred_at,
        payload={to_camel(key): value for key, value in entry.payload.items()},
    )


def _summary(row: SubscriberRow) -> SubscriberSummary:
    return SubscriberSummary(
        user_id=row.user_id,
        display_name=row.display_name,
        state=row.state.value,
        plan_id=row.plan_id,
        access_until=row.access_until,
        expires_at=row.expires_at,
        trial_ends_at=row.trial_ends_at,
        grace_ends_at=row.grace_ends_at,
        last_active_at=row.last_active_at,
        promo_code=row.promo_code,
        referrer_id=row.referrer_id,
    )


@router.get(
    "",
    summary="One page of subscribers, filtered and sorted",
    dependencies=[RequirePermission("subscribers.read")],
    responses=error_responses(401, 403, 422),
)
async def list_page(
    query: Annotated[SubscriberQueryParams, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriberPage:
    world = _world()
    projection = await _projection(session, world.id)
    page = await list_subscribers(world, projection, query.to_query())
    return SubscriberPage(
        items=[_summary(row) for row in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get(
    "/{user_id}",
    summary="One subscriber: the subscription, its plan, its promo code and its referrer",
    dependencies=[RequirePermission("subscribers.read")],
    responses=error_responses(401, 403, 404, 422),
)
async def read_one(
    user_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriberDetail:
    world = _world()
    subscription = await _require(world, user_id)

    projection = await _projection(session, world.id)
    display_name, last_active_at = projection.get(user_id, (user_id, None))
    row = build_row(subscription, display_name, last_active_at)
    plan = PLAN_BY_ID[subscription.plan_id]
    program_id = await world.storage.get_program_id(subscription.referrer_id or "")
    return SubscriberDetail(
        subscriber=_summary(row),
        plan=plan_summary(plan),
        promo_code=subscription.promo_code,
        referrer_id=subscription.referrer_id,
        referral_program_id=program_id,
    )


@router.get(
    "/{user_id}/events",
    summary="One page of what has happened to this subscriber, newest first",
    dependencies=[RequirePermission("subscribers.read")],
    responses=error_responses(401, 403, 404, 422),
)
async def read_events(
    user_id: str,
    page: Annotated[PageParams, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriberEventPage:
    world = _world()
    await _require(world, user_id)

    found = await list_events(session, world.id, user_id, page=page.page, page_size=page.page_size)
    return SubscriberEventPage(
        items=[_event(entry) for entry in found.items],
        total=found.total,
        page=found.page,
        page_size=found.page_size,
    )
