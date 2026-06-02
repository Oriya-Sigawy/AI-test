"""HTTP endpoints for registration, login, and the current user's profile.

Thin HTTP layer: each handler validates input via its schema, delegates to a service, and
returns the result. ``UserResponse`` carries no password field, so profiles never leak it.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    UserUpdate,
)
from app.security import create_access_token, get_current_user
from app.services import authenticate_user, register_user, update_profile

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)) -> User:
    """Create a new account and return its public profile. No token is issued (log in to get one)."""
    return register_user(db, data)


@router.post("/auth/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Exchange email and password for a bearer access token."""
    user = authenticate_user(db, data)
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/users/me", response_model=UserResponse)
def read_profile(current_user: User = Depends(get_current_user)) -> User:
    """Return the authenticated user's profile."""
    return current_user


@router.patch("/users/me", response_model=UserResponse)
def update_my_profile(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Update the current user's display name and/or default currency."""
    return update_profile(db, current_user, data)
