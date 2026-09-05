"""The operators a sandbox invents for itself, and its own copies of the roles.

WHY THE COPIES EXIST AT ALL.

The permission editor is one of the things this panel is built to demonstrate, and most people
who will ever see it arrive by pressing a button on the login page rather than with credentials.

Shown the real roles, they would be shown them read-only: a visitor who takes `users.write` off
`admin` takes it off everybody until the next restart.

So a sandbox gets four roles of its own, carrying the same codes and the same grants, and they are
NOT system roles: they can be renamed, re-granted and deleted, and they die with the world in an
hour. The demonstration of the editor is then the editor, not a picture of it.

A visitor who strips `users.write` off the role they are signed in as loses the screen for the
rest of the session. That is the failure the rule on the real roles exists to prevent.

Here it is contained, recoverable by starting another demonstration, and the most memorable thing
the screen can teach.
"""

from __future__ import annotations

import random
import uuid
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role, RolePermission, User, normalize_email
from app.permissions import SYSTEM_ROLES
from app.seed.run import display_name

VISITOR: Final = "you@example.com"
"""The address the visitor's own account carries, so that the users screen names them among the
people they are looking at rather than hiding whoever is signed in."""

INVENTED: Final = 7
"""How many operators a sandbox makes up, on top of the visitor.

Enough that the role column shows more than one value and the list is worth ordering; few enough
that the screen is the panel's users screen rather than a stress test of its pager.
"""

# Round-robined over the invented operators, so every role has somebody holding it and the editor's
# "in use" refusal is reachable without the visitor having to build a user first.
_SPREAD: Final = ("admin", "support", "viewer", "demo")

_NO_SIGN_IN: Final = "!"
"""Not a hash, and not a string argon2 could ever produce.

Nobody signs in as an invented operator: the login statement asks for `world_id IS NULL` and a
demo session arrives holding a token instead. A real hash would mean spending argon2 eight times
on every sandbox, on credentials that exist to be looked at.
"""


async def populate(session: AsyncSession, *, world_id: str, seed: int) -> uuid.UUID:
    """Give one sandbox its roles and its operators. Returns the visitor's own account.

    Deterministic from `seed`, like everything else a sandbox is built from: two visitors on the
    same afternoon see the same invented colleagues, and a screenshot taken today is a screenshot
    somebody can reproduce.
    """
    stream = random.Random(seed)
    roles = {code: _copy_of(code, world_id) for code in SYSTEM_ROLES}
    for role in roles.values():
        session.add(role)
    await session.flush()

    for role in roles.values():
        for code in sorted(SYSTEM_ROLES[role.code].permissions):  # type: ignore[index]
            session.add(RolePermission(role_id=role.id, permission_code=code))

    taken: set[str] = set()
    for index in range(INVENTED):
        session.add(
            User(
                email=_address(stream, taken),
                password_hash=_NO_SIGN_IN,
                role_id=roles[_SPREAD[index % len(_SPREAD)]].id,
                world_id=world_id,
            )
        )

    visitor = User(
        email=VISITOR,
        password_hash=_NO_SIGN_IN,
        role_id=roles["demo"].id,
        world_id=world_id,
    )
    session.add(visitor)
    await session.flush()
    return visitor.id


def _copy_of(code: str, world_id: str) -> Role:
    """One system role, as a sandbox's own editable copy of it."""
    spec = SYSTEM_ROLES[code]  # type: ignore[index]
    return Role(code=spec.code, name=spec.name, is_system=False, world_id=world_id)


def _address(stream: random.Random, taken: set[str]) -> str:
    """An invented colleague's address, drawn until it is one this world has not used.

    The name generator has 26 by 22 pairs in it, so a collision inside eight draws is unlikely and
    not impossible — and a collision is an IntegrityError against the world-scoped unique index,
    which would be a sandbox that refuses to open for one visitor in a few hundred.
    """
    while True:
        first, last = display_name(stream).split(" ")
        address = normalize_email(f"{first}.{last}@example.com")
        if address not in taken and address != VISITOR:
            taken.add(address)
            return address
