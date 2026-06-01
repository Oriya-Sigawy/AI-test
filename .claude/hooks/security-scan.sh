#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit): mechanical security scan of edited Python.
# Complements security-skill, which owns the OWASP judgment. Stays silent until the project
# has a pyproject.toml (like run-tests.sh). On a finding it exits 2 to surface an advisory
# message; secret values are never echoed — only line numbers.

set -uo pipefail
root="${CLAUDE_PROJECT_DIR:-$PWD}"

# Pull the edited file path out of the JSON tool payload on stdin.
file=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)

# Only react to Python under src/ or tests/, and only once the project exists.
case "$file" in *src/*.py|*tests/*.py) ;; *) exit 0 ;; esac
cd "$root" 2>/dev/null || exit 0
[ -f pyproject.toml ] || exit 0
[ -f "$file" ] || exit 0

# 1) Hardcoded secrets (no external tool). Report line numbers only; skip obvious
#    placeholders. Do NOT skip settings/config lines — likeliest place a secret is hardcoded.
secret_lines=$(grep -niE \
  '(-----BEGIN ([A-Z]+ )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|(password|passwd|secret|token|api_?key|access_key)[^=]*=[[:space:]]*["'\''][^"'\'']{6,}["'\''])' \
  "$file" 2>/dev/null \
  | grep -viE 'example|placeholder|changeme|dummy|<|\$\{' \
  | cut -d: -f1 | paste -sd, -)

# 2) bandit static analysis (medium+ severity & confidence) — empty if bandit isn't available.
bandit_out=$(uv run bandit -q --severity-level medium --confidence-level medium "$file" 2>/dev/null)

[ -z "$secret_lines" ] && [ -z "$bandit_out" ] && exit 0

{
  echo "Security scan flagged ${file}:"
  [ -n "$secret_lines" ] && echo "- Possible hardcoded secret(s) at line(s) ${secret_lines} (value redacted) — move to env/secrets store (OWASP A05)."
  [ -n "$bandit_out" ] && { echo "- bandit (medium+):"; printf '%s\n' "$bandit_out" | tail -n 40; }
  echo "(Advisory — security-skill owns the full OWASP judgment.)"
} >&2
exit 2
