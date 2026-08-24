"""In-memory rate limiting, the client's address, and the pepper that hides it.

The counters are a dictionary in this process. They are lost on restart and they are not shared,
which is why the systemd unit pins `--workers 1`: a second worker would quietly double every
limit here. For a panel with a handful of operators that is the right trade — the alternative is
a Redis on a box that has 2 GB of RAM and one job. Both halves of a counter's key are chosen by
whoever is asking, so the dictionary is capped and evicts: see `MAX_COUNTERS`.

Only the event loop touches these structures, so there is no lock — and that is exactly why
deciding and recording are one call rather than two. A caller that reads a counter and writes to
it after an await gets no protection from the single thread: the requests that arrive together
have all read it before any of them has written.
"""

import hashlib
import hmac
import ipaddress
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from fastapi import Request

from app.config import get_settings

# uvicorn always reports a peer for a TCP connection. This stands in for the cases that are not
# one — a unix socket, a test client with no transport — so that a missing address is one bucket
# rather than an exception in front of the login form.
_UNKNOWN_IP: Final = "unknown"

_FORWARDED_FOR: Final = "x-forwarded-for"


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """A ceiling and the window it applies over.

    `name` namespaces the counter, so that the address that has spent nineteen of its twenty login
    attempts still has all sixty of its refreshes.
    """

    name: str
    limit: int
    window: timedelta


# Five failures against one address is somebody guessing at one account. The counter is cleared by
# a successful login, so a person who mistypes their password four times and then gets it right
# starts again from zero.
LOGIN_PER_EMAIL: Final = RateLimitRule("login_email", 5, timedelta(minutes=15))

# Counted per attempt rather than per failure, and never cleared. Twenty logins in a quarter of an
# hour from one address is a script whether or not it is guessing correctly, and an attacker
# working through a list of addresses never fails against the same one twice.
LOGIN_PER_IP: Final = RateLimitRule("login_ip", 20, timedelta(minutes=15))

# Loose on purpose. A tab that wakes up, a reload and a couple of retries all refresh at once, and
# this is a ceiling on a runaway client rather than a security boundary — the token itself is the
# credential, and presenting a bad one twice already ends the session.
REFRESH_PER_IP: Final = RateLimitRule("refresh_ip", 60, timedelta(minutes=1))

_ALL_RULES: Final = (LOGIN_PER_EMAIL, LOGIN_PER_IP, REFRESH_PER_IP)
_LONGEST_WINDOW: Final = max(rule.window for rule in _ALL_RULES)
_SWEEP_INTERVAL: Final = timedelta(minutes=5)

# The table is one entry per (rule, key) anybody has touched, and both halves of a key are chosen
# by whoever is asking: a new email or a new address behind a proxy is a new counter. Left
# unbounded that is a way to spend this box's two gigabytes from an unauthenticated endpoint, and
# the restart that follows is worse than the memory — it wipes every counter there is, which turns
# "make the panel run out of RAM" into "clear the ceiling I have been pushing against".
#
# Ten thousand counters of at most sixty timestamps each (the refresh rule, the largest of the
# three) is on the order of forty megabytes: enough headroom that no plausible operator ever meets
# it, small enough that this process loses the argument with the OOM killer before Postgres does.
MAX_COUNTERS: Final = 10_000

# Evicted a batch at a time rather than one entry per request. Finding the oldest entries is a
# scan of the whole table, and paying for one on every request while the table is full is how a
# rate limiter becomes the denial of service it was put there to prevent.
_EVICTION_BATCH: Final = MAX_COUNTERS // 10


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Whether one more event is within a rule, and how long until it would be."""

    allowed: bool

    # Whole seconds, for the Retry-After header. Zero when allowed, never zero when not: a
    # Retry-After of 0 invites the client to try again immediately, which is the opposite of the
    # instruction.
    retry_after: int


class RateLimiter:
    """A sliding-window counter per (rule, key).

    Sliding rather than fixed: a fixed window lets an attacker spend the whole allowance at the
    end of one window and the whole allowance at the start of the next, which is twice the limit
    in the space of a second.
    """

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[datetime]] = {}
        self._swept_at: datetime | None = None

    def __len__(self) -> int:
        """How many counters this process is holding — the bound in `MAX_COUNTERS`, made visible.

        It exists so a test can assert the memory bound itself rather than a symptom of it: an
        assertion about one key's allowance is satisfied by the window filter alone and would pass
        with the sweep below deleted.
        """
        return len(self._hits)

    def hit(self, rule: RateLimitRule, key: str, *, now: datetime) -> RateLimitDecision:
        """Record one event, unless it is over the ceiling, and report the decision.

        Deciding and recording are one step on purpose. Anything that reads the counter and writes
        to it later leaves an await in between, and requests that arrive together then all read a
        counter none of them has written to yet — which is a ceiling that holds against a serial
        attacker and against nobody else.

        A refused event is not recorded. Counting it would extend the window every time a blocked
        client polls, which turns Retry-After into a number that never comes true and punishes the
        honest client who read it.
        """
        self._sweep(now)
        hits = self._live(rule, key, now)
        decision = self._decide(rule, hits, now)
        if decision.allowed:
            if not hits:
                # An empty deque means the table is not holding this key, which is the only moment
                # it can grow.
                self._make_room(now)
            hits.append(now)
            self._hits[(rule.name, key)] = hits
        return decision

    def reset(self, rule: RateLimitRule, key: str) -> None:
        """Forget a counter. A successful login calls this for the address that just signed in."""
        self._hits.pop((rule.name, key), None)

    def clear(self) -> None:
        """Drop every counter. Between tests, and nowhere else."""
        self._hits.clear()
        self._swept_at = None

    def _decide(
        self, rule: RateLimitRule, hits: deque[datetime], now: datetime
    ) -> RateLimitDecision:
        if len(hits) < rule.limit:
            return RateLimitDecision(allowed=True, retry_after=0)
        # The oldest event still in the window is the one whose expiry frees the next slot.
        frees_at = hits[0] + rule.window
        return RateLimitDecision(
            allowed=False, retry_after=max(1, math.ceil((frees_at - now).total_seconds()))
        )

    def _live(self, rule: RateLimitRule, key: str, now: datetime) -> deque[datetime]:
        """The events for this key that are still inside the window, pruned in place."""
        hits = self._hits.get((rule.name, key))
        if hits is None:
            return deque()
        cutoff = now - rule.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            del self._hits[(rule.name, key)]
        return hits

    def _make_room(self, now: datetime) -> None:
        """Hold the table at `MAX_COUNTERS`, and say which counter pays when it is full.

        A sweep first, because an entry nobody has touched for longer than the longest window is
        free to drop. If that was not enough, the entries whose most recent event is oldest go.
        Evicting a counter does hand its key a fresh allowance, and that is the cost of the bound:
        the entries chosen are the ones whose windows were closest to closing anyway, so the
        allowance is handed back early rather than granted out of nothing — and the alternative,
        an unbounded table, hands every counter in the process back at once when the box runs out
        of memory.
        """
        if len(self._hits) < MAX_COUNTERS:
            return
        self._sweep(now, force=True)
        if len(self._hits) < MAX_COUNTERS:
            return
        # Every stored deque holds at least one event: `_live` deletes a key it has emptied, and
        # `hit` only writes back a deque it is about to append to.
        doomed = sorted(self._hits, key=lambda key: self._hits[key][-1])[:_EVICTION_BATCH]
        for key in doomed:
            del self._hits[key]

    def _sweep(self, now: datetime, *, force: bool = False) -> None:
        """Drop counters nobody has touched for longer than the longest window.

        Pruning only happens on the keys a request mentions, so without this the dictionary keeps
        one entry per address that ever failed a login, forever. A pass every five minutes is
        cheap and needs no background task to run it; `force` is what `_make_room` uses when five
        minutes is too long to wait because the table is already full.
        """
        if not force and self._swept_at is not None and now - self._swept_at < _SWEEP_INTERVAL:
            return
        self._swept_at = now
        cutoff = now - _LONGEST_WINDOW
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]


_limiter: Final = RateLimiter()


def get_limiter() -> RateLimiter:
    """The counters for this process."""
    return _limiter


def ip_hash(ip: str) -> str:
    """The form an address is allowed to exist in outside this module.

    HMAC and not a bare sha256: the IPv4 space is four billion addresses, which is a table anyone
    can build in seconds and then use to read every "anonymised" address in the journal. Under a
    keyed hash that table cannot be built without the pepper.
    """
    pepper = get_settings().ip_hash_pepper.get_secret_value().encode("utf-8")
    return hmac.new(pepper, ip.encode("utf-8"), hashlib.sha256).hexdigest()


def client_ip_hash(request: Request) -> str:
    """The bucket key and log field for whoever sent this request.

    Routes call this rather than `client_ip`, so the raw address is never bound to a name that
    could end up in a log line or an error message.
    """
    return ip_hash(client_ip(request))


def client_ip(request: Request) -> str:
    """The address this request actually came from.

    X-Forwarded-For is a header the client can write. It is trusted only when the peer on the
    other end of the socket is loopback, which here means Caddy on the same machine — uvicorn runs
    with `--forwarded-allow-ips=127.0.0.1` for the same reason. Caddy *sets* the header to the
    real peer rather than appending to it, so the last hop is the only hop; taking the last one is
    what stops a client from sending "1.2.3.4, 5.6.7.8" and choosing its own rate-limit bucket.
    """
    peer = request.client.host if request.client is not None else None
    forwarded = request.headers.get(_FORWARDED_FOR)
    if forwarded and peer is not None and _is_loopback(peer):
        hop = _canonical(forwarded.rsplit(",", 1)[-1].strip())
        if hop is not None:
            return hop
    return (_canonical(peer) if peer is not None else None) or _UNKNOWN_IP


def _parse(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse an address, unwrapping the IPv4-mapped form.

    A dual-stack listener reports a v4 peer as ::ffff:127.0.0.1, and that value is not
    `is_loopback` and does not equal the same address written plainly. Unwrapping it here is what
    keeps one client in one bucket and keeps the proxy recognisable as local.
    """
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _canonical(value: str) -> str | None:
    """One spelling per address, so two spellings cannot buy two allowances."""
    address = _parse(value)
    return str(address) if address is not None else None


def _is_loopback(value: str) -> bool:
    address = _parse(value)
    return address is not None and address.is_loopback
