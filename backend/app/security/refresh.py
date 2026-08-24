"""Refresh tokens: issue, rotate, detect reuse, and give the honest races a grace window.

A family is one device's chain of tokens. It is minted at login, it lasts ninety days, and it is
never extended: sliding expiry inside a hard ceiling. Each exchange consumes the token presented
and issues its successor in the same family. Exactly one token per family is live at any moment,
and every rotation — including a grace rotation — maintains that by revoking whatever leaf it
replaces. A family that held two live tokens would be two independent sessions that never collide,
which is to say a family in which reuse can no longer be detected at all.

Presenting a token that was already consumed is the signal that a copy of it exists somewhere it
should not, and the answer is to revoke every family the user has — the device is no longer
trusted, and neither are its siblings. That rule alone would log people out constantly: a reload
mid-flight, a second tab, a retry after the wifi dropped all legitimately present the same token
twice within a second. The thirty-second grace window is what separates the two, and every hit on
it is logged.

Revocation is not theft. Every revoked row says why it was revoked, and the reason decides the
answer: a session that was logged out, deactivated or caught in somebody else's cascade is over,
and saying so is a plain refusal. Only a token that was actually replayed revokes anything. Asking
"is it revoked?" without asking "why?" would mean that after one cascade the user's other devices
each trip a cascade of their own on their next refresh, killing the session they had just signed
back into and logging an alarm about a family that leaked nothing.

Every function here commits. The revocation that follows reuse detection has to survive the 401
that follows it, and a rotated token has to exist in the table before its value reaches a cookie;
leaving either to a caller's error path would make correctness depend on which branch it took.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

import structlog
from fastapi import Request, Response
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.models import RefreshToken, User

_log = structlog.get_logger(__name__)

# Path is /api/auth and not /, which is why the cookie cannot carry the __Host- prefix: that
# prefix requires Path=/, and Path=/ would attach the refresh token to every single API request
# the panel makes. The prefix buys a guarantee about which host set the cookie; the narrow path
# keeps the token off the wire except on the three routes that exchange it.
COOKIE_NAME: Final = "sa_refresh"
COOKIE_PATH: Final = "/api/auth"

# 32 bytes from secrets, base64url-encoded. There is nothing to guess and nothing to grind, which
# is why the stored form is a plain sha256 rather than argon2: a salted hash cannot be looked up
# by value, and a lookup that costs 50 ms would put the whole refresh path on one CPU's critical
# section.
_TOKEN_BYTES: Final = 32

FAMILY_TTL: Final = timedelta(days=90)
TOKEN_TTL: Final = timedelta(days=30)

# Long enough to cover a reload with a request already in flight, short enough that a stolen
# token is worth nothing by the time it is carried anywhere.
GRACE_PERIOD: Final = timedelta(seconds=30)

# How long a row outlives the moment it stopped being exchangeable. See prune_expired().
PRUNE_RETENTION: Final = timedelta(days=7)


class RevocationReason(StrEnum):
    """Why `revoked_at` was set. Written in the same statement, never afterwards.

    The value is what a later presentation of that row is judged by, so these are not log labels:
    SUPERSEDED is a leaf that a rotation replaced and may still be inside its grace window, REUSE
    marks the one token that was actually replayed, and the other three are sessions that ended
    for a reason having nothing to do with the token that is now being presented.
    """

    SUPERSEDED = "superseded"
    LOGOUT = "logout"
    INACTIVE = "inactive"
    REUSE = "reuse"
    FAMILY_REVOKED = "family_revoked"


class Presentation(StrEnum):
    """What the row behind a presented token says about it."""

    FRESH = "fresh"
    GRACE = "grace"
    REUSE = "reuse"
    REVOKED = "revoked"
    EXPIRED = "expired"
    FAMILY_EXPIRED = "family_expired"


class RefreshFailure(StrEnum):
    """Why an exchange was refused.

    REUSED answers with the error code REFRESH_TOKEN_REUSED and INACTIVE with USER_INACTIVE;
    everything else is REFRESH_TOKEN_INVALID, because the distinctions between them are useful in
    a log and are nobody else's business. The values are the `reason` field of that log line.
    """

    UNKNOWN = "unknown"
    EXPIRED = "expired"
    FAMILY_EXPIRED = "family_expired"
    REUSED = "reused"
    REVOKED = "revoked"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class IssuedRefreshToken:
    """A token that now exists in the table. `value` is the only copy of the plaintext."""

    value: str
    family_id: uuid.UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RefreshRotated:
    """The exchange succeeded and the caller owes the client a cookie and an access token."""

    user: User
    token: IssuedRefreshToken

    # True when the presented token had already been consumed and the grace window covered it.
    # The rotation is real either way; this is here so the route can say so in its log line.
    grace: bool


@dataclass(frozen=True, slots=True)
class RefreshRejected:
    """The exchange failed. The caller clears the cookie on every one of these."""

    reason: RefreshFailure
    user_id: uuid.UUID | None = None
    family_id: uuid.UUID | None = None


RefreshOutcome = RefreshRotated | RefreshRejected


def mint_refresh_token() -> str:
    """A new opaque token value."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_refresh_token(value: str) -> str:
    """The form stored in `refresh_tokens.token_hash`, and the only form ever written down."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def classify_presented_token(token: RefreshToken, now: datetime) -> Presentation:
    """Decide what a presented token is, in the order the conditions have to be asked.

    Expiry comes first, and the family's ceiling before the token's own. Every token expires no
    later than its family does, so asking about the token first would answer "expired" for a
    session that actually reached its ninety-day end — true, and useless to whoever is reading the
    log. An expired token of either kind is refused without revoking anything: nobody can exchange
    it, so treating one as evidence of theft would end every session belonging to a person whose
    laptop slept for a month.

    Then revocation, judged by its reason and never by its mere existence:

    - SUPERSEDED is the leaf a rotation replaced. Inside the grace window it is the other half of
      an honest double submit — the two racing requests hand out two tokens, and the browser keeps
      whichever response arrived last, so the loser has to work for as long as the window covers
      it. Outside the window it is theft, and this is the branch that makes theft visible: an
      attacker who replays a token inside the window gets a live one, but the copy the victim's
      browser kept is now superseded, and the victim's own next refresh — fifteen minutes later,
      when the access token expires — presents it and trips the cascade.
    - REUSE is the one token that was actually replayed. Presenting it again is not new
      information, but it is not innocent either.
    - Everything else is a session that ended for its own reasons: a logout, a deactivated
      account, or a cascade started by some other device. The session is over, which is a plain
      refusal — treating it as theft would make every sibling of a revoked family start a cascade
      of its own. A revoked row with no reason at all is not something this code writes; it is
      judged the same way, because inventing evidence of theft out of a missing value is the one
      mistake with a blast radius.

    Then use: an unused token rotates, a token used within the grace window rotates again, and a
    token used before that is a copy of a secret that is in two places at once.
    """
    if token.family_expires_at <= now:
        return Presentation.FAMILY_EXPIRED
    if token.expires_at <= now:
        return Presentation.EXPIRED
    if token.revoked_at is not None:
        if token.revoked_reason == RevocationReason.SUPERSEDED:
            if now - token.revoked_at <= GRACE_PERIOD:
                return Presentation.GRACE
            return Presentation.REUSE
        if token.revoked_reason == RevocationReason.REUSE:
            return Presentation.REUSE
        return Presentation.REVOKED
    if token.used_at is None:
        return Presentation.FRESH
    if now - token.used_at <= GRACE_PERIOD:
        return Presentation.GRACE
    return Presentation.REUSE


async def issue_for_login(
    session: AsyncSession, *, user_id: uuid.UUID, now: datetime
) -> IssuedRefreshToken:
    """Start a family. This is the only place a family_id is minted."""
    issued = await _issue(
        session,
        user_id=user_id,
        family_id=uuid.uuid4(),
        family_expires_at=now + FAMILY_TTL,
        now=now,
    )
    await session.commit()
    return issued


async def rotate(session: AsyncSession, *, presented: str, now: datetime) -> RefreshOutcome:
    """Exchange a refresh token for its successor, or refuse and say why."""
    token_hash = hash_refresh_token(presented)
    loaded = await _load(session, token_hash)
    if loaded is None:
        return RefreshRejected(RefreshFailure.UNKNOWN)
    token, user = loaded

    verdict = classify_presented_token(token, now)
    if verdict is Presentation.FRESH and not await _consume(session, token.id, now):
        # Two requests presented the same unused token at the same time and the database awarded
        # the single fresh rotation to the other one. Read the row back as it now stands and judge
        # it again: it has just been used, so this request lands in the grace window and rotates
        # there. The winner is chosen by `WHERE used_at IS NULL`, never by whichever coroutine
        # happened to be resumed first.
        loaded = await _load(session, token_hash, reread=True)
        if loaded is None:
            return RefreshRejected(RefreshFailure.UNKNOWN)
        token, user = loaded
        verdict = classify_presented_token(token, now)

    if verdict is Presentation.EXPIRED or verdict is Presentation.FAMILY_EXPIRED:
        reason = (
            RefreshFailure.EXPIRED
            if verdict is Presentation.EXPIRED
            else RefreshFailure.FAMILY_EXPIRED
        )
        return RefreshRejected(reason, user_id=user.id, family_id=token.family_id)

    if verdict is Presentation.REVOKED:
        # A session that ended for a reason of its own: a logout, a deactivated account, or a
        # cascade some other device started. Nothing is revoked here — everything already is, and
        # a second cascade would take with it whatever the user has signed into since.
        return RefreshRejected(RefreshFailure.REVOKED, user_id=user.id, family_id=token.family_id)

    if verdict is Presentation.REUSE:
        # The replayed row is marked first, and with a reason of its own, so the cascade below
        # skips it: it is the only token this user holds that is evidence of anything, and the
        # only one whose re-presentation should trip this branch again.
        replayed = await _mark_replayed(session, token_id=token.id, now=now)
        cascaded = await revoke_all_families_of_user(
            session, user_id=user.id, now=now, reason=RevocationReason.FAMILY_REVOKED
        )
        _log.warning(
            "refresh_token_reuse_detected",
            user_id=str(user.id),
            family_id=str(token.family_id),
            revoked_tokens=replayed + cascaded,
        )
        return RefreshRejected(RefreshFailure.REUSED, user_id=user.id, family_id=token.family_id)

    if not user.is_active:
        # The family dies with the account. A deactivated user holding a live refresh token would
        # otherwise keep minting access tokens that the request path then refuses one by one.
        await revoke_family(
            session, family_id=token.family_id, now=now, reason=RevocationReason.INACTIVE
        )
        return RefreshRejected(RefreshFailure.INACTIVE, user_id=user.id, family_id=token.family_id)

    if verdict is Presentation.GRACE:
        # The presented token has already been rotated once, so the family holds a leaf that this
        # exchange is about to replace. Revoking it here is what keeps "one live token per family"
        # true through a grace hit: without it the family forks, both branches rotate forever as
        # FRESH, they never collide, and reuse detection can never fire on that family again.
        #
        # The presented token itself is deliberately left alone. Its own window is measured from
        # `used_at` and must not be restarted by every hit, or a client that keeps replaying one
        # token would hold it open indefinitely.
        superseded = await _supersede_leaves(
            session, family_id=token.family_id, keeping=token.id, now=now
        )
        # GRACE is reachable through a token that was used or one that was superseded; whichever
        # timestamp exists is the one the window was measured from. The fallback is there so the
        # type checker does not have to take that on trust.
        since = token.used_at or token.revoked_at or now
        _log.warning(
            "refresh_token_grace_rotation",
            user_id=str(user.id),
            family_id=str(token.family_id),
            used_age_ms=int((now - since).total_seconds() * 1000),
            superseded_tokens=superseded,
        )

    issued = await _issue(
        session,
        user_id=user.id,
        family_id=token.family_id,
        # Never recomputed. The ceiling is set once, at login, and a family that has been rotating
        # for eighty-nine days has one day left.
        family_expires_at=token.family_expires_at,
        now=now,
    )
    await session.commit()
    return RefreshRotated(user=user, token=issued, grace=verdict is Presentation.GRACE)


async def revoke_family(
    session: AsyncSession, *, family_id: uuid.UUID, now: datetime, reason: RevocationReason
) -> int:
    """Revoke every live token in one family. Returns how many rows it touched."""
    return await _revoke(session, RefreshToken.family_id == family_id, now, reason)


async def revoke_all_families_of_user(
    session: AsyncSession, *, user_id: uuid.UUID, now: datetime, reason: RevocationReason
) -> int:
    """Revoke every live token this user has, on every device. Returns how many rows it touched.

    This is the answer to reuse detection, and it is deliberately blunt: a token that turned up
    twice was copied, and nothing about the copy says which of the user's devices it came from.
    """
    return await _revoke(session, RefreshToken.user_id == user_id, now, reason)


async def revoke_family_for_token(session: AsyncSession, *, presented: str, now: datetime) -> bool:
    """Revoke the family a presented token belongs to. False when no such token exists.

    This is logout. It asks nothing about whether the token is fresh, used or already revoked:
    the point is that the family stops working, and a caller that has already been logged out is
    not an error. It ends this family and no other — the reason it writes says so, so that the
    person's other devices read their next refusal as "this session ended" rather than as theft.
    """
    stmt = select(RefreshToken.family_id).where(
        RefreshToken.token_hash == hash_refresh_token(presented)
    )
    family_id = (await session.execute(stmt)).scalar_one_or_none()
    if family_id is None:
        return False
    await revoke_family(session, family_id=family_id, now=now, reason=RevocationReason.LOGOUT)
    return True


async def prune_expired(session: AsyncSession, *, now: datetime) -> int:
    """Delete the rows that can no longer answer a question. Returns how many.

    A row stops being exchangeable at `expires_at` — never later, since the family's ceiling caps
    every token it issues — and from that moment it is only evidence. What it is evidence of is
    reuse: which token was replayed, when, and what the cascade took with it. That is worth
    something for as long as somebody might still be reading the alarm it produced, and nothing at
    all afterwards, so rows are kept a week past the point of no use and then deleted.

    Both dates are asked, because a family can be revoked after its tokens have expired — logging
    out of a laptop that has been shut for a month writes `revoked_at` onto rows that expired
    weeks ago — and a week of retention has to be a week from the last thing that happened to the
    row, not from a date that was already in the past when it was written.

    Deleting rather than archiving: this is the one table in the schema that grows with traffic
    rather than with the number of people using the panel, and a session that ended in April is
    not an audit trail. The audit log is a different table with a different retention.
    """
    cutoff = now - PRUNE_RETENTION
    stmt = (
        delete(RefreshToken)
        .where(
            RefreshToken.expires_at <= cutoff,
            or_(RefreshToken.revoked_at.is_(None), RefreshToken.revoked_at <= cutoff),
        )
        # Counted through RETURNING rather than rowcount, for the same reason the revocations
        # above are: the count goes into a log line and into the CLI's output, and this table
        # holds a handful of rows per person per month.
        .returning(RefreshToken.id)
        .execution_options(synchronize_session=False)
    )
    deleted = (await session.execute(stmt)).scalars().all()
    await session.commit()
    return len(deleted)


def set_refresh_cookie(response: Response, issued: IssuedRefreshToken) -> None:
    """Attach the refresh cookie for a token that was just issued."""
    response.set_cookie(
        COOKIE_NAME,
        issued.value,
        # The cookie dies with the token it carries, including when the family's ninety-day
        # ceiling cut this token short.
        expires=issued.expires_at,
        path=COOKIE_PATH,
        httponly=True,
        # Lax, not Strict: a link from an email into the panel must not land on a login form for
        # someone who is already signed in. The token is only ever sent to /api/auth, and every
        # route under it is a POST, which Lax does not attach a cookie to cross-site.
        samesite="lax",
        secure=get_settings().cookie_secure,
        # No Domain attribute: a host-only cookie is not shared with any subdomain.
    )


def clear_refresh_cookie(response: Response) -> None:
    """Expire the refresh cookie.

    Sent on logout and on every refusal to refresh. A cookie that has been rejected once will be
    rejected forever, and leaving it in the browser means the panel retries it on every load.
    The attributes have to match the ones it was set with or the browser deletes nothing.
    """
    response.delete_cookie(
        COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
    )


def read_refresh_cookie(request: Request) -> str | None:
    """The presented token, or None when there is no usable cookie."""
    return request.cookies.get(COOKIE_NAME) or None


async def _issue(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    family_expires_at: datetime,
    now: datetime,
) -> IssuedRefreshToken:
    """Write one new token row and hand back the only copy of its plaintext."""
    value = mint_refresh_token()
    # Sliding, but capped: a family that is nearly ninety days old issues tokens that expire with
    # it rather than a month after it.
    #
    # Converted to UTC because on the capped branch this value came back from Postgres carrying
    # whatever offset the server's TimeZone names, and it goes on to be a cookie's Expires — which
    # is written as GMT, and which the standard library refuses to render from an instant whose
    # tzinfo is not UTC. Without this, every rotation in the last thirty days of a family's life
    # is a 500 on any host whose database was initialised outside UTC.
    expires_at = min(now + TOKEN_TTL, family_expires_at).astimezone(UTC)

    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(value),
            family_id=family_id,
            # Written explicitly rather than left to the column default, so that every timestamp
            # in one exchange comes from the same instant.
            issued_at=now,
            expires_at=expires_at,
            family_expires_at=family_expires_at,
        )
    )
    await session.flush()
    return IssuedRefreshToken(value=value, family_id=family_id, expires_at=expires_at)


async def _load(
    session: AsyncSession, token_hash: str, *, reread: bool = False
) -> tuple[RefreshToken, User] | None:
    """Fetch a token and its user in one statement.

    `reread` forces the row already in the identity map to be overwritten with what the database
    holds now. Without it a second select silently returns the stale copy, which on the race path
    is exactly the copy that says the token has never been used.
    """
    stmt = (
        select(RefreshToken, User)
        .join(User, User.id == RefreshToken.user_id)
        .where(RefreshToken.token_hash == token_hash)
    )
    if reread:
        stmt = stmt.execution_options(populate_existing=True)
    return (await session.execute(stmt)).tuples().one_or_none()


async def _consume(session: AsyncSession, token_id: uuid.UUID, now: datetime) -> bool:
    """Mark a token used, but only if nobody else already has. False means somebody else did.

    The condition lives in the WHERE clause so that Postgres decides which of two concurrent
    exchanges owns the rotation. Reading the row and then updating it would let both requests see
    an unused token and both issue a successor, which is two live tokens in one family and a
    reuse alarm the next time either is presented.
    """
    stmt = (
        update(RefreshToken)
        .where(
            RefreshToken.id == token_id,
            RefreshToken.used_at.is_(None),
            RefreshToken.revoked_at.is_(None),
        )
        .values(used_at=now)
        .returning(RefreshToken.id)
        .execution_options(synchronize_session=False)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _revoke(
    session: AsyncSession, criterion: ColumnElement[bool], now: datetime, reason: RevocationReason
) -> int:
    """Set revoked_at and its reason on the live rows matching `criterion`, and commit."""
    revoked = await _mark_revoked(session, criterion, now, reason)
    await session.commit()
    return revoked


async def _mark_replayed(session: AsyncSession, *, token_id: uuid.UUID, now: datetime) -> int:
    """Revoke the one token that was replayed, naming it as such. 1 when it was still live.

    Does not commit: the cascade that follows does, and the two writes belong to one decision.
    A token that was already revoked keeps the reason it had — it stopped being trusted then, not
    now, and whatever ended it is a truer record than this presentation is.
    """
    return await _mark_revoked(session, RefreshToken.id == token_id, now, RevocationReason.REUSE)


async def _supersede_leaves(
    session: AsyncSession, *, family_id: uuid.UUID, keeping: uuid.UUID, now: datetime
) -> int:
    """Revoke a family's unused tokens except one. Returns how many rows it touched.

    These are the leaves a grace rotation is replacing: a family's chain is linear, so an unused
    row other than the presented one was issued after it. Does not commit — the token that
    replaces them is written in the same transaction, and a family must never be observable
    without a leaf.

    `used_at IS NULL` is what keeps this to the leaves. The rest of the chain is already-consumed
    ancestors, and revoking one would move the only record of when it was consumed: SUPERSEDED is
    judged against `revoked_at`, so stamping it onto a token used a week ago would restart that
    token's grace window here, and presenting it in the next thirty seconds would rotate instead
    of raising the alarm. An ancestor needs no revoking to be refused — `used_at` already refuses
    it, and it refuses it as reuse.
    """
    return await _mark_revoked(
        session,
        (RefreshToken.family_id == family_id)
        & (RefreshToken.id != keeping)
        & RefreshToken.used_at.is_(None),
        now,
        RevocationReason.SUPERSEDED,
    )


async def _mark_revoked(
    session: AsyncSession, criterion: ColumnElement[bool], now: datetime, reason: RevocationReason
) -> int:
    """The revocation itself, without the commit. Returns how many rows it touched."""
    stmt = (
        update(RefreshToken)
        # Rows already revoked are left alone, so `revoked_at` keeps saying when the family
        # actually stopped being trusted rather than when it was last asked about — and so that a
        # cascade cannot overwrite the reason on the one row that says a token was replayed.
        .where(criterion, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason.value)
        .returning(RefreshToken.id)
        .execution_options(synchronize_session=False)
    )
    return len((await session.execute(stmt)).scalars().all())
