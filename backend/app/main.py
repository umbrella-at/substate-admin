"""The application object: what is mounted, what wraps it, and what happens at either end.

`uvicorn app.main:app` is what the systemd unit runs, so importing this module is what starting
the service means. Two consequences are deliberate.

Importing it reads the configuration, and a host missing JWT_SECRET, IP_HASH_PEPPER or
DATABASE_URL fails here — loudly, before the socket is bound, in the same JSON the journal
already holds. The alternative is a process that starts happily and signs tokens with whatever
the default was.

Importing it does not touch Postgres. The engine is built by the first request that needs one and
the lifespan below asks the database nothing, because the unit orders itself after
postgresql.service — which on Debian returns before the cluster accepts connections — and pairs
Restart=always with no restart limit. A startup that required the database would turn a slow
Postgres into a restart loop; instead it costs one 503 from /api/health until the cluster is up.
"""

from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from app import __version__
from app.config import get_settings
from app.db import dispose_engine, get_engine
from app.errors import install_error_handlers
from app.logging import RequestContextMiddleware, configure_logging, get_logger
from app.routers import analytics, audit, auth, health, plans, subscribers, users
from app.worlds.bootstrap import build_base_world, set_base_world_status
from app.worlds.journal import flush_world
from app.worlds.registry import World, get_registry
from app.worlds.ticker import ticking

_log = get_logger(__name__)

# Caddy proxies /api/* with `handle`, not `handle_path`, so the prefix survives the hop and this
# application owns it. It is mounted here rather than baked into every route: the refresh cookie's
# Path=/api/auth is written against these paths, and a prefix that lived in the proxy could be
# changed there without anything in this repository noticing.
API_PREFIX: Final = "/api"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Bracket the served life of the process.

    The base world is built here and nowhere else, and it is the only thing in this function that
    touches the database. `sync-permissions` still runs from the deploy right after
    `alembic upgrade head` and never from startup: a restart would race it.

    Building the world cannot fail the boot. It is wrapped so that a seeder that raises leaves a
    panel with an empty shop window rather than a unit that restarts every two seconds — and the
    only way out of that loop is the provider's console.
    """
    settings = get_settings()
    _log.info(
        "startup",
        version=__version__,
        commit=settings.commit,
        app_env=settings.app_env,
        docs=settings.docs_enabled,
    )
    registry = get_registry()
    _, status = await build_base_world(registry, get_engine())
    set_base_world_status(status)

    async def record(world: World) -> None:
        """Put what a tick produced into the journal.

        Its own transaction per world and per round: a round that failed to record one sandbox
        should not take the base world's events down with it.
        """
        async with get_engine().begin() as connection:
            await flush_world(connection, world)

    try:
        async with ticking(registry, record):
            yield
    finally:
        # Hands the pool's connections back rather than leaving Postgres to time out backends
        # that nothing is ever going to speak to again.
        await dispose_engine()
        _log.info("shutdown")


def create_app() -> FastAPI:
    """Assemble the application.

    A factory, so the order below is written down once and a test can build a second application
    against different settings instead of reaching into a module-level object and mutating it.
    """
    # First, and before anything else can log. The line that reports a missing setting has to be
    # the same JSON as every line after it, or the one entry worth finding in the journal is the
    # one `jq` refuses to parse.
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title="substate-admin API",
        version=__version__,
        lifespan=lifespan,
        # Under /api with everything else, and absent entirely in production: an interactive
        # console enumerating every route of an admin panel is a map that helps nobody who is
        # supposed to be here.
        docs_url=f"{API_PREFIX}/docs" if settings.docs_enabled else None,
        openapi_url=f"{API_PREFIX}/openapi.json" if settings.docs_enabled else None,
        # ReDoc renders the same schema a second time. The OAuth2 redirect belongs to a flow this
        # service does not have, and left at its default it would mount a route at /docs — outside
        # the prefix Caddy proxies, where it would be answered by the SPA.
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
    )

    # The outermost of this application's own layers, so the request id exists before anything
    # below it can log and the duration it records covers every one of them.
    app.add_middleware(RequestContextMiddleware)

    # There is no CORSMiddleware, and its absence is the design. Caddy serves the panel and
    # proxies this API from one origin, which is also what makes SameSite=Lax the correct
    # attribute for the refresh cookie. A CORS policy here would be permission granted to an
    # origin that does not exist.

    install_error_handlers(app)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(users.router, prefix=API_PREFIX)
    app.include_router(plans.router, prefix=API_PREFIX)
    app.include_router(plans.programs_router, prefix=API_PREFIX)
    app.include_router(subscribers.router, prefix=API_PREFIX)
    app.include_router(audit.router, prefix=API_PREFIX)
    app.include_router(analytics.router, prefix=API_PREFIX)

    return app


def api_routes(app: FastAPI) -> tuple[APIRoute, ...]:
    """Every route this application actually serves.

    `app.routes` is not that list. Since FastAPI 0.141 `include_router` appends one lazy node per
    included router instead of copying its routes upward, so the top-level sequence holds three
    wrappers and not six routes. That matters far beyond tidiness: the check that no route reaches
    production without declaring who may call it walks a list of routes and asserts every one of
    them carries a declaration, and a walk over three objects that are not APIRoutes passes by
    finding nothing to inspect. A guard that cannot fail is not a guard.

    So the wrappers are unwrapped here, by the attribute that names what was included rather than
    by importing a private class, which also means the older shape — routes already flat — walks
    straight through. The APIRoute objects yielded are the ones the routers built, so their `path`
    is the path as written in the router, without the /api this application mounts them under.
    """
    return tuple(route for route in _flatten(app.routes) if isinstance(route, APIRoute))


def _flatten(routes: Iterable[BaseRoute]) -> Iterator[BaseRoute]:
    """Walk a route list, descending into anything that is an included router, not a route."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        included = getattr(route, "original_router", None)
        if included is None:
            # /api/docs and /api/openapi.json, which FastAPI generates and which are gated on
            # APP_ENV rather than on a declaration.
            yield route
            continue
        yield from _flatten(included.routes)


# The object the unit's ExecStart names. Built at import, which is where a misconfigured host is
# supposed to fail.
app = create_app()
