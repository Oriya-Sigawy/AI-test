"""HTTP endpoints for listing, creating, updating, and deleting categories.

Thin HTTP layer: each handler authenticates via ``get_current_user``, delegates to a service,
and returns the result. The list is paginated with the shared ``Page`` envelope; single
resources are returned bare. Every route requires a bearer token.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    Page,
    PaginationParams,
)
from app.security import get_current_user
from app.services import (
    create_category,
    delete_category,
    list_categories,
    update_category,
)

router = APIRouter(tags=["categories"])


@router.get("/categories", response_model=Page[CategoryResponse])
def list_my_categories(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[CategoryResponse]:
    """List the categories available to the user (shared defaults plus their own), paginated."""
    items, total = list_categories(db, current_user, pagination.limit, pagination.offset)
    return Page[CategoryResponse](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create(
    data: CategoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CategoryResponse:
    """Create a custom category owned by the user."""
    return create_category(db, current_user, data)


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
def update(
    category_id: int,
    data: CategoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CategoryResponse:
    """Update the user's own custom category (name, icon, and/or color)."""
    return update_category(db, current_user, category_id, data)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete the user's own unused custom category."""
    delete_category(db, current_user, category_id)
