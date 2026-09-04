"""What operators did, read back.

Its own module and its own router: the audit is not a fact about a subscriber, and hanging it off
`/subscribers` would have made the path say otherwise. It is also the second endpoint in this
service where the permission matrix has teeth — `viewer` holds every `*.read` code except this one
and `users.read`, so the menu entry is absent for them and the direct call is a 403.

One statement per page, count included, like the subscriber's feed. The actor's email is joined
rather than looked up per row, which is the same rule the table's projection follows and for the
same reason.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import RequirePermission
from app.models import AuditLog, User
from app.routers import error_responses
from app.schemas import AuditActor, AuditEntry, AuditPage, AuditQueryParams

router = APIRouter(prefix="/audit", tags=["audit"])


# The filters are applied to two different statements — the page and the count behind it — and
# both keep their own row type through them.
def _narrowed[S: Select[Any]](statement: S, query: AuditQueryParams) -> S:
    """Apply the filters the screen offers, and only those.

    Each one is a value the screen can produce: a row's actor, a row's action, a row's subscriber,
    and the two outcomes. There is no free-text search, because the only free text in this table is
    `payload_json`, whose keys differ per action — a search box over it would silently cover some
    rows and not others.
    """
    if query.actor_user_id is not None:
        statement = statement.where(AuditLog.actor_user_id == query.actor_user_id)
    if query.action:
        statement = statement.where(AuditLog.action.in_(query.action))
    if query.target_id is not None:
        statement = statement.where(AuditLog.target_id == query.target_id)
    if query.outcome is not None:
        statement = statement.where(AuditLog.outcome == query.outcome)
    return statement


@router.get(
    "",
    summary="One page of what operators did, newest first",
    dependencies=[RequirePermission("audit.read")],
    responses=error_responses(401, 403, 422),
)
async def list_page(
    query: Annotated[AuditQueryParams, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuditPage:
    statement = _narrowed(
        select(
            AuditLog.id,
            AuditLog.occurred_at,
            AuditLog.actor_user_id,
            User.email,
            AuditLog.action,
            AuditLog.target_type,
            AuditLog.target_id,
            AuditLog.world_id,
            AuditLog.outcome,
            AuditLog.error_code,
            AuditLog.payload_json,
            func.count().over().label("total"),
        ).join(User, User.id == AuditLog.actor_user_id),
        query,
    )
    # Tie-broken by `seq`, the order the rows were written in. A burst of operations shares a
    # transaction and therefore an `occurred_at`, and the random uuid this used to fall back on
    # ordered them arbitrarily — as well as letting one row appear on two pages and on neither.
    rows = (
        await session.execute(
            statement.order_by(AuditLog.occurred_at.desc(), AuditLog.seq.desc())
            .limit(query.page_size)
            .offset((query.page - 1) * query.page_size)
        )
    ).all()

    return AuditPage(
        items=[
            AuditEntry(
                id=row.id,
                occurred_at=row.occurred_at,
                actor=AuditActor(id=row.actor_user_id, email=row.email),
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                world_id=row.world_id,
                outcome=row.outcome,
                error_code=row.error_code,
                payload=row.payload_json,
            )
            for row in rows
        ],
        # A page past the end carries no rows and therefore no window count. Zero would say the
        # log is empty, and the pager would erase the way back.
        total=rows[0].total if rows else await _count(session, query),
        page=query.page,
        page_size=query.page_size,
    )


async def _count(session: AsyncSession, query: AuditQueryParams) -> int:
    """How many rows match. Only asked when the page came back empty."""
    statement = _narrowed(select(func.count()).select_from(AuditLog), query)
    found: int = (await session.execute(statement)).scalar_one()
    return found
