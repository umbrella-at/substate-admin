"""The six operations, and the refusals they can produce.

The refusals are the point of this file. The specification requires that a refusal from `substate`
reaches the frontend as a machine-readable code equal to the exception's own name, and a
translation table is worth nothing unless every entry in it is reachable through a request. So
each of the seven is provoked here against a real engine — not asserted from the mapping, which
would only prove the mapping agrees with itself.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from substate import Accrual, Period, Plan, PromoCode, PromoKind, ReferralProgram

from app.models import AuditLog
from app.worlds.registry import BASE_WORLD_ID, World
from support import Clock, bearer, create_account, envelope

MONTHLY = Plan(
    id="monthly", price=500, currency="USD", period=Period.months(1), trial_days=14, grace_days=5
)
ANNUAL = Plan(
    id="annual", price=4200, currency="USD", period=Period.months(12), trial_days=30, grace_days=7
)

PERCENT = PromoCode(code="LAUNCH20", kind=PromoKind.PERCENT, value=20, max_redemptions=10)
FIXED = PromoCode(code="WELCOME5", kind=PromoKind.FIXED, value=100, max_redemptions=10)
SPENT = PromoCode(code="GONE", kind=PromoKind.PERCENT, value=10, max_redemptions=0)

PARTNERS = ReferralProgram(id="partners", percent=30, accrual=Accrual.EVERY_PAYMENT)

LIVE = "sub-live"
"""In TRIAL: every operation is legal on it except `subscribe`."""

ENDED = "sub-ended"
"""EXPIRED, so `subscribe` starts a new cycle in place."""


@pytest.fixture
async def world(base_world: World) -> World:
    """The suite's base world, stocked with a catalogue and two subscribers."""
    base_world.engine.register_referral_program(PARTNERS)
    for plan in (MONTHLY, ANNUAL):
        base_world.engine.register_plan(plan)
    for promo in (PERCENT, FIXED, SPENT):
        base_world.engine.register_promo_code(promo)
    await base_world.engine.subscribe(LIVE, "monthly")
    await base_world.engine.subscribe(ENDED, "monthly")
    # CANCELLED is the state where a payment is filed and changes nothing, so it is the one that
    # needs `subscribe` to have anything to offer at all.
    await base_world.engine.cancel(ENDED)
    base_world.sink.drain()
    return base_world


@pytest.fixture
async def operator(session: AsyncSession, clock: Clock) -> dict[str, str]:
    account = await create_account(session, email="operator@example.com", role_code="admin")
    return bearer(account, now=clock.now)


def _path(user_id: str, operation: str) -> str:
    return f"/api/subscribers/{user_id}/{operation}"


async def _audit(session: AsyncSession) -> list[AuditLog]:
    rows = await session.execute(select(AuditLog).order_by(AuditLog.occurred_at))
    return list(rows.scalars())


def _types(response: Response) -> list[str]:
    return [event["type"] for event in response.json()["events"]]


def _card(response: Response) -> dict[str, Any]:
    return response.json()["subscriber"]["subscriber"]


# --------------------------------------------------------------------------------------------
# What each operation does when it is accepted.
# --------------------------------------------------------------------------------------------


async def test_cancelling_answers_with_the_card_it_produced(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(_path(LIVE, "cancel"), headers=operator)

    assert response.status_code == 200
    assert _card(response)["state"] == "cancelled"
    assert _types(response) == ["subscription.cancelled"]
    # Filtered to the state that owns it, like the two boundaries beside it.
    assert _card(response)["cancelledAt"] is not None


async def test_cancelling_twice_changes_nothing_and_says_so(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    """The engine treats a second cancellation as nothing, the way a webhook delivered twice is.
    The answer has to be an honest empty list rather than a repeat of the first one."""
    await client.post(_path(LIVE, "cancel"), headers=operator)

    again = await client.post(_path(LIVE, "cancel"), headers=operator)

    assert again.status_code == 200
    assert _types(again) == []
    assert _card(again)["state"] == "cancelled"


async def test_changing_the_plan_schedules_it_for_the_next_payment(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(
        _path(LIVE, "change-plan"), headers=operator, json={"planId": "annual"}
    )

    assert response.status_code == 200
    assert _card(response)["planId"] == "monthly"
    assert _card(response)["pendingPlanId"] == "annual"
    assert _types(response) == ["subscription.plan_changed"]


async def test_naming_the_current_plan_drops_a_pending_change(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    """Which is what makes this the one operation that needs no confirmation: it undoes itself."""
    await client.post(_path(LIVE, "change-plan"), headers=operator, json={"planId": "annual"})

    undone = await client.post(
        _path(LIVE, "change-plan"), headers=operator, json={"planId": "monthly"}
    )

    assert _card(undone)["pendingPlanId"] is None


async def test_redeeming_binds_the_code_to_the_subscription(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(
        _path(LIVE, "redeem"), headers=operator, json={"promoCode": "LAUNCH20"}
    )

    assert response.status_code == 200
    assert response.json()["subscriber"]["promoCode"] == "LAUNCH20"
    assert _types(response) == ["promo.redeemed"]


async def test_a_payment_that_covers_the_price_starts_a_paid_period(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(_path(LIVE, "payment"), headers=operator, json={"amount": 500})

    assert response.status_code == 200
    assert _card(response)["state"] == "active"
    assert _types(response) == ["payment.recorded", "subscription.activated"]


async def test_a_payment_repeated_under_one_reference_is_recorded_once(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    """A 200 that changed nothing is the worst answer this round can produce, so the event that
    says so travels in the body rather than being inferred from a card that did not move."""
    body = {"amount": 500, "reference": "ref-0001"}
    await client.post(_path(LIVE, "payment"), headers=operator, json=body)

    again = await client.post(_path(LIVE, "payment"), headers=operator, json=body)

    assert again.status_code == 200
    assert _types(again) == ["payment.duplicate"]


async def test_a_payment_short_of_the_price_says_how_short(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(_path(LIVE, "payment"), headers=operator, json={"amount": 499})

    assert _types(response) == ["payment.recorded", "payment.underpaid"]
    underpaid = response.json()["events"][1]["payload"]
    assert underpaid["amount"] == 499
    assert underpaid["expected"] == 500
    assert _card(response)["state"] == "trial"


async def test_starting_a_new_subscription_replaces_the_one_that_ended(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(
        _path(ENDED, "subscribe"), headers=operator, json={"planId": "annual"}
    )

    assert response.status_code == 200
    assert _card(response)["planId"] == "annual"
    assert _types(response) == ["subscription.created"]


async def test_assigning_a_programme_changes_who_is_paid_and_emits_nothing(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(
        _path(LIVE, "referral-program"), headers=operator, json={"programId": "partners"}
    )

    assert response.status_code == 200
    assert response.json()["subscriber"]["referralProgramId"] == "partners"
    # The engine emits nothing for this one, so the card is the whole evidence — which is why the
    # answer is the card rather than a bare 204.
    assert _types(response) == []


# --------------------------------------------------------------------------------------------
# Every refusal the translation table claims to handle, provoked through a request.
# --------------------------------------------------------------------------------------------


async def test_a_live_subscription_refuses_a_new_one(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(
        _path(LIVE, "subscribe"), headers=operator, json={"planId": "annual"}
    )

    assert response.status_code == 409
    assert envelope(response)["code"] == "ALREADY_SUBSCRIBED"
    assert envelope(response)["field"] is None


async def test_an_unknown_plan_names_the_field_it_came_from(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    """422 with the field, not 404: it is a value somebody submitted, and the field is what puts
    the sentence under the input rather than in a banner above the form."""
    response = await client.post(
        _path(LIVE, "change-plan"), headers=operator, json={"planId": "platinum"}
    )

    assert response.status_code == 422
    assert envelope(response)["code"] == "UNKNOWN_PLAN"
    assert envelope(response)["field"] == "planId"


async def test_an_unknown_promo_code_names_the_field_it_came_from(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(
        _path(LIVE, "redeem"), headers=operator, json={"promoCode": "NOPE"}
    )

    assert response.status_code == 422
    assert envelope(response)["code"] == "UNKNOWN_PROMO_CODE"
    assert envelope(response)["field"] == "promoCode"


async def test_a_code_with_no_redemptions_left_is_refused(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(
        _path(LIVE, "redeem"), headers=operator, json={"promoCode": "GONE"}
    )

    assert response.status_code == 409
    assert envelope(response)["code"] == "PROMO_LIMIT_REACHED"


async def test_a_second_discount_is_refused_rather_than_replacing_the_first(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    await client.post(_path(LIVE, "redeem"), headers=operator, json={"promoCode": "LAUNCH20"})

    second = await client.post(
        _path(LIVE, "redeem"), headers=operator, json={"promoCode": "WELCOME5"}
    )

    assert second.status_code == 409
    assert envelope(second)["code"] == "PROMO_ALREADY_BOUND"


async def test_an_unknown_referral_programme_names_the_field_it_came_from(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    response = await client.post(
        _path(LIVE, "referral-program"), headers=operator, json={"programId": "nobody"}
    )

    assert response.status_code == 422
    assert envelope(response)["code"] == "UNKNOWN_REFERRAL_PROGRAM"
    assert envelope(response)["field"] == "programId"


@pytest.mark.parametrize(
    ("operation", "body"),
    [
        ("subscribe", {"planId": "monthly"}),
        ("cancel", None),
        ("change-plan", {"planId": "monthly"}),
        ("redeem", {"promoCode": "LAUNCH20"}),
        ("payment", {"amount": 500}),
        ("referral-program", {"programId": "partners"}),
    ],
)
async def test_every_operation_refuses_a_subscriber_who_does_not_exist(
    client: AsyncClient,
    session: AsyncSession,
    world: World,
    operator: dict[str, str],
    operation: str,
    body: dict[str, Any] | None,
) -> None:
    """404 before the engine is touched, so an unknown id is never dressed up as a domain refusal
    and never leaves an audit row about a subscriber nobody has."""
    response = await client.post(_path("nobody", operation), headers=operator, json=body)

    assert response.status_code == 404
    assert envelope(response)["code"] == "NOT_FOUND"
    assert await _audit(session) == []


# --------------------------------------------------------------------------------------------
# The audit.
# --------------------------------------------------------------------------------------------


async def test_an_accepted_operation_writes_one_audit_row(
    client: AsyncClient, session: AsyncSession, world: World, operator: dict[str, str]
) -> None:
    await client.post(_path(LIVE, "change-plan"), headers=operator, json={"planId": "annual"})

    rows = await _audit(session)

    assert len(rows) == 1
    row = rows[0]
    assert row.action == "subscription.change_plan"
    assert row.target_type == "subscription"
    assert row.target_id == LIVE
    assert row.outcome == "ok"
    assert row.error_code is None
    assert row.payload_json == {"planId": "annual"}
    assert row.world_id == BASE_WORLD_ID
    # HMAC, never the address.
    assert len(row.ip_hash) == 64


async def test_a_refused_operation_is_audited_with_the_code_the_caller_got(
    client: AsyncClient, session: AsyncSession, world: World, operator: dict[str, str]
) -> None:
    """The row an investigation is most likely to want. A log of successes cannot tell an operator
    who cancelled one subscription from one who tried nine and succeeded once."""
    await client.post(_path(LIVE, "redeem"), headers=operator, json={"promoCode": "NOPE"})

    rows = await _audit(session)

    assert len(rows) == 1
    assert rows[0].outcome == "refused"
    assert rows[0].error_code == "UNKNOWN_PROMO_CODE"
    assert rows[0].payload_json == {"promoCode": "NOPE"}


async def test_a_reference_belongs_to_the_subscriber_it_was_typed_on(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    """The engine's duplicate guard is (provider, externalId) and nothing else, so the same word
    typed on two people would have the second payment refused as a repeat of the first."""
    body = {"amount": 500, "reference": "inv-1"}
    await client.post(_path(LIVE, "payment"), headers=operator, json=body)

    other = await client.post(_path(ENDED, "payment"), headers=operator, json=body)

    assert "payment.duplicate" not in _types(other)
    assert "payment.recorded" in _types(other)


async def test_an_operation_answers_with_the_payload_in_this_api_s_spelling(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    """The engine writes `external_id`; every other key this API sends is camelCase, and a payload
    carrying Python's spelling would make the frontend hold two conventions."""
    response = await client.post(
        _path(LIVE, "payment"), headers=operator, json={"amount": 500, "reference": "inv-2"}
    )

    recorded = response.json()["events"][0]["payload"]
    assert set(recorded) == {"amount", "provider", "externalId"}


async def test_a_refusal_keeps_the_events_the_engine_emitted_on_its_way_to_refusing(
    client: AsyncClient, session: AsyncSession, world: World, operator: dict[str, str]
) -> None:
    """The reason a refusal flushes at all.

    A spent code, not an unknown one, and the difference is the point: an unknown code is refused
    by `_promo_code` before the engine looks at the subscription, while a spent one is refused by
    `_claim` after `_load_and_advance` has already caught the record up and saved it. Here the
    trial has run out under the subscriber's feet, so the refused redemption is itself the cause of
    an expiry — a row the journal must keep even though the caller was told no.
    """
    world.clock.advance(timedelta(days=400))

    response = await client.post(
        _path(LIVE, "redeem"), headers=operator, json={"promoCode": "GONE"}
    )

    assert response.status_code == 409
    feed = await client.get(f"/api/subscribers/{LIVE}/events", headers=operator)
    assert "subscription.expired" in [event["type"] for event in feed.json()["items"]]
    # And the attempt is on file with the code the caller was given.
    rows = await _audit(session)
    assert [(row.outcome, row.error_code) for row in rows] == [("refused", "PROMO_LIMIT_REACHED")]


async def test_the_audit_records_the_reference_a_payment_was_filed_under(
    client: AsyncClient, session: AsyncSession, world: World, operator: dict[str, str]
) -> None:
    """Minted when the caller sends none. Without it in the row, a duplicate refused next week
    could not be traced to the press that created the reference this week."""
    await client.post(_path(LIVE, "payment"), headers=operator, json={"amount": 500})

    payload = (await _audit(session))[0].payload_json

    assert set(payload) == {"amount", "provider", "reference"}
    assert payload["provider"] == "panel"
    assert payload["reference"]


async def test_an_operation_that_was_refused_is_not_in_the_card(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    """The refusal happens before anything is saved, so the subscription is what it was."""
    await client.post(_path(LIVE, "redeem"), headers=operator, json={"promoCode": "NOPE"})

    card = await client.get(f"/api/subscribers/{LIVE}", headers=operator)

    assert card.json()["promoCode"] is None


async def test_what_an_operation_emitted_is_in_the_feed(
    client: AsyncClient, world: World, operator: dict[str, str]
) -> None:
    await client.post(_path(LIVE, "cancel"), headers=operator)

    feed = await client.get(f"/api/subscribers/{LIVE}/events", headers=operator)

    assert [event["type"] for event in feed.json()["items"]] == ["subscription.cancelled"]
