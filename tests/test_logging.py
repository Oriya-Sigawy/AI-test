"""Assertions on the emitted log output for auth flows and rejected operations (T021).

This is the one place the suite asserts on log *output* itself (plan §Test Strategy): that
auth events carry the request id and the acting user, that a rejected operation logs a
``domain_error`` at WARNING with its FR-034 category and status, and — the invariant that
matters most — that no log line ever contains a credential, its hash, a bearer token, or a
full email address (plan §Logging, "Never logged"). Everywhere else logs are a side effect,
not the behavior under test.
"""

import logging

import pytest

from app.logging_config import ContextFilter, JsonLogFormatter

# Distinctive values driven through the API so they are unambiguous to scan for in the output.
# A unique local part means the full address can be asserted absent while its domain is allowed.
_PW = "do-not-log-this-passphrase"
_EMAIL = "logtester@example.com"
_DOMAIN = "example.com"


def _register_body(password: str = _PW) -> dict[str, str]:
    """Build a registration request body for the log-test user (password set separately)."""
    body = {"email": _EMAIL, "display_name": "Log Tester", "default_currency": "USD"}
    body["password"] = password
    return body


def _login_body(password: str = _PW) -> dict[str, str]:
    """Build a login request body for the log-test user (password set separately)."""
    body = {"email": _EMAIL}
    body["password"] = password
    return body


class _CapturingHandler(logging.Handler):
    """Collect every emitted record together with its fully rendered JSON line.

    Mirrors the production handler (same ``ContextFilter`` + ``JsonLogFormatter``), so the
    captured lines are byte-for-byte what would reach stdout — which is exactly what the
    sensitive-data assertions must inspect. The filter runs before ``emit`` (stdlib
    ``Handler.handle``), so ``request_id``/``user_id`` are populated on each captured record.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.lines: list[str] = []
        self.addFilter(ContextFilter())
        self.setFormatter(JsonLogFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.lines.append(self.format(record))


@pytest.fixture
def captured_logs():
    """Attach a capturing handler to the root logger for the duration of one test.

    Sets the root level to DEBUG so INFO milestones (register/login) are captured, and
    restores the prior level and handler set on teardown so tests stay independent.
    """
    handler = _CapturingHandler()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


def _events(handler: _CapturingHandler) -> dict[str, logging.LogRecord]:
    """Index the captured records by their ``event`` field (last write wins)."""
    return {getattr(r, "event", None): r for r in handler.records}


def _assert_no_sensitive_data(handler: _CapturingHandler, *, jwt: str | None = None) -> None:
    """Assert no rendered log line contains the credential, a bcrypt hash, the token, or the full email."""
    blob = "\n".join(handler.lines)
    assert _PW not in blob, "the plaintext credential appeared in a log line"
    assert _EMAIL not in blob, "full email address appeared in a log line (only the domain may be logged)"
    assert "$2b$" not in blob, "a bcrypt hash appeared in a log line"
    if jwt is not None:
        assert jwt not in blob, "the issued bearer token appeared in a log line"


def test_register_and_login_logs_carry_request_id_event_and_user(client, captured_logs):
    """register + login emit records carrying request_id and the expected event/user_id, no secrets."""
    register = client.post("/auth/register", json=_register_body())
    assert register.status_code == 201, register.text
    login = client.post("/auth/login", json=_login_body())
    assert login.status_code == 200, login.text
    jwt = login.json()["access_token"]

    events = _events(captured_logs)
    assert "register" in events, "no register log record emitted"
    assert "login_success" in events, "no login_success log record emitted"

    register_rec = events["register"]
    assert register_rec.user_id is not None
    assert isinstance(register_rec.request_id, str) and register_rec.request_id
    # The register event records only the email's domain — never the address or credential.
    assert getattr(register_rec, "email_domain", None) == _DOMAIN

    login_rec = events["login_success"]
    assert login_rec.user_id is not None
    assert isinstance(login_rec.request_id, str) and login_rec.request_id

    _assert_no_sensitive_data(captured_logs, jwt=jwt)


def test_rejected_login_logs_domain_error_warning_without_sensitive_data(client, captured_logs):
    """A rejected op (bad credentials → 401) logs a domain_error at WARNING with category + status, no secrets."""
    register = client.post("/auth/register", json=_register_body())
    assert register.status_code == 201, register.text

    rejected = client.post("/auth/login", json=_login_body("wrong-" + _PW))
    assert rejected.status_code == 401, rejected.text

    domain_errors = [r for r in captured_logs.records if getattr(r, "event", None) == "domain_error"]
    assert domain_errors, "no domain_error log record emitted for the rejected operation"
    rec = domain_errors[-1]
    assert rec.levelno == logging.WARNING
    assert rec.category == "unauthenticated"
    assert rec.status == 401
    assert isinstance(rec.request_id, str) and rec.request_id

    # Neither the real nor the attempted credential may appear, and the login_failure record
    # must not name which credential was wrong.
    _assert_no_sensitive_data(captured_logs)
    assert ("wrong-" + _PW) not in "\n".join(captured_logs.lines), "the attempted credential appeared in a log line"
