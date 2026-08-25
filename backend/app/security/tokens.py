"""The access token: fifteen minutes, HS256, and a claim set with nothing spare in it.

There are no permissions in the token. A token that carried them would be a snapshot of a role at
the moment it was minted, and revoking a permission would take up to fifteen minutes to mean
anything. Permissions are read from the database on every request instead; the token only says
who is asking.

`jti` is minted and never consulted. There is no deny-list, because a deny-list needs shared
state and this process has none — a token is cut short by deactivating the user, which the
database answers on the next request.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, cast, get_args

import jwt

from app.config import get_settings
from app.db import NowProvider, utc_now

# "access" is a person who logged in. "demo" names a world and is refused by every dependency that
# guards a permission; no route mints one today, and validating the shape here is what stops one
# from being forged into existence.
TokenType = Literal["access", "demo"]

ALGORITHM: Final = "HS256"
ACCESS_TOKEN_TTL: Final = timedelta(minutes=15)

_TOKEN_TYPES: Final[frozenset[str]] = frozenset(get_args(TokenType))

# Never decode with the algorithm the token names, and never accept a token that leaves out the
# claims this application reads. `jti` is absent on purpose: nothing depends on it.
_REQUIRED_CLAIMS: Final[list[str]] = ["exp", "iat", "sub", "typ"]


class AccessTokenError(Exception):
    """Base for every reason a bearer token was not accepted."""


class AccessTokenExpired(AccessTokenError):
    """The signature was good and the token is past its expiry.

    The distinct type matters: this is the one condition the frontend answers by refreshing, and
    it reaches it as the error code TOKEN_EXPIRED rather than NOT_AUTHENTICATED.
    """


class AccessTokenInvalid(AccessTokenError):
    """Missing, malformed, wrongly signed, or carrying a claim set this application never mints."""


@dataclass(frozen=True, slots=True)
class IssuedAccessToken:
    """A minted token and the facts about it the caller has to report."""

    token: str
    issued_at: datetime
    expires_at: datetime
    jti: uuid.UUID


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """A verified token, with every claim already turned into the type it stands for."""

    subject: uuid.UUID
    typ: TokenType
    issued_at: datetime
    expires_at: datetime
    jti: uuid.UUID | None
    world_id: uuid.UUID | None


def encode_access_token(
    *,
    user_id: uuid.UUID,
    now: datetime,
    typ: TokenType = "access",
    world_id: uuid.UUID | None = None,
    ttl: timedelta = ACCESS_TOKEN_TTL,
) -> IssuedAccessToken:
    """Mint a token for `user_id`.

    `world_id` belongs to a demo token and to nothing else. Getting that pairing wrong is a
    programming error, not a request anyone can make, so it fails here rather than at a decode
    that would have to guess what was meant.
    """
    if typ == "demo" and world_id is None:
        raise ValueError("A demo token must name a world.")
    if typ != "demo" and world_id is not None:
        raise ValueError("Only a demo token may name a world.")

    # Truncated to whole seconds because that is what the claims hold. Without this the expiry
    # reported to the client and the expiry inside the token differ by however far into a second
    # the request happened to start.
    issued_at = now.astimezone(UTC).replace(microsecond=0)
    expires_at = issued_at + ttl
    jti = uuid.uuid4()

    claims: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(jti),
        "typ": typ,
    }
    if world_id is not None:
        claims["world_id"] = str(world_id)

    token = jwt.encode(claims, get_settings().jwt_secret.get_secret_value(), algorithm=ALGORITHM)
    return IssuedAccessToken(token=token, issued_at=issued_at, expires_at=expires_at, jti=jti)


def decode_access_token(token: str, *, now: NowProvider = utc_now) -> AccessTokenClaims:
    """Verify a bearer token and return its claims.

    Raises AccessTokenExpired for a good token that has run out, AccessTokenInvalid for anything
    else. Those two are the whole vocabulary: the caller needs to know whether refreshing would
    help, and nothing finer than that may reach a response body.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            get_settings().jwt_secret.get_secret_value(),
            # Named explicitly. Reading the algorithm out of the token's own header is how a
            # service ends up verifying an HS256 signature against a public key, or accepting
            # alg=none.
            algorithms=[ALGORITHM],
            leeway=0,
            options={"require": _REQUIRED_CLAIMS, "verify_signature": True},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AccessTokenExpired("The access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AccessTokenInvalid("The access token could not be verified.") from exc

    raw_typ = payload.get("typ")
    if not isinstance(raw_typ, str) or raw_typ not in _TOKEN_TYPES:
        raise AccessTokenInvalid("The access token names a type this application does not mint.")
    typ = cast(TokenType, raw_typ)

    raw_world = payload.get("world_id")
    if typ == "demo":
        if raw_world is None:
            raise AccessTokenInvalid("A demo token must name a world.")
        world_id = _as_uuid(raw_world, "world_id")
    else:
        if raw_world is not None:
            raise AccessTokenInvalid("Only a demo token may name a world.")
        world_id = None

    raw_jti = payload.get("jti")
    expires_at = _as_instant(payload.get("exp"), "exp")

    # jwt.decode has already compared exp with the real clock. This repeats the comparison against
    # the caller's clock, which is what lets a test move time forward without touching the
    # process. Two checks, and the stricter one wins: an expired token cannot be revived by
    # handing this function a clock that disagrees.
    if expires_at <= now():
        raise AccessTokenExpired("The access token has expired.")

    return AccessTokenClaims(
        subject=_as_uuid(payload.get("sub"), "sub"),
        typ=typ,
        issued_at=_as_instant(payload.get("iat"), "iat"),
        expires_at=expires_at,
        jti=_as_uuid(raw_jti, "jti") if raw_jti is not None else None,
        world_id=world_id,
    )


def _as_uuid(value: Any, claim: str) -> uuid.UUID:
    """Read a claim that this application always writes as a uuid string."""
    if not isinstance(value, str):
        raise AccessTokenInvalid(f"Claim {claim} is not a string.")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise AccessTokenInvalid(f"Claim {claim} is not a uuid.") from exc


def _as_instant(value: Any, claim: str) -> datetime:
    """Read a NumericDate claim as an aware UTC datetime."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AccessTokenInvalid(f"Claim {claim} is not a number.")
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OSError, OverflowError, ValueError) as exc:
        # A timestamp far outside the range of a datetime. Malformed, not expired.
        raise AccessTokenInvalid(f"Claim {claim} is not a representable instant.") from exc
