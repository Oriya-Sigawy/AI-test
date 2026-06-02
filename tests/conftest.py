"""Shared pytest fixtures: test-DB schema + seed, per-test rollback, HTTP client, auth.

Tests run against a dedicated Postgres ``TEST_DATABASE_URL`` — never the dev/prod DB.
A session-scoped fixture builds the schema and seeds the seven default categories once.
Each test then runs inside an outer transaction on its
own connection that is rolled back at teardown, so tests are independent. The app's
``get_db`` is overridden to yield that same session; because services call
``session.commit()``, the session joins the outer transaction in ``create_savepoint`` mode,
so those commits land on savepoints and the single outer ``rollback()`` still wipes everything.
"""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import DEFAULT_CATEGORIES
from app.database import Base, get_db
from app.models import Category
from app.main import app

if not os.environ.get("TEST_DATABASE_URL"):
    raise RuntimeError("TEST_DATABASE_URL must be set to run the tests (see .env.example).")

# Dedicated test engine — never the app's DATABASE_URL engine. Lazy: no connection is opened
# until a fixture uses it.
_test_engine = create_engine(os.environ["TEST_DATABASE_URL"])

_TEST_PASSWORD = "correct horse battery staple"  # test-only credential; not a real secret


@pytest.fixture(scope="session", autouse=True)
def _schema_and_seed():
    """Build a pristine schema on the test DB and seed the default categories once per run.

    Drops then recreates every table so a leftover row from an aborted run can't skew tests —
    system defaults share a NULL owner, which the partial unique index deliberately does not
    cover, so a duplicate default would otherwise go uncaught. The seed is committed, so it is
    visible to each per-test connection and survives the per-test rollback.
    """
    Base.metadata.drop_all(_test_engine)
    Base.metadata.create_all(_test_engine)
    with Session(_test_engine) as session:
        session.add_all(
            Category(name=c["name"], icon=c["icon"], color=c["color"], is_system=True)
            for c in DEFAULT_CATEGORIES
        )
        session.commit()
    yield
    Base.metadata.drop_all(_test_engine)


@pytest.fixture
def db_session():
    """Yield a Session in an outer transaction that is rolled back after the test, so tests are independent."""
    connection = _test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    """Yield a TestClient whose ``get_db`` yields the test's ``db_session``.

    The app lifespan is intentionally not started, so the app's own startup create_all/seed
    never runs against the non-test engine; the schema/seed fixture owns that on the test DB.
    """
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _register_and_login(client: TestClient, email: str) -> dict[str, str]:
    """Register a user and return their ``Authorization`` Bearer header.

    email: must be unique per logged-in user so registrations don't collide within a test.
    """
    register = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": _TEST_PASSWORD,
            "display_name": email.split("@")[0],
            "default_currency": "USD",
        },
    )
    assert register.status_code == 201, register.text
    login = client.post("/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    """Bearer auth header for a registered, logged-in primary user."""
    return _register_and_login(client, "user1@example.com")


@pytest.fixture
def second_user(client: TestClient) -> dict[str, str]:
    """Bearer auth header for a distinct second user, for cross-user isolation tests."""
    return _register_and_login(client, "user2@example.com")
