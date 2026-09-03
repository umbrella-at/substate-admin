"""Reading back what operators did.

The writer is exercised beside the operations that call it. What is here is the read: that the
page is one statement with its own count, that every filter the screen offers narrows what it
claims to, that the order is fixed, and that the one column which must never leave the machine
does not.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import OK, REFUSED, Entry, record
from app.models import AuditLog, User
from app.worlds.registry import BASE_WORLD_ID
from support import Clock, bearer, create_account, envelope

AUDIT = "/api/audit"

# Long enough to page over without writing thirty rows into every test.
BATCH = 7


async def _write(
    session: AsyncSession, actor: uuid.UUID, *, targets: Iterable[str], refused: bool = False
) -> None:
    from app.errors import ErrorCode

    for target in targets:
        await record(
            session,
            Entry(
                actor_user_id=actor,
                action="subscription.cancel",
                target_type="subscription",
                target_id=target,
                ip_hash="0" * 64,
                world_id=BASE_WORLD_ID,
                payload={"note": target},
            ),
            refusal=ErrorCode.PROMO_ALREADY_BOUND if refused else None,
        )
    await session.commit()


@pytest.fixture
async def admin(session: AsyncSession, clock: Clock) -> tuple[User, dict[str, str]]:
    account = await create_account(session, email="auditor@example.com", role_code="admin")
    return account, bearer(account, now=clock.now)


async def test_a_row_carries_who_did_it_and_what_it_was(
    client: AsyncClient, session: AsyncSession, admin: tuple[User, dict[str, str]]
) -> None:
    account, headers = admin
    await _write(session, account.id, targets=["sub-0001"])

    response = await client.get(AUDIT, headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"items", "total", "page", "pageSize"}
    assert body["total"] == 1
    row = body["items"][0]
    assert set(row) == {
        "id",
        "occurredAt",
        "actor",
        "action",
        "targetType",
        "targetId",
        "worldId",
        "outcome",
        "errorCode",
        "payload",
    }
    assert row["actor"] == {"id": str(account.id), "email": "auditor@example.com"}
    assert row["action"] == "subscription.cancel"
    assert row["outcome"] == OK
    assert row["errorCode"] is None


async def test_the_address_never_leaves_the_machine_that_hashed_it(
    client: AsyncClient, session: AsyncSession, admin: tuple[User, dict[str, str]]
) -> None:
    """Stored so an investigation can ask the database, never sent so a screen can show twelve
    characters of an HMAC and call it evidence."""
    account, headers = admin
    await _write(session, account.id, targets=["sub-0001"])

    response = await client.get(AUDIT, headers=headers)

    assert "ipHash" not in response.json()["items"][0]
    assert "0000000000" not in response.text


async def test_the_page_carries_the_whole_count(
    client: AsyncClient, session: AsyncSession, admin: tuple[User, dict[str, str]]
) -> None:
    account, headers = admin
    await _write(session, account.id, targets=[f"sub-{n:04d}" for n in range(BATCH)])

    response = await client.get(f"{AUDIT}?pageSize=3", headers=headers)

    assert len(response.json()["items"]) == 3
    assert response.json()["total"] == BATCH


async def test_a_page_past_the_end_still_reports_the_total(
    client: AsyncClient, session: AsyncSession, admin: tuple[User, dict[str, str]]
) -> None:
    account, headers = admin
    await _write(session, account.id, targets=[f"sub-{n:04d}" for n in range(BATCH)])

    response = await client.get(f"{AUDIT}?pageSize=3&page=9", headers=headers)

    assert response.json()["items"] == []
    assert response.json()["total"] == BATCH


async def test_the_newest_row_is_first(
    client: AsyncClient, session: AsyncSession, admin: tuple[User, dict[str, str]]
) -> None:
    """Written with instants of their own rather than through `record`.

    `occurred_at` defaults to `now()`, which in Postgres is the transaction's timestamp — one row
    per request in production, three rows sharing an instant inside one test. Ordering rows that
    are simultaneous would assert the tie-break, and the tie-break is the next test.
    """
    account, headers = admin
    start = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    for offset, target in enumerate(["first", "second", "third"]):
        session.add(
            AuditLog(
                actor_user_id=account.id,
                action="subscription.cancel",
                target_type="subscription",
                target_id=target,
                outcome=OK,
                payload_json={},
                world_id=BASE_WORLD_ID,
                ip_hash="0" * 64,
                occurred_at=start + timedelta(minutes=offset),
            )
        )
    await session.commit()

    targets = [
        row["targetId"] for row in (await client.get(AUDIT, headers=headers)).json()["items"]
    ]

    assert targets == ["third", "second", "first"]


async def test_paging_over_simultaneous_rows_covers_each_once(
    client: AsyncClient, session: AsyncSession, admin: tuple[User, dict[str, str]]
) -> None:
    """What the tie-break is for. Rows written in one transaction share `now()` exactly, and an
    order with only one key lets a row appear on two pages and on neither."""
    account, headers = admin
    await _write(session, account.id, targets=[f"sub-{n:04d}" for n in range(BATCH)])

    seen: list[str] = []
    for page in (1, 2, 3):
        answer = await client.get(f"{AUDIT}?pageSize=3&page={page}", headers=headers)
        seen.extend(row["id"] for row in answer.json()["items"])

    assert len(seen) == BATCH
    assert len(set(seen)) == BATCH


async def test_filtering_by_the_subscriber_narrows_to_that_subscriber(
    client: AsyncClient, session: AsyncSession, admin: tuple[User, dict[str, str]]
) -> None:
    account, headers = admin
    await _write(session, account.id, targets=["sub-0001", "sub-0002"])

    response = await client.get(f"{AUDIT}?targetId=sub-0002", headers=headers)

    assert [row["targetId"] for row in response.json()["items"]] == ["sub-0002"]
    assert response.json()["total"] == 1


async def test_filtering_by_outcome_separates_what_worked_from_what_did_not(
    client: AsyncClient, session: AsyncSession, admin: tuple[User, dict[str, str]]
) -> None:
    """The answer to the objection that auditing refusals fills the table with noise: the noise is
    one chip away, and the alternative is a log that cannot show intent that failed."""
    account, headers = admin
    await _write(session, account.id, targets=["worked"])
    await _write(session, account.id, targets=["refused"], refused=True)

    only_refused = await client.get(f"{AUDIT}?outcome={REFUSED}", headers=headers)

    assert [row["targetId"] for row in only_refused.json()["items"]] == ["refused"]
    assert only_refused.json()["items"][0]["errorCode"] == "PROMO_ALREADY_BOUND"


async def test_filtering_by_action_accepts_more_than_one(
    client: AsyncClient, session: AsyncSession, admin: tuple[User, dict[str, str]]
) -> None:
    account, headers = admin
    await _write(session, account.id, targets=["sub-0001"])

    matched = await client.get(
        f"{AUDIT}?action=subscription.cancel&action=subscription.redeem", headers=headers
    )
    missed = await client.get(f"{AUDIT}?action=subscription.redeem", headers=headers)

    assert matched.json()["total"] == 1
    assert missed.json()["total"] == 0


async def test_filtering_by_an_actor_who_did_nothing_returns_nothing(
    client: AsyncClient, session: AsyncSession, admin: tuple[User, dict[str, str]]
) -> None:
    account, headers = admin
    await _write(session, account.id, targets=["sub-0001"])

    response = await client.get(f"{AUDIT}?actorUserId={uuid.uuid4()}", headers=headers)

    assert response.json() == {"items": [], "total": 0, "page": 1, "pageSize": 25}


async def test_an_action_this_service_does_not_have_is_refused(
    client: AsyncClient, admin: tuple[User, dict[str, str]]
) -> None:
    """The vocabulary is closed on the way in as well as on the way out. A filter naming an action
    nobody writes would answer an empty page, which reads as "nobody has ever done that"."""
    _, headers = admin

    response = await client.get(f"{AUDIT}?action=subscription.explode", headers=headers)

    assert response.status_code == 422
    assert envelope(response)["field"] == "action.0"


async def test_a_viewer_is_refused(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """The other half of the rule the interface follows: the menu entry is not drawn, and the
    direct call is refused. Showing somebody the product is not showing them what its operators
    have been doing."""
    viewer = await create_account(session, email="viewer@example.com", role_code="viewer")

    response = await client.get(AUDIT, headers=bearer(viewer, now=clock.now))

    assert response.status_code == 403
    assert envelope(response)["code"] == "PERMISSION_DENIED"
