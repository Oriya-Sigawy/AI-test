"""Expense CRUD, validation, filtering, ownership isolation, and pagination behavior.

Tests drive the HTTP API through the shared ``client`` fixture (black-box). Default and
other-user categories are read/seeded straight through ``db_session`` because the category
API arrives in a later phase; the client and db_session share one session, so seeded rows
are visible to the API. The pure date-bound helper is unit-tested directly (imported lazily,
since it is added with the expense build task that follows this test file).
"""

import datetime as dt

import pytest
from sqlalchemy import select

from app.models import Category

_TODAY = dt.date.today()


def _expense_body(**overrides) -> dict:
    """Return a valid expense-creation body, with any field overridden for a negative case."""
    body = {
        "amount": "42.50",
        "category_id": None,  # filled in by the test from a real category id
        "date": _TODAY.isoformat(),
        "description": "Groceries",
        "receipt_url": None,
    }
    body.update(overrides)
    return body


@pytest.fixture
def food_category_id(db_session) -> int:
    """The id of the seeded "Food" system default — an always-accessible category for every user."""
    return db_session.execute(
        select(Category.id).where(Category.name == "Food", Category.is_system.is_(True))
    ).scalar_one()


@pytest.fixture
def other_user_category_id(client, second_user, db_session) -> int:
    """A custom category owned by a *different* user — inaccessible to the primary user.

    Seeded via the session because the category API does not exist yet; its owner is the
    real second user so the row is a faithful cross-user case.
    """
    owner_id = client.get("/users/me", headers=second_user).json()["id"]
    category = Category(
        name="Second User Only", icon="x", color="#123456", is_system=False, owner_id=owner_id
    )
    db_session.add(category)
    db_session.flush()
    return category.id


def _create(client, auth_headers, category_id, **overrides):
    """POST one expense for the primary user against ``category_id`` and return the response."""
    return client.post(
        "/expenses", json=_expense_body(category_id=category_id, **overrides), headers=auth_headers
    )


# --- Create ---------------------------------------------------------------------------


def test_create_expense_against_default_category(client, auth_headers, food_category_id):
    """Creating an expense against a default category returns it with the amount as a string.

    Amounts are serialized as JSON strings (e.g. ``"42.50"``) so a client's float round-trip
    can't perturb the stored value; the category is embedded as a nested object.
    """
    resp = _create(client, auth_headers, food_category_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["amount"] == "42.50" and isinstance(body["amount"], str)
    assert body["currency"] == "USD"  # the owner's default
    assert body["category"]["id"] == food_category_id
    assert body["category"]["name"] == "Food"
    assert body["date"] == _TODAY.isoformat()
    assert {"id", "created_at", "updated_at"} <= body.keys()
    assert "budget_warning" not in body  # no budget set → no warning


def test_create_expense_accepts_exactly_seven_days_ahead(client, auth_headers, food_category_id):
    """A date exactly 7 days in the future (the inclusive boundary) is accepted."""
    seven_ahead = (_TODAY + dt.timedelta(days=7)).isoformat()
    resp = _create(client, auth_headers, food_category_id, date=seven_ahead)
    assert resp.status_code == 201, resp.text
    assert resp.json()["date"] == seven_ahead


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"amount": "0.00"}, "amount"),  # zero rejected (must be > 0)
        ({"amount": "-5.00"}, "amount"),  # negative rejected
        ({"amount": "1000000000.00"}, "amount"),  # over the 999,999,999.99 ceiling
        ({"amount": "42.555"}, "amount"),  # more than two decimal places
        ({"date": (_TODAY + dt.timedelta(days=8)).isoformat()}, "date"),  # > 7 days ahead
        ({"description": "x" * 501}, "description"),  # over 500 characters
        ({"receipt_url": "not a url at all"}, "receipt_url"),  # malformed URL
    ],
)
def test_create_expense_invalid_field_returns_422(
    client, auth_headers, food_category_id, overrides, field
):
    """Each invalid field is rejected as a validation error naming the offending field and reason."""
    resp = _create(client, auth_headers, food_category_id, **overrides)
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["category"] == "validation"
    assert body["field"] == field
    assert body["reason"]  # a human-readable reason is always present


def test_create_expense_against_inaccessible_category_is_not_found(
    client, auth_headers, other_user_category_id
):
    """Creating an expense against another user's category is reported as not-found (no disclosure)."""
    resp = _create(client, auth_headers, other_user_category_id)
    assert resp.status_code == 404
    assert resp.json()["category"] == "not_found"


def test_create_expense_ignores_client_supplied_currency(client, auth_headers, food_category_id):
    """A client-supplied currency is ignored; the expense is stored in the owner's default (FR-017)."""
    resp = _create(client, auth_headers, food_category_id, currency="EUR")
    assert resp.status_code == 201, resp.text
    assert resp.json()["currency"] == "USD"


def test_create_expense_requires_a_token(client, food_category_id):
    """The expense collection is protected: a request with no token is rejected as unauthenticated."""
    resp = client.post("/expenses", json=_expense_body(category_id=food_category_id))
    assert resp.status_code == 401
    assert resp.json()["category"] == "unauthenticated"


# --- List, filter, and pagination -----------------------------------------------------


def test_list_expenses_filters_by_date_category_and_amount(
    client, auth_headers, db_session, food_category_id
):
    """List filters narrow results by date range, category, and amount range."""
    transport_id = db_session.execute(
        select(Category.id).where(Category.name == "Transport", Category.is_system.is_(True))
    ).scalar_one()
    # Three expenses spread across dates, categories, and amounts.
    _create(client, auth_headers, food_category_id, amount="10.00", date="2026-01-15")
    _create(client, auth_headers, food_category_id, amount="200.00", date="2026-03-15")
    _create(client, auth_headers, transport_id, amount="50.00", date="2026-02-15")

    by_category = client.get(
        "/expenses", params={"category_id": transport_id}, headers=auth_headers
    ).json()
    assert by_category["total"] == 1
    assert by_category["items"][0]["category"]["id"] == transport_id

    by_date = client.get(
        "/expenses", params={"date_from": "2026-02-01", "date_to": "2026-02-28"}, headers=auth_headers
    ).json()
    assert by_date["total"] == 1
    assert by_date["items"][0]["date"] == "2026-02-15"

    by_amount = client.get(
        "/expenses", params={"amount_min": "100.00"}, headers=auth_headers
    ).json()
    assert by_amount["total"] == 1
    assert by_amount["items"][0]["amount"] == "200.00"


@pytest.mark.parametrize(
    "params, field",
    [
        ({"date_from": "2026-06-10", "date_to": "2026-06-01"}, {"date_from", "date_to"}),
        ({"amount_min": "100.00", "amount_max": "10.00"}, {"amount_min", "amount_max"}),
    ],
)
def test_list_expenses_rejects_inverted_ranges(client, auth_headers, params, field):
    """An inverted date or amount range is rejected as a validation error naming a bound."""
    resp = client.get("/expenses", params=params, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["category"] == "validation"
    assert body["field"] in field
    assert body["reason"]


def test_list_expenses_paginates_with_metadata(client, auth_headers, food_category_id):
    """A page returns its items plus ``total``/``limit``/``offset`` metadata (FR-035)."""
    for n in range(3):
        _create(client, auth_headers, food_category_id, amount=f"{n + 1}.00")

    first = client.get("/expenses", params={"limit": 2, "offset": 0}, headers=auth_headers).json()
    assert first["total"] == 3 and first["limit"] == 2 and first["offset"] == 0
    assert len(first["items"]) == 2
    assert first["count"] == 2  # items returned on this page (a full page)

    second = client.get("/expenses", params={"limit": 2, "offset": 2}, headers=auth_headers).json()
    assert second["total"] == 3 and len(second["items"]) == 1
    assert second["count"] == 1  # last, partial page: fewer than the limit


@pytest.mark.parametrize(
    "params, field",
    [
        ({"limit": 101}, "limit"),  # over the max page size of 100
        ({"limit": "abc"}, "limit"),  # non-integer
        ({"offset": -1}, "offset"),  # negative offset
    ],
)
def test_list_expenses_rejects_malformed_pagination(client, auth_headers, params, field):
    """Out-of-range or non-integer pagination params are rejected, bounding the result set."""
    resp = client.get("/expenses", params=params, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["field"] == field


# --- Get, update, delete --------------------------------------------------------------


def test_get_update_delete_round_trip(client, auth_headers, food_category_id):
    """An owner can fetch, update, and delete their expense; the deleted one then reads as gone."""
    created = _create(client, auth_headers, food_category_id).json()
    expense_id = created["id"]

    got = client.get(f"/expenses/{expense_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["id"] == expense_id

    updated = client.patch(
        f"/expenses/{expense_id}", json={"amount": "99.99"}, headers=auth_headers
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["amount"] == "99.99"

    deleted = client.delete(f"/expenses/{expense_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get(f"/expenses/{expense_id}", headers=auth_headers).status_code == 404


def test_update_expense_re_applies_creation_validation(client, auth_headers, food_category_id):
    """Updating with an invalid amount is rejected — update re-applies all creation validations (FR-022)."""
    expense_id = _create(client, auth_headers, food_category_id).json()["id"]
    resp = client.patch(f"/expenses/{expense_id}", json={"amount": "-1.00"}, headers=auth_headers)
    assert resp.status_code == 422
    body = resp.json()
    assert body["category"] == "validation" and body["field"] == "amount" and body["reason"]


def test_users_cannot_reach_each_others_expenses(
    client, auth_headers, second_user, food_category_id
):
    """A user gets 404 (not 403) on another user's expense for get, update, and delete (FR-023)."""
    expense_id = _create(client, auth_headers, food_category_id).json()["id"]

    assert client.get(f"/expenses/{expense_id}", headers=second_user).status_code == 404
    assert (
        client.patch(
            f"/expenses/{expense_id}", json={"amount": "1.00"}, headers=second_user
        ).status_code
        == 404
    )
    assert client.delete(f"/expenses/{expense_id}", headers=second_user).status_code == 404
    # The owner still sees it untouched.
    assert client.get(f"/expenses/{expense_id}", headers=auth_headers).status_code == 200


# --- Unit: the pure date-bound helper -------------------------------------------------


def test_date_bound_helper_accepts_today_and_seven_days_ahead():
    """The date-bound helper accepts today and exactly 7 days ahead, with the reference date injected."""
    from app.schemas import validate_expense_date

    today = dt.date(2026, 6, 1)
    assert validate_expense_date(today, today=today) == today
    seven = today + dt.timedelta(days=7)
    assert validate_expense_date(seven, today=today) == seven


def test_date_bound_helper_rejects_eight_days_ahead():
    """The helper rejects a date 8 days ahead (just past the inclusive 7-day bound)."""
    from app.schemas import validate_expense_date

    today = dt.date(2026, 6, 1)
    with pytest.raises(ValueError):
        validate_expense_date(today + dt.timedelta(days=8), today=today)
