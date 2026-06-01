---
name: "security-skill"
description: "Enforce the Security gate (constitution Principle V) via an OWASP Top 10 review. Use whenever a Markdown artifact (requirements / spec / plan / tasks / README / AI_USAGE) is produced or updated, or code is about to be or has been written (inline per task and on the whole change). Read-only — surfaces findings, never edits or approves."
argument-hint: "Optional path or scope to focus the review (e.g. a file, module, or task ID)"
compatibility: "Requires spec-kit project structure with .specify/ and the docs/ artifacts to review against"
allowed-tools: ["Read", "Grep", "Glob"]
metadata:
  author: "AI-assignment"
  gate: "Security"
user-invocable: true
disable-model-invocation: false
---

## Purpose

Enforce the **Security** gate and **Principle V (Security By Default)**: every change is reviewed
against the **OWASP Top 10** before it is considered complete. The review covers both the Markdown
artifacts (Steps 1-4) and the code (Steps 5-6). Run only the mode for the current phase; each returns
**PASS** or **CHANGES NEEDED** plus the specific finding and fix.

This gate **surfaces findings; it does not self-approve.** It is advisory — the developer resolves
the findings and gives final acceptance.

## When To Use

| Mode | Fires | Reviews |
| --- | --- | --- |
| 1 | An artifact (`requirements.md`, `spec.md`, `plan.md`, `tasks.md`, `README.md`, `AI_USAGE.md`) is produced/updated | the Markdown document |
| 2 | Code is about to be / has been written (inline per task, and the whole change at Step 6) | the code |

## What NOT To Do

- **Do not edit, fix, or write any file.** This skill is read-only; surface the finding and the
  recommended fix — the developer (or the implementation step) applies it.
- **Do not approve or sign off.** Findings are advisory; only the developer accepts.
- **Do not output discovered secrets.** If you find a credential / token / key, report its location
  and **redact the value** — never echo it.
- Do not run destructive, networked, or state-changing commands.

## Mode 1 — Artifact (Markdown) review

- [ ] No secrets, credentials, API keys, tokens, real PII, or internal hostnames/IPs in the document.
- [ ] Security-relevant requirements are **present and not weakened**: authentication, authorization
      (ownership / least privilege), input validation, secure secret & password storage, error handling.
- [ ] No insecure guidance that would propagate into code (e.g. plaintext passwords, disabled TLS
      verification, "trust client input", overly broad permissions).
- [ ] Trust boundaries and sensitive-data flows are identified where the document describes them.

## Mode 2 — Code review (OWASP Top 10)

- [ ] **A01 Broken Access Control** — every resource is owner-scoped; no missing authorization checks.
- [ ] **A02 Cryptographic Failures** — passwords hashed (strong algo); secrets not hardcoded; TLS / at-rest as needed.
- [ ] **A03 Injection** — parameterized queries / ORM; input validated; no string-built SQL / shell / commands.
- [ ] **A04 Insecure Design** — sensitive flows (auth, tokens) follow a safe-by-default pattern.
- [ ] **A05 Security Misconfiguration** — no debug in prod; safe defaults; secrets from env; errors don't leak internals.
- [ ] **A06 Vulnerable / Outdated Components** — dependencies pinned (manual pin-review only; no automated CVE audit — run `pip-audit` if needed).
- [ ] **A07 Identification & Authentication Failures** — tokens signed & expiring; no weak/guessable auth; no user enumeration.
- [ ] **A08 Software & Data Integrity Failures** — inputs / deserialization validated; no untrusted code paths.
- [ ] **A09 Security Logging Failures** — security events logged; logs never contain secrets / passwords / tokens.
- [ ] **A10 SSRF** — server-side fetches of user-supplied URLs are validated / restricted (skip if the app makes no such fetches).

## Output

End every run with:

1. **Verdict:** `PASS` or `CHANGES NEEDED`.
2. **Findings** (one per issue): severity (`high` / `medium` / `low`), `file:line` (or doc section),
   the OWASP category (Mode 2) or artifact issue (Mode 1), the risk in one line, and the recommended fix.
3. If `PASS`, state what was checked so the developer can confirm the scope.

Order findings by severity (high → low). No findings → `PASS`.

---

**Note:** a deterministic security hook (secret scan + static analysis, e.g. `bandit`) can run on each
code edit for the mechanical checks; this skill owns the **judgment**. They are complementary — the
hook catches obvious sinks/secrets the moment they're written; the skill reasons about access control,
design, and the Markdown artifacts.
