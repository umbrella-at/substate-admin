"""The role editor, and the two refusals that are not merely hidden buttons.

A SYSTEM ROLE IS REFUSED BY THE APPLICATION. `sync-permissions` restores it on every deploy, so
an accepted edit would be undone at the next push and would look, until then, like a change that
took. Not drawing the control is the other half of the rule, and the browser test asserts it.

The cache is the other thing worth a test of its own. A role's grants are held for thirty seconds,
so an editor that did not drop the snapshot would appear to work and take half a minute to do
anything — which is indistinguishable, at the keyboard, from not working.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Role
from app.permissions import PERMISSION_CODES, ROLE_CODES
from support import Account, Clock, bearer, create_account, envelope

ROLES: Final = "/api/roles"
USERS: Final = "/api/users"


@pytest.fixture
async def admin(session: AsyncSession, clock: Clock) -> tuple[Account, dict[str, str]]:
    account = await create_account(session, email="owner@example.com", role_code="admin")
    return account, bearer(account, now=clock.now)


async def _create(client: AsyncClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    payload = {"code": "analysts", "name": "Analysts", "permissions": [], **body}
    response = await client.post(ROLES, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def test_the_list_carries_the_roles_and_the_catalogue_they_grant_from(
    client: AsyncClient, admin: tuple[Account, dict[str, str]]
) -> None:
    """One request draws one screen, so the editor cannot offer a permission that does not exist."""
    _, headers = admin
    response = await client.get(ROLES, headers=headers)
    assert response.status_code == 200

    body = response.json()
    assert {role["code"] for role in body["items"]} >= set(ROLE_CODES)
    assert [permission["code"] for permission in body["permissions"]] == list(PERMISSION_CODES)
    assert all(permission["description"] for permission in body["permissions"])


async def test_a_system_role_says_how_many_people_hold_it(
    client: AsyncClient, admin: tuple[Account, dict[str, str]]
) -> None:
    """The screen says why a role cannot be deleted before anybody presses the button."""
    _, headers = admin
    body = (await client.get(ROLES, headers=headers)).json()
    administrators = next(role for role in body["items"] if role["code"] == "admin")

    assert administrators["isSystem"] is True
    assert administrators["holders"] >= 1
    assert set(administrators["permissions"]) == set(PERMISSION_CODES)


async def test_a_role_of_your_own_can_be_made_edited_and_removed(
    client: AsyncClient, admin: tuple[Account, dict[str, str]]
) -> None:
    _, headers = admin
    created = await _create(client, headers, permissions=["analytics.read"])
    assert created["isSystem"] is False
    assert created["permissions"] == ["analytics.read"]
    assert created["holders"] == 0

    replaced = await client.put(
        f"{ROLES}/{created['id']}",
        headers=headers,
        json={"name": "Analysts and auditors", "permissions": ["analytics.read", "audit.read"]},
    )
    assert replaced.status_code == 200
    assert replaced.json()["name"] == "Analysts and auditors"
    assert replaced.json()["permissions"] == ["analytics.read", "audit.read"]

    removed = await client.delete(f"{ROLES}/{created['id']}", headers=headers)
    assert removed.status_code == 204
    assert created["code"] not in {
        role["code"] for role in (await client.get(ROLES, headers=headers)).json()["items"]
    }


@pytest.mark.parametrize("code", ROLE_CODES)
async def test_a_system_role_refuses_the_direct_call_and_not_only_the_button(
    client: AsyncClient, session: AsyncSession, admin: tuple[Account, dict[str, str]], code: str
) -> None:
    """All four, because the rule is about `is_system` rather than about any one of them."""
    _, headers = admin
    role_id = (await session.execute(select(Role.id).where(Role.code == code))).scalar_one()

    replaced = await client.put(
        f"{ROLES}/{role_id}", headers=headers, json={"name": "Mine now", "permissions": []}
    )
    removed = await client.delete(f"{ROLES}/{role_id}", headers=headers)

    assert replaced.status_code == 409
    assert envelope(replaced)["code"] == "ROLE_IS_SYSTEM"
    assert removed.status_code == 409
    assert envelope(removed)["code"] == "ROLE_IS_SYSTEM"


async def test_a_refused_edit_leaves_the_role_exactly_as_it_was(
    client: AsyncClient, session: AsyncSession, admin: tuple[Account, dict[str, str]]
) -> None:
    """The refusal is not a message over a change that happened anyway."""
    _, headers = admin
    before = next(
        role
        for role in (await client.get(ROLES, headers=headers)).json()["items"]
        if role["code"] == "viewer"
    )

    await client.put(
        f"{ROLES}/{before['id']}", headers=headers, json={"name": "Nothing", "permissions": []}
    )

    after = next(
        role
        for role in (await client.get(ROLES, headers=headers)).json()["items"]
        if role["code"] == "viewer"
    )
    assert after == before


async def test_a_role_somebody_holds_is_not_deleted_out_from_under_them(
    client: AsyncClient, session: AsyncSession, admin: tuple[Account, dict[str, str]]
) -> None:
    """Refused here rather than left to the foreign key, which arrives with nothing to say."""
    _, headers = admin
    created = await _create(client, headers, code="temporary", name="Temporary")
    await create_account(session, email="holder@example.com", role_code="temporary")

    response = await client.delete(f"{ROLES}/{created['id']}", headers=headers)
    assert response.status_code == 409
    assert envelope(response)["code"] == "ROLE_IN_USE"


async def test_a_code_that_is_taken_is_named_as_the_field_that_was_wrong(
    client: AsyncClient, admin: tuple[Account, dict[str, str]]
) -> None:
    _, headers = admin
    await _create(client, headers, code="analysts")

    response = await client.post(
        ROLES, headers=headers, json={"code": "analysts", "name": "Again", "permissions": []}
    )
    assert response.status_code == 409
    assert envelope(response) == {
        "code": "ROLE_CODE_TAKEN",
        "message": "A role already exists under that code.",
        "field": "code",
    }


async def test_a_permission_this_application_does_not_have_is_refused_by_the_schema(
    client: AsyncClient, admin: tuple[Account, dict[str, str]]
) -> None:
    """Typed as the catalogue, so the refusal names the value rather than a foreign key."""
    _, headers = admin
    response = await client.post(
        ROLES,
        headers=headers,
        json={"code": "wrong", "name": "Wrong", "permissions": ["users.raed"]},
    )
    assert response.status_code == 422
    assert envelope(response)["code"] == "VALIDATION_ERROR"


async def test_an_unknown_role_is_a_404_rather_than_a_refusal(
    client: AsyncClient, admin: tuple[Account, dict[str, str]]
) -> None:
    _, headers = admin
    missing = uuid.uuid4()
    assert (await client.delete(f"{ROLES}/{missing}", headers=headers)).status_code == 404
    replaced = await client.put(
        f"{ROLES}/{missing}", headers=headers, json={"name": "Nobody", "permissions": []}
    )
    assert replaced.status_code == 404


async def test_a_grant_takes_effect_on_the_next_request_and_not_thirty_seconds_later(
    client: AsyncClient, session: AsyncSession, clock: Clock, admin: tuple[Account, dict[str, str]]
) -> None:
    """The snapshot is dropped by the write, so the holder's next call sees the new grant.

    Without the invalidation this passes its first assertion, fails its last, and looks exactly
    like an editor that does not save.
    """
    _, headers = admin
    created = await _create(client, headers, code="newcomers", name="Newcomers", permissions=[])
    holder = await create_account(session, email="newcomer@example.com", role_code="newcomers")
    as_holder = bearer(holder, now=clock.now)

    assert (await client.get(USERS, headers=as_holder)).status_code == 403

    granted = await client.put(
        f"{ROLES}/{created['id']}",
        headers=headers,
        json={"name": "Newcomers", "permissions": ["users.read"]},
    )
    assert granted.status_code == 200

    assert (await client.get(USERS, headers=as_holder)).status_code == 200


async def test_a_grant_taken_away_stops_working_on_the_next_request(
    client: AsyncClient, session: AsyncSession, clock: Clock, admin: tuple[Account, dict[str, str]]
) -> None:
    """The direction that matters more, and the one a cache would hide for half a minute."""
    _, headers = admin
    created = await _create(
        client, headers, code="leavers", name="Leavers", permissions=["users.read"]
    )
    holder = await create_account(session, email="leaver@example.com", role_code="leavers")
    as_holder = bearer(holder, now=clock.now)

    assert (await client.get(USERS, headers=as_holder)).status_code == 200

    await client.put(
        f"{ROLES}/{created['id']}", headers=headers, json={"name": "Leavers", "permissions": []}
    )
    assert (await client.get(USERS, headers=as_holder)).status_code == 403


async def test_an_edit_to_a_role_is_recorded_and_names_no_world(
    client: AsyncClient, session: AsyncSession, admin: tuple[Account, dict[str, str]]
) -> None:
    """A role belongs to the panel, not to a world, and the row says so by leaving it empty."""
    _, headers = admin
    created = await _create(client, headers, code="recorded", name="Recorded")
    await client.put(
        f"{ROLES}/{created['id']}",
        headers=headers,
        json={"name": "Recorded", "permissions": ["plans.read"]},
    )
    await client.delete(f"{ROLES}/{created['id']}", headers=headers)

    rows = (
        (
            await session.execute(
                # Tie-broken by `seq`. The three writes share this test's outer transaction, so
                # they share an `occurred_at` — and the order without it was the primary key's.
                select(AuditLog)
                .where(AuditLog.target_id == "recorded")
                .order_by(AuditLog.occurred_at, AuditLog.seq)
            )
        )
        .scalars()
        .all()
    )
    assert [row.action for row in rows] == ["role.create", "role.update", "role.delete"]
    assert {row.target_type for row in rows} == {"role"}
    assert {row.world_id for row in rows} == {None}
    assert rows[1].payload_json["permissions"] == ["plans.read"]
