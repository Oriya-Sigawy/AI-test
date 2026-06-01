# Phase 1 — Data Model

Entities, fields, relationships, constraints, and indexes for the Personal Expense Tracker.
Field-level validation lives in `spec.md` §Validation Rules and is summarized here where it maps
to a storage or constraint decision. Money is `Decimal` in code, `NUMERIC(11, 2)` in storage
(fits the `999,999,999.99` ceiling exactly). All timestamps are `TIMESTAMPTZ`, UTC.

**Storage conventions** (decided with the developer): primary keys are **auto-increment integers**
(`BIGSERIAL`); amount columns carry a `CHECK` for their bounds; and foreign keys **encode the
business deletion rules** — `expenses.category_id` is `ON DELETE RESTRICT` (the DB refuses to drop
an in-use category, backing FR-014) while `budgets.category_id` and all `owner_id` keys are
`ON DELETE CASCADE` (budgets die with their category per FR-015; a user's rows die with the user).
Services still check first so they can return the FR-014 expense **count**; the FK rules are the
backstop (defense in depth). Timestamps are maintained **app-layer by the ORM** — `created_at` via
`server_default=now()`, `updated_at` via SQLAlchemy's `onupdate=now()` on every flush — not by DB
triggers, keeping the behavior visible in the models and portable.

## Entity overview & relationships

```text
User 1───* Category (custom only; system defaults have owner = NULL, shared by all)
User 1───* Expense  *───1 Category
User 1───* Budget   *───1 Category
```

- A `User` owns their custom `Category`, `Expense`, and `Budget` rows.
- System-default categories are ownerless (`owner_id IS NULL`) and visible to every user.
- An `Expense` references exactly one `Category` (a default or the owner's own).
- A `Budget` references one `Category`, scoped to a `(month, year)`; at most one per
  `(owner, category, month, year)`.

## User

| Field | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | auto-increment integer identifier |
| `email` | string, ≤254 | stored lowercased; **unique on `lower(email)`** (FR-002) |
| `password_hash` | string | bcrypt hash; **never** returned or logged (FR-003) |
| `display_name` | string, 1–100 | mutable any time |
| `default_currency` | char(3) | 3 ASCII letters, uppercased; mutable only while the user has **zero** expenses (FR-007) |
| `created_at` / `updated_at` | timestamptz | |

- **Constraints**: unique `lower(email)`.
- **Currency-change guard** (service): reject if any expense exists for the user → 409.

## Category

| Field | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | auto-increment integer identifier |
| `name` | string, 1–50 | trimmed; unique per user case-insensitively, **including** defaults (FR-011) |
| `icon` | string, non-empty | icon identifier (e.g. `"food"`) |
| `color` | string `#RRGGBB` | hex color |
| `is_system` | bool | `true` for the seven defaults |
| `owner_id` | FK→User, nullable | `NULL` for system defaults; user id for custom |
| `created_at` / `updated_at` | timestamptz | |

- **Constraints**: partial unique index on custom rows `(owner_id, lower(name))`; uniqueness
  against defaults enforced in the service (defaults have null owner).
- **Seed (idempotent)**: Food, Transport, Entertainment, Shopping, Bills, Health, Other — each
  with a predefined icon and color, `is_system = true`, `owner_id = NULL`.
- **Rules**: system defaults are read-only (modify/delete → 403, FR-013). A custom category with
  referencing expenses cannot be deleted (→ 409 with expense **count**, FR-014). Deleting an
  unused custom category also removes its budgets (FR-015).

## Expense

| Field | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | auto-increment integer identifier |
| `owner_id` | FK→User | not null |
| `category_id` | FK→Category | must be a default or owned by the user; else 404/422 |
| `amount` | NUMERIC(11,2) | `> 0`, ≤ 999,999,999.99, ≤ 2 decimals (FR-018/019) |
| `currency` | char(3) | copied from owner's `default_currency` at creation; client value ignored (FR-017). A deliberate **immutable snapshot** (matches `requirements.md` §3); it never diverges from the owner because the currency-change guard blocks edits once expenses exist — see plan Complexity Tracking |
| `date` | date | calendar date; ≤ today_utc + 7 days; no lower bound (FR-020) |
| `description` | string ≤500, nullable | optional |
| `receipt_url` | string ≤2048, nullable | optional; **stored & returned only, never fetched** |
| `created_at` / `updated_at` | timestamptz | |

- **Indexes**: `(owner_id, date)` for date-filtered lists and `(owner_id, category_id, date)` for
  category-filtered lists — the trailing `date` lets the category filter also serve the `date DESC`
  ordering (FR-036) and the per-month aggregation, so no extra sort is needed (the `id DESC`
  tiebreak is resolved outside the index, which is negligible at this scale).
- **FK rule**: `category_id` is `ON DELETE RESTRICT` — the DB blocks deleting a referenced category
  (FR-014 backstop). `owner_id` is `ON DELETE CASCADE`.
- **List ordering (FR-036)**: `date DESC, id DESC`.
- **Filters (FR-021)**: date range, category, amount range; inverted ranges rejected (422).

## Budget

| Field | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | auto-increment integer identifier |
| `owner_id` | FK→User | not null |
| `category_id` | FK→Category | must be accessible to the user |
| `amount` | NUMERIC(11,2) | `>= 0` (zero allowed), ≤ 999,999,999.99, ≤ 2 decimals (FR-025) |
| `month` | smallint 1–12 | |
| `year` | int | `CHECK (year BETWEEN 2000 AND 2100)` — blocks `year = 0`, matches the rigor of the amount/month checks |
| `created_at` / `updated_at` | timestamptz | |

- **Constraints**: unique `(owner_id, category_id, year, month)` — at most one per category per
  month; setting an existing one updates it (FR-026, upsert). `category_id` and `owner_id` are
  `ON DELETE CASCADE` (budgets are removed with their category, FR-015, or with the user).
- **List ordering (FR-036)**: `year DESC, month DESC, id DESC`.
- Past/present/future months all allowed (FR-024).

## Authentication Token (not persisted)

A signed JWT issued at login; `sub` = user id, with an expiry claim. Verified per request to
identify and authorize the user. No server-side token table (stateless; expires naturally).

## Derived / computed (no table)

- **Budget warning** (FR-028/029): for an expense's `(category, month-of-date)`, `spent` =
  `SUM(amount)` of the owner's expenses in that category+month, **computed after the create/update
  is persisted so the just-saved expense is included**. Warning when `spent` is **strictly greater
  than** `budget` — an expense that brings the total to exactly the budget does **not** warn.
- **Reports** (FR-030–033): monthly summary, trend, and budget status are computed via SQL
  aggregation over `Expense` (+ `Budget` for status); no stored report rows.

## Cross-cutting invariants

- **Ownership**: every `Expense`/`Budget`/custom `Category` query is filtered by `owner_id`;
  unowned ids resolve to 404 (FR-023).
- **Single currency**: every expense's `currency` equals the owner's `default_currency`; reports
  never mix currencies (FR-017/033). Enforced by copying on create and by the currency-change
  guard.
- **Uniqueness is DB-authoritative**: services rely on the unique indexes and catch `IntegrityError`
  → 409 (rather than SELECT-then-INSERT) for `lower(email)` and custom category
  `(owner_id, lower(name))`; the budget unique key drives `INSERT … ON CONFLICT … DO UPDATE`
  (FR-026 upsert). Category-vs-system-default name collisions are an explicit service check (defaults
  are null-owner, so no single constraint can cover them).
