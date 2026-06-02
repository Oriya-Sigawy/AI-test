"""Shared Pydantic shapes: the paginated-list envelope, list query params, and the error body.

Per-resource request/response models are added to this module by their own build tasks
(plan §Layering). This foundation holds only the cross-cutting shapes: the ``Page`` envelope
and ``PaginationParams`` that every list endpoint reuses (FR-035), and the
``ErrorCategory``/``ErrorResponse`` that every failure is rendered through (FR-034).
"""

import datetime as dt
import re
from decimal import Decimal
from enum import Enum
from typing import Annotated, Generic, TypeVar
from fastapi import Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    computed_field,
    field_validator,
    model_serializer,
)

from app.config import settings

ItemT = TypeVar("ItemT")

# A pragmatic "commonly accepted" email shape: non-empty local part, an "@", and a domain with
# a dot. Deliberately not RFC-exhaustive and not a dependency on an external validator —
# format only, no deliverability check.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# A six-digit hex color, e.g. "#6F4E37" — the only color shape categories accept.
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _normalize_currency(value: str) -> str:
    """Upper-case and validate a currency code as exactly three ASCII letters (format only)."""
    value = value.strip().upper()
    if not (len(value) == 3 and value.isascii() and value.isalpha()):
        raise ValueError("must be exactly three letters")
    return value


# Every money amount a response returns is rendered as a fixed two-decimal JSON string (e.g.
# "42.50") so a client's float round-trip can't perturb the value (SC-006). The rule is defined
# once here and applied by typing each output amount field as ``MoneyOut``.
MoneyOut = Annotated[Decimal, PlainSerializer(lambda value: f"{value:.2f}", return_type=str)]


class Page(BaseModel, Generic[ItemT]):
    """The envelope every paginated list endpoint returns (FR-035).

    Wraps one page of ``items`` with the metadata needed to page through the rest:
    the ``total`` number of matching rows and the ``limit``/``offset`` used for this page.
    ``count`` is how many items this page actually carries — equal to ``limit`` for a full
    page, fewer on the last page.
    """

    items: list[ItemT]
    total: int
    limit: int
    offset: int

    @computed_field
    @property
    def count(self) -> int:
        """Number of items returned on this page (``<= limit``); derived from ``items``."""
        return len(self.items)


class PaginationParams:
    """Shared ``limit``/``offset`` query parameters for every list endpoint (FR-035).

    Used as a FastAPI dependency (``Depends(PaginationParams)``). ``limit`` defaults to the
    configured page size and is capped at the configured maximum; ``offset`` is a
    non-negative start index. Out-of-range or non-integer values are rejected as 422 by
    FastAPI before the route runs.
    """

    def __init__(
        self,
        limit: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
        offset: int = Query(default=0, ge=0),
    ) -> None:
        self.limit = limit
        self.offset = offset


class ErrorCategory(str, Enum):
    """The FR-034 failure classes; each member's value is the wire ``category`` string."""

    VALIDATION = "validation"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNEXPECTED = "unexpected"


class ErrorResponse(BaseModel):
    """The error body returned for every failure (FR-034; contract §Error body shape).

    ``message`` and ``category`` are always present. ``field``/``reason`` accompany a
    validation failure; ``count`` accompanies the category-in-use conflict (FR-014). Unset
    optional fields are omitted from the response (handlers serialize with ``exclude_none``).
    """

    message: str
    category: ErrorCategory
    field: str | None = None
    reason: str | None = None
    count: int | None = None


# --- Auth & users ---------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """A new-account registration body; the password is validated here but never echoed back."""

    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    default_currency: str

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        value = value.strip().lower()  # stored and matched case-insensitively
        if not _EMAIL_RE.match(value):
            raise ValueError("must be a valid email address")
        return value

    @field_validator("default_currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        return _normalize_currency(value)


class LoginRequest(BaseModel):
    """Login credentials. The email is lower-cased for lookup but not format-checked here, so a
    malformed email fails as a generic 401 rather than disclosing anything via a 422."""

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str) -> str:
        return value.strip().lower()


class TokenResponse(BaseModel):
    """The bearer token issued on a successful login."""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """A user's public profile. Excludes the password hash by construction, so it can never leak."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    default_currency: str
    created_at: dt.datetime
    updated_at: dt.datetime


class UserUpdate(BaseModel):
    """A profile update. Only display name and currency are editable; an ``email`` field, if
    sent, is ignored (the address is immutable). Both fields are optional — omit to leave as-is."""

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    default_currency: str | None = None

    @field_validator("default_currency")
    @classmethod
    def _validate_currency(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_currency(value)


# --- Categories -----------------------------------------------------------------------


def _validate_category_name(value: str) -> str:
    """Trim surrounding whitespace and require 1–50 characters (checked after trimming)."""
    value = value.strip()
    if not 1 <= len(value) <= 50:
        raise ValueError("must be between 1 and 50 characters")
    return value


def _validate_icon(value: str) -> str:
    """Trim and require a non-empty icon identifier."""
    value = value.strip()
    if not value:
        raise ValueError("must not be empty")
    return value


def _validate_color(value: str) -> str:
    """Require a six-digit hex color like ``#RRGGBB``."""
    if not _HEX_COLOR_RE.match(value):
        raise ValueError("must be a six-digit hex color like #RRGGBB")
    return value


class CategoryCreate(BaseModel):
    """A new custom category: a name (unique to the user), an icon identifier, and a hex color."""

    name: str
    icon: str
    color: str

    _name = field_validator("name")(_validate_category_name)
    _icon = field_validator("icon")(_validate_icon)
    _color = field_validator("color")(_validate_color)


class CategoryUpdate(BaseModel):
    """A custom-category edit. Every field is optional — omit one to leave it unchanged."""

    name: str | None = Field(default=None)
    icon: str | None = Field(default=None)
    color: str | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        return None if value is None else _validate_category_name(value)

    @field_validator("icon")
    @classmethod
    def _validate_icon_field(cls, value: str | None) -> str | None:
        return None if value is None else _validate_icon(value)

    @field_validator("color")
    @classmethod
    def _validate_color_field(cls, value: str | None) -> str | None:
        return None if value is None else _validate_color(value)


class CategoryResponse(BaseModel):
    """A category as returned to clients: a shared system default (``owner_id`` null) or the user's own."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    icon: str
    color: str
    is_system: bool
    owner_id: int | None


# --- Expenses -------------------------------------------------------------------------

# Amount: a positive Decimal with at most 11 total / 2 fractional digits — exactly the
# 999,999,999.99 ceiling and the two-decimal precision rule (FR-018/019). Shared with budgets.
_AMOUNT_MAX_DIGITS = 11
ExpenseAmount = Annotated[Decimal, Field(gt=0, max_digits=_AMOUNT_MAX_DIGITS, decimal_places=2)]

# Expense dates may be any time in the past but at most this many days ahead (FR-020).
_EXPENSE_FUTURE_DAYS = 7

# A receipt link is stored and returned only, never fetched, so format is all that is checked:
# an http/https URL with no whitespace (no SSRF surface — the server never dereferences it).
_RECEIPT_URL_RE = re.compile(r"^https?://\S+$")


def _utc_today() -> dt.date:
    """Return today's date in UTC — the reference point for the expense-date bound."""
    return dt.datetime.now(tz=dt.timezone.utc).date()


def validate_expense_date(value: dt.date, *, today: dt.date) -> dt.date:
    """Return the expense date if within bounds, else raise ``ValueError``.

    value: the expense's calendar date (no lower bound).
    today: the reference 'today', injected by the caller (not read from the clock here) so the
        rule stays pure and deterministically testable; the date may be at most 7 days ahead.
    """
    if value > today + dt.timedelta(days=_EXPENSE_FUTURE_DAYS):
        raise ValueError("must not be more than 7 days in the future")
    return value


def _validate_receipt_url(value: str | None) -> str | None:
    """Validate a receipt URL's format (http/https); ``None`` (no receipt) passes through unchanged."""
    if value is None:
        return None
    if not _RECEIPT_URL_RE.match(value):
        raise ValueError("must be a valid http(s) URL")
    return value


class CategoryRef(BaseModel):
    """The category as embedded inside an expense response — the contract's nested shape.

    Deliberately omits ``owner_id`` (carried only by the standalone ``CategoryResponse``); this
    is the read-only reference every expense (and later budget/report) nests.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    icon: str
    color: str
    is_system: bool


class ExpenseCreate(BaseModel):
    """A new expense. There is intentionally no ``currency`` field — an expense is always stored
    in the owner's default currency (FR-017), so any client-sent currency is ignored as unknown."""

    amount: ExpenseAmount
    category_id: int
    date: dt.date
    description: str | None = Field(default=None, max_length=500)
    receipt_url: str | None = Field(default=None, max_length=2048)

    @field_validator("date")
    @classmethod
    def _validate_date(cls, value: dt.date) -> dt.date:
        return validate_expense_date(value, today=_utc_today())

    @field_validator("receipt_url")
    @classmethod
    def _validate_receipt(cls, value: str | None) -> str | None:
        return _validate_receipt_url(value)


class ExpenseUpdate(BaseModel):
    """A partial expense edit; every field optional (omit to leave unchanged). Supplied fields
    re-run all creation validations (FR-022). Currency is never editable (single-currency)."""

    amount: ExpenseAmount | None = None
    category_id: int | None = None
    date: dt.date | None = None
    description: str | None = Field(default=None, max_length=500)
    receipt_url: str | None = Field(default=None, max_length=2048)

    @field_validator("date")
    @classmethod
    def _validate_date(cls, value: dt.date | None) -> dt.date | None:
        return None if value is None else validate_expense_date(value, today=_utc_today())

    @field_validator("receipt_url")
    @classmethod
    def _validate_receipt(cls, value: str | None) -> str | None:
        return _validate_receipt_url(value)


class ExpenseResponse(BaseModel):
    """A stored expense as returned to clients, with its category embedded.

    The amount is serialized as a JSON string (e.g. ``"42.50"``) so a client's float round-trip
    cannot perturb the value (SC-006).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: MoneyOut
    currency: str
    category: CategoryRef
    date: dt.date
    description: str | None
    receipt_url: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class BudgetWarning(BaseModel):
    """The budget-exceeded warning attached to a create/update expense response (FR-029).

    Present only when the expense's month-and-category total *strictly* exceeds that period's
    budget. ``category_name`` is a plain string label — deliberately not the nested ``category``
    object used everywhere else; the money fields serialize as strings like every other amount.
    """

    category_name: str
    budget: MoneyOut
    spent: MoneyOut
    exceeded_by: MoneyOut


class ExpenseWriteResponse(ExpenseResponse):
    """An expense returned from create/update: an ``ExpenseResponse`` plus an optional warning.

    The ``budget_warning`` is included only when the period is over budget; otherwise it is
    dropped from the payload entirely (never emitted as ``null``), matching the contract where
    the field is absent unless a budget is exceeded.
    """

    budget_warning: BudgetWarning | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_warning(self, handler):
        """Serialize as usual, then drop ``budget_warning`` when there is none (no null key)."""
        data = handler(self)
        if data.get("budget_warning") is None:
            data.pop("budget_warning", None)
        return data


class ExpenseFilters:
    """Optional expense-list filters, used as a FastAPI dependency (``Depends(ExpenseFilters)``).

    Each is an optional query parameter; malformed values (a bad date or amount) are rejected as
    422 by FastAPI before the route runs. Inverted ranges (``from`` > ``to``, ``min`` > ``max``)
    are rejected in the service, which names the offending bound.
    """

    def __init__(
        self,
        date_from: dt.date | None = Query(default=None),
        date_to: dt.date | None = Query(default=None),
        category_id: int | None = Query(default=None),
        amount_min: Decimal | None = Query(default=None),
        amount_max: Decimal | None = Query(default=None),
    ) -> None:
        self.date_from = date_from
        self.date_to = date_to
        self.category_id = category_id
        self.amount_min = amount_min
        self.amount_max = amount_max


# --- Budgets --------------------------------------------------------------------------

# A budget amount may be zero (a deliberate "no spending" limit) but not negative; it shares the
# expenses' 11-digit / 2-decimal ceiling (FR-018/019). The sign rule differs from ``ExpenseAmount``
# (which is strictly positive), so it is its own annotation.
BudgetAmount = Annotated[Decimal, Field(ge=0, max_digits=_AMOUNT_MAX_DIGITS, decimal_places=2)]


class BudgetUpsert(BaseModel):
    """A set-or-update budget request for one ``(category, month, year)`` (FR-026).

    ``amount`` may be zero but not negative; ``month`` is 1–12 and ``year`` a sane calendar year
    (matching the table's CHECK bounds). Re-sending an existing period updates it in place rather
    than creating a second budget — an idempotent upsert.
    """

    category_id: int
    amount: BudgetAmount
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)


class BudgetResponse(BaseModel):
    """A stored budget as returned to clients: its category embedded and the amount as a string."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    category: CategoryRef
    amount: MoneyOut
    month: int
    year: int


# --- Reports --------------------------------------------------------------------------


class CategoryTotal(BaseModel):
    """One category's total spend within a monthly summary; the amount serializes as a string."""

    category: CategoryRef
    total: MoneyOut


class MonthlySummaryResponse(BaseModel):
    """A month's total spend with its per-category breakdown — non-zero categories only (FR-030)."""

    month: int
    year: int
    total: MoneyOut
    by_category: list[CategoryTotal]


class TrendMonth(BaseModel):
    """One month's total in a spending trend; zero when the month had no spend (FR-031)."""

    year: int
    month: int
    total: MoneyOut


class TrendResponse(BaseModel):
    """A spending trend: one total per month over the requested window, oldest→newest (FR-031)."""

    months: list[TrendMonth]


class BudgetStatusRow(BaseModel):
    """One budgeted category's spend versus its budget for the month, with the remaining balance.

    ``remaining`` is ``budget − spent`` and goes negative once the budget is exceeded (FR-032).
    """

    category: CategoryRef
    budget: MoneyOut
    spent: MoneyOut
    remaining: MoneyOut


class BudgetStatusResponse(BaseModel):
    """Per budgeted category for the month: spent vs budget with remaining (FR-032).

    Only categories that have a budget set for the month appear (a spent-but-unbudgeted category
    is omitted).
    """

    month: int
    year: int
    categories: list[BudgetStatusRow]
