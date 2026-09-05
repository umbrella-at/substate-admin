"""The access token, and everything a valid signature is still not allowed to say.

A forged token is the easy case: the signature fails and it is refused. The cases worth testing
are the ones where the signature is good — a token this service signed, or one signed with a
stolen key — and the claims are not what this service mints. `typ` decides whether a token may
reach a guarded route at all, `world_id` belongs to exactly one kind of token, and `sub` becomes a
database lookup, so each of them is parsed rather than trusted.

The claim set is asserted whole, because what is absent from it is the design: no permissions
travel in a token, so a role edited at ten o'clock stops granting at ten o'clock rather than
fifteen minutes later.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
import pytest

from app.config import get_settings
from app.db import utc_now
from app.security.tokens import (
    ACCESS_TOKEN_TTL,
    ALGORITHM,
    AccessTokenExpired,
    AccessTokenInvalid,
    decode_access_token,
    encode_access_token,
)
from support import Clock

_SUBJECT: Final = uuid.UUID("11111111-1111-1111-1111-111111111111")
_WORLD: Final = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _claims(**overrides: Any) -> dict[str, Any]:
    """A claim set this service would have minted, before it is spoilt on purpose."""
    issued = _now()
    payload: dict[str, Any] = {
        "sub": str(_SUBJECT),
        "iat": int(issued.timestamp()),
        "exp": int((issued + ACCESS_TOKEN_TTL).timestamp()),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def _signed(**overrides: Any) -> str:
    """Sign a claim set with this service's own key, so only the claims are ever in question."""
    return jwt.encode(
        _claims(**overrides), get_settings().jwt_secret.get_secret_value(), algorithm=ALGORITHM
    )


def test_a_minted_token_carries_exactly_five_claims() -> None:
    """No permissions in the token, and nothing else spare either."""
    issued = encode_access_token(user_id=_SUBJECT, now=_now())

    payload = jwt.decode(
        issued.token, get_settings().jwt_secret.get_secret_value(), algorithms=[ALGORITHM]
    )

    assert set(payload) == {"sub", "iat", "exp", "jti", "typ"}
    assert payload["typ"] == "access"
    assert payload["sub"] == str(_SUBJECT)


def test_a_minted_token_reads_back_as_what_was_minted() -> None:
    now = _now()

    issued = encode_access_token(user_id=_SUBJECT, now=now)
    claims = decode_access_token(issued.token, now=Clock(now))

    assert claims.subject == _SUBJECT
    assert claims.typ == "access"
    assert claims.issued_at == now
    assert claims.expires_at == now + ACCESS_TOKEN_TTL
    assert claims.jti == issued.jti
    assert claims.world_id is None


def test_the_expiry_reported_and_the_expiry_inside_the_token_are_the_same_instant() -> None:
    """Truncated to whole seconds, because that is what a NumericDate claim holds. Without it the
    `expiresIn` handed to the client and the token's own `exp` differ by however far into a second
    the request happened to start."""
    now = datetime.now(UTC).replace(microsecond=987_654)

    issued = encode_access_token(user_id=_SUBJECT, now=now)

    assert issued.issued_at.microsecond == 0
    assert (issued.expires_at - issued.issued_at) == ACCESS_TOKEN_TTL
    assert decode_access_token(issued.token, now=Clock(now)).expires_at == issued.expires_at


def test_a_demo_token_names_its_world_and_reads_back_with_it() -> None:
    now = _now()

    issued = encode_access_token(user_id=_SUBJECT, now=now, typ="demo", world_id=_WORLD)

    claims = decode_access_token(issued.token, now=Clock(now))
    assert claims.typ == "demo"
    assert claims.world_id == _WORLD


def test_minting_refuses_the_pairings_that_cannot_mean_anything() -> None:
    """A programming error rather than a request anyone can make, so it fails here instead of at a
    decode that would have to guess what was meant."""
    with pytest.raises(ValueError, match="must name a world"):
        encode_access_token(user_id=_SUBJECT, now=_now(), typ="demo")

    with pytest.raises(ValueError, match="Only a demo token"):
        encode_access_token(user_id=_SUBJECT, now=_now(), world_id=_WORLD)


def test_a_token_expired_against_the_caller_s_clock_is_expired() -> None:
    """Two comparisons, and the stricter wins: an expired token cannot be revived by handing this
    function a clock that disagrees."""
    now = _now()
    issued = encode_access_token(user_id=_SUBJECT, now=now)

    with pytest.raises(AccessTokenExpired):
        decode_access_token(issued.token, now=Clock(now + ACCESS_TOKEN_TTL + timedelta(seconds=1)))


def test_a_token_expired_against_the_real_clock_is_expired_too() -> None:
    stale = _signed(exp=int((_now() - timedelta(seconds=1)).timestamp()))

    with pytest.raises(AccessTokenExpired):
        decode_access_token(stale, now=utc_now)


def test_the_algorithm_is_never_taken_from_the_token() -> None:
    """Reading it out of the token's own header is how a service ends up accepting alg=none."""
    unsigned = jwt.encode(_claims(), key=None, algorithm="none")

    with pytest.raises(AccessTokenInvalid):
        decode_access_token(unsigned, now=utc_now)


def test_a_token_signed_with_another_key_is_refused() -> None:
    forged = jwt.encode(_claims(), "a-key-this-service-does-not-hold", algorithm=ALGORITHM)

    with pytest.raises(AccessTokenInvalid):
        decode_access_token(forged, now=utc_now)


@pytest.mark.parametrize("claim", ["sub", "iat", "exp", "typ"])
def test_a_claim_this_application_reads_may_not_be_missing(claim: str) -> None:
    with pytest.raises(AccessTokenInvalid):
        decode_access_token(_signed(**{claim: None}), now=utc_now)


def test_a_token_with_no_jti_is_still_valid() -> None:
    """`jti` is minted and never consulted: there is no deny-list for it to be looked up in."""
    claims = decode_access_token(_signed(jti=None), now=utc_now)

    assert claims.jti is None


@pytest.mark.parametrize(
    "spoilt",
    [
        {"typ": "banana"},
        {"typ": 7},
        {"sub": "not-a-uuid"},
        {"sub": 7},
        {"exp": "soon"},
        {"iat": "recently"},
        # A NumericDate far outside the range of a datetime: malformed, not expired.
        {"exp": 10**20},
        # `jti` is optional, but when it is there it is a uuid string. PyJWT itself refuses a
        # non-string `sub`, so this is the claim that reaches the parsing below.
        {"jti": 7},
        {"jti": "not-a-uuid"},
        # Only a demo token may name a world.
        {"world_id": str(_WORLD)},
        # And a demo token must name one.
        {"typ": "demo"},
        {"typ": "demo", "world_id": "not-a-uuid"},
    ],
)
def test_a_claim_set_this_application_never_mints_is_refused(spoilt: dict[str, Any]) -> None:
    """Every token here carries this service's own signature. What is refused is what it says."""
    with pytest.raises(AccessTokenInvalid):
        decode_access_token(_signed(**spoilt), now=utc_now)


def test_rubbish_is_refused_rather_than_raising_something_else() -> None:
    for nonsense in ("", "not.a.token", "Bearer something", "a.b.c"):
        with pytest.raises(AccessTokenInvalid):
            decode_access_token(nonsense, now=utc_now)
