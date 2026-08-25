"""argon2id hashing and the single password policy this application applies.

Every path that touches a password goes through this module: the CLI when it creates an account,
login when it checks one. Two implementations of "is this password acceptable" would eventually
disagree, and the one that disagrees quietly is the one that lets a six-character password in.
"""

import secrets
import unicodedata
from dataclasses import dataclass
from typing import Final

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from app.models import normalize_email

MIN_PASSWORD_LENGTH: Final = 12

# Not cosmetic. argon2 reads its whole input before it starts, so an unbounded password field is a
# free way to make one CPU do megabytes of work per request.
MAX_PASSWORD_LENGTH: Final = 128

# 19 MiB, two passes, one lane — the second of the two parameter sets RFC 9106 recommends. The
# library's own defaults ask for 64 MiB and four threads, which on a 2 GB box shared with Postgres
# is a way to meet the OOM killer during a login storm. These cost about 25 ms here.
_hasher: Final = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# The sets this module has stopped hashing with but a stored hash may still carry. Empty today,
# because the parameters above have never moved.
#
# They matter the moment they do. A hash is upgraded on its owner's next successful login, so a
# raise leaves the outgoing set and the new one side by side in the table for as long as it takes
# every operator to sign in once, and during that time a verification against the older set costs
# less than one against the new. That difference is readable with a stopwatch from anywhere, and
# what it says is "this address belongs to an account that has not signed in since the parameters
# moved" — the account-enumeration oracle the throwaway hash exists to close, walking back in
# through the other door.
#
# So the unit of work is the whole ladder rather than its top rung. Every verification spends one
# argon2 operation per set in play — the stored hash pays for the set it was written with,
# throwaway hashes pay for the rest — and the total is identical for an unknown address, a dormant
# account and one that signed in this morning. Raising the parameters therefore means listing the
# outgoing set here in the same commit; a set is dropped from the list only once no stored hash
# can still carry it, which is what brings a login back down to one operation.
_RETIRED: Final[tuple[PasswordHasher, ...]] = ()

# Each rung with its own hash of 32 random bytes, discarded the moment this module is imported: no
# password matches them and nobody knows what would. One per set, because a stand-in that cost
# less than the thing it stands in for would not stand in for it at all.
_LADDER: Final[tuple[tuple[PasswordHasher, str], ...]] = tuple(
    (hasher, hasher.hash(secrets.token_urlsafe(32))) for hasher in (_hasher, *_RETIRED)
)


class PasswordPolicyError(ValueError):
    """A password the shared validator refuses. The message is written to be shown to a person."""


@dataclass(frozen=True, slots=True)
class PasswordVerification:
    """The outcome of checking a password against a stored hash."""

    ok: bool

    # True only when the password was correct and the stored hash was made with parameters this
    # module no longer uses. Reported rather than acted on: producing the replacement is a second
    # argon2 operation, and the caller is the only one that knows whether the rest of its checks
    # passed — a failure path that spent it would take measurably longer than the failure paths
    # that did not.
    outdated: bool = False


def _fold(password: str) -> str:
    """Fold a password to the form that is hashed.

    The stored hash is over the NFKC form, so every path folds the same way. A passphrase typed
    with a composing keyboard on one machine and a precomposed one on another is the same secret
    to the person typing it, and has to be the same string by the time it reaches argon2.
    """
    return unicodedata.normalize("NFKC", password)


def validate_password(password: str, *, email: str) -> str:
    """Apply the policy and return the folded password that should be hashed.

    Returning the folded value rather than a bare boolean is what keeps validation and hashing in
    agreement: the caller hashes exactly the string that was judged acceptable.

    There are no composition rules. Length is the only property that reliably costs an attacker
    anything, and a rule demanding a digit mostly produces a password ending in "1".
    """
    if len(password) > MAX_PASSWORD_LENGTH:
        # Checked before folding as well as after: NFKC can lengthen its input, and the ceiling is
        # there to bound the work, not only the result.
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")

    candidate = _fold(password)
    if len(candidate) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(candidate) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")

    # Compared casefolded, because "Administrator" as the password for administrator@ is the same
    # guess with one shift key held down.
    local_part = _fold(normalize_email(email)).partition("@")[0]
    if local_part and candidate.casefold() == local_part.casefold():
        raise PasswordPolicyError("Password must not be the account name.")

    return candidate


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return _hasher.hash(_fold(password))


def _matches(encoded: str, candidate: str) -> bool:
    """One argon2 verification, with every way of failing flattened into False.

    InvalidHashError means the column does not hold an argon2 hash at all. It is a wrong password
    as far as the answer goes; the difference belongs in a log line, not in a reply.
    """
    try:
        return _hasher.verify(encoded, candidate)
    except (VerificationError, InvalidHashError):
        return False


def _written_with(hasher: PasswordHasher, encoded: str) -> bool:
    """Whether this hash carries exactly the parameters of that rung of the ladder.

    A string that is not an argon2 hash belongs to no rung, so it skips nothing: it is checked
    against the stored value as well as against every stand-in, which costs a little more than a
    real hash would. Nothing valid takes that path, and paying more on it leaks nothing.
    """
    try:
        return not hasher.check_needs_rehash(encoded)
    except InvalidHashError:
        return False


def _verify_at_every_parameter_set(candidate: str, stored: str | None) -> bool:
    """Spend one verification per accepted parameter set, and report whether `stored` matched.

    The stored hash pays for the rung it was written with; every other rung is paid for with its
    throwaway hash. An unknown address has no stored hash and so pays for all of them, which is
    what makes "no such account" cost exactly what "wrong password" costs — whichever rung that
    account's hash happens to be sitting on today.
    """
    for hasher, dummy in _LADDER:
        if stored is None or not _written_with(hasher, stored):
            _matches(dummy, candidate)
    return stored is not None and _matches(stored, candidate)


def verify_password(password: str, password_hash: str) -> PasswordVerification:
    """Check a password against a stored hash, and say whether that hash should be replaced."""
    if len(password) > MAX_PASSWORD_LENGTH:
        # Refused without folding or hashing. No stored password can be this long, so an attacker
        # learns nothing from the shortcut and the CPU is spared the work.
        return PasswordVerification(ok=False)

    candidate = _fold(password)
    if not _verify_at_every_parameter_set(candidate, password_hash):
        return PasswordVerification(ok=False)
    return PasswordVerification(ok=True, outdated=not _written_with(_hasher, password_hash))


def verify_dummy_password(password: str) -> None:
    """Spend one full verification and learn nothing. Called when no account matched the address.

    The result is deliberately discarded: this exists so that the failure path with no user takes
    the same time as the failure path with one — including the shortcut on an overlong password,
    which `verify_password` takes too.
    """
    if len(password) > MAX_PASSWORD_LENGTH:
        return
    _verify_at_every_parameter_set(_fold(password), None)
