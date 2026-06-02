"""Category listing, creation, update, and deletion behavior.

All tests drive the public HTTP API through the shared ``client`` fixture (black-box).
The two DB-coupled deletion rules are exercised by seeding their preconditions straight
through ``db_session`` — the referencing expenses for the in-use guard, and a budget for
the cascade — because the expense and budget APIs are built in later phases; the seeded
rows share the test's session, so the category service sees them.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import DEFAULT_CATEGORIES
from app.models import Budget, Category, Expense

_DEFAULT_NAMES = {c["name"] for c in DEFAULT_CATEGORIES}


def _category_body(**overrides) -> dict:
    """Return a valid create/update body, with any field overridden for a specific case."""
    body = {"name": "Coffee", "icon": "cup", "color": "#6F4E37"}
    body.update(overrides)
    return body


def _create_category(client, headers, **overrides) -> dict:
    """Create a custom category through the API and return the response body."""
    resp = client.post("/categories", json=_category_body(**overrides), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- Listing --------------------------------------------------------------------------


def test_list_returns_the_seven_system_defaults(client, auth_headers):
    """A user with no custom categories sees exactly the seven shared system defaults."""
    resp = client.get("/categories", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 7
    names = {c["name"] for c in body["items"]}
    assert names == _DEFAULT_NAMES
    assert all(c["is_system"] for c in body["items"])


def test_list_requires_authentication(client):
    """Listing categories without a token is rejected as unauthenticated."""
    resp = client.get("/categories")
    assert resp.status_code == 401
    assert resp.json()["category"] == "unauthenticated"


def test_list_includes_own_custom_categories(client, auth_headers):
    """A created custom category appears in the owner's list alongside the defaults."""
    _create_category(client, auth_headers, name="Coffee")
    body = client.get("/categories", headers=auth_headers).json()
    assert body["total"] == 8
    assert "Coffee" in {c["name"] for c in body["items"]}


def test_list_does_not_show_another_users_custom_category(client, auth_headers, second_user):
    """A custom category is private to its owner; another user's list never shows it."""
    _create_category(client, second_user, name="Coffee")
    body = client.get("/categories", headers=auth_headers).json()
    assert body["total"] == 7  # only the shared defaults, not user 2's custom category
    assert "Coffee" not in {c["name"] for c in body["items"]}


# --- Ordering -------------------------------------------------------------------------


def test_list_orders_system_first_then_name_ascending(client, auth_headers):
    """Categories are ordered system-defaults first, then by name ascending within each group."""
    _create_category(client, auth_headers, name="Zucchini")
    _create_category(client, auth_headers, name="Apples")
    items = client.get("/categories", headers=auth_headers).json()["items"]

    system_flags = [c["is_system"] for c in items]
    assert system_flags == sorted(system_flags, reverse=True)  # is_system DESC: all True precede all False

    system_names = [c["name"] for c in items if c["is_system"]]
    custom_names = [c["name"] for c in items if not c["is_system"]]
    assert system_names == sorted(system_names)  # name ascending within the defaults
    assert custom_names == ["Apples", "Zucchini"]  # name ascending within the customs


# --- Pagination -----------------------------------------------------------------------


def test_list_returns_pagination_metadata(client, auth_headers):
    """The list endpoint returns the page envelope with total/limit/offset and a capped item count."""
    body = client.get("/categories?limit=5&offset=0", headers=auth_headers).json()
    assert body.keys() == {"items", "total", "limit", "offset", "count"}
    assert body["total"] == 7
    assert body["limit"] == 5
    assert body["offset"] == 0
    assert len(body["items"]) == 5  # bounded by limit
    assert body["count"] == 5  # items on this page, capped by limit


@pytest.mark.parametrize(
    "query",
    [
        "limit=101",  # over the max page size of 100
        "limit=0",  # below the minimum of 1
        "offset=-1",  # negative offset
        "limit=abc",  # non-integer
    ],
)
def test_list_rejects_malformed_pagination(client, auth_headers, query):
    """Malformed or over-max pagination parameters are rejected as validation errors."""
    resp = client.get(f"/categories?{query}", headers=auth_headers)
    assert resp.status_code == 422
    body = resp.json()
    assert body["category"] == "validation"
    assert body["field"] and body["reason"]  # names the offending parameter and why


# --- Creation -------------------------------------------------------------------------


def test_create_custom_category(client, auth_headers):
    """Creating a custom category returns it as a non-system category owned by the caller."""
    body = _create_category(client, auth_headers, name="Coffee", icon="cup", color="#6F4E37")
    assert body["name"] == "Coffee"
    assert body["icon"] == "cup"
    assert body["color"] == "#6F4E37"
    assert body["is_system"] is False
    owner_id = client.get("/users/me", headers=auth_headers).json()["id"]
    assert body["owner_id"] == owner_id


def test_create_requires_authentication(client):
    """Creating a category without a token is rejected as unauthenticated."""
    resp = client.post("/categories", json=_category_body())
    assert resp.status_code == 401
    assert resp.json()["category"] == "unauthenticated"


def test_create_duplicate_custom_name_is_conflict(client, auth_headers):
    """A second custom category with the same name (case-insensitively) is a conflict."""
    _create_category(client, auth_headers, name="Coffee")
    resp = client.post("/categories", json=_category_body(name="coffee"), headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["category"] == "conflict"


def test_create_name_colliding_with_a_default_is_conflict(client, auth_headers):
    """A custom name that duplicates a system default (case-insensitively) is a conflict."""
    resp = client.post("/categories", json=_category_body(name="food"), headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["category"] == "conflict"


def test_two_users_may_each_have_a_category_of_the_same_name(client, auth_headers, second_user):
    """Custom-name uniqueness is per user — two different users can both create "Coffee"."""
    _create_category(client, auth_headers, name="Coffee")
    resp = client.post("/categories", json=_category_body(name="Coffee"), headers=second_user)
    assert resp.status_code == 201, resp.text


# --- Update ---------------------------------------------------------------------------


def test_update_own_custom_category(client, auth_headers):
    """An owner can change the name, icon, and color of their own custom category."""
    created = _create_category(client, auth_headers, name="Coffee")
    resp = client.patch(
        f"/categories/{created['id']}",
        json={"name": "Espresso", "icon": "shot", "color": "#000000"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Espresso"
    assert body["icon"] == "shot"
    assert body["color"] == "#000000"


def test_rename_to_an_existing_name_is_conflict(client, auth_headers):
    """Renaming a category onto another visible name (case-insensitively) is a conflict."""
    _create_category(client, auth_headers, name="Coffee")
    other = _create_category(client, auth_headers, name="Tea")
    resp = client.patch(f"/categories/{other['id']}", json={"name": "coffee"}, headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["category"] == "conflict"


def test_update_system_default_is_forbidden(client, auth_headers):
    """Modifying a system default category is forbidden."""
    default_id = client.get("/categories", headers=auth_headers).json()["items"][0]["id"]
    resp = client.patch(f"/categories/{default_id}", json={"name": "Renamed"}, headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["category"] == "forbidden"


def test_update_another_users_category_is_not_found(client, auth_headers, second_user):
    """Updating another user's custom category reads as not-found, never disclosing it exists."""
    created = _create_category(client, second_user, name="Coffee")
    resp = client.patch(f"/categories/{created['id']}", json={"name": "Mine"}, headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["category"] == "not_found"


# --- Deletion -------------------------------------------------------------------------


def test_delete_unused_custom_category(client, auth_headers):
    """An owner can delete their own custom category when nothing references it."""
    created = _create_category(client, auth_headers, name="Coffee")
    resp = client.delete(f"/categories/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    remaining = {c["name"] for c in client.get("/categories", headers=auth_headers).json()["items"]}
    assert created["name"] not in remaining


def test_delete_system_default_is_forbidden(client, auth_headers):
    """Deleting a system default category is forbidden."""
    default_id = client.get("/categories", headers=auth_headers).json()["items"][0]["id"]
    resp = client.delete(f"/categories/{default_id}", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["category"] == "forbidden"


def test_delete_another_users_category_is_not_found(client, auth_headers, second_user):
    """Deleting another user's custom category reads as not-found."""
    created = _create_category(client, second_user, name="Coffee")
    resp = client.delete(f"/categories/{created['id']}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["category"] == "not_found"


def test_delete_in_use_category_is_blocked_with_count_and_advisory(client, auth_headers, db_session):
    """Deleting a category that still has expenses is blocked, naming the count and advising reassignment.

    The referencing expenses are seeded through the test session because the expense API
    arrives in a later phase; they share the session, so the deletion guard counts them.
    """
    created = _create_category(client, auth_headers, name="Coffee")
    owner_id = client.get("/users/me", headers=auth_headers).json()["id"]
    db_session.add_all(
        Expense(
            owner_id=owner_id,
            category_id=created["id"],
            amount=Decimal("5.00"),
            currency="USD",
            date=dt.date.today(),
        )
        for _ in range(3)
    )
    db_session.flush()

    resp = client.delete(f"/categories/{created['id']}", headers=auth_headers)
    assert resp.status_code == 409
    body = resp.json()
    assert body["category"] == "conflict"
    assert body["count"] == 3  # the blocking-expense count
    assert "reassign" in body["message"].lower()  # advises reassigning the expenses first


def test_delete_unused_category_also_removes_its_budgets(client, auth_headers, db_session):
    """Deleting an unused custom category also removes any budgets that referenced it.

    The budget is seeded through the test session (the budget API arrives in a later phase).
    After the delete it must be gone — verified by querying the session directly.
    """
    created = _create_category(client, auth_headers, name="Coffee")
    owner_id = client.get("/users/me", headers=auth_headers).json()["id"]
    db_session.add(
        Budget(
            owner_id=owner_id,
            category_id=created["id"],
            amount=Decimal("100.00"),
            month=6,
            year=2026,
        )
    )
    db_session.flush()

    resp = client.delete(f"/categories/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    remaining = db_session.execute(
        select(Budget.id).where(Budget.category_id == created["id"])
    ).first()
    assert remaining is None  # the budget was removed with its category
