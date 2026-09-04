"""The HTTP surface, one module per group of routes.

Nothing is re-exported. `app.main` imports each module by name and mounts its router under /api,
so the list of what this service answers is one block of code in one file rather than a tuple
assembled here and a loop over it there.

What does live here is what the routers share. The `responses=` entries put the error envelope
into the published schema: without them the schema promises `{"detail": ...}` on a 401 — FastAPI's
default — while the handlers in `app.errors` send the envelope, and a client generated from that
schema is wrong about every failure it will ever see.

And the world a request reads. A second router that looked it up for itself would be a second
answer to which world the panel is showing.
"""

from typing import Any, Final

from fastapi import status

from app.deps import world_of_request
from app.errors import ApiError, ErrorCode, ErrorEnvelope
from app.worlds.registry import World

_ENVELOPE: Final[dict[str, Any]] = {"model": ErrorEnvelope}


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Document the failures one route can produce, all of them shaped like the envelope.

    Declaring 422 also suppresses the `HTTPValidationError` response FastAPI adds on its own to
    any route with a body or a query parameter: that shape is not what this service sends.
    """
    return {code: dict(_ENVELOPE) for code in statuses}


def current_world() -> World:
    """The world this request reads: a visitor's own sandbox, or the base world for an operator.

    Decided once, where the token is read, and carried on the request rather than looked up again
    here — a second lookup would be a second answer to which world the panel is showing, and the
    one thing a sandbox may never do is answer with somebody else's.

    None means the base world failed to build, which is a bad shop window rather than an outage:
    the panel serves, signing in works, and only the routes that need a world say so.
    """
    world = world_of_request()
    if world is None:
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            message="The demonstration world is not available.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return world
