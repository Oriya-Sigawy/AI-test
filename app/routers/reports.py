"""HTTP endpoints for the three spending reports: monthly summary, trend, and budget status.

Thin HTTP layer: validate the query parameters, delegate the SQL aggregation to the service,
and return its already-shaped result. Every route requires authentication (``get_current_user``)
and is owner-scoped in the service. All amounts are rendered as JSON strings (SC-006).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import BudgetStatusResponse, MonthlySummaryResponse, TrendResponse
from app.security import get_current_user
from app.services import budget_status, monthly_summary, trend

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/monthly-summary", response_model=MonthlySummaryResponse)
def monthly_summary_report(
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonthlySummaryResponse:
    """Total spend and per-category breakdown for one month (non-zero categories only)."""
    return monthly_summary(db, current_user, month, year)


@router.get("/trend", response_model=TrendResponse)
def trend_report(
    end_month: int = Query(ge=1, le=12),
    end_year: int = Query(ge=2000, le=2100),
    months: int = Query(default=6, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TrendResponse:
    """Spend total per month over the window ending at the given month, oldest→newest, zero-filled.

    ``months`` is capped at 36 in the service, so an over-large request is clamped, not rejected.
    """
    return trend(db, current_user, end_year, end_month, months)


@router.get("/budget-status", response_model=BudgetStatusResponse)
def budget_status_report(
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BudgetStatusResponse:
    """Per budgeted category for the month: spent vs budget with remaining (negative when over)."""
    return budget_status(db, current_user, month, year)
