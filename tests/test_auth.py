"""Authentication and profile behavior, plus the cross-cutting 500 handler and the
security helpers (password hashing, JWT) that auth is built on.

Most tests drive the HTTP API through the shared ``client`` fixture. The password and JWT
helpers are pure functions, so they are unit-tested directly (and imported lazily inside
those tests, since the ``security`` module is built after this test file). The
currency-change guard test seeds a blocking expense straight through ``db_session`` because
the expense API does not exist yet at this point in the build.
"""

import datetime as dt
import logging
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.errors import Unauthenticated
from app.main import app
from app.models import Category, Expense

_VALID_PASSWORD = "correct horse battery staple"  # test-only credential; not a real secret


def _registration(**overrides) -> dict:
    """Return a valid registration body, with any field overridden for a negative case."""
    body = {
        "email": "sam@example.com",
        "password": _VALID_PASSWORD,
        "display_name": "Sam",
        "default_currency": "USD",
    }
    body.update(overrides)
    return body


# --- Registration ---------------------------------------------------------------------


def test_register_hides_password_and_uppercases_currency(client):
    """Registering returns the public profile, never echoes the password, upper-cases currency, and issues no token.

    Registration creates the account but does not authenticate it (FR-001) — the token is
    obtained only by logging in, so no ``access_token`` may appear in the response.
    """
    resp = client.post("/auth/register", json=_registration(default_currency="usd"))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "sam@example.com"
    assert body["display_name"] == "Sam"
    assert body["default_currency"] == "USD"  # normalized from "usd"
    assert "id" in body
    assert "password" not in body and "password_hash" not in body
    assert "access_token" not in body  # registration does not issue a token (FR-001)
    assert _VALID_PASSWORD not in resp.text


def test_register_duplicate_email_is_conflict(client):
    """A second registration of the same email (case-insensitively) is rejected as a conflict."""
    first = client.post("/auth/register", json=_registration(email="Dup@Example.com"))
    assert first.status_code == 201, first.text
    resp = client.post("/auth/register", json=_registration(email="dup@example.com"))
    assert resp.status_code == 409
    assert resp.json()["category"] == "conflict"


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"password": "short"}, "password"),  # under 8 characters
        ({"password": "a" * 129}, "password"),  # over 128 characters
        ({"default_currency": "US"}, "default_currency"),  # not exactly three letters
        ({"email": "not-an-email"}, "email"),  # missing "@" and domain
    ],
)
def test_register_invalid_field_returns_422(client, overrides, field):
    """Malformed registration fields are rejected as validation errors naming the bad field."""
    resp = client.post("/auth/register", json=_registration(**overrides))
    assert resp.status_code == 422
    body = resp.json()
    assert body["category"] == "validation"
    assert body["field"] == field
    assert body["reason"]  # a human-readable reason is always present


# --- Login ----------------------------------------------------------------------------


def test_login_returns_a_bearer_token(client):
    """Correct credentials exchange for a bearer access token."""
    client.post("/auth/register", json=_registration())
    resp = client.post("/auth/login", json={"email": "sam@example.com", "password": _VALID_PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


@pytest.mark.parametrize(
    "credentials",
    [
        {"email": "sam@example.com", "password": "the wrong password"},  # right user, wrong password
        {"email": "nobody@example.com", "password": _VALID_PASSWORD},  # unknown email
    ],
)
def test_login_bad_credentials_are_unauthorized(client, credentials):
    """Wrong password and unknown email are both rejected as unauthenticated, with no token."""
    client.post("/auth/register", json=_registration())
    resp = client.post("/auth/login", json=credentials)
    assert resp.status_code == 401
    assert resp.json()["category"] == "unauthenticated"
    assert "access_token" not in resp.json()


def test_login_failure_does_not_reveal_which_credential_was_wrong(client):
    """A wrong password and an unknown email return the identical generic message (no enumeration)."""
    client.post("/auth/register", json=_registration())
    wrong_password_resp = client.post(
        "/auth/login", json={"email": "sam@example.com", "password": "nope nope nope"}
    )
    unknown_email_resp = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": _VALID_PASSWORD}
    )
    assert wrong_password_resp.status_code == unknown_email_resp.status_code == 401
    assert wrong_password_resp.json()["message"] == unknown_email_resp.json()["message"]


def test_login_unknown_email_still_runs_password_verification(client, monkeypatch):
    """An unknown email triggers a bcrypt verify too, so response time can't distinguish it from a
    wrong password — closing the user-enumeration timing side-channel (OWASP A07).

    Asserted by behavior, not wall-clock: ``verify_password`` must be called exactly once, against
    the dummy hash, even though no account matches the email.
    """
    import app.services as services

    real_verify = services.verify_password
    seen_hashes: list[str] = []
    monkeypatch.setattr(
        services,
        "verify_password",
        lambda password, password_hash: seen_hashes.append(password_hash)
        or real_verify(password, password_hash),
    )

    resp = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": _VALID_PASSWORD}
    )
    assert resp.status_code == 401
    assert seen_hashes == [services.DUMMY_PASSWORD_HASH]


# --- Token-protected access -----------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},  # no Authorization header
        {"Authorization": "Bearer not-a-real-token"},  # malformed token
    ],
)
def test_protected_route_rejects_missing_or_malformed_token(client, headers):
    """A protected endpoint rejects a request with no token or an unparseable one."""
    resp = client.get("/users/me", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["category"] == "unauthenticated"


def test_protected_route_rejects_expired_token(client, monkeypatch):
    """A correctly-signed but expired token is rejected as unauthenticated."""
    from app.security import create_access_token

    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)  # mints an already-expired token
    expired = create_access_token(1)
    resp = client.get("/users/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401
    assert resp.json()["category"] == "unauthenticated"


def test_protected_route_rejects_token_for_unknown_user(client):
    """A validly-signed, unexpired token whose user no longer exists is rejected as unauthenticated."""
    from app.security import create_access_token

    token = create_access_token(999_999)  # no account has this id
    resp = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["category"] == "unauthenticated"


# --- Profile (get / update) -----------------------------------------------------------


def test_get_profile_returns_the_current_user(client, auth_headers):
    """The profile endpoint returns the authenticated user's details and no password."""
    resp = client.get("/users/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "user1@example.com"
    assert {"id", "display_name", "default_currency"} <= body.keys()
    assert "password" not in body and "password_hash" not in body


def test_update_display_name(client, auth_headers):
    """The display name can be updated at any time."""
    resp = client.patch("/users/me", json={"display_name": "Renamed"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Renamed"


def test_currency_change_allowed_before_any_expense(client, auth_headers):
    """The default currency can be changed (and is normalized) while the user has no expenses."""
    resp = client.patch("/users/me", json={"default_currency": "eur"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_currency"] == "EUR"


def test_email_is_immutable(client, auth_headers):
    """An email supplied to the profile update is ignored; the address never changes."""
    resp = client.patch(
        "/users/me",
        json={"email": "changed@example.com", "display_name": "Still Me"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "user1@example.com"  # unchanged
    assert body["display_name"] == "Still Me"  # the allowed field still applied


def test_currency_change_blocked_once_an_expense_exists(client, auth_headers, db_session):
    """Once the user has any expense, changing the default currency is a conflict.

    The expense is seeded directly through the session because the expense API arrives in a
    later phase; it shares the test's session, so the currency guard sees it.
    """
    user_id = client.get("/users/me", headers=auth_headers).json()["id"]
    category_id = db_session.execute(
        select(Category.id).where(Category.is_system.is_(True)).limit(1)
    ).scalar_one()
    db_session.add(
        Expense(
            owner_id=user_id,
            category_id=category_id,
            amount=Decimal("5.00"),
            currency="USD",
            date=dt.date.today(),
        )
    )
    db_session.flush()

    resp = client.patch("/users/me", json={"default_currency": "EUR"}, headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["category"] == "conflict"


# --- Cross-cutting: the unexpected-error (500) handler --------------------------------


@pytest.fixture
def boom_route():
    """Temporarily mount an endpoint that raises an unhandled error, then remove it.

    Exercising the global 500 handler needs a route that fails; mounting a throwaway one
    keeps the test independent of which real endpoints happen to exist yet. The route is
    stripped on teardown so no other test can reach it.
    """
    path = "/_test_only_boom"
    leak = "internal-detail-that-must-not-reach-the-client"

    async def _boom():
        raise RuntimeError(leak)

    app.add_api_route(path, _boom, methods=["GET"])
    try:
        yield path, leak
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != path]


def test_unhandled_error_returns_generic_500_and_logs_server_side(boom_route, caplog):
    """An unexpected exception yields a generic 500 that leaks nothing and is logged at ERROR."""
    path, leak = boom_route
    # raise_server_exceptions=False so the client returns the 500 response rather than
    # re-raising the exception that the outer error middleware re-raises after responding.
    local_client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        resp = local_client.get(path)

    assert resp.status_code == 500
    assert resp.json() == {"message": "Internal server error", "category": "unexpected"}
    # neither the exception detail nor a stack trace may appear in the response body
    assert leak not in resp.text
    assert "RuntimeError" not in resp.text and "Traceback" not in resp.text
    # the failure is recorded server-side
    assert any(
        getattr(record, "event", None) == "domain_error" and record.levelno == logging.ERROR
        for record in caplog.records
    )


# --- Cross-cutting: interactive API docs gating (OWASP A05) ---------------------------


def test_docs_are_served_by_default(client):
    """With the default configuration the interactive docs and schema are reachable."""
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_can_be_disabled():
    """Turning docs off removes ``/docs``, ``/redoc`` and ``/openapi.json`` (404), so a hardened
    deployment need not expose its schema or interactive console (OWASP A05)."""
    from fastapi import FastAPI

    from app.main import _docs_urls

    disabled = TestClient(FastAPI(**_docs_urls(enabled=False)))
    assert disabled.get("/docs").status_code == 404
    assert disabled.get("/redoc").status_code == 404
    assert disabled.get("/openapi.json").status_code == 404


# --- Unit: security helpers (pure functions) ------------------------------------------


def test_password_hash_and_verify_round_trip():
    """A hashed password verifies against the original and rejects a different one."""
    from app.security import hash_password, verify_password

    hashed = hash_password(_VALID_PASSWORD)
    assert hashed != _VALID_PASSWORD  # never stored in the clear
    assert verify_password(_VALID_PASSWORD, hashed) is True
    assert verify_password("a different password", hashed) is False


def test_password_hashing_distinguishes_passwords_beyond_72_bytes():
    """Passwords identical in their first 72 bytes but differing after are still told apart.

    bcrypt alone truncates input at 72 bytes; the SHA-256 pre-hash is what defeats that.
    """
    from app.security import hash_password, verify_password

    base = "a" * 72
    hashed = hash_password(base + "ONE")
    assert verify_password(base + "ONE", hashed) is True
    assert verify_password(base + "TWO", hashed) is False


def test_jwt_round_trips_the_user_id():
    """Encoding then decoding a token returns the original user id as an int."""
    from app.security import create_access_token, decode_access_token

    assert decode_access_token(create_access_token(123)) == 123


def test_jwt_expired_token_is_rejected(monkeypatch):
    """An expired token is rejected by the decoder."""
    from app.security import create_access_token, decode_access_token

    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
    expired = create_access_token(123)
    with pytest.raises(Unauthenticated):
        decode_access_token(expired)


def test_jwt_tampered_token_is_rejected():
    """A token whose signature has been altered is rejected by the decoder."""
    from app.security import create_access_token, decode_access_token

    token = create_access_token(123)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(Unauthenticated):
        decode_access_token(tampered)
