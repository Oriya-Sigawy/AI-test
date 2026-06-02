"""Volume test: the list/paging mechanism stays correct under a large dataset.

Opt-in (``@pytest.mark.slow``; run with ``pytest -m slow``) because it seeds many more rows
than the behavioral suite. Categories are created through the API to exercise that write path
under volume; the bulk of expenses are inserted straight through ``db_session`` (the same
fast-seed pattern the other expense tests use) since the goal here is to load the table, then
prove that paginated GETs walk the whole set with no gaps and no duplicates.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Category, Expense

_TODAY = dt.date.today()

NUM_CATEGORIES = 25  # custom categories, on top of the 7 system defaults
NUM_EXPENSES = 1000
PAGE = 100  # the configured max_page_size — the largest page a client may request


@pytest.mark.slow
def test_paging_walks_a_large_dataset_without_gaps_or_duplicates(
    client, auth_headers, db_session
):
    """With ~1000 expenses across many categories, paging covers every row exactly once."""
    owner_id = client.get("/users/me", headers=auth_headers).json()["id"]

    # Create many custom categories through the API (exercises the write path under volume).
    cat_ids = []
    for i in range(NUM_CATEGORIES):
        resp = client.post(
            "/categories",
            json={"name": f"Load Cat {i:03d}", "icon": "x", "color": "#123456"},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        cat_ids.append(resp.json()["id"])

    # Bulk-seed the expenses directly; dates spread into the past so none trip the
    # 7-day future-date rule, and amounts stay positive.
    db_session.add_all(
        Expense(
            owner_id=owner_id,
            category_id=cat_ids[i % len(cat_ids)],
            amount=Decimal("10.00"),
            currency="USD",
            date=_TODAY - dt.timedelta(days=i % 900),
            description=f"load expense {i:04d}",
        )
        for i in range(NUM_EXPENSES)
    )
    db_session.flush()

    # Walk every page and collect ids, asserting the page envelope is correct each step.
    seen: list[int] = []
    for offset in range(0, NUM_EXPENSES, PAGE):
        body = client.get(
            "/expenses", params={"limit": PAGE, "offset": offset}, headers=auth_headers
        ).json()
        assert body["total"] == NUM_EXPENSES
        assert body["count"] == len(body["items"])  # count mirrors items returned
        assert body["count"] == min(PAGE, NUM_EXPENSES - offset)  # full pages, partial last
        seen.extend(e["id"] for e in body["items"])

    assert len(seen) == NUM_EXPENSES  # no rows skipped across pages
    assert len(set(seen)) == NUM_EXPENSES  # and none returned twice

    # An offset at/after the end is a well-formed empty page, not an error.
    beyond = client.get(
        "/expenses", params={"limit": PAGE, "offset": NUM_EXPENSES}, headers=auth_headers
    ).json()
    assert beyond["total"] == NUM_EXPENSES and beyond["count"] == 0 and beyond["items"] == []


@pytest.mark.slow
def test_category_list_is_complete_under_load(client, auth_headers):
    """Listing categories still returns every row (system + custom) after a volume of inserts."""
    # A fresh user starts with only the seeded system defaults; capture that baseline.
    baseline = client.get(
        "/categories", params={"limit": PAGE, "offset": 0}, headers=auth_headers
    ).json()["total"]

    for i in range(NUM_CATEGORIES):
        resp = client.post(
            "/categories",
            json={"name": f"Bulk Cat {i:03d}", "icon": "x", "color": "#654321"},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text

    expected = baseline + NUM_CATEGORIES
    body = client.get(
        "/categories", params={"limit": PAGE, "offset": 0}, headers=auth_headers
    ).json()
    assert body["total"] == expected
    assert body["count"] == len(body["items"]) == expected  # all fit within one max-size page
