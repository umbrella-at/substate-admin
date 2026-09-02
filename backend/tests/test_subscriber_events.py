"""One subscriber's feed.

The card asks two questions of the same person — what is true now, and what happened — and only
the second one is in Postgres. So these tests are about the journal read: that it answers for one
subscriber and not for the world, newest first, one statement per page, and that a subscriber who
does not exist is told so rather than shown an empty history.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from substate import (
    Event,
    PaymentRecorded,
    Period,
    Plan,
    State,
    SubscriptionActivated,
    SubscriptionCreated,
)

from app.schemas import PageParams
from app.subscribers.events import list_events
from app.worlds.journal import flush_world, write_events
from app.worlds.registry import World
from support import Clock, bearer, create_account, envelope

MONTHLY = Plan(
    id="monthly", price=500, currency="USD", period=Period.months(1), trial_days=14, grace_days=5
)

SUBSCRIBER = "sub-0001"
EVENTS = f"/api/subscribers/{SUBSCRIBER}/events"


@pytest.fixture
async def world(base_world: World) -> World:
    """The suite's base world, holding one subscriber."""
    base_world.engine.register_plan(MONTHLY)
    await base_world.engine.subscribe(SUBSCRIBER, "monthly")
    return base_world


async def _history(connection: AsyncConnection, world: World, count: int) -> list[Event]:
    """`count` events for the subscriber, a day apart, oldest first."""
    start = datetime.now(UTC) - timedelta(days=count)
    events = [
        SubscriptionCreated(
            SUBSCRIBER, start + timedelta(days=day), plan_id="monthly", state=State.TRIAL
        )
        for day in range(count)
    ]
    await write_events(connection, world.id, events)
    return events


async def _headers(session: AsyncSession, clock: Clock, email: str) -> dict[str, str]:
    account = await create_account(session, email=email, role_code="admin")
    return bearer(account, now=clock.now)


async def test_events_from_one_call_keep_the_order_the_engine_made_them_in(
    connection: AsyncConnection, session: AsyncSession, world: World
) -> None:
    """One call reads the clock once, so its events share an instant to the microsecond.

    Tie-broken by the primary key — a random uuid — the feed showed a renewal above the payment
    that caused it about half the time. The write sequence is the order the engine produced them
    in, and this is the assertion that says so.
    """
    at = datetime.now(UTC)
    await write_events(
        connection,
        world.id,
        [
            PaymentRecorded(SUBSCRIBER, at, provider="panel", external_id="ref", amount=500),
            SubscriptionActivated(SUBSCRIBER, at, plan_id="monthly", expires_at=at),
        ],
    )

    page = await list_events(session, world.id, SUBSCRIBER)

    # Newest first, and within one instant the last one written is the newest.
    assert [entry.type for entry in page.items] == ["subscription.activated", "payment.recorded"]


async def test_the_feed_is_newest_first(
    connection: AsyncConnection, session: AsyncSession, world: World
) -> None:
    written = await _history(connection, world, 5)

    page = await list_events(session, world.id, SUBSCRIBER)

    assert [entry.occurred_at for entry in page.items] == [
        event.occurred_at for event in reversed(written)
    ]


async def test_a_page_carries_the_whole_count_and_not_its_own(
    connection: AsyncConnection, session: AsyncSession, world: World
) -> None:
    """The pager needs to know how far it can go, and a count of the rows on this page would say
    the feed ends here on every page."""
    await _history(connection, world, 7)

    page = await list_events(session, world.id, SUBSCRIBER, page=1, page_size=3)

    assert len(page.items) == 3
    assert page.total == 7


async def test_paging_covers_the_history_once(
    connection: AsyncConnection, session: AsyncSession, world: World
) -> None:
    await _history(connection, world, 7)

    seen: list[str] = []
    for number in (1, 2, 3):
        page = await list_events(session, world.id, SUBSCRIBER, page=number, page_size=3)
        seen.extend(entry.id for entry in page.items)

    assert len(seen) == 7
    assert len(set(seen)) == 7


async def test_a_page_past_the_end_still_reports_the_total(
    connection: AsyncConnection, session: AsyncSession, world: World
) -> None:
    """Otherwise the pager reads a total of zero, erases itself, and strands whoever typed a page
    number into the address bar on a screen with no way back."""
    await _history(connection, world, 3)

    page = await list_events(session, world.id, SUBSCRIBER, page=9, page_size=3)

    assert page.items == ()
    assert page.total == 3


async def test_the_feed_belongs_to_one_subscriber(
    connection: AsyncConnection, session: AsyncSession, world: World
) -> None:
    await _history(connection, world, 2)
    await write_events(
        connection,
        world.id,
        [SubscriptionCreated("sub-0002", datetime.now(UTC), plan_id="monthly", state=State.TRIAL)],
    )

    page = await list_events(session, world.id, SUBSCRIBER)

    assert page.total == 2


async def test_the_feed_belongs_to_one_world(
    connection: AsyncConnection, session: AsyncSession, world: World
) -> None:
    """Both halves of the key are in the predicate. Filtering by the subscriber alone would show a
    sandbox's history on the base world's card the day sandboxes exist."""
    await _history(connection, world, 2)
    await write_events(
        connection,
        "somewhere-else",
        [SubscriptionCreated(SUBSCRIBER, datetime.now(UTC), plan_id="monthly", state=State.TRIAL)],
    )

    page = await list_events(session, world.id, SUBSCRIBER)

    assert page.total == 2


async def test_what_an_operation_emits_appears_in_the_feed(
    connection: AsyncConnection, session: AsyncSession, world: World
) -> None:
    """The reason the sink writes at all: press cancel, see it happen."""
    await world.engine.cancel(SUBSCRIBER)
    await flush_world(connection, world)

    page = await list_events(session, world.id, SUBSCRIBER)

    assert [entry.type for entry in page.items] == [
        "subscription.cancelled",
        "subscription.created",
    ]
    # The engine's own spelling, in the database. The route is what camelCases it.
    assert "access_until" in page.items[0].payload


async def test_the_route_answers_the_feed(
    client: AsyncClient,
    connection: AsyncConnection,
    session: AsyncSession,
    clock: Clock,
    world: World,
) -> None:
    await _history(connection, world, 2)

    response = await client.get(EVENTS, headers=await _headers(session, clock, "feed@example.com"))

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"items", "total", "page", "pageSize"}
    assert body["total"] == 2
    # The same page vocabulary as every other collection here, not a third one.
    assert body["pageSize"] == PageParams().page_size
    assert set(body["items"][0]) == {"id", "type", "occurredAt", "payload"}
    # camelCase all the way down: the payload is part of this response, not a second convention.
    assert set(body["items"][0]["payload"]) == {"planId", "state"}


async def test_a_subscriber_who_does_not_exist_is_said_so(
    client: AsyncClient, session: AsyncSession, clock: Clock, world: World
) -> None:
    """Not an empty feed. "Nothing has happened to this person" and "there is no such person" look
    identical on screen and are different answers."""
    response = await client.get(
        "/api/subscribers/nobody/events",
        headers=await _headers(session, clock, "missing@example.com"),
    )

    assert response.status_code == 404
    assert envelope(response)["code"] == "NOT_FOUND"


async def test_the_page_size_has_a_ceiling(
    client: AsyncClient, session: AsyncSession, clock: Clock, world: World
) -> None:
    response = await client.get(
        f"{EVENTS}?pageSize=101",
        headers=await _headers(session, clock, "ceiling@example.com"),
    )

    assert response.status_code == 422
    assert envelope(response)["field"] == "pageSize"
