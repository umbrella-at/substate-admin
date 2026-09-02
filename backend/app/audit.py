"""The record of what operators did.

Narrow by decision: operations over subscriptions, and later edits to roles. Signing in, signing
out and changing a filter are authentication and navigation — they go to the structured log, where
they do not bury the handful of lines that say somebody changed something.

Attempts, not successes. `outcome` is `ok` or the code the caller was given, because "who tried to
cancel this subscription and was refused" is the question an investigation actually asks, and a
log holding only what worked cannot answer it.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, get_args

from sqlalchemy.ext.asyncio import AsyncSession
from substate import Event

from app.errors import ApiError, ErrorCode
from app.models import AuditLog
from app.subscribers.operations import CODE_FOR, FIELD_FOR, HANDLED
from app.worlds.journal import write_events
from app.worlds.registry import World, collecting

AuditAction = Literal[
    "subscription.subscribe",
    "subscription.cancel",
    "subscription.change_plan",
    "subscription.redeem",
    "subscription.payment",
    "subscription.assign_program",
]
"""What was asked for, named as the button names it.

Present tense, and deliberately not the engine's past tense: the journal says `subscription.
cancelled` because that is what happened, and this says `subscription.cancel` because that is what
somebody asked for. A row here with no matching event there is a refusal, and the two vocabularies
being different is what makes that readable rather than confusing.
"""

AUDIT_ACTIONS: Final[tuple[AuditAction, ...]] = get_args(AuditAction)

TargetType = Literal["subscription"]

OK: Final = "ok"
REFUSED: Final = "refused"
"""What became of the attempt. The code that explains a refusal is beside it, not folded into it:
the screen filters on two values, and a filter written as `outcome <> 'ok'` is a filter that has
to know every code there will ever be."""


@dataclass(frozen=True, slots=True)
class Entry:
    """One thing an operator did, minus what the caller already knows."""

    actor_user_id: uuid.UUID
    action: AuditAction
    target_type: TargetType
    target_id: str
    ip_hash: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    """The arguments of the operation, and nothing else. No token, no password, no raw address."""


async def record(
    session: AsyncSession, entry: Entry, *, world_id: str, refusal: ErrorCode | None
) -> None:
    """Add one row. The caller's transaction is what decides whether it survives."""
    session.add(
        AuditLog(
            actor_user_id=entry.actor_user_id,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            outcome=OK if refusal is None else REFUSED,
            error_code=None if refusal is None else refusal.value,
            payload_json=dict(entry.payload),
            world_id=world_id,
            ip_hash=entry.ip_hash,
        )
    )
    await session.flush()


async def perform(
    session: AsyncSession,
    world: World,
    entry: Entry,
    run: Callable[[], Awaitable[None]],
) -> list[Event]:
    """Run one operation against the engine, write down what happened, and report a refusal.

    The order is the whole content of this function. The engine moves first, because it is memory
    and cannot be rolled back by anything here; then everything it emitted goes to the journal and
    the attempt goes to the audit, in one transaction, so a card cannot show a cancellation whose
    audit row was lost.

    THE FLUSH HAPPENS ON THE REFUSAL PATH TOO, because some refusals come after the world has
    already moved. A code the engine has never heard of is refused before it looks at the
    subscription; a code with no redemptions left is refused after `_load_and_advance` has caught
    the record up and saved it. The second kind can therefore be the cause of an expiry, and
    skipping the flush would drop that event on the floor. It is also why a refusal is audited:
    without the row, the journal records a state change with nothing to explain it.

    Returns what the engine emitted, so the answer can say what happened. Three of the payment
    outcomes are events rather than exceptions — duplicate, underpaid, unmatched — and a 200 with
    an unchanged card is the worst screen this round can produce.
    """
    refused: ApiError | None = None
    code: ErrorCode | None = None
    # What THIS call emitted, which is not what the world has emitted. The sink is shared with the
    # ticker, and there is an await between the engine and the drain below for it to run in.
    with collecting() as produced:
        try:
            await run()
        except HANDLED as failure:
            code = CODE_FOR[type(failure)]
            refused = ApiError(code, field=FIELD_FOR.get(code))
            refused.__cause__ = failure

    # Everything pending, not only this call's. Two consequences, and the second is the price of
    # the first: a row the ticker left behind reaches the journal sooner, and if this request's
    # transaction rolls back that row is lost with it. The alternative — writing only this call's
    # events — would leave the rest for the ticker to write and there is no way to take a subset
    # out of the sink without racing it.
    pending = world.sink.drain()
    if pending:
        await write_events(await session.connection(), world.id, pending)
    await record(session, entry, world_id=world.id, refusal=code)
    await session.commit()

    if refused is not None:
        raise refused
    return produced
