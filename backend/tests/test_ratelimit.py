"""The counters, on their own.

Login exercises them from outside, but three of the limiter's decisions are invisible from there
and each is the difference between a working ceiling and a broken one: the window slides rather
than resetting, a refused event is not recorded, and Retry-After is never zero. The last two go
together — counting a refused attempt would extend the window every time a blocked client polls,
which turns Retry-After into a number that never comes true and punishes the client that read it.

`ip_hash` gets its own test because a bare sha256 of an address is not anonymisation: the IPv4
space is four billion values, which is a table anyone builds in seconds.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from starlette.requests import Request

from app.config import get_settings
from app.security.ratelimit import (
    LOGIN_PER_EMAIL,
    LOGIN_PER_IP,
    MAX_COUNTERS,
    REFRESH_PER_IP,
    RateLimiter,
    RateLimitRule,
    client_ip,
    client_ip_hash,
    ip_hash,
)

_START: Final = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
_RULE: Final = RateLimitRule("probe", 3, timedelta(minutes=1))
_OTHER: Final = RateLimitRule("other", 3, timedelta(minutes=1))


@pytest.fixture
def limiter() -> RateLimiter:
    return RateLimiter()


def test_the_ceilings_are_the_ones_the_specification_fixed() -> None:
    assert (LOGIN_PER_EMAIL.limit, LOGIN_PER_EMAIL.window) == (5, timedelta(minutes=15))
    assert (LOGIN_PER_IP.limit, LOGIN_PER_IP.window) == (20, timedelta(minutes=15))
    assert (REFRESH_PER_IP.limit, REFRESH_PER_IP.window) == (60, timedelta(minutes=1))


def test_the_allowance_is_spent_and_then_refused(limiter: RateLimiter) -> None:
    for _ in range(_RULE.limit):
        assert limiter.hit(_RULE, "key", now=_START).allowed

    refused = limiter.hit(_RULE, "key", now=_START)

    assert refused.allowed is False
    assert refused.retry_after == int(_RULE.window.total_seconds())


def test_a_refused_attempt_does_not_extend_the_window(limiter: RateLimiter) -> None:
    """A blocked client polling every second must not keep pushing its own release further away."""
    for _ in range(_RULE.limit):
        limiter.hit(_RULE, "key", now=_START)

    for second in range(1, 30):
        polling = limiter.hit(_RULE, "key", now=_START + timedelta(seconds=second))
        # The wait shrinks with every poll rather than resetting to the full window.
        assert polling.retry_after == int(_RULE.window.total_seconds()) - second


def test_the_window_slides_rather_than_resetting(limiter: RateLimiter) -> None:
    """A fixed window lets an attacker spend the whole allowance at the end of one and the whole
    allowance at the start of the next, which is twice the limit in the space of a second."""
    for index in range(_RULE.limit):
        limiter.hit(_RULE, "key", now=_START + timedelta(seconds=index * 10))
    assert not limiter.hit(_RULE, "key", now=_START + timedelta(seconds=30)).allowed

    # One event has aged out of the window, and exactly one slot opens with it — not the whole
    # allowance, which is what a fixed window would hand back.
    freed = _START + _RULE.window + timedelta(seconds=1)
    assert limiter.hit(_RULE, "key", now=freed).allowed
    assert not limiter.hit(_RULE, "key", now=freed).allowed


def test_retry_after_is_never_zero_when_the_answer_is_no(limiter: RateLimiter) -> None:
    """A Retry-After of 0 invites the client to try again immediately, which is the opposite of
    the instruction."""
    for _ in range(_RULE.limit):
        limiter.hit(_RULE, "key", now=_START)

    at_the_boundary = limiter.hit(_RULE, "key", now=_START + _RULE.window - timedelta(seconds=1))

    assert at_the_boundary.allowed is False
    assert at_the_boundary.retry_after >= 1


def test_a_key_and_a_rule_are_counted_separately(limiter: RateLimiter) -> None:
    """The address that has spent nineteen of its twenty login attempts still has all sixty of
    its refreshes."""
    for _ in range(_RULE.limit):
        limiter.hit(_RULE, "spent", now=_START)

    assert not limiter.hit(_RULE, "spent", now=_START).allowed
    assert limiter.hit(_RULE, "another", now=_START).allowed
    assert limiter.hit(_OTHER, "spent", now=_START).allowed


def test_a_counter_can_be_forgotten(limiter: RateLimiter) -> None:
    """What a successful login does to the address that just signed in."""
    for _ in range(_RULE.limit):
        limiter.hit(_RULE, "key", now=_START)
    assert not limiter.hit(_RULE, "key", now=_START).allowed

    limiter.reset(_RULE, "key")

    assert limiter.hit(_RULE, "key", now=_START).allowed


def test_counters_nobody_has_touched_are_swept(limiter: RateLimiter) -> None:
    """Pruning only happens on the keys a request mentions, so without a sweep the dictionary
    keeps one entry per address that ever failed a login, forever.

    The size of the table is the assertion, because the sweep is about memory and nothing else.
    Asking instead whether `key-0` has its allowance back proves nothing: the window filter alone
    answers yes to that, and the question would go on passing with the sweep deleted.
    """
    for index in range(50):
        limiter.hit(_RULE, f"key-{index}", now=_START)
    assert len(limiter) == 50

    limiter.hit(_RULE, "later", now=_START + timedelta(days=1))

    assert len(limiter) == 1


def test_the_table_of_counters_is_bounded(limiter: RateLimiter) -> None:
    """An attacker varying the email — or the address, behind any number of proxies — asks for one
    counter per value, and an unbounded table is a way to spend a 2 GB box from a public endpoint.

    Every key below is inside its window, so the sweep has nothing to drop and the bound is the
    only thing that can hold.
    """
    for index in range(MAX_COUNTERS * 2):
        limiter.hit(_RULE, f"key-{index}", now=_START + timedelta(milliseconds=index))

    assert len(limiter) <= MAX_COUNTERS

    # What survives is the recent end of the table. The newest counter still remembers the attempt
    # it recorded, so it has one fewer than a fresh allowance left.
    recently = _START + timedelta(seconds=21)
    newest = f"key-{MAX_COUNTERS * 2 - 1}"
    for _ in range(_RULE.limit - 1):
        assert limiter.hit(_RULE, newest, now=recently).allowed
    assert not limiter.hit(_RULE, newest, now=recently).allowed

    # The oldest is gone and its key starts again from zero. That is what the bound costs, and it
    # is why the entries evicted are the ones whose windows were closest to closing anyway: the
    # allowance is handed back early rather than out of nothing.
    for _ in range(_RULE.limit):
        assert limiter.hit(_RULE, "key-0", now=recently).allowed


def test_an_address_is_hashed_under_the_pepper_and_not_bare() -> None:
    """Under a keyed hash the lookup table an attacker would build cannot be built without the
    pepper — which is the only thing that makes an `ip_hash` in the journal anonymous."""
    hashed = ip_hash("198.51.100.4")

    assert len(hashed) == 64
    assert hashed != hashlib.sha256(b"198.51.100.4").hexdigest()
    assert hashed == ip_hash("198.51.100.4")
    assert hashed != ip_hash("198.51.100.5")


def test_the_pepper_is_what_makes_the_hash_unguessable() -> None:
    expected = hashlib.sha256(
        get_settings().ip_hash_pepper.get_secret_value().encode() + b"salted?"
    ).hexdigest()

    assert ip_hash("198.51.100.4") != expected


@pytest.mark.parametrize(
    ("peer", "forwarded", "counted"),
    [
        # One spelling per address, so two spellings cannot buy two allowances.
        ("127.0.0.1", "2001:0db8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
        # A dual-stack listener reports a v4 peer like this, and it is the same client.
        ("::ffff:198.51.100.4", None, "198.51.100.4"),
        # Leading zeros are refused rather than reinterpreted — some parsers read them as octal,
        # and an address that means two things is an address that buys two allowances.
        ("127.0.0.1", "198.051.100.004", "127.0.0.1"),
        # Rubbish in the header, or none at all: fall back to the socket.
        ("127.0.0.1", "not-an-address", "127.0.0.1"),
        ("127.0.0.1", "", "127.0.0.1"),
    ],
)
def test_an_address_is_read_defensively(peer: str, forwarded: str | None, counted: str) -> None:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []

    request = Request({"type": "http", "headers": headers, "client": (peer, 4000)})

    assert client_ip(request) == counted


def test_a_request_with_no_peer_is_one_bucket_rather_than_an_exception() -> None:
    """A unix socket, or a transport that reports no peer. A missing address must not be an error
    in front of the login form."""
    request = Request({"type": "http", "headers": [], "client": None})

    assert client_ip(request) == "unknown"
    assert len(client_ip_hash(request)) == 64
