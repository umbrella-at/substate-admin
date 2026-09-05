"""Who may call a route, and who is calling it.

Every route in this service carries exactly one of `Public()`, `Authenticated()` or
`RequirePermission(code)`. No marker does not mean public: `undeclared_routes` walks the router
and reports anything carrying none, and a test fails the build on it. That is why `Public()` is a
real dependency with nothing in it — an answer that has to be written down cannot be forgotten
silently, and because the declaration *is* the dependency FastAPI awaits, a route cannot claim to
be guarded without actually being guarded.

Permissions are not in the access token. They are read from the database, so a role edited at
10:00 stops granting what it granted at 09:55 on the next request rather than fifteen minutes
later. What an authenticated request costs is one statement — the user and their role, inner
joined — and that statement is what answers `is_active` too. The role → permission mapping is
small enough to hold whole (four system roles, at most a dozen grants each), so it is read in one
statement and cached for thirty seconds instead of being joined onto every request; any write to a
role drops it.
"""

import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Final, Literal

from fastapi import params
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import BaseRoute, Route

from app.db import NowProvider, get_now, get_session
from app.demo.sandboxes import SANDBOX_TTL
from app.errors import ApiError, ErrorCode
from app.logging import bind_request_context, get_logger
from app.models import Role, RolePermission, User
from app.permissions import PermissionCode
from app.security.tokens import (
    AccessTokenClaims,
    AccessTokenExpired,
    AccessTokenInvalid,
    decode_access_token,
)
from app.worlds.registry import BASE_WORLD_ID, World, get_registry

_log = get_logger(__name__)

_world: ContextVar[World | None] = ContextVar("world_of_request", default=None)
"""The world this request reads, decided once, where the token is read.

A context variable rather than a parameter on eleven route bodies, and the same mechanism the
request's log context already uses: the answer is a fact about the request, and every route that
needs it needs the same one. `app.routers.current_world` is what reads it.
"""


def world_of_request() -> World | None:
    """The world the current request resolved to, or None outside one."""
    return _world.get()


# Long enough that a burst of requests from one panel costs one read of a table that changes
# perhaps twice a year, short enough that a role edited by hand in psql — which cannot call
# `invalidate_permission_cache` — takes effect while the person who did it is still watching.
PERMISSION_CACHE_TTL: Final = timedelta(seconds=30)

# The attribute the three declarations carry and `route_declarations` looks for.
DECLARATION_ATTR: Final = "route_declaration"

# The only routes this application serves that carry no declaration, and the only exemption
# `undeclared_routes` allows. FastAPI generates them from `docs_url` and `openapi_url`; they are
# plain Starlette routes, which never enter the dependency machinery a declaration lives in, and
# they are gated on APP_ENV rather than on a permission — in production they are not mounted at
# all. Written out here rather than imported from app.main, which imports this module; a test
# asserts that the two agree about them.
DOCUMENTATION_PATHS: Final[frozenset[str]] = frozenset({"/api/docs", "/api/openapi.json"})

# RFC 6750 says a 401 refusing a bearer token names the scheme it wanted. The frontend switches on
# the error code and ignores this, but a 401 with no challenge is a protocol answer that means
# something else.
_BEARER_CHALLENGE: Final[Mapping[str, str]] = MappingProxyType({"WWW-Authenticate": "Bearer"})

# auto_error=False because FastAPI's own refusal is a 403 shaped `{"detail": ...}`: the wrong
# status for a missing credential and the wrong body for this API. Declared all the same, so the
# published schema — and the Authorize button in the docs — describe the scheme.
optional_bearer: Final = HTTPBearer(bearerFormat="JWT", auto_error=False)


class Access(StrEnum):
    """What a route declared about who may call it."""

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    PERMISSION = "permission"


@dataclass(frozen=True, slots=True)
class RouteDeclaration:
    """One route's answer, in a form a test can read back off the router."""

    access: Access

    # Set only when access is PERMISSION.
    permission: PermissionCode | None = None


@dataclass(frozen=True, slots=True)
class Identity:
    """Who is making this request, as the database describes them at this moment."""

    user: User

    # The codes the role grants, as rows — not as the catalogue in app.permissions. A grant naming
    # a code the catalogue has since dropped is a grant nobody can spend, not a reason to fail a
    # request, so this stays `str` and the typing happens where a route names a code.
    permissions: frozenset[str]

    claims: AccessTokenClaims

    world: World | None
    """The world this session reads: a visitor's own sandbox, or the base world for an operator.

    None only when the base world failed to build, which is a bad shop window rather than an
    outage — signing in still works, and `app.routers.current_world` is what answers 503 to the
    routes that actually need a world.
    """

    @property
    def role(self) -> Role:
        return self.user.role

    @property
    def kind(self) -> Literal["user", "demo"]:
        """What sort of session this is, for GET /api/auth/me.

        Derived from the verified claim rather than written as a constant in the route that
        reports it, because the claim is where the answer is.
        """
        return "demo" if self.claims.typ == "demo" else "user"

    @property
    def world_id(self) -> uuid.UUID | None:
        return self.claims.world_id

    @property
    def world_scope(self) -> str | None:
        """The value `world_id` carries on the rows this session may see.

        None for an operator of this installation, and the sandbox's id for a visitor. Every query
        over users, roles and the audit is filtered by it, which is the only thing between one
        demonstration and the next.
        """
        return str(self.claims.world_id) if self.claims.world_id is not None else None

    def has(self, code: PermissionCode) -> bool:
        """Whether this identity holds one permission. Typed, so a typo is a type error."""
        return code in self.permissions


async def load_user(
    session: AsyncSession, user_id: uuid.UUID, *, world_id: str | None
) -> User | None:
    """The statement every authenticated request pays for, and the only one a warm process runs.

    `User.role` is an inner-joined eager load, so this is a single SELECT across users and roles:
    `is_active`, the role's code and the role's id all arrive together. Nothing about it is
    cached. A user disabled a second ago must stop working on the very next request, which is the
    whole reason the token carries neither permissions nor an active flag.

    THE WORLD IS PART OF THE LOOKUP, NOT A CHECK AFTERWARDS.

    A token this service signed names a subject and, for a demo session, a world. Looking the
    subject up on its own would let a demo token point at any row in the table — another sandbox's
    operator, or a real one — and come back holding that row's grants.

    The world has no default because `None` is not "unspecified" here, it is a particular
    world: the operators of this installation. A caller who forgot the keyword would be given
    them, and a sandbox visitor would come back either missing or holding a real role.
    """
    result = await session.execute(
        select(User).where(User.id == user_id, User.world_id == world_id)
    )
    return result.scalars().one_or_none()


@dataclass(frozen=True, slots=True)
class _RolePermissions:
    """Every role's grants as of one instant."""

    by_role: Mapping[uuid.UUID, frozenset[str]]
    expires_at: datetime


# Process-wide, like the rate limiter's counters, and for the same reason: the unit runs one
# worker. Only the event loop touches it, so there is no lock — two coroutines that both miss
# simply both read the table, which is idempotent.
_cache: _RolePermissions | None = None

# Bumped by every invalidation, and the only thing that makes the read below safe to install.
# There is exactly one await between deciding to read the table and storing what came back, and
# an invalidation landing inside that window is invalidating rows the read may already have seen.
_generation: int = 0


async def load_role_permissions(
    session: AsyncSession, *, role_id: uuid.UUID, now: datetime
) -> frozenset[str]:
    """What one role grants, from the snapshot or from the database.

    `now` is the request's clock rather than the wall clock, so a test controls expiry by moving
    the clock instead of by sleeping thirty seconds.
    """
    global _cache

    cached = _cache
    if cached is not None and now < cached.expires_at:
        found = cached.by_role.get(role_id)
        if found is not None:
            return found

    # Read before the await, compared after it. Whoever invalidated while this statement was in
    # flight did so because the rows it was reading had just changed, so installing the result
    # would reinstate the answer they had just replaced — for a further thirty seconds, which is
    # long enough that the person watching concludes the edit did not take. The rows still answer
    # *this* request: they are no staler than the snapshot the request a microsecond earlier was
    # served from, and the next request re-reads.
    generation = _generation
    by_role = await _read_role_permissions(session)
    if generation == _generation:
        _cache = _RolePermissions(by_role=by_role, expires_at=now + PERMISSION_CACHE_TTL)

    # A role_id absent from a table just read whole belongs to a role deleted between the two
    # statements, which the RESTRICT on users.role_id does not allow. Granting nothing is the
    # answer anyway: the request is then refused by the permission check rather than by a 500.
    return by_role.get(role_id, frozenset())


def invalidate_permission_cache() -> None:
    """Forget the snapshot.

    Called by anything that changes what a role grants, and by a test that has just written one.
    `substate-admin sync-permissions` does not need it — it runs in its own process, and the
    served process holds the snapshot for at most thirty seconds after the deploy that ran it.

    Moving the generation is the half that matters when a read is already in flight: dropping the
    snapshot alone would be undone a moment later by that read installing the pre-change rows.
    """
    global _cache, _generation
    _cache = None
    _generation += 1


async def _read_role_permissions(session: AsyncSession) -> dict[uuid.UUID, frozenset[str]]:
    """Every role's grants, in one statement.

    Read outward from `roles` rather than from `role_permissions`, so that a role granting nothing
    still gets an entry. Without it, that role's users would miss the snapshot and re-read this
    table on every single request.
    """
    rows = await session.execute(
        select(Role.id, RolePermission.permission_code).outerjoin(
            RolePermission, RolePermission.role_id == Role.id
        )
    )
    grants: dict[uuid.UUID, set[str]] = {}
    for role_id, code in rows.tuples():
        codes = grants.setdefault(role_id, set())
        # NULL is the outer join reporting a role with no grants at all.
        if code is not None:
            codes.add(code)
    return {role_id: frozenset(codes) for role_id, codes in grants.items()}


async def _current_identity(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, params.Depends(dependency=optional_bearer)
    ],
    session: Annotated[AsyncSession, params.Depends(dependency=get_session)],
    now: Annotated[NowProvider, params.Depends(dependency=get_now)],
) -> Identity:
    """Resolve the bearer token into the user the database holds right now.

    Shared by `Authenticated()` and `RequirePermission()` and depended on by nothing else, so the
    order below is the order every guarded request is checked in: credential, signature, token
    type, world, subject, account, grants.

    The world comes before the subject on purpose: a demo token outliving its sandbox is the
    ordinary end of every demonstration.

    Asking for its operator first would answer "this user no longer exists" — a 401 that says
    nothing, logged as the rare case of an account deleted under a live session.
    """
    if credentials is None:
        raise ApiError(ErrorCode.NOT_AUTHENTICATED, headers=_BEARER_CHALLENGE)

    try:
        claims = decode_access_token(credentials.credentials, now=now)
    except AccessTokenExpired as exc:
        # The one code the frontend answers by refreshing. Everything else it answers by sending
        # the person back to the login form.
        raise ApiError(ErrorCode.TOKEN_EXPIRED, headers=_BEARER_CHALLENGE) from exc
    except AccessTokenInvalid as exc:
        raise ApiError(ErrorCode.NOT_AUTHENTICATED, headers=_BEARER_CHALLENGE) from exc

    # The signature verified, so the subject is an id this service minted a token for. Bound
    # before the checks below rather than after them, so that a refusal is attributable too.
    bind_request_context(user_id=claims.subject)

    world = _world_for(claims, now=now())
    _world.set(world)
    scope = str(claims.world_id) if claims.world_id is not None else None

    user = await load_user(session, claims.subject, world_id=scope)
    if user is None:
        # A signed token for a row that no longer exists. Worth a line: the only way to get one is
        # a user deleted while holding a live session.
        _log.warning("token_subject_missing")
        raise ApiError(ErrorCode.NOT_AUTHENTICATED, headers=_BEARER_CHALLENGE)

    if not user.is_active:
        # No challenge header: the credential was fine and presenting another one will not help.
        _log.warning("user_inactive")
        raise ApiError(ErrorCode.USER_INACTIVE)

    permissions = await load_role_permissions(session, role_id=user.role_id, now=now())
    return Identity(user=user, permissions=permissions, claims=claims, world=world)


def _world_for(claims: AccessTokenClaims, *, now: datetime) -> World | None:
    """Which world this token reads, and whether it still exists.

    An operator reads the base world, and a missing one is not a reason to refuse them: signing in
    and reading the audit work without a shop window, and `current_world` answers 503 to the routes
    that do need it.

    A demo token is the other way round. Its world IS the session — gone means the session is over,
    whether the hour ran out or the process restarted under it, and both endings are one answer.
    No bearer challenge: the credential was fine, and presenting another will not bring it back.
    """
    registry = get_registry()
    if claims.typ != "demo" or claims.world_id is None:
        return registry.get(BASE_WORLD_ID)

    world = registry.get(str(claims.world_id))
    if world is None or not world.alive_at(now):
        _log.info("sandbox_gone", world_id=str(claims.world_id))
        raise ApiError(ErrorCode.SANDBOX_GONE)

    # Used, so still wanted. In memory only: a write here would ride on whatever transaction the
    # request has and be rolled back by every refusal, and the row that outlives the process is
    # written where the token is re-minted.
    world.extend(ttl=SANDBOX_TTL, now=now)
    return world


class _Declared:
    """Base for the three declarations: the marker is an attribute of the object FastAPI calls.

    Not a registry keyed by the endpoint function. A registry can disagree with the router — an
    entry written for a function whose decorator later lost its dependency still reads "guarded" —
    while an attribute on the callable that is about to be awaited cannot: it is present exactly
    when the check runs, and absent exactly when nobody wired one up.
    """

    def __init__(self, declaration: RouteDeclaration) -> None:
        self.route_declaration = declaration


class _Public(_Declared):
    """Anyone may call this route."""

    def __init__(self) -> None:
        super().__init__(RouteDeclaration(Access.PUBLIC))

    async def __call__(self) -> None:
        """Check nothing. Saying so is the entire job."""
        return None


class _Authenticated(_Declared):
    """A valid access token, an existing user, and an account that is still active."""

    def __init__(self) -> None:
        super().__init__(RouteDeclaration(Access.AUTHENTICATED))

    async def __call__(
        self, identity: Annotated[Identity, params.Depends(dependency=_current_identity)]
    ) -> Identity:
        return identity


class _RequirePermission(_Declared):
    """Everything `Authenticated` requires, and one permission the role must grant."""

    def __init__(self, code: PermissionCode) -> None:
        super().__init__(RouteDeclaration(Access.PERMISSION, code))
        self.code = code

    async def __call__(
        self, identity: Annotated[Identity, params.Depends(dependency=_current_identity)]
    ) -> Identity:
        if not identity.has(self.code):
            _log.warning("permission_denied", permission=self.code, role=identity.role.code)
            raise ApiError(ErrorCode.PERMISSION_DENIED)
        return identity


# The three below are capitalised because they are dependency factories used exactly where
# FastAPI's own `Depends`, `Query` and `Security` are used, and a route reads better declaring
# `Public()` than `public()`. They return `params.Depends(...)` directly rather than through the
# `Depends(...)` helper, which is annotated as returning Any: a factory here promises the
# marker-carrying object it actually returns, and that promise is what `undeclared_routes` rests
# on.


def Public() -> params.Depends:
    """Declare a route open to anyone: `@router.get(..., dependencies=[Public()])`."""
    return params.Depends(dependency=_Public())


def Authenticated() -> params.Depends:
    """Declare a route that needs a session: `identity: Annotated[Identity, Authenticated()]`."""
    return params.Depends(dependency=_Authenticated())


def RequirePermission(code: PermissionCode) -> params.Depends:
    """Declare a route that needs one permission.

    `code` is a `PermissionCode`, so `RequirePermission("user.read")` is caught by mypy in CI
    rather than by a 403 nobody sees until a reviewer opens the wrong tab.
    """
    return params.Depends(dependency=_RequirePermission(code))


def route_declarations(route: BaseRoute) -> tuple[RouteDeclaration, ...]:
    """Every declaration reachable from one route, in resolution order.

    Dependencies of dependencies are walked too, so a declaration cannot be buried inside a helper
    and thereby hidden from this. The route's own endpoint is never asked: declarations live on
    dependencies, and an attribute on an endpoint function would be a claim with nothing enforcing
    it.
    """
    if not isinstance(route, APIRoute):
        return ()
    return tuple(
        declaration
        for dependant in _walk(route.dependant)
        if (declaration := _declaration_of(dependant.call)) is not None
    )


def route_declaration(route: BaseRoute) -> RouteDeclaration | None:
    """A route's single declaration, or None when it carries none — or more than one."""
    declarations = route_declarations(route)
    return declarations[0] if len(declarations) == 1 else None


def undeclared_routes(routes: Iterable[BaseRoute]) -> tuple[BaseRoute, ...]:
    """Everything routable that does not carry exactly one declaration. A test asserts it is empty.

    Zero and two are both failures. Zero is a route nobody decided about — which, without this
    check, is a route that answers whoever asks. Two is a route whose answer depends on which
    dependency happened to run first.

    Every kind of route is asked, not only APIRoutes, and that is the whole point of the guard. A
    `Mount` is one entry in the list with a tree of paths and a second application behind it; a
    `WebSocketRoute` never passes through the dependency machinery at all; a hand-written
    Starlette route has nowhere to put a declaration. None of them can be guarded by anything in
    this module, so none of them may appear at all — a guard that skipped what it cannot express
    would go green on exactly the routes nobody had decided about. The single exemption is
    `DOCUMENTATION_PATHS`, and a test asserts that set is the one FastAPI actually mounted.

    Pass `app.routes` rather than a filtered list: since FastAPI 0.141 that sequence holds one
    lazy node per included router instead of the routes themselves, so the descent below is what
    turns it into what is served. Descending here rather than in the caller is deliberate — a
    caller that flattened first would be free to drop the very kinds of route this looks for.
    """
    return tuple(route for route in _routable(routes) if not _is_declared(route))


def _is_declared(route: BaseRoute) -> bool:
    """Whether one route has said, exactly once, who may call it."""
    if isinstance(route, APIRoute):
        return len(route_declarations(route)) == 1
    # Nothing else can carry a declaration, so for anything else the question is not what it
    # declared but whether it is allowed to be here at all.
    return isinstance(route, Route) and route.path in DOCUMENTATION_PATHS


def _routable(routes: Iterable[BaseRoute]) -> Iterator[BaseRoute]:
    """Every route that answers a request, with included routers descended into.

    Found by the attribute naming the router that was included rather than by importing a private
    class, which also means the older shape — routes already flat — walks straight through.
    """
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is None:
            yield route
        else:
            yield from _routable(included.routes)


def _declaration_of(call: object | None) -> RouteDeclaration | None:
    """The declaration a dependency carries, if it is one of ours.

    The type is checked, not just the attribute name: something else that happens to own an
    attribute called `route_declaration` has not declared anything.
    """
    found = getattr(call, DECLARATION_ATTR, None)
    return found if isinstance(found, RouteDeclaration) else None


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    """Every dependency below one dependant, at any depth."""
    for sub in dependant.dependencies:
        yield sub
        yield from _walk(sub)
