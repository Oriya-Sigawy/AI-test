# Implementation Plan: Personal Expense Tracker API

**Branch**: `001-expense-tracker-api` | **Date**: 2026-06-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-expense-tracker-api/spec.md`

## Summary

A REST API for personal expense tracking: token-authenticated users record expenses,
organize them with system-default and custom categories, set monthly per-category budgets,
receive budget-exceeded warnings, and view spending reports (monthly summary, multi-month
trend, budget status). All amounts use the owner's single default currency; conversion is out
of scope.

**Technical approach**: A single FastAPI service backed by PostgreSQL via **synchronous**
SQLAlchemy 2.0 ORM, organized in three thin layers (API → services → models) with Pydantic v2
for validation and serialization. JWT (signed, expiring) bearer tokens; bcrypt password
hashing. A small **Typer + httpx CLI client** (developer-approved scope addition) exercises the
same HTTP API. Tests are pytest integration tests through the API against a real Postgres test
database, plus a few focused unit tests for pure calculation logic. Synchronous I/O and the
absence of a repository layer or migration framework are deliberate simplicity choices
(Principle IV) that keep every line explainable at the follow-up interview.

## Technical Context

**Language/Version**: Python 3.11+ (developed on 3.12)

**Primary Dependencies**: FastAPI (web framework) · Uvicorn (ASGI server) · Pydantic v2 +
pydantic-settings (validation, config) · SQLAlchemy 2.0 (ORM, **sync**) · psycopg 3 (Postgres
driver) · PyJWT (token signing/verification) · passlib[bcrypt] (password hashing) · Typer +
httpx (CLI client). Dev: pytest (+ httpx TestClient), bandit (already in `pyproject.toml`).

**Storage**: PostgreSQL 16 (relational, required). Schema created at startup via
`Base.metadata.create_all()`; default categories seeded idempotently. No migration framework
(see Complexity Tracking).

**Testing**: pytest. Integration tests drive the API through FastAPI's `TestClient` against a
dedicated Postgres **test** database; each test runs inside a transaction rolled back on
teardown for isolation. Pure logic (budget-warning math, trend month-window, date bounds) also
covered by unit tests.

**Target Platform**: Linux container; `Dockerfile` + `docker-compose.yml` run the API and
Postgres together. TLS is terminated by the deployment's reverse proxy (out of app scope; noted
in README).

**Project Type**: Web service (REST API) + a thin first-party CLI client.

**Performance Goals**: Interactive single-user workload. Targeted indexes and SQL aggregation
keep common operations (expense list, reports, budget check) within tens of milliseconds on
realistic data (low thousands of expenses). No high-throughput target is in scope.

**Constraints**: Secrets only via environment variables (`SECRET_KEY`, DB URL); structured
(JSON) logs to stdout; no secrets or passwords in logs or responses; server never fetches
user-supplied receipt URLs (no SSRF surface).

**Scale/Scope**: Single-developer learning project; a handful of users, low thousands of
expenses per user; ~6 resource groups (auth, users, categories, expenses, budgets, reports).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design — still passing.*

| Principle | Assessment |
|---|---|
| **I. Requirements First** | PASS. Every endpoint and rule traces to an FR in `spec.md`. Two scope items beyond the literal assignment are explicitly authorized and tracked: the **CLI client** (developer-approved this session) and **pagination on all list endpoints** (spec Clarification 2026-06-01). No other inferred features. |
| **II. Specification-Driven** | PASS. This plan derives from the reviewed spec; tasks and code will derive from this plan. No code is written in this phase. |
| **III. Test Before Implementation** | PASS. Test strategy (below) defines per-task tests authored from this plan and observed failing before implementation; the four mandatory areas + ≥8 tests (SC-008) are mapped to concrete modules. |
| **IV. Simplicity Over Complexity** | PASS. Sync SQLAlchemy (no async), no repository pattern (services use the session directly), no migration tool (`create_all` + seed), stdlib logging (no logging framework dep). Deviations justified in Complexity Tracking. |
| **V. Security By Default** | PASS. JWT signed + expiring; bcrypt hashes; owner-scoped queries for object-level authZ; generic login error; env-var secrets; receipt URLs stored-not-fetched. Detailed in "Security Design". |
| **VI. Maintainability Over Cleverness** | PASS. Mainstream libraries, explicit three-layer separation, clear names, no metaprogramming — every line explainable at interview. |

## Architecture & Design

### Layering (three thin layers — no repository pattern)

- **`app/routers/`** — HTTP concerns only: routing, status codes, dependency injection
  (`get_db`, `get_current_user`), wiring requests to services. One module per resource group.
- **`app/services.py`** — business logic: validation rules, budget-warning computation, report
  aggregation, category-deletion guard, currency-change guard. Functions receive a SQLAlchemy
  `Session` and the acting user and raise typed domain exceptions. Kept as one module at this
  size; split by domain only if it actually grows.
- **`app/models.py`** (ORM entities) and **`app/schemas.py`** (Pydantic request/response models,
  incl. pagination + error shapes) each hold all four entities together — they are small and read
  better in one file than scattered across many.
- **`app/security.py`** (hashing + JWT + `get_current_user`), **`app/database.py`** (`Base`,
  engine, `SessionLocal`, `get_db`, default-category seed), **`app/config.py`** (settings),
  **`app/logging_config.py`**, and **`app/errors.py`** (domain exceptions + the exception handlers
  that map them to the FR-034 categories).

The session is passed directly to service functions; no repository abstraction (needless
indirection at this scope — Principle IV).

### Error model (FR-034) — domain exception → category → HTTP status

A small set of domain exceptions is raised by services and translated once by FastAPI exception
handlers. Tests assert the **category** (and, for validation, the field + reason), not the raw
status number — but the mapping is fixed here for consistency:

| Category | HTTP | Raised when |
|---|---|---|
| invalid input (validation) | **422** | Pydantic schema failure, domain validation (amount/date bounds, inverted filter range, malformed pagination), bad currency format |
| unauthenticated | **401** | Missing / malformed / invalid / expired token; bad login credentials (one generic message) |
| forbidden | **403** | Modifying or deleting a **visible but unowned read-only** resource — i.e., a system-default category (FR-013) |
| not found | **404** | A resource id outside the user's scope — another user's expense/custom-category/budget, or a non-existent id (owner-scoped queries make cross-user resources indistinguishable from missing, which also avoids existence-enumeration leakage) |
| conflict | **409** | Duplicate email (FR-002), duplicate category name (FR-011), deleting an in-use category (FR-014, includes count), changing currency after expenses exist (FR-007) |
| success | 200 / 201 / 204 | 201 create; 204 delete; 200 otherwise |

Note: cross-user object access resolves to **404** rather than 403 by design — resources are
queried already filtered by owner, so an unowned id is simply absent from scope. This satisfies
both FR-023 (no cross-user access) and OWASP API1 (no BOLA enumeration). 403 is reserved for the
genuinely-visible-but-read-only system defaults.

### Validation (anchored from spec §Validation Rules)

Enforced by Pydantic where structural, by services where relational:

- **Amounts**: `Decimal`, ≤ `999_999_999.99`, ≤ 2 decimal places; expense `> 0`, budget `>= 0`.
  Stored as SQL `NUMERIC(11, 2)`; **serialized in JSON as a string** (e.g. `"42.50"`) so client
  float round-trips can't perturb the value (matches the SC-006 sum-equality criteria).
- **Expense date**: calendar `date`; reject if `> today_utc + 7 days`; no lower bound.
- **Currency**: exactly 3 ASCII letters, uppercased; **format only**, no registry check.
- **Email**: accepted-format, ≤ 254 chars, stored lowercased; unique case-insensitively.
- **Password**: 8–128 chars (validated on input, never stored or logged). **No composition rules**
  (NIST 800-63B favors length over forced character classes; adding them is unrequested scope —
  Principle I). Because bcrypt silently truncates input beyond 72 bytes, `security.py` pre-hashes as
  `base64(sha256(password))` before bcrypt — base64 (not the raw 32-byte digest, which can contain a
  `0x00` that bcrypt's C-string handling would truncate on) yields 44 null-free ASCII chars, so the
  full 8–128 range stays meaningful.
- **Display name** 1–100; **category name** 1–50, trimmed; **icon** non-empty; **color** `#RRGGBB`.
- **Description** ≤ 500 optional; **receipt URL** accepted-format, ≤ 2048, optional, **stored
  and returned only — never fetched** by the server.
- **Pagination**: `limit` (default 50, max 100) + `offset` (default 0, ≥ 0); malformed → 422.
- **Ordering (FR-036)**: expenses `date DESC, id DESC`; categories `is_system DESC, name ASC`;
  budgets `year DESC, month DESC, id DESC`.

### Budget-warning logic (FR-028/029)

On expense **create or update**, compute the month of the expense's `date` (UTC year+month).
`spent` = SUM of the user's expenses in that category for that month (a single aggregate query,
including the just-saved row). If a budget exists for that `category + month + owner` and
`spent > budget.amount` (strict), attach `budget_warning = {category_name, budget, spent,
exceeded_by = spent - budget}`; otherwise omit it. The label is `category_name` (a string), not the
key `category` — which is the nested category object everywhere else in the contract.

### Reports (FR-030–033) — computed in SQL, not Python loops

- **Monthly summary**: total + per-category `GROUP BY` SUM for the target month, **only**
  categories with non-zero spend (spec Clarification).
- **Trend**: for end month/year and `N` (default 6, inclusive, capped at 36), one total per
  month, **zero-filled** for empty months (months generated in code, totals from one grouped
  query).
- **Budget status**: for each budget in the target month, `spent` (aggregate) vs `budget`, with
  `remaining = budget - spent` (negative when exceeded).
- All amounts are in the user's default currency (single-currency invariant; FR-033).

### Security Design (Principle V; carries the spec's security items)

- **Auth tokens**: JWT signed HS256 with `SECRET_KEY` from env; short expiry (configurable,
  default 60 min); `sub` = user id. Integrity-protected and expiring, not forgeable opaque
  strings.
- **Passwords**: bcrypt via passlib, pre-hashed as `base64(sha256(password))` to defeat bcrypt's
  72-byte truncation (see Validation); only the salted hash is persisted; never returned, never
  logged. Response schemas structurally exclude the hash. No character-composition rules (NIST
  800-63B). **Pin** `passlib==1.7.4` with `bcrypt<4.1` (passlib 1.7.4 reads `bcrypt.__about__`,
  removed in bcrypt ≥4.1 → the well-known `AttributeError`).
- **JWT claims**: `sub` is encoded as a **string** (PyJWT validates/round-trips `sub` as a string;
  the integer user id is `str()`-cast on encode and parsed back on decode).
- **Login**: one generic failure message; no email-existence disclosure (FR-004). Registration
  knowingly discloses duplicate email (accepted tradeoff, spec Assumptions). **Rate limiting /
  brute-force protection is intentionally out of scope** — a deployment/proxy-layer concern, noted
  here as a decision, not an oversight.
- **Object-level authZ**: collection queries are filtered by `owner_id`; by-id lookups are
  owner-scoped so cross-user ids resolve to 404 (no existence disclosure).
- **Conflict integrity**: uniqueness is **DB-authoritative** — services catch `IntegrityError` → 409
  rather than SELECT-then-INSERT (race-free; single-user concurrency per spec) for `lower(email)`
  and custom category `(owner_id, lower(name))`. The budget unique key
  `(owner_id, category_id, year, month)` instead drives an **upsert** — `INSERT … ON CONFLICT … DO
  UPDATE` — because FR-026 *updates* an existing budget rather than conflicting. The category-vs-
  **default** name collision can't be one constraint (defaults are null-owner), so that case stays
  an explicit service check.
- **Secrets**: only via env (`SECRET_KEY`, `DATABASE_URL`); `.env.example` holds placeholders;
  real `.env` is gitignored. bandit scans the code (hook active now that `pyproject.toml` exists).
- **SSRF**: receipt URLs are stored/returned only; the server never dereferences them.
- **Transport**: TLS terminated at the deployment proxy (documented; out of app code scope).

### Performance Design (Performance gate — reviewed manually, no skill)

- **Indexes**: unique on `lower(email)`; expense `(owner_id, date)` and `(owner_id, category_id,
  date)` (the trailing `date` serves category-filtered lists' ordering for free); budget unique
  `(owner_id, category_id, year, month)`; partial unique on custom category `(owner_id, lower(name))`.
- **Aggregation in SQL**: budget checks and all reports use `SUM`/`GROUP BY`, never load-all-then-
  sum in Python.
- **Bounded result sets**: all list endpoints paginated (max page size 100).
- **Connection pooling**: SQLAlchemy engine default pool; one session per request via dependency.
- No caching layer (unjustified complexity at this scale).

### Logging & Documentation (Logging gate; SHOULD-have structured logging)

- **Structured logs** to stdout via stdlib `logging` with a JSON formatter (`logging_config.py`),
  initialized at startup — no logging-framework dependency (Principle IV). One line per request
  outcome plus explicit events for: registration, login success/failure (without revealing which
  credential failed), expense create/update (and whether a budget warning fired), blocked
  category deletion (with count), and any handled domain error.
- **Levels**: INFO for normal lifecycle, WARNING for rejected operations (validation/conflict),
  ERROR for unexpected failures (with stack traces). Records carry the acting `user_id` (when
  authenticated) and a **request id** generated by a small ASGI middleware registered in `main.py`
  (one per request, attached to every log record for correlation).
- **Never logged**: passwords, password hashes, JWTs, `Authorization` headers, or full request
  bodies (Logging gate / Principle V).
- **Documentation**: concise docstrings on public functions/classes (the *why*, not a restatement);
  the API self-documents via FastAPI's auto OpenAPI/Swagger UI at `/docs`. The deliverable
  `README.md` covers how to run, how to test, and the **two required design decisions** (candidates:
  sync-over-async simplicity, single-currency-per-user, or the 404-not-403 cross-user choice);
  `AI_USAGE.md` covers its four required sections. The Logging & Documentation gate formally fires
  during the tasks and implementation phases, but its expectations are planned here.

## Test Strategy (Testing gate; Principle III)

**Framework & isolation.** pytest + FastAPI `TestClient`. A session-scoped fixture creates the
schema on a dedicated **Postgres test database** (`TEST_DATABASE_URL`) and seeds defaults. For each
test, a function-scoped fixture opens one connection, begins an outer transaction, and binds a
`Session(bind=connection, join_transaction_mode="create_savepoint")`; the app's `get_db` dependency
is overridden to yield **that** session. This is the crucial detail: the services' own
`session.commit()` calls land on savepoints, so the fixture's single outer `rollback()` at teardown
still wipes everything — a naive `begin → rollback` would break the moment a service commits. Tests
are therefore independent and order-free. A real Postgres (not SQLite) is used so `NUMERIC`,
case-insensitive uniqueness, and aggregation behave exactly as in production.

**Style.** Behavior-first: most tests drive the public HTTP API (black-box, no implementation
details). A few unit tests cover pure functions where a full request would obscure the math:
budget-warning computation, trend month-window generation, and the date-bound check.

**Fixtures.** `client`, `db_session`, `auth_headers` (a registered+logged-in user), and a
`second_user` (for cross-user isolation). Tests construct their own data; no shared mutable state.

**Coverage of the four mandatory areas (SC-008, ≥8 tests):**

| Area | Module | Representative tests |
|---|---|---|
| Authentication | `tests/test_auth.py` | register success (no password echoed); duplicate email → 409; login success issues token; bad credentials → generic 401; protected route without token → 401; profile get/update; currency change allowed pre-expense, 409 post-expense |
| Expense CRUD | `tests/test_expenses.py` | create against default category; reject zero/negative/over-max/>2-decimals/>7-days-future (422); list with date/category/amount filters + inverted-range reject; get/update (re-validates)/delete; cross-user 404 isolation; pagination metadata |
| Budget checking logic | `tests/test_budgets.py` | set/update budget; zero allowed, negative rejected; one-per-category-per-month upsert; past/future month allowed; **warning present** when expense pushes month over budget with correct `budget/spent/exceeded_by`; **no warning** at-or-below |
| Report calculations | `tests/test_reports.py` | monthly summary total == sum and breakdown sums to total (non-zero categories only); trend zero-fills empty months over N; budget status spent-vs-budget matches data |
| (CLI client) | `tests/test_cli.py` | register→login persists token; `expense add` then `expense list` round-trips through the API |

Edge cases from spec §Edge Cases are folded into the relevant modules above. Each behavioral
task in `tasks.md` will pair with its test task, authored first and observed failing.

## Project Structure

### Documentation (this feature)

```text
specs/001-expense-tracker-api/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — entities, fields, constraints, indexes
├── quickstart.md        # Phase 1 — run & test instructions
├── contracts/           # Phase 1 — endpoint contracts
│   └── api.md
├── spec.md              # Feature specification (input)
└── tasks.md             # Phase 2 — created by /speckit-tasks (NOT here)
```

### Source Code (repository root)

```text
app/
├── main.py             # FastAPI app: logging init, request-id middleware, startup (create tables + seed), routers, handlers
├── config.py           # pydantic-settings (SECRET_KEY, DATABASE_URL, token TTL, page sizes)
├── logging_config.py   # structured JSON logging to stdout
├── database.py         # Base, engine, SessionLocal, get_db, seed_default_categories
├── security.py         # bcrypt (+SHA-256 pre-hash) hash/verify; JWT encode/decode; get_current_user
├── models.py           # all ORM entities: User, Category, Expense, Budget
├── schemas.py          # all Pydantic request/response models (incl. pagination + error shapes)
├── services.py         # business logic for auth, categories, expenses, budgets, reports
├── errors.py           # domain exceptions + exception handlers → FR-034 categories/status codes
└── routers/
    ├── auth.py         # register, login, GET/PATCH /users/me
    ├── categories.py
    ├── expenses.py
    ├── budgets.py
    └── reports.py

cli.py                  # Typer + httpx client (run: `python -m cli`): register, login, expense add/list, report
tests/
├── conftest.py         # fixtures: db_session, client, auth_headers, second_user
├── test_auth.py
├── test_expenses.py
├── test_categories.py
├── test_budgets.py
├── test_reports.py
└── test_cli.py

Dockerfile              # API image (slim base, non-root user)
docker-compose.yml      # api + postgres; api waits for db healthcheck
.env.example            # placeholders: SECRET_KEY, DATABASE_URL, ...
README.md               # run, test, two design decisions (deliverable)
AI_USAGE.md             # required four sections (deliverable)
```

**Structure Decision**: A single flat `app/` package — one module per concern, with `models.py`
and `schemas.py` each holding all four entities — plus a `routers/` subpackage, a top-level
`cli.py` client, and a `tests/` suite. Routers handle HTTP, `services.py` holds business logic,
`models.py` handles persistence: three responsibilities kept testable without a deep folder tree
(~15 files, not ~30). No backend/frontend split (no web UI) and no repository layer.

## Complexity Tracking

> Deviations from the most minimal possible solution, each justified.

| Item | Why needed | Simpler alternative rejected because |
|------|------------|--------------------------------------|
| **CLI client (`cli.py`)** | Developer-approved this session as a usability convenience and a second consumer of the API. | "No client at all" was the default; the developer explicitly chose a thin CLI. Kept minimal (Typer + httpx, no business logic) so it adds little surface. A web frontend was rejected as larger, less-aligned scope. |
| **Pagination on all list endpoints** | Spec Clarification 2026-06-01 (API consistency). | Paginating only expenses (the literal assignment) was rejected to avoid an inconsistent API; the uniform rule is simpler to reason about and test. |
| **Service layer** | Isolates business rules (budget warning, reports, deletion guard) for unit testing and interview clarity. | Putting logic in routers was rejected: it couples HTTP to rules and hurts testability. Still kept thin — no repository pattern beneath it. |
| **`expenses.currency` column** | `requirements.md` §3 lists Currency as an Expense attribute; stored as a deliberate **immutable snapshot** of the owner's currency at creation, and a safe extension point if single-currency is ever relaxed. | Deriving currency from the owner at read time was considered; the column never diverges (the currency-change guard blocks edits once expenses exist), so the snapshot is a knowingly accepted, requirements-backed denormalization, not an accident. |
```
