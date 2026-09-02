"""The subscriber table, one subscriber's card, and the operations on it.

The reads answer from two sources and never confuse them: `substate` for the state of a
subscription, the projection for the display name and the last time somebody turned up. The
projection is loaded per request in one statement rather than per row — a table of three hundred
rows that issues three hundred queries is a table that will be rewritten the first time anybody
looks at it under load.

The writes are the six engine methods that take a subscriber. Every one of them goes through
`audit.perform`, which is where the order lives: the engine moves, what it emitted goes to the
journal, the attempt goes to the audit, and a refusal comes back as this API's own code. `tick()`
is not among them and has no endpoint — it takes no subscriber and belongs beside a clock.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from substate import Payment, Subscription

from app import audit
from app.db import get_session
from app.deps import Identity, RequirePermission
from app.errors import ApiError, ErrorCode
from app.models import SubscriberView
from app.routers import error_responses
from app.routers.plans import plan_summary
from app.schemas import (
    AssignProgramRequest,
    ChangePlanRequest,
    EngineEvent,
    PageParams,
    PaymentRequest,
    RedeemRequest,
    SubscriberDetail,
    SubscribeRequest,
    SubscriberEvent,
    SubscriberEventPage,
    SubscriberOperationResult,
    SubscriberPage,
    SubscriberQueryParams,
    SubscriberSummary,
)
from app.security.ratelimit import client_ip_hash
from app.seed.catalogue import PLAN_BY_ID
from app.subscribers.events import JournalEntry, list_events
from app.subscribers.query import SubscriberRow, build_row, list_subscribers
from app.worlds.journal import payload_of
from app.worlds.registry import BASE_WORLD_ID, World, WorldRegistry, get_registry

router = APIRouter(prefix="/subscribers", tags=["subscribers"])

PANEL_PROVIDER = "panel"
"""Where money recorded here came from. Not a field on the request: it did not arrive through a
gateway, and letting an operator type a provider name would invite them to claim it did."""


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


async def _projected(
    session: AsyncSession, world_id: str, user_id: str
) -> tuple[str, datetime | None]:
    """One subscriber's projected row, or the id itself when there is none.

    The table loads the whole projection because it draws the whole page; a card draws one person,
    and reading three hundred rows to use one of them is the shape of query this file already
    argues against in the other direction.
    """
    found = (
        await session.execute(
            select(SubscriberView.display_name, SubscriberView.last_active_at).where(
                SubscriberView.world_id == world_id, SubscriberView.user_id == user_id
            )
        )
    ).first()
    return (user_id, None) if found is None else (found.display_name, found.last_active_at)


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
        payload=_camel(entry.payload),
    )


async def _detail(session: AsyncSession, world: World, user_id: str) -> SubscriberDetail:
    """The card, rebuilt from the engine. Every operation answers with it, so what is on screen
    after a press is what the engine holds rather than what the panel guessed it would hold."""
    subscription = await _require(world, user_id)
    display_name, last_active_at = await _projected(session, world.id, user_id)
    row = build_row(subscription, display_name, last_active_at)
    return SubscriberDetail(
        subscriber=_summary(row),
        plan=plan_summary(PLAN_BY_ID[subscription.plan_id]),
        promo_code=subscription.promo_code,
        referrer_id=subscription.referrer_id,
        # Two different people. `get_program_id` answers "what is this id paid on", so asking it
        # about the referrer gives what the referral cost, and asking it about the subscriber
        # gives what they earn — which is the one the assign-program operation changes.
        referrer_program_id=await world.storage.get_program_id(subscription.referrer_id or ""),
        referral_program_id=await world.storage.get_program_id(user_id),
        trial_started_at=subscription.trial_started_at,
    )


def _camel(payload: dict[str, object]) -> dict[str, Any]:
    """The engine's field names in this API's spelling. One place, two callers."""
    return {to_camel(key): value for key, value in payload.items()}


async def _operate(
    *,
    session: AsyncSession,
    request: Request,
    identity: Identity,
    user_id: str,
    action: audit.AuditAction,
    payload: dict[str, Any],
    run: Callable[[World], Awaitable[object]],
) -> SubscriberOperationResult:
    """Every operation, minus the one line that differs.

    The subscriber is required BEFORE the engine is touched, so an unknown id is a 404 rather than
    a `NotSubscribed` dressed up as a domain refusal — and so nothing is written to the audit for
    a subscriber that does not exist.
    """
    world = _world()
    await _require(world, user_id)

    entry = audit.Entry(
        actor_user_id=identity.user.id,
        action=action,
        target_type="subscription",
        target_id=user_id,
        ip_hash=client_ip_hash(request),
        payload=payload,
    )

    async def call() -> None:
        await run(world)

    produced = await audit.perform(session, world, entry, call)
    return SubscriberOperationResult(
        subscriber=await _detail(session, world, user_id),
        events=[
            EngineEvent(
                type=type(event).name,
                occurred_at=event.occurred_at,
                payload=_camel(payload_of(event)),
            )
            for event in produced
        ],
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
        cancelled_at=row.cancelled_at,
        pending_plan_id=row.pending_plan_id,
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
    await _require(world, user_id)
    return await _detail(session, world, user_id)


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


# The write half. Each route is the one line that differs, plus what the audit needs to write
# down; everything else — the 404, the journal, the audit row, the refusal — is `_operate`.
_WRITE = "subscribers.write"

# 409 for the refusals about the state of a subscription, 422 for the ones about a value that was
# submitted. Not every operation can produce both: `cancel` takes no value and refuses nothing,
# and a route that documents a status it cannot return is a schema a client writes dead code for.
_STATE_OR_VALUE = error_responses(401, 403, 404, 409, 422)
_VALUE_ONLY = error_responses(401, 403, 404, 422)
_NOTHING_TO_REFUSE = error_responses(401, 403, 404)


@router.post(
    "/{user_id}/subscribe",
    summary="Start a new subscription for a subscriber whose last one has ended",
    responses=_STATE_OR_VALUE,
)
async def subscribe(
    user_id: str,
    body: SubscribeRequest,
    request: Request,
    identity: Annotated[Identity, RequirePermission(_WRITE)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriberOperationResult:
    """Begin a cycle in place. Refused with ALREADY_SUBSCRIBED unless the record has ended.

    The one revival path there is from CANCELLED: a payment on a cancelled record is filed and
    changes nothing, so without this the card for those subscribers offers no way to serve someone
    who has called to come back.
    """
    return await _operate(
        session=session,
        request=request,
        identity=identity,
        user_id=user_id,
        action="subscription.subscribe",
        payload={"planId": body.plan_id, "promoCode": body.promo_code},
        run=lambda world: world.engine.subscribe(user_id, body.plan_id, promo=body.promo_code),
    )


@router.post(
    "/{user_id}/cancel",
    summary="Stop the renewals and keep access to the end of the paid period",
    responses=_NOTHING_TO_REFUSE,
)
async def cancel(
    user_id: str,
    request: Request,
    identity: Annotated[Identity, RequirePermission(_WRITE)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriberOperationResult:
    """No body: there is nothing to say beyond which subscription."""
    return await _operate(
        session=session,
        request=request,
        identity=identity,
        user_id=user_id,
        action="subscription.cancel",
        payload={},
        run=lambda world: world.engine.cancel(user_id),
    )


@router.post(
    "/{user_id}/change-plan",
    summary="Schedule the plan the next payment will buy",
    responses=_VALUE_ONLY,
)
async def change_plan(
    user_id: str,
    body: ChangePlanRequest,
    request: Request,
    identity: Annotated[Identity, RequirePermission(_WRITE)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriberOperationResult:
    """Nothing moves now. Naming the plan the subscription is already on drops a pending change."""
    return await _operate(
        session=session,
        request=request,
        identity=identity,
        user_id=user_id,
        action="subscription.change_plan",
        payload={"planId": body.plan_id},
        run=lambda world: world.engine.change_plan(user_id, body.plan_id),
    )


@router.post(
    "/{user_id}/redeem",
    summary="Redeem a promo code against this subscription",
    responses=_STATE_OR_VALUE,
)
async def redeem(
    user_id: str,
    body: RedeemRequest,
    request: Request,
    identity: Annotated[Identity, RequirePermission(_WRITE)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriberOperationResult:
    """Spends one of the code's redemptions. There is no un-redeem, here or in the engine."""
    return await _operate(
        session=session,
        request=request,
        identity=identity,
        user_id=user_id,
        action="subscription.redeem",
        payload={"promoCode": body.promo_code},
        run=lambda world: world.engine.redeem(user_id, body.promo_code),
    )


@router.post(
    "/{user_id}/payment",
    summary="Record a payment against this subscription",
    responses=_VALUE_ONLY,
)
async def payment(
    user_id: str,
    body: PaymentRequest,
    request: Request,
    identity: Annotated[Identity, RequirePermission(_WRITE)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriberOperationResult:
    """Three of the outcomes here are events rather than refusals — duplicate, underpaid,
    unmatched — and every one of them is a 200 that moved nothing. The answer carries them."""
    # Namespaced by the subscriber. The engine's duplicate guard is `(provider, external_id)` and
    # nothing else, so two operators typing `inv-1` on two different people would have the second
    # payment refused as a repeat of the first.
    reference = body.reference if body.reference is not None else str(uuid.uuid4())
    external_id = f"{user_id}:{reference}"
    return await _operate(
        session=session,
        request=request,
        identity=identity,
        user_id=user_id,
        action="subscription.payment",
        # The minted reference is written down: without it, a duplicate that the engine refused
        # tomorrow could not be traced to the press that created it today.
        payload={"amount": body.amount, "provider": PANEL_PROVIDER, "reference": reference},
        run=lambda world: world.engine.apply_payment(
            Payment(
                provider=PANEL_PROVIDER,
                external_id=external_id,
                user_id=user_id,
                amount=body.amount,
            )
        ),
    )


@router.post(
    "/{user_id}/referral-program",
    summary="Put this subscriber on a referral programme as a referrer",
    # Its own permission, and the reason is what the endpoint does: it changes who is paid for
    # bringing people in, which is a fact about the programme rather than about this subscription.
    responses=_VALUE_ONLY,
)
async def assign_program(
    user_id: str,
    body: AssignProgramRequest,
    request: Request,
    identity: Annotated[Identity, RequirePermission("referrals.write")],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubscriberOperationResult:
    """Only future accruals move. What has already been paid out is history and is not recomputed.

    It emits no event, so the answer carries an empty list — the card's programme row is the whole
    evidence, which is why the answer is the card rather than a bare 204.
    """
    return await _operate(
        session=session,
        request=request,
        identity=identity,
        user_id=user_id,
        action="subscription.assign_program",
        payload={"programId": body.program_id},
        run=lambda world: world.engine.assign_program(user_id, body.program_id),
    )
