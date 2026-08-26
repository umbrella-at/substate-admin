"""The health endpoint, which asks the database rather than asking itself.

A probe that returns 200 because the process is running proves the process is running. The deploy
smoke check, the unit's restart loop and anyone reading a dashboard all want a different question
answered — whether this release can serve a request — and the only honest way to answer it is to
make Postgres say something. So this route runs a real SELECT 1 and reports 503 when it does not
come back.

The reply carries the version and the commit for the same reason: Caddy's SPA fallback answers
any unmatched path with index.html and a cheerful 200, so a smoke check that only asserts a
status code can pass over a backend that is not running at all. Comparing the commit cannot.
"""

from fastapi import APIRouter, Response

from app import __version__
from app.config import get_settings
from app.db import check_database
from app.deps import Public
from app.schemas import HealthResponse, WorldHealth
from app.worlds.bootstrap import base_world_status

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Report the service version and whether the database answers",
    dependencies=[Public()],
    responses={
        # Not the error envelope. A degraded reply is a successful measurement of a broken
        # dependency, and the caller wants the same four fields either way — including `commit`,
        # which is how a deploy tells "the new release is up but its database is down" from "the
        # old release is still serving".
        503: {"model": HealthResponse, "description": "The database did not answer."}
    },
)
async def health(response: Response) -> HealthResponse:
    """Answer 200 when Postgres responds and 503 when it does not."""
    # Never raises: `check_database` swallows the driver error, which would otherwise carry the
    # DSN — and the DSN carries the password — into an exception handler and a log line.
    reachable = await check_database()
    world = base_world_status()

    # Set on the injected response rather than raised, because a raise would be answered by the
    # error handlers with the envelope and none of the fields below.
    response.status_code = 200 if reachable else 503

    return HealthResponse(
        status="ok" if reachable else "degraded",
        version=__version__,
        commit=get_settings().commit,
        db=reachable,
        # Beside the database, not folded into `status`: an empty world is a bad shop window and
        # not an outage, and a smoke check that treated it as one would roll a deploy back over it.
        world=WorldHealth(seeded=world.seeded, subscribers=world.subscribers, events=world.events),
    )
