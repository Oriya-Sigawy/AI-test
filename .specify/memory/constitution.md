<!--
Sync Impact Report
==================
Version change: 2.1.0 → 2.2.0
Rationale: Adds the Testing review to the Plan phase (a testability check on plan.md) so the
Development Workflow matches CLAUDE.md, which now fires Testing at the Plan gate. Materially
expands workflow guidance; no principles added or removed → MINOR bump per the versioning policy.

Modified sections:
  - Development Workflow (Plan review now includes Testing — confirms the plan is testable)
Added principles: N/A
Removed principles: N/A
Added sections: N/A
Removed sections: N/A

Templates requiring updates:
  - .specify/templates/plan-template.md ✅ aligned
  - .specify/templates/spec-template.md ✅ aligned
  - .specify/templates/tasks-template.md ✅ aligned
  - CLAUDE.md ✅ aligned (Plan-phase gate now lists Testing)

Follow-up TODOs: None.
-->

# learning-AI Constitution

## Core Principles

### I. Requirements First

All work MUST originate from explicit requirements.

The project MUST NOT:

- Implement assumptions.
- Infer new features.
- Expand scope without approval.

If requirements are unclear, work MUST stop and seek clarification before proceeding.

**Rationale**: Acting on unstated assumptions produces scope creep and rework. Explicit
requirements are the only authorized source of work.

### II. Specification-Driven Development

Every change MUST flow through the authorized workflow (see Development Workflow). Implementation
is NOT allowed until the planning artifacts for that workflow exist and have been reviewed.

- Production code MUST NOT be written before reviewed planning artifacts exist.
- Implementation MUST NEVER bypass the workflow.
- When implementation conflicts with requirements, specifications, or plans, the planning
  documents are the source of truth.

**Rationale**: A single authoritative pipeline keeps the project coherent, catches design
problems while they are cheap to fix, and ensures documented intent—not ad hoc code—governs the
system.

### III. Test Before Implementation (NON-NEGOTIABLE)

The project follows Test-Driven Development (TDD).

Rules:

- Tests MUST be written before implementation.
- Tests MUST be derived from requirements and `plan.md`.
- Tests MUST validate behavior, not implementation details.
- New functionality MUST have tests, observed failing, before implementation begins.

**Rationale**: Writing tests first forces clear behavioral contracts and prevents code that is
untestable or untested from entering the project.

### IV. Simplicity Over Complexity

The simplest solution that satisfies the requirements MUST be preferred.

The project MUST avoid:

- Overengineering.
- Unnecessary abstractions.
- Premature optimization.
- Speculative design.

Complexity MUST be justified before it is introduced.

**Rationale**: As a small single-developer learning project, accidental complexity is the
primary risk to progress and understanding.

### V. Security By Default

Security MUST be considered during requirements, planning, implementation, and review.

Security reviews MUST cover:

- `requirements.md`
- `spec.md`
- `plan.md`
- implementation code

Security MUST be designed into the solution rather than added afterward.

**Rationale**: Retrofitting security is costly and error-prone; designing for it from the start
keeps the solution sound.

### VI. Maintainability Over Cleverness

Code MUST be understandable by future maintainers.

The project MUST prefer:

- Readability.
- Consistency.
- Clear naming.
- Straightforward design.

The project MUST avoid:

- Clever but obscure solutions.
- Unnecessary complexity.
- Hidden behavior.

A future maintainer SHOULD be able to understand the project quickly.

**Rationale**: Code is read far more often than it is written; clarity outlasts cleverness.

## Mandatory Review Gates

Every change MUST be reviewed against the following areas before it is considered complete. A
change MUST NOT be merged or accepted until each gate has been reviewed:

- **Security** — trust boundaries, input validation, authentication, authorization, secrets,
  sensitive data, and OWASP risks (see Principle V).
- **Testing** — coverage and TDD compliance; tests derive from `plan.md`; edge cases, error
  handling, return values, and test independence (see Principle III).
- **Architecture** — alignment with the approved plan and simplicity (Principle IV); separation
  of concerns, maintainability, and no needless abstraction.
- **Performance** — acceptable resource and runtime behavior; bottlenecks, expensive operations,
  large datasets, and caching.
- **Logging** — adequate, useful, consistent, non-sensitive logging that supports debugging and
  observability.

## Development Workflow

The authorized end-to-end workflow is:

Requirements → Specification → Plan → Review → Tasks → Review → (per task) Tests → Verify
Expected Failure → Implementation → Verify Tests Pass → Mandatory Review Gates

Reviews fire as follows:

- **Requirements** and **Specification** — Security review (Principle V).
- **Plan** — Security, Performance, Architecture, and Testing review; the Testing review confirms
  the plan is testable (every described behavior can be tested, edge and failure cases are
  identifiable, success criteria are measurable). Planning artifacts MUST be approved before any
  code is written.
- **Tasks** — all five gates: every task testable with a corresponding test task, security- and
  performance-sensitive work captured as explicit tasks, logging included in the relevant tasks,
  and a simple breakdown.
- **Mandatory Review Gates** — all five gates re-applied to the implementation before the change
  is closed.

Rules:

- No phase may be skipped.
- Tests MUST be observed failing before implementation begins.
- All Mandatory Review Gates MUST be satisfied before a change is closed.

## Governance

This constitution supersedes all other practices in the project. When any document, habit, or
tool conflicts with it, this constitution prevails.

- **Amendments**: Changes to this constitution MUST be documented, justified, and dated. Each
  amendment increments the version per the policy below.
- **Versioning policy** (semantic versioning):
  - **MAJOR**: Backward-incompatible governance or principle removals/redefinitions.
  - **MINOR**: A new principle or section is added, or guidance is materially expanded.
  - **PATCH**: Clarifications, wording, or non-semantic refinements.
- **Compliance review**: All work MUST be verified against these principles and the Mandatory
  Review Gates. Any complexity that deviates from Principle IV MUST be explicitly justified.

**Version**: 2.2.0 | **Ratified**: 2026-05-31 | **Last Amended**: 2026-05-31
