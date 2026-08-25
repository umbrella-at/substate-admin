"""GET /api/users.

One collection, and the shape every collection added later copies. The ordering is the part worth
testing hardest: under a non-unique ordering Postgres may return ties differently per statement,
and two adjacent pages then repeat one row and skip another with nothing in the response to say
so.
"""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from support import USERS, Clock, bearer, create_account, envelope


async def test_a_page_is_ordered_and_reports_the_whole_total(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    reader = await create_account(session, email="zoe@example.com", role_code="admin")
    await create_account(session, email="alice@example.com", role_code="viewer")
    await create_account(session, email="mallory@example.com", role_code="support")

    response = await client.get(f"{USERS}?page=1&pageSize=2", headers=bearer(reader, now=clock.now))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "pageSize"}
    assert [item["email"] for item in body["items"]] == [
        "alice@example.com",
        "mallory@example.com",
    ]
    # The count is of the table, not of the page: the client renders a pager from it.
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["pageSize"] == 2


async def test_the_pages_partition_the_table(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    reader = await create_account(session, email="zoe@example.com")
    await create_account(session, email="alice@example.com")
    await create_account(session, email="mallory@example.com")
    headers = bearer(reader, now=clock.now)

    first = (await client.get(f"{USERS}?page=1&pageSize=2", headers=headers)).json()
    second = (await client.get(f"{USERS}?page=2&pageSize=2", headers=headers)).json()

    seen = [item["email"] for item in first["items"] + second["items"]]
    assert seen == ["alice@example.com", "mallory@example.com", "zoe@example.com"]
    assert len(seen) == len(set(seen))


async def test_a_row_carries_the_role_and_not_the_hash(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    reader = await create_account(session, email="only@example.com", role_code="support")
    stored = (
        await session.execute(select(User.password_hash).where(User.id == reader.id))
    ).scalar_one()

    response = await client.get(USERS, headers=bearer(reader, now=clock.now))

    row = response.json()["items"][0]
    assert set(row) == {"id", "email", "isActive", "createdAt", "lastLoginAt", "role"}
    assert row["role"] == {"code": "support", "name": "Support"}
    assert stored not in response.text
    for forbidden in ("passwordHash", "password_hash", "roleId", "role_id"):
        assert forbidden not in response.text


async def test_the_page_size_has_a_ceiling(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """A collection that will answer `?pageSize=100000` is a collection that will one day be asked
    to."""
    reader = await create_account(session, email="greedy@example.com")

    response = await client.get(f"{USERS}?pageSize=101", headers=bearer(reader, now=clock.now))

    assert response.status_code == 422
    assert envelope(response)["field"] == "pageSize"


async def test_the_defaults_are_the_first_page(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    reader = await create_account(session, email="default@example.com")

    body = (await client.get(USERS, headers=bearer(reader, now=clock.now))).json()

    assert body["page"] == 1
    assert body["pageSize"] == 25


async def test_the_page_number_has_a_ceiling_too(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """`page` is what the offset is computed from, and the offset is sent to Postgres, whose
    OFFSET is a bigint. Unbounded, a page number nobody could reach by clicking is a 500 about an
    overflowing query rather than a 422 naming the parameter that was wrong."""
    reader = await create_account(session, email="deep@example.com")

    response = await client.get(
        f"{USERS}?page=99999999999999999999", headers=bearer(reader, now=clock.now)
    )

    assert response.status_code == 422
    assert envelope(response)["field"] == "page"
