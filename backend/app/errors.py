"""The error envelope and the handlers that guarantee it.

Every failure this service reports has one shape:

    {"error": {"code": "...", "message": "...", "field": null}}

The frontend switches on `code`, shows `message`, and attaches the message to the form input
named by `field`. That contract only holds if it holds everywhere, so the handlers below cover
the failures nobody raises on purpose too: a 404 from the router, a 405 from a mistyped method,
a 422 from pydantic, and an unhandled exception. FastAPI's own replies are `{"detail": ...}` in
three different shapes, which would leave the frontend parsing errors by guessing.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from enum import StrEnum, auto
from types import MappingProxyType
from typing import Any, Final

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.logging import REQUEST_ID_HEADER, get_logger, get_request_id

_log = get_logger(__name__)


class ErrorCode(StrEnum):
    """The closed catalogue of machine-readable failures.

    Closed is the point: the frontend has a switch over these values, and a code invented at a
    call site is a code that falls through it.
    """

    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        # The value is the name, said once. Writing both out is how a member ends up sending a
        # string that no longer matches what everyone greps for.
        return name

    INVALID_CREDENTIALS = auto()
    NOT_AUTHENTICATED = auto()
    TOKEN_EXPIRED = auto()
    USER_INACTIVE = auto()
    PERMISSION_DENIED = auto()
    REFRESH_TOKEN_INVALID = auto()
    REFRESH_TOKEN_REUSED = auto()
    RATE_LIMITED = auto()
    VALIDATION_ERROR = auto()
    NOT_FOUND = auto()
    METHOD_NOT_ALLOWED = auto()
    INTERNAL_ERROR = auto()
    ROLE_IS_SYSTEM = auto()
    ROLE_IN_USE = auto()
    ROLE_CODE_TAKEN = auto()
    SANDBOX_GONE = auto()
    SANDBOX_FULL = auto()
    WORLD_FULLY_WOUND = auto()

    # Refusals that came out of `substate`. Each name is the exception's own, mechanically
    # respelled — `app.subscribers.operations` asserts that at import, so a code here and the
    # class it stands for cannot drift into two different words for one refusal.
    ALREADY_SUBSCRIBED = auto()
    UNKNOWN_PLAN = auto()
    UNKNOWN_PROMO_CODE = auto()
    PROMO_LIMIT_REACHED = auto()
    PROMO_ALREADY_BOUND = auto()
    UNKNOWN_REFERRAL_PROGRAM = auto()


# The status and the sentence that belong to each code, in one table. The three login failure
# paths must be indistinguishable from outside, and the cheapest way to guarantee that is for
# none of them to write the sentence themselves.
_DEFAULTS: Final[Mapping[ErrorCode, tuple[int, str]]] = MappingProxyType(
    {
        ErrorCode.INVALID_CREDENTIALS: (401, "Email or password is incorrect."),
        ErrorCode.NOT_AUTHENTICATED: (401, "Authentication is required."),
        ErrorCode.TOKEN_EXPIRED: (401, "The session has expired."),
        ErrorCode.USER_INACTIVE: (401, "This account is disabled."),
        ErrorCode.PERMISSION_DENIED: (403, "You do not have permission to do that."),
        ErrorCode.REFRESH_TOKEN_INVALID: (401, "The session is no longer valid."),
        ErrorCode.REFRESH_TOKEN_REUSED: (401, "The session was ended for security reasons."),
        ErrorCode.RATE_LIMITED: (429, "Too many attempts. Try again in a few minutes."),
        ErrorCode.VALIDATION_ERROR: (422, "The submitted data is invalid."),
        ErrorCode.NOT_FOUND: (404, "The requested resource does not exist."),
        ErrorCode.METHOD_NOT_ALLOWED: (405, "That method is not allowed for this resource."),
        # Not "something went wrong", which is the one sentence this API's own rules forbid and
        # which is the fallback behind every operation button. It cannot name the cause without
        # leaking one, so it names the thing that can be chased instead.
        ErrorCode.INTERNAL_ERROR: (
            500,
            "The service failed to handle this request. Try again; the request id in the "
            "response headers identifies it in the log.",
        ),
        # The two the roles editor produces, and one the API can produce without an editor. All
        # three are 409: they are refusals about the state of the world rather than about a value
        # that was submitted, and each names the way out.
        ErrorCode.ROLE_IS_SYSTEM: (
            409,
            "This role is defined by the application and is restored on every deploy. "
            "Copy it into a role of your own and change that.",
        ),
        ErrorCode.ROLE_IN_USE: (
            409,
            "People still hold this role. Move them to another one, and it can be deleted.",
        ),
        ErrorCode.ROLE_CODE_TAKEN: (409, "A role already exists under that code."),
        # A refusal names what is true and what can be done about it. "Something went wrong" is
        # the one sentence none of these may become: the engine knew exactly what was wrong.
        #
        # 409 for a refusal about the state of the world, 422 for one about a value that was
        # submitted — and 422 carries `field`, which is what puts the sentence under the input
        # that caused it rather than in a banner above the form.
        ErrorCode.ALREADY_SUBSCRIBED: (
            409,
            "This subscriber already has a live subscription. Cancel it first, or change the plan.",
        ),
        ErrorCode.UNKNOWN_PLAN: (422, "No plan is registered under that id."),
        ErrorCode.UNKNOWN_PROMO_CODE: (422, "No promo code is registered under that code."),
        ErrorCode.PROMO_LIMIT_REACHED: (
            409,
            "That code cannot be redeemed again: either this subscriber has already used it, or "
            "the code is used up. A different code can still be redeemed.",
        ),
        ErrorCode.PROMO_ALREADY_BOUND: (
            409,
            "A discount is already attached, and only one can apply at a time. "
            "A code that grants days can still be redeemed.",
        ),
        ErrorCode.UNKNOWN_REFERRAL_PROGRAM: (
            422,
            "No referral programme is registered under that id.",
        ),
        # 410 rather than 404, and one code for two endings. A demonstration that ran out of time
        # and one whose process was restarted under it are the same event from outside, and the
        # panel's answer to both is the same: it was here, it is over, start another.
        ErrorCode.SANDBOX_GONE: (
            410,
            "This demonstration has ended. Everything in it was invented and is now gone; "
            "starting another takes one click.",
        ),
        # 409 rather than 422, by the rule this table states for itself: the body is well formed
        # and the world is the thing that will not have it. A 422 on `days` would tell a client to
        # correct a number, and no number succeeds.
        ErrorCode.WORLD_FULLY_WOUND: (
            409,
            "This world has been wound as far as it goes.",
        ),
        ErrorCode.SANDBOX_FULL: (
            503,
            "Every demonstration slot is in use just now. They are handed back within the hour, "
            "and the panel can be read in the meantime.",
        ),
    }
)

# A code with no default is a KeyError on the unhappy path, which is precisely where nobody is
# watching. Fail at import instead.
if set(_DEFAULTS) != set(ErrorCode):
    raise RuntimeError("every ErrorCode needs a default status and message")

# What a bare HTTPException means when it comes from the framework rather than from a route.
_STATUS_TO_CODE: Final[Mapping[int, ErrorCode]] = MappingProxyType(
    {
        401: ErrorCode.NOT_AUTHENTICATED,
        403: ErrorCode.PERMISSION_DENIED,
        404: ErrorCode.NOT_FOUND,
        405: ErrorCode.METHOD_NOT_ALLOWED,
        429: ErrorCode.RATE_LIMITED,
    }
)

# pydantic prefixes every location with where it read the value. The frontend only knows about
# its own form fields, so the prefix is dropped before the path is handed over.
_LOCATIONS: Final[frozenset[str]] = frozenset({"body", "query", "path", "header", "cookie"})


class ErrorBody(BaseModel):
    """The contents of the envelope."""

    code: ErrorCode
    message: str

    # Always present, `null` when the failure is not about one input. A key that comes and goes
    # is a key every consumer has to test for.
    field: str | None = None


class ErrorEnvelope(BaseModel):
    """The body of every non-2xx response this service produces.

    Routes declare it in `responses=` so the published schema says so as well.
    """

    error: ErrorBody


class ApiError(HTTPException):
    """A failure this service reports deliberately.

    It extends HTTPException so that Starlette's existing machinery routes it — one handler then
    covers both what we raise and what the framework raises — and so that raising it from a
    dependency behaves exactly like raising it from a route.

    The status and the message come from the catalogue unless the call site overrides them, which
    is what keeps `ApiError(ErrorCode.PERMISSION_DENIED)` from ever being answered with a 401.
    """

    def __init__(
        self,
        code: ErrorCode,
        *,
        message: str | None = None,
        field: str | None = None,
        status_code: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        default_status, default_message = _DEFAULTS[code]
        self.code = code
        self.message = message if message is not None else default_message
        self.field = field
        # `headers` carries the two things a failure has to say outside the body: Retry-After on
        # a 429, and the Set-Cookie that clears a refresh cookie the client must stop replaying.
        super().__init__(
            status_code=status_code if status_code is not None else default_status,
            detail=self.message,
            headers=dict(headers) if headers is not None else None,
        )


def error_payload(
    code: ErrorCode,
    *,
    message: str | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    """Build the envelope for one failure."""
    body = ErrorBody(
        code=code,
        message=message if message is not None else _DEFAULTS[code][1],
        field=field,
    )
    return ErrorEnvelope(error=body).model_dump(mode="json")


def error_response(
    code: ErrorCode,
    *,
    message: str | None = None,
    field: str | None = None,
    status_code: int | None = None,
    headers: Mapping[str, str] | None = None,
    request: Request | None = None,
) -> JSONResponse:
    """Render one failure as a response.

    The request id is echoed here as well as by the middleware: a 500 is written by the
    outermost middleware of all, above the layer that stamps the header onto ordinary responses,
    and the id on the failing response is what makes the failure findable in the journal.
    """
    final_headers = dict(headers) if headers is not None else {}
    request_id = get_request_id(request) if request is not None else None
    if request_id is not None:
        final_headers.setdefault(REQUEST_ID_HEADER, request_id)
    return JSONResponse(
        status_code=status_code if status_code is not None else _DEFAULTS[code][0],
        content=error_payload(code, message=message, field=field),
        headers=final_headers or None,
    )


def field_from_loc(loc: Sequence[str | int]) -> str | None:
    """Turn a pydantic error location into the name of a form field.

    ("body", "email")             -> "email"
    ("body", "page_size")         -> "pageSize"
    ("query", "filters", 0, "op") -> "filters.0.op"
    ("body",) / ()                -> None: the failure is about the payload as a whole

    Segments are camelCased individually rather than through pydantic's `to_camel`: the
    locations pydantic reports are the wire aliases, which are already camelCase, and a
    conversion that is not idempotent would turn `pageSize` into something else.
    """
    parts: list[str | int] = list(loc)
    if parts and parts[0] in _LOCATIONS:
        parts = parts[1:]
    if not parts:
        return None
    return ".".join(_camel(str(part)) for part in parts)


def _camel(segment: str) -> str:
    """snake_case -> camelCase, leaving anything already camelCase alone."""
    head, *rest = segment.split("_")
    return head + "".join(word[:1].upper() + word[1:] for word in rest)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Answer both ApiError and the HTTPExceptions Starlette raises on its own."""
    if isinstance(exc, ApiError):
        return error_response(
            exc.code,
            message=exc.message,
            field=exc.field,
            status_code=exc.status_code,
            headers=exc.headers,
            request=request,
        )

    # Everything else here was raised by the framework: a 404 with no matching route, a 405 with
    # its Allow header. `exc.detail` is the HTTP reason phrase — "Not Found" — which is not a
    # sentence anyone should read in a toast, so the catalogue's message wins. Routes in this
    # service raise ApiError and keep their wording.
    code = _STATUS_TO_CODE.get(
        exc.status_code,
        ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.VALIDATION_ERROR,
    )
    return error_response(
        code,
        status_code=exc.status_code,
        headers=exc.headers,
        request=request,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Answer a request body, query or path that failed validation.

    422 stays 422. The status is what the frontend's generic handler keys on; `field` is what
    puts the message under the right input.
    """
    errors: Sequence[Any] = exc.errors()
    field = field_from_loc(errors[0].get("loc", ())) if errors else None

    # pydantic's own message names the constraint that failed ("String should have at most 128
    # characters"), which is an implementation detail of this service. The frontend has its own
    # wording per field; it gets the field.
    return error_response(ErrorCode.VALIDATION_ERROR, field=field, status_code=422, request=request)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Answer a bug.

    The traceback goes to the journal beside the request id and nothing else leaves the process:
    an exception's message is as likely to be a DSN or a row of user data as it is to be useful.
    """
    _log.error(
        "unhandled_exception",
        method=request.method,
        path=request.url.path,
        request_id=get_request_id(request),
        exc_info=exc,
    )
    return error_response(ErrorCode.INTERNAL_ERROR, status_code=500, request=request)


# Starlette types a handler as taking the base Exception, so a handler that names the exception
# it actually answers is not assignable to it. The narrowing happens where the handler is
# registered — against the class the framework will match — rather than by widening three
# signatures and testing the type again inside each of them.
_Handler = Callable[[Request, Any], Awaitable[JSONResponse]]


def _register(app: FastAPI, exception: type[Exception], handler: _Handler) -> None:
    app.add_exception_handler(exception, handler)


def install_error_handlers(app: FastAPI) -> None:
    """Replace FastAPI's default handlers with the ones above.

    Handles the base classes on purpose: Starlette resolves a handler by walking the exception's
    MRO, so registering `HTTPException` also covers FastAPI's subclass, and registering
    `Exception` is what gives ServerErrorMiddleware something to call instead of its own
    plain-text 500.
    """
    _register(app, HTTPException, http_exception_handler)
    _register(app, RequestValidationError, validation_exception_handler)
    _register(app, Exception, unhandled_exception_handler)
