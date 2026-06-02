"""Spending reports: monthly summary, multi-month trend, and budget status.

Tests drive the HTTP API through the shared ``client`` fixture; expenses are created through
the real expense API and budgets are seeded straight through ``db_session`` (the budget API
arrives in a later phase). All amounts are returned as JSON strings (SC-006). The pure
trend month-window helper is unit-tested directly (imported lazily, since it is added with
the report build task that follows this test file). All report dates are kept in the past so
the expense future-date bound never interferes.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Budget, Category


def _category_id(db_session, name: str) -> int:
    """The id of the named system-default category (always accessible to every user)."""
    return db_session.execute(
        select(Category.id).where(Category.name == name, Category.is_system.is_(True))
    ).scalar_one()


def _add_expense(client, auth_headers, category_id: int, amount: str, date: str) -> None:
    """Create one expense for the primary user via the public API, asserting it succeeds."""
    resp = client.post(
        "/expenses",
        json={"amount": amount, "category_id": category_id, "date": date},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text


# --- Monthly summary ------------------------------------------------------------------


def test_monthly_summary_total_equals_sum_and_breakdown_is_non_zero_only(
    client, auth_headers, db_session
):
    """The month's total equals the sum of its expenses; the breakdown lists only spent categories.

    Expenses in another month are excluded, and a category with no spend that month never
    appears in the breakdown (spec Clarification: non-zero categories only).
    """
    food = _category_id(db_session, "Food")
    transport = _category_id(db_session, "Transport")
    _add_expense(client, auth_headers, food, "10.00", "2026-04-10")
    _add_expense(client, auth_headers, food, "30.00", "2026-04-15")
    _add_expense(client, auth_headers, transport, "50.00", "2026-04-20")
    _add_expense(client, auth_headers, food, "999.00", "2026-03-10")  # different month, excluded

    body = client.get(
        "/reports/monthly-summary", params={"month": 4, "year": 2026}, headers=auth_headers
    ).json()

    assert body["month"] == 4 and body["year"] == 2026
    assert body["total"] == "90.00" and isinstance(body["total"], str)
    by_name = {row["category"]["name"]: row["total"] for row in body["by_category"]}
    assert by_name == {"Food": "40.00", "Transport": "50.00"}  # March spend excluded
    # Breakdown sums back to the reported total (SC-006), and every amount is a string.
    assert sum(Decimal(t) for t in by_name.values()) == Decimal(body["total"])
    assert all(isinstance(t, str) for t in by_name.values())


# --- Trend ----------------------------------------------------------------------------


def test_trend_defaults_to_six_months_and_zero_fills_empty_months(
    client, auth_headers, db_session
):
    """The trend defaults to six months ending at the given month, oldest→newest, zero-filling gaps."""
    food = _category_id(db_session, "Food")
    _add_expense(client, auth_headers, food, "30.00", "2026-02-15")
    _add_expense(client, auth_headers, food, "100.00", "2026-05-10")

    body = client.get(
        "/reports/trend", params={"end_month": 5, "end_year": 2026}, headers=auth_headers
    ).json()

    months = body["months"]
    assert [(m["year"], m["month"]) for m in months] == [
        (2025, 12), (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5)
    ]
    totals = {(m["year"], m["month"]): m["total"] for m in months}
    assert totals[(2026, 2)] == "30.00"
    assert totals[(2026, 5)] == "100.00"
    assert totals[(2025, 12)] == "0.00"  # empty month zero-filled
    assert all(isinstance(m["total"], str) for m in months)


def test_trend_caps_window_at_thirty_six_months(client, auth_headers):
    """A request for more than the maximum window is capped at 36 months."""
    body = client.get(
        "/reports/trend",
        params={"end_month": 5, "end_year": 2026, "months": 50},
        headers=auth_headers,
    ).json()
    assert len(body["months"]) == 36
    # Still ends at the requested month, oldest→newest.
    assert (body["months"][-1]["year"], body["months"][-1]["month"]) == (2026, 5)


# --- Budget status --------------------------------------------------------------------


def test_budget_status_reports_spent_versus_budget_with_remaining(
    client, auth_headers, db_session
):
    """Each budgeted category shows spent vs budget with remaining; remaining is negative when exceeded.

    Only categories that have a budget that month appear — a spent-but-unbudgeted category is
    excluded. The budget is seeded directly (the budget API does not exist yet).
    """
    user_id = client.get("/users/me", headers=auth_headers).json()["id"]
    food = _category_id(db_session, "Food")
    transport = _category_id(db_session, "Transport")
    db_session.add(
        Budget(owner_id=user_id, category_id=food, amount=Decimal("100.00"), month=4, year=2026)
    )
    db_session.flush()
    _add_expense(client, auth_headers, food, "100.00", "2026-04-10")
    _add_expense(client, auth_headers, food, "42.50", "2026-04-12")
    _add_expense(client, auth_headers, transport, "50.00", "2026-04-15")  # unbudgeted, excluded

    body = client.get(
        "/reports/budget-status", params={"month": 4, "year": 2026}, headers=auth_headers
    ).json()

    assert body["month"] == 4 and body["year"] == 2026
    rows = {row["category"]["name"]: row for row in body["categories"]}
    assert set(rows) == {"Food"}  # Transport has no budget that month
    food_row = rows["Food"]
    assert food_row["budget"] == "100.00"
    assert food_row["spent"] == "142.50"
    assert food_row["remaining"] == "-42.50"  # budget − spent, negative when exceeded


# --- Auth -----------------------------------------------------------------------------


def test_reports_require_a_token(client):
    """A report endpoint rejects a request with no token as unauthenticated (FR-005)."""
    resp = client.get("/reports/monthly-summary", params={"month": 4, "year": 2026})
    assert resp.status_code == 401
    assert resp.json()["category"] == "unauthenticated"


# --- Unit: the pure trend month-window helper -----------------------------------------


def test_month_window_generates_n_months_ending_at_target_oldest_first():
    """The window is ``count`` (year, month) pairs ending at the target, ordered oldest→newest."""
    from app.services import month_window

    assert month_window(2026, 5, 6) == [
        (2025, 12), (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5)
    ]


def test_month_window_crosses_year_boundary():
    """The window steps correctly back across a calendar-year boundary."""
    from app.services import month_window

    assert month_window(2026, 2, 4) == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]
