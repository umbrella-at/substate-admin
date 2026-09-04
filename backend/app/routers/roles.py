"""Roles and what they grant.

THE REFUSAL IS IN THE APPLICATION, NOT IN A HIDDEN BUTTON. A system role is restored from the
catalogue on every deploy, so an accepted edit is undone at the next push and looks, until then,
like a change that took. Not drawing the control is the other half of the same rule.

Every write drops the role snapshot, and drops it AFTER its commit. It is cached for thirty
seconds: dropped before the commit, a reader racing the write re-reads the rows as they still are
and installs the pre-edit grants for another thirty.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_session
from app.deps import Identity, RequirePermission, invalidate_permission_cache
from app.errors import ApiError, ErrorCode
from app.models import Role, RolePermission, User
from app.permissions import PERMISSIONS
from app.routers import error_responses
from app.schemas import (
    CreateRoleRequest,
    PermissionSummary,
    RoleDetail,
    RolesResponse,
    RoleWriteRequest,
)
from app.security.ratelimit import client_ip_hash

router = APIRouter(prefix="/roles", tags=["roles"])

_WRITE = "users.write"
"""The catalogue already says what this code covers: the panel's own users and roles.

A `roles.write` of its own would be a fourteenth permission drawing a line the panel does not
draw — whoever may disable an operator's account is whoever decides what operators may do.
"""


async def _detail(session: AsyncSession, role: Role) -> RoleDetail:
    """One role with its grants and its holders, both counted where they are stored."""
    granted = (
        (
            await session.execute(
                select(RolePermission.permission_code)
                .where(RolePermission.role_id == role.id)
                .order_by(RolePermission.permission_code)
            )
        )
        .scalars()
        .all()
    )
    holders = (
        await session.execute(select(func.count()).select_from(User).where(User.role_id == role.id))
    ).scalar_one()
    return RoleDetail(
        id=role.id,
        code=role.code,
        name=role.name,
        is_system=role.is_system,
        permissions=list(granted),
        holders=holders,
    )


async def _load(session: AsyncSession, role_id: uuid.UUID, scope: str | None) -> Role:
    """One role of the caller's own world, or nothing.

    404 rather than 403 for a role belonging to somebody else, and that is the honest answer: a
    role of another world is not a role this session is refused, it is one that does not exist as
    far as this session is concerned.
    """
    role = (
        await session.execute(select(Role).where(Role.id == role_id, Role.world_id == scope))
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return role


def _refuse_if_system(role: Role) -> None:
    if role.is_system:
        raise ApiError(ErrorCode.ROLE_IS_SYSTEM)


async def _set_grants(session: AsyncSession, role: Role, codes: list[str]) -> None:
    """Replace what a role grants. The editor sends the whole set, so this is a replacement."""
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for code in sorted(set(codes)):
        session.add(RolePermission(role_id=role.id, permission_code=code))
    await session.flush()


async def _write_down(
    session: AsyncSession,
    identity: Identity,
    request: Request,
    action: audit.AuditAction,
    role: Role,
    payload: dict[str, object],
) -> None:
    """The audit row for a role edit. No world: this happened to the panel, not inside one."""
    await audit.record(
        session,
        audit.Entry(
            actor_user_id=identity.user.id,
            action=action,
            target_type="role",
            target_id=role.code,
            ip_hash=client_ip_hash(request),
            payload=payload,
        ),
        refusal=None,
    )


@router.get(
    "",
    summary="Every role, and the permissions a role may grant",
    responses=error_responses(401, 403),
)
async def list_roles(
    identity: Annotated[Identity, RequirePermission("users.read")],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RolesResponse:
    """The caller's own world's roles. A sandbox holds editable copies of the four system ones."""
    roles = (
        (
            await session.execute(
                select(Role)
                .where(Role.world_id == identity.world_scope)
                .order_by(Role.is_system.desc(), Role.code)
            )
        )
        .scalars()
        .all()
    )
    return RolesResponse(
        items=[await _detail(session, role) for role in roles],
        permissions=[
            PermissionSummary(code=code, description=description)
            for code, description in PERMISSIONS.items()
        ],
    )


@router.post(
    "",
    summary="Create a role of your own",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409, 422),
)
async def create_role(
    body: CreateRoleRequest,
    request: Request,
    identity: Annotated[Identity, RequirePermission(_WRITE)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoleDetail:
    role = Role(code=body.code, name=body.name, is_system=False, world_id=identity.world_scope)
    session.add(role)
    try:
        # Flushed alone, before the grants: both unique indexes on `roles` are over the code, one
        # per world, so an integrity error here can only be the code. Pre-checking with a SELECT
        # would leave a window the constraint would then fill with a 500.
        await session.flush()
    except IntegrityError as clash:
        raise ApiError(ErrorCode.ROLE_CODE_TAKEN, field="code") from clash

    await _set_grants(session, role, list(body.permissions))
    await _write_down(
        session, identity, request, "role.create", role, {"name": body.name, **_granted(body)}
    )
    await session.commit()
    invalidate_permission_cache()
    return await _detail(session, role)


@router.put(
    "/{role_id}",
    summary="Replace a role's name and what it grants",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def replace_role(
    role_id: uuid.UUID,
    body: RoleWriteRequest,
    request: Request,
    identity: Annotated[Identity, RequirePermission(_WRITE)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoleDetail:
    role = await _load(session, role_id, identity.world_scope)
    _refuse_if_system(role)

    role.name = body.name
    await _set_grants(session, role, list(body.permissions))
    await _write_down(
        session, identity, request, "role.update", role, {"name": body.name, **_granted(body)}
    )
    await session.commit()
    invalidate_permission_cache()
    return await _detail(session, role)


@router.delete(
    "/{role_id}",
    summary="Delete a role nobody holds",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409),
)
async def delete_role(
    role_id: uuid.UUID,
    request: Request,
    identity: Annotated[Identity, RequirePermission(_WRITE)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    role = await _load(session, role_id, identity.world_scope)
    _refuse_if_system(role)

    # Checked here rather than left to the RESTRICT on `users.role_id`, which would arrive as an
    # integrity error with nothing a screen can say. The refusal names the way out instead.
    holders = (
        await session.execute(select(func.count()).select_from(User).where(User.role_id == role.id))
    ).scalar_one()
    if holders:
        raise ApiError(ErrorCode.ROLE_IN_USE)

    await _write_down(session, identity, request, "role.delete", role, {"name": role.name})
    await session.delete(role)
    await session.commit()
    invalidate_permission_cache()


def _granted(body: RoleWriteRequest) -> dict[str, object]:
    """What went into the audit row: the grants as they were submitted, sorted and deduplicated."""
    return {"permissions": sorted(set(body.permissions))}
