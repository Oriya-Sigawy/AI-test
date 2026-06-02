"""Shared Pydantic shapes: the paginated-list envelope, list query params, and the error body.

Per-resource request/response models are added to this module by their own build tasks
(plan §Layering). This foundation holds only the cross-cutting shapes: the ``Page`` envelope
and ``PaginationParams`` that every list endpoint reuses (FR-035), and the
``ErrorCategory``/``ErrorResponse`` that every failure is rendered through (FR-034).
"""

from enum import Enum
from typing import Generic, TypeVar
from fastapi import Query
from pydantic import BaseModel

from app.config import settings

ItemT = TypeVar("ItemT")


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
