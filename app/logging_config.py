"""Structured JSON logging to stdout (plan §Logging; research §10).

Python's stdlib ``logging`` configured to emit one JSON object per line on
stdout — no logging-framework dependency (Principle IV), and stdout suits
containers. Every record carries ``event``, ``level``, ``request_id`` and
``user_id``; any keyword passed via ``logging``'s ``extra=`` rides along as its
own field, so event-specific context (``email_domain``, ``expense_id``, ...)
needs no bespoke formatter.

``request_id`` and ``user_id`` are request-scoped and so live in context
variables here, populated by the request-id middleware (``app.main``) and
``get_current_user`` (``app.security``) and read back onto each record by
:class:`ContextFilter`. Secrets (passwords, hashes, tokens, full request bodies)
are never logged — enforced at the call sites, not by redaction here.
"""

import datetime as dt
import json
import logging
import sys
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
"""Per-request correlation id; set by the request-id middleware in ``app.main``."""

user_id_var: ContextVar[int | None] = ContextVar("user_id", default=None)
"""Acting user's id once authenticated; set by ``get_current_user`` (``app.security``)."""

# Attributes the logging machinery puts on every LogRecord. Anything a caller
# adds through ``extra=`` is, by definition, a key NOT in this set — which is how
# the formatter tells context fields apart from machinery fields.
_RESERVED_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
}


class ContextFilter(logging.Filter):
    """Inject the request-scoped ``request_id`` and ``user_id`` onto each record.

    Values come from the context variables above. An explicit ``extra=`` on the
    log call takes precedence (the attribute is left untouched if already set),
    so ``login_success`` can record the just-authenticated user even though the
    auth dependency has not run to populate ``user_id_var``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        if not hasattr(record, "user_id"):
            record.user_id = user_id_var.get()
        return True


class JsonLogFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object.

    Always emits ``timestamp``, ``level``, ``logger``, ``event``, ``request_id``,
    ``user_id`` and ``message``; every ``extra=`` keyword is appended as its own
    field. A stack trace, when present, goes to ``exception`` — stdout only,
    never to clients (plan §Error model).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": dt.datetime.fromtimestamp(
                record.created, tz=dt.timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", None),
            "request_id": getattr(record, "request_id", None),
            "user_id": getattr(record, "user_id", None),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int | str = logging.INFO) -> None:
    """Install the JSON stdout handler on the root logger (call once at startup).

    ``level`` -- lowest level the root logger emits (default INFO: normal
    lifecycle and above). Idempotent — existing handlers are cleared first, so a
    repeated call (e.g. across tests) does not stack duplicate handlers. The
    context filter is attached to the handler rather than the logger so it also
    applies to records propagated up from child loggers (``app.routers.*`` etc.).
    """
    root = logging.getLogger()
    root.setLevel(level)
    for existing in list(root.handlers):
        root.removeHandler(existing)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(ContextFilter())
    root.addHandler(handler)
