"""Business logic for each resource group.

Each function takes a ``Session`` (and, where relevant, the acting user), enforces the
domain rules, and raises the typed exceptions in ``app.errors`` that the HTTP layer renders.
Functions are grouped by resource as their build tasks add them; auth comes first.
"""

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import Integer, Select, and_, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import Conflict, Forbidden, InvalidInput, NotFound, Unauthenticated
from app.models import Budget, Category, Expense, User
from app.schemas import (
    BudgetStatusResponse,
    BudgetStatusRow,
    BudgetUpsert,
    BudgetWarning,
    CategoryCreate,
    CategoryTotal,
    CategoryUpdate,
    ExpenseCreate,
    ExpenseFilters,
    ExpenseUpdate,
    LoginRequest,
    MonthlySummaryResponse,
    RegisterRequest,
    TrendMonth,
    TrendResponse,
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
    The conflict message is intentionally generic: it does not confirm that the email is
    already registered, to avoid account enumeration. Only the email's domain is logged,
    never the address or password.
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
        raise Conflict("Registration could not be completed") from exc
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
    logger.info(
        "category created",
        extra={"event": "category_created", "user_id": user.id, "category_id": category.id},
    )
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
    logger.info(
        "category updated",
        extra={"event": "category_updated", "user_id": user.id, "category_id": category.id},
    )
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
    logger.info(
        "category deleted",
        extra={"event": "category_deleted", "user_id": user.id, "category_id": category_id},
    )


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
    warning = _budget_warning_for_expense(db, user, category.id, category.name, expense.date)
    expense.budget_warning = warning
    logger.info(
        "expense created",
        extra={
            "event": "expense_created",
            "user_id": user.id,
            "expense_id": expense.id,
            "category_id": category.id,
            "budget_warning": warning is not None,
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
    warning = _budget_warning_for_expense(
        db, user, expense.category_id, expense.category.name, expense.date
    )
    expense.budget_warning = warning
    logger.info(
        "expense updated",
        extra={
            "event": "expense_updated",
            "user_id": user.id,
            "expense_id": expense.id,
            "category_id": expense.category_id,
            "budget_warning": warning is not None,
        },
    )
    return expense


def delete_expense(db: Session, user: User, expense_id: int) -> None:
    """Delete the user's own expense; raises ``NotFound`` if it isn't theirs or doesn't exist."""
    expense = get_expense(db, user, expense_id)
    db.delete(expense)
    db.commit()
    logger.info(
        "expense deleted",
        extra={"event": "expense_deleted", "user_id": user.id, "expense_id": expense_id},
    )


# --- Budgets --------------------------------------------------------------------------


def compute_budget_warning(
    category_name: str, budget: Decimal, spent: Decimal
) -> BudgetWarning | None:
    """Return a budget warning iff the spend *strictly* exceeds the budget, else ``None``.

    A pure function — no I/O; the caller supplies the month's ``spent`` from a SUM query.
    Spending exactly the budget is not a breach (FR-028); ``exceeded_by`` is the overage above it.
    """
    if spent <= budget:
        return None
    return BudgetWarning(
        category_name=category_name, budget=budget, spent=spent, exceeded_by=spent - budget
    )


def _month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    """Return the half-open ``[first-of-month, first-of-next-month)`` date range for a period.

    A half-open range lets the SUM ride the ``(owner, category, date)`` index as a range scan,
    rather than wrapping every row in ``extract(month/year)``.
    """
    start = dt.date(year, month, 1)
    end = dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    return start, end


def _budget_warning_for_expense(
    db: Session, user: User, category_id: int, category_name: str, on_date: dt.date
) -> BudgetWarning | None:
    """Compute the warning for an expense against *its own* month's budget, or ``None``.

    Keyed on the expense's ``on_date`` (not the current calendar month; FR-029): with no budget
    for that category+period there is no warning. Otherwise the month's category spend — the
    just-saved row included — is summed and compared by ``compute_budget_warning``.
    """
    budget = db.scalar(
        select(Budget.amount).where(
            Budget.owner_id == user.id,
            Budget.category_id == category_id,
            Budget.year == on_date.year,
            Budget.month == on_date.month,
        )
    )
    if budget is None:
        return None
    start, end = _month_bounds(on_date.year, on_date.month)
    spent = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), Decimal("0"))).where(
            Expense.owner_id == user.id,
            Expense.category_id == category_id,
            Expense.date >= start,
            Expense.date < end,
        )
    )
    return compute_budget_warning(category_name, budget, spent)


def set_budget(db: Session, user: User, data: BudgetUpsert) -> Budget:
    """Set or update the user's budget for one ``(category, month, year)`` and return it.

    The category must be accessible (a default or the user's own) — otherwise ``NotFound``, so
    another user's category is never disclosed (FR-023). The write is an idempotent upsert keyed
    by the ``(owner, category, year, month)`` unique index (FR-026): the first call inserts, a
    repeat updates the amount in place — race-free, no read-then-write.
    """
    category = _accessible_category(db, user, data.category_id)
    insert_stmt = pg_insert(Budget).values(
        owner_id=user.id,
        category_id=category.id,
        amount=data.amount,
        month=data.month,
        year=data.year,
    )
    upsert = insert_stmt.on_conflict_do_update(
        constraint="uq_budgets_owner_category_year_month",
        set_={"amount": insert_stmt.excluded.amount, "updated_at": func.now()},
    ).returning(Budget.id)
    budget_id = db.scalar(upsert)
    db.commit()
    logger.info(
        "budget set",
        extra={
            "event": "budget_set",
            "user_id": user.id,
            "budget_id": budget_id,
            "category_id": category.id,
        },
    )
    return db.scalar(
        select(Budget).where(Budget.id == budget_id).options(selectinload(Budget.category))
    )


def list_budgets(db: Session, user: User, limit: int, offset: int) -> tuple[list[Budget], int]:
    """Return one owner-scoped page of the user's budgets (newest period first) plus the total.

    Ordered ``year DESC, month DESC, id DESC`` (FR-036) for a stable page, with the category
    eager-loaded so a page costs one extra query rather than one per row.
    """
    stmt = (
        select(Budget)
        .where(Budget.owner_id == user.id)
        .order_by(Budget.year.desc(), Budget.month.desc(), Budget.id.desc())
        .options(selectinload(Budget.category))
    )
    return paginate(db, stmt, limit, offset)


def delete_budget(db: Session, user: User, budget_id: int) -> None:
    """Delete the user's own budget; raises ``NotFound`` if it isn't theirs or doesn't exist.

    Owner-scoped, so another user's budget id reads identically to a missing one (404; FR-023).
    """
    budget = db.scalar(select(Budget).where(Budget.id == budget_id, Budget.owner_id == user.id))
    if budget is None:
        raise NotFound("Budget not found")
    db.delete(budget)
    db.commit()
    logger.info(
        "budget deleted",
        extra={"event": "budget_deleted", "user_id": user.id, "budget_id": budget_id},
    )


# --- Reports --------------------------------------------------------------------------

# The trend window is capped so a client cannot request an unbounded number of months (FR-031).
_TREND_MAX_MONTHS = 36


def month_window(year: int, month: int, count: int) -> list[tuple[int, int]]:
    """Return ``count`` ``(year, month)`` pairs ending at the given month, ordered oldest→newest.

    year, month: the most recent month in the window (inclusive).
    count: how many consecutive months to include, counted backwards from that month.
    Months are indexed as a single ordinal so stepping back across a year boundary is plain
    subtraction — no calendar special-casing.
    """
    end_ordinal = year * 12 + (month - 1)
    return [
        ((end_ordinal - offset) // 12, (end_ordinal - offset) % 12 + 1)
        for offset in range(count - 1, -1, -1)
    ]


def monthly_summary(db: Session, user: User, month: int, year: int) -> MonthlySummaryResponse:
    """Return the user's total spend for one month plus a per-category breakdown (FR-030).

    Only categories with spend that month appear (the inner join drops the rest); the breakdown
    is ordered most-spent first. The total is summed from the same exact ``Decimal`` rows, so it
    always equals the breakdown's sum (SC-006). One grouped aggregate, owner-scoped.
    """
    start, end = _month_bounds(year, month)
    total_per_category = func.sum(Expense.amount)
    rows = db.execute(
        select(Category, total_per_category)
        .join(Expense, Expense.category_id == Category.id)
        .where(Expense.owner_id == user.id, Expense.date >= start, Expense.date < end)
        .group_by(Category.id)
        .order_by(total_per_category.desc())
    ).all()
    by_category = [CategoryTotal(category=category, total=total) for category, total in rows]
    total = sum((total for _, total in rows), Decimal("0"))
    return MonthlySummaryResponse(month=month, year=year, total=total, by_category=by_category)


def trend(db: Session, user: User, end_year: int, end_month: int, months: int) -> TrendResponse:
    """Return the user's monthly spend totals over the window ending at ``end_year``/``end_month``.

    months: requested window length, capped at 36 (FR-031). Empty months are zero-filled so the
    series is always contiguous oldest→newest. One grouped aggregate over the whole window's date
    range; the per-month totals are then mapped onto the generated window.
    """
    window = month_window(end_year, end_month, min(months, _TREND_MAX_MONTHS))
    start = dt.date(*window[0], 1)
    _, end = _month_bounds(end_year, end_month)
    year_part = cast(func.extract("year", Expense.date), Integer)
    month_part = cast(func.extract("month", Expense.date), Integer)
    rows = db.execute(
        select(year_part, month_part, func.sum(Expense.amount))
        .where(Expense.owner_id == user.id, Expense.date >= start, Expense.date < end)
        .group_by(year_part, month_part)
    ).all()
    totals = {(row_year, row_month): total for row_year, row_month, total in rows}
    points = [
        TrendMonth(year=y, month=m, total=totals.get((y, m), Decimal("0"))) for y, m in window
    ]
    return TrendResponse(months=points)


def budget_status(db: Session, user: User, month: int, year: int) -> BudgetStatusResponse:
    """Return spent-vs-budget for each category the user budgeted that month (FR-032).

    Only budgeted categories appear: the query starts from the month's budgets and LEFT JOINs the
    month's expenses, so a budget with no spend still shows (``spent`` 0) while a spent-but-
    unbudgeted category is excluded. ``remaining`` is ``budget − spent`` (negative when over). A
    single grouped aggregate — not a SUM per budget.
    """
    start, end = _month_bounds(year, month)
    spent = func.coalesce(func.sum(Expense.amount), Decimal("0"))
    rows = db.execute(
        select(Category, Budget.amount, spent)
        .select_from(Budget)
        .join(Category, Category.id == Budget.category_id)
        .outerjoin(
            Expense,
            and_(
                Expense.category_id == Budget.category_id,
                Expense.owner_id == user.id,
                Expense.date >= start,
                Expense.date < end,
            ),
        )
        .where(Budget.owner_id == user.id, Budget.month == month, Budget.year == year)
        .group_by(Category.id, Budget.id)
        .order_by(Category.name.asc())
    ).all()
    categories = [
        BudgetStatusRow(
            category=category, budget=budget, spent=spent_amount, remaining=budget - spent_amount
        )
        for category, budget, spent_amount in rows
    ]
    return BudgetStatusResponse(month=month, year=year, categories=categories)
