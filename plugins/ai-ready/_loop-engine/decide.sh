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
#     "out_of_scope": { "BLOCKER":n, "CRITICAL":n, "MAJOR":n, "MINOR":n, "unmarked":n },
#     "await": true|false }
#
# 규칙(루브릭 "종료 판정"):
#   - await(BLOCKER 또는 force_await) 있으면         → AWAIT_USER
#   - BLOCKER 0, CRITICAL>=1                          → RETRY
#   - 위 아니고 MAJOR>=1                              → RETRY_SOFT
#   - 그 외(MINOR 만 또는 깨끗)                       → PASS
#
# `out_of_scope` 는 **판정에 안 들어간다.** verdict 는 위 네 줄이 전부고 이 값은 세기만 한다.
# 왜 세나: 무인 루프가 회차를 다 쓰고 멈추는 자리에서 사람이 묻는 것이 "이 지적이 이번 phase 가
# 보기로 한 표면인가" 인데, 지금까지 그 답이 사람 머릿속에만 있었다. phase 가 안 볼 표면을 미리
# 적고(`phases.json` 의 `non_goals`) 렌즈가 finding 마다 표시하면, 그 답이 파일에 남아 다음
# 판단의 근거가 된다. **등급을 내리지 않는 이유**는 근거가 아직 한 저장소 한 루프뿐이어서다 —
# 재는 장치를 먼저 두고, 수치가 쌓인 뒤에 강등을 얹을지 정한다.

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
      # 범위 밖 계측(판정에 안 들어감). `in_scope == false` 라고 **분명히 말한 것만** 범위 밖으로
      # 센다. 나머지는 전부 unmarked 다 — 필드 누락(null)뿐 아니라 `"false"` 같은 오타 값도 여기로
      # 온다. 오타를 범위 밖으로 읽으면 강등이 없는 지금도 수치가 부풀고, 나중에 강등을 얹으면
      # 그 오타 하나가 등급을 내린다. score.sh 의 force_await 판정이 "거짓이라고 분명히 말한 값만
      # 거짓" 인 것과 같은 방향이다 — 애매한 것은 사람을 부르는 쪽으로 떨어뜨린다.
      # 세 갈래(in / out / unmarked)의 합은 항상 finding 총수와 같아, 렌즈가 표시를 통째로
      # 빠뜨린 회차는 unmarked 가 총수와 같은 것으로 드러난다(0 이 "범위 밖 없음" 인지
      # "아무도 안 쟀음" 인지 구분되게 하는 자리).
      out_of_scope: {
        BLOCKER:  ([$f[] | select(.in_scope == false and .severity == "BLOCKER")]  | length),
        CRITICAL: ([$f[] | select(.in_scope == false and .severity == "CRITICAL")] | length),
        MAJOR:    ([$f[] | select(.in_scope == false and .severity == "MAJOR")]    | length),
        MINOR:    ([$f[] | select(.in_scope == false and .severity == "MINOR")]    | length),
        unmarked: ([$f[] | select(.in_scope != true and .in_scope != false)]       | length)
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
