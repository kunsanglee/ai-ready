#!/usr/bin/env bash
# Stop-hook wrapper for ai-ready plugin freshness check.
#
# Install by adding to your project's .claude/settings.json:
#
#   {
#     "hooks": {
#       "Stop": [
#         {
#           "matcher": ".*",
#           "hooks": [
#             { "type": "command",
#               "command": "$CLAUDE_PLUGIN_ROOT/skills/audit/hooks/freshness_check.sh" }
#           ]
#         }
#       ]
#     }
#   }
#
# CLAUDE_PLUGIN_ROOT is set by Claude Code when this hook fires from a plugin
# context. install_hook.py writes that exact command into settings.json.
#
# It is intentionally advisory: prints warnings, never blocks. Output is also
# appended to <project>/.ai-ready/freshness.log.

set -u

SKILL_DIR="${CLAUDE_PLUGIN_ROOT}/skills/audit"
SCRIPT="${SKILL_DIR}/scripts/freshness_check.py"

if [ ! -f "$SCRIPT" ]; then
  echo "freshness_check.sh: missing ${SCRIPT}" >&2
  exit 0
fi

# CLAUDE_PROJECT_DIR is provided by Claude Code when running hooks.
TARGET="${CLAUDE_PROJECT_DIR:-$PWD}"
THRESHOLD_DAYS="${AI_READY_FRESHNESS_DAYS:-7}"

python3 "$SCRIPT" --target "$TARGET" --threshold-days "$THRESHOLD_DAYS" --quiet || true
exit 0
