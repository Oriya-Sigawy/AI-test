# AI Usage

## Tools I Used

- **Claude Code** (Anthropic, Claude Opus) as the primary assistant for planning,
  implementation, tests, and review.

- I drove it with a spec-driven workflow and five review gates — Security, Testing,
  Performance, Logging, Architecture — each applied per change, plus a final review pass.

- **ChatGPT** (OpenAI) for general technical questions.

## What Helped Most

- **Surfacing a real security flaw I'd have missed.** During the security review, the
  assistant flagged a login *timing* side-channel: an unknown email skipped the bcrypt
  check and returned faster than a wrong password, letting an attacker enumerate accounts.
  The fix (always verify against a dummy hash) was small but I would not have spotted the
  hole on my own.

- **Catching wasted work in the hot path.** The performance pass noticed the shared
  pagination helper counted rows over a subquery that still carried its `ORDER BY` — a
  pointless sort on every list request. One-line fix (`order_by(None)`), verified against
  the load test.

## What I Had to Fix

- **Acting against an explicit "no."** When the AI asked a question and I answered "no, ..."
  while describing the change I *did* want, it sometimes went ahead and made the change I had
  just declined anyway. I had to catch it and revert.

## What AI Struggled With

- **Letting an outside review override the rules.** When I gave it another agent's review of
  its Markdown files, it followed the review's comments instead of the principles we'd already
  agreed on in CLAUDE.md / the constitution.

- **Not pausing when I asked to discuss.** Choosing "Chat about this" on a question should stop
  the task and wait for me, but it kept going and decided on its own — e.g. where to put and how
  to name the requirements doc — even after I reminded it that the decision was still mine.

- **Coordinating across multiple agents.** When several agents work together, they struggle to
  open or access the shared VS Code workspace holding each other's changes.

## What I Brought From My Own Experience

- **Centralizing shared and constant values in config.** Rather than scattering magic values
  through the code, I kept settings and constants in one place (`app/config.py`) — secrets and
  the database URL read from the environment, plus tunables like page sizes and the default
  categories — so they're easy to find, change, and override per environment.

- **Adding load testing.** I included a volume/load test that seeds a large dataset and checks
  the app still behaves correctly under it (e.g. pagination stays consistent across many rows),
  so performance and correctness at scale are verified, not assumed.
