"""A thin first-party command-line client for the Expense Tracker API.

Run as ``python -m cli``. It is a *client*, not part of the service: every command is a small
HTTP call to the running API (``API_BASE_URL``, default ``http://localhost:8000``) shaped for the
terminal — it holds no business logic of its own. ``login`` saves the bearer token to a local
file (``EXPENSE_TRACKER_TOKEN_FILE``, default ``~/.expense_tracker_token``) which the
authenticated commands then read.
"""

import os
from pathlib import Path

import httpx
import typer

app = typer.Typer(help="Personal Expense Tracker CLI (a thin client over the REST API).")
expense_app = typer.Typer(help="Add and list expenses.")
report_app = typer.Typer(help="View spending reports.")
app.add_typer(expense_app, name="expense")
app.add_typer(report_app, name="report")


def _base_url() -> str:
    """Return the API base URL, overridable via ``API_BASE_URL`` (read per call so tests can set it)."""
    return os.environ.get("API_BASE_URL", "http://localhost:8000")


def _token_file() -> Path:
    """Return the path the bearer token is stored at (``EXPENSE_TRACKER_TOKEN_FILE`` or a home dotfile)."""
    override = os.environ.get("EXPENSE_TRACKER_TOKEN_FILE")
    return Path(override) if override else Path.home() / ".expense_tracker_token"


def _client() -> httpx.Client:
    """Return an HTTP client bound to the API base URL.

    A single seam for every request, so a test can substitute a client wired to the ASGI app
    (``ASGITransport``) and exercise the CLI without a live server.
    """
    return httpx.Client(base_url=_base_url(), timeout=10.0)


def _load_token() -> str:
    """Return the saved bearer token, or exit with guidance if the user has not logged in."""
    path = _token_file()
    if not path.exists():
        typer.echo("Not logged in — run `login` first.", err=True)
        raise typer.Exit(1)
    return path.read_text().strip()


def _request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    auth: bool = False,
) -> httpx.Response:
    """Send one request to the API and return the response, exiting on a transport or HTTP error.

    auth: when true, attach the saved bearer token; the API rejects the call as 401 without it.
    A 4xx/5xx response is rendered as the API's ``message`` and turned into a non-zero exit.
    """
    headers = {"Authorization": f"Bearer {_load_token()}"} if auth else {}
    try:
        with _client() as client:
            response = client.request(method, path, json=json, params=params, headers=headers)
    except httpx.HTTPError as exc:
        typer.echo(f"Could not reach the API at {_base_url()}: {exc}", err=True)
        raise typer.Exit(1)
    if response.status_code >= 400:
        _fail(response)
    return response


def _fail(response: httpx.Response) -> None:
    """Print the API error's human-readable message and exit non-zero."""
    try:
        message = response.json().get("message", response.text)
    except ValueError:
        message = response.text
    typer.echo(f"Error {response.status_code}: {message}", err=True)
    raise typer.Exit(1)


def _resolve_category_id(name: str) -> int:
    """Return the id of the visible category matching ``name`` (case-insensitive), or exit.

    The API addresses categories by id; the CLI accepts the friendlier name and looks it up
    against the user's visible categories (the seven defaults plus their own).
    """
    response = _request("GET", "/categories", params={"limit": 100}, auth=True)
    for category in response.json()["items"]:
        if category["name"].lower() == name.lower():
            return category["id"]
    typer.echo(f"No category named '{name}'.", err=True)
    raise typer.Exit(1)


@app.command()
def register(
    email: str = typer.Option(..., "--email", help="Account email address."),
    display_name: str = typer.Option(..., "--display-name", help="Display name."),
    currency: str = typer.Option(..., "--currency", help="Three-letter default currency, e.g. USD."),
    password: str = typer.Option(
        ..., prompt=True, hide_input=True, help="Account password (prompted, hidden)."
    ),
) -> None:
    """Create a new account (the password is prompted and never echoed)."""
    response = _request(
        "POST",
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": display_name,
            "default_currency": currency,
        },
    )
    body = response.json()
    typer.echo(f"Registered {body['email']} (id {body['id']}).")


@app.command()
def login(
    email: str = typer.Option(..., "--email", help="Account email address."),
    password: str = typer.Option(
        ..., prompt=True, hide_input=True, help="Account password (prompted, hidden)."
    ),
) -> None:
    """Log in and persist the bearer token locally for the authenticated commands."""
    response = _request("POST", "/auth/login", json={"email": email, "password": password})
    path = _token_file()
    path.write_text(response.json()["access_token"])
    os.chmod(path, 0o600)  # the token is a credential — keep it readable only by its owner
    typer.echo("Logged in; token saved.")


@expense_app.command("add")
def expense_add(
    amount: str = typer.Option(..., "--amount", help='Amount, e.g. "12.50" (your default currency).'),
    category: str = typer.Option(..., "--category", help="Category name, e.g. Food."),
    date: str = typer.Option(..., "--date", help="Expense date, YYYY-MM-DD."),
    description: str | None = typer.Option(None, "--description", help="Optional note."),
) -> None:
    """Add an expense against a category (named), in your default currency."""
    response = _request(
        "POST",
        "/expenses",
        json={
            "amount": amount,
            "category_id": _resolve_category_id(category),
            "date": date,
            "description": description,
        },
        auth=True,
    )
    body = response.json()
    typer.echo(f"Added expense {body['id']}: {body['amount']} {body['currency']} on {body['date']}.")
    warning = body.get("budget_warning")
    if warning:
        typer.echo(
            f"  Budget exceeded for {warning['category_name']}: "
            f"spent {warning['spent']} of {warning['budget']} (over by {warning['exceeded_by']})."
        )


@expense_app.command("list")
def expense_list(
    date_from: str | None = typer.Option(None, "--date-from", help="Earliest date, YYYY-MM-DD."),
    date_to: str | None = typer.Option(None, "--date-to", help="Latest date, YYYY-MM-DD."),
) -> None:
    """List your expenses, optionally bounded by a date range (newest first)."""
    params: dict = {}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    page = _request("GET", "/expenses", params=params, auth=True).json()
    for item in page["items"]:
        typer.echo(
            f"{item['id']}\t{item['date']}\t{item['amount']} {item['currency']}"
            f"\t{item['category']['name']}\t{item['description'] or ''}"
        )
    typer.echo(f"({page['total']} total, showing {len(page['items'])})")


@report_app.command("monthly")
def report_monthly(
    month: int = typer.Option(..., "--month", help="Month number, 1-12."),
    year: int = typer.Option(..., "--year", help="Four-digit year."),
) -> None:
    """Show the monthly spending summary: the month's total and per-category breakdown."""
    summary = _request(
        "GET", "/reports/monthly-summary", params={"month": month, "year": year}, auth=True
    ).json()
    typer.echo(f"{summary['year']}-{summary['month']:02d} total: {summary['total']}")
    for row in summary["by_category"]:
        typer.echo(f"  {row['category']['name']}: {row['total']}")
