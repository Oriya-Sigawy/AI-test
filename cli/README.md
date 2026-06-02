# Expense Tracker CLI

A thin first-party command-line client for the Expense Tracker API. It only makes HTTP calls to
a **running API** and shapes the results for the terminal — all business rules live in the
service. Run it as a module from the repository root:

```bash
python -m cli --help
```

## Configuration

Both are read from the environment on every invocation:

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_BASE_URL` | `http://localhost:8000` | Base URL of the running API. |
| `EXPENSE_TRACKER_TOKEN_FILE` | `~/.expense_tracker_token` | Where `login` stores the bearer token (written `0600`). |

Start the API first (see the project root README / `docker compose up`), then point the CLI at it
if it isn't on the default URL:

```bash
export API_BASE_URL=http://localhost:8000
```

## Commands

Authenticate once, then the token file carries your session for the other commands.

```bash
# Create an account — prompts for the password (hidden), never echoed
python -m cli register --email you@example.com --display-name "You" --currency USD

# Log in — prompts for the password, saves the token locally
python -m cli login --email you@example.com

# Add an expense; --category takes the category *name* (resolved to its id for you),
# the amount is recorded in your account's default currency
python -m cli expense add --amount 12.50 --category Food --date 2026-06-01 --description "Lunch"

# List your expenses, newest first, optionally within a date range
python -m cli expense list --date-from 2026-06-01 --date-to 2026-06-30

# Monthly summary: the month's total and per-category breakdown
python -m cli report monthly --month 6 --year 2026
```

If an expense pushes that month's category spend over a set budget, `expense add` prints a
budget-exceeded line in addition to the confirmation (the warning comes from the API).

Every command exits non-zero and prints the API's error message on failure (e.g. not logged in,
unknown category name, validation error, or an unreachable API). Run any command with `--help`
for its full options.
