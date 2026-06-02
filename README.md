# Personal Expense Tracker API

A REST API for tracking personal expenses: token-based auth, expenses, categories
(system defaults + custom), monthly per-category budgets, and spending reports
(monthly summary, multi-month trend, budget status). Built with FastAPI, SQLAlchemy,
and PostgreSQL.

## Run with Docker (recommended)

```bash
cp .env.example .env          # then set SECRET_KEY (and DB creds if you change the defaults)
docker compose up --build     # starts postgres + the api; the api waits for the db healthcheck
```

- API: `http://localhost:8000` — interactive docs at `http://localhost:8000/docs`.
- On startup the app creates the tables and seeds the seven default categories (idempotent).

## Run locally (without Docker)

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and a local PostgreSQL 16.

```bash
uv sync                          # install dependencies from the lockfile
cp .env.example .env             # set SECRET_KEY and point DATABASE_URL at your local Postgres
set -a; . ./.env; set +a         # load the environment
uv run uvicorn app.main:app --reload
```

## Run the tests

The tests need a **dedicated** Postgres database (never your dev/prod DB), set via
`TEST_DATABASE_URL`. Each test runs in a transaction that is rolled back, so they are
independent.

```bash
createdb expense_test                                   # one-time: create the test database
export TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/expense_test
uv run pytest                                           # behavioral suite (116 tests)
uv run pytest -m slow                                   # optional: volume/load tests
```

## CLI client & Swagger UI

A thin first-party command-line client over the running API:

```bash
python -m cli register --email you@example.com --display-name "You" --currency USD
python -m cli login --email you@example.com            # stores the bearer token locally (0o600)
python -m cli expense add --amount 12.50 --category Food --date 2026-06-01 --description Lunch
python -m cli report monthly --month 6 --year 2026
```

For the CLI client and the interactive **Swagger UI** (`/docs`), there's a dedicated, friendly
walkthrough — every command and how to authorize and explore the API — in
**[`cli/README.md`](cli/README.md)**. Start there.

## Design decisions

**1. Test through the HTTP layer.**

I wanted to use the app for real, so I built a small CLI client. For tests, I weighed three options with AI:

- Call the service functions directly.
- Drive the running app over HTTP with FastAPI's `TestClient`.
- Exercise everything through the CLI.

I chose **HTTP**: it tests the app the way a real client uses it — routing, validation, serialization, status codes, auth — without coupling to internals, so a behavior-preserving refactor won't break the suite. The service-only option skips the HTTP contract; the CLI-only option just adds a moving part that makes failures harder to locate.

**2. Generic response when registering an existing email.**

The conventional answer is `409 Conflict` with a message like "email already registered" — but that confirms the address has an account, an **enumeration risk** (an attacker can probe who's registered).

My balance: still return `409`, but with a generic message that doesn't confirm the email exists, and log only the email's *domain*. Login follows the same rule — wrong password and unknown email both return an identical `401` — so neither flow leaks which accounts exist.
