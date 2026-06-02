# Expense Tracker CLI

A thin first-party command-line client for the Expense Tracker API. It only makes HTTP calls to a
**running API** and shapes the results for the terminal — all business rules live in the service.

Run everything **from the repository root**, in two terminals: one for the API, one for the CLI.

## Recommended: the Swagger UI

The fastest way to explore the API is the built-in **Swagger UI** — an interactive console for
every endpoint, including the few options the CLI doesn't expose (receipt URLs, the amount/category
filters on expense listing). **Prefer it** for one-off calls and exploration; the CLI is best for
scripting the common flows.

1. **Open it.** With the API running (see Setup below), go to `http://localhost:8000/docs`.
2. **Authorize once.** Most endpoints need a bearer token, or they return `401`. To get one:
   expand `POST /auth/register` → **Try it out** → fill the body → **Execute** (skip if you
   already have an account), then do the same for `POST /auth/login` and copy the `access_token`
   from the response. Click the **Authorize** button (top-right), paste the token, and confirm.
   Every "Try it out" call now sends your token automatically.
3. **Use any endpoint.** Expand it, click **Try it out**, fill in the fields, and **Execute**.
   The response body, status code, and the exact `curl` are shown below the button.

The token expires after the configured TTL (default 60 min); when calls start returning `401`,
log in again and re-**Authorize**.

## 1. Setup

**Configure secrets** (once). The API reads `SECRET_KEY` and `DATABASE_URL` from a `.env` file at
the repo root. Create it from the template and set a signing key:

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # paste the output as SECRET_KEY in .env
```

> `.env` holds secrets and is gitignored — never commit it. Only `.env.example` is tracked.

**Start the API** (terminal 1). Needs a running PostgreSQL; the bundled one starts with
`docker compose up -d db`.

```bash
python -m uvicorn app.main:app --port 8000
```

Wait for `Application startup complete`. First start creates the tables and seeds seven default
categories (Food, Transport, Entertainment, Shopping, Bills, Health, Other). Interactive docs:
`http://localhost:8000/docs`.

*Alternative:* `docker compose up --build` runs PostgreSQL **and** the API together.

**Point the CLI at the API** (terminal 2). Only needed if the API isn't on the default URL:

```bash
export API_BASE_URL=http://localhost:8000   # default; set only if the API runs elsewhere
```

## 2. Commands

Run any command with `--help` for its full options. On failure, every command prints the API's
error message and exits non-zero (not logged in, unknown category, validation error, unreachable
API). Dates are `YYYY-MM-DD`; amounts and reports use your account's default currency.

### Account

```bash
# Create an account — password is prompted (hidden), never echoed
python -m cli register --email you@example.com --display-name "You" --currency USD

# Log in — prompts for the password, saves the bearer token to ~/.expense_tracker_token (0600)
python -m cli login --email you@example.com

# Show your profile: id, email, display name, default currency, timestamps
python -m cli profile show

# Update your profile — both flags optional; email is immutable
python -m cli profile update --display-name "New Name" --currency EUR
```

`login` saves a token that authorizes every other command. It expires after the configured TTL
(default 60 min); when commands start failing with "not authenticated", run `login` again. Override
the token path with `EXPENSE_TRACKER_TOKEN_FILE`. `profile update` ignores any attempt to change
the email, and the API rejects a currency change once you have expenses (`409`).

### Categories

```bash
# List every category visible to you — id, name, icon, color, system|custom
python -m cli category list

# Create a custom category — name unique among your visible categories, color is #RRGGBB
python -m cli category add --name Coffee --icon cup --color "#6F4E37"

# Update one of your custom categories — pass only the fields you want to change (id from `list`)
python -m cli category update --id 8 --name Espresso --color "#3B2F2F"

# Delete one of your unused custom categories
python -m cli category delete --id 8
```

A name must be unique (case-insensitive) among the defaults plus your own — a duplicate returns
`409`, a bad color `422`. You can only edit or delete your **own** custom categories (the seven
defaults are read-only), and a delete is blocked with `409` while any expense still references it.

### Expenses

```bash
# Add an expense — --category takes the category *name* (resolved to its id for you)
python -m cli expense add --amount 12.50 --category Food --date 2026-06-01 --description "Lunch"

# List expenses, newest first, optionally within a date range
python -m cli expense list --date-from 2026-06-01 --date-to 2026-06-30

# Show a single expense by id (ids come from `expense list`)
python -m cli expense get --id 42

# Update an expense — pass only the fields you want to change; all add-time rules still apply
python -m cli expense update --id 42 --amount 13.00 --description "Lunch (corrected)"

# Delete an expense
python -m cli expense delete --id 42
```

If an expense pushes that month's category spend over a set budget, `expense add` also prints a
red budget-exceeded line (the warning comes from the API). In `expense list`, each category name is
tinted in its own color on a real terminal.

### Budgets

```bash
# Set or update a category's monthly limit — re-running for the same month replaces it
python -m cli budget set --category Food --amount 300.00 --month 6 --year 2026

# List your budgets, newest period first — id, period, category, amount
python -m cli budget list

# Delete a budget (id from `budget list`)
python -m cli budget delete --id 5
```

### Reports

```bash
# Monthly summary: the month's total and per-category breakdown
python -m cli report monthly --month 6 --year 2026

# Spending trend: one total per month over a window ending at the given month (oldest first)
python -m cli report trend --end-month 6 --end-year 2026 --months 6

# Budget status: spent vs budget per budgeted category (remaining goes negative when over)
python -m cli report budget-status --month 6 --year 2026
```

## Notes

- **Receipt URLs** on an expense and the `category_id`/amount filters on `expense list` are not
  exposed as CLI flags — use the [Swagger UI](#recommended-the-swagger-ui) at `/docs` for those.
- **Environment variables:** `API_BASE_URL` (default `http://localhost:8000`) and
  `EXPENSE_TRACKER_TOKEN_FILE` (default `~/.expense_tracker_token`).
