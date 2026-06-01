#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit): mechanical security scan of edited files.
# Secret scan runs on Python AND on config likely to hold credentials (compose/Dockerfile/ini);
# bandit static analysis is Python-only. Complements security-skill, which owns the OWASP
# judgment. Stays silent until the project has a pyproject.toml (like run-tests.sh). On a finding
# it exits 2 to surface an advisory message; secret values are never echoed — only line numbers.

set -uo pipefail
root="${CLAUDE_PROJECT_DIR:-$PWD}"

# Pull the edited file path out of the JSON tool payload on stdin.
file=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)

# React to Python (secrets + bandit) and to config likely to hold secrets (secrets only).
# .env is intentionally excluded — it's the designated local secret store, so flagging it is noise.
case "$file" in
  *src/*.py|*tests/*.py)             is_py=1 ;;
  *compose*.y*ml|*Dockerfile*|*.ini) is_py=0 ;;
  *) exit 0 ;;
esac
cd "$root" 2>/dev/null || exit 0
[ -f pyproject.toml ] || exit 0
[ -f "$file" ] || exit 0

# 1) Hardcoded secrets (no external tool). Handles `k = "v"`, `k: v`, `k=v`, and credentials
#    embedded in URLs (`scheme://user:pass@`). Report line numbers only; skip env reads and
#    obvious placeholders. The key must END in a credential word (secret_key, access_token, ...),
#    so benign keys like token_type/token_url don't trip it. Do NOT skip settings/config lines.
secret_lines=$(grep -niE \
  '(-----BEGIN ([A-Z]+ )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|://[^@/[:space:]]*:[^@/[:space:]]{3,}@|(password|passwd|secret|token|api_?key|access_key)(_?(key|token|secret|password|pwd|hash))?["'\'']?[[:space:]]*[:=][[:space:]]*["'\'']?[^"'\''[:space:]]{6,})' \
  "$file" 2>/dev/null \
  | grep -viE 'getenv|environ|os\.|example|placeholder|changeme|dummy|<|\$\{' \
  | cut -d: -f1 | paste -sd, -)

# 2) bandit static analysis (Python only; medium+ severity & confidence). rc 0 = clean, 1 = findings,
#    >=2 = bandit didn't run — surface that loudly so this half of the gate can't fail silently.
bandit_out=""; bandit_rc=0
[ "$is_py" = 1 ] && { bandit_out=$(uv run bandit -q --severity-level medium --confidence-level medium "$file" 2>/dev/null); bandit_rc=$?; }
bandit_note=""
[ "$bandit_rc" -ge 2 ] && bandit_note="bandit did not run — the static-analysis half of the security gate is OFF (add 'bandit' to dev deps)."

[ -z "$secret_lines" ] && [ -z "$bandit_out" ] && [ -z "$bandit_note" ] && exit 0

{
  echo "Security scan flagged ${file}:"
  [ -n "$secret_lines" ] && echo "- Possible hardcoded secret(s) at line(s) ${secret_lines} (value redacted) — move to env/secrets store (OWASP A05)."
  [ -n "$bandit_out" ] && { echo "- bandit (medium+):"; printf '%s\n' "$bandit_out" | tail -n 40; }
  [ -n "$bandit_note" ] && echo "- ${bandit_note}"
  echo "(Advisory — security-skill owns the full OWASP judgment.)"
} >&2
exit 2
