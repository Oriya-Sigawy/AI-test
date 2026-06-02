"""Shared Pydantic shapes: the paginated-list envelope, list query params, and the error body.

Per-resource request/response models are added to this module by their own build tasks
(plan §Layering). This foundation holds only the cross-cutting shapes: the ``Page`` envelope
and ``PaginationParams`` that every list endpoint reuses (FR-035), and the
``ErrorCategory``/``ErrorResponse`` that every failure is rendered through (FR-034).
"""

import datetime as dt
import re
from enum import Enum
from typing import Generic, TypeVar
from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings

ItemT = TypeVar("ItemT")

# A pragmatic "commonly accepted" email shape: non-empty local part, an "@", and a domain with
# a dot. Deliberately not RFC-exhaustive and not a dependency on an external validator —
# format only, no deliverability check.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_currency(value: str) -> str:
    """Upper-case and validate a currency code as exactly three ASCII letters (format only)."""
    value = value.strip().upper()
    if not (len(value) == 3 and value.isascii() and value.isalpha()):
        raise ValueError("must be exactly three letters")
    return value


class Page(BaseModel, Generic[ItemT]):
    """The envelope every paginated list endpoint returns (FR-035).

    Wraps one page of ``items`` with the metadata needed to page through the rest:
    the ``total`` number of matching rows and the ``limit``/``offset`` used for this page.
    """

    items: list[ItemT]
    total: int
    limit: int
    offset: int


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
