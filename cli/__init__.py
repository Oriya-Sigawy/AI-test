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
profile_app = typer.Typer(help="View and update your profile.")
category_app = typer.Typer(help="Manage your categories.")
expense_app = typer.Typer(help="Add, list, and manage expenses.")
budget_app = typer.Typer(help="Set, list, and delete per-category monthly budgets.")
report_app = typer.Typer(help="View spending reports.")
app.add_typer(profile_app, name="profile")
app.add_typer(category_app, name="category")
app.add_typer(expense_app, name="expense")
app.add_typer(budget_app, name="budget")
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


def _write_token(path: Path, token: str) -> None:
    """Persist the bearer token to ``path``, readable only by its owner.

    The token is a credential, so the file is *created* with mode 0o600 via ``os.open`` rather
    than written and then ``chmod``-ed — the latter would leave it briefly world-readable under
    the usual umask. The trailing ``chmod`` only tightens a file that already existed with looser
    permissions (e.g. one written by an older version).
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as token_file:
        token_file.write(token)
    os.chmod(path, 0o600)


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


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """Return the ``(r, g, b)`` components of a ``#RRGGBB`` color (the format the API guarantees)."""
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


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


def _echo_expense(item: dict) -> None:
    """Print one expense as a tab-separated row with its category name tinted in its own color.

    typer.echo strips the color codes when output is not a terminal (piped/redirected), so this
    stays scripting-safe. Shared by ``expense list`` and ``expense get`` for one consistent row.
    """
    category = item["category"]
    name = typer.style(category["name"], fg=_hex_to_rgb(category["color"]))
    typer.echo(
        f"{item['id']}\t{item['date']}\t{item['amount']} {item['currency']}"
        f"\t{name}\t{item['description'] or ''}"
    )


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
    _write_token(path, response.json()["access_token"])
    typer.echo("Logged in; token saved.")


@profile_app.command("show")
def profile_show() -> None:
    """Show your profile: id, email, display name, default currency, and timestamps."""
    body = _request("GET", "/users/me", auth=True).json()
    typer.echo(f"id:            {body['id']}")
    typer.echo(f"email:         {body['email']}")
    typer.echo(f"display name:  {body['display_name']}")
    typer.echo(f"currency:      {body['default_currency']}")
    typer.echo(f"created:       {body['created_at']}")
    typer.echo(f"updated:       {body['updated_at']}")


@profile_app.command("update")
def profile_update(
    display_name: str | None = typer.Option(None, "--display-name", help="New display name."),
    currency: str | None = typer.Option(None, "--currency", help="New default currency, e.g. EUR."),
) -> None:
    """Update your display name and/or default currency (email is immutable)."""
    payload: dict = {}
    if display_name is not None:
        payload["display_name"] = display_name
    if currency is not None:
        payload["default_currency"] = currency
    if not payload:
        # Guard against a no-op PATCH so the user gets actionable feedback, not a silent success.
        typer.echo("Nothing to update — pass --display-name and/or --currency.", err=True)
        raise typer.Exit(1)
    body = _request("PATCH", "/users/me", json=payload, auth=True).json()
    typer.echo(f"Updated profile: {body['display_name']} ({body['default_currency']}).")


@category_app.command("add")
def category_add(
    name: str = typer.Option(..., "--name", help="Category name (unique, 1-50 chars)."),
    icon: str = typer.Option(..., "--icon", help="Icon identifier, e.g. cup."),
    color: str = typer.Option(..., "--color", help="Hex color #RRGGBB, e.g. #6F4E37."),
) -> None:
    """Create a custom category."""
    response = _request(
        "POST", "/categories", json={"name": name, "icon": icon, "color": color}, auth=True
    )
    body = response.json()
    styled = typer.style(body["name"], fg=_hex_to_rgb(body["color"]))
    typer.echo(f"Created category {body['id']}: {styled} (icon {body['icon']}).")


@category_app.command("list")
def category_list() -> None:
    """List every category visible to you (the seven defaults plus your own)."""
    page = _request("GET", "/categories", params={"limit": 100}, auth=True).json()
    for item in page["items"]:
        # Tint each name in its own color; typer.echo strips the codes when piped/redirected.
        name = typer.style(item["name"], fg=_hex_to_rgb(item["color"]))
        kind = "system" if item["is_system"] else "custom"
        typer.echo(f"{item['id']}\t{name}\t{item['icon']}\t{item['color']}\t{kind}")
    typer.echo(f"({page['total']} total, showing {len(page['items'])})")


@category_app.command("update")
def category_update(
    category_id: int = typer.Option(..., "--id", help="Id of your custom category (see `category list`)."),
    name: str | None = typer.Option(None, "--name", help="New name (unique, 1-50 chars)."),
    icon: str | None = typer.Option(None, "--icon", help="New icon identifier."),
    color: str | None = typer.Option(None, "--color", help="New hex color #RRGGBB."),
) -> None:
    """Update one of your custom categories (only the fields you pass change)."""
    payload = {k: v for k, v in {"name": name, "icon": icon, "color": color}.items() if v is not None}
    if not payload:
        # Guard against a no-op PATCH so the user gets actionable feedback, not a silent success.
        typer.echo("Nothing to update — pass --name, --icon, and/or --color.", err=True)
        raise typer.Exit(1)
    body = _request("PATCH", f"/categories/{category_id}", json=payload, auth=True).json()
    styled = typer.style(body["name"], fg=_hex_to_rgb(body["color"]))
    typer.echo(f"Updated category {body['id']}: {styled} (icon {body['icon']}).")


@category_app.command("delete")
def category_delete(
    category_id: int = typer.Option(..., "--id", help="Id of your custom category (see `category list`)."),
) -> None:
    """Delete one of your unused custom categories (the API blocks it if expenses reference it)."""
    _request("DELETE", f"/categories/{category_id}", auth=True)
    typer.echo(f"Deleted category {category_id}.")


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
        # Tint the over-budget warning red; typer.echo strips the codes automatically when output
        # is not a terminal (piped/redirected), so this stays scripting-safe.
        typer.echo(
            typer.style(
                f"  Budget exceeded for {warning['category_name']}: "
                f"spent {warning['spent']} of {warning['budget']} (over by {warning['exceeded_by']}).",
                fg=typer.colors.RED,
            )
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
        _echo_expense(item)
    typer.echo(f"({page['total']} total, showing {len(page['items'])})")


@expense_app.command("get")
def expense_get(
    expense_id: int = typer.Option(..., "--id", help="Id of the expense (see `expense list`)."),
) -> None:
    """Show a single expense by id."""
    body = _request("GET", f"/expenses/{expense_id}", auth=True).json()
    _echo_expense(body)


@expense_app.command("update")
def expense_update(
    expense_id: int = typer.Option(..., "--id", help="Id of the expense (see `expense list`)."),
    amount: str | None = typer.Option(None, "--amount", help='New amount, e.g. "12.50".'),
    category: str | None = typer.Option(None, "--category", help="New category name."),
    date: str | None = typer.Option(None, "--date", help="New date, YYYY-MM-DD."),
    description: str | None = typer.Option(None, "--description", help="New note."),
) -> None:
    """Update an expense (only the fields you pass change; all creation rules still apply)."""
    payload: dict = {}
    if amount is not None:
        payload["amount"] = amount
    if category is not None:
        payload["category_id"] = _resolve_category_id(category)
    if date is not None:
        payload["date"] = date
    if description is not None:
        payload["description"] = description
    if not payload:
        # Guard against a no-op PATCH so the user gets actionable feedback, not a silent success.
        typer.echo("Nothing to update — pass --amount, --category, --date, and/or --description.", err=True)
        raise typer.Exit(1)
    body = _request("PATCH", f"/expenses/{expense_id}", json=payload, auth=True).json()
    typer.echo(f"Updated expense {body['id']}: {body['amount']} {body['currency']} on {body['date']}.")


@expense_app.command("delete")
def expense_delete(
    expense_id: int = typer.Option(..., "--id", help="Id of the expense (see `expense list`)."),
) -> None:
    """Delete one of your expenses."""
    _request("DELETE", f"/expenses/{expense_id}", auth=True)
    typer.echo(f"Deleted expense {expense_id}.")


@budget_app.command("set")
def budget_set(
    category: str = typer.Option(..., "--category", help="Category name, e.g. Food."),
    amount: str = typer.Option(..., "--amount", help='Monthly limit, e.g. "300.00" (>= 0).'),
    month: int = typer.Option(..., "--month", help="Month number, 1-12."),
    year: int = typer.Option(..., "--year", help="Four-digit year."),
) -> None:
    """Set or update the budget for a category in one month (re-running replaces it)."""
    body = _request(
        "PUT",
        "/budgets",
        json={
            "category_id": _resolve_category_id(category),
            "amount": amount,
            "month": month,
            "year": year,
        },
        auth=True,
    ).json()
    typer.echo(
        f"Budget {body['id']} set: {body['category']['name']} "
        f"{body['amount']} for {body['year']}-{body['month']:02d}."
    )


@budget_app.command("list")
def budget_list() -> None:
    """List your budgets, newest period first."""
    page = _request("GET", "/budgets", params={"limit": 100}, auth=True).json()
    for item in page["items"]:
        category = item["category"]
        name = typer.style(category["name"], fg=_hex_to_rgb(category["color"]))
        typer.echo(f"{item['id']}\t{item['year']}-{item['month']:02d}\t{name}\t{item['amount']}")
    typer.echo(f"({page['total']} total, showing {len(page['items'])})")


@budget_app.command("delete")
def budget_delete(
    budget_id: int = typer.Option(..., "--id", help="Id of the budget (see `budget list`)."),
) -> None:
    """Delete one of your budgets."""
    _request("DELETE", f"/budgets/{budget_id}", auth=True)
    typer.echo(f"Deleted budget {budget_id}.")


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


@report_app.command("trend")
def report_trend(
    end_month: int = typer.Option(..., "--end-month", help="Last month of the window, 1-12."),
    end_year: int = typer.Option(..., "--end-year", help="Year of that last month."),
    months: int = typer.Option(6, "--months", help="How many months to compare (capped at 36)."),
) -> None:
    """Show the spend total per month over a window ending at the given month (oldest first)."""
    body = _request(
        "GET",
        "/reports/trend",
        params={"end_month": end_month, "end_year": end_year, "months": months},
        auth=True,
    ).json()
    for row in body["months"]:
        typer.echo(f"{row['year']}-{row['month']:02d}\t{row['total']}")


@report_app.command("budget-status")
def report_budget_status(
    month: int = typer.Option(..., "--month", help="Month number, 1-12."),
    year: int = typer.Option(..., "--year", help="Four-digit year."),
) -> None:
    """Show spent vs budget per budgeted category for the month (remaining goes negative if over)."""
    body = _request(
        "GET", "/reports/budget-status", params={"month": month, "year": year}, auth=True
    ).json()
    typer.echo(f"{body['year']}-{body['month']:02d} budget status:")
    for row in body["categories"]:
        name = typer.style(row["category"]["name"], fg=_hex_to_rgb(row["category"]["color"]))
        typer.echo(f"  {name}: spent {row['spent']} of {row['budget']} (remaining {row['remaining']})")
