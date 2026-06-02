# Tasks: Personal Expense Tracker API

**Branch**: `001-expense-tracker-api` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

> **Conventions** — Phases are sequential; within a phase do tasks in order. `[test]` =
> write/extend tests from `plan.md` via **testing-skill** and observe them fail before any code.
> `[build]` includes logging + docstrings (**logging-docs-skill**) and applies the five gates inline
> (CLAUDE.md Step 5.4). Most tests are black-box HTTP via `TestClient`; **pure logic helpers also get
> direct unit tests** (marked *Unit (logic)*), folded into the relevant test file (plan §Test Strategy).
> DB-coupled logic (owner-scoping, dup-name, deletion guard, aggregation) is tested through the API.
> Every validation (422) test asserts the error names the **offending field + reason** (FR-034, plan §Error model).
> Every protected resource has at least one **`no-token → 401`** assertion (FR-005) — catches a router missing the `get_current_user` dependency.
> Paginated-list tests assert malformed and **over-max (`limit` > 100)** params → 422 (bounds the result set).
>
> **`schemas.py`, `services.py`, and `main.py` grow incrementally** (plan §Layering): each `[build]`
> task adds that resource's functions to the shared `schemas.py`/`services.py` and **registers its
> router in `main.py`** — not a file per resource. **`cli.py` is test-first-exempt** (thin client);
> T020's round-trip is an integration smoke test, not unit coverage.
> **Pure helpers live in their owning module** — the date-bound validation helper in `schemas.py`, business-logic helpers (budget-warning math, trend window) in `services.py`; **no new `utils.py`/`helpers.py`**.
> **Paginated list services reuse one shared limit/offset/total-count routine** (the pagination shape is centralized in `schemas.py`) — not copy-pasted per resource.

## Phase 0 — Setup
- [x] T001 Scaffold repo: `pyproject.toml` (FastAPI, SQLAlchemy 2.0 sync, psycopg3, PyJWT, bcrypt, pydantic-settings, Typer, httpx; dev: pytest, bandit, httpx2) + `app/` layout. Activates the security hook. (plan §Technical Context, §Project Structure)
- [x] T002 `config.py` (env: SECRET_KEY, DATABASE_URL, token TTL, page sizes) + `database.py` (Base, engine, SessionLocal, get_db — no model imports). (plan §Layering, §Constraints)
- [x] T003 `logging_config.py`: JSON logs to stdout; every record carries event/level/request_id/user_id. (logging-docs-skill; plan §Logging)
- [x] T004 `Dockerfile` (slim, non-root), `docker-compose.yml` (api + postgres healthcheck), `.env.example`. (deliverables; plan §Target Platform)
- [x] T005 `conftest.py` fixtures: session-scoped schema create + default-category seed on `TEST_DATABASE_URL`; client (wraps `app.main:app`, first exercised in Phase 2), db_session (per-test outer-tx + savepoint rollback), auth_headers, second_user. (plan §Test Strategy)

## Phase 1 — Foundation
- [x] T006 `models.py`: User, Category, Expense, Budget + indexes (lower(email) unique; expense (owner,date)/(owner,category,date); budget unique (owner,category,year,month); partial-unique custom (owner,lower(name))). (plan §Performance; data-model)
- [x] T007 `errors.py` domain exceptions + handlers → FR-034 categories/status (500 leaks nothing) + `schemas.py` pagination & error shapes; handlers log `domain_error` (category + status) — **WARNING** for rejected ops (validation/conflict/forbidden/not-found), **ERROR** (+stack trace, server-side only) for 500. (FR-034/035; plan §Error model, §Logging)
- [x] T008 `main.py`: app, request-id middleware, startup create_all + idempotent seed of 7 default categories, and register the T007 exception handlers. Routers are added per build task. (FR-008; plan §Layering)

## Phase 2 — US1 Authentication (P1)
- [x] T009 [test] `test_auth.py`: register (no password echo, currency normalized to uppercase, password <8/>128 & non-3-letter currency→422), dup email→409, login token, bad creds→generic 401, missing/malformed/expired token→401, profile get/update, **email immutable** (FR-007), currency change pre-expense ok / post-expense→409 (seed the blocking expense via `db_session` — expense API arrives Phase 3); **500 handler** — a service forced to raise returns a generic 500 with no exception detail/stack-trace and logs the error server-side (FR-034 / A05). **Unit (logic):** password pre-hash+verify round-trips and treats >72-byte passwords as distinct; JWT encode→decode returns the user id, and expired/tampered tokens are rejected. (FR-001–007, 034; plan §Security, §Error model, §Test Strategy)
- [x] T010 [build] `security.py` (bcrypt+sha256 prehash, JWT, get_current_user — hash/verify + encode/decode are **pure helpers**, unit-tested in T009), auth schemas + service, `routers/auth.py` (register, login, **GET/PATCH `/users/me` profile**, **currency-change guard** — display name always editable, currency blocked once expenses exist; register in `main.py`); log register (`email_domain` only — never the full address/password), login_success, login_failure (no credential-revealing field). (FR-001–007; plan §Security, §Logging)

## Phase 3 — US2 Expenses (P2)
- [x] T011 [test] `test_expenses.py`: create vs default category (amount returned as a string, e.g. `"42.50"` — plan §110); reject zero/neg/over-max/>2dp/>7d (422), inaccessible category (another user's — seed via `db_session`, category API arrives Phase 4), bad receipt-URL, description>500; client-supplied currency ignored (FR-017); list filters + **inverted date and amount ranges**→422; get/update(re-validate)/delete; cross-user 404; pagination meta. **Unit (logic):** date-bound helper (reference date passed in) accepts today and +7d, rejects +8d. (FR-016–023, 035, 036; plan §Validation, §Test Strategy)
- [x] T012 [build] expense schemas + service (validation incl. **date-bound check as a pure helper taking the reference date as a parameter** (clock injected, not read internally), amounts **serialized as strings**, receipt URL **stored/returned only — never fetched** (no SSRF, A10), owner-scope, eager-load category, ordering date desc/id desc, pagination) + `routers/expenses.py` (register in `main.py`); log expense_created/updated. (FR-016–023, 035, 036; plan §Validation, §Performance)

## Phase 4 — US3 Categories (P3)
- [x] T013 [test] `test_categories.py`: list 7 defaults; create custom; dup name (incl. defaults)→409; update; default/other-user modify→403/404; delete-in-use→409 w/ count + reassign advisory; delete unused removes budgets; pagination meta + order (is_system DESC, name ASC). (FR-008–015, 035, 036)
- [x] T014 [build] category schemas + service (dup guard via IntegrityError + default-name check, read-only defaults, delete guards (in-use→409 with count + reassign-first advisory), budget cascade, pagination + ordering) + `routers/categories.py` (register in `main.py`); log category_delete_blocked. (FR-008–015, 035, 036; plan §Conflict integrity)

## Phase 5 — US4 Budgets & warnings (P4)
- [x] T015 [test] `test_budgets.py`: set/upsert; zero ok / negative/over-max/>2dp→422; bad month(≠1–12)/year→422; one-per-cat-month; past/future ok; list + delete; budget on inaccessible/other-user category→404; cross-user 404; pagination meta + order (year DESC, month DESC, id DESC); warning with correct budget/spent/exceeded_by on create **and** on update over budget, none at-or-below; **month-basis** — back-/future-dated expenses are checked against *their own* month's budget, not the current calendar month (current month unaffected). **Unit (logic):** budget-warning math — `exceeded_by = spent − budget`, warn iff `spent > budget` (strict), none at/below. (FR-023–029, 035, 036; plan §Budget-warning logic, §Test Strategy)
- [x] T016 [build] budget schemas + service (upsert ON CONFLICT, validation, list/delete, pagination + ordering) + budget-warning wired into expense create/update — **math as a pure helper** (from spent+budget), fed by the SUM query, and set the `budget_warning` bool on the expense_created/updated logs — + `routers/budgets.py` (register in `main.py`). (FR-023–029, 035, 036; plan §Budget-warning logic, §Logging)

## Phase 6 — US5 Reports (P5)
- [x] T017 [test] `test_reports.py`: monthly summary total==sum & breakdown (non-zero only), amounts as strings (SC-006); trend default 6 + cap 36, zero-fills empty months over N; budget status spent-vs-budget with remaining (negative when exceeded). **Unit (logic):** trend month-window generation — N months ending at Y/M, correct order, zero-fill skeleton. (FR-030–033; plan §Reports, §Test Strategy)
- [x] T018 [build] report schemas + service (SQL SUM/GROUP BY, **trend month-window as a pure helper** + cap + zero-fill, budget-status via a **single grouped aggregate** — group the month's expenses by category, join the month's budgets; not a per-budget SUM — remaining, single currency) + `routers/reports.py` (register in `main.py`). (FR-030–033; plan §Reports, §Performance)

## Phase 7 — CLI & logging verification
- [x] T019 [build] `cli.py` (Typer+httpx: register, login w/ token persist, expense add/list, report). Test-first-exempt (see Conventions). (plan §Complexity Tracking)
- [x] T020 [test] `test_cli.py`: register→login→expense add→list round-trip smoke test through the API. (plan §Test Strategy, §Complexity Tracking)
- [x] T021 [test] `test_logging.py`: register then login and assert records carry request_id + expected event/user_id and **never** contain the password, its hash, the token, or the full email address; **and a rejected op emits a `domain_error` record (category + status, WARNING) carrying no sensitive data** — the one place log output is asserted (plan §Test Strategy). (plan §Logging, §Test Strategy)

## Phase 8 — Step 6 review & deliverables
- [x] T022 Run full suite green; confirm ≥8 tests + all 4 areas (SC-008); confirm every FR implemented and no unrequested features. (Principle I; SC-008)
- [x] T023 `README.md` (run, test, two design decisions) + `AI_USAGE.md` (four sections); logging-docs-skill review. (deliverables; plan §Documentation)
- [x] T024 Final five-gate review via `code-review-subagent` (Security, Testing, Performance, Logging, Architecture) over the **whole change incl. deliverables**; resolve findings. (CLAUDE.md Step 6)
