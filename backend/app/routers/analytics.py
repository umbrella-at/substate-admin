"""The five figures, one route each.

Two read the engine and three read the journal, and the split is visible in the imports rather
than buried: `standing` answers what is true now, `movements` answers what happened. Only
`states` asks the question the subscriber table asks, and only it may be compared with it.

The period defaults come off the world's clock rather than off the wall, so a world that has been
wound forward is asked about the time it is actually in.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import movements, standing
from app.db import get_session
from app.deps import RequirePermission
from app.routers import current_world, error_responses
from app.schemas import (
    FlowParams,
    FlowPoint,
    FlowResponse,
    FunnelResponse,
    FunnelStage,
    PeriodParams,
    QuietBand,
    QuietResponse,
    RevenueMonth,
    RevenueParams,
    RevenueResponse,
    StateCount,
    StatesResponse,
)
from app.subscribers.projection import load as load_projection
from app.worlds.registry import World

router = APIRouter(prefix="/analytics", tags=["analytics"])

DEFAULT_PERIOD: Final = timedelta(days=90)
"""What a caller who names no period is asking about.

Long enough that a cohort has had time to convert and renew, which is what makes the funnel worth
reading; short enough that a week is still a visible slice of it.
"""


def _period(params: PeriodParams, world: World) -> tuple[datetime, datetime]:
    """The window, in UTC. The bucket keys are built from it and Postgres groups in UTC."""
    until = (params.until if params.until is not None else world.clock.now()).astimezone(UTC)
    since = params.since.astimezone(UTC) if params.since is not None else until - DEFAULT_PERIOD
    return since, until


@router.get(
    "/funnel",
    summary="Where the people who arrived in a period stopped",
    dependencies=[RequirePermission("analytics.read")],
    responses=error_responses(401, 403, 422),
)
async def read_funnel(
    params: Annotated[PeriodParams, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FunnelResponse:
    world = current_world()
    since, until = _period(params, world)
    found = await movements.funnel(session, world.id, since, until)
    return FunnelResponse(
        since=since,
        until=until,
        stages=[
            FunnelStage(stage="arrived", count=found.arrived),
            FunnelStage(stage="paid", count=found.paid),
            FunnelStage(stage="renewed", count=found.renewed),
        ],
        started_a_trial=found.started_a_trial,
    )


@router.get(
    "/flow",
    summary="Arrivals against departures, bucket by bucket",
    dependencies=[RequirePermission("analytics.read")],
    responses=error_responses(401, 403, 422),
)
async def read_flow(
    params: Annotated[FlowParams, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FlowResponse:
    world = current_world()
    since, until = _period(params, world)
    found = await movements.flow(session, world.id, since, until, params.granularity)
    return FlowResponse(
        since=since,
        until=until,
        granularity=found.granularity,
        points=[
            FlowPoint(starts_at=point.starts_at, joined=point.joined, left=point.left)
            for point in found.points
        ],
    )


@router.get(
    "/states",
    summary="Every subscription the engine holds, by the state it is in",
    dependencies=[RequirePermission("analytics.read")],
    responses=error_responses(401, 403),
)
async def read_states() -> StatesResponse:
    found = await standing.snapshot(current_world())
    return StatesResponse(
        states=[StateCount(state=each.state.value, count=each.count) for each in found.states],
        total=found.total,
    )


@router.get(
    "/quiet",
    summary="The quiet cohort, split by how long the silence has run",
    dependencies=[RequirePermission("analytics.read")],
    responses=error_responses(401, 403),
)
async def read_quiet(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QuietResponse:
    world = current_world()
    projection = await load_projection(session, world.id)
    found = await standing.quiet(world, projection, now=world.clock.now())
    return QuietResponse(
        bands=[
            QuietBand(from_days=band.from_days, to_days=band.to_days, count=band.count)
            for band in found.bands
        ],
        total=found.total,
    )


@router.get(
    "/revenue",
    summary="What was taken, by calendar month",
    dependencies=[RequirePermission("analytics.read")],
    responses=error_responses(401, 403, 422),
)
async def read_revenue(
    params: Annotated[RevenueParams, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RevenueResponse:
    world = current_world()
    found = await movements.revenue(session, world.id, world.clock.now(), params.months)
    return RevenueResponse(
        currency=found.currency,
        months=[
            RevenueMonth(starts_at=month.starts_at, amount=month.amount) for month in found.months
        ],
    )
