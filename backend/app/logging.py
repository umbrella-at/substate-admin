"""Structured logging, and the request context every line is written against.

One JSON object per line on stdout, which systemd captures verbatim: `journalctl -u
substate-admin-api -o cat | jq` is the whole log tooling this service needs. Uvicorn's own
records go through the same formatter, so a startup failure is the same shape as a request.

What is never written here is as fixed as what is: no Authorization header, no cookie in either
direction, no password, no refresh token, and no raw client address. Addresses appear only as
`ip_hash`. The rate limiter needs to count them, the journal does not need to keep them.
"""

import logging
import re
import sys
import time
import uuid
from collections.abc import Sequence
from typing import Any, Final, cast

import structlog
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.typing import EventDict, Processor

REQUEST_ID_HEADER: Final = "X-Request-Id"

# Namespaced, because the scope is shared with the server and with every other middleware. It is
# the scope rather than a contextvar alone because the 500 handler runs above the middleware
# that binds the contextvar, and by then the binding is gone — the scope is the same object all
# the way up.
_REQUEST_ID_SCOPE_KEY: Final = "substate.request_id"

# An inbound request id is echoed back in a header and written into the journal, so it is
# checked before it is trusted: a newline in this value forges a log line, and a newline in a
# response header is a response-splitting bug.
_SAFE_REQUEST_ID: Final = re.compile(r"[A-Za-z0-9._~-]{1,64}")

_REDACTED: Final = "[redacted]"

# A backstop, not the rule. The rule is that nothing logs these; this is what happens when a
# later keyword argument is named `password` anyway. The value is replaced rather than dropped
# so the mistake is visible in the journal instead of silently invisible.
_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "password",
        "new_password",
        "token",
        "access_token",
        "refresh_token",
        "token_hash",
        "jwt_secret",
        "database_url",
        "ip",
        "client_ip",
    }
)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """A logger for one module.

    Typed as the stdlib-flavoured BoundLogger because that is what `configure_logging` installs;
    `structlog.get_logger` itself promises nothing a type checker can use.
    """
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


# Bound lazily: this module is imported long before `configure_logging` runs, and the first call
# is what fixes the configuration in place.
_log = get_logger("app.request")


def _redact(_: Any, __: str, event_dict: EventDict) -> EventDict:
    for key in tuple(event_dict):
        if key.lower() in _FORBIDDEN_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def _shared_processors() -> Sequence[Processor]:
    """The processors that run for structlog and stdlib records alike."""
    return (
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    )


def configure_logging(*, level: int = logging.INFO) -> None:
    """Point structlog and the standard library at one JSON handler on stdout.

    Called once, from the application's lifespan and from the CLI. Uvicorn's loggers are stripped
    of their own handlers and left to propagate, which is what stops a startup traceback from
    arriving as unparseable text between two JSON objects.
    """
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *_shared_processors(),
            # Hands the event dict to the stdlib handler below instead of rendering it here, so
            # that structlog and uvicorn share one formatter and one destination.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=list(_shared_processors()),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _redact,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # uvicorn.access is silenced, not adopted. `--no-access-log` works by setting this logger's
    # propagate to False, and uvicorn does that while building its Config — before it imports this
    # module. Letting it propagate here would quietly undo the flag, and uvicorn's access line
    # carries the RAW client address, which is exactly what the deny-list below and Caddy's ip_mask
    # exist to keep out of the journal. Our own `request` line already reports the same request,
    # with the address hashed.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False


def get_request_id(request: Request | None = None) -> str | None:
    """The id of the request being served, if there is one.

    The scope is asked first because it is the source that outlives the request: an exception
    handler running above the middleware still holds the same scope object.
    """
    if request is not None:
        from_scope = request.scope.get(_REQUEST_ID_SCOPE_KEY)
        if isinstance(from_scope, str):
            return from_scope
    bound = structlog.contextvars.get_contextvars().get("request_id")
    return bound if isinstance(bound, str) else None


def bind_request_context(
    *, user_id: uuid.UUID | str | None = None, ip_hash: str | None = None
) -> None:
    """Add what authentication learned to every remaining line of this request.

    Called by the dependency that resolves the current user and by the rate limiter. Both know
    things the middleware cannot: the middleware runs before anyone has been identified.
    """
    values: dict[str, str] = {}
    if user_id is not None:
        values["user_id"] = str(user_id)
    if ip_hash is not None:
        values["ip_hash"] = ip_hash
    if values:
        structlog.contextvars.bind_contextvars(**values)


def _inbound_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            return candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else None
    return None


def _level_for(status: int) -> int:
    """The level of the one-line-per-request record.

    Levelling purely by status number reads well until you notice what 401 means here. The panel
    holds the access token in memory only, so the first request of every single visit is a refresh
    attempt by a browser that may hold no cookie at all, and its 401 is the ordinary, expected
    answer. Logging that at WARNING makes the most common request on the only public page the
    loudest thing in the journal, and a level that fires on the happy path has stopped being a
    signal.

    So 401 is INFO: unauthenticated is the normal state of a public endpoint, not an anomaly.
    Nothing is lost by it — a failed login writes its own `login_failed` warning carrying the
    reason, and a burst writes `login_rate_limited`. Those say something a status number cannot.

    403 stays WARNING, and the difference from 401 is the point: it means a request that DID
    authenticate asked for something its role does not allow, which is either a bug in the panel
    or someone probing.
    """
    if status >= 500:
        return logging.ERROR
    if status == 401:
        return logging.INFO
    if status >= 400:
        return logging.WARNING
    return logging.INFO


class RequestContextMiddleware:
    """Mints the request id, binds it, echoes it, and writes the one line per request.

    Raw ASGI rather than BaseHTTPMiddleware: BaseHTTPMiddleware runs the endpoint in a separate
    task, and a contextvar bound inside that task — `user_id`, `ip_hash` — is not visible again
    out here when the line is written. The access line would be permanently anonymous.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _inbound_request_id(scope) or str(uuid.uuid4())
        scope[_REQUEST_ID_SCOPE_KEY] = request_id

        # Each request is served in its own task with its own copy of the context, so clearing
        # here cannot disturb a request in flight, and it stops anything a previous handler left
        # behind from being attributed to this one.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Nothing sent means the application raised: the response will be the 500 that
        # ServerErrorMiddleware writes above this layer.
        status = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).setdefault(REQUEST_ID_HEADER, request_id)
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            _log.log(
                _level_for(status),
                "request",
                method=scope.get("method"),
                # The path, not the full URL: a query string is client-supplied text, and
                # nothing this API reads from one is worth keeping in the journal.
                path=scope.get("path"),
                status=status,
                duration_ms=duration_ms,
            )
