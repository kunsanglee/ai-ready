#!/usr/bin/env bash
# Stop-hook wrapper for ai-ready plugin freshness check.
#
# Standard install (what install_hook.py writes into settings.json):
# audit.py copies this script AND freshness_check.py into the target repo's
# .ai-ready/hooks/, and the project's .claude/settings.json references:
#
#   {
#     "hooks": {
#       "Stop": [
#         {
#           "matcher": ".*",
#           "hooks": [
#             { "type": "command",
#               "command": "[ -x \"$CLAUDE_PROJECT_DIR/.ai-ready/hooks/freshness_check.sh\" ] && exec \"$CLAUDE_PROJECT_DIR/.ai-ready/hooks/freshness_check.sh\"; exit 0" }
#           ]
#         }
#       ]
#     }
#   }
#
# The `[ -x … ]` guard is not decoration. When this file is missing — the session was opened
# from a parent folder so CLAUDE_PROJECT_DIR points outside the repo, or install_hook.py ran
# before audit.py copied the script here — a bare command prints "No such file or directory"
# at the end of every turn. This hook is advisory and blocks nothing, so that error stops
# nothing and only leaves noise; the guard exits 0 silently instead. `exec` passes the hook
# JSON on stdin straight through. install_hook.py writes exactly that command.
#
# Secondary option: you may instead point the command at the plugin bundle
# ($CLAUDE_PLUGIN_ROOT/skills/audit/hooks/freshness_check.sh) — but
# CLAUDE_PLUGIN_ROOT is only set when the hook fires from a plugin context,
# so the copied-into-repo form above is the standard.
#
# It is intentionally advisory: prints warnings, never blocks. Output is also
# appended to <project>/.ai-ready/freshness.log.

set -u

# Python script resolution, two tiers:
#   1. next to this script (the standard copied-into-repo layout)
#   2. plugin bundle via CLAUDE_PLUGIN_ROOT, when that variable is available
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="${SELF_DIR}/freshness_check.py"
if [ ! -f "$SCRIPT" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/freshness_check.py"
fi

if [ ! -f "$SCRIPT" ]; then
  echo "freshness_check.sh: missing freshness_check.py (looked in ${SELF_DIR} and \$CLAUDE_PLUGIN_ROOT)" >&2
  exit 0
fi

# CLAUDE_PROJECT_DIR is provided by Claude Code when running hooks.
TARGET="${CLAUDE_PROJECT_DIR:-$PWD}"
THRESHOLD_DAYS="${AI_READY_FRESHNESS_DAYS:-7}"

python3 "$SCRIPT" --target "$TARGET" --threshold-days "$THRESHOLD_DAYS" --quiet || true
exit 0
