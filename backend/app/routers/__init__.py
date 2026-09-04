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

from app.errors import ApiError, ErrorCode, ErrorEnvelope
from app.worlds.registry import BASE_WORLD_ID, World, WorldRegistry, get_registry

_ENVELOPE: Final[dict[str, Any]] = {"model": ErrorEnvelope}


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Document the failures one route can produce, all of them shaped like the envelope.

    Declaring 422 also suppresses the `HTTPValidationError` response FastAPI adds on its own to
    any route with a body or a query parameter: that shape is not what this service sends.
    """
    return {code: dict(_ENVELOPE) for code in statuses}


def current_world() -> World:
    """The world this request reads. Always the base world today.

    A function rather than a constant because it will eventually be read out of the token, and
    every caller already goes through it — which is why the world key went on everything from the
    first day rather than the last.
    """
    registry: WorldRegistry = get_registry()
    world = registry.get(BASE_WORLD_ID)
    if world is None:
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            message="The demonstration world is not available.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return world
