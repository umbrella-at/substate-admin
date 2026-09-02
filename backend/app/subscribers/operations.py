"""Refusals that came out of the engine, said in this API's words.

`substate` refuses in exceptions and this service answers in an envelope, so something has to
translate. The rule the specification fixes is that the machine-readable `code` IS the exception's
name, respelled — the frontend switches on it, and a code invented here would be a second
vocabulary for a refusal that already had one.

So the mapping is derived rather than typed out. `PromoAlreadyBound` becomes `PROMO_ALREADY_BOUND`
mechanically, and the lookup into `ErrorCode` happens at import: a class this module claims to
handle whose name has no matching code is an ImportError, not a 500 on the day somebody redeems a
second discount.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import MappingProxyType
from typing import Final

from substate import (
    AlreadySubscribed,
    NotSubscribed,
    PromoAlreadyBound,
    PromoLimitReached,
    SubstateError,
    UnknownPlan,
    UnknownPromoCode,
    UnknownReferralProgram,
)

from app.errors import ApiError, ErrorCode

HANDLED: Final[tuple[type[SubstateError], ...]] = (
    AlreadySubscribed,
    NotSubscribed,
    UnknownPlan,
    UnknownPromoCode,
    PromoLimitReached,
    PromoAlreadyBound,
    UnknownReferralProgram,
)
"""Every refusal an operation endpoint can produce.

Deliberately not `SubstateError` itself. The rest of that tree — `DuplicatePlan`, `InvalidPeriod`,
`AdapterError` — means this service is configured wrongly rather than that the caller asked for
something impossible, and answering those with a tidy 409 would hide a deployment fault behind a
sentence about promo codes.
"""


def screaming(name: str) -> str:
    """PascalCase to SCREAMING_SNAKE. `PromoAlreadyBound` -> `PROMO_ALREADY_BOUND`."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


CODE_FOR: Final[Mapping[type[SubstateError], ErrorCode]] = MappingProxyType(
    # ErrorCode(...) is a lookup by value, so a class whose respelled name is not in the catalogue
    # raises here, at import, rather than at the call site nobody is watching.
    {failure: ErrorCode(screaming(failure.__name__)) for failure in HANDLED}
)

FIELD_FOR: Final[Mapping[ErrorCode, str]] = MappingProxyType(
    {
        # The two refusals that are about a value somebody submitted rather than about the state
        # of the subscription. Naming the field is what puts the sentence under the input.
        ErrorCode.UNKNOWN_PLAN: "planId",
        ErrorCode.UNKNOWN_PROMO_CODE: "promoCode",
        ErrorCode.UNKNOWN_REFERRAL_PROGRAM: "programId",
    }
)


@contextmanager
def refusals() -> Iterator[None]:
    """Turn a refusal from the engine into this API's envelope, and let anything else through.

    Anything else is a bug or a misconfiguration, and both belong in the 500 handler with a
    traceback in the journal rather than in a 409 that reads as an ordinary answer.
    """
    try:
        yield
    except HANDLED as refusal:
        code = CODE_FOR[type(refusal)]
        raise ApiError(code, field=FIELD_FOR.get(code)) from refusal
