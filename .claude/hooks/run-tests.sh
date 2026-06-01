#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit): run the test suite after a Python source/test edit.
# Backs the Testing gate (continuous TDD red/green feedback). Stays silent until the project has
# a pyproject.toml, a test file, and uv. On a failing suite it exits 2 to feed output back to Claude.

set -uo pipefail
root="${CLAUDE_PROJECT_DIR:-$PWD}"

# Pull the edited file path out of the JSON tool payload on stdin.
file=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)

# Only react to Python under src/ or tests/.
case "$file" in *src/*.py|*tests/*.py) ;; *) exit 0 ;; esac
cd "$root" 2>/dev/null || exit 0

# Stay dormant until the project, tests, and runner all exist.
[ -f pyproject.toml ] || exit 0
find tests -name '*.py' -print -quit 2>/dev/null | grep -q . || exit 0
command -v uv >/dev/null 2>&1 || exit 0

out=$(uv run pytest -q 2>&1) && exit 0

{
  echo "Test status after editing ${file}: FAILING."
  echo "(Expected during the TDD red phase; must pass once the behavior is implemented.)"
  echo "--- pytest output (last 40 lines) ---"
  printf '%s\n' "$out" | tail -n 40
} >&2
exit 2
