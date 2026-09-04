"""The door into a demonstration: one route, and no session machinery behind it.

Pressed without a credential it builds a world and hands back a pass into it. Pressed WITH a live
pass it extends the same world and hands back a fresh one, up to the sandbox's hard ceiling.

THAT SECOND HALF IS NOT A REFRESH, AND THE DIFFERENCE IS THE WHOLE DESIGN.

There is no cookie, no token family, no rotation and no reuse detection — none of the machinery
`app.security.refresh` exists to run, and no row anywhere that has to be revoked.

The only state is the world itself, and the ceiling on it is absolute: past two hours nothing
renews, whatever anybody presents.

Without the renewal the extension would be a lie. A pass that cannot be re-minted dies in an hour,
so extending the world past that keeps a world nobody can reach — holding a slot under the ceiling
against a visitor who has already been thrown out.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import NowProvider, get_now, get_session
from app.demo.sandboxes import SandboxesAreFull, extend_sandbox, open_sandbox
from app.deps import Public, load_user, optional_bearer
from app.errors import ApiError, ErrorCode
from app.logging import get_logger
from app.routers import error_responses
from app.schemas import DemoSessionResponse
from app.security.ratelimit import DEMO_PER_IP, client_ip_hash, get_limiter
from app.security.tokens import AccessTokenError, decode_access_token, encode_access_token
from app.worlds.registry import World, get_registry

_log = get_logger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post(
    "/session",
    summary="Open a demonstration world, or keep the one you have",
    dependencies=[Public()],
    responses=error_responses(429, 503),
)
async def open_session(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(optional_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    now: Annotated[NowProvider, Depends(get_now)],
) -> DemoSessionResponse:
    """Build a world for whoever asked, or extend the one their pass names.

    Public by necessity: the first press comes from somebody with no credential at all. The
    ceiling on how many worlds may stand and the rate limit below are what that costs.
    """
    moment = now()
    registry = get_registry()
    standing = await _standing(session, credentials, now=moment)

    if standing is None:
        ip_hash = client_ip_hash(request)
        decision = get_limiter().hit(DEMO_PER_IP, ip_hash, now=moment)
        if not decision.allowed:
            _log.warning("demo_rate_limited", retry_after=decision.retry_after)
            raise ApiError(
                ErrorCode.RATE_LIMITED, headers={"Retry-After": str(decision.retry_after)}
            )
        try:
            sandbox = await open_sandbox(session, registry, ip_hash=ip_hash, now=moment)
        except SandboxesAreFull as full:
            _log.warning("demo_ceiling_reached", standing=len(registry.sandboxes()))
            raise ApiError(ErrorCode.SANDBOX_FULL) from full
        world, user_id = sandbox.world, sandbox.user_id
    else:
        world, user_id = standing
        await extend_sandbox(session, world, now=moment)

    # Both paths wrote: a whole history on the first, one row on the second. Committed here rather
    # than in either of them, so a world exists in the registry only once its rows are on disk.
    await session.commit()

    ends_at = world.ceiling_at
    expires_at = world.expires_at
    if (
        ends_at is None or expires_at is None
    ):  # pragma: no cover - a sandbox has both by construction
        raise ApiError(ErrorCode.INTERNAL_ERROR)

    # As long as the world has left and not a minute more. The pass and the sandbox end together,
    # so there is never a live token for a world that is gone, nor a world nobody may open.
    issued = encode_access_token(
        user_id=user_id,
        now=moment,
        typ="demo",
        world_id=uuid.UUID(world.id),
        ttl=expires_at - moment,
    )
    return DemoSessionResponse(
        access_token=issued.token,
        expires_in=int((issued.expires_at - moment).total_seconds()),
        ends_at=ends_at,
    )


async def _standing(
    session: AsyncSession, credentials: HTTPAuthorizationCredentials | None, *, now: datetime
) -> tuple[World, uuid.UUID] | None:
    """The world this request already holds a live pass into, if it holds one.

    Anything else — no pass, a pass this service did not mint, one that has run out, one naming a
    world that is gone — is not an error here. It is somebody pressing the button, and the answer
    to that is a new world rather than a refusal they can do nothing about.
    """
    if credentials is None:
        return None
    try:
        claims = decode_access_token(credentials.credentials, now=lambda: now)
    except AccessTokenError:
        return None
    if claims.typ != "demo" or claims.world_id is None:
        return None

    world = get_registry().get(str(claims.world_id))
    if world is None or not world.alive_at(now) or world.ceiling_at is None:
        return None
    if world.ceiling_at <= now:
        return None

    # The pass names a subject, and the subject has to still be an operator of that world. It is
    # the same lookup the identity resolver runs, and for the same reason: a token names a row, and
    # a row that is not there is not one to mint a fresh pass for.
    user = await load_user(session, claims.subject, world_id=world.id)
    return None if user is None else (world, user.id)
