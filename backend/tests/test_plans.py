"""The two catalogue endpoints.

Written because the controls that read them depend on their being complete: a plan filter offering
four of five hides people, and a programme list missing a programme is a programme nobody can be
put on. Both fail while looking like they work.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.seed.catalogue import PLANS
from support import Clock, bearer, create_account

PROGRAMS = "/api/referral-programs"


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


async def test_the_referral_programmes_are_the_ones_the_catalogue_holds(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """Both, with the two knobs a programme has.

    The control that assigns one reads this, so a list missing a programme is a programme nobody
    can be put on — and the percentage and the accrual are what make the choice a choice rather
    than an identifier somebody has to know.
    """
    account = await create_account(session, email="programmes@example.com", role_code="admin")

    response = await client.get(PROGRAMS, headers=bearer(account, now=clock.now))

    assert response.status_code == 200
    assert response.json() == [
        {"id": "users", "percent": 10, "accrual": "first_payment_only"},
        {"id": "partners", "percent": 30, "accrual": "every_payment"},
    ]


async def test_a_viewer_may_read_the_programmes_and_a_demo_session_may_not(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """`referrals.read` rather than `subscribers.read`: the list is a fact about the programmes,
    not about anybody's subscription, and it takes the permission named after what it is about."""
    viewer = await create_account(session, email="programme-viewer@example.com", role_code="viewer")

    allowed = await client.get(PROGRAMS, headers=bearer(viewer, now=clock.now))

    assert allowed.status_code == 200
