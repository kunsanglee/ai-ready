#!/usr/bin/env bash
# checker finding 에 결정론으로 severity 를 부여한다 (checker 는 severity 를 안 매긴다).
# Usage:
#   score.sh < findings.json
#   score.sh findings.json
#
# 입력(JSON): checker 출력.
#   { "findings": [
#       { "id":"f1", "kind":"n-plus-1", "dimension":"runtime",
#         "location":"path/File.kt:88", "evidence":"...",
#         "weights":["hotpath"],        # 가중조건 플래그 (생략 가능)
#         "force_await": false } ,       # 자동화 금지 영역 직접 플래그 (생략 가능)
#       ... ] }
#
# 처리:
#   0. 입력 게이트. {"findings":[...]} 객체가 아니면(빈 문자열·null·{}·findings 비배열)
#      조용히 통과시키지 않고 exit 65 로 거부한다. checker JSON 추출 실패를 PASS 로 둔갑 금지.
#   1. severity 의 주 경로는 dimension floor. KINDS 예외표에 오른 kind 만 floor 대신 표값을 쓴다.
#      모르는 kind 든 floor 와 같은 kind 든 전부 dimension floor 로 채점된다(fallback 아니라 주 메커니즘).
#      kind·dimension 인덱싱은 null-safe(`// ""`) — 필드 누락이 jq 크래시로 배치 전체를 날리지 않게.
#      모르는/누락 dimension 은 가장 관대한 MINOR 가 아니라 보수적으로 CRITICAL 로 떨어뜨린다.
#      (dimension 은 checker 가 5값으로 못박은 닫힌 어휘라, 그 밖의 값은 정당한 신호가 아니라 LLM 오타다.)
#   2. weights 중 rubric WEIGHTS 표의 허용 키가 하나라도 있으면 한 단계 상향 (CRITICAL→BLOCKER 등).
#      표 밖 키는 무시하고 weights_ignored 로 노출(임의 상향 차단). 허용 표가 없으면 레거시(비어있지 않으면 상향).
#   3. force_await(always 종류 / finding 플래그) 또는 BLOCKER 면 await=true.
#
# 출력(JSON): 입력 findings 각각에 severity, await, base, kind_known 추가.

set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

input="$(cat "${1:-/dev/stdin}")"
loop_validate_json "$input" \
  'type=="object" and has("findings") and (.findings|type=="array")' \
  'score 입력은 {"findings":[...]} 객체여야 한다 (checker JSON 추출 실패 의심 — 사람 대기). 깨끗하면 {"findings":[]}'
kinds="$(loop_kinds_json)"
dimfloor="$(loop_dimfloor_json)"
weights_allowed="$(loop_weights_json)"

jq \
  --argjson kinds "$kinds" \
  --argjson dim "$dimfloor" \
  --argjson wal "$weights_allowed" '
  def levels: ["_", "MINOR", "MAJOR", "CRITICAL", "BLOCKER"];
  def rank($s): {"MINOR":1, "MAJOR":2, "CRITICAL":3, "BLOCKER":4}[$s] // 0;
  def upgrade($s): rank($s) as $r | (if ($r >= 1 and $r < 4) then $r + 1 else $r end) | levels[.];

  .findings = ((.findings // []) | map(
    . as $f
    | ($kinds[$f.kind // ""]) as $k
    | (if $k then $k.base else ($dim[$f.dimension // ""] // "CRITICAL") end) as $base
    # 가중 키를 rubric 허용 집합(WEIGHTS 표)으로 거른다 — 표 밖 키는 무시(임의 상향 차단).
    # 허용 표가 없으면(빈 배열) 레거시 동작 유지: 비어있지 않은 weights 면 상향.
    | (($f.weights // []) | if ($wal | length) == 0 then . else map(select(IN($wal[]))) end) as $vw
    | (if ($wal | length) == 0 then [] else (($f.weights // []) - $wal) end) as $vign
    | (if ($vw | length) > 0 then upgrade($base) else $base end) as $sev
    | ( $sev == "BLOCKER"
        or (($k.force_await // "no") == "always")
        or (($f.force_await // false) == true)
      ) as $await
    | $f + { severity: $sev, await: $await, base: $base, kind_known: ($k != null), weights_ignored: $vign }
  ))
' <<<"$input"
