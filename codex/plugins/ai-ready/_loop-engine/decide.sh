#!/usr/bin/env bash
# scored finding 들을 모아 종료 verdict 하나로 집계한다 (결정론).
# Usage:
#   score.sh < findings.json | decide.sh
#   decide.sh scored.json
#
# 입력(JSON): score.sh 출력 (각 finding 에 severity, await 포함).
#
# 출력(JSON):
#   { "verdict": "AWAIT_USER"|"RETRY"|"RETRY_SOFT"|"PASS",
#     "counts": { "BLOCKER":n, "CRITICAL":n, "MAJOR":n, "MINOR":n },
#     "await": true|false }
#
# 규칙(루브릭 "종료 판정"):
#   - await(BLOCKER 또는 force_await) 있으면         → AWAIT_USER
#   - BLOCKER 0, CRITICAL>=1                          → RETRY
#   - 위 아니고 MAJOR>=1                              → RETRY_SOFT
#   - 그 외(MINOR 만 또는 깨끗)                       → PASS

set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

input="$(cat "${1:-/dev/stdin}")"
# 빈 입력 = 앞단(score) 실패 의심. 파이프(score|decide)는 set -o pipefail 을 바깥에 전파
# 안 하므로, 빈 stdin 을 조용히 받아 PASS 같은 결과를 내면 score 실패가 통과로 둔갑한다.
[ -n "$input" ] || { echo "decide: 빈 입력 — score 단계 실패 의심 (사람 대기)" >&2; exit 65; }
# findings 없는 JSON(계약 밖 입력)을 // [] 로 빈 배열 오독하면 그대로 PASS 가 된다 — score 출력 계약을 fail-loud 로 강제.
loop_validate_json "$input" 'type=="object" and has("findings") and (.findings|type=="array")' \
  'decide 입력은 score 출력({findings:[...]})이어야 한다 (파이프 배선 오류 의심 — 사람 대기)'

jq '
  ((.findings // []) | map(select(.severity != null))) as $f
  | {
      counts: {
        BLOCKER:  ([$f[] | select(.severity == "BLOCKER")]  | length),
        CRITICAL: ([$f[] | select(.severity == "CRITICAL")] | length),
        MAJOR:    ([$f[] | select(.severity == "MAJOR")]    | length),
        MINOR:    ([$f[] | select(.severity == "MINOR")]    | length)
      },
      await: (([$f[] | select(.await == true)] | length) > 0)
    }
  | .verdict = (
      if   (.await or .counts.BLOCKER > 0) then "AWAIT_USER"
      elif (.counts.CRITICAL > 0)          then "RETRY"
      elif (.counts.MAJOR > 0)             then "RETRY_SOFT"
      else                                      "PASS"
      end )
' <<<"$input"
