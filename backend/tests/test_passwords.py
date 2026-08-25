"""The one password policy, and the hashing underneath it.

Length is the only rule, so the boundaries are the whole specification and each of the four is
asserted from both sides. The NFKC cases are the ones worth having: folding changes how long a
string is, and a validator that measured before folding while the hasher hashed after would accept
a password the person cannot type again.
"""

import unicodedata
from typing import Final

import pytest
from argon2 import PasswordHasher, Type, extract_parameters

from app.security import passwords
from app.security.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    validate_password,
    verify_dummy_password,
    verify_password,
)

_EMAIL: Final = "someone@example.com"

# "e" followed by a combining acute accent: two code points that NFKC folds into one. A password
# written with them is the shortest way to prove which form the policy measures.
_COMBINING: Final = "e\u0301"

_OUTDATED: Final = PasswordHasher(
    time_cost=1, memory_cost=8, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
)


def test_the_minimum_is_twelve_characters() -> None:
    with pytest.raises(PasswordPolicyError, match="at least 12"):
        validate_password("x" * (MIN_PASSWORD_LENGTH - 1), email=_EMAIL)

    assert validate_password("x" * MIN_PASSWORD_LENGTH, email=_EMAIL) == "x" * 12


def test_the_maximum_is_a_hundred_and_twenty_eight_characters() -> None:
    """Not cosmetic: argon2 reads its whole input, so an unbounded field is a way to spend the
    box's only CPU from an unauthenticated endpoint."""
    assert validate_password("x" * MAX_PASSWORD_LENGTH, email=_EMAIL) == "x" * 128

    with pytest.raises(PasswordPolicyError, match="at most 128"):
        validate_password("x" * (MAX_PASSWORD_LENGTH + 1), email=_EMAIL)


def test_length_is_measured_after_folding() -> None:
    """Twelve code points that NFKC turns into six characters is a six-character password."""
    typed = _COMBINING * 6
    assert len(typed) == 12

    with pytest.raises(PasswordPolicyError, match="at least 12"):
        validate_password(typed, email=_EMAIL)


def test_the_ceiling_is_applied_before_folding_as_well() -> None:
    """The maximum bounds the work, not only the result: a hundred and thirty code points are a
    hundred and thirty code points to normalise, whatever they fold down to."""
    typed = _COMBINING * 65
    assert len(typed) == 130
    assert len(unicodedata.normalize("NFKC", typed)) == 65

    with pytest.raises(PasswordPolicyError, match="at most 128"):
        validate_password(typed, email=_EMAIL)


def test_the_validator_returns_the_string_that_will_be_hashed() -> None:
    """Returning the folded value rather than a boolean is what keeps validation and hashing in
    agreement: the caller hashes exactly the string that was judged acceptable."""
    typed = _COMBINING * 12

    folded = validate_password(typed, email=_EMAIL)

    assert folded == unicodedata.normalize("NFKC", typed)
    assert len(folded) == 12


def test_the_two_spellings_of_one_passphrase_are_one_secret() -> None:
    """A composing keyboard on one machine and a precomposed one on another produce the same
    password as far as the person typing it is concerned."""
    stored = hash_password(_COMBINING * 12)

    assert verify_password(unicodedata.normalize("NFC", _COMBINING * 12), stored).ok


@pytest.mark.parametrize("password", ["administrator", "ADMINISTRATOR", "Administrator"])
def test_the_password_may_not_be_the_account_name(password: str) -> None:
    """`Administrator` as the password for administrator@ is the same guess, shift key held."""
    with pytest.raises(PasswordPolicyError, match="account name"):
        validate_password(password, email="Administrator@example.com")


def test_a_password_that_merely_contains_the_account_name_is_allowed() -> None:
    """Equal to it, not built from it. There are no composition rules, and this is not one by the
    back door."""
    assert validate_password("administrator-and-then-some", email="administrator@example.com")


def test_a_hash_round_trips_and_a_wrong_password_does_not() -> None:
    stored = hash_password("a-perfectly-good-password")

    assert verify_password("a-perfectly-good-password", stored).ok
    assert not verify_password("a-perfectly-good-passwerd", stored).ok


def test_two_hashes_of_one_password_differ() -> None:
    """Salted, so a stolen table says nothing about which two operators chose the same words."""
    assert hash_password("a-perfectly-good-password") != hash_password("a-perfectly-good-password")


def test_a_column_that_does_not_hold_an_argon2_hash_is_a_wrong_password() -> None:
    """The difference belongs in a log line, not in a reply."""
    assert not verify_password("a-perfectly-good-password", "not a hash at all").ok


def test_an_overlong_password_is_refused_without_being_hashed() -> None:
    """No stored password can be this long, so the shortcut tells an attacker nothing and spares
    the CPU the work."""
    stored = hash_password("a-perfectly-good-password")

    assert not verify_password("x" * (MAX_PASSWORD_LENGTH + 1), stored).ok


def test_a_hash_made_with_weaker_parameters_is_reported_for_replacement() -> None:
    """Reported rather than replaced here: producing the new hash is a second argon2 operation,
    and only the caller knows whether the rest of its checks passed. A verification that spent it
    would make one failure path measurably slower than the others."""
    stale = _OUTDATED.hash("a-perfectly-good-password")

    verification = verify_password("a-perfectly-good-password", stale)

    assert verification.ok
    assert verification.outdated
    # And the replacement the caller writes is one this module is content with.
    replaced = verify_password(
        "a-perfectly-good-password", hash_password("a-perfectly-good-password")
    )
    assert replaced.ok
    assert not replaced.outdated


def test_a_current_hash_is_left_alone() -> None:
    stored = hash_password("a-perfectly-good-password")

    assert not verify_password("a-perfectly-good-password", stored).outdated


def test_a_wrong_password_is_never_reported_as_outdated() -> None:
    """The caller writes the hash this flag asks for, and it can only produce one from a password
    that was right."""
    stale = _OUTDATED.hash("a-perfectly-good-password")

    verification = verify_password("a-perfectly-good-passwerd", stale)

    assert not verification.ok
    assert not verification.outdated


def test_the_work_is_the_same_whichever_parameters_a_stored_hash_carries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raising the parameters upgrades stored hashes one login at a time, so for a while the table
    holds both sets. If a comparison spent only what the hash in front of it cost, an account that
    had not signed in since the raise would answer faster than an unknown address — the same
    account-enumeration oracle the dummy hash exists to close, arriving from the other side.

    Counted rather than timed: the operations argon2 performs are what the stopwatch measures, and
    a test that measured milliseconds would fail on a busy machine instead of on a regression.
    """
    retired_dummy = _OUTDATED.hash("nobody knows this one either")
    monkeypatch.setattr(
        passwords,
        "_LADDER",
        ((passwords._hasher, hash_password("nor this one")), (_OUTDATED, retired_dummy)),
    )

    spent: list[int] = []
    real = passwords._matches

    def counted(encoded: str, candidate: str) -> bool:
        # The time cost names the parameter set, which is what has to be paid for exactly once.
        spent.append(extract_parameters(encoded).time_cost)
        return real(encoded, candidate)

    monkeypatch.setattr(passwords, "_matches", counted)

    dormant = _OUTDATED.hash("a-perfectly-good-password")
    current = hash_password("a-perfectly-good-password")

    costs = {}
    for name, stored in (("dormant", dormant), ("current", current)):
        spent.clear()
        assert verify_password("a-perfectly-good-password", stored).ok
        costs[name] = sorted(spent)
    spent.clear()
    verify_dummy_password("a-perfectly-good-password")
    costs["unknown"] = sorted(spent)

    assert costs["dormant"] == costs["current"] == costs["unknown"]
    # One verification per set, and neither set paid for twice.
    assert costs["unknown"] == sorted([_OUTDATED.time_cost, passwords._hasher.time_cost])


def test_the_dummy_verification_costs_a_real_one() -> None:
    """Login spends this when no account matched the address, so that "no such user" takes as long
    as "wrong password". It has no result by design: only its cost matters."""
    assert verify_dummy_password("anything at all") is None


def test_a_password_that_folding_lengthens_past_the_ceiling_is_refused() -> None:
    """NFKC can lengthen its input as well as shorten it — a ligature becomes two letters — so the
    ceiling is applied to the folded form too."""
    typed = "ﬁ" * 100
    assert len(typed) == 100
    assert len(unicodedata.normalize("NFKC", typed)) == 200

    with pytest.raises(PasswordPolicyError, match="at most 128"):
        validate_password(typed, email=_EMAIL)


def test_an_address_with_no_local_part_is_not_a_rule_about_the_empty_string() -> None:
    """The account-name rule compares against the part before the @. When there is nothing there,
    there is nothing to compare, and an empty password must not become the one forbidden value."""
    assert validate_password("a-perfectly-good-password", email="")
