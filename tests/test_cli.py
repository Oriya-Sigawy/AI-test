"""End-to-end smoke test for the thin CLI client (T020).

The CLI (``cli/``) holds no business logic — it is a second HTTP consumer of the API — so it
gets one integration round-trip rather than per-command unit coverage (plan §Complexity Tracking,
§Test Strategy; tasks.md Conventions: the client is test-first-exempt). Here the CLI's HTTP seam
(``cli._client``) is rebound to the suite's ``TestClient`` — the same in-process app the other
tests drive, with ``get_db`` overridden to the per-test ``db_session`` — so ``register → login →
expense add → expense list`` runs through the real API without a live server. A passing round-trip
proves the commands wire request bodies, the persisted bearer token, and response rendering
together correctly.
"""

import os
import re
import stat

import pytest
from typer.testing import CliRunner

import cli

runner = CliRunner()

_EMAIL = "cli@example.com"
_PW = "correct horse battery staple"  # test-only credential; not a real secret


def _id_from(output: str) -> int:
    """Pull the first integer out of a command's confirmation line (e.g. 'Created category 8: ...')."""
    match = re.search(r"\d+", output)
    assert match, f"no id found in: {output!r}"
    return int(match.group())


@pytest.fixture
def cli_env(client, tmp_path, monkeypatch):
    """Wire the CLI to the suite's ``TestClient`` and an isolated token file for one test.

    Reuses the ``client`` fixture (a ``TestClient`` bound to the test's ``db_session``, with its
    seeded default categories) so CLI calls share the same app and per-test rollback as every
    other test. The CLI opens its client as ``with _client() as c:``; a ``TestClient`` entered
    that way would start the app lifespan, whose startup ``create_all``/seed targets the non-test
    engine — so a tiny wrapper hands over the already-built client without entering its lifespan
    or closing it between commands. The token file is redirected to ``tmp_path`` so ``login``
    persists somewhere disposable instead of the user's home dotfile. Yields that token path.
    """
    monkeypatch.setenv("EXPENSE_TRACKER_TOKEN_FILE", str(tmp_path / "token"))

    class _BorrowedClient:
        def __enter__(self):
            return client

        def __exit__(self, *exc) -> bool:
            return False

    monkeypatch.setattr(cli, "_client", lambda: _BorrowedClient())
    yield tmp_path / "token"


def test_register_login_expense_roundtrip(cli_env):
    """register → login (token persisted) → expense add → expense list, all through the API."""
    token_file = cli_env

    registered = runner.invoke(
        cli.app,
        [
            "register",
            "--email", _EMAIL,
            "--display-name", "CLI User",
            "--currency", "usd",
            "--password", _PW,
        ],
    )
    assert registered.exit_code == 0, registered.output
    assert f"Registered {_EMAIL}" in registered.output

    logged_in = runner.invoke(
        cli.app, ["login", "--email", _EMAIL, "--password", _PW]
    )
    assert logged_in.exit_code == 0, logged_in.output
    # The token must be persisted so the authenticated commands below can read it back.
    assert token_file.exists() and token_file.read_text().strip()

    added = runner.invoke(
        cli.app,
        [
            "expense", "add",
            "--amount", "12.50",
            "--category", "Food",  # a seeded default category, resolved by name
            "--date", "2026-06-01",
            "--description", "lunch",
        ],
    )
    assert added.exit_code == 0, added.output
    assert "Added expense" in added.output
    # Currency is normalized server-side and echoed back uppercase (FR-017).
    assert "12.50 USD" in added.output

    listed = runner.invoke(cli.app, ["expense", "list"])
    assert listed.exit_code == 0, listed.output
    assert "12.50 USD" in listed.output
    assert "Food" in listed.output
    assert "lunch" in listed.output
    assert "(1 total, showing 1)" in listed.output

    shown = runner.invoke(cli.app, ["profile", "show"])
    assert shown.exit_code == 0, shown.output
    assert _EMAIL in shown.output
    assert "CLI User" in shown.output

    # Only display name is updated here: currency is locked once expenses exist (added above),
    # which the API enforces — so this exercises the realistic update path for a used account.
    updated = runner.invoke(cli.app, ["profile", "update", "--display-name", "Renamed"])
    assert updated.exit_code == 0, updated.output
    assert "Renamed" in updated.output


def test_category_expense_budget_report_management_roundtrip(cli_env):
    """The management commands all wire through the API: category list/update/delete, expense
    get/update/delete, budget set/list/delete, and the trend / budget-status reports."""
    for args in (
        ["register", "--email", _EMAIL, "--display-name", "CLI User", "--currency", "usd",
         "--password", _PW],
        ["login", "--email", _EMAIL, "--password", _PW],
    ):
        assert runner.invoke(cli.app, args).exit_code == 0

    # Categories: create → list → update.
    added = runner.invoke(
        cli.app, ["category", "add", "--name", "Coffee", "--icon", "cup", "--color", "#6F4E37"]
    )
    assert added.exit_code == 0, added.output
    category_id = _id_from(added.output)

    listed = runner.invoke(cli.app, ["category", "list"])
    assert listed.exit_code == 0, listed.output
    assert "Coffee" in listed.output
    assert "Food" in listed.output  # a seeded default is visible alongside the custom one

    renamed = runner.invoke(cli.app, ["category", "update", "--id", str(category_id), "--name", "Espresso"])
    assert renamed.exit_code == 0, renamed.output
    assert "Espresso" in renamed.output

    # Expenses: add → get → update.
    added_expense = runner.invoke(
        cli.app,
        ["expense", "add", "--amount", "20.00", "--category", "Espresso", "--date", "2026-06-01"],
    )
    assert added_expense.exit_code == 0, added_expense.output
    expense_id = _id_from(added_expense.output)

    got = runner.invoke(cli.app, ["expense", "get", "--id", str(expense_id)])
    assert got.exit_code == 0, got.output
    assert "20.00 USD" in got.output
    assert "Espresso" in got.output

    updated_expense = runner.invoke(
        cli.app, ["expense", "update", "--id", str(expense_id), "--amount", "25.00"]
    )
    assert updated_expense.exit_code == 0, updated_expense.output
    assert "25.00 USD" in updated_expense.output

    # Budgets: set (below the 25.00 spend, so the month is over budget) → list.
    budget = runner.invoke(
        cli.app,
        ["budget", "set", "--category", "Espresso", "--amount", "5.00", "--month", "6", "--year", "2026"],
    )
    assert budget.exit_code == 0, budget.output
    budget_id = _id_from(budget.output)

    budgets = runner.invoke(cli.app, ["budget", "list"])
    assert budgets.exit_code == 0, budgets.output
    assert "Espresso" in budgets.output
    assert "5.00" in budgets.output

    # Reports: trend (window includes the spend month) and budget status (spent > budget).
    trend = runner.invoke(
        cli.app, ["report", "trend", "--end-month", "6", "--end-year", "2026", "--months", "3"]
    )
    assert trend.exit_code == 0, trend.output
    assert "2026-06" in trend.output

    status = runner.invoke(cli.app, ["report", "budget-status", "--month", "6", "--year", "2026"])
    assert status.exit_code == 0, status.output
    assert "spent 25.00 of 5.00" in status.output
    assert "remaining -20.00" in status.output

    # Deletes: expense first frees the category, then the budget and the now-unused category.
    deleted_expense = runner.invoke(cli.app, ["expense", "delete", "--id", str(expense_id)])
    assert deleted_expense.exit_code == 0, deleted_expense.output

    deleted_budget = runner.invoke(cli.app, ["budget", "delete", "--id", str(budget_id)])
    assert deleted_budget.exit_code == 0, deleted_budget.output

    deleted_category = runner.invoke(cli.app, ["category", "delete", "--id", str(category_id)])
    assert deleted_category.exit_code == 0, deleted_category.output


def test_login_writes_token_file_readable_only_by_owner(cli_env, monkeypatch):
    """The saved bearer token is a credential: its file must be owner-only (0o600) by virtue of
    how it is created, not a follow-up ``chmod`` that leaves a brief world-readable window.

    To prove the permissions don't depend on that post-write ``chmod``, we neutralize it and set a
    permissive umask — a non-atomic ``write_text`` then would leave the token group/world-readable
    and fail, while an atomic owner-only create still yields 0o600.
    """
    token_file = cli_env
    monkeypatch.setattr(os, "chmod", lambda *args, **kwargs: None)
    previous_umask = os.umask(0o022)
    try:
        runner.invoke(
            cli.app,
            ["register", "--email", _EMAIL, "--display-name", "CLI User", "--currency", "usd",
             "--password", _PW],
        )
        logged_in = runner.invoke(cli.app, ["login", "--email", _EMAIL, "--password", _PW])
    finally:
        os.umask(previous_umask)
    assert logged_in.exit_code == 0, logged_in.output

    mode = stat.S_IMODE(token_file.stat().st_mode)
    assert mode == 0o600, f"token file mode is {oct(mode)}, expected 0o600"
