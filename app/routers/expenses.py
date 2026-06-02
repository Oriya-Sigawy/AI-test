"""HTTP endpoints for expense create, list (filtered + paginated), get, update, and delete.

Thin HTTP layer: validate via the schema, delegate to the service, shape the response. Every
route requires authentication (``get_current_user``) and is owner-scoped in the service, so a
caller only ever reaches their own expenses.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Expense, User
from app.schemas import (
    ExpenseCreate,
    ExpenseFilters,
    ExpenseResponse,
    ExpenseUpdate,
    ExpenseWriteResponse,
    Page,
    PaginationParams,
)
from app.security import get_current_user
from app.services import (
    create_expense,
    delete_expense,
    get_expense,
    list_expenses,
    update_expense,
)

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.post("", response_model=ExpenseWriteResponse, status_code=status.HTTP_201_CREATED)
def create(
    data: ExpenseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Expense:
    """Create an expense in the owner's currency; an inaccessible category is reported as 404."""
    return create_expense(db, current_user, data)


@router.get("", response_model=Page[ExpenseResponse])
def list_(
    filters: ExpenseFilters = Depends(),
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[ExpenseResponse]:
    """List the user's expenses with optional date/category/amount filters, paginated."""
    items, total = list_expenses(db, current_user, filters, pagination.limit, pagination.offset)
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.get("/{expense_id}", response_model=ExpenseResponse)
def get_one(
    expense_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Expense:
    """Return the user's own expense; another user's or a missing id is a 404."""
    return get_expense(db, current_user, expense_id)


@router.patch("/{expense_id}", response_model=ExpenseWriteResponse)
def update(
    expense_id: int,
    data: ExpenseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Expense:
    """Update the user's own expense, re-applying all creation validations (FR-022)."""
    return update_expense(db, current_user, expense_id, data)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    expense_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete the user's own expense (404 if it isn't theirs)."""
    delete_expense(db, current_user, expense_id)
