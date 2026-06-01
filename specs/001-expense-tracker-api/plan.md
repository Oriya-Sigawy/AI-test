# Implementation Plan: Personal Expense Tracker API

**Branch**: `001-expense-tracker-api` | **Date**: 2026-06-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-expense-tracker-api/spec.md`

## Summary

A REST API for personal expense tracking: token-authenticated users record expenses, organize
them with system-default and custom categories, set monthly per-category budgets, receive
budget-exceeded warnings, and view spending reports (monthly summary, multi-month trend, budget
status). All amounts use the owner's single default currency; conversion is out of scope.

A single FastAPI service over PostgreSQL via **synchronous** SQLAlchemy 2.0, in three thin layers
(routers → services → models) with Pydantic v2 for validation/serialization, JWT bearer tokens,
and bcrypt password hashing. A thin **Typer + httpx CLI client** (developer-approved) drives the
same HTTP API. Sync I/O, no repository layer, and no migration framework are deliberate
simplicity choices (Principle IV) that keep every line explainable at the follow-up interview.

## Technical Context

**Language/Version**: Python 3.11+ (developed on 3.12)

**Primary Dependencies**: FastAPI · Uvicorn (ASGI) · Pydantic v2 + pydantic-settings · SQLAlchemy
2.0 (**sync**) · psycopg 3 · PyJWT · passlib[bcrypt] · Typer + httpx (CLI). Dev: pytest (+ httpx
`TestClient`), bandit (in `pyproject.toml`).

**Storage**: PostgreSQL 16 (relational, required). Schema created at startup via
`Base.metadata.create_all()`; default categories seeded idempotently. No migration framework
(see Complexity Tracking).

**Testing**: pytest. Integration tests drive the API through `TestClient` against a dedicated
Postgres **test** database, each inside a transaction rolled back on teardown. Pure logic
(budget math, trend window, date bounds) also covered by unit tests. (Details in Test Strategy.)

**Target Platform**: Linux container; `Dockerfile` + `docker-compose.yml` run API + Postgres.
TLS terminated by the deployment's reverse proxy (out of app scope; noted in README).

**Project Type**: Web service (REST API) + a thin first-party CLI client.

**Performance Goals**: Interactive single-user workload. Targeted indexes and SQL aggregation
keep common operations (expense list, reports, budget check) within tens of milliseconds on
realistic data (low thousands of expenses). No high-throughput target.

**Constraints**: Secrets only via env (`SECRET_KEY`, `DATABASE_URL`); JSON logs to stdout; no
secrets/passwords in logs or responses; receipt URLs are never fetched (no SSRF surface).

**Scale/Scope**: Single-developer learning project; a handful of users, low thousands of
expenses each; ~6 resource groups (auth, users, categories, expenses, budgets, reports).

## Constitution Check

*GATE: passed before Phase 0; re-checked after Phase 1 design — still passing.*

| Principle | Assessment |
|---|---|
| **I. Requirements First** | PASS. Every endpoint/rule traces to an FR in `spec.md`. Two authorized scope items beyond the literal assignment, both tracked in Complexity Tracking: the **CLI client** (developer-approved) and **pagination on all list endpoints** (spec Clarification 2026-06-01). No other inferred features. |
| **II. Specification-Driven** | PASS. Plan derives from the reviewed spec; tasks and code derive from this plan. No code in this phase. |
| **III. Test Before Implementation** | PASS. Per-task tests are authored from this plan and observed failing before code; the four mandatory areas + ≥8 tests (SC-008) map to concrete modules (Test Strategy). |
| **IV. Simplicity Over Complexity** | PASS. Sync SQLAlchemy, no repository pattern, no migration tool (`create_all` + seed), stdlib logging. Deviations justified in Complexity Tracking. |
| **V. Security By Default** | PASS. Signed/expiring JWT; bcrypt hashes; owner-scoped queries; generic login error; env-var secrets; receipt URLs stored-not-fetched. See Security Design. |
| **VI. Maintainability Over Cleverness** | PASS. Mainstream libraries, explicit three-layer separation, clear names, no metaprogramming. |

## Architecture & Design

### Layering (three thin layers — no repository pattern)

- **`app/routers/`** — HTTP only: routing, status codes, dependency injection (`get_db`,
  `get_current_user`), wiring requests to services. One module per resource group.
- **`app/services.py`** — business logic: validation rules, budget-warning computation, report
  aggregation, category-deletion guard (blocks while expenses reference it; on a successful delete
  of an unused category, **removes any budgets that referenced it** — FR-015), currency-change
  guard. Functions take a `Session` and the acting user and raise typed domain exceptions. One
  module at this size; split only if it grows.
- **`app/models.py`** (ORM entities) and **`app/schemas.py`** (Pydantic request/response models,
  incl. pagination + error shapes) each hold all four entities together — small enough to read
  better in one file than scattered.
- **`app/security.py`** (hashing + JWT + `get_current_user`), **`app/database.py`** (`Base`,
  engine, `SessionLocal`, `get_db` — **pure infrastructure, imports no domain models**, so the
  dependency only ever flows `models → database`), **`app/config.py`**,
  **`app/logging_config.py`**, **`app/errors.py`** (domain exceptions + the handlers that map them
  to the FR-034 categories). Seeding the default categories is **not** here — it needs the
  `Category` model, so it lives in `main.py`'s startup (the composition root), keeping `database.py`
  free of any upward dependency.

The session is passed directly to services; no repository abstraction (needless indirection here).

### Error model (FR-034) — domain exception → category → HTTP status

Services raise a small set of domain exceptions, translated once by FastAPI handlers. Tests assert
the **category** (and, for validation, field + reason), not the raw status — but the mapping is
fixed here:

| Category | HTTP | Raised when |
|---|---|---|
| invalid input (validation) | **422** | Pydantic schema failure, domain validation (amount/date bounds, inverted filter range, malformed pagination), bad currency format |
| unauthenticated | **401** | Missing / malformed / invalid / expired token; bad login credentials (one generic message) |
| forbidden | **403** | Modifying/deleting a **visible-but-unowned read-only** resource — a system-default category (FR-013) |
| not found | **404** | A resource id outside the user's scope (another user's expense/category/budget, or non-existent). Owner-scoped queries make cross-user ids indistinguishable from missing, satisfying FR-023 and avoiding OWASP-API1 enumeration. **403 is reserved only for the genuinely-visible system defaults.** |
| conflict | **409** | Duplicate email (FR-002), duplicate category name (FR-011), deleting an in-use category (FR-014; body carries the associated-expense **count** + a reassign-first advisory), changing currency after expenses exist (FR-007) |
| unexpected | **500** | Any unhandled exception — **generic body, no exception detail or stack trace returned to the client**; the full error (with stack trace) is logged server-side only (`domain_error`/ERROR), so internals never leak (A05) |
| success | 200 / 201 / 204 | 201 create; 204 delete; 200 otherwise |

### Validation (anchored from spec §Validation Rules)

Enforced by Pydantic where structural, by services where relational:

- **Amounts**: `Decimal`, ≤ `999_999_999.99`, ≤ 2 decimals; expense `> 0`, budget `>= 0`. Stored
  as `NUMERIC(11, 2)`; **serialized in JSON as a string** (e.g. `"42.50"`) so client float
  round-trips can't perturb the value (SC-006 sum-equality).
- **Expense date**: calendar `date`; reject if `> today_utc + 7 days`; no lower bound.
- **Currency**: exactly 3 ASCII letters, uppercased; **format only**, no registry check.
- **Email**: accepted-format, ≤ 254 chars, stored lowercased; unique case-insensitively.
- **Password**: 8–128 chars; validated on input, never stored/logged. **No composition rules**
  (NIST 800-63B favors length; adding them is unrequested scope). Pre-hashed before bcrypt to
  defeat its 72-byte truncation — see Security Design.
- **Display name** 1–100; **category name** 1–50, trimmed; **icon** non-empty; **color** `#RRGGBB`.
- **Description** ≤ 500 optional; **receipt URL** accepted-format, ≤ 2048, optional, **stored and
  returned only — never fetched**.
- **Budget month/year**: `month` 1–12, valid `year`; malformed → 422.
- **Pagination**: `limit` (default 50, max 100) + `offset` (default 0, ≥ 0); malformed → 422.
- **Ordering (FR-036)**: expenses `date DESC, id DESC`; categories `is_system DESC, name ASC`;
  budgets `year DESC, month DESC, id DESC`.

### Budget-warning logic (FR-028/029)

On expense **create or update**, compute the month of the expense's `date` (UTC year+month).
`spent` = SUM of the user's expenses in that category for that month (one aggregate query,
including the just-saved row). If a budget exists for that `category + month + owner` and
`spent > budget.amount` (strict), attach `budget_warning = {category_name, budget, spent,
exceeded_by = spent - budget}`; otherwise omit it. The label is `category_name` (a string), not
the key `category` (the nested category object used everywhere else in the contract).

### Reports (FR-030–033) — computed in SQL, not Python loops

- **Monthly summary**: total + per-category `GROUP BY` SUM for the target month, **only**
  categories with non-zero spend (spec Clarification).
- **Trend**: for end month/year and `N` (default 6, inclusive, capped at 36), one total per month,
  **zero-filled** for empty months (months generated in code, totals from one grouped query).
- **Budget status**: per budget in the target month, `spent` (aggregate) vs `budget`, with
  `remaining = budget - spent` (negative when exceeded).
- All amounts in the user's default currency (single-currency invariant; FR-033).

### Security Design (Principle V; carries the spec's security items)

- **Auth tokens**: JWT signed HS256 with `SECRET_KEY` from env; short expiry (configurable,
  default 60 min); `sub` = user id, encoded/decoded as a **string** (PyJWT round-trips `sub` as a
  string; the integer id is `str()`-cast on encode, parsed back on decode).
- **Passwords**: bcrypt via passlib, pre-hashed as `base64(sha256(password))` before bcrypt — this
  defeats bcrypt's 72-byte truncation, and base64 (rather than the raw 32-byte digest, which can
  contain a `0x00` that bcrypt's C-string handling would truncate on) yields 44 null-free ASCII
  chars, so the full 8–128 range stays meaningful. Only the salted hash is persisted; never
  returned (response schemas exclude it), never logged. **Pin** `passlib==1.7.4` with `bcrypt<4.1`
  (1.7.4 reads `bcrypt.__about__`, removed in ≥4.1 → the well-known `AttributeError`).
- **Login**: one generic failure message; no email-existence disclosure (FR-004). Registration
  knowingly discloses duplicate email (accepted tradeoff, spec Assumptions). **Rate limiting /
  brute-force protection is intentionally out of scope** — a proxy-layer concern, a decision not an
  oversight.
- **Object-level authZ**: collection queries filtered by `owner_id`; by-id lookups owner-scoped, so
  cross-user ids resolve to 404 (no existence disclosure — see Error model).
- **Conflict integrity**: uniqueness is **DB-authoritative** — services catch `IntegrityError` → 409
  (race-free; no SELECT-then-INSERT) for `lower(email)` and custom category `(owner_id,
  lower(name))`. The budget key `(owner_id, category_id, year, month)` instead drives an **upsert**
  (`INSERT … ON CONFLICT … DO UPDATE`), since FR-026 *updates* an existing budget. The category-vs-
  **default** name collision can't be one constraint (defaults are null-owner), so it stays an
  explicit service check.
- **Secrets**: only via env; `.env.example` holds placeholders; real `.env` gitignored. bandit
  scans the code (the security hook activates once `pyproject.toml` exists — i.e. from the
  implementation phase onward).
- **SSRF**: receipt URLs are stored/returned only; never dereferenced.
- **Transport**: TLS terminated at the deployment proxy (out of app code scope).

### Performance Design (Performance gate — reviewed manually, no skill)

- **Indexes**: unique on `lower(email)`; expense `(owner_id, date)` and `(owner_id, category_id,
  date)` (trailing `date` serves category-filtered ordering for free); budget unique `(owner_id,
  category_id, year, month)`; partial unique on custom category `(owner_id, lower(name))`.
- **SQL aggregation**: budget checks and all reports use `SUM`/`GROUP BY`, never load-all-then-sum.
- **No N+1**: expense responses embed the nested `category`, so list/get-expense queries
  **eager-load `Expense.category`** (`selectinload`) — one expense query + one category query per
  page, never one category load per row.
- **Bounded result sets**: all list endpoints paginated (max page size 100).
- **Pooling**: SQLAlchemy engine default pool; one session per request via dependency.
- No caching layer (unjustified at this scale).

### Logging & Documentation (Logging gate; SHOULD-have structured logging)

- **Structured logs** to stdout via stdlib `logging` with a JSON formatter (`logging_config.py`),
  initialized at startup — no logging-framework dependency. Every record carries `event`, `level`,
  `request_id`, and `user_id` (null when unauthenticated); event-specific fields are listed below.
  One line per request outcome plus explicit events:
  - `register` — `email_domain` only (never the address or password).
  - `login_success` / `login_failure` — `user_id` on success; failure carries **no** field that
    reveals which credential was wrong.
  - `expense_created` / `expense_updated` — `expense_id`, `category_id`, `budget_warning` (bool;
    logged at **INFO, not WARNING** — per the assignment's *Budget Alerts*, an exceeded budget is a
    business-normal outcome surfaced in the `budget_warning` **response field** of the same name, not
    an operational anomaly; "warning" here is that API field's name, not a log severity).
  - `category_delete_blocked` — `category_id`, `expense_count`.
  - `domain_error` — `category` (the FR-034 bucket) and `status`.
- **Levels**: INFO normal lifecycle, WARNING rejected operations (validation/conflict), ERROR
  unexpected failures (with stack traces). The `request_id` originates in a small ASGI middleware
  in `main.py` and is attached to every record.
- **Never logged**: passwords, hashes, JWTs, `Authorization` headers, or full request bodies.
- **Documentation**: concise docstrings (first line = *what* the function does, plus a one-line note
  per non-trivial argument), with comments reserved for the *why*; the API self-documents via FastAPI's OpenAPI/
  Swagger UI at `/docs`. `README.md` covers run, test, and the **two required design decisions**
  (candidates: sync-over-async, single-currency-per-user, or 404-not-403); `AI_USAGE.md` covers its
  four sections. The gate formally fires during tasks/implementation; its expectations are set here.

## Test Strategy (Testing gate; Principle III)

**Framework & isolation.** pytest + `TestClient`. A session-scoped fixture creates the schema on a
dedicated **Postgres test database** (`TEST_DATABASE_URL`) and seeds defaults. Per test, a
function-scoped fixture opens one connection, begins an outer transaction, and binds a
`Session(bind=connection, join_transaction_mode="create_savepoint")`; `get_db` is overridden to
yield **that** session. The crucial detail: services' own `session.commit()` calls land on
savepoints, so the fixture's single outer `rollback()` at teardown still wipes everything (a naive
`begin → rollback` would break the moment a service commits). Tests are independent and order-free.
Real Postgres (not SQLite) so `NUMERIC`, case-insensitive uniqueness, and aggregation match prod.

**Style.** Behavior-first: most tests drive the public HTTP API (black-box). A few unit tests cover
pure functions where a request would obscure the math: budget-warning computation, trend
month-window generation, and the date-bound check.

**Fixtures.** `client`, `db_session`, `auth_headers` (a registered+logged-in user), `second_user`
(cross-user isolation). Tests build their own data; no shared mutable state.

**Coverage of the four mandatory areas (SC-008, ≥8 tests):**

| Area | Module | Representative tests |
|---|---|---|
| Authentication | `tests/test_auth.py` | register success (no password echoed); duplicate email → 409; login issues token; bad credentials → generic 401; protected route without token → 401; profile get/update; currency change allowed pre-expense, 409 post-expense |
| Expense CRUD | `tests/test_expenses.py` | create against default category; reject zero/negative/over-max/>2-decimals/>7-days-future (422); list with date/category/amount filters + inverted-range reject; get/update (re-validates)/delete; cross-user 404 isolation; pagination metadata |
| Budget checking logic | `tests/test_budgets.py` | set/update; zero allowed, negative rejected; one-per-category-per-month upsert; past/future month allowed; **warning present** when an expense pushes the month over budget (correct `budget/spent/exceeded_by`); **no warning** at-or-below |
| Report calculations | `tests/test_reports.py` | monthly summary total == sum and breakdown sums to total (non-zero categories only); trend zero-fills empty months over N; budget status spent-vs-budget matches data |
| (CLI client) | `tests/test_cli.py` | register→login persists token; `expense add` then `expense list` round-trips through the API |

Edge cases from spec §Edge Cases are folded into the relevant modules. Each behavioral task in
`tasks.md` pairs with its test task, authored first and observed failing.

**Logging assertions** (`tests/test_logging.py`, via pytest `caplog`/a captured handler): register
then login and assert the emitted records (a) carry `request_id` and the expected `event`/`user_id`,
and (b) **never** contain the password, its hash, or the issued token — verifying the "never logged"
invariant above rather than trusting it. This is the one place log *output* is asserted; everywhere
else logs are a side effect, not the behavior under test.

## Project Structure

### Documentation (this feature)

```text
specs/001-expense-tracker-api/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — entities, fields, constraints, indexes
├── quickstart.md        # Phase 1 — run & test instructions
├── contracts/api.md     # Phase 1 — endpoint contracts
├── spec.md              # Feature specification (input)
└── tasks.md             # Phase 2 — created by /speckit-tasks (NOT here)
```

### Source Code (repository root)

```text
app/
├── main.py             # FastAPI app + composition root: logging init, request-id middleware, startup (create tables + seed default categories — imports models freely as the top of the dep tree), routers, handlers
├── config.py           # pydantic-settings (SECRET_KEY, DATABASE_URL, token TTL, page sizes)
├── logging_config.py   # structured JSON logging to stdout
├── database.py         # Base, engine, SessionLocal, get_db (infrastructure only — no model imports)
├── security.py         # bcrypt (+SHA-256 pre-hash) hash/verify; JWT encode/decode; get_current_user
├── models.py           # all ORM entities: User, Category, Expense, Budget
├── schemas.py          # all Pydantic request/response models (incl. pagination + error shapes)
├── services.py         # business logic for auth, categories, expenses, budgets, reports
├── errors.py           # domain exceptions + handlers → FR-034 categories/status codes
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
├── test_logging.py
└── test_cli.py

Dockerfile              # API image (slim base, non-root user)
docker-compose.yml      # api + postgres; api waits for db healthcheck
.env.example            # placeholders: SECRET_KEY, DATABASE_URL, ...
README.md               # run, test, two design decisions (deliverable)
AI_USAGE.md             # required four sections (deliverable)
```

**Structure Decision**: One flat `app/` package — a module per concern, with `models.py` and
`schemas.py` each holding all four entities — plus a `routers/` subpackage, a top-level `cli.py`,
and a `tests/` suite. Routers handle HTTP, `services.py` holds business logic, `models.py`
persistence: three responsibilities, testable without a deep tree (~15 files, not ~30). No
backend/frontend split (no web UI) and no repository layer.

## Complexity Tracking

> Deviations from the most minimal possible solution, each justified.

| Item | Why needed | Simpler alternative rejected because |
|------|------------|--------------------------------------|
| **CLI client (`cli.py`)** | Developer-approved as a usability convenience and a second API consumer. | "No client" was the default; the developer chose a thin CLI. Kept minimal (Typer + httpx, no business logic). A web frontend was larger, less-aligned scope. |
| **Pagination on all list endpoints** | Spec Clarification 2026-06-01 (API consistency). | Paginating only expenses (the literal assignment) gives an inconsistent API; one uniform rule is simpler to reason about and test. |
| **Service layer** | Isolates business rules (budget warning, reports, deletion guard) for unit testing and interview clarity. | Logic in routers couples HTTP to rules and hurts testability. Still thin — no repository beneath it. |
| **`expenses.currency` column** | `requirements.md` §3 lists Currency as an Expense attribute; stored as an **immutable snapshot** of the owner's currency at creation, and a safe extension point if single-currency is relaxed. | Deriving currency at read time was considered; the column never diverges (the currency-change guard blocks edits once expenses exist), so the snapshot is an accepted, requirements-backed denormalization. |
