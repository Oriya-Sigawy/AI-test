# Feature Specification: Personal Expense Tracker API

**Feature Branch**: `001-expense-tracker-api`

**Created**: 2026-06-01

**Status**: Draft

**Input**: User description: "Build a REST API for a personal expense tracking application. Users register and log in with token-based auth and hashed passwords, then track expenses, organize them into categories (system defaults plus custom categories), set monthly per-category budgets, and view spending reports (monthly summary, multi-month trend, and budget status). Business rules include budget-exceeded warnings when creating an expense, blocking category deletion while expenses still reference it, and validation edge cases (future-dated expenses allowed up to 7 days, negative amounts rejected, an amount ceiling, and no duplicate category names per user). Currency conversion is out of scope."

## User Scenarios & Testing *(mandatory)*

Behaviors are stated once and precisely in **Requirements**, **Validation Rules**, and **Edge
Cases**. The stories below give the prioritized user journeys and the signature scenarios that
anchor each story's independent test.

### User Story 1 - Register and authenticate (Priority: P1)

A new person registers with email, password, display name, and default currency, logs in to receive
an authentication token, and can view and update their own profile.

**Why this priority**: Every other story depends on an authenticated, isolated account; it is the
smallest slice that delivers value.

**Independent Test**: Register, log in for a token, fetch the profile, update display name and
currency, and confirm requests without a valid token are rejected.

**Acceptance Scenarios**:

1. **Given** a valid registration, **When** the person registers, **Then** the account is created
   and the password is never returned; **And** registering an email already in use (case-insensitive)
   is rejected with a clear message.
2. **Given** a registered account, **When** they log in with correct credentials, **Then** a token is
   issued; **And** an unknown email or wrong password is rejected with one generic message and no
   token.
3. **Given** an authenticated user, **When** they change their default currency before any expense
   exists, **Then** it is accepted; **And** after an expense exists it is rejected (display name stays
   updatable).
4. **Given** a missing or invalid token, **When** any non-authentication operation is called, **Then**
   it is rejected as unauthorized.

---

### User Story 2 - Track expenses (Priority: P2)

An authenticated user records expenses (amount, category, date, optional description, optional
receipt link) and lists, filters, views, updates, and deletes them. Default categories are available
immediately, so tracking needs no setup.

**Why this priority**: Recording and reviewing expenses is the core value; with P1 it forms a usable
MVP, testable using the system default categories.

**Independent Test**: Create expenses against default categories, list with date/category/amount
filters, fetch/update/delete one, and confirm only the owner's expenses are visible.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they create an expense with a valid amount, an
   accessible category, and a date, **Then** it is stored in the user's default currency and returned.
2. **Given** invalid input, **When** they create an expense with a zero/negative/over-maximum amount,
   an amount with more than two decimals, a date more than 7 days ahead, or another user's category,
   **Then** the request is rejected with a clear validation message.
3. **Given** stored expenses, **When** they list with date/category/amount filters, **Then** only
   matching expenses are returned; **And** updating an expense re-applies all creation validations.
4. **Given** two users, **When** one lists or fetches expenses, **Then** they never see the other's.

---

### User Story 3 - Organize with categories (Priority: P3)

The system provides defaults (Food, Transport, Entertainment, Shopping, Bills, Health, Other); users
create, update, and delete their own custom categories. A custom category cannot be deleted while
expenses reference it.

**Why this priority**: Custom categories add organization beyond the always-present defaults, so they
enhance rather than block tracking.

**Independent Test**: List and see the seven defaults; create a custom category; reject a duplicate
name; update it; fail to delete it while it has expenses (with a count); delete it once unused.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they list categories, **Then** the seven defaults plus
   their own custom categories are returned.
2. **Given** a custom category, **When** they create it with a name, icon, and color, **Then** it is
   owned by them; **And** a name duplicating any visible category (case-insensitive, including
   defaults) is rejected.
3. **Given** a custom category, **When** they delete it while expenses reference it, **Then** it is
   rejected with the associated-expense count; **And** once unused it is deleted along with any
   budgets that referenced it.
4. **Given** a system default or another user's category, **When** they try to modify or delete it,
   **Then** it is rejected.

---

### User Story 4 - Set budgets and get overspend warnings (Priority: P4)

A user sets a monthly per-category spending limit, lists and deletes budgets, and receives a warning
when creating or updating an expense pushes that category's month over its budget.

**Why this priority**: Budgets and warnings turn passive tracking into active control, building on
existing expenses and categories.

**Independent Test**: Set a budget; create expenses within and then over it; confirm the warning
appears only when exceeded with correct figures; confirm a zero budget and a past-month budget are
allowed.

**Acceptance Scenarios**:

1. **Given** an accessible category, **When** they set a monthly budget (month/year), **Then** it is
   stored, listable, and deletable; **And** zero is allowed, a negative budget rejected, and past,
   present, and future months allowed.
2. **Given** a budget for a category and month, **When** creating or updating an expense makes that
   month's category total strictly exceed the budget, **Then** the response includes a warning with
   the category, budget, spent, and exceeded-by amounts; otherwise no warning is included.

---

### User Story 5 - View spending reports (Priority: P5)

A user views a monthly summary (total and per-category breakdown), a multi-month trend, and a
budget-status report (spent vs budget per category), all in their default currency.

**Why this priority**: Reports are the insight layer over recorded data and depend on expenses and
budgets already being present.

**Independent Test**: With a known dataset, verify the monthly summary total and breakdown, the
per-month trend figures, and the per-category budget status.

**Acceptance Scenarios**:

1. **Given** expenses in a month, **When** they request the monthly summary, **Then** the total
   equals the sum of that month's expenses with a correct per-category breakdown.
2. **Given** expenses across months, **When** they request the trend over the last N months (default
   6, including the end month), **Then** each month has a total, zero-filled when empty.
3. **Given** budgets and expenses for a month, **When** they request budget status, **Then** each
   budgeted category shows spent vs budget; **And** all report amounts use the user's single default
   currency (never mixed).

---

### Edge Cases

- **Delete a category with expenses** → rejected with the associated-expense count and an advisory to
  reassign first (advisory text only; no bulk-reassignment capability is in scope).
- **Delete a custom category with budgets but no expenses** → allowed; its budgets are removed with it.
- **Budget for a past / present / future month** → allowed.
- **Expense date** → up to 7 days in the future (UTC) allowed, beyond rejected; no lower bound;
  counted in the report month of its date (so a future-dated expense can land in a future month).
- **Zero/negative amount, amount over 999,999,999.99, or more than two decimals** → rejected.
- **Budget of zero** → allowed; **negative budget** → rejected.
- **Duplicate category name** (case-insensitive, including system defaults) → rejected.
- **Inverted filter range** (date start after end, or amount min above max) → rejected.
- **Budget-exceeded check on back/future-dated expenses** → uses the expense's month, not the current
  calendar month.
- **Change default currency after expenses exist** → rejected (preserves single-currency integrity).
- **Access another user's data** → rejected; users see and modify only their own.
- **Operate on a non-existent expense, category, or budget** → not-found error.
- **Budget for a category the user cannot access** → rejected.
- **Missing or malformed required fields** → validation error identifying the field(s).

## Requirements *(mandatory)*

### Functional Requirements

**Accounts & Authentication**

- **FR-001**: System MUST let a person register an account with a unique email, a password, a display
  name, and a default currency. Registration creates the account but does not issue a token; the user
  obtains one by logging in (FR-004).
- **FR-002**: System MUST treat email as unique case-insensitively and reject registration of an
  email already in use, with a clear message.
- **FR-003**: System MUST never include a password in any response (success or error), and MUST
  persist it only as a salted one-way hash — never plaintext or a reversible encoding — verifiable by
  inspecting the stored value. The hashing algorithm is a planning / Security-gate concern.
- **FR-004**: System MUST let a user log in with email and password and receive a token, and MUST
  reject invalid credentials without issuing a token, using one generic message that does not reveal
  whether the email exists.
- **FR-005**: System MUST require a valid token for every operation except registration and login,
  reject missing, malformed, invalid, or expired tokens as unauthorized, identify the acting user from
  the token, and scope all returned or changed data to that user.
- **FR-006**: System MUST let an authenticated user retrieve their own profile (email, display name,
  default currency).
- **FR-007**: System MUST let an authenticated user update their display name at any time and their
  default currency only while no expenses exist (rejected once expenses exist). The email is
  immutable; password change/reset is out of scope (per requirements §2.1).

**Categories**

- **FR-008**: System MUST provide seven default categories for every user — Food, Transport,
  Entertainment, Shopping, Bills, Health, Other — each with a predefined icon and color (values are a
  planning detail).
- **FR-009**: System MUST let a user list all categories available to them (defaults plus their own
  custom categories).
- **FR-010**: System MUST let a user create a custom category with a name, an icon identifier, and a
  color.
- **FR-011**: System MUST reject creating or renaming a category to a name that duplicates (case-
  insensitively) any category visible to that user, including system defaults.
- **FR-012**: System MUST let a user update the name, icon, and color of their own custom category.
- **FR-013**: System MUST prevent modifying or deleting system default categories.
- **FR-014**: System MUST prevent deleting a custom category that has expenses referencing it; the
  error MUST include the count of associated expenses and advise reassigning them first.
- **FR-015**: System MUST let a user delete their own custom category when no expenses reference it,
  removing any budgets that referenced it.

**Expenses**

- **FR-016**: System MUST let a user create an expense with an amount, a category available to them
  (own custom or a system default), a date, an optional description, and an optional receipt link; an
  inaccessible category MUST be rejected.
- **FR-017**: System MUST store every expense in the owner's default currency; a client-supplied
  currency is ignored.
- **FR-018**: System MUST reject an expense amount that is zero or negative.
- **FR-019**: System MUST reject an expense amount above 999,999,999.99 or with more than two decimal
  places.
- **FR-020**: System MUST accept an expense dated up to 7 days in the future (UTC) and reject one
  dated beyond that; there is no lower bound.
- **FR-021**: System MUST let a user list their expenses with date-range, category, and amount-range
  filters, and MUST reject inverted ranges.
- **FR-022**: System MUST let a user retrieve, update, and delete their own expenses, re-applying all
  creation-time validations on update.
- **FR-023**: System MUST ensure a user can only read, modify, or delete their own expenses,
  categories, and budgets, never another user's.

**Budgets**

- **FR-024**: System MUST let a user set or update a monthly spending limit for a category they can
  access, scoped to a valid month (1–12) and year, for past, present, or future months.
- **FR-025**: System MUST allow a budget of zero, reject a negative budget, and apply the same maximum
  (999,999,999.99) and two-decimal precision as expense amounts.
- **FR-026**: System MUST keep at most one budget per category per month/year; setting one that
  already exists updates it.
- **FR-027**: System MUST let a user list all of their budgets and delete a budget.

**Budget Warnings**

- **FR-028**: System MUST, when an expense is created or updated, evaluate the category's total
  spending for the month of the expense's date against any budget for that category and month.
- **FR-029**: System MUST include a budget warning alongside the saved expense — containing the
  category, the budget, the amount spent (sum of that category's expenses that month), and the
  exceeded-by amount (spent minus budget) — when that total strictly exceeds the budget, and omit it
  when the total is at or below the budget or no budget is set.

**Reports**

- **FR-030**: System MUST provide a monthly spending summary for a specified month giving the total
  and a per-category breakdown.
- **FR-031**: System MUST provide a multi-month trend over the last N months ending at a specified
  month (N caller-provided, default 6, window inclusive of the end month), reporting a total per month
  (zero for months with no expenses).
- **FR-032**: System MUST provide a budget-status report for a specified month showing spent versus
  budget for each category that has a budget that month.
- **FR-033**: System MUST express all report amounts in the user's single default currency so reports
  never mix currencies.

**Cross-cutting**

- **FR-034**: System MUST return a distinct outcome category for each failure class — invalid input,
  unauthenticated, forbidden (cross-user), not found, and conflict (duplicate or in-use) — each with
  its own appropriate status code, and successful requests their own. A validation failure MUST
  identify the offending field and reason. (The category-to-status-code mapping is a planning detail;
  tests assert the category and, for validation failures, the field and reason.)

### Validation Rules

Field constraints — chosen defaults where the requirements were silent, recorded so they are not
guessed during implementation:

- **Email**: a commonly accepted format, ≤ 254 characters, unique case-insensitively (accept/reject
  examples anchored in `plan.md`).
- **Password**: 8–128 characters.
- **Display name**: required, 1–100 characters.
- **Default currency**: a 3-letter ISO 4217 code (e.g., USD, EUR, ILS), normalized to uppercase.
- **Category name**: required, 1–50 characters, unique per user case-insensitively (including
  defaults); trimmed of surrounding whitespace before validation/uniqueness checks.
- **Category icon**: required, a non-empty string identifier (e.g., `"food"`). **Color**: required, a
  hex code (e.g., `#RRGGBB`).
- **Expense / budget amount**: at most two decimals, ≤ 999,999,999.99; expense amount > 0, budget
  amount ≥ 0.
- **Expense date**: a calendar date; ≤ 7 days in the future (UTC); no lower bound.
- **Expense description**: optional, ≤ 500 characters. **Receipt link**: optional, a commonly accepted
  URL format, ≤ 2048 characters (examples anchored in `plan.md`).
- **Budget month/year**: month 1–12 and a valid year. **Report period**: a target month (1–12) and
  year; trend N is a positive integer with a reasonable maximum (cap is a planning detail).
- **Filter values**: date-range and amount-range bounds must be well-formed (valid dates; amounts
  within expense-amount bounds).

### Response Content

The information each successful response conveys (wire format, field names, and status codes are
planning details):

- **Registration**: the created user's public profile — identifier, email, display name, default
  currency, created timestamp; never the password.
- **Login**: the authentication token (token type/expiry are planning details).
- **Profile**: identifier, email, display name, default currency, timestamps.
- **Category** (and each list entry): identifier, name, icon, color, whether it is a system default,
  owner indicator.
- **Expense** (and each list entry): identifier, amount, currency, referenced category, date,
  description, receipt link, timestamps; a create/update response also includes the budget warning
  when the budget is strictly exceeded (FR-029).
- **Budget** (and each list entry): identifier, referenced category, amount, month, year.
- **List responses**: the matching items plus pagination metadata (at least total count and the
  caller's position) when the listing is paginated.
- **Monthly summary**: target month/year, overall total, per-category breakdown (category + its
  total).
- **Spending trend**: an ordered series, each entry the month/year and that month's total.
- **Budget status**: target month/year and, per budgeted category, the category, budget, spent, and
  remaining (negative when exceeded).
- **Category-deletion blocked**: the associated-expense count and reassignment advisory (FR-014).
- **Error**: a human-readable message, the error category (FR-034), and — for validation failures —
  the offending field(s) and reason(s).

### Key Entities

Field-level attributes are defined in **Validation Rules** and **Response Content**; this lists
identity, relationships, and the constraints unique to each entity.

- **User**: owns categories, expenses, and budgets; identified by a case-insensitively unique email;
  password persisted only as a hash.
- **Category**: either belongs to one user (custom) or is a shared system default (no owner); name
  unique per user case-insensitively, including defaults.
- **Expense**: belongs to one user, references one category, denominated in the owner's default
  currency.
- **Budget**: belongs to one user, references one category, scoped to a month/year; at most one per
  category per month.
- **Authentication Token**: issued at login; identifies and authorizes the user on later requests.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user can go from no account to recording a first expense (register → log in →
  create expense against a default category) with no manual category setup.
- **SC-002**: 100% of stored expenses and report amounts are in the owner's single default currency;
  no report mixes currencies.
- **SC-003**: 100% of invalid expense submissions (zero/negative, over maximum, more than two
  decimals, or more than 7 days ahead) are rejected with a clear message; valid boundary cases (e.g.,
  exactly 7 days ahead) are accepted.
- **SC-004**: 100% of attempts to delete an in-use category are blocked, stating how many expenses
  block it.
- **SC-005**: A budget warning is returned exactly when creating or updating an expense pushes its
  category's month over the budget, with budget, spent, and exceeded-by matching the data.
- **SC-006**: For any dataset, the monthly summary total equals the sum of that month's expenses, the
  breakdown sums to that total, and budget-status spent values match the underlying expenses.
- **SC-007**: A user can never read or modify another user's data (0 cross-user access).
- **SC-008**: At least 8 automated tests, with each of the four areas — authentication, expense CRUD,
  budget-checking logic, and report calculations — covered by at least one behavior-level test (test
  quality is enforced by the Testing gate, not the count alone).

## Assumptions

Decisions made where `docs/requirements.md` was silent, recorded so an implementer need not guess and
each is explainable at interview:

- **Single currency**: expenses, budgets, and reports all use the owner's default currency; no
  per-expense currency, no conversion; currency is changeable only before expenses exist (FR-007).
- **Monetary precision**: two decimal places, maximum 999,999,999.99.
- **Month & time basis**: the budget-exceeded check and report grouping use the month of the expense's
  date, evaluated in UTC; expense dates are calendar dates (no time-of-day).
- **One budget per category per month**: setting an existing one updates it (FR-026).
- **System defaults**: shared and read-only — not owned by any user, not editable or deletable.
- **Report scoping**: summary and budget status take a month/year; trend takes an end month and N
  (default 6). Pagination page size and default list ordering are planning details.
- **Chosen defaults & platform**: the Validation Rules limits are reasonable defaults, tunable in
  planning; platform/delivery constraints (runtime version, relational DB, containers, structured
  logging, env-based secrets — requirements §6) are addressed in `plan.md`.
- **Auth lifecycle**: tokens are issued at login and simply expire (no logout/revocation endpoint;
  lifetime is a planning detail).
- **Account lifecycle**: account deletion and password change/reset are out of scope; only display
  name and (pre-expense) default currency are mutable.
- **Single-user concurrency**: budget and uniqueness checks are evaluated per request without special
  protection against simultaneous conflicting requests.
