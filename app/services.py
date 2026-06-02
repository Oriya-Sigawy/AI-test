"""Business logic for each resource group.

Each function takes a ``Session`` (and, where relevant, the acting user), enforces the
domain rules, and raises the typed exceptions in ``app.errors`` that the HTTP layer renders.
Functions are grouped by resource as their build tasks add them; auth comes first.
"""

import logging
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import Conflict, Forbidden, InvalidInput, NotFound, Unauthenticated
from app.models import Category, Expense, User
from app.schemas import (
    CategoryCreate,
    CategoryUpdate,
    ExpenseCreate,
    ExpenseFilters,
    ExpenseUpdate,
    LoginRequest,
    RegisterRequest,
    UserUpdate,
)

from app.security import hash_password, verify_password

logger = logging.getLogger(__name__)


def paginate(db: Session, stmt: Select, limit: int, offset: int) -> tuple[list, int]:
    """Return one page of rows for an ordered query plus the total matching count.

    Shared by every list endpoint so the limit/offset/count shape is defined once.
    stmt: a SELECT already filtered and ordered; ``limit``/``offset`` bound the page returned.
    """
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(db.scalars(stmt.limit(limit).offset(offset)).all())
    return items, total


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


# --- Categories -----------------------------------------------------------------------


def _reject_default_name_collision(db: Session, name: str) -> None:
    """Raise ``Conflict`` if a shared system default already uses this name (case-insensitively).

    Custom-vs-custom duplicates are caught by the partial unique index (it excludes the
    null-owner defaults), so this covers only the default collision the index cannot — together
    they enforce "unique among every category visible to the user, including defaults".
    """
    clash = db.scalar(
        select(Category.id).where(
            Category.owner_id.is_(None), func.lower(Category.name) == name.lower()
        )
    )
    if clash is not None:
        raise Conflict(f"A category named '{name}' already exists")


def _own_category(db: Session, user: User, category_id: int) -> Category:
    """Return the user's own custom category, or raise the right error for why it isn't editable.

    A system default is visible but read-only (``Forbidden``); any other id outside the user's
    scope — another user's category or a non-existent one — is an indistinguishable ``NotFound``.
    """
    category = db.get(Category, category_id)
    if category is None:
        raise NotFound("Category not found")
    if category.is_system:
        raise Forbidden("System default categories cannot be modified")
    if category.owner_id != user.id:
        raise NotFound("Category not found")
    return category


def list_categories(db: Session, user: User, limit: int, offset: int) -> tuple[list[Category], int]:
    """Return a page of the categories visible to the user: the shared defaults plus their own.

    Ordered system-defaults first, then by name ascending, so pagination is stable.
    """
    stmt = (
        select(Category)
        .where((Category.owner_id == user.id) | (Category.owner_id.is_(None)))
        .order_by(Category.is_system.desc(), Category.name.asc())
    )
    return paginate(db, stmt, limit, offset)


def create_category(db: Session, user: User, data: CategoryCreate) -> Category:
    """Create and return a custom category owned by the user.

    Name uniqueness is enforced two ways: an explicit check against the shared defaults, and
    the per-owner partial unique index for the user's own categories (a duplicate surfaces as an
    ``IntegrityError`` → ``Conflict``, so there is no read-then-write race).
    """
    _reject_default_name_collision(db, data.name)
    category = Category(
        name=data.name, icon=data.icon, color=data.color, is_system=False, owner_id=user.id
    )
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"A category named '{data.name}' already exists") from exc
    db.refresh(category)
    return category


def update_category(db: Session, user: User, category_id: int, data: CategoryUpdate) -> Category:
    """Apply a partial update to the user's own custom category and return it.

    System defaults are read-only (403) and other users' categories are not found (404). A
    rename re-checks name uniqueness the same way creation does.
    """
    category = _own_category(db, user, category_id)
    renaming = data.name is not None and data.name.lower() != category.name.lower()
    if renaming:
        _reject_default_name_collision(db, data.name)

    if data.name is not None:
        category.name = data.name
    if data.icon is not None:
        category.icon = data.icon
    if data.color is not None:
        category.color = data.color
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"A category named '{data.name}' already exists") from exc
    db.refresh(category)
    return category


def delete_category(db: Session, user: User, category_id: int) -> None:
    """Delete the user's own unused custom category; its budgets cascade away with it.

    Blocked (409) while expenses still reference it — the conflict carries the expense count and
    advises reassigning them first. System defaults are read-only (403), others' 404.
    """
    category = _own_category(db, user, category_id)
    expense_count = db.scalar(
        select(func.count()).select_from(Expense).where(Expense.category_id == category_id)
    )
    if expense_count:
        logger.warning(
            "category delete blocked: in use",
            extra={
                "event": "category_delete_blocked",
                "category_id": category_id,
                "expense_count": expense_count,
            },
        )
        raise Conflict(
            f"Category has {expense_count} expenses; reassign them before deleting",
            count=expense_count,
        )
    db.delete(category)  # budgets referencing it are removed by the FK ON DELETE CASCADE
    db.commit()


# --- Expenses -------------------------------------------------------------------------


def _accessible_category(db: Session, user: User, category_id: int) -> Category:
    """Return a category the user may spend against (a system default or their own), else ``NotFound``.

    Another user's category is indistinguishable from a missing one (both 404), so the API never
    discloses that it exists (FR-023).
    """
    category = db.get(Category, category_id)
    if category is None or (category.owner_id is not None and category.owner_id != user.id):
        raise NotFound("Category not found")
    return category


def create_expense(db: Session, user: User, data: ExpenseCreate) -> Expense:
    """Create and return an expense against an accessible category, in the owner's currency.

    The category is checked for accessibility first (404 otherwise); the currency is copied from
    the owner's default and the client-supplied value, if any, is ignored (FR-017).
    """
    category = _accessible_category(db, user, data.category_id)
    expense = Expense(
        owner_id=user.id,
        category_id=category.id,
        amount=data.amount,
        currency=user.default_currency,
        date=data.date,
        description=data.description,
        receipt_url=data.receipt_url,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    logger.info(
        "expense created",
        extra={
            "event": "expense_created",
            "user_id": user.id,
            "expense_id": expense.id,
            "category_id": category.id,
        },
    )
    return expense


def list_expenses(
    db: Session, user: User, filters: ExpenseFilters, limit: int, offset: int
) -> tuple[list[Expense], int]:
    """Return one owner-scoped page of the user's expenses matching the filters, plus the total.

    Date/category/amount filters narrow the set; an inverted date or amount range is rejected
    (422) naming the offending bound. Ordered date desc, id desc (FR-036), with the category
    eager-loaded so a page costs one extra query rather than one per row.
    """
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        raise InvalidInput(
            "date_to must not be before date_from",
            field="date_to",
            reason="must not be before date_from",
        )
    if (
        filters.amount_min is not None
        and filters.amount_max is not None
        and filters.amount_min > filters.amount_max
    ):
        raise InvalidInput(
            "amount_max must not be less than amount_min",
            field="amount_max",
            reason="must not be less than amount_min",
        )

    conditions = [Expense.owner_id == user.id]
    if filters.date_from is not None:
        conditions.append(Expense.date >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(Expense.date <= filters.date_to)
    if filters.category_id is not None:
        conditions.append(Expense.category_id == filters.category_id)
    if filters.amount_min is not None:
        conditions.append(Expense.amount >= filters.amount_min)
    if filters.amount_max is not None:
        conditions.append(Expense.amount <= filters.amount_max)

    stmt = (
        select(Expense)
        .where(*conditions)
        .order_by(Expense.date.desc(), Expense.id.desc())
        .options(selectinload(Expense.category))
    )
    return paginate(db, stmt, limit, offset)


def get_expense(db: Session, user: User, expense_id: int) -> Expense:
    """Return the user's own expense by id (category eager-loaded), or raise ``NotFound``.

    Owner-scoped, so another user's id reads identically to a non-existent one (404; FR-023).
    """
    expense = db.scalar(
        select(Expense)
        .where(Expense.id == expense_id, Expense.owner_id == user.id)
        .options(selectinload(Expense.category))
    )
    if expense is None:
        raise NotFound("Expense not found")
    return expense


def update_expense(db: Session, user: User, expense_id: int, data: ExpenseUpdate) -> Expense:
    """Apply a partial update to the user's own expense and return it.

    Only the fields actually supplied are changed (each already re-validated by the schema,
    FR-022); changing the category re-checks accessibility (404 otherwise). Currency is never
    touched, preserving the single-currency invariant.
    """
    expense = get_expense(db, user, expense_id)
    updates = data.model_dump(exclude_unset=True)
    if "category_id" in updates:
        _accessible_category(db, user, updates["category_id"])
    for field, value in updates.items():
        setattr(expense, field, value)
    db.commit()
    db.refresh(expense)
    logger.info(
        "expense updated",
        extra={
            "event": "expense_updated",
            "user_id": user.id,
            "expense_id": expense.id,
            "category_id": expense.category_id,
        },
    )
    return expense


def delete_expense(db: Session, user: User, expense_id: int) -> None:
    """Delete the user's own expense; raises ``NotFound`` if it isn't theirs or doesn't exist."""
    expense = get_expense(db, user, expense_id)
    db.delete(expense)
    db.commit()
