"""The HTTP surface, one module per group of routes.

Nothing is re-exported. `app.main` imports each module by name and mounts its router under /api,
so the list of what this service answers is one block of code in one file rather than a tuple
assembled here and a loop over it there.

What does live here is the single thing all three routers share: the `responses=` entries that
put the error envelope into the published schema. Without them the schema promises
`{"detail": ...}` on a 401 — FastAPI's default — while the handlers in `app.errors` send the
envelope, and a client generated from that schema is wrong about every failure it will ever see.
"""

from typing import Any, Final

from app.errors import ErrorEnvelope

_ENVELOPE: Final[dict[str, Any]] = {"model": ErrorEnvelope}


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Document the failures one route can produce, all of them shaped like the envelope.

    Declaring 422 also suppresses the `HTTPValidationError` response FastAPI adds on its own to
    any route with a body or a query parameter: that shape is not what this service sends.
    """
    responses: dict[int | str, dict[str, Any]] = {status: dict(_ENVELOPE) for status in statuses}
    return responses
