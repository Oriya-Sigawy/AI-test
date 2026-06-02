"""Domain exceptions and the FastAPI handlers that render them as the FR-034 error model.

Services raise the typed exceptions defined here; the handlers (installed on the app in
``app.main``) translate each to its HTTP status and the shared ``ErrorResponse`` body, and
emit one structured ``domain_error`` log record. Rejected operations — validation,
unauthenticated, forbidden, not-found, conflict — log at WARNING with their category and
status. An unhandled exception logs at ERROR with its stack trace (kept server-side) and
returns a generic 500 that discloses no internals (plan §Error model; OWASP A05).
"""

import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas import ErrorCategory, ErrorResponse

logger = logging.getLogger(__name__)

# Segments FastAPI prefixes onto a validation error's location ("body"/"query"/...); dropped so
# the reported ``field`` names the offending input itself (e.g. "amount", not "body").
_LOCATION_PREFIXES = frozenset({"body", "query", "path", "header", "cookie"})


class DomainError(Exception):
    """Base for failures that map to a fixed FR-034 ``category`` and HTTP ``status_code``."""

    category: ErrorCategory
    status_code: int

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def to_body(self) -> ErrorResponse:
        """Render this error as the wire body; subclasses extend it with their own fields."""
        return ErrorResponse(message=self.message, category=self.category)


class InvalidInput(DomainError):
    """422 — domain validation a schema can't express: the >7-day date bound, an inverted filter range.

    ``field`` -- the offending input; ``reason`` -- why it was rejected (FR-034 names both).
    """

    category = ErrorCategory.VALIDATION
    status_code = 422

    def __init__(self, message: str, *, field: str, reason: str) -> None:
        super().__init__(message)
        self.field = field
        self.reason = reason

    def to_body(self) -> ErrorResponse:
        return ErrorResponse(
            message=self.message, category=self.category, field=self.field, reason=self.reason
        )


class Unauthenticated(DomainError):
    """401 — a missing/malformed/invalid/expired token, or bad login credentials (one generic message)."""

    category = ErrorCategory.UNAUTHENTICATED
    status_code = 401


class Forbidden(DomainError):
    """403 — acting on a visible read-only resource: a system-default category (FR-013)."""

    category = ErrorCategory.FORBIDDEN
    status_code = 403


class NotFound(DomainError):
    """404 — an id outside the caller's scope; another user's resource reads identically to a missing one (FR-023)."""

    category = ErrorCategory.NOT_FOUND
    status_code = 404


class Conflict(DomainError):
    """409 — duplicate email/category name, deleting an in-use category, or changing currency after expenses exist.

    ``count`` -- blocking-expense count for the in-use-category conflict (FR-014); omitted otherwise.
    """

    category = ErrorCategory.CONFLICT
    status_code = 409

    def __init__(self, message: str, *, count: int | None = None) -> None:
        super().__init__(message)
        self.count = count

    def to_body(self) -> ErrorResponse:
        return ErrorResponse(message=self.message, category=self.category, count=self.count)


def _render(status_code: int, body: ErrorResponse) -> JSONResponse:
    """Serialize an error body to JSON, dropping unset optional fields."""
    return JSONResponse(
        status_code=status_code, content=body.model_dump(mode="json", exclude_none=True)
    )


def _first_error_field(exc: RequestValidationError) -> tuple[str | None, str | None]:
    """Extract ``(field, reason)`` from the first validation error, stripping the location prefix."""
    errors = exc.errors()
    if not errors:
        return None, None
    first = errors[0]
    parts = [str(p) for p in first.get("loc", ()) if p not in _LOCATION_PREFIXES]
    field = parts[-1] if parts else None
    return field, first.get("msg")


async def _handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
    """Map a raised domain exception to its status + body and log the rejection (WARNING)."""
    logger.warning(
        "request rejected",
        extra={"event": "domain_error", "category": exc.category.value, "status": exc.status_code},
    )
    return _render(exc.status_code, exc.to_body())


async def _handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render FastAPI/Pydantic request-validation failures in the shared 422 shape (field + reason)."""
    field, reason = _first_error_field(exc)
    logger.warning(
        "request rejected",
        extra={"event": "domain_error", "category": ErrorCategory.VALIDATION.value, "status": 422},
    )
    body = ErrorResponse(
        message="Validation failed", category=ErrorCategory.VALIDATION, field=field, reason=reason
    )
    return _render(422, body)


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: log the failure with its stack trace (server-side) and return a generic 500 (A05)."""
    logger.error(
        "unhandled exception",
        exc_info=exc,
        extra={"event": "domain_error", "category": ErrorCategory.UNEXPECTED.value, "status": 500},
    )
    body = ErrorResponse(message="Internal server error", category=ErrorCategory.UNEXPECTED)
    return _render(500, body)


def install_error_handlers(app: FastAPI) -> None:
    """Register the domain, request-validation, and catch-all handlers (called from ``app.main``).

    The catch-all is keyed on ``Exception`` so any unhandled error returns the generic 500
    above instead of a framework default. Starlette routes that handler through the outermost
    middleware, which re-raises after responding so the server still logs it — therefore tests
    that exercise the 500 path must drive the app with a client configured to surface server
    responses rather than re-raise (``raise_server_exceptions=False``; plan §Error model).
    """
    app.add_exception_handler(DomainError, _handle_domain_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
