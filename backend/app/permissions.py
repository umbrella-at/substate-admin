"""The permission catalogue and the four system roles.

This file is the source of truth, not a row in Postgres: `substate-admin sync-permissions`
force-syncs the database to what is written here, and it runs on every deploy. Adding a
permission means adding it to `PermissionCode` and to `PERMISSIONS`, which makes it a type error
everywhere a role's grant list forgot about it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, cast, get_args

# A Literal rather than an enum so that RequirePermission("users.read") type-checks at the call
# site and RequirePermission("user.read") does not. A typo is caught by mypy in CI instead of by
# a 403 that nobody sees until a reviewer clicks the wrong tab.
PermissionCode = Literal[
    "subscribers.read",
    "subscribers.write",
    "plans.read",
    "plans.write",
    "promo.read",
    "promo.write",
    "referrals.read",
    "referrals.write",
    "analytics.read",
    "audit.read",
    "users.read",
    "users.write",
    "demo.control",
]

RoleCode = Literal["admin", "support", "viewer", "demo"]

PERMISSIONS: Final[Mapping[PermissionCode, str]] = MappingProxyType(
    {
        "subscribers.read": "View subscribers and the state of their subscriptions.",
        "subscribers.write": "Create, modify and cancel subscriptions.",
        "plans.read": "View subscription plans.",
        "plans.write": "Create and modify subscription plans.",
        "promo.read": "View promotional codes and their redemptions.",
        "promo.write": "Create, modify and revoke promotional codes.",
        "referrals.read": "View referral programmes and their results.",
        "referrals.write": "Create and modify referral programmes.",
        "analytics.read": "View aggregate analytics.",
        "audit.read": "Read the record of administrative actions.",
        "users.read": "View the panel's own users and roles.",
        "users.write": "Create, modify and deactivate the panel's own users and roles.",
        "demo.control": "Drive the time machine in a demo world.",
    }
)

PERMISSION_CODES: Final[tuple[PermissionCode, ...]] = tuple(PERMISSIONS)

# The Literal and the descriptions are two lists that have to say the same thing, and mypy only
# checks one direction of that — a key it has never heard of is an error, a key nobody wrote is
# not. This is the other direction, and it fails at import rather than at the first 403.
if set(PERMISSION_CODES) != set(get_args(PermissionCode)):
    raise RuntimeError("PERMISSIONS and PermissionCode disagree about which codes exist")

_ALL: Final[frozenset[PermissionCode]] = frozenset(PERMISSION_CODES)
_READ: Final[frozenset[PermissionCode]] = frozenset(
    code for code in PERMISSION_CODES if code.endswith(".read")
)

# Support answers tickets: it changes what a subscriber has and hands out a promo code, and it
# reads everything else.
_SUPPORT_WRITES: Final[frozenset[PermissionCode]] = frozenset({"subscribers.write", "promo.write"})

# A viewer is for showing the panel to someone. It sees the product, not who administers it and
# not what they did.
_VIEWER_DENIED: Final[frozenset[PermissionCode]] = frozenset({"audit.read", "users.read"})

# The demo role drives everything it can see, including the time machine, and cannot create or
# disable an account — the one action whose effects outlive the demo.
#
# It cannot read the panel's own users either, which is one code narrower than the "everything
# except users.write" the specification writes. A demo session is handed to whoever clicks the
# button on the login page, and `users.read` would hand that stranger the email address of every
# real operator. The narrowing costs nothing today because nothing mints a demo session yet; once
# something does, it is a visible removal of an ability people have seen.
_DEMO_DENIED: Final[frozenset[PermissionCode]] = frozenset({"users.write", "users.read"})


@dataclass(frozen=True, slots=True)
class SystemRole:
    """A role this application defines and keeps in sync. Custom roles are never touched."""

    code: RoleCode
    name: str
    permissions: frozenset[PermissionCode]


SYSTEM_ROLES: Final[Mapping[RoleCode, SystemRole]] = MappingProxyType(
    {
        "admin": SystemRole("admin", "Administrator", _ALL),
        "support": SystemRole("support", "Support", _READ | _SUPPORT_WRITES),
        "viewer": SystemRole("viewer", "Viewer", _READ - _VIEWER_DENIED),
        "demo": SystemRole("demo", "Demo", _ALL - _DEMO_DENIED),
    }
)

ROLE_CODES: Final[tuple[RoleCode, ...]] = tuple(SYSTEM_ROLES)


def system_role(code: str) -> SystemRole | None:
    """Look up a system role by an untrusted string — a CLI flag, a column read back from a row.

    Returns None for a custom role or a typo, which is why the caller gets an Optional instead of
    a KeyError: neither is exceptional, and both need the same "that is not a system role" reply.
    """
    return SYSTEM_ROLES.get(cast(RoleCode, code))
