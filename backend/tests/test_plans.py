"""The catalogue endpoint.

Written because the plan filter depends on it being complete: a filter that offers four of five
plans hides people, and it does so while looking like it works.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.seed.catalogue import PLANS
from support import Clock, bearer, create_account


async def _headers(session: AsyncSession, clock: Clock, role: str = "admin") -> dict[str, str]:
    account = await create_account(session, email=f"{role}@example.com", role_code=role)
    return bearer(account, now=clock.now)


async def test_the_whole_catalogue_is_offered(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    response = await client.get("/api/plans", headers=await _headers(session, clock))
    assert response.status_code == 200
    assert [plan["id"] for plan in response.json()] == [plan.id for plan in PLANS]


async def test_the_ladder_keeps_its_order(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """Shortest to longest, so the filter reads as a ladder rather than an alphabet."""
    response = await client.get("/api/plans", headers=await _headers(session, clock))
    days = [
        plan["periodCount"] * (1 if plan["periodUnit"] == "days" else 30)
        for plan in response.json()
    ]
    assert days == sorted(days)


async def test_a_stranger_is_refused(client: AsyncClient) -> None:
    assert (await client.get("/api/plans")).status_code == 401
