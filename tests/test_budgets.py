"""Budget set/upsert, validation, listing, deletion, ownership isolation, and the
budget-exceeded warning surfaced on expense create/update.

Tests drive the HTTP API through the shared ``client`` fixture (black-box). Budgets used to
exercise the *expense* warning are seeded straight through ``db_session`` so those tests turn
purely on the warning logic, not on the budget write endpoint. The pure budget-warning math
helper is unit-tested directly (imported lazily, since it is added by the build task that
follows this test file).
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Budget, Category

_TODAY = dt.date.today()


def _budget_body(category_id, **overrides) -> dict:
    """Return a valid PUT /budgets body, with any field overridden for a specific case."""
    body = {"category_id": category_id, "amount": "100.00", "month": 6, "year": 2026}
    body.update(overrides)
    return body


def _put_budget(client, headers, category_id, **overrides):
    """Set/update a budget for the user against ``category_id`` and return the response."""
    return client.put("/budgets", json=_budget_body(category_id, **overrides), headers=headers)


def _create_expense(client, headers, category_id, **overrides):
    """POST one expense for the user against ``category_id`` and return the response."""
    body = {
        "amount": "42.50",
        "category_id": category_id,
        "date": _TODAY.isoformat(),
        "description": None,
        "receipt_url": None,
    }
    body.update(overrides)
    return client.post("/expenses", json=body, headers=headers)


@pytest.fixture
def food_category_id(db_session) -> int:
    """The id of the seeded "Food" system default — always accessible to every user."""
    return db_session.execute(
        select(Category.id).where(Category.name == "Food", Category.is_system.is_(True))
    ).scalar_one()


@pytest.fixture
def user_id(client, auth_headers) -> int:
    """The primary user's id."""
    return client.get("/users/me", headers=auth_headers).json()["id"]


@pytest.fixture
def other_user_category_id(client, second_user, db_session) -> int:
    """A custom category owned by a different user — inaccessible to the primary user.

    Seeded via the session with the real second user as owner, so it is a faithful cross-user case.
    """
    owner_id = client.get("/users/me", headers=second_user).json()["id"]
    category = Category(
        name="Second User Only", icon="x", color="#123456", is_system=False, owner_id=owner_id
    )
    db_session.add(category)
    db_session.flush()
    return category.id


def _seed_budget(db_session, owner_id, category_id, amount, month, year) -> None:
    """Insert a budget directly so a test can exercise the warning without the budget endpoint."""
    db_session.add(
        Budget(
            owner_id=owner_id,
            category_id=category_id,
            amount=Decimal(amount),
            month=month,
            year=year,
        )
    )
    db_session.flush()


# --- Set / upsert ---------------------------------------------------------------------


def test_set_budget_returns_the_saved_budget(client, auth_headers, food_category_id):
    """Setting a budget returns it with the amount as a string and the category embedded."""
    resp = _put_budget(client, auth_headers, food_category_id, amount="100.00", month=6, year=2026)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["amount"] == "100.00" and isinstance(body["amount"], str)
    assert body["month"] == 6 and body["year"] == 2026
    assert body["category"]["id"] == food_category_id
    assert "id" in body


def test_setting_an_existing_budget_updates_it_in_place(client, auth_headers, food_category_id):
    """Re-setting the same (category, month, year) updates the one budget rather than adding another."""
    _put_budget(client, auth_headers, food_category_id, amount="100.00", month=6, year=2026)
    _put_budget(client, auth_headers, food_category_id, amount="250.00", month=6, year=2026)

    items = client.get("/budgets", headers=auth_headers).json()["items"]
    june_food = [
        b for b in items if b["category"]["id"] == food_category_id and b["month"] == 6 and b["year"] == 2026
    ]
    assert len(june_food) == 1  # one-per-category-per-month
    assert june_food[0]["amount"] == "250.00"  # updated to the latest value


def test_zero_budget_is_allowed(client, auth_headers, food_category_id):
    """A budget of zero is accepted (only negative is rejected)."""
    resp = _put_budget(client, auth_headers, food_category_id, amount="0.00")
    assert resp.status_code == 200, resp.text
    assert resp.json()["amount"] == "0.00"


@pytest.mark.parametrize(
    "month, year",
    [(1, 2020), (12, 2030)],  # a past month and a future month
)
def test_budget_allowed_for_past_and_future_months(client, auth_headers, food_category_id, month, year):
    """Budgets can be set for past, present, or future months."""
    resp = _put_budget(client, auth_headers, food_category_id, month=month, year=year)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"amount": "-5.00"}, "amount"),  # negative rejected
        ({"amount": "1000000000.00"}, "amount"),  # over the 999,999,999.99 ceiling
        ({"amount": "100.555"}, "amount"),  # more than two decimal places
        ({"month": 0}, "month"),  # below 1
        ({"month": 13}, "month"),  # above 12
        ({"year": 0}, "year"),  # not a valid year
    ],
)
def test_set_budget_invalid_field_returns_422(
    client, auth_headers, food_category_id, overrides, field
):
    """Each invalid field is rejected as a validation error naming the offending field and reason."""
    resp = _put_budget(client, auth_headers, food_category_id, **overrides)
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["category"] == "validation"
    assert body["field"] == field
    assert body["reason"]


def test_set_budget_requires_a_token(client, food_category_id):
    """Setting a budget without a token is rejected as unauthenticated."""
    resp = client.put("/budgets", json=_budget_body(food_category_id))
    assert resp.status_code == 401
    assert resp.json()["category"] == "unauthenticated"


# --- Ownership / access ---------------------------------------------------------------


def test_set_budget_on_inaccessible_category_is_not_found(
    client, auth_headers, other_user_category_id
):
    """Budgeting against another user's category is reported as not-found (no disclosure)."""
    resp = _put_budget(client, auth_headers, other_user_category_id)
    assert resp.status_code == 404
    assert resp.json()["category"] == "not_found"


def test_users_cannot_delete_each_others_budgets(
    client, auth_headers, second_user, food_category_id, db_session
):
    """Deleting another user's budget reads as not-found; the budget endpoints are owner-scoped."""
    second_id = client.get("/users/me", headers=second_user).json()["id"]
    budget = Budget(
        owner_id=second_id, category_id=food_category_id, amount=Decimal("100.00"), month=6, year=2026
    )
    db_session.add(budget)
    db_session.flush()

    resp = client.delete(f"/budgets/{budget.id}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["category"] == "not_found"


# --- List / delete --------------------------------------------------------------------


def test_list_orders_by_year_then_month_descending(client, auth_headers, food_category_id):
    """Budgets list newest-period first: year descending, then month descending."""
    _put_budget(client, auth_headers, food_category_id, month=6, year=2025)
    _put_budget(client, auth_headers, food_category_id, month=1, year=2026)
    _put_budget(client, auth_headers, food_category_id, month=3, year=2026)

    items = client.get("/budgets", headers=auth_headers).json()["items"]
    assert [(b["year"], b["month"]) for b in items] == [(2026, 3), (2026, 1), (2025, 6)]


def test_list_breaks_ties_within_a_month_by_id_descending(
    client, auth_headers, food_category_id, db_session
):
    """Two budgets in the same month/year (different categories) order by id descending — a stable tiebreak."""
    transport_id = db_session.execute(
        select(Category.id).where(Category.name == "Transport", Category.is_system.is_(True))
    ).scalar_one()
    first_id = _put_budget(client, auth_headers, food_category_id, month=6, year=2026).json()["id"]
    second_id = _put_budget(client, auth_headers, transport_id, month=6, year=2026).json()["id"]

    same_period = [
        b["id"] for b in client.get("/budgets", headers=auth_headers).json()["items"]
        if b["year"] == 2026 and b["month"] == 6
    ]
    assert same_period == sorted(same_period, reverse=True)  # id DESC tiebreak
    assert same_period[0] == max(first_id, second_id)  # the later-created budget comes first


def test_list_budgets_paginates_with_metadata(client, auth_headers, food_category_id):
    """A page returns its items plus total/limit/offset metadata."""
    for month in (1, 2, 3):
        _put_budget(client, auth_headers, food_category_id, month=month, year=2026)

    first = client.get("/budgets", params={"limit": 2, "offset": 0}, headers=auth_headers).json()
    assert first.keys() == {"items", "total", "limit", "offset"}
    assert first["total"] == 3 and first["limit"] == 2 and first["offset"] == 0
    assert len(first["items"]) == 2


@pytest.mark.parametrize(
    "params, field",
    [
        ({"limit": 101}, "limit"),  # over the max page size of 100
        ({"limit": "abc"}, "limit"),  # non-integer
        ({"offset": -1}, "offset"),  # negative offset
    ],
)
def test_list_budgets_rejects_malformed_pagination(client, auth_headers, params, field):
    """Out-of-range or non-integer pagination params are rejected, bounding the result set."""
    resp = client.get("/budgets", params=params, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["field"] == field


def test_delete_budget(client, auth_headers, food_category_id):
    """An owner can delete their budget; it then no longer appears in the list."""
    budget_id = _put_budget(client, auth_headers, food_category_id).json()["id"]
    assert client.delete(f"/budgets/{budget_id}", headers=auth_headers).status_code == 204
    items = client.get("/budgets", headers=auth_headers).json()["items"]
    assert all(b["id"] != budget_id for b in items)


def test_list_budgets_requires_a_token(client):
    """Listing budgets without a token is rejected as unauthenticated."""
    resp = client.get("/budgets")
    assert resp.status_code == 401
    assert resp.json()["category"] == "unauthenticated"


# --- Budget-exceeded warning on expense create / update -------------------------------


def test_creating_an_expense_over_budget_returns_a_warning(
    client, auth_headers, food_category_id, db_session, user_id
):
    """An expense pushing the month's category total over budget carries a budget warning.

    The warning reports the category name, the budget, the month's spend, and the overage —
    all as strings, like every other amount.
    """
    _seed_budget(db_session, user_id, food_category_id, "100.00", _TODAY.month, _TODAY.year)
    resp = _create_expense(client, auth_headers, food_category_id, amount="142.50", date=_TODAY.isoformat())
    assert resp.status_code == 201, resp.text
    warning = resp.json()["budget_warning"]
    assert warning["category_name"] == "Food"
    assert warning["budget"] == "100.00"
    assert warning["spent"] == "142.50"
    assert warning["exceeded_by"] == "42.50"


def test_expense_at_or_below_budget_has_no_warning(
    client, auth_headers, food_category_id, db_session, user_id
):
    """An expense whose month total equals the budget (not strictly over) carries no warning."""
    _seed_budget(db_session, user_id, food_category_id, "100.00", _TODAY.month, _TODAY.year)
    resp = _create_expense(client, auth_headers, food_category_id, amount="100.00", date=_TODAY.isoformat())
    assert resp.status_code == 201, resp.text
    assert "budget_warning" not in resp.json()


def test_updating_an_expense_over_budget_returns_a_warning(
    client, auth_headers, food_category_id, db_session, user_id
):
    """Updating an expense so the month total exceeds the budget carries the warning on the update too."""
    _seed_budget(db_session, user_id, food_category_id, "100.00", _TODAY.month, _TODAY.year)
    created = _create_expense(client, auth_headers, food_category_id, amount="50.00", date=_TODAY.isoformat())
    assert created.status_code == 201, created.text
    assert "budget_warning" not in created.json()  # 50 is at/below the 100 budget

    expense_id = created.json()["id"]
    updated = client.patch(f"/expenses/{expense_id}", json={"amount": "142.50"}, headers=auth_headers)
    assert updated.status_code == 200, updated.text
    warning = updated.json()["budget_warning"]
    assert warning["spent"] == "142.50"
    assert warning["exceeded_by"] == "42.50"


def test_budget_warning_uses_the_expense_month_not_the_current_month(
    client, auth_headers, food_category_id, db_session, user_id
):
    """The warning checks the expense's own month — a back-dated expense uses that month's budget.

    A budget is set only for a past month; an expense dated in that month warns against it, while
    an expense in the current month (which has no budget) does not.
    """
    _seed_budget(db_session, user_id, food_category_id, "100.00", 1, 2020)

    back_dated = _create_expense(client, auth_headers, food_category_id, amount="142.50", date="2020-01-15")
    assert back_dated.status_code == 201, back_dated.text
    assert back_dated.json()["budget_warning"]["exceeded_by"] == "42.50"

    current = _create_expense(client, auth_headers, food_category_id, amount="500.00", date=_TODAY.isoformat())
    assert current.status_code == 201, current.text
    assert "budget_warning" not in current.json()  # no budget for the current month


# --- Unit: the pure budget-warning math -----------------------------------------------


def test_budget_warning_math_warns_only_when_strictly_over_budget():
    """The warning helper returns a warning iff spend strictly exceeds budget; exceeded_by = spent - budget."""
    from app.services import compute_budget_warning

    assert compute_budget_warning("Food", Decimal("100.00"), Decimal("50.00")) is None  # below
    assert compute_budget_warning("Food", Decimal("100.00"), Decimal("100.00")) is None  # exactly at budget

    warning = compute_budget_warning("Food", Decimal("100.00"), Decimal("142.50"))
    assert warning is not None
    assert warning.category_name == "Food"
    assert warning.budget == Decimal("100.00")
    assert warning.spent == Decimal("142.50")
    assert warning.exceeded_by == Decimal("42.50")
