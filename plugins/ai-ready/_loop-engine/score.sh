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
# 출력(JSON): 입력 findings 각각에 severity, await, base, kind_known,
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
# 타입을 먼저 확정한다 — `.reviewed` 가 배열이 아니면 길이를 0 으로 본다(거부 방향).
# 그냥 `(.reviewed // []) | length` 로 쓰면 `reviewed:true` 에서 jq 가 죽고, 그 실패가
# 명령치환의 빈 문자열이 되어 `if` 조건이 거짓이 되고, 게이트가 통째로 열린다(0.9.7 적대적 시험).
if [ "$(jq -r 'def n($v): if ($v|type) == "array" then ($v|length) else 0 end;
               (n(.findings) == 0) and (n(.reviewed) == 0)' <<<"$input")" = "true" ]; then
  echo "loop: findings 도 reviewed 도 비었다 — checker 가 무엇을 봤는지 증거가 없다 (베이스 브랜치 해석 실패 의심 — 사람 대기). 정말 깨끗하면 검토한 파일을 reviewed 에 담아 보낸다." >&2
  exit 65
fi

kinds="$(loop_kinds_json)"
dimfloor="$(loop_dimfloor_json)"
weights_allowed="$(loop_weights_json)"
pathweights="$(loop_pathweights_json)"
pathexclude="$(loop_pathexclude_json)"

# PATHWEIGHTS 가 유도하는 키는 전부 WEIGHTS 허용 표 안이어야 한다. 밖이면 rubric 설정 오류다 —
# 조용히 무시하면 사람은 그 경로를 덮었다고 믿고 실제로는 아무 가중도 안 선다.
# 표 구분자가 `|` 라 정규식에 alternation 을 쓰면 열이 밀려 경로가 가중 키 자리에 오는데,
# 그 사고가 정확히 여기서 잡힌다(`| db/migrate|db/changelog | operational_data |`).
bad_keys="$(jq -r --argjson wal "$weights_allowed" '
  [ .[] | .w[] | select(IN($wal[]) | not) ] | unique | join(", ")' <<<"$pathweights")"
# 가중 열이 빈 행도 거부한다 — `| db/migrate| | operational_data |` 처럼 파이프 오타 하나로
# 그 행이 아무것도 안 붙이는데 경고가 없었다(계약 리뷰 실측).
empty_rows="$(jq -r '[ .[] | select((.w | length) == 0) | .p ] | join(", ")' <<<"$pathweights")"
if [ -n "$empty_rows" ]; then
  echo "loop: PATHWEIGHTS 행에 가중 키가 없다: $empty_rows" >&2
  exit 65
fi
if [ -n "$bad_keys" ]; then
  echo "loop: PATHWEIGHTS 가 WEIGHTS 허용 표에 없는 키를 유도한다: $bad_keys" >&2
  echo "      (정규식에 | 를 쓰면 표 열이 밀린다 — 패턴은 한 행에 하나만 적는다)" >&2
  exit 65
fi

jq \
  --argjson kinds "$kinds" \
  --argjson dim "$dimfloor" \
  --argjson wal "$weights_allowed" \
  --argjson pw "$pathweights" \
  --argjson px "$pathexclude" '
  def levels: ["_", "MINOR", "MAJOR", "CRITICAL", "BLOCKER"];
  def rank($s): {"MINOR":1, "MAJOR":2, "CRITICAL":3, "BLOCKER":4}[$s] // 0;
  def upgrade($s): rank($s) as $r | (if ($r >= 1 and $r < 4) then $r + 1 else $r end) | levels[.];

  .findings = ((.findings // []) | map(
    . as $f
    | ($kinds[$f.kind // ""]) as $k
    | ($dim[$f.dimension // ""] // "CRITICAL") as $floor
    # kind 가 선언한 dimension 과 신고된 dimension 이 같으면 표값을 그대로 쓴다(n-plus-1 이 runtime floor
    # 아래인 것처럼, 표가 floor 보다 낮게 두는 것은 의도다). 어긋나면 둘 중 **높은 쪽**을 쓴다 —
    # 어긋남은 정당한 신호가 아니라 오태깅이고, 어느 방향으로도 조용히 낮아지면 안 된다.
    | (if $k then
         (if ($k.dimension == ($f.dimension // "")) then $k.base
          else (if rank($k.base) >= rank($floor) then $k.base else $floor end) end)
       else $floor end) as $base
    # location 경로가 PATHWEIGHTS 패턴에 걸리면 셸이 가중을 직접 붙인다 — checker 가 표시를 빠뜨려도
    # 등급이 서게 하는 자리. 잘못된 정규식은 그 행만 건너뛴다(한 줄 오타로 배치 전체를 죽이지 않게).
    # `location` 은 `경로:줄`(때로 `:줄:열`) 형태라 줄 번호를 떼고 맞춘다 — 안 그러면 `\.md$` 같은
    # 끝 앵커가 영영 안 맞는다(`docs/x.md:12`). 실제로 그래서 문서 제외가 안 들었다.
    | (($f.location // "") | sub("(:[0-9]+)+$"; "")) as $loc
    # 패턴을 `$ex` 로 묶는 것이 핵심이다 — `test(.; "i")` 로 쓰면 인자 안의 `.` 이 패턴이 아니라
    # 입력($loc)을 가리켜 경로를 자기 자신과 비교하고, 모든 경로가 제외된다(실제로 그렇게 짰다가 잡았다).
    | ([ $px[] as $ex | select(try ($loc | test($ex; "i")) catch false) ] | length > 0) as $excluded
    | (if $excluded then []
       else ([ $pw[] as $row | select(try ($loc | test($row.p; "i")) catch false) | $row.w[] ] | unique) end) as $derived
    | (if (($f.weights // []) | type) == "array" then ($f.weights // []) else [] end) as $given
    | (if (($f.weights // []) | type) == "array" then [] else [($f.weights | tostring)] end) as $malformed
    | (($given + $derived) | unique) as $all
    # 합친 뒤 rubric 허용 집합(WEIGHTS 표)으로 거른다 — 표 밖 키는 무시(임의 상향 차단).
    # 허용 표가 없으면(빈 배열) 레거시 동작 유지: 비어있지 않은 weights 면 상향.
    | (if ($wal | length) == 0 then $all else ($all | map(select(IN($wal[])))) end) as $vw
    | ((if ($wal | length) == 0 then [] else ($all - $wal) end) + $malformed) as $vign
    | (if ($vw | length) > 0 then upgrade($base) else $base end) as $sev
    # `== true` 엄격 비교가 `"always"`·`"true"`·`1` 을 조용히 무시했다. 하필 KINDS 표의 그 열 값이
    # `always` 라, 표 어휘를 그대로 베낀 checker 가 사람 대기를 통째로 없앨 수 있었다(적대적 시험 8).
    # 부정 목록으로 뒤집어 **거짓이라고 분명히 말한 값만** 거짓으로 본다 — 오타는 사람을 부르는 쪽으로.
    | (($f.force_await // false) | (. != false and . != null and . != "false" and . != "no" and . != "")) as $fa
    | ( $sev == "BLOCKER"
        or (($k.force_await // "no") == "always")
        or $fa
      ) as $await
    | $f + { severity: $sev, await: $await, base: $base, kind_known: ($k != null),
             weights_ignored: $vign, weights_derived: $derived }
  ))
' <<<"$input"
