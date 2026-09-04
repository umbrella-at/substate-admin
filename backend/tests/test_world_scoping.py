"""Rows that belong to a world, and the two uniqueness rules that replaced one.

A sandbox gets its own operators and its own copies of the system roles, so that the screen which
edits them is a real screen inside the demonstration rather than a read-only one. That is the
whole reason `world_id` is nullable on both tables.

The rule it replaces was `UNIQUE (email)`. The rule it must NOT become is `UNIQUE (world_id,
email)`: Postgres counts NULLs as distinct, so that one would let this installation hold two
operators on one address — and `one_or_none()` on the login path turns the second one into a 500.
"""

import uuid
from collections.abc import Iterator
from typing import get_args

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import api_routes, app
from app.models import Role, User


async def _role(session: AsyncSession, *, code: str, world_id: str | None = None) -> Role:
    role = Role(code=code, name=code.title(), world_id=world_id)
    session.add(role)
    await session.flush()
    return role


async def _operator(
    session: AsyncSession, *, email: str, role: Role, world_id: str | None = None
) -> User:
    user = User(email=email, password_hash="x", role_id=role.id, world_id=world_id)
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def role(session: AsyncSession) -> Role:
    """One real role, for the users below to point at."""
    return await _role(session, code=f"custom-{uuid.uuid4().hex[:8]}")


async def test_two_operators_of_this_installation_cannot_share_an_address(
    session: AsyncSession, role: Role
) -> None:
    """The rule the whole shape exists to keep. A composite key over a nullable column would
    accept both of these, and the second one would surface as a 500 at the login form."""
    address = f"{uuid.uuid4().hex[:8]}@example.com"
    await _operator(session, email=address, role=role)

    with pytest.raises(IntegrityError):
        await _operator(session, email=address, role=role)


async def test_two_sandboxes_may_each_have_an_operator_at_the_same_address(
    session: AsyncSession, role: Role
) -> None:
    """Sandboxes are seeded from one deterministic script, so every one of them invents the same
    people. Without this they would collide on the second visitor."""
    address = f"{uuid.uuid4().hex[:8]}@example.com"
    await _operator(session, email=address, role=role, world_id="world-one")
    await _operator(session, email=address, role=role, world_id="world-two")

    found = (
        (await session.execute(select(User.world_id).where(User.email == address))).scalars().all()
    )
    assert sorted(found) == ["world-one", "world-two"]


async def test_one_sandbox_cannot_have_the_same_address_twice(
    session: AsyncSession, role: Role
) -> None:
    address = f"{uuid.uuid4().hex[:8]}@example.com"
    await _operator(session, email=address, role=role, world_id="world-one")

    with pytest.raises(IntegrityError):
        await _operator(session, email=address, role=role, world_id="world-one")


async def test_a_sandbox_may_reuse_a_real_operators_address(
    session: AsyncSession, role: Role
) -> None:
    """The two rules are separate, and this is what separate means: a sandbox inventing an
    operator does not have to know which addresses this installation has already spent."""
    address = f"{uuid.uuid4().hex[:8]}@example.com"
    await _operator(session, email=address, role=role)
    await _operator(session, email=address, role=role, world_id="world-one")


async def test_the_same_pair_of_rules_holds_for_role_codes(session: AsyncSession) -> None:
    """A sandbox copies `admin`, `support`, `viewer` and `demo` under their own codes, which is
    the point: the visitor edits roles that look like the real ones and breaks nothing."""
    code = f"custom-{uuid.uuid4().hex[:8]}"
    await _role(session, code=code)
    await _role(session, code=code, world_id="world-one")
    await _role(session, code=code, world_id="world-two")

    with pytest.raises(IntegrityError):
        await _role(session, code=code)


async def test_one_sandbox_cannot_hold_a_role_code_twice(session: AsyncSession) -> None:
    code = f"custom-{uuid.uuid4().hex[:8]}"
    await _role(session, code=code, world_id="world-one")

    with pytest.raises(IntegrityError):
        await _role(session, code=code, world_id="world-one")


def _model_names(annotation: object) -> set[str]:
    """Every name a pydantic model accepts, its aliases included, at any depth.

    Through containers as well as through bare classes. A filter object arrives as `Inner | None`
    or `list[Inner]` far more often than as `Inner`, and a recursion that opened only the bare
    class stopped at exactly the shape the guard below exists to catch.
    """
    found: set[str] = set()
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        for name, field in annotation.model_fields.items():
            found.add(name)
            if field.alias is not None:
                found.add(field.alias)
            found |= _model_names(field.annotation)
        return found
    for inside in get_args(annotation):
        found |= _model_names(inside)
    return found


def test_a_world_named_inside_a_list_or_an_optional_is_still_found() -> None:
    """The guard's own reach, asserted — because the guard is the only thing watching.

    `isinstance(list[Inner], type)` is False, and so is `isinstance(Inner | None, type)`. A
    recursion gated on that alone reports green for the one shape a nested filter actually takes.
    """

    class Inner(BaseModel):
        world_id: str | None = None

    class Wrapped(BaseModel):
        one: Inner | None = None
        many: list[Inner] = []

    assert "world_id" in _model_names(Wrapped)


def _accepted(route: APIRoute) -> set[str]:
    """Every name this route will read a value out of: path, query, header, cookie or body."""
    names = set(route.param_convertors)
    for dependant in _walk(route.dependant):
        for field in (
            *dependant.query_params,
            *dependant.path_params,
            *dependant.header_params,
            *dependant.cookie_params,
            *dependant.body_params,
        ):
            names |= {field.name, field.alias} | _model_names(field.field_info.annotation)
    return names


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk(sub)


@pytest.mark.parametrize(
    "route",
    api_routes(app),
    ids=[f"{sorted(r.methods or [])[0]} {r.path}" for r in api_routes(app)],
)
def test_no_endpoint_lets_the_caller_name_a_world(route: APIRoute) -> None:
    """THE ISOLATION, AS A PROPERTY OF THE ROUTER RATHER THAN AS A GREP DONE ONCE.

    A demo session's world is a claim inside a signed token, and a request that could name one
    would be a request that could name somebody else's.

    Today no model has such a field, which is exactly why this is worth asserting: the day somebody
    adds `worldId` to a filter object for a good local reason, nothing else in the suite notices.

    Sub-dependencies are walked too, and pydantic models are opened to any depth, because a field
    buried in a nested query model is read from the request just as surely as a top-level one.
    """
    named = {name for name in _accepted(route) if "world" in name.lower()}
    assert named == set(), f"{route.path} reads {sorted(named)} from the request"
