#!/usr/bin/env bash
# ai-ready 무인 검증 loop — 결정론 루브릭 적용 셸의 공용 부트스트랩.
# 첫 줄에서 source 한다: source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
#
# 책임:
#   1. repo root / rubric.md 경로 해석.
#   2. severity 사다리 헬퍼 (MINOR<MAJOR<CRITICAL<BLOCKER).
#   3. rubric.md 의 마커로 감싼 마크다운 표를 TSV/JSON 으로 추출.
#
# 설계: severity 는 checker(LLM)가 아니라 이 셸이 매긴다 (judge 일관성).
# 호환: macOS 기본 bash 3.2 를 깨지 않는다 — 연관 배열(declare -A)·${var^^}·mapfile 미사용.
#       데이터 가공은 awk/jq 로 위임한다. jq, awk 는 필수.

set -euo pipefail

# shellcheck disable=SC2155
LOOP_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# rubric 은 2단이다: BASE(엔진에 번들된 프로젝트 무관 골격) + LOCAL(대상 프로젝트가 주입하는 override, 옵션).
# BASE 는 이 셸 옆에 항상 있다 — plugin 설치 위치($CLAUDE_PLUGIN_ROOT/_loop-engine)든 레포 내장이든
# 셸 위치 기준이라 cwd 와 무관하게 결정론적이다. 예전의 repo root 3단 역산은 제거했다: plugin 으로
# 배포되면 엔진 설치 위치와 대상 프로젝트가 다른 트리라 깊이 역산이 무의미하기 때문이다.
# LOCAL 은 looping 스킬이 $CLAUDE_PROJECT_DIR 기준으로 찾아 LOOP_RUBRIC_LOCAL 로 넘긴다.
# 둘을 합쳐 채점하되 같은 kind/dimension 은 LOCAL 이 BASE 를 덮는다.
LOOP_RUBRIC_BASE="${LOOP_RUBRIC_BASE:-$LOOP_LIB_DIR/rubric.base.md}"
export LOOP_RUBRIC_BASE
LOOP_RUBRIC_LOCAL="${LOOP_RUBRIC_LOCAL:-}"
export LOOP_RUBRIC_LOCAL

loop_require() {
  command -v "$1" >/dev/null 2>&1 || { echo "loop: '$1' 필요 (PATH 확인)" >&2; exit 127; }
}
loop_require jq
loop_require awk

[ -f "$LOOP_RUBRIC_BASE" ] || { echo "loop: base rubric 없음: $LOOP_RUBRIC_BASE" >&2; exit 66; }
if [ -n "$LOOP_RUBRIC_LOCAL" ] && [ ! -f "$LOOP_RUBRIC_LOCAL" ]; then
  echo "loop: LOCAL rubric 지정됐으나 파일 없음: $LOOP_RUBRIC_LOCAL" >&2; exit 66
fi

# --- severity 사다리 (순수 bash, 버전 안전) ---

loop_sev_rank() {
  case "$1" in
    MINOR) echo 1;; MAJOR) echo 2;; CRITICAL) echo 3;; BLOCKER) echo 4;; *) echo 0;;
  esac
}
loop_sev_name() {
  case "$1" in
    1) echo MINOR;; 2) echo MAJOR;; 3) echo CRITICAL;; 4) echo BLOCKER;; *) echo UNKNOWN;;
  esac
}
# 한 단계 상향 (BLOCKER 에서 멈춤).
loop_sev_upgrade() {
  local r; r="$(loop_sev_rank "$1")"
  [ "$r" -ge 1 ] && [ "$r" -lt 4 ] && r=$((r + 1))
  loop_sev_name "$r"
}

# --- 입력 검증 (fail-loud 게이트) ---
# 채점 셸은 신뢰하는 변환기가 아니라 안전 게이트다. 입력 생산자가 LLM checker 라
# 빈 출력·null·형식 오류가 흔하다. 그런 변질 입력을 조용히 통과(fail-open)시키면
# 진짜 결함이 PASS 로 둔갑한다. 비었거나 jq 검증식($2)을 통과 못 하면 시끄럽게 거부한다.
# exit 65 = 입력 데이터 오류(EX_DATAERR). 오케스트레이터는 이걸 사람 대기 신호로 본다.
loop_validate_json() {
  local input="$1" check="$2" msg="$3"
  if [ -z "$input" ]; then
    echo "loop: 빈 입력 — $msg" >&2; exit 65
  fi
  if ! printf '%s' "$input" | jq -e "$check" >/dev/null 2>&1; then
    echo "loop: 입력 형식 오류 — $msg" >&2; exit 65
  fi
}

# --- rubric 표 추출 ---
# 마커 LOOP_RUBRIC:<NAME>:BEGIN ~ :END 사이의 마크다운 표를
# 구분자 행을 빼고 TSV(헤더 포함)로 평탄화한다.
# BASE 표 먼저, LOCAL 표(있으면) 를 이어 출력한다. 헤더 행은 호출부(loop_kinds_json 등)가
# kind_id/dimension/param 으로 걸러내므로 BASE·LOCAL 양쪽 헤더가 섞여도 무해하다.
loop_table() {
  local name="$1"
  _loop_table_one "$LOOP_RUBRIC_BASE" "$name"
  [ -n "$LOOP_RUBRIC_LOCAL" ] && _loop_table_one "$LOOP_RUBRIC_LOCAL" "$name"
  return 0
}
_loop_table_one() {
  local file="$1" name="$2"
  awk -v b="LOOP_RUBRIC:${name}:BEGIN" -v e="LOOP_RUBRIC:${name}:END" '
    index($0, b) > 0 { inblk = 1; next }
    index($0, e) > 0 { inblk = 0; next }
    inblk && $0 ~ /^[[:space:]]*\|/ {
      line = $0
      # 구분자 행(|---|---|) 스킵
      if (line ~ /^[[:space:]]*\|[[:space:]:|-]+\|[[:space:]:|-]*$/) next
      sub(/^[[:space:]]*\|/, "", line)
      sub(/\|[[:space:]]*$/, "", line)
      n = split(line, a, "|")
      out = ""
      for (i = 1; i <= n; i++) {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", a[i])
        out = out a[i]
        if (i < n) out = out "\t"
      }
      print out
    }
  ' "$file"
}

# KINDS 표 → {kind_id: {dimension,layer,base,force_await}} JSON.
# 열 수가 모자란 행은 **조용히 버리지 않는다.** 전에는 `NF < 5` 로 건너뛰어, 손으로 적은 LOCAL 행이
# 한 칸 빠지면 그 kind 가 등록 안 된 채 dimension floor 로 떨어졌다 — 사람은 등록했다고 믿는다.
loop_kinds_json() {
  loop_table KINDS | awk -F'\t' '
    $1 == "kind_id" { next }
    NF < 5 { printf "loop: KINDS 행의 열이 모자란다(%d/5): %s\n", NF, $0 > "/dev/stderr"; bad = 1; next }
    { printf "{\"kind\":\"%s\",\"dimension\":\"%s\",\"layer\":\"%s\",\"base\":\"%s\",\"force_await\":\"%s\"}\n", $1, $2, $3, $4, $5 }
    END { if (bad) exit 65 }
  ' | jq -s '
    # 같은 kind 는 LOCAL(뒤)이 BASE(앞)를 덮는다 — **단 force_await=always 만 합집합**이다.
    # 자동화 금지 목록의 뜻이 "등급 무관 사람 대기" 라, 등급은 저장소가 조절해도 사람 게이트는 남는다.
    # 이 파일은 `.loop/rubric.md` 라 채점받는 쪽이 쓸 수 있어, 한 줄로 게이트가 사라지면 안 된다.
    group_by(.kind)
    | map({ key: .[0].kind,
            value: (.[-1] + { force_await: (if any(.[]; .force_await == "always") then "always"
                                            else .[-1].force_await end) }) })
    | from_entries'
}

# PATHEXCLUDE 표 → 제외 패턴 배열. 걸리면 경로 유도를 아예 안 한다(checker 가 직접 단 가중은 남는다).
# 부분 일치라 마이그레이션을 설명하는 문서·픽스처·의존성 트리까지 잡혀 무인 루프가 서던 것을 막고,
# 동시에 LOCAL 이 BASE 경로 규칙을 끄는 유일한 길이다(PATHWEIGHTS 는 누적이라 덮을 수 없다).
loop_pathexclude_json() {
  loop_table PATHEXCLUDE | awk -F'\t' '
    $1 == "exclude_pattern" || $1 == "" { next }
    { print $1 }
  ' | jq -R -s 'split("\n") | map(select(length > 0))'
}

# DIMFLOOR 표 → {dimension: floor_severity} JSON.
loop_dimfloor_json() {
  loop_table DIMFLOOR | awk -F'\t' '
    $1 == "dimension" || NF < 2 { next }
    { printf "{\"d\":\"%s\",\"f\":\"%s\"}\n", $1, $2 }
  ' | jq -s 'map({key: .d, value: .f}) | from_entries'
}

# WEIGHTS 표 → 허용 가중 키 JSON 배열 ["hotpath", ...]. 표가 없으면 빈 배열(score 가 레거시로 폴백).
# 단일 열(weight_key)이라 첫 컬럼만 본다. 헤더 행과 빈 행은 건너뛴다.
loop_weights_json() {
  loop_table WEIGHTS | awk -F'\t' '
    $1 == "weight_key" || $1 == "" { next }
    { printf "{\"w\":\"%s\"}\n", $1 }
  ' | jq -s 'map(.w)'
}

# PATHWEIGHTS 표 → [{p: 패턴, w: [가중키...]}] JSON 배열. 표가 없으면 빈 배열(유도 없음).
# location 경로에 패턴이 걸리면 score 가 그 가중을 checker 가 준 것과 합집합한다.
# 패턴 안에 `|` 를 쓰면 표 열이 쪼개지므로 한 행에 하나만 — rubric 산문이 그 제약을 적는다.
# BASE 행 뒤에 LOCAL 행이 이어 붙는다(덮어쓰기가 아니라 누적 — 경로 규칙은 많을수록 촘촘하다).
# JSON 은 손으로 짜지 않고 `jq -R` 로 인코딩한다. 이 열의 값은 **정규식**이라 역슬래시가 흔한데
# (`\.sql$` 같은), printf 로 따옴표에 끼워 넣으면 `\.` 이 JSON 의 잘못된 이스케이프가 되어
# 파서가 죽는다. 실제로 그렇게 죽는 것을 확인하고 이 방식으로 바꿨다. 큰따옴표도 같은 이유다.
loop_pathweights_json() {
  loop_table PATHWEIGHTS | awk -F'\t' '
    $1 == "path_pattern" || $1 == "" || NF < 2 { next }
    { print $1 "\t" $2 }
  ' | jq -R -s '
    split("\n") | map(select(length > 0)) | map(split("\t"))
    | map({ p: .[0],
            w: ((.[1] // "") | split(",") | map(sub("^\\s+"; "") | sub("\\s+$"; "")) | map(select(length > 0))) })
  '
}

# PARAMS 표에서 한 값 조회. 없으면 비0 exit.
loop_param() {
  loop_table PARAMS | awk -F'\t' -v k="$1" '
    $1 == "param" { next }
    $1 == k { val = $2; found = 1 }   # 마지막 매치 우선 — LOCAL 이 BASE 를 덮는다
    END { if (found) { print val; exit 0 } else exit 3 }
  '
}
