# Phase 0 — Research & Decisions

Decisions that resolve the Technical Context. Each is recorded as **Decision / Rationale /
Alternatives considered** so it is explainable at the follow-up interview. There were no
open `NEEDS CLARIFICATION` markers — the spec's Clarifications and Assumptions already settled
the behavioral unknowns; this file settles the *technical* ones.

## 1. Web framework — FastAPI

- **Decision**: FastAPI + Uvicorn.
- **Rationale**: First-class Pydantic v2 validation (covers most of spec §Validation Rules
  declaratively), dependency injection for `get_db`/`get_current_user`, automatic OpenAPI/Swagger
  UI (satisfies the NICE-to-have API docs for free), and a built-in `TestClient` for behavior
  tests. Mainstream and easy to explain.
- **Alternatives**: Flask (more wiring for validation/serialization); Django REST Framework
  (heavier than this scope needs — Principle IV).

## 2. Concurrency model — synchronous

- **Decision**: Synchronous endpoints + synchronous SQLAlchemy.
- **Rationale**: The workload is interactive single-user, not high-concurrency. Sync code is
  simpler to read, test, and debug; it avoids async/await footguns (blocking calls, event-loop
  fixtures). Directly serves Principle IV and Principle VI.
- **Alternatives**: async SQLAlchemy + asyncpg — rejected as unjustified complexity for the scale.

## 3. ORM & driver — SQLAlchemy 2.0 + psycopg 3

- **Decision**: SQLAlchemy 2.0 ORM (typed `Mapped[...]`) over PostgreSQL via psycopg 3.
- **Rationale**: ORM gives clear models and relationships, parameterized queries (SQL-injection
  safe by default), and SQL-side aggregation for reports. 2.0 typed style reads well.
- **Alternatives**: raw SQL (more boilerplate, easier to get injection/escaping wrong); SQLModel
  (couples ORM and serialization — we keep ORM and Pydantic schemas separate on purpose).

## 4. Schema management — `create_all` + idempotent seed (no migrations)

- **Decision**: Create tables at startup with `Base.metadata.create_all()`; seed the seven
  default categories idempotently.
- **Rationale**: Greenfield project with no production data to migrate; a migration tool would be
  ceremony without payoff (Principle IV). `create_all` runs with `checkfirst=True` and the seed is
  idempotent, so repeated **single-worker** startups are safe.
- **Assumption**: a single startup actor. `create_all` + seed can race if multiple Uvicorn
  workers/replicas start simultaneously; this app assumes single-worker startup. Scaling out would
  move schema setup to a migration step (Alembic) or guard it with a Postgres advisory lock.
- **Alternatives**: Alembic — rejected now; noted as the obvious upgrade path if the schema ever
  needs versioned evolution (or multi-worker startup). Explainable as a conscious tradeoff at interview.

## 5. Authentication — JWT (HS256), bcrypt passwords

- **Decision**: Bearer JWT signed HS256 with an env `SECRET_KEY`, short configurable expiry,
  `sub` = user id (encoded as a **string** — PyJWT validates `sub` as a string); passwords hashed
  with the **`bcrypt` library directly**. **No token revocation or refresh** — invalidation is by short expiry only
  (a deliberate consequence of choosing stateless tokens over a server-side session store).
- **Rationale**: Satisfies the spec's security item that tokens be integrity-protected and
  expiring (not forgeable opaque strings) with no server-side session store. bcrypt is the
  well-understood, salted, slow password hash. Both are interview-defensible.
- **bcrypt gotchas** (decided on purpose): bcrypt **silently truncates input at 72 bytes**, so
  passwords are pre-hashed as `base64(sha256(password))` before bcrypt (base64, not the raw digest,
  to avoid an embedded `0x00` re-truncating). We call the **`bcrypt` library directly rather than
  `passlib`**: passlib 1.7.4 (its last release) reads `bcrypt.__about__` (raising `AttributeError`
  against bcrypt ≥ 4.1) and imports the stdlib `crypt` module (removed in Python 3.13) — using
  `bcrypt` directly avoids both, needs no version pin, and stays 3.13-safe.
- **Alternatives**: opaque DB session tokens (needs a store + revocation; more moving parts);
  argon2 (excellent, no 72-byte limit, but bcrypt is more universally recognized and sufficient
  here); RS256 (asymmetric keys unnecessary for a single service).

## 6. Money type — `Decimal` / `NUMERIC(11,2)`

- **Decision**: Represent amounts as `Decimal`, store as `NUMERIC(11, 2)`.
- **Rationale**: Exact decimal arithmetic (no float rounding) is mandatory for money and for the
  report-sum equality success criteria (SC-006). `NUMERIC(11,2)` exactly fits the
  `999,999,999.99` ceiling (9 integer + 2 fraction digits).
- **Alternatives**: float/double (rounding errors — unacceptable); integer cents (works, but
  `Decimal`/`NUMERIC` is clearer and maps directly to the spec's two-decimal rule).

## 7. Case-insensitive uniqueness (email, category name)

- **Decision**: Store email lowercased with a unique index on `lower(email)`. For category names,
  enforce uniqueness in the service via a `lower(name)` lookup across the user's *visible* set
  (their custom categories **and** the shared defaults), backed by a partial unique index on
  custom rows `(owner_id, lower(name))`.
- **Rationale**: A single DB constraint can't express "unique among defaults + my own" because
  defaults have a null owner; the service check covers that, and the partial index defends custom
  rows. Matches FR-002/FR-011.
- **Alternatives**: `CITEXT` column type (extension dependency); app-only checks without an index
  (race-prone). Chosen approach is the simplest correct combination at this scale.

## 8. Reports & budget check — SQL aggregation

- **Decision**: Compute sums with `SUM`/`GROUP BY` in the database; generate trend month buckets
  in Python and zero-fill from the grouped result.
- **Rationale**: Performance gate — avoids loading all expenses into memory; keeps report and
  budget-warning cost roughly constant in result size. SC-006 correctness is easier to reason
  about with a single aggregate query.
- **Alternatives**: load rows and sum in Python — rejected (O(rows), needless memory).

## 9. CLI client — Typer + httpx (developer-approved)

- **Decision**: A thin `cli.py` Typer app that calls the API over httpx and stores the login token
  locally; it contains **no business logic**.
- **Rationale**: The developer chose "API + thin CLI client" this session. Keeping it a pure HTTP
  client means the business rules live in one place (the API) and the CLI stays trivial to test
  and explain. Tracked in plan Complexity Tracking.
- **Alternatives**: no client (default); web frontend (larger, less-aligned scope) — both rejected
  per the developer's choice.

## 10. Logging — stdlib `logging` with a JSON formatter

- **Decision**: Python stdlib `logging` configured to emit JSON lines to stdout; a request
  id/user id on log records where useful; never log passwords, tokens, or full request bodies.
- **Rationale**: Satisfies the SHOULD-have structured logging and the Logging gate with zero
  extra dependencies (Principle IV). stdout suits containers.
- **Alternatives**: structlog / python-json-logger — capable, but an added dependency we don't
  need at this size.

## 11. Testing — pytest + TestClient against real Postgres, transaction rollback

- **Decision**: pytest with FastAPI `TestClient`; a session fixture builds the schema on a
  dedicated `TEST_DATABASE_URL` Postgres and seeds defaults; a function fixture opens **one
  connection**, begins an outer transaction, binds a `Session(bind=connection,
  join_transaction_mode="create_savepoint")`, and **overrides the app's `get_db`** to yield that
  same session. The `get_db` override is essential — without it the request runs on its own
  connection and the rollback wouldn't cover what the API wrote; and because services call
  `session.commit()`, the savepoint join mode is what lets those commits land on savepoints so the
  single outer `rollback()` still wipes everything.
- **Rationale**: Behavior tests through the real API on the real engine make `NUMERIC`,
  case-insensitive uniqueness, and aggregation behave as in production; rollback gives fast,
  independent tests (Principle III). SQLite would diverge on exactly these behaviors.
- **Alternatives**: SQLite in-memory (behavior drift); testcontainers (clean isolation but needs
  a Docker socket in the test run — heavier than pointing at the compose Postgres).

## 12. Containerization — Dockerfile + docker-compose (api + postgres)

- **Decision**: Slim Python base, non-root user, dependencies installed from the lockfile; compose
  runs `api` + `postgres` with the API waiting on a Postgres healthcheck.
- **Rationale**: Required deliverable; non-root and a pinned base are baseline container hardening.
- **Alternatives**: single all-in-one image with embedded DB — rejected (not how the relational DB
  requirement is meant, and worse separation).
