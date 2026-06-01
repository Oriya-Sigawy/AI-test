#!/usr/bin/env bash
# PostToolUse hook — runs the test suite after a Python source/test edit.
#
# Backs the Testing gate (constitution Principle III): gives continuous red/green
# feedback in the per-task TDD loop. It is intentionally defensive — it stays silent
# until the project actually has a pyproject.toml and at least one test, so it does
# nothing during early scaffolding.
#
# Triggered as a PostToolUse hook on Edit|Write|MultiEdit. On a failing suite it exits
# 2, which feeds the failure output back to Claude.

set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$PWD}"

# The tool payload arrives as JSON on stdin; pull out the edited file path.
input=$(cat)
file=$(printf '%s' "$input" | python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get("tool_input", {}).get("file_path", ""))
except Exception:
    print("")
' 2>/dev/null)

# React only to Python files under src/ or tests/.
case "$file" in
  *src/*.py|*tests/*.py) ;;
  *) exit 0 ;;
esac

cd "$root" 2>/dev/null || exit 0

# Nothing to run until the project exists and has tests.
[ -f pyproject.toml ] || exit 0
[ -d tests ] || exit 0
find tests -name '*.py' -print -quit 2>/dev/null | grep -q . || exit 0

out=$(uv run pytest -q 2>&1)
status=$?

if [ "$status" -eq 0 ]; then
  exit 0
fi

{
  echo "Test status after editing ${file}: FAILING."
  echo "(Expected during the TDD red phase; must pass once the behavior is implemented.)"
  echo "--- pytest output (last 40 lines) ---"
  printf '%s\n' "$out" | tail -n 40
} >&2
exit 2
