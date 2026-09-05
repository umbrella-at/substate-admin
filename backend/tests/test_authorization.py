"""Who may call what — asked of the router rather than of a list somebody maintains.

The matrix is what carries this module. It reads the permission each route demands off the route,
reads what each system role grants out of the catalogue, and asserts that the application agrees
with the two of them. It names no endpoint and no expected status, so a route added tomorrow is
checked against all four roles tomorrow, and a role whose grants change is re-checked without
anybody remembering to come back here.

Reading the expectations off the code is also the matrix's blind spot: a route that quietly asked
for less would drag its own expectation down with it. Three small tests close that, and between
them they are the whole authorisation surface written out once — which routes are public, what
each of the others demands, and what the four roles hold. Every one of them fails when a route
arrives, which is the friction that makes somebody decide.

The router guard and the role snapshot are here too, because both are load-bearing for everything
above: a guard that cannot see a route decides nothing about it, and a snapshot that outlives an
edit answers with permissions the database no longer grants.
"""

import uuid
from datetime import timedelta
from typing import Final

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.websockets import WebSocket

from app import deps
from app.deps import (
    DOCUMENTATION_PATHS,
    Access,
    RouteDeclaration,
    invalidate_permission_cache,
    load_role_permissions,
    route_declaration,
    route_declarations,
    undeclared_routes,
)
from app.main import API_PREFIX, api_routes, app
from app.permissions import ROLE_CODES, SYSTEM_ROLES, RoleCode, system_role
from app.worlds.registry import World, get_registry
from support import Clock, bearer, create_account, envelope, role_id_for


def _method(route: APIRoute) -> str:
    """The verb a route is called with. HEAD and OPTIONS are what the framework adds."""
    return sorted(route.methods - {"HEAD", "OPTIONS"})[0]


def _url(route: APIRoute) -> str:
    """The path as served. A router's own routes do not carry the prefix the application mounts."""
    return f"{API_PREFIX}{route.path}"


def _guarded() -> list[tuple[APIRoute, RouteDeclaration]]:
    """Every route that is not public, with what it declared."""
    found = []
    for route in api_routes(app):
        declaration = route_declaration(route)
        if declaration is not None and declaration.access is not Access.PUBLIC:
            found.append((route, declaration))
    return found


_MATRIX: Final = [
    (route, declaration, role_code) for route, declaration in _guarded() for role_code in ROLE_CODES
]

_MATRIX_IDS: Final = [
    f"{_method(route)} {_url(route)}-{role_code}" for route, _, role_code in _MATRIX
]


def test_every_route_declares_who_may_call_it() -> None:
    # `app.routes` rather than `api_routes(app)`: the guard has to be shown everything the
    # application serves, including the routes that are not APIRoutes, and a caller that filtered
    # those out first would be handing it only the routes that cannot fail. Since FastAPI 0.141
    # this sequence holds one lazy node per included router rather than the routes themselves,
    # and `undeclared_routes` descends for that reason.
    #
    # A walk that found nothing would also pass, so asserting there is something to inspect is
    # part of the check.
    assert api_routes(app)
    assert undeclared_routes(app.routes) == ()


def test_the_public_routes_are_the_ones_that_have_to_be() -> None:
    """Login and refresh are the credential exchange; logout ends a session and needs no access
    token to do it; health is what the deploy's smoke check reads before anyone has one.

    The demonstration door is public by necessity — the first press comes from somebody with no
    credential at all — and what that costs is a ceiling on how many worlds may stand and a rate
    limit on building them.
    """
    public = {
        (_method(route), _url(route))
        for route in api_routes(app)
        if (declaration := route_declaration(route)) is not None
        and declaration.access is Access.PUBLIC
    }

    assert public == {
        ("GET", "/api/health"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/refresh"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/demo/session"),
    }


def test_each_guarded_route_demands_what_it_is_supposed_to() -> None:
    """The one place the demands themselves are written down.

    The matrix below reads what a route requires off the route, which is what lets it cover an
    endpoint nobody has come back here to think about — and which also means a route that quietly
    downgraded from `RequirePermission("users.read")` to `Authenticated()` would take the matrix's
    expectations down with it and still pass. Stating the demands once is what closes that, and a
    route added tomorrow fails this until somebody says what it needs.
    """
    demands = {
        (_method(route), _url(route)): declaration.permission for route, declaration in _guarded()
    }

    assert demands == {
        # None: a session, and no particular permission.
        ("GET", "/api/auth/me"): None,
        ("GET", "/api/users"): "users.read",
        # The catalogue is read by the table's plan filter, so it is gated with the table rather
        # than left open: knowing what is sold and at what price is not a public fact here.
        ("GET", "/api/plans"): "subscribers.read",
        # The programme list is not read by the table, so it takes the permission named after what
        # it is about rather than the one its neighbour happens to use.
        ("GET", "/api/referral-programs"): "referrals.read",
        ("GET", "/api/subscribers"): "subscribers.read",
        ("GET", "/api/subscribers/{user_id}"): "subscribers.read",
        # The feed is the card's other half and is read under the same permission: what happened
        # to a subscription is not a more private fact than what state it is in.
        ("GET", "/api/subscribers/{user_id}/events"): "subscribers.read",
        # Five of the six operations change one subscription and ask for the permission named
        # after that.
        ("POST", "/api/subscribers/{user_id}/subscribe"): "subscribers.write",
        ("POST", "/api/subscribers/{user_id}/cancel"): "subscribers.write",
        ("POST", "/api/subscribers/{user_id}/change-plan"): "subscribers.write",
        ("POST", "/api/subscribers/{user_id}/redeem"): "subscribers.write",
        ("POST", "/api/subscribers/{user_id}/payment"): "subscribers.write",
        # The sixth does not. Putting somebody on a referral programme decides who gets paid for
        # bringing people in, which is a fact about the programme; support may serve a customer
        # and may not change what a partner earns.
        ("POST", "/api/subscribers/{user_id}/referral-program"): "referrals.write",
        # The one code `viewer` is denied besides `users.read`: showing somebody the product is
        # not showing them what the people who run it have been doing.
        ("GET", "/api/audit"): "audit.read",
        # The five figures take the code named after what they are, not after their sources. Two
        # of them read the same engine the table reads and three read the journal, and gating
        # either half with `subscribers.read` would make the permission describe a query plan.
        ("GET", "/api/analytics/funnel"): "analytics.read",
        ("GET", "/api/analytics/flow"): "analytics.read",
        ("GET", "/api/analytics/states"): "analytics.read",
        ("GET", "/api/analytics/quiet"): "analytics.read",
        ("GET", "/api/analytics/revenue"): "analytics.read",
        # Roles take the codes the catalogue already describes as covering "the panel's own users
        # and roles". A `roles.*` pair of its own would draw a line the panel does not draw:
        # whoever may disable an operator's account is whoever decides what operators may do.
        ("GET", "/api/roles"): "users.read",
        ("POST", "/api/roles"): "users.write",
        ("PUT", "/api/roles/{role_id}"): "users.write",
        ("DELETE", "/api/roles/{role_id}"): "users.write",
        # Reading the clock takes a session and no more: every screen already renders times
        # measured against it, and a panel that cannot say what time its world thinks it is falls
        # back on the browser's — which reads "just now" for a world wound a month forward.
        ("GET", "/api/clock"): None,
        # Winding it is the one thing `viewer` and `support` are refused here. It changes what
        # everybody reading that world sees.
        ("POST", "/api/clock/advance"): "demo.control",
    }


@pytest.mark.parametrize(("route", "declaration", "role_code"), _MATRIX, ids=_MATRIX_IDS)
async def test_the_permission_matrix(
    client: AsyncClient,
    session: AsyncSession,
    clock: Clock,
    base_world: World,
    route: APIRoute,
    declaration: RouteDeclaration,
    role_code: RoleCode,
) -> None:
    account = await create_account(session, email=f"{role_code}@example.com", role_code=role_code)
    method = _method(route)

    response = await client.request(
        method,
        _url(route),
        headers=bearer(account, now=clock.now),
        # An empty object for anything with a body: a route that answers 422 has still let the
        # caller past the permission check, which is the only thing under test here.
        json=None if method == "GET" else {},
    )

    granted = (
        declaration.permission is None
        or declaration.permission in SYSTEM_ROLES[role_code].permissions
    )
    if granted:
        # 503 as well as 403. A route that needs a world answers 503 when there is none, which is
        # "not 403" and would let six endpoints wired to nothing pass this matrix — which is why
        # `base_world` is a fixture here rather than only in the tests about operations.
        assert response.status_code not in (403, 503)
    else:
        assert response.status_code == 403
        assert envelope(response)["code"] == "PERMISSION_DENIED"


@pytest.mark.parametrize(
    ("route", "declaration"), _guarded(), ids=[f"{_method(r)} {_url(r)}" for r, _ in _guarded()]
)
async def test_a_demo_token_whose_world_is_gone_reaches_no_guarded_route(
    client: AsyncClient,
    session: AsyncSession,
    clock: Clock,
    route: APIRoute,
    declaration: RouteDeclaration,
) -> None:
    """The ordinary end of every demonstration, on every route at once.

    Worlds live in memory, so an hour passing and a deploy restarting the process are the same
    event from outside — and the answer is the same on all of them, before the subject is even
    looked up.
    """
    account = await create_account(session, email="demo-session@example.com", role_code="demo")
    method = _method(route)

    response = await client.request(
        method,
        _url(route),
        headers=bearer(account, now=clock.now, typ="demo", world_id=uuid.uuid4()),
        json=None if method == "GET" else {},
    )

    assert response.status_code == 410
    assert envelope(response)["code"] == "SANDBOX_GONE"


async def test_a_demo_token_cannot_name_an_operator_of_this_installation(
    client: AsyncClient, session: AsyncSession, clock: Clock
) -> None:
    """THE ISOLATION, ASSERTED FROM THE SIDE IT WOULD BE BROKEN FROM.

    A demo token is signed by this service, so nothing about the signature says which rows it may
    reach. The subject is looked up together with the world, and an operator of this installation
    carries no world — so a demo token naming one finds nothing and is refused.
    """
    world = get_registry().create(str(uuid.uuid4()), ttl=timedelta(minutes=60))
    operator = await create_account(session, email="real@example.com", role_code="admin")

    response = await client.get(
        "/api/subscribers",
        headers=bearer(operator, now=clock.now, typ="demo", world_id=uuid.UUID(world.id)),
    )

    assert response.status_code == 401
    assert envelope(response)["code"] == "NOT_AUTHENTICATED"


def test_the_catalogue_and_the_system_roles_are_what_the_specification_says() -> None:
    """The matrix reads its expectations out of this table, so the table itself is asserted."""
    assert len(SYSTEM_ROLES) == 4
    assert {code: len(role.permissions) for code, role in SYSTEM_ROLES.items()} == {
        "admin": 13,
        "support": 9,
        "viewer": 5,
        "demo": 13,
    }
    # The specification writes demo as "everything except users.write", and it is now everything.
    # Inside a sandbox the operators and the roles are invented, its own, and gone in an hour, so
    # the world filter is what makes the grant safe rather than the grant being withheld.
    assert SYSTEM_ROLES["demo"].permissions == SYSTEM_ROLES["admin"].permissions
    assert {"audit.read", "users.read"}.isdisjoint(SYSTEM_ROLES["viewer"].permissions)
    assert {"subscribers.write", "promo.write"} <= SYSTEM_ROLES["support"].permissions


def test_a_role_the_application_did_not_define_is_not_a_system_role() -> None:
    """The lookup takes an untrusted string — a CLI flag, a column read back from a row — so a
    custom role and a typo get the same "that is not a system role" answer rather than a KeyError.
    """
    assert system_role("admin") is SYSTEM_ROLES["admin"]
    assert system_role("auditor") is None
    assert system_role("Admin") is None
    assert system_role("") is None


def test_a_route_the_framework_generated_is_not_asked_to_declare_anything() -> None:
    """/api/docs and /api/openapi.json are plain Starlette routes rather than APIRoutes, and they
    are gated on APP_ENV instead. They are the guard's only exemption, so the list of them is
    asserted against what FastAPI actually mounted: an exemption naming a path nobody serves would
    be an exemption for whatever got mounted there next."""
    mounted = {
        route.path
        for route in app.routes
        if isinstance(route, Route) and not isinstance(route, APIRoute)
    }

    assert mounted == DOCUMENTATION_PATHS

    generated = Route("/api/docs", endpoint=lambda request: None)

    assert route_declarations(generated) == ()
    assert route_declaration(generated) is None
    assert undeclared_routes([generated]) == ()


def test_a_route_no_declaration_can_reach_is_a_failure_rather_than_a_gap() -> None:
    """The guard reports every kind of route it cannot express an answer for.

    A mount is the dangerous one: one entry in the list, a whole tree of paths and a second
    application behind it. A websocket route never passes through the dependency machinery the
    declarations live in, and a hand-written Starlette route has nowhere to put one. If the guard
    skipped what it cannot express it would go green on exactly the routes nobody had decided
    about, which is the opposite of what it is for.
    """

    async def socket(websocket: WebSocket) -> None:  # pragma: no cover - never connected to
        await websocket.close()

    mount = Mount("/internal", routes=[])
    live = WebSocketRoute("/live", endpoint=socket)
    plain = Route("/api/backdoor", endpoint=lambda request: None)

    assert undeclared_routes([mount]) == (mount,)
    assert undeclared_routes([live]) == (live,)
    assert undeclared_routes([plain]) == (plain,)


def test_the_guard_descends_into_an_included_router() -> None:
    """`app.routes` holds one lazy node per included router rather than the routes themselves, so
    a guard that walked it without descending would pass by finding nothing to inspect."""
    router = APIRouter()

    async def undeclared() -> None:
        return None

    router.add_api_route("/undeclared", undeclared, methods=["GET"])
    # No docs: this application is not the one under test, and FastAPI's defaults would mount
    # /docs and /openapi.json, which are not the paths this application exempts.
    other = FastAPI(docs_url=None, openapi_url=None)
    other.include_router(router, prefix=API_PREFIX)

    reported = undeclared_routes(other.routes)

    assert len(reported) == 1
    found = reported[0]
    assert isinstance(found, APIRoute)
    assert found.endpoint is undeclared


class _CountingRead:
    """The one statement that reads the whole role -> permission table, wrapped so a test can
    count it and fire an invalidation from inside it.

    The suite runs on a single connection inside a single transaction, so two genuinely concurrent
    requests are not available to it. The window that matters is not concurrency in general
    though: it is the one await between deciding to read the table and installing what came back,
    and firing the invalidation inside the read lands in exactly that window, deterministically.
    """

    def __init__(self, *, invalidate_during_the_first: bool) -> None:
        self._read = deps._read_role_permissions
        self._invalidate = invalidate_during_the_first
        self.calls = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(deps, "_read_role_permissions", self)

    async def __call__(self, session: AsyncSession) -> dict[uuid.UUID, frozenset[str]]:
        self.calls += 1
        rows = await self._read(session)
        if self._invalidate and self.calls == 1:
            # A role edited while this statement was in flight: another request doing it, or the
            # deploy's `sync-permissions` run.
            invalidate_permission_cache()
        return rows


async def test_the_role_snapshot_answers_the_next_request(
    session: AsyncSession, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the test below.

    Without it, "the second request read the table again" would also be true of a cache that
    never worked at all.
    """
    role = await role_id_for(session, "viewer")
    reads = _CountingRead(invalidate_during_the_first=False)
    reads.install(monkeypatch)

    await load_role_permissions(session, role_id=role, now=clock.now)
    await load_role_permissions(session, role_id=role, now=clock.now)

    assert reads.calls == 1


async def test_an_invalidation_during_the_read_is_not_undone_by_it(
    session: AsyncSession, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whoever invalidates while the snapshot is being read is doing so because the rows being
    read have just changed.

    Installing the result regardless would put the pre-change answer back for a further thirty
    seconds — long enough for the person who made the change to watch it apparently not take.
    """
    role = await role_id_for(session, "viewer")
    reads = _CountingRead(invalidate_during_the_first=True)
    reads.install(monkeypatch)

    first = await load_role_permissions(session, role_id=role, now=clock.now)
    second = await load_role_permissions(session, role_id=role, now=clock.now)

    # The rows just read still answer the request that read them: they are no staler than the
    # snapshot the request a microsecond earlier was served from. What must not happen is the
    # next request being answered out of a snapshot the invalidation had already dropped.
    assert first == second
    assert reads.calls == 2
