"""The catalogues: what is sold, and what a referrer is paid on.

Their own module and their own routers rather than routes on the subscriber one: neither is a fact
about any subscriber, and hanging them off `/subscribers` would have made the paths say otherwise.
Both are lists a control chooses from, which is why they exist at all — a control over an
identifier nobody can discover is a control you learn by being refused.
"""

from fastapi import APIRouter, status
from substate import Accrual, PeriodUnit, Plan

from app.deps import RequirePermission
from app.routers import error_responses
from app.schemas import PlanSummary, ReferralProgramSummary
from app.seed.catalogue import PLANS, REFERRAL_PROGRAMS

router = APIRouter(prefix="/plans", tags=["plans"])
programs_router = APIRouter(prefix="/referral-programs", tags=["referrals"])


def plan_summary(plan: Plan) -> PlanSummary:
    """One plan, as the API describes it.

    `PeriodUnit` is an enum in the library and a string in the schema, and this is the only place
    that translation happens — two copies of it would eventually disagree about `months`.
    """
    return PlanSummary(
        id=plan.id,
        price=plan.price,
        currency=plan.currency,
        period_unit="days" if plan.period.unit is PeriodUnit.DAYS else "months",
        period_count=plan.period.count,
        trial_days=plan.trial_days,
        grace_days=plan.grace_days,
    )


@router.get(
    "",
    response_model=list[PlanSummary],
    responses=error_responses(status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
    dependencies=[RequirePermission("subscribers.read")],
)
async def list_plans() -> list[PlanSummary]:
    """The whole catalogue, in the order the table's plan filter should offer it.

    The filter needs every plan, not the ones that happen to appear on the page being looked at —
    a filter offering four of five because the fifth is on page two is a filter that hides people.
    The order is the catalogue's own, which is the duration ladder, so it reads shortest to
    longest rather than alphabetically.
    """
    return [plan_summary(plan) for plan in PLANS]


@programs_router.get(
    "",
    response_model=list[ReferralProgramSummary],
    responses=error_responses(status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
    dependencies=[RequirePermission("referrals.read")],
)
async def list_programs() -> list[ReferralProgramSummary]:
    """Every referral programme, so putting a subscriber on one is a choice from a list.

    Without it the control is a text field for an identifier nobody can discover, and the only way
    to learn the right value is to be refused with the wrong one.
    """
    return [
        ReferralProgramSummary(
            id=program.id,
            percent=program.percent,
            accrual="first_payment_only"
            if program.accrual is Accrual.FIRST_PAYMENT_ONLY
            else "every_payment",
        )
        for program in REFERRAL_PROGRAMS
    ]
