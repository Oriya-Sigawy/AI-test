# Phase 1 — API Contract

The HTTP surface the service exposes. Wire field names are the canonical contract; the runtime
also publishes an OpenAPI document and Swagger UI at `/docs`. All endpoints except register and
login require `Authorization: Bearer <token>`. Error categories and their status codes follow the
plan's Error model (validation 422 · unauthenticated 401 · forbidden 403 · not found 404 ·
conflict 409). Every error body carries `{ message, category }`, plus `field` + `reason` for
validation failures.

Conventions (decided with the developer):
- JSON bodies; field names **snake_case**; resource ids are **integers**.
- **Amounts are JSON strings** with exactly two decimals (e.g. `"42.50"`) to preserve precision.
- An **expense embeds its category** as a nested object (`{ id, name, icon, color, is_system }`);
  single resources are returned **bare**, only **lists** use the envelope.
- List endpoints accept `limit` (default 50, max 100) and `offset` (default 0) and return
  `{ items: [...], total, limit, offset }` (FR-035). Malformed pagination → 422.
- `date` fields are `YYYY-MM-DD`; timestamps are ISO-8601 UTC.

## Auth & Users

| Method | Path | Auth | Purpose | Success |
|---|---|---|---|---|
| POST | `/auth/register` | no | Create account (email, password, display_name, default_currency). Never echoes password. Duplicate email → 409. | 201 |
| POST | `/auth/login` | no | Exchange email+password for a token. Bad creds → 401 (generic). | 200 `{ access_token, token_type }` |
| GET | `/users/me` | yes | Current user's profile. | 200 |
| PATCH | `/users/me` | yes | Update `display_name` (any time) and/or `default_currency` (only if no expenses exist; else 409). Email immutable. | 200 |

## Categories

| Method | Path | Auth | Purpose | Success |
|---|---|---|---|---|
| GET | `/categories` | yes | List the 7 defaults + the user's custom categories (paginated; `is_system DESC, name ASC`). | 200 |
| POST | `/categories` | yes | Create custom category (name, icon, color). Duplicate visible name (CI) → 409. | 201 |
| PATCH | `/categories/{id}` | yes | Update own custom category's name/icon/color. System default → 403; other user's → 404; duplicate name → 409. | 200 |
| DELETE | `/categories/{id}` | yes | Delete own unused custom category (also removes its budgets). In use → 409 with expense **count**. System default → 403. | 204 |

## Expenses

| Method | Path | Auth | Purpose | Success |
|---|---|---|---|---|
| POST | `/expenses` | yes | Create expense (amount, category_id, date, optional description, optional receipt_url). Currency forced to owner default. May include `budget_warning`. Invalid amount/date/category → 422 (or 404 for inaccessible category). | 201 |
| GET | `/expenses` | yes | List own expenses with filters `date_from`, `date_to`, `category_id`, `amount_min`, `amount_max` (paginated; `date DESC, id DESC`). Inverted range → 422. | 200 |
| GET | `/expenses/{id}` | yes | Fetch own expense. Other user's / missing → 404. | 200 |
| PATCH | `/expenses/{id}` | yes | Update own expense; re-applies all creation validations; may include `budget_warning`. | 200 |
| DELETE | `/expenses/{id}` | yes | Delete own expense. | 204 |

**Expense response** includes: `id, amount, currency, category, date, description, receipt_url,
created_at, updated_at`. Create/update responses additionally include `budget_warning` **only
when** that month's category total strictly exceeds the budget:
`{ category_name, budget, spent, exceeded_by }` (FR-029). The label field is `category_name` (a
string) — deliberately **not** the key `category`, which everywhere else is the nested category
object.

## Budgets

| Method | Path | Auth | Purpose | Success |
|---|---|---|---|---|
| PUT | `/budgets` | yes | Set/update the budget for `(category_id, month, year)` with `amount` (≥0). One per category per month (idempotent upsert; FR-026). Negative → 422; inaccessible category → 404. | 200 |
| GET | `/budgets` | yes | List own budgets (paginated; `year DESC, month DESC, id DESC`). | 200 |
| DELETE | `/budgets/{id}` | yes | Delete own budget. | 204 |

## Reports

| Method | Path | Auth | Purpose | Success |
|---|---|---|---|---|
| GET | `/reports/monthly-summary?month=&year=` | yes | Total + per-category breakdown for the month (only categories with non-zero spend). | 200 |
| GET | `/reports/trend?end_month=&end_year=&months=` | yes | Total per month over the last `months` (default 6, inclusive, capped 36), zero-filled. | 200 |
| GET | `/reports/budget-status?month=&year=` | yes | Per budgeted category: `spent`, `budget`, `remaining` (negative when exceeded). | 200 |

All report amounts are in the user's single default currency (FR-033).

## Error body shape

```json
{ "message": "human-readable", "category": "validation|unauthenticated|forbidden|not_found|conflict",
  "field": "amount", "reason": "must be greater than 0" }
```

`field`/`reason` present only for validation errors; the category-deletion conflict additionally
includes the blocking expense `count`.

## Concrete examples

```jsonc
// POST /auth/register  →  201   (password never echoed)
req:  { "email": "sam@x.com", "password": "correct horse battery staple",
        "display_name": "Sam", "default_currency": "usd" }
resp: { "id": 1, "email": "sam@x.com", "display_name": "Sam",
        "default_currency": "USD", "created_at": "2026-06-01T10:00:00Z" }

// POST /auth/login  →  200
resp: { "access_token": "eyJ...", "token_type": "bearer" }

// POST /expenses   (Authorization: Bearer …)  →  201
req:  { "amount": "42.50", "category_id": 3, "date": "2026-06-01",
        "description": "Groceries", "receipt_url": null }
resp: { "id": 17, "amount": "42.50", "currency": "USD",
        "category": { "id": 3, "name": "Food", "icon": "food", "color": "#FF8800", "is_system": true },
        "date": "2026-06-01", "description": "Groceries", "receipt_url": null,
        "created_at": "2026-06-01T10:05:00Z", "updated_at": "2026-06-01T10:05:00Z",
        "budget_warning": { "category_name": "Food", "budget": "100.00",
                            "spent": "142.50", "exceeded_by": "42.50" } }   // omitted unless exceeded

// GET /expenses?limit=20&offset=0  →  200   (envelope; single resources are bare)
resp: { "items": [ /* expense objects as above */ ], "total": 57, "limit": 20, "offset": 0 }

// GET /users/me  →  200
resp: { "id": 1, "email": "sam@x.com", "display_name": "Sam", "default_currency": "USD",
        "created_at": "2026-06-01T10:00:00Z", "updated_at": "2026-06-01T10:00:00Z" }

// PATCH /users/me  →  200   (display_name any time; default_currency only while no expenses exist)
req:  { "display_name": "Samuel", "default_currency": "EUR" }
resp: { "id": 1, "email": "sam@x.com", "display_name": "Samuel", "default_currency": "EUR",
        "created_at": "2026-06-01T10:00:00Z", "updated_at": "2026-06-01T11:00:00Z" }
//   → 409 { "message": "Cannot change currency after expenses exist", "category": "conflict" }  (if expenses exist)

// POST /categories  →  201    // GET /categories  →  200 envelope of these objects
req:  { "name": "Coffee", "icon": "cup", "color": "#6F4E37" }
resp: { "id": 12, "name": "Coffee", "icon": "cup", "color": "#6F4E37",
        "is_system": false, "owner_id": 1 }

// PUT /budgets  →  200    // GET /budgets  →  200 envelope of these objects
req:  { "category_id": 3, "amount": "100.00", "month": 6, "year": 2026 }
resp: { "id": 5, "category": { "id": 3, "name": "Food", "icon": "food", "color": "#FF8800", "is_system": true },
        "amount": "100.00", "month": 6, "year": 2026 }

// GET /reports/monthly-summary?month=6&year=2026  →  200   (only non-zero categories)
resp: { "month": 6, "year": 2026, "total": "142.50",
        "by_category": [ { "category": { "id": 3, "name": "Food", "icon": "food",
                                          "color": "#FF8800", "is_system": true }, "total": "142.50" } ] }

// GET /reports/trend?end_month=6&end_year=2026&months=6  →  200   (zero-filled, oldest→newest)
resp: { "months": [ { "month": 1, "year": 2026, "total": "0.00" },
                    { "month": 2, "year": 2026, "total": "30.00" },
                    /* … */ { "month": 6, "year": 2026, "total": "142.50" } ] }

// GET /reports/budget-status?month=6&year=2026  →  200   (per budgeted category)
resp: { "month": 6, "year": 2026,
        "categories": [ { "category": { "id": 3, "name": "Food", "icon": "food",
                                        "color": "#FF8800", "is_system": true },
                          "budget": "100.00", "spent": "142.50", "remaining": "-42.50" } ] }

// errors
404: { "message": "Expense not found", "category": "not_found" }
422: { "message": "Validation failed", "category": "validation",
       "field": "amount", "reason": "must be greater than 0" }
409 (duplicate): { "message": "A category named 'Food' already exists", "category": "conflict" }
409 (category in use): { "message": "Category has 4 expenses; reassign them before deleting",
                        "category": "conflict", "count": 4 }
403 (system default):  { "message": "System default categories cannot be modified", "category": "forbidden" }
```
