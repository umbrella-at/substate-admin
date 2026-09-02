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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel
from substate import State

from app.audit import AuditAction
from app.errors import ErrorCode
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

    # Which world the panel is showing. Named rather than left for a client to assume: the audit
    # holds rows from worlds that no longer exist, and a screen deciding whether a row is about
    # the world on screen was otherwise comparing against a constant it had copied.
    id: str
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

    `accessUntil` sits alongside them rather than replacing them. It is the one of the three that
    is true in the state the row is in, which is what a table with a single date column has to
    show; the three stay because they are different questions and the subscriber card asks all of
    them separately.
    """

    user_id: str
    display_name: str
    state: Literal["trial", "active", "grace", "expired", "cancelled"]
    plan_id: str
    access_until: datetime | None = None
    expires_at: datetime | None = None
    trial_ends_at: datetime | None = None
    grace_ends_at: datetime | None = None
    cancelled_at: datetime | None = None
    # Not state-filtered: it is null unless a change is waiting, and the card has to show the
    # change it was just asked to schedule or the operation looks as though it did nothing.
    pending_plan_id: str | None = None
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


class ReferralProgramSummary(ApiModel):
    """A referral programme, as the control that assigns one describes it.

    `percent` and `accrual` are the two knobs the engine gives a programme, and they are here so
    the choice reads as a choice — "30% on every payment" rather than an id somebody has to know.
    """

    id: str
    percent: int
    accrual: Literal["first_payment_only", "every_payment"]


class SubscriberDetail(ApiModel):
    """GET /api/subscribers/{id}: the subscription, its plan, its promo code and its referrer."""

    subscriber: SubscriberSummary
    plan: PlanSummary
    promo_code: str | None = None

    # Who brought this subscriber in, and on what terms that person is paid. Two facts about
    # somebody else, and neither is what this subscriber earns.
    referrer_id: str | None = None
    referrer_program_id: str | None = None

    # What THIS subscriber earns when they bring somebody in. Null means nobody assigned them one,
    # NOT that they are paid nothing: the engine falls back to the world's default programme, which
    # in the base world pays ten per cent on a first payment.
    referral_program_id: str | None = None

    # On the card and not on the table row, because only the card asks the question it answers:
    # starting a new subscription grants a fresh trial when this is null and ends access today
    # when it is not, and a confirmation that cannot tell the two apart has to guess.
    trial_started_at: datetime | None = None


class EngineEvent(ApiModel):
    """One thing `substate` emitted.

    `payload` is whatever the event carried beyond the two fields above it, and its keys differ
    per type — `payment.recorded` has an amount, `subscription.expired` has a reason. It is typed
    as an open object on purpose: naming a union of thirteen payload shapes in the schema would
    make every new event in a later engine a breaking change to this API.
    """

    type: str
    occurred_at: datetime
    payload: dict[str, Any]


class SubscriberEvent(EngineEvent):
    """One entry of a subscriber's feed: an event, plus the row it was written as."""

    id: str


class SubscriberEventPage(ApiModel):
    """GET /api/subscribers/{id}/events, in the shape every collection here answers with."""

    items: list[SubscriberEvent]
    total: int
    page: int
    page_size: int


class SubscribeRequest(ApiModel):
    """POST /api/subscribers/{id}/subscribe.

    No `referrerId`. Every subscriber this route can reach already exists, and the engine writes
    the referrer once when the record is created and ignores the argument in silence ever after —
    a control that can never take effect is a control that lies about what it does.
    """

    plan_id: str = Field(min_length=1, max_length=64)
    promo_code: str | None = Field(default=None, min_length=1, max_length=64)


class ChangePlanRequest(ApiModel):
    """POST /api/subscribers/{id}/change-plan. Naming the current plan cancels a pending change."""

    plan_id: str = Field(min_length=1, max_length=64)


class RedeemRequest(ApiModel):
    """POST /api/subscribers/{id}/redeem."""

    promo_code: str = Field(min_length=1, max_length=64)


class PaymentRequest(ApiModel):
    """POST /api/subscribers/{id}/payment.

    Minor units, like every amount the engine handles: 500 is $5.00. The provider is the panel and
    is not a field — money recorded here did not come from a gateway, and offering the operator a
    provider name would invite them to claim it did.
    """

    amount: int = Field(ge=1, le=100_000_000)

    # The engine is idempotent on (provider, externalId), so a reference typed twice records one
    # payment. Optional, and a fresh one is minted when it is absent: without that, a double press
    # is a second payment, and with it forced, a payment nobody has a reference for cannot be
    # recorded at all.
    reference: str | None = Field(default=None, min_length=1, max_length=128)


class AssignProgramRequest(ApiModel):
    """POST /api/subscribers/{id}/referral-program."""

    program_id: str = Field(min_length=1, max_length=64)


class SubscriberOperationResult(ApiModel):
    """What one operation did: the card as it now stands, and what the engine emitted doing it.

    The events are in the answer because three of the payment outcomes are events rather than
    refusals — duplicate, underpaid, unmatched — and all three are a 200 that changed nothing. An
    answer carrying only the subscriber would leave the panel saying "Payment recorded" over a
    card that did not move.
    """

    subscriber: SubscriberDetail
    events: list[EngineEvent]


class AuditActor(ApiModel):
    """Who did it. The email rather than the id alone: an audit nobody can read is a log."""

    id: uuid.UUID
    email: str


class AuditEntry(ApiModel):
    """One row of the audit.

    `ipHash` is stored and never sent. A twelve-character HMAC on screen tells a reader nothing
    and is evidence leaving the machine that holds the pepper; the column is there for the day an
    investigation asks the database, not for a column on a table.
    """

    id: uuid.UUID
    occurred_at: datetime
    actor: AuditActor
    action: AuditAction
    target_type: str
    target_id: str

    # Which world it happened in. The base world is rebuilt at every restart, so a row older than
    # the last one names a subscriber whose state has been reset — which is why the screen links
    # the target only when this matches the world it is looking at.
    world_id: str

    outcome: Literal["ok", "refused"]
    error_code: ErrorCode | None = None

    # The arguments of the operation as they were submitted. Never its result.
    payload: dict[str, Any]


class AuditPage(ApiModel):
    """GET /api/audit."""

    items: list[AuditEntry]
    total: int
    page: int
    page_size: int


class AuditQueryParams(ApiModel):
    """The query string of GET /api/audit.

    No date range and no sort. An audit log has one order — newest first — and offering another
    produces something that reads as a ranking of who did the most; and a date filter needs a date
    control, which this interface does not have and `docs/design.md` has no recipe for. A filter
    nobody can operate is not a filter.
    """

    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=25, ge=1, le=100)
    actor_user_id: uuid.UUID | None = None
    action: list[AuditAction] = Field(default_factory=list)
    target_id: str | None = Field(default=None, max_length=200)
    outcome: Literal["ok", "refused"] | None = None


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
    plan_id: list[str] = Field(default_factory=list)
    cohort: Literal["quiet", "trial-ending", "cancelled-still-active"] | None = None
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
            plan_ids=tuple(self.plan_id),
            cohort=Cohort(self.cohort) if self.cohort else None,
            search=self.q,
        )
