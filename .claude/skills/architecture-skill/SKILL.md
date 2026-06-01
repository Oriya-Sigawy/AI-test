---
name: "architecture-skill"
description: "Enforce the Architecture gate (constitution Principle IV — simplicity over complexity, maintainability over cleverness). Use after plan.md or tasks.md is produced/updated, and when code is written or changed (Step 5.4 and the whole change at Step 6). Checks plan alignment, separation of concerns, and no needless abstraction. Read-only — surfaces findings, never edits or approves."
argument-hint: "Optional path or scope to focus the review (e.g. a file, module, or task ID)"
compatibility: "Requires spec-kit project structure with .specify/ and the docs/ artifacts to review against"
allowed-tools: ["Read", "Grep", "Glob"]
metadata:
  author: "AI-assignment"
  gate: "Architecture"
user-invocable: true
disable-model-invocation: false
---

## Purpose

Enforce the **Architecture** gate and **Principle IV (Simplicity Over Complexity, Maintainability
Over Cleverness)**: code and artifacts stay **simple, clear, and clean** — aligned with the approved
`plan.md`, concerns separated, no abstraction the requirements don't earn. Run only the mode for the
current phase; each returns **PASS** or **CHANGES NEEDED** plus the finding and fix.

This skill owns **judgment** — is this the simplest design that meets the requirement, is a clever
construct hurting clarity, is a layer pulling its weight. **Mechanical style** (formatting, import
order, line length, unused vars) is the **format+lint hook's** job, not this skill's; where you spot
it, note "run the linter" rather than re-reviewing it by hand.

This gate **surfaces findings; it does not self-approve.** It is advisory — the developer resolves
the findings and gives final acceptance.

## When To Use

| Mode | Fires | Reviews |
| --- | --- | --- |
| 1 | `plan.md` finished/updated (Step 3) | the design: simple, well-separated, not over-engineered |
| 2 | `tasks.md` generated/updated (Step 4) | the breakdown: simple, each task maps to the plan |
| 3 | Code is about to be / has been written (inline per task at Step 5.4, and the whole change at Step 6) | the code's structure and clarity |

## What NOT To Do

- **Do not edit, fix, or write any file.** This skill is read-only; surface the finding and the
  recommended fix — the developer (or the implementation step) applies it.
- **Do not approve or sign off.** Findings are advisory; only the developer accepts.
- **Do not re-review mechanical formatting.** Line length, import order, blank lines, unused imports
  belong to the format+lint hook — flag "run the linter" and move on.
- **Do not invent architecture the requirements don't ask for.** Recommending a new layer, pattern,
  or abstraction "for the future" is itself a Principle IV violation.

## Mode 1 — Plan review (read only)

- [ ] The design is the **simplest** that meets the requirements — no speculative layers, patterns, or
      generality the assignment doesn't call for (YAGNI).
- [ ] **Separation of concerns** is clear: routing / business logic / data access are distinct, and the
      plan says where each responsibility lives.
- [ ] Every component in the plan **traces to a requirement** in `requirements.md` / `spec.md`; nothing
      extra is being built.
- [ ] Dependencies flow one way (no circular or tangled module relationships described).

## Mode 2 — Tasks review (read only)

- [ ] Each task maps to a piece of the plan; no task introduces structure the plan didn't describe.
- [ ] The breakdown is **simple** — tasks are small, single-purpose, and independently meaningful.
- [ ] No task is a catch-all "refactor / clean up architecture later" deferral.

## Mode 3 — Code review

**Structure**

- [ ] Code matches the **approved plan** — same layers, same responsibilities; deviations are justified,
      not accidental.
- [ ] **Separation of concerns** holds: handlers don't embed SQL, business rules aren't scattered in route
      functions, data access is isolated. One module, one reason to change.
- [ ] **No needless abstraction** — no factory/manager/wrapper with a single caller, no premature generality,
      no indirection that adds a hop without adding meaning.

**Clarity**

- [ ] **Simple over clever** — straightforward control flow; no dense one-liners or tricks that need a
      comment to decode. Favor the readable form.
- [ ] **Names say intent** — functions and variables read as what they do; no misleading or cryptic names.
- [ ] **Functions are focused** — reasonable length, one job; deep nesting and long parameter lists are
      refactored, not tolerated.
- [ ] **No dead weight** — no unused code, commented-out blocks, duplicated logic, or copy-paste that
      should be a shared helper.

## Conventions & examples

Prefer the simple, explicit form over the clever one.

```python
# clean — explicit, one job, reads top to bottom
def monthly_total(expenses: list[Expense]) -> Decimal:
    """Return the sum of expense amounts for a month."""
    return sum((e.amount for e in expenses), Decimal("0"))

# over-engineered — a registry + strategy for one caller, no requirement asks for it
class TotalStrategyFactory:        # needless abstraction (Principle IV)
    def get_strategy(self, kind): ...
```

```python
# separation of concerns — the handler delegates; it doesn't embed SQL or rules
@router.post("/expenses")
def create_expense(body: ExpenseIn, user: User = Depends(current_user)):
    """Create an expense for the current user; warn if it breaks the budget."""
    return expense_service.create(user, body)   # logic lives in the service layer

# tangled — routing + raw SQL + business rule all in the handler (flag this)
@router.post("/expenses")
def create_expense(body, conn):
    conn.execute("INSERT INTO expenses ...")     # data access leaked into the route
    if month_total > budget: ...                 # business rule leaked into the route
```

## Output

End every run with:

1. **Verdict:** `PASS` or `CHANGES NEEDED`.
2. **Findings** (one per issue): severity (`high` / `medium` / `low`), `file:line` (or doc section /
   task id), which concern (**plan alignment**, **separation**, **needless abstraction**, **clarity**),
   the problem in one line, and the recommended fix.
3. If `PASS`, state what was checked so the developer can confirm the scope.

Order findings by severity (high → low). No findings → `PASS`.

---

**Note:** the format+lint hook (`ruff`/`black`) handles mechanical style on every edit; this skill owns
the **judgment** — whether the design is simple, the concerns are separated, and an abstraction earns its
place. They are complementary: the hook keeps the surface clean, the skill keeps the structure sound.
