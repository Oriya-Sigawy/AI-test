---
name: "logging-docs-skill"
description: "Enforce the Logging & Documentation gate. Use after tasks.md is generated (logging/docs captured), when code is written or changed (Step 5.4 and the whole change at Step 6), and when README.md / AI_USAGE.md are produced or reviewed. Covers docstrings, diagnosable non-sensitive logs, and the README/AI_USAGE deliverables. Read-only — surfaces findings, never edits or approves."
argument-hint: "Optional path or scope to focus the review (e.g. a file, module, or task ID)"
compatibility: "Requires spec-kit project structure with .specify/ and the docs/ artifacts to review against"
allowed-tools: ["Read", "Grep", "Glob"]
metadata:
  author: "AI-assignment"
  gate: "Logging"
user-invocable: true
disable-model-invocation: false
---

## Purpose

Enforce the **Logging & Documentation** gate (no separate docs gate). Three things must hold:
**code docs** — every public function carries a short docstring saying what it does, plus a one-line
note for each non-trivial argument; **logging** — logs help diagnose problems, never carry sensitive
data, and stay useful and concise; and the **doc deliverables** — `README.md` and `AI_USAGE.md`
exist and contain their required structure. Run only the mode for the current phase; each returns
**PASS** or **CHANGES NEEDED** plus the specific finding and fix.

This gate **surfaces findings; it does not self-approve.** It is advisory — the developer resolves
the findings and gives final acceptance.

## When To Use

| Mode | Fires | Reviews |
| --- | --- | --- |
| 1 | `tasks.md` generated/updated | logging & docs are captured in the relevant tasks (not a separate afterthought) |
| 2 | Code is about to be / has been written (inline per task at Step 5.4, and the whole change at Step 6) | the docstrings and the log statements in the code |
| 3 | `README.md` / `AI_USAGE.md` produced/updated, and the final documentation-review task | the doc deliverables |

## What NOT To Do

- **Do not edit, fix, or write any file.** This skill is read-only; surface the finding and the
  recommended fix — the developer (or the implementation step) applies it.
- **Do not approve or sign off.** Findings are advisory; only the developer accepts.
- **Do not output any sensitive value** you find in a log (password, token, key, PII). Report its
  location and **redact the value** — never echo it.

## Mode 1 — Tasks review (read only)

- [ ] Tasks that add behavior also call for its **logging** (where it helps diagnosis) and its **docs**.
- [ ] No task defers logging/docs to a vague "polish later" step; they ride with the code they describe.

## Mode 2 — Code review

**Documentation**

- [ ] Every **public function / endpoint handler** has a docstring whose **first line says what it does** (a verb phrase, not how).
- [ ] Each **non-trivial argument** (unit, format, constraint, or non-obvious meaning) gets a one-line note.
- [ ] The docstring is **short** — no restating the signature, no line-by-line narration of the body.
- [ ] Comments explain **why**, not what; no commented-out code or stale comments left behind.

**Logging**

- [ ] **Diagnosable** — errors and key state transitions are logged with enough context (what failed,
      which entity/id), including a **request/correlation id** so one request's logs trace end-to-end.
- [ ] **No sensitive data** — no passwords, tokens, keys, full card/PII, or raw request bodies; identify
      records by id, not by secret.
- [ ] **Right level** — `DEBUG` detail / `INFO` milestones / `WARNING` recoverable operational
      anomalies (e.g. a retried transient failure, a rejected/conflicting operation) / `ERROR` failures;
      no `print()`; not noisy (no per-iteration logs in hot paths). A **budget-exceeded** outcome is
      business-normal — log it at `INFO` and surface it to the user via the `budget_warning` response
      field, **not** as a `WARNING` log.
- [ ] **Concise & consistent** — one event per line, structured (logger + message + fields), same shape
      across the codebase; message is self-contained and readable.

## Mode 3 — Documentation deliverables (read only)

- [ ] `README.md` has **run instructions**, **test instructions**, and **two design decisions with rationale**.
- [ ] `AI_USAGE.md` has all four sections — *Tools I Used / What Helped Most / What I Had to Fix /
      What AI Struggled With* — each with real content, not a placeholder.
- [ ] Both match what was actually built — no stale, missing, or aspirational claims.

## Conventions & examples

**Docstring** — first line = what it does; note only the non-trivial args.

```python
def budget_status(spent: Decimal, limit: Decimal | None) -> str:
    """Return a category's budget state for a month.

    spent: total expenses in the category that month, >= 0.
    limit: the category's monthly budget; None means no budget set.
    """
```

Trivial functions need only the one-liner: `"""Return the user's active categories."""`

**Logging** — structured fields, identify by id, never log secrets.

```python
# good — diagnosable, safe, concise
logger.info("expense created", extra={"user_id": user.id, "expense_id": exp.id, "amount": exp.amount, "budget_warning": True})  # budget-exceeded is business-normal: INFO + a budget_warning response field, never a WARNING log
logger.warning("category delete blocked: in use", extra={"user_id": user.id, "category_id": cat.id, "expense_count": 4})
logger.error("auth failed: token expired", extra={"user_id": user.id})

# bad — leaks secrets / PII, no context, wrong tool
logger.info(f"login {email} password={password} token={jwt}")   # sensitive data
print("something went wrong")                                    # no level, no context
```

## Output

End every run with:

1. **Verdict:** `PASS` or `CHANGES NEEDED`.
2. **Findings** (one per issue): severity (`high` / `medium` / `low`), `file:line` (or task id),
   whether it is a **docs** or **logging** issue, the problem in one line, and the recommended fix.
3. If `PASS`, state what was checked so the developer can confirm the scope.

Order findings by severity (high → low). No findings → `PASS`.

---

**Note:** a formatter/linter hook can flag a missing docstring or a stray `print()` mechanically; this
skill owns the **judgment** — whether the docstring actually explains the function, whether a log line is
diagnosable, and whether anything sensitive is being logged.
