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

import pytest
from typer.testing import CliRunner

import cli

runner = CliRunner()

_EMAIL = "cli@example.com"
_PW = "correct horse battery staple"  # test-only credential; not a real secret


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
