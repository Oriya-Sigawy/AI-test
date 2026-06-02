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

**1. Money is exact `Decimal`, never `float`.** Amounts are stored as PostgreSQL
`NUMERIC(11, 2)`, handled as Python `Decimal` throughout, and serialized on the wire as
JSON *strings* (e.g. `"42.50"`). Floating-point can't represent most decimal fractions
exactly, so summing expenses or comparing spend against a budget with floats would
accumulate rounding errors — unacceptable for financial data. The `NUMERIC(11, 2)` type
also enforces the amount ceiling and two-decimal precision at the database level, and the
string serialization stops a client's float round-trip from perturbing the value.

**2. Integrity is enforced by the database, not by read-then-write checks.** Uniqueness
(case-insensitive email, per-user category names, one budget per category/month) lives in
unique indexes; value bounds (positive amount, valid month/year) live in `CHECK`
constraints; and setting a budget is a single `INSERT ... ON CONFLICT DO UPDATE` upsert.
Doing these checks in application code with a separate "does it exist?" query first would
leave a race window where two concurrent requests both pass the check and then both write.
Letting the database be the single source of truth makes the rules race-free; the service
layer simply catches the resulting `IntegrityError` and returns a clean `409 Conflict`.
