# Welcome

Thank you for participating in our technical assessment process. We're excited to see what you build!

This project is designed to give you a realistic task that reflects the kind of work you'd do on our team. Take your time, write code you're proud of, and most importantly - make sure you understand everything you submit.

---

## About This Assessment

You'll be building a REST API for a personal expense tracking application. Users can track their spending, categorize expenses, set budgets, and view spending summaries.

This isn't a trick test. We want to see how you approach a realistic problem, structure your code, and handle common backend challenges like authentication, data aggregation, and business logic.

---

## Using AI Tools

You are **explicitly permitted and encouraged** to use AI coding assistants during this assessment. This includes ChatGPT, GitHub Copilot, Claude, Cursor, or any other AI tools you prefer.

**Why we allow this:**
- AI tools are part of modern development - we use them too
- We're evaluating your judgment and understanding, not your typing speed
- The best developers know how to leverage AI while catching its mistakes

**What we're actually evaluating:**
- Can you understand and explain the code you submit?
- Do you make sound architectural decisions?
- Can you identify when AI gives you bad advice?
- Is the final product correct, secure, and well-structured?

**Important:** You will be asked to explain your code and decisions in a follow-up technical interview. Make sure you understand every line.

---

## Functional Requirements

### User Management

- Register new account
- Login and receive authentication token
- Get current user profile
- Update user profile (name, default currency)

### Categories

Users can manage expense categories:

- Create a custom category
- List all categories (system defaults + user custom)
- Update a custom category
- Delete a custom category (only if no expenses use it)

System provides default categories: Food, Transport, Entertainment, Shopping, Bills, Health, Other

### Expenses

- Create an expense (amount, category, date, description, optional receipt URL)
- List expenses with filters (date range, category, amount range)
- Get a specific expense
- Update an expense
- Delete an expense

### Budgets

Users can set monthly budgets per category:

- Set/update budget for a category
- List all budgets
- Delete a budget

### Reports

- Get spending summary for a month (total, by category)
- Get spending trend (last N months comparison)
- Get budget status (spent vs budget per category)

---

## Data Model

Design your data model to support:

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
- Icon identifier (string, e.g., "food", "car", "shopping")
- Is system default (boolean)
- Owner (null for system defaults, user ID for custom)
- Color (hex code for UI)

### Expense
- Unique identifier
- Amount (decimal)
- Currency
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
- Month/Year (which month this budget applies to)
- Owner relationship

---

## Business Logic

### Budget Alerts

When creating an expense, check if user exceeds their budget for that category in the current month. Include a warning in the response:

```json
{
  "expense": { ... },
  "budget_warning": {
    "category": "Food",
    "budget": 500.00,
    "spent": 523.50,
    "exceeded_by": 23.50
  }
}
```

### Category Deletion

- Cannot delete a category that has expenses associated with it
- Return an error with count of associated expenses
- Suggest moving expenses to another category first

### Currency Handling

- Store amounts in user's default currency
- For reports, all amounts should be in user's default currency
- Currency conversion is NOT required (out of scope)

---

## Edge Cases to Handle

1. **Deleting category with expenses** → Error with expense count
2. **Setting budget for past month** → Allow it (for retroactive tracking)
3. **Expense with future date** → Allow up to 7 days in future, reject beyond
4. **Negative expense amount** → Reject (use separate income tracking if needed)
5. **Budget of zero** → Allow (user wants to track but not limit)
6. **Duplicate category name for same user** → Reject
7. **Very large amounts** → Set reasonable limit (e.g., 999,999,999.99)

---

## Technical Requirements

### Must Have

- Python 3.11+
- Web framework of your choice
- Relational database
- Token-based authentication
- Secure password hashing
- Input validation with meaningful errors
- Proper HTTP status codes
- Containerized setup (Dockerfile + docker-compose)
- At least 8 meaningful tests covering:
  - Authentication flow
  - Expense CRUD
  - Budget checking logic
  - Report calculations

### Should Have

- Environment variables for secrets
- Structured logging
- Clean code organization
- Pagination for expense listing
- Date range filtering

### Nice to Have

- API documentation
- Soft delete for expenses
- Export expenses to CSV

---

## Submission Requirements

Submit a Git repository containing:

```
your-project/
├── README.md
├── AI_USAGE.md
├── docker-compose.yml
├── Dockerfile
├── (your application code)
└── (your tests)
```

### README.md

Include:
1. How to run the project
2. How to run tests
3. **Two design decisions** you made and why

### AI_USAGE.md

```markdown
# AI Tool Usage

## Tools I Used
[List the AI tools you used]

## What Helped Most
[Describe 1-2 specific cases where AI helped significantly]

## What I Had to Fix
[Describe 1-2 cases where AI gave incorrect or suboptimal code that you corrected]

## What AI Struggled With
[Any parts where AI wasn't helpful]
```

---

## Tips for Success

1. **Start with the data model** - Get your entities and relationships right
2. **Build expenses first** - It's the core feature
3. **Add budget logic second** - Builds on expenses
4. **Reports last** - They're just queries over existing data
5. **Test the math** - Budget calculations are easy to get wrong
6. **Don't over-engineer** - Simple, working code wins

---

We look forward to seeing your solution! Good luck, and have fun with it.

