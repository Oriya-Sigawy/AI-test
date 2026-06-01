# Feature Specification: Personal Expense Tracker API

**Feature Branch**: `001-expense-tracker-api`

**Created**: 2026-06-01

**Status**: Draft

**Input**: User description: "Build a REST API for a personal expense tracking application. Users register and log in with token-based auth and hashed passwords, then track expenses, organize them into categories (system defaults plus custom categories), set monthly per-category budgets, and view spending reports (monthly summary, multi-month trend, and budget status). Business rules include budget-exceeded warnings when creating an expense, blocking category deletion while expenses still reference it, and validation edge cases (future-dated expenses allowed up to 7 days, negative amounts rejected, an amount ceiling, and no duplicate category names per user). Currency conversion is out of scope."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Register and authenticate (Priority: P1)

A new person creates an account with their email, a password, a display name, and a default
currency, then logs in to receive an authentication token they use for every subsequent action.
They can view and update their own profile.

**Why this priority**: Nothing else in the system is usable without an authenticated, isolated
account. This is the foundation that every other story depends on, and it is the smallest slice
that delivers real value (a secured personal account).

**Independent Test**: Register a new account, log in to obtain a token, fetch the profile with
that token, update the display name and default currency, and confirm requests without a valid
token are rejected.

**Acceptance Scenarios**:

1. **Given** no account exists for an email, **When** the person registers with that email, a
   password, a display name, and a default currency, **Then** the account is created and the
   password is never stored or returned in readable form.
2. **Given** an account already exists for an email, **When** someone registers again with that
   same email, **Then** the request is rejected with a clear "email already in use" message.
3. **Given** a registered account, **When** the person logs in with correct credentials, **Then**
   they receive an authentication token.
4. **Given** a registered account, **When** the person logs in with an incorrect password, **Then**
   the request is rejected and no token is issued.
5. **Given** a valid token, **When** the person requests their profile, **Then** their email,
   display name, and default currency are returned.
6. **Given** a valid token, **When** the person updates their display name and default currency,
   **Then** the changes are saved and reflected on the next profile read.
7. **Given** a missing or invalid token, **When** any non-authentication endpoint is called,
   **Then** the request is rejected as unauthorized.

---

### User Story 2 - Track expenses (Priority: P2)

An authenticated user records expenses (amount, category, date, optional description, optional
receipt link), then lists, filters, views, updates, and deletes them. Default categories are
available immediately, so a user can begin tracking without any setup.

**Why this priority**: Recording and reviewing expenses is the core value of the product. Combined
with P1 it forms a usable MVP. It is independently testable using the system default categories.

**Independent Test**: As an authenticated user, create several expenses against default categories,
list them with date/category/amount filters, fetch one, update it, delete it, and confirm only the
owner's expenses are visible.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they create an expense with a valid amount, an existing
   category, and a date, **Then** the expense is stored in the user's default currency and returned.
2. **Given** an expense amount that is negative, **When** the user tries to create it, **Then** the
   request is rejected with a clear validation message.
3. **Given** an expense amount above the maximum allowed value, **When** the user tries to create it,
   **Then** the request is rejected with a clear validation message.
4. **Given** an expense date more than 7 days in the future, **When** the user tries to create it,
   **Then** the request is rejected; **And** a date up to 7 days in the future is accepted.
5. **Given** several stored expenses, **When** the user lists with a date range, a category, and/or
   an amount range filter, **Then** only matching expenses are returned.
6. **Given** a stored expense, **When** the user updates or deletes it, **Then** the change is
   persisted and reflected on the next read.
7. **Given** two different users with their own expenses, **When** one user lists or fetches
   expenses, **Then** they never see the other user's expenses.

---

### User Story 3 - Organize with categories (Priority: P3)

A user works with categories: the system provides defaults (Food, Transport, Entertainment,
Shopping, Bills, Health, Other), and the user can create, update, and delete their own custom
categories. A custom category cannot be deleted while expenses still reference it.

**Why this priority**: Categories add organization value beyond the defaults. Because defaults are
always present, custom-category management is an enhancement rather than a blocker for tracking.

**Independent Test**: List categories and confirm the seven defaults appear; create a custom
category; reject a duplicate name for the same user; update the custom category; attempt to delete
a custom category that has expenses and confirm it is blocked with a count; delete an unused custom
category successfully.

**Acceptance Scenarios**:

1. **Given** any authenticated user, **When** they list categories, **Then** the seven system
   default categories plus their own custom categories are returned.
2. **Given** an authenticated user, **When** they create a custom category with a name, icon, and
   color, **Then** it is created and owned by them.
3. **Given** a user already has a category with a given name, **When** they create another category
   with the same name, **Then** the request is rejected as a duplicate.
4. **Given** a custom category with no expenses, **When** the user deletes it, **Then** it is removed.
5. **Given** a custom category that has expenses referencing it, **When** the user tries to delete
   it, **Then** the request is rejected with an error that includes the count of associated expenses
   and suggests moving those expenses to another category first.
6. **Given** a system default category, **When** a user tries to modify or delete it, **Then** the
   request is rejected.

---

### User Story 4 - Set budgets and get overspend warnings (Priority: P4)

A user sets a monthly spending limit per category for a given month/year, lists and deletes budgets,
and — when creating an expense that pushes that category's spending for the expense's month over its
budget — receives a budget-exceeded warning alongside the created expense.

**Why this priority**: Budgets and warnings turn passive tracking into active control, but they
build on expenses and categories already existing.

**Independent Test**: Set a budget for a category and month; create expenses that stay within and
then exceed the budget; confirm the warning appears only when exceeded and reports the correct
category, budget, spent, and exceeded-by amounts; set a zero budget and a past-month budget and
confirm both are allowed.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they set a monthly budget for a category, **Then** it
   is stored for that month/year and can be listed and deleted.
2. **Given** a budget for a category in a month, **When** the user creates an expense whose date is
   in that month and whose addition makes the category's total for that month exceed the budget,
   **Then** the response includes a budget warning containing the category, the budget, the amount
   spent (sum of that category's expenses in that month), and the exceeded-by amount.
3. **Given** a budget for a category in a month, **When** the user creates an expense that does not
   exceed the budget, **Then** no budget warning is included.
4. **Given** a budget of zero, **When** the user sets it, **Then** it is allowed (tracking without
   a spending allowance).
5. **Given** a month already in the past, **When** the user sets a budget for it, **Then** it is
   allowed (retroactive tracking).

---

### User Story 5 - View spending reports (Priority: P5)

A user views reports computed from their expenses: a monthly summary (total and per-category
breakdown), a multi-month trend, and a budget-status report (spent versus budget per category). All
amounts are in the user's default currency.

**Why this priority**: Reports are the insight layer on top of the recorded data; they depend on
expenses and budgets already being present.

**Independent Test**: With a known set of expenses and budgets, request the monthly summary and
confirm the total equals the sum of that month's expenses and per-category figures are correct;
request a multi-month trend and confirm each month's figure; request budget status and confirm
spent-versus-budget per category.

**Acceptance Scenarios**:

1. **Given** expenses in a month, **When** the user requests the monthly summary, **Then** the
   reported total equals the sum of that month's expenses and a correct per-category breakdown is
   returned.
2. **Given** expenses across several months, **When** the user requests a multi-month trend for the
   last N months, **Then** each month's total is reported for comparison.
3. **Given** budgets and expenses for a month, **When** the user requests budget status, **Then**
   each category shows the amount spent against its budget.
4. **Given** any report, **When** it is returned, **Then** all amounts are expressed in the user's
   single default currency (reports never mix currencies).

---

### Edge Cases

- **Deleting a category that has expenses** → rejected with an error that includes the count of
  associated expenses and suggests reassigning them first.
- **Budget for a past month** → allowed (retroactive tracking).
- **Expense dated in the future** → allowed up to 7 days ahead; rejected beyond 7 days.
- **Negative expense amount** → rejected.
- **Budget of zero** → allowed (track without limiting).
- **Duplicate category name for the same user** → rejected.
- **Very large expense amount** → rejected above a fixed maximum (999,999,999.99).
- **Budget-exceeded check on back-dated or future-dated expenses** → evaluated against the month of
  the expense's date, not the current calendar month.
- **Accessing another user's data** → rejected; users see and modify only their own data.

## Requirements *(mandatory)*

### Functional Requirements

**Accounts & Authentication**

- **FR-001**: System MUST let a person register an account with a unique email, a password, a
  display name, and a default currency.
- **FR-002**: System MUST reject registration when the email is already in use, with a clear message.
- **FR-003**: System MUST store passwords only in a securely hashed form and MUST never return or
  expose passwords in readable form.
- **FR-004**: System MUST let a registered user log in with valid credentials and receive an
  authentication token, and MUST reject login with invalid credentials without issuing a token.
- **FR-005**: System MUST require a valid authentication token for every non-authentication
  endpoint and MUST reject missing or invalid tokens as unauthorized.
- **FR-006**: System MUST let an authenticated user retrieve their own profile (email, display
  name, default currency).
- **FR-007**: System MUST let an authenticated user update their own profile display name and
  default currency.

**Categories**

- **FR-008**: System MUST provide seven default categories available to every user: Food,
  Transport, Entertainment, Shopping, Bills, Health, Other.
- **FR-009**: System MUST let a user list all categories available to them (system defaults plus
  their own custom categories).
- **FR-010**: System MUST let a user create a custom category with a name, an icon identifier, and
  a color.
- **FR-011**: System MUST reject creating a category whose name duplicates another of that same
  user's categories.
- **FR-012**: System MUST let a user update their own custom category.
- **FR-013**: System MUST prevent modifying or deleting system default categories.
- **FR-014**: System MUST prevent deleting a custom category that has expenses referencing it, and
  the error MUST include the count of associated expenses and suggest moving them to another
  category first.
- **FR-015**: System MUST let a user delete their own custom category when no expenses reference it.

**Expenses**

- **FR-016**: System MUST let a user create an expense with an amount, an existing category, a date,
  an optional description, and an optional receipt link.
- **FR-017**: System MUST store every expense in the owner's default currency and MUST NOT accept a
  per-expense currency from the client.
- **FR-018**: System MUST reject expenses with a negative amount.
- **FR-019**: System MUST reject expenses with an amount above the fixed maximum of 999,999,999.99.
- **FR-020**: System MUST accept an expense dated up to 7 days in the future and MUST reject an
  expense dated more than 7 days in the future.
- **FR-021**: System MUST let a user list their expenses with filters for date range, category, and
  amount range.
- **FR-022**: System MUST let a user retrieve, update, and delete a specific one of their own
  expenses.
- **FR-023**: System MUST ensure users can only read or modify their own expenses (and never
  another user's).

**Budgets**

- **FR-024**: System MUST let a user set or update a monthly spending limit for a category, scoped
  to a month and year.
- **FR-025**: System MUST allow a budget amount of zero.
- **FR-026**: System MUST allow setting a budget for a month in the past.
- **FR-027**: System MUST let a user list all of their budgets and delete a budget.

**Budget Warnings**

- **FR-028**: System MUST, when an expense is created, evaluate the category's total spending for
  the month of the expense's date against any budget set for that category and month.
- **FR-029**: System MUST, when that month's category total exceeds the budget, include a budget
  warning alongside the created expense containing the category, the budget, the amount spent (the
  sum of that category's expenses in that month), and the exceeded-by amount; and MUST omit the
  warning when the budget is not exceeded.

**Reports**

- **FR-030**: System MUST provide a monthly spending summary giving the month's total and a
  per-category breakdown.
- **FR-031**: System MUST provide a multi-month spending trend comparing totals across the last N
  months.
- **FR-032**: System MUST provide a budget-status report showing spent versus budget per category.
- **FR-033**: System MUST express all report amounts in the user's single default currency so that
  reports never mix currencies.

**Cross-cutting**

- **FR-034**: System MUST validate input and return meaningful error messages and appropriate
  status codes for both successful and failed requests.

### Key Entities *(include if feature involves data)*

- **User**: A person with an account. Key attributes: unique identifier, unique email, securely
  stored password, display name, default currency, created/updated timestamps. Owns categories,
  expenses, and budgets.
- **Category**: A grouping for expenses. Key attributes: unique identifier, name, icon identifier,
  color, whether it is a system default, and owner (none for system defaults, a specific user for
  custom). A category name is unique per user.
- **Expense**: A recorded spend. Key attributes: unique identifier, amount, currency (always the
  owner's default), category reference, date, optional description, optional receipt link, owner
  reference, created/updated timestamps.
- **Budget**: A monthly spending limit. Key attributes: unique identifier, category reference,
  monthly amount limit, the month and year it applies to, owner reference.
- **Authentication Token**: A credential issued at login that identifies and authorizes the user on
  subsequent requests.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user can go from no account to recording their first expense (register → log in
  → create expense against a default category) without any manual setup of categories.
- **SC-002**: 100% of stored expenses and all report amounts are in the owner's single default
  currency; no report ever mixes currencies.
- **SC-003**: 100% of invalid expense submissions — negative amounts, amounts above the maximum, and
  dates more than 7 days in the future — are rejected with a clear, specific message; valid
  boundary cases (e.g., exactly 7 days ahead) are accepted.
- **SC-004**: 100% of attempts to delete an in-use category are blocked and the response states how
  many expenses are blocking the deletion.
- **SC-005**: A budget-exceeded warning is returned exactly when an expense pushes its category's
  total for the expense's month over the budget, and the reported budget, spent, and exceeded-by
  values match the underlying data.
- **SC-006**: For any dataset, the monthly summary total equals the sum of that month's expenses,
  the per-category breakdown sums to that total, and budget-status spent values match the
  underlying expenses (report math is correct).
- **SC-007**: A user can never read or modify another user's accounts, categories, expenses, or
  budgets (0 cross-user data access).
- **SC-008**: The delivered solution includes at least 8 meaningful automated tests spanning the
  authentication flow, expense create/read/update/delete, budget-checking logic, and report
  calculations.

## Assumptions

- **Single currency per user**: An expense's currency always equals the owner's default currency at
  creation time; the API does not accept a per-expense currency, and currency conversion is out of
  scope (per requirements §4.3).
- **Budget month basis**: The budget-exceeded check uses the month of the expense's date (not the
  current calendar month), keeping the check coherent for back-dated and future-dated expenses (per
  requirements §4.1).
- **Trend window (N months)**: The multi-month trend compares a caller-provided number of recent
  months; when unspecified, a reasonable default window is used. The exact default is a planning
  detail.
- **One budget per category per month**: A category has at most one budget for a given month/year;
  setting a budget for an existing category/month updates the existing one.
- **System defaults are read-only and shared**: The seven default categories are not owned by any
  user and cannot be edited or deleted by users.
- **Pagination and ordering of expense listings** are expected for large result sets; specific page
  sizes and default ordering are planning details.
- **Platform and delivery constraints** (language/runtime version, relational database,
  containerized setup, structured logging, secrets via environment) are mandated by requirements §6
  and are addressed in `plan.md`, not in this behavioral specification.
- **Token lifecycle** (issuance at login, expiry/refresh policy) follows standard token-based
  authentication practice; specific lifetimes are a planning detail.
