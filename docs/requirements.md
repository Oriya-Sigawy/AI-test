# Requirements — Personal Expense Tracker REST API

Extracted from [`junior-mid-expense-tracker.md`](./junior-mid-expense-tracker.md).
This is the single source of truth for *what must be built*. No implementation details,
no assumptions, no extra features. `spec.md`, `plan.md`, and `tasks.md` derive from this.

> Priority legend: **MUST** = required to pass · **SHOULD** = expected, not strictly required ·
> **NICE** = optional bonus.

---

## 1. Overview

Build a **REST API** for a personal expense tracking application. Users can track
spending, categorize expenses, set budgets, and view spending summaries.

---

## 2. Functional Requirements (MUST)

### 2.1 User Management
- Register a new account.
- Login and receive an authentication token.
- Get the current user's profile.
- Update the user profile (name, default currency).

### 2.2 Categories
- Create a custom category.
- List all categories (system defaults + the user's custom ones).
- Update a custom category.
- Delete a custom category — **only if no expenses use it**.
- System provides default categories: **Food, Transport, Entertainment, Shopping,
  Bills, Health, Other**.

### 2.3 Expenses
- Create an expense (amount, category, date, description, optional receipt URL).
- List expenses with filters (date range, category, amount range).
- Get a specific expense.
- Update an expense.
- Delete an expense.

### 2.4 Budgets
Monthly budgets per category:
- Set / update a budget for a category.
- List all budgets.
- Delete a budget.

### 2.5 Reports
- Spending summary for a month (total, and by category).
- Spending trend (last N months comparison).
- Budget status (spent vs. budget per category).

---

## 3. Data Model (MUST support)

### User
- Unique identifier
- Email (unique)
- Secure password storage
- Display name
- Default currency (USD, EUR, ILS, etc.)
- Timestamps

### Category
- Unique identifier
- Name
- Icon identifier (string, e.g. `"food"`, `"car"`, `"shopping"`)
- Is system default (boolean)
- Owner (null for system defaults, user ID for custom)
- Color (hex code for UI)

### Expense
- Unique identifier
- Amount (decimal)
- Currency (always the owner's default currency — see §4.3; not client-settable per expense)
- Category relationship
- Date of expense
- Description (optional)
- Receipt URL (optional)
- Owner relationship
- Timestamps

### Budget
- Unique identifier
- Category relationship
- Monthly amount limit
- Month/Year the budget applies to
- Owner relationship

---

## 4. Business Logic (MUST)

### 4.1 Budget Alerts
When creating an expense, check whether the user exceeds the budget for that category
in **the month of the expense's date** (not the actual current calendar month — this keeps
the check coherent with back-dated and future-dated expenses, see Edge Cases 2 and 3).
If exceeded, include a `budget_warning` in the response alongside the created expense,
containing: `category`, `budget`, `spent`, `exceeded_by`. "Spent" is the sum of expenses
in that category for that same month.

### 4.2 Category Deletion
- Cannot delete a category that has expenses associated with it.
- Return an error that includes the **count** of associated expenses.
- Suggest moving expenses to another category first.

### 4.3 Currency Handling
- **Single currency per user.** Every expense is stored in the user's default currency.
  The API does **not** accept a per-expense currency on input; an expense's currency always
  equals the owner's default currency at creation time.
- Store amounts in the user's default currency.
- Reports present all amounts in the user's default currency (so reports never mix currencies).
- Currency conversion is **out of scope** (not required).

---

## 5. Edge Cases (MUST handle)

1. **Delete category with expenses** -> error including the expense count.
2. **Budget for a past month** -> allow (retroactive tracking).
3. **Expense with a future date** -> allow up to **7 days** in the future; reject beyond.
4. **Negative expense amount** -> reject.
5. **Budget of zero** -> allow (track without limiting).
6. **Duplicate category name for the same user** -> reject.
7. **Very large amounts** -> enforce a reasonable limit (e.g. `999,999,999.99`).

---

## 6. Technical Requirements

### MUST Have
- Python **3.11+**
- A web framework (developer's choice)
- A relational database
- Token-based authentication
- Secure password hashing
- Input validation with meaningful error messages
- Proper HTTP status codes
- Containerized setup: **Dockerfile + docker-compose**
- **At least 8 meaningful tests** covering:
  - Authentication flow
  - Expense CRUD
  - Budget checking logic
  - Report calculations

### SHOULD Have
- Environment variables for secrets
- Structured logging
- Clean code organization
- Pagination for expense listing
- Date range filtering

### NICE to Have
- API documentation
- Soft delete for expenses
- Export expenses to CSV

---

## 7. Submission / Deliverables (MUST)

Submit a Git repository with this structure:

```
your-project/
├── README.md
├── AI_USAGE.md
├── docker-compose.yml
├── Dockerfile
├── (application code)
└── (tests)
```

**README.md** must include:
1. How to run the project.
2. How to run the tests.
3. **Two design decisions** you made, and why.

**AI_USAGE.md** must include these sections:
- Tools I Used
- What Helped Most (1-2 specific cases)
- What I Had to Fix (1-2 cases where AI was wrong/suboptimal and you corrected it)
- What AI Struggled With

---

## 8. For the Developer to Know After Finishing (MUST)

- There will be a **follow-up technical interview** where you must explain your code
  and decisions.
- You must be able to **understand and explain every line** you submit.
- Be ready to justify your **architectural decisions** and to identify where AI gave
  bad advice.

---

## 9. Context — How the Work Is Evaluated (non-normative)

Not build requirements; recorded only so priorities stay aligned. Assessors evaluate:
understanding and ability to explain the code, sound architectural decisions, catching
bad AI advice, and whether the final product is correct, secure, and well-structured.
The assignment's own guidance: start with the data model, build expenses first, then
budget logic, then reports; test the math; don't over-engineer.

Additionally, this assignment will be examined against the **five review gates** defined
in [`CLAUDE.md`](./CLAUDE.md): **Security**, **Testing**, **Performance**, **Logging**, and
**Architecture**. A change is not considered complete until every applicable gate has been
reviewed and passes.
