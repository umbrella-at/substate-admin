"""The user list.

One route, and the shape every collection added later copies: a permission on the decorator, a
`PageParams` off the query string, a count and a page in two statements, and rows serialised
through a response model that names its fields.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import Identity, RequirePermission
from app.models import User
from app.routers import error_responses
from app.schemas import PageParams, UserListResponse, UserSummary

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    summary="List the operators of this panel",
    responses=error_responses(401, 403, 422),
)
async def list_users(
    page: Annotated[PageParams, Query()],
    identity: Annotated[Identity, RequirePermission("users.read")],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserListResponse:
    """One page of users, under an ordering the client can page through safely.

    Scoped to the caller's world, which for an operator is the rows carrying none. A demonstration
    visitor sees the colleagues their sandbox invented and never an address from outside it.

    That scope is also what keeps the ordering below total: an address is unique WITHIN a world,
    so a listing spanning two of them could hold the same key twice.
    """
    mine = User.world_id == identity.world_scope
    total = (await session.execute(select(func.count()).select_from(User).where(mine))).scalar_one()

    rows = (
        (
            await session.execute(
                # Ordered by the unique column, so the ordering is total. Under any non-unique
                # ordering Postgres is free to return ties in a different order per statement, and
                # two adjacent pages then repeat one row and skip another with nothing in the
                # response to say so.
                #
                # `User.role` is an inner-joined eager load, so this is one statement and the role
                # each row reports arrives with it. LIMIT is safe over it because the relationship
                # is many-to-one: there is no collection for the limit to truncate.
                select(User)
                .where(mine)
                .order_by(User.email)
                .limit(page.page_size)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )

    return UserListResponse(
        items=[UserSummary.model_validate(user) for user in rows],
        # The count is of the whole table, not of the page. The client renders a pager from it,
        # and a total that only described what it could already see would be useless.
        total=total,
        page=page.page,
        page_size=page.page_size,
    )
