---
name: "testing-skill"
description: "Enforce TDD and test quality (constitution Principle III). Use at four points: (1) after plan.md is finished or updated, confirm the plan is testable; (2) after tasks.md is generated, confirm every behavioral task has a paired test task ordered before it; (3) before implementing each task, write that task's tests from plan.md and observe them fail before any production code; (4) after all implementation tasks are done, run the full suite and confirm every planned behavior is covered. Invoke whenever a plan is completed, tasks are generated, a task is about to be implemented, or implementation has finished."
argument-hint: "Optional path or scope to focus the review (e.g. a module or task ID)"
compatibility: "Requires spec-kit project structure with .specify/ and a plan.md to derive tests from"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
metadata:
  author: "AI-assignment"
  gate: "Testing"
user-invocable: true
disable-model-invocation: false
---

## Purpose

Enforce the **Testing** gate and **Principle III (NON-NEGOTIABLE)**: tests derive from `plan.md`
and requirements, validate behavior (not implementation), and are seen failing before the code.
Run only the mode for the current phase. Each returns **PASS** / **CHANGES NEEDED** (Mode 4:
**GAPS FOUND**) plus the specific fix.

This gate **surfaces findings; it does not self-approve.** Modes 1, 2, and 4 are advisory reviews —
the developer gives the go-ahead (especially before crossing plan → implementation) and final
acceptance. The skill owns the judgment of *what* the findings are, not the decision to proceed.

## When To Use

| Mode | Fires | Action |
| --- | --- | --- |
| 1 | `plan.md` finished/updated | Review the plan is testable |
| 2 | `tasks.md` generated/updated | Review every task has a test task before it |
| 3 | Before each task | Write that task's tests, observe them fail |
| 4 | All tasks done | Run the full suite, check coverage |

## Mode 1 — Plan testable? (read only)

- [ ] Every behavior, edge case, and failure scenario in `plan.md` is testable.
- [ ] Success criteria are observable (inputs/outputs), not internal state.
- [ ] Where the plan logs, the expected log output (success + failure) is defined well enough to assert.

## Mode 2 — Tasks testable? (read only)

- [ ] Every behavioral task has a paired test task, ordered before its implementation task (TDD).
- [ ] No untestable task; no `plan.md` behavior left without a test task.

## Mode 3 — Write the task's tests (before any code)

Read `plan.md` → write tests → run them, confirm they **fail for the expected reason** (behavior
missing, not an import/typo). Do not implement here — return to the TDD loop.

- [ ] Cover: happy path, edge cases, errors/failures, return values — and log output where the behavior logs.
- [ ] Derived from `plan.md` (survives a refactor); independent; simple and readable (smallest test
      proving the behavior); only what this task needs — no duplicates.

## Mode 4 — Coverage (all tasks done)

- [ ] Suite green; every `plan.md` behavior maps to ≥1 test (happy, edge, error, logging where specified).
- [ ] Tests independent and deterministic; none fragile, dead, or duplicate.

---

**Note:** a PostToolUse hook runs the suite after each edit (execution feedback); this skill owns
the judgment. A red suite is expected during Mode 3 — status, not violation.
