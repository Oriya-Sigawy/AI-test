"""HTTP endpoints for setting, listing, and deleting per-category monthly budgets.

Thin HTTP layer: validate via the schema, delegate to the service, shape the response. Every
route requires authentication (``get_current_user``) and is owner-scoped in the service, so a
caller only ever reaches their own budgets. Setting a budget is a ``PUT`` — an idempotent upsert
keyed by ``(category, month, year)``, so re-sending a period updates it rather than duplicating it.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Budget, User
from app.schemas import BudgetResponse, BudgetUpsert, Page, PaginationParams
from app.security import get_current_user
from app.services import delete_budget, list_budgets, set_budget

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.put("", response_model=BudgetResponse)
def set_(
    data: BudgetUpsert,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Budget:
    """Set or update the budget for a (category, month, year); an inaccessible category is a 404."""
    return set_budget(db, current_user, data)


@router.get("", response_model=Page[BudgetResponse])
def list_(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[BudgetResponse]:
    """List the user's budgets, newest period first, paginated."""
    items, total = list_budgets(db, current_user, pagination.limit, pagination.offset)
    return Page[BudgetResponse](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    budget_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete the user's own budget (404 if it isn't theirs)."""
    delete_budget(db, current_user, budget_id)
