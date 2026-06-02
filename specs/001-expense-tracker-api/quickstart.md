# Phase 1 — Quickstart

How to run the API, the tests, and the CLI once the code from `tasks.md` is implemented. This is
the design-phase reference; the deliverable `README.md` will carry the final, verified version.

## Prerequisites

- Docker + Docker Compose (primary path), or Python 3.11+ and a local PostgreSQL 16 (local path).
- Secrets via environment variables — never committed. Copy `.env.example` to `.env` and set at
  least `SECRET_KEY` and `DATABASE_URL`.

## Run with Docker (primary)

```bash
cp .env.example .env          # set SECRET_KEY (and DB creds if changing defaults)
docker compose up --build     # starts postgres + api; api waits for the db healthcheck
```

- API at `http://localhost:8000`; interactive docs at `http://localhost:8000/docs`.
- On startup the app creates tables and idempotently seeds the seven default categories.

## Run locally (without Docker)

```bash
uv sync                                   # install deps from the lockfile
set -a; . ./.env; set +a                  # load env (SECRET_KEY, DATABASE_URL, ...) safely
uvicorn app.main:app --reload
```

## Run the tests

Tests need a **dedicated Postgres test database** (never the dev/prod DB) via `TEST_DATABASE_URL`.
The schema is created and defaults seeded by a session fixture; each test runs in a transaction
that is rolled back, so tests are independent.

```bash
export TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/expense_test
pytest                # or: pytest -q
```

Expected coverage (SC-008): authentication, expense CRUD, budget-checking logic, and report
calculations each have at least one behavior test; ≥8 tests total.

## Use the CLI client

The CLI is a thin first-party client over the running API (`API_BASE_URL`, default
`http://localhost:8000`). It stores the login token locally after `login`.

```bash
python -m cli register --email you@example.com --display-name "You" --currency USD   # prompts for password (hidden)
python -m cli login --email you@example.com         # prompts for password (hidden); stores token
python -m cli expense add --amount 12.50 --category Food --date 2026-06-01 --description "Lunch"
python -m cli expense list --date-from 2026-06-01 --date-to 2026-06-30
python -m cli report monthly --month 6 --year 2026
```

## First end-to-end check (mirrors SC-001)

1. `register` a user, then `login` to get a token.
2. `expense add` against the default **Food** category — confirm it stores in your default
   currency with no manual category setup.
3. `report monthly` — confirm the total equals the expense you just added.
