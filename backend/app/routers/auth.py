"""Login, refresh, logout, and the session's own description of itself.

Three of the four routes below are public, and that is the whole attack surface of this service.
Two properties are load-bearing across them:

Login gives one answer. An unknown address, a wrong password and a disabled account all produce
401 INVALID_CREDENTIALS with the same sentence, and all three spend exactly the same argon2 work,
so neither the body nor the clock says which it was. The real reason is written to the journal,
where it is useful and unreachable. A distinct "this account is disabled" would turn the only
page an unauthenticated visitor can reach into an account-enumeration oracle.

Every refusal to refresh clears the cookie. A refresh token that has been rejected once will be
rejected forever; leaving it in the browser means the panel replays it on every load, and the one
token that reuse detection condemned ends every session the person has signed back into since,
every time it is presented.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import NowProvider, get_now, get_session
from app.deps import Authenticated, Identity, Public
from app.errors import ApiError, ErrorCode
from app.logging import bind_request_context, get_logger
from app.models import User, normalize_email
from app.routers import error_responses
from app.schemas import LoginRequest, MeResponse, RoleSummary, TokenResponse, UserProfile
from app.security.passwords import hash_password, verify_dummy_password, verify_password
from app.security.ratelimit import (
    LOGIN_PER_EMAIL,
    LOGIN_PER_IP,
    REFRESH_PER_IP,
    RateLimitDecision,
    client_ip_hash,
    get_limiter,
)
from app.security.refresh import (
    RefreshFailure,
    RefreshRejected,
    clear_refresh_cookie,
    issue_for_login,
    read_refresh_cookie,
    revoke_family_for_token,
    rotate,
    set_refresh_cookie,
)
from app.security.tokens import encode_access_token

_log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Two failure reasons reach the client as something other than "this token is no longer valid".
# Everything else — an unknown token, an expired one, a family that has run out its ninety days, a
# session that was logged out or caught in a cascade — is one answer outside this process, because
# the differences between them are useful in a log and are nobody else's business.
_REFRESH_ERROR_CODES: Final[Mapping[RefreshFailure, ErrorCode]] = MappingProxyType(
    {
        RefreshFailure.REUSED: ErrorCode.REFRESH_TOKEN_REUSED,
        RefreshFailure.INACTIVE: ErrorCode.USER_INACTIVE,
    }
)


@router.post(
    "/login",
    summary="Exchange an email and password for an access token",
    dependencies=[Public()],
    responses=error_responses(401, 422, 429),
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    now: Annotated[NowProvider, Depends(get_now)],
) -> TokenResponse:
    """Authenticate a person and start a refresh-token family for the device they used."""
    instant = now()
    limiter = get_limiter()

    ip_key = client_ip_hash(request)
    bind_request_context(ip_hash=ip_key)

    # Counted per attempt and never cleared: an attacker working through a list of addresses never
    # fails against the same one twice, so a per-address counter alone would never fire.
    per_ip = limiter.hit(LOGIN_PER_IP, ip_key, now=instant)
    if not per_ip.allowed:
        _log.warning("login_rate_limited", scope="ip", retry_after=per_ip.retry_after)
        raise _rate_limited(per_ip)

    email = normalize_email(body.email)

    # Recorded on the way in and refunded by the reset below when the password turns out to be
    # right. Reading the counter here and recording the failure afterwards would leave the lookup
    # and one argon2 verification between the two, and attempts that arrive together would all
    # read a counter none of them had written to yet — a ceiling of five that fifty simultaneous
    # requests walk straight through, enforced only against an attacker patient enough to wait for
    # each answer.
    per_email = limiter.hit(LOGIN_PER_EMAIL, email, now=instant)
    if not per_email.allowed:
        _log.warning("login_rate_limited", scope="email", retry_after=per_email.retry_after)
        raise _rate_limited(per_email)

    # One statement: the joined eager load on User.role brings the role's code back with the row,
    # and the log line below needs it.
    #
    # An operator of this installation, which is what `world_id IS NULL` means. A sandbox invents
    # operators of its own and they have no password anybody was ever given; without the predicate
    # `one_or_none` would raise on the address two worlds happen to share, and a 500 at the login
    # form is the last place to discover it.
    user = (
        (await session.execute(select(User).where(User.email == email, User.world_id.is_(None))))
        .scalars()
        .one_or_none()
    )

    if user is None:
        # A verification nobody asked for, against a hash of bytes that were discarded at import.
        # Without it "no such address" returns in microseconds while "wrong password" costs
        # twenty-five milliseconds, and the difference is measurable from anywhere on the internet.
        verify_dummy_password(body.password)
        raise _reject_login("no_user")

    # The address exists, so the request is attributable from here on — including its refusals.
    bind_request_context(user_id=user.id)

    verification = verify_password(body.password, user.password_hash)
    if not verification.ok:
        raise _reject_login("bad_password")

    # Asked after the verification, never before. Short-circuiting on a disabled account would
    # skip the argon2 work and answer in a fraction of the time, which is the same oracle by a
    # different route.
    if not user.is_active:
        raise _reject_login("disabled")

    if verification.outdated:
        # The argon2 parameters have moved on since this hash was written, and a successful login
        # is the only moment the plaintext exists to write a new one from. Computed here rather
        # than inside the verification, and below the check above rather than beside it: it is a
        # second argon2 operation, and spending it before `is_active` is read would make a correct
        # password against a disabled account slower than a wrong one against a live one.
        user.password_hash = hash_password(body.password)
    user.last_login_at = instant

    # Commits, and carries the two writes above with it. One round trip, and no window in which a
    # refresh token exists for a login that was never recorded.
    issued = await issue_for_login(session, user_id=user.id, now=instant)

    # The person proved they know the password, so the attempts that came before it are no longer
    # evidence of anything — including the one this request recorded on its way in, which is what
    # makes the counter a count of failures again. The per-address counter is deliberately left
    # alone.
    limiter.reset(LOGIN_PER_EMAIL, email)

    set_refresh_cookie(response, issued)
    _log.info("login_succeeded", role=user.role.code)
    return _access_token_for(user.id, instant)


@router.post(
    "/refresh",
    summary="Rotate the refresh cookie and mint a new access token",
    # Public because the cookie is the credential. This route is what a client with an expired
    # access token calls, so requiring an unexpired one would make it unreachable exactly when it
    # is needed.
    dependencies=[Public()],
    responses=error_responses(401, 429),
)
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    now: Annotated[NowProvider, Depends(get_now)],
) -> TokenResponse:
    """Consume the presented refresh token and issue its successor in the same family."""
    instant = now()

    ip_key = client_ip_hash(request)
    bind_request_context(ip_hash=ip_key)

    # A loose ceiling on a runaway client rather than a security boundary: the token itself is the
    # credential, and presenting a bad one twice already ends the session.
    decision = get_limiter().hit(REFRESH_PER_IP, ip_key, now=instant)
    if not decision.allowed:
        _log.warning("refresh_rate_limited", retry_after=decision.retry_after)
        raise _rate_limited(decision)

    presented = read_refresh_cookie(request)
    if presented is None:
        # No cookie at all: a first visit, a cleared browser, or something calling this by hand.
        # Answered exactly like a token that no longer exists, and cleared anyway in case what is
        # there is a cookie this route cannot read.
        _log.info("refresh_failed", reason="absent")
        raise ApiError(ErrorCode.REFRESH_TOKEN_INVALID, headers=_cleared_cookie())

    outcome = await rotate(session, presented=presented, now=instant)
    if isinstance(outcome, RefreshRejected):
        raise _reject_refresh(outcome)

    bind_request_context(user_id=outcome.user.id)
    set_refresh_cookie(response, outcome.token)

    # `grace` says the presented token had already been consumed and the thirty-second window
    # covered it — a reload with a request in flight, a second tab, a retry after the wifi
    # dropped. Worth a line: a client producing these steadily has a bug in its refresh
    # scheduling, and the alternative to the window is logging that person out.
    _log.info("refresh_rotated", grace=outcome.grace)
    return _access_token_for(outcome.user.id, instant)


@router.post(
    "/logout",
    summary="Revoke this device's refresh-token family",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    # Public, and deliberately so: logout takes no access token. Access tokens last fifteen
    # minutes, the thing being revoked is the refresh family, and its cookie is the credential
    # that names it. Requiring a live access token would mean a tab left open over lunch could no
    # longer be signed out, and the client's only recourse would be to refresh first — which is to
    # mint a session in order to end it.
    dependencies=[Public()],
)
async def logout(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    now: Annotated[NowProvider, Depends(get_now)],
) -> Response:
    """Always 204. A caller who is already logged out has got what they asked for."""
    # Built here rather than injected, so the cookie is cleared on the response that is actually
    # returned even if the revocation below finds nothing to revoke.
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response)

    presented = read_refresh_cookie(request)
    if presented is None:
        _log.info("logout", revoked=False)
        return response

    try:
        revoked = await revoke_family_for_token(session, presented=presented, now=now())
    except SQLAlchemyError as exc:
        # "Always 204, always clears the cookie" is the promise, and a database that is down is
        # exactly when a person is most likely to be trying to get out. A 500 here would leave the
        # cookie in the browser, so the panel would look signed in and replay a token on every
        # load. The family stays revocable — the token is still in the table, and it still expires
        # — and the failure is loud in the journal rather than in the client.
        #
        # The type and nothing else: a psycopg error carries the statement it failed on.
        _log.error("logout_revocation_failed", error=type(exc).__name__)
        return response

    _log.info("logout", revoked=revoked)
    return response


@router.get(
    "/me",
    summary="Describe the current session",
    responses=error_responses(401),
)
async def me(identity: Annotated[Identity, Authenticated()]) -> MeResponse:
    """Report the user, their role and what that role grants, as the database says right now."""
    return MeResponse(
        # Both built through the response models rather than dumped from the ORM rows: only the
        # declared fields are read, which is what keeps `password_hash` and `role_id` inside this
        # process without anyone having to remember to exclude them.
        user=UserProfile.model_validate(identity.user),
        role=RoleSummary.model_validate(identity.role),
        # Flat and sorted. The set has no order of its own, and a list that reorders itself
        # between two identical requests is a diff nobody can read.
        permissions=sorted(identity.permissions),
        kind=identity.kind,
        # Derived from the verified claim rather than written as null: a demo token names a world,
        # and no dependency in this service accepts one, so this is null today by consequence.
        world_id=str(identity.world_id) if identity.world_id is not None else None,
    )


def _access_token_for(user_id: uuid.UUID, now: datetime) -> TokenResponse:
    """The body login and refresh both answer with."""
    issued = encode_access_token(user_id=user_id, now=now)
    return TokenResponse(
        access_token=issued.token,
        # Seconds of life, taken from the token's own claims. The client schedules its refresh off
        # its own clock, so handing it an instant would make a browser with a wrong clock either
        # refresh in a loop or never refresh at all.
        expires_in=int((issued.expires_at - issued.issued_at).total_seconds()),
    )


def _rate_limited(decision: RateLimitDecision) -> ApiError:
    """Refuse an attempt and say when the next one would be accepted."""
    return ApiError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(decision.retry_after)})


def _reject_login(reason: str) -> ApiError:
    """Write down which failure it was and return the one answer login gives.

    Every failing path goes through here, which is what makes the three of them identical from
    outside: no call site writes its own status, sentence or error code. The attempt was counted
    before the password was checked, so nothing is recorded here. The address is not logged — the
    journal already has the request id and, where there is one, the user id, and an unbounded log
    of who tried to sign in is a list of this panel's operators.
    """
    _log.warning("login_failed", reason=reason)
    return ApiError(ErrorCode.INVALID_CREDENTIALS)


def _reject_refresh(rejected: RefreshRejected) -> ApiError:
    """Refuse an exchange, clear the cookie, and keep the distinctions in the journal."""
    if rejected.user_id is not None:
        bind_request_context(user_id=rejected.user_id)
    _log.warning("refresh_failed", reason=rejected.reason)
    return ApiError(
        _REFRESH_ERROR_CODES.get(rejected.reason, ErrorCode.REFRESH_TOKEN_INVALID),
        headers=_cleared_cookie(),
    )


def _cleared_cookie() -> dict[str, str]:
    """The Set-Cookie that deletes the refresh cookie, rendered as a header on a failure.

    A `Response` injected into a route only reaches the client when the route returns; raising
    goes straight to an exception handler, which builds a response of its own. Carrying the header
    on the error is what makes "every refusal to refresh also clears the cookie" true on both
    refusal paths rather than on the one that happens to return.
    """
    carrier = Response()
    clear_refresh_cookie(carrier)
    return {"Set-Cookie": carrier.headers["set-cookie"]}
