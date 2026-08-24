"""The wire format.

The API speaks camelCase and Python speaks snake_case, and the translation happens exactly here
— in the alias generator on `ApiModel` — for responses and request bodies alike. Doing it per
field is how one endpoint ends up answering `last_login_at` while the rest answer `lastLoginAt`.

These models are also the boundary that `password_hash` and `role_id` do not cross. A response
carries the fields declared below and nothing else, so serialising an ORM row cannot leak a
column by accident.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Base for everything that crosses the wire."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        # Python code constructs these by field name; the wire uses the alias. Without this,
        # `TokenResponse(access_token=...)` would be a validation error in our own routes.
        populate_by_name=True,
        # Lets a route hand an ORM row straight to `model_validate`. Only declared fields are
        # read, which is the other half of why a hash cannot escape this way.
        from_attributes=True,
        # A request body with a key nobody asked for is a client that believes something untrue
        # about this API. Saying so is more useful than ignoring it.
        extra="forbid",
    )


class HealthResponse(ApiModel):
    """GET /api/health."""

    # "degraded" is answered with 503: the process is up, its database is not.
    status: Literal["ok", "degraded"]
    version: str
    commit: str
    db: bool


class LoginRequest(ApiModel):
    """POST /api/auth/login."""

    email: str = Field(min_length=1, max_length=320)

    # The upper bound is the password policy's, and it is load-bearing rather than cosmetic:
    # argon2 hashes whatever it is given, so an unbounded field is a way to spend the box's only
    # CPU from an unauthenticated endpoint. Beyond non-emptiness there is nothing else to check
    # here — the policy applies where passwords are set, not where they are typed.
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(ApiModel):
    """The answer to POST /api/auth/login and POST /api/auth/refresh.

    Both mint an access token under identical terms, and the refresh token itself is never in a
    body — it is in the cookie, where script cannot read it.
    """

    access_token: str

    # Seconds, not an instant: the client schedules its refresh off its own clock, and a browser
    # whose clock is wrong would otherwise either refresh in a loop or never refresh at all.
    expires_in: int


class RoleSummary(ApiModel):
    """A role as the panel displays it. `id` stays inside the process."""

    code: str
    name: str


class UserProfile(ApiModel):
    """The subject of the session, as GET /api/auth/me reports it."""

    id: uuid.UUID
    email: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class MeResponse(ApiModel):
    """GET /api/auth/me."""

    user: UserProfile
    role: RoleSummary

    # Flat, sorted and deduplicated by the route. Permissions are read from the database on every
    # request and are deliberately absent from the access token: a role edited at 10:00 must not
    # keep granting what it granted at 09:55 until the token expires.
    permissions: list[str]

    kind: Literal["user", "demo"]

    # Null for a session belonging to a user. Nothing in this service assigns a world.
    world_id: str | None = None


class UserSummary(UserProfile):
    """A row of GET /api/users: the profile, plus the role it was granted."""

    role: RoleSummary


class PageParams(ApiModel):
    """The query string of a paginated collection, e.g. `?page=2&pageSize=50`.

    A model rather than two `Query()` defaults so the camelCase aliasing is the same rule as
    everywhere else, and so the ceiling on `pageSize` cannot be forgotten by the next collection.
    """

    # Both bounded at both ends. `page` needs a ceiling for the same reason `pageSize` needs one,
    # and for one more: the offset it computes is sent to Postgres, whose OFFSET is a bigint, so
    # `?page=99999999999999999999` is otherwise a 500 about an overflowing query rather than a 422
    # naming the parameter that was wrong. A million pages is far past anything a pager reaches —
    # a collection that deep is answered by a filter, not by paging to it.
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=25, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class UserListResponse(ApiModel):
    """GET /api/users."""

    items: list[UserSummary]
    total: int
    page: int
    page_size: int
