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
#   0-1. **깨끗함과 안 봄을 가른다.** findings 가 비었는데 reviewed 도 비면 exit 65.
#      `{"findings":[]}` 는 정상 형식이라 "파일이 비었나" 가드를 지나고, 베이스 브랜치 해석이
#      어긋나 diff 가 통째로 빈 경우와 진짜 깨끗한 경우가 구분되지 않는다. checker 는 정말
#      깨끗할 때 검토한 파일을 `reviewed` 에 담아야 한다(0.9.7 계약 변경).
#   1. severity 의 주 경로는 dimension floor. KINDS 예외표에 오른 kind 만 floor 대신 표값을 쓴다.
#      모르는 kind 든 floor 와 같은 kind 든 전부 dimension floor 로 채점된다(fallback 아니라 주 메커니즘).
#      kind·dimension 인덱싱은 null-safe(`// ""`) — 필드 누락이 jq 크래시로 배치 전체를 날리지 않게.
#      모르는/누락 dimension 은 가장 관대한 MINOR 가 아니라 보수적으로 CRITICAL 로 떨어뜨린다.
#      (dimension 은 checker 가 5값으로 못박은 닫힌 어휘라, 그 밖의 값은 정당한 신호가 아니라 LLM 오타다.)
#   2. location 이 rubric PATHWEIGHTS 패턴에 걸리면 셸이 가중을 붙여 checker 것과 합집합한다.
#      가중은 checker 가 주는 값이라 안 달면 조용히 한 단계 낮게 채점된다 — 경로로 유도되는 것만이라도
#      모델 밖에서 세운다. 붙인 값은 weights_derived 로 노출한다.
#      합친 뒤 rubric WEIGHTS 표의 허용 키가 하나라도 있으면 한 단계 상향 (CRITICAL→BLOCKER 등).
#      표 밖 키는 무시하고 weights_ignored 로 노출(임의 상향 차단). 허용 표가 없으면 레거시(비어있지 않으면 상향).
#   3. force_await(always 종류 / finding 플래그) 또는 BLOCKER 면 await=true.
#
# 출력(JSON): 입력 findings 각각에 severity, await, base, kind_known, layer,
#             weights_ignored, weights_derived 추가.

set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

input="$(cat "${1:-/dev/stdin}")"
loop_validate_json "$input" \
  'type=="object" and has("findings") and (.findings|type=="array")' \
  'score 입력은 {"findings":[...]} 객체여야 한다 (checker JSON 추출 실패 의심 — 사람 대기). 깨끗하면 {"findings":[]}'

# 깨끗한 결과("아무것도 못 찾음")와 아예 안 본 것을 가른다.
# findings 가 비었는데 reviewed 도 비어 있으면 checker 가 무엇을 봤는지 증거가 없다 — 흔한 원인은
# 베이스 브랜치 해석이 어긋나 diff 가 통째로 비는 것이고, 그러면 점검 없이 phase 가 통과한다.
# 파일이 비었는지는 오케스트레이터가 이미 보지만 `{"findings":[]}` 는 정상 형식이라 그 가드를 지난다.
if [ "$(jq -r '((.findings|length) == 0) and (((.reviewed // []) | length) == 0)' <<<"$input")" = "true" ]; then
  echo "loop: findings 도 reviewed 도 비었다 — checker 가 무엇을 봤는지 증거가 없다 (베이스 브랜치 해석 실패 의심 — 사람 대기). 정말 깨끗하면 검토한 파일을 reviewed 에 담아 보낸다." >&2
  exit 65
fi

kinds="$(loop_kinds_json)"
dimfloor="$(loop_dimfloor_json)"
weights_allowed="$(loop_weights_json)"
pathweights="$(loop_pathweights_json)"

jq \
  --argjson kinds "$kinds" \
  --argjson dim "$dimfloor" \
  --argjson wal "$weights_allowed" \
  --argjson pw "$pathweights" '
  def levels: ["_", "MINOR", "MAJOR", "CRITICAL", "BLOCKER"];
  def rank($s): {"MINOR":1, "MAJOR":2, "CRITICAL":3, "BLOCKER":4}[$s] // 0;
  def upgrade($s): rank($s) as $r | (if ($r >= 1 and $r < 4) then $r + 1 else $r end) | levels[.];

  .findings = ((.findings // []) | map(
    . as $f
    | ($kinds[$f.kind // ""]) as $k
    | (if $k then $k.base else ($dim[$f.dimension // ""] // "CRITICAL") end) as $base
    # location 경로가 PATHWEIGHTS 패턴에 걸리면 셸이 가중을 직접 붙인다 — checker 가 표시를 빠뜨려도
    # 등급이 서게 하는 자리. 잘못된 정규식은 그 행만 건너뛴다(한 줄 오타로 배치 전체를 죽이지 않게).
    | ($f.location // "") as $loc
    | ([ $pw[] as $row | select(try ($loc | test($row.p)) catch false) | $row.w[] ] | unique) as $derived
    | ((($f.weights // []) + $derived) | unique) as $all
    # 합친 뒤 rubric 허용 집합(WEIGHTS 표)으로 거른다 — 표 밖 키는 무시(임의 상향 차단).
    # 허용 표가 없으면(빈 배열) 레거시 동작 유지: 비어있지 않은 weights 면 상향.
    | (if ($wal | length) == 0 then $all else ($all | map(select(IN($wal[])))) end) as $vw
    | (if ($wal | length) == 0 then [] else ($all - $wal) end) as $vign
    | (if ($vw | length) > 0 then upgrade($base) else $base end) as $sev
    | ( $sev == "BLOCKER"
        or (($k.force_await // "no") == "always")
        or (($f.force_await // false) == true)
      ) as $await
    | $f + { severity: $sev, await: $await, base: $base, kind_known: ($k != null),
             layer: ($k.layer // null), weights_ignored: $vign, weights_derived: $derived }
  ))
' <<<"$input"
