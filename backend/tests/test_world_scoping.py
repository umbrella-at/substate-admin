"""Rows that belong to a world, and the two uniqueness rules that replaced one.

A sandbox gets its own operators and its own copies of the system roles, so that the screen which
edits them is a real screen inside the demonstration rather than a read-only one. That is the
whole reason `world_id` is nullable on both tables.

The rule it replaces was `UNIQUE (email)`. The rule it must NOT become is `UNIQUE (world_id,
email)`: Postgres counts NULLs as distinct, so that one would let this installation hold two
operators on one address — and `one_or_none()` on the login path turns the second one into a 500.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
