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

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel
from substate import State

from app.subscribers.query import Cohort, SubscriberQuery, parse_sort


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


class WorldHealth(ApiModel):
    """Whether the demonstration has a world behind it.

    Reported beside the database rather than folded into `status`, because the two failures are
    not the same kind. A database that does not answer means the panel cannot serve; a world that
    failed to seed means the shop window is empty while signing in, permissions and every
    operator screen keep working. Answering 503 for the second would make a deploy roll itself
    back over a cosmetic problem.
    """

    seeded: bool
    subscribers: int
    events: int


class HealthResponse(ApiModel):
    """GET /api/health."""

    # "degraded" is answered with 503: the process is up, its database is not.
    status: Literal["ok", "degraded"]
    version: str
    commit: str
    db: bool
    world: WorldHealth


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


class SubscriberSummary(ApiModel):
    """One row of the subscriber table.

    The date fields are a discriminated view rather than a bag of optionals: `trialEndsAt` is set
    only in TRIAL, `graceEndsAt` only in GRACE. The frontend's tagged union is built on that, so a
    field that is present in a state it does not belong to would be a type that lies.
    """

    user_id: str
    display_name: str
    state: Literal["trial", "active", "grace", "expired", "cancelled"]
    plan_id: str
    expires_at: datetime | None = None
    trial_ends_at: datetime | None = None
    grace_ends_at: datetime | None = None
    last_active_at: datetime | None = None
    promo_code: str | None = None
    referrer_id: str | None = None


class SubscriberPage(ApiModel):
    """GET /api/subscribers. The shape the specification fixes: items, total, page, pageSize."""

    items: list[SubscriberSummary]
    total: int
    page: int
    page_size: int


class PlanSummary(ApiModel):
    """The plan a subscription is on, as the card shows it."""

    id: str
    price: int
    currency: str
    period_unit: Literal["days", "months"]
    period_count: int
    trial_days: int
    grace_days: int


class SubscriberDetail(ApiModel):
    """GET /api/subscribers/{id}: the subscription, its plan, its promo code and its referrer."""

    subscriber: SubscriberSummary
    plan: PlanSummary
    promo_code: str | None = None
    referrer_id: str | None = None
    referral_program_id: str | None = None


class SubscriberQueryParams(ApiModel):
    """The query string of GET /api/subscribers, and the whole of the table's state.

    Every field here is also a URL parameter on the frontend, deliberately: refreshing the page
    restores the view and the link can be sent to somebody else. A table whose state lives only in
    component memory is a table you cannot point at.
    """

    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=25, ge=1, le=100)
    sort: str = "-lastActiveAt"
    state: list[Literal["trial", "active", "grace", "expired", "cancelled"]] = Field(
        default_factory=list
    )
    plan_id: str | None = None
    cohort: Literal["in-grace", "quiet", "trial-ending", "cancelled-still-active"] | None = None
    q: str | None = Field(default=None, max_length=200)

    @field_validator("sort")
    @classmethod
    def _known_sort(cls, value: str) -> str:
        """An unknown sort field is refused rather than ignored.

        Falling back to a default would answer a different question than the one asked and say
        nothing about it — the table would look sorted and be sorted by something else.
        """
        try:
            parse_sort(value)
        except ValueError as unknown:
            raise ValueError(f"unknown sort field: {value}") from unknown
        return value

    def to_query(self) -> SubscriberQuery:
        """The query-string shape turned into the one the reader understands."""
        return SubscriberQuery(
            page=self.page,
            page_size=self.page_size,
            sort=self.sort,
            states=tuple(State(s) for s in self.state),
            plan_id=self.plan_id,
            cohort=Cohort(self.cohort) if self.cohort else None,
            search=self.q,
        )
