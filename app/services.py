"""Business logic for each resource group.

Each function takes a ``Session`` (and, where relevant, the acting user), enforces the
domain rules, and raises the typed exceptions in ``app.errors`` that the HTTP layer renders.
Functions are grouped by resource as their build tasks add them; auth comes first.
"""

import logging
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import Conflict, Unauthenticated
from app.models import Expense, User
from app.schemas import LoginRequest, RegisterRequest, UserUpdate

from app.security import hash_password, verify_password

logger = logging.getLogger(__name__)


def register_user(db: Session, data: RegisterRequest) -> User:
    """Create and return a new account from a validated registration request.

    Email uniqueness is enforced case-insensitively by the database index, so a duplicate is
    caught as an ``IntegrityError`` and surfaced as a ``Conflict`` — no read-then-write race.
    Only the email's domain is logged, never the address or password.
    """
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
        default_currency=data.default_currency,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("An account with this email already exists") from exc
    db.refresh(user)
    logger.info(
        "account registered",
        extra={"event": "register", "user_id": user.id, "email_domain": data.email.split("@")[-1]},
    )
    return user


def authenticate_user(db: Session, data: LoginRequest) -> User:
    """Return the user matching the login credentials, or raise ``Unauthenticated``.

    An unknown email and a wrong password fail identically (one generic 401), so the response
    never reveals whether an email is registered. The failure log carries no field that would
    reveal which credential was wrong.
    """
    user = db.scalar(select(User).where(func.lower(User.email) == data.email))
    if user is None or not verify_password(data.password, user.password_hash):
        logger.warning("login failed", extra={"event": "login_failure"})
        raise Unauthenticated("Invalid email or password")
    logger.info("login succeeded", extra={"event": "login_success", "user_id": user.id})
    return user


def update_profile(db: Session, user: User, data: UserUpdate) -> User:
    """Apply a profile update and return the user.

    The display name is editable at any time; the default currency may change only while the
    user has no expenses (raising ``Conflict`` otherwise), preserving the single-currency
    invariant. The currency guard is checked before any field is mutated.
    """
    changing_currency = (
        data.default_currency is not None and data.default_currency != user.default_currency
    )
    if changing_currency:
        has_expense = db.scalar(select(Expense.id).where(Expense.owner_id == user.id).limit(1))
        if has_expense is not None:
            raise Conflict("Cannot change currency after expenses exist")

    if data.display_name is not None:
        user.display_name = data.display_name
    if data.default_currency is not None:
        user.default_currency = data.default_currency
    db.commit()
    db.refresh(user)
    return user
