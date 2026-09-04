"""The time machine: where a world's clock stands, and winding it forward.

Forward only. `substate` compares a due date against now, so moving now backwards produces states
the engine could never have reached by itself — a renewed period nobody paid for, a grace that ends
before it began. A refusal is a bug report; a clamp is the same bug arriving later.

AN ADVANCE RUNS THE WORLD RATHER THAN JUST TICKING IT, AND THAT IS THE DIFFERENCE BETWEEN A
DEMONSTRATION AND A GRAVEYARD.

Nobody pays in a world that is only ticked: the engine expires whoever falls due and nothing
renews, arrives or comes back. Measured on the base world, a month of that takes ACTIVE from 248
to 86 and EXPIRED from 45 to 211, and three months leave 32 subscribers of 351 still paying.

So the same modelled life the history was made of runs over the days being crossed — a day at a
time, which is also what the engine needs: it crosses at most eight period boundaries per
subscription per tick, so one tick after a ninety-day jump would leave a weekly subscriber behind.
"""

from datetime import timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import Authenticated, Identity, RequirePermission
from app.errors import ApiError, ErrorCode
from app.logging import get_logger
from app.routers import current_world, error_responses
from app.schemas import AdvanceRequest, ClockResponse
from app.seed.run import carry_on
from app.worlds.journal import ProjectedSubscriber, flush_world, rewrite_projection
from app.worlds.registry import World

_log = get_logger(__name__)

router = APIRouter(prefix="/clock", tags=["clock"])

MAX_WIND: Final = timedelta(days=365)
"""How far a world may be wound in total, over every press.

THE THIRD OVERLOAD VALVE, AND THE ONE A CEILING ON WORLDS DOES NOT COVER. The ceiling bounds how
many sandboxes stand at once and the rate limit bounds how fast they are built; neither bounds how
big one of them grows.

Measured: a year of winding takes a world from 3773 journal rows to 31026 and from 351 subscribers
to 1160, and a full-year press costs 1.8 seconds of the only CPU there is. Nothing stopped a
visitor pressing it for their whole hour, and each press added another year of modelled life.

A year is far more than a demonstration needs — twelve presses of Month, or one of the field — and
it holds a world at about 30000 rows, so thirty-two of them at the ceiling are bounded too.
"""


@router.get(
    "",
    summary="Where this world's clock stands",
    dependencies=[Authenticated()],
    responses=error_responses(401, 503),
)
async def read_clock() -> ClockResponse:
    """Model time, and the offset it is made of.

    Readable by anybody with a session rather than by whoever may wind it: every screen already
    renders data measured against this clock, and a panel that cannot say what time its world
    thinks it is renders "just now" against the browser's.
    """
    return _reading(current_world())


@router.post(
    "/advance",
    summary="Wind this world forward",
    responses=error_responses(401, 403, 422, 503),
)
async def advance(
    body: AdvanceRequest,
    identity: Annotated[Identity, RequirePermission("demo.control")],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClockResponse:
    """Run the world forward `days` days and report where its clock landed.

    The two writes are the point of the endpoint as much as the clock is: the days produce events,
    and the subscribers who turned up during them have to move with the world — otherwise the quiet
    cohort becomes the whole table at the first press.
    """
    world = current_world()
    asked = timedelta(days=body.days)
    left = MAX_WIND - world.clock.offset
    if asked > left:
        # A refusal about the field, because that is what it is about: the body is well formed and
        # the number in it is one this world can no longer afford. The sentence says what is left.
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            message=(
                f"This world has been wound as far as it goes. "
                f"{max(left.days, 0)} of its 365 days are left."
            ),
            field="days",
            status_code=422,
        )

    population = world.population
    if population is None:
        # A world that never seeded. The panel serves without one, and this is the one route that
        # cannot: there is no life to continue.
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            message="The demonstration world is not available.",
            status_code=503,
        )

    report = await carry_on(
        world.engine, population, world.clock.advance, world.clock.now, days=body.days
    )

    connection = await session.connection()
    await flush_world(connection, world)
    await rewrite_projection(
        connection,
        world.id,
        [
            ProjectedSubscriber(user_id=uid, display_name=name, last_active_at=seen)
            for uid, name, seen in report.subscribers_projection
        ],
    )
    await session.commit()

    _log.info(
        "clock_advanced",
        world_id=world.id,
        days=body.days,
        subscribers=report.subscribers,
        states=report.states,
        role=identity.role.code,
    )
    return _reading(world)


def _reading(world: World) -> ClockResponse:
    return ClockResponse(
        now=world.clock.now(),
        # Whole seconds. The panel adds this to its own clock to render model time, and it ticks
        # in the browser rather than standing still between requests.
        offset_seconds=int(world.clock.offset.total_seconds()),
        is_sandbox=world.is_sandbox,
    )
