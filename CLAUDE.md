# CLAUDE.md

The operating manual for Claude Code on this project: Claude's role, the documents,
and which review gate fires at which workflow phase. The **principles** behind these
rules live in `.specify/memory/constitution.md`.

## The Assignment

Build a **REST API for a personal expense tracking application** in **Python 3.11+**.
Users register and log in (token-based auth, hashed passwords), then track expenses,
organize them into categories (system defaults + custom), set monthly per-category
budgets, and view spending reports (monthly summary, multi-month trend, budget status).
Notable business rules: budget-exceeded warnings on expense creation, category deletion
blocked while expenses reference it, and a set of validation edge cases (future-dated
expenses allowed up to 7 days, negative amounts rejected, amount ceiling, no duplicate
category names per user). Currency conversion is **out of scope**.

The full, authoritative requirements are in [`docs/requirements.md`](docs/requirements.md);
read it before doing any work. Key things to keep in mind:

- **Deliverables** (a Git repo): `README.md`, `AI_USAGE.md`, `docker-compose.yml`,
  `Dockerfile`, application code, and tests. A relational DB and containerized setup are
  required, plus **at least 8 meaningful tests** (auth, expense CRUD, budget logic, reports).
- **`README.md`** must cover how to run the project, how to run the tests, and **two design
  decisions** with rationale. **`AI_USAGE.md`** has four required sections (Tools I Used,
  What Helped Most, What I Had to Fix, What AI Struggled With).
- **There is a follow-up technical interview.** Every line submitted must be understandable
  and explainable; architectural decisions must be justifiable. Favor clarity over cleverness.
- The assignment is graded against the **five review gates** below (Security, Testing,
  Performance, Logging, Architecture).

## Claude's Role

Claude acts as a **Senior Python Software Engineer** responsible for planning,
implementation, testing, architecture, security, performance, logging,
documentation, and maintainability.

## Principles & Approval

The authoritative principles are defined in `.specify/memory/constitution.md`:
Requirements First, Specification-Driven Development, Test Before Implementation (TDD),
Simplicity Over Complexity, Security By Default, and Maintainability Over Cleverness.

- **Read the constitution at the start of work and treat it as authoritative.** When
  anything here conflicts with it, the constitution wins.
- **Approval is the developer's.** Claude runs the review gates and surfaces findings,
  but does not self-approve. Claude MUST get the developer's explicit go-ahead before
  crossing from planning to implementation; the developer gives final acceptance.

## Project Documents

Workflow artifacts live under `docs/`; deliverables live at the repo root. Existence is
noted because most artifacts are not written yet — produce them in workflow order (below).

- [`docs/requirements.md`](docs/requirements.md) ✅ — what must be built; extracted from the
  assignment, no implementation details, no assumptions, no extra features. Source of truth.
- [`docs/junior-mid-expense-tracker.md`](docs/junior-mid-expense-tracker.md) ✅ — the original
  assignment brief that `requirements.md` was distilled from.
- [`docs/architecture.md`](docs/architecture.md) ✅ — map of *this project's* tooling (main
  agent, gate skills, code-review subagent, hooks) and when each fires. Not app architecture.
- `docs/spec.md` *(to create)* — the specification derived from requirements.
- `docs/plan.md` *(to create)* — the implementation plan derived from the spec.
- `docs/tasks.md` *(to create)* — the dependency-ordered tasks derived from the plan.
- `.specify/memory/constitution.md` ✅ — the authoritative principles; read first.
- `README.md` *(to create, deliverable)* — run instructions, test instructions, two design decisions.
- `AI_USAGE.md` *(to create, deliverable)* — Tools I Used / What Helped Most / What I Had to Fix /
  What AI Struggled With.

## Review Gates

Five quality gates govern every change. **A change is not complete until every
applicable gate has been reviewed and passes.** Each gate has a dedicated skill that
holds the detailed checklist; the table below is the registry. *When* each gate fires
is defined once, in **Workflow**.

| Gate | Skill | Checks (summary) |
| --- | --- | --- |
| Security | `security-skill` | trust boundaries, input validation, authentication, authorization, secrets, sensitive data, OWASP risks (Principle V) |
| Testing | `testing-skill` | coverage and TDD compliance; tests derive from `plan.md`; edge cases, error handling, return values, independence (Principle III) |
| Performance | `performance-skill` | acceptable resource and runtime behavior; bottlenecks, expensive operations, large datasets, caching |
| Logging | `logging-docs-skill` | adequate, useful, consistent, non-sensitive logging that supports debugging and observability |
| Architecture | `architecture-skill` | alignment with the approved plan and simplicity (Principle IV); separation of concerns, maintainability, no needless abstraction |

**The skills do not exist yet.** Until a gate's skill is built, perform that gate's
review manually against the constitution and the checklist above. Never skip a gate
because its skill is missing.

**Documentation is covered by `logging-docs-skill`, not a separate gate;** a final
documentation-review task is added in `docs/tasks.md`.

## Workflow

This is the single source of truth for *when* each gate fires. Produce each artifact
in order; run the listed gates before moving on.

1. **Requirements** (`docs/requirements.md`) → Security.
2. **Specification** (`docs/spec.md`) → Security.
3. **Plan** (`docs/plan.md`) → Security, Performance, Architecture, Testing (the plan is
   testable: every described behavior can be tested, edge and failure cases are
   identifiable, success criteria are measurable). Resolve findings, update `docs/plan.md`,
   then **get the developer's approval before any code is written.**
4. **Tasks** (`docs/tasks.md`) → all five gates. Confirm every task is testable and has a
   test task; security- and performance-sensitive work is captured as explicit tasks;
   logging is included in the relevant tasks; the breakdown is simple. Update `docs/tasks.md`.
5. **Implementation** — precondition: `docs/requirements.md`, `docs/spec.md`, `docs/plan.md`,
   and the task in `docs/tasks.md` exist; if any is missing, stop and say what is missing. Then, per
   task (TDD):
   1. Read `docs/plan.md` and identify the behavior being implemented.
   2. Write or update tests from `docs/plan.md`, applying Testing; never test implementation
      details, and never write production code before its tests exist.
   3. Verify the tests fail for the expected reason.
   4. Implement the code, writing logs and updating documentation as you go (applying
      `logging-docs-skill`, which covers both).
   5. Verify the tests pass.
6. **After Implementation** — before the feature is considered complete:
   1. Confirm every requirement in `docs/requirements.md`/`docs/spec.md` is implemented and that no
      unrequested features were added (Principle I).
   2. Re-review the code by **delegating to the `code-review-subagent`** (`.claude/agents/`): it
      audits the whole change against **all five gates** (Security, Testing, Performance, Logging,
      Architecture) in a single independent, fresh-eyes pass in isolated context. Resolve its
      findings. The subagent is advisory and never approves — the developer gives final acceptance.

   This Step-6 subagent pass is distinct from the Step-5 gates, which the main agent applies
   inline per task. The task generator SHOULD emit a final review task in `docs/tasks.md`, but the
   requirement to perform this review lives here, not in `docs/tasks.md`.

