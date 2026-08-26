"""The plan catalogue.

Its own module and its own router rather than a route on the subscriber one: the catalogue is not
a fact about any subscriber, and hanging it off `/subscribers` would have made the path say
otherwise.
"""

from fastapi import APIRouter, status
from substate import PeriodUnit, Plan

from app.deps import RequirePermission
from app.routers import error_responses
from app.schemas import PlanSummary
from app.seed.catalogue import PLANS

router = APIRouter(prefix="/plans", tags=["plans"])


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
