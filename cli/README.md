# Expense Tracker CLI

A thin first-party command-line client for the Expense Tracker API. It only makes HTTP calls to
a **running API** and shapes the results for the terminal — all business rules live in the
service. Everything below is run **from the repository root**.

The CLI needs the API running, so use two terminals: one for the API, one for the CLI.

## Prerequisites

- The repository checked out, and its virtual environment active (`source .venv/bin/activate`).
- A running PostgreSQL. If you use the bundled container: `docker compose up -d db`
  (or `docker start <db-container>` if it already exists).

## Terminal 1 — start the API

### Secrets: where they come from

The API reads two required settings from environment variables, conventionally kept in a **`.env`
file at the repository root** that the app loads automatically on startup:

| Variable | What it is | Where to get it |
| --- | --- | --- |
| `SECRET_KEY` | HS256 signing key for auth tokens. | Generate one: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DATABASE_URL` | PostgreSQL connection URL. | Match your database, e.g. `postgresql+psycopg://expense:change-me@localhost:5432/expense` |

`.env.example` (repo root) is the template listing every variable with placeholders and the
PostgreSQL credentials. Create your `.env` from it once:

```bash
cp .env.example .env          # then open .env and set SECRET_KEY (and DB creds if you changed them)
```

> The real `.env` holds secrets and is gitignored — never commit it. Only `.env.example`
> (placeholders) is tracked.

### Run it

```bash
python -m uvicorn app.main:app --port 8000     # reads .env automatically; serves on http://localhost:8000
```

Wait for `Application startup complete`. On first start it creates the tables and seeds the seven
default categories. Interactive API docs are at `http://localhost:8000/docs`.

*Alternative:* `docker compose up --build` starts PostgreSQL **and** the API together (also on
`http://localhost:8000`), using the same `.env`. Use this instead of the two steps above if you
prefer running everything in containers.

## Terminal 2 — use the CLI

The CLI reads these from the environment on every invocation:

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_BASE_URL` | `http://localhost:8000` | Base URL of the running API. |
| `EXPENSE_TRACKER_TOKEN_FILE` | `~/.expense_tracker_token` | Where `login` stores the bearer token (written `0600`). |

If the API is on the default URL above, you don't need to set anything. Otherwise point the CLI
at it:

```bash
export API_BASE_URL=http://localhost:8000
```

Then authenticate once — the saved token carries your session for the other commands:

```bash
# Create an account — prompts for the password (hidden), never echoed
python -m cli register --email you@example.com --display-name "You" --currency USD

# Log in — prompts for the password, saves the token locally
python -m cli login --email you@example.com

# Create a custom category (name unique among your visible categories; color is #RRGGBB)
python -m cli category add --name Coffee --icon cup --color "#6F4E37"

# Add an expense; --category takes the category *name* (resolved to its id for you),
# the amount is recorded in your account's default currency
python -m cli expense add --amount 12.50 --category Food --date 2026-06-01 --description "Lunch"

# List your expenses, newest first, optionally within a date range (dates are YYYY-MM-DD).
# Each category name is shown tinted in its own color on a real terminal.
python -m cli expense list --date-from 2026-06-01 --date-to 2026-06-30

# Monthly summary: the month's total and per-category breakdown
python -m cli report monthly --month 6 --year 2026
```

If an expense pushes that month's category spend over a set budget, `expense add` prints a
budget-exceeded line in addition to the confirmation (the warning comes from the API).

Every command exits non-zero and prints the API's error message on failure (e.g. not logged in,
unknown category name, validation error, or an unreachable API). Run any command with `--help`
for its full options.

## Notes

- Seven categories are seeded by default (Food, Transport, Entertainment, Shopping, Bills,
  Health, Other); create more with `category add`. A category name must be unique among the ones
  visible to you (the defaults plus your own), case-insensitively — a duplicate returns `409`, and
  a color that isn't `#RRGGBB` returns `422`. The CLI does not edit or delete categories; use the
  API (`PATCH`/`DELETE /categories/{id}`) or the Swagger UI at `/docs` for that.
- The auth token expires after the configured TTL (default 60 minutes); if commands start failing
  with "not authenticated", run `login` again.
