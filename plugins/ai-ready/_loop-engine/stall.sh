#!/usr/bin/env bash
# 정체 감지: 등급 개수 벡터 사전식 비교 + best-ever floor. 사이클 간 상태 파일 유지.
# Usage:
#   decide.sh < scored.json | stall.sh --state .loop/run/{ticket}/stall.json
#   stall.sh --state <file> decide.json
#
# 입력(JSON): decide.sh 출력 (.counts.{CRITICAL,MAJOR,MINOR} 사용).
# 상태 파일: 없으면 INIT 로 생성, 있으면 읽어 갱신 후 다시 씀.
#
# 출력(JSON, stdout) = 갱신된 상태 + 판정:
#   { "status": "INIT"|"PROGRESS"|"ONGOING"|"STALLED"|"REGRESS_ESCALATE"|"NO_STALL_MINOR",
#     "floor": [C,M,Mn],            # best-ever (사전식 최소) 벡터
#     "cur":   [C,M,Mn],
#     "no_progress": n,             # floor 연속 미갱신 횟수
#     "regress_streak": n,          # 직전 대비 악화 연속 횟수
#     "active_grade": "CRITICAL"|"MAJOR"|"MINOR"|"NONE",   # cur 의 최상위 비0 등급(임계 기준)
#     "threshold": n|null }
#
# 규칙(루브릭 "정체 점수"):
#   - 진전 = cur 가 best-ever floor 보다 사전식으로 작을 때만. (직전 대비 아님)
#   - 정체 = floor 연속 미갱신이 임계 이상. 임계 기준은 cur 의 active grade(floor 아님 — floor 가
#     MINOR-only 라도 cur 가 CRITICAL 로 고착되면 STALLED). CRITICAL/MAJOR 임계는 rubric PARAMS.
#     cur 가 MINOR 만이면 비활성(NO_STALL_MINOR) — 게이트가 통과시킴.
#   - 악화 = 직전 대비 "상위 등급 새로 생김"(CRITICAL 칸 증가, 또는 CRITICAL 동일+MAJOR 칸 증가).
#     MINOR 만 늘어난 건 악화 아님. regress_consecutive 연속 → 즉시 사람(REGRESS_ESCALATE).
#   - BLOCKER 는 즉시 사람이라 정체 벡터에서 제외.

set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

state_file=""
arg=""
while [ $# -gt 0 ]; do
  case "$1" in
    --state)
      [ $# -ge 2 ] || { echo "stall: --state 에 <file> 인자 필요" >&2; exit 64; }
      state_file="$2"; shift 2;;
    *) arg="$1"; shift;;
  esac
done
[ -n "$state_file" ] || { echo "stall: --state <file> 필요" >&2; exit 64; }

if [ -n "$arg" ]; then input="$(cat "$arg")"; else input="$(cat)"; fi
# 빈 입력 = 앞단(decide) 실패 의심. 조용히 죽으면 state(best-ever floor)를 잃어 다음 사이클이
# INIT 로 리셋되고 정체 감지가 무력화된다. 시끄럽게 거부하고 state 는 건드리지 않는다.
[ -n "$input" ] || { echo "stall: 빈 입력 — decide 단계 실패 의심 (사람 대기)" >&2; exit 65; }
# counts 없는 JSON(예: score 출력을 직결한 배선 오류)을 // 0 으로 [0,0,0] 오독하면 floor 가 0 벡터로
# 굳어 이후 모든 사이클이 "미갱신"으로 왜곡된다 — decide 출력 계약을 fail-loud 로 강제한다.
loop_validate_json "$input" 'type=="object" and has("counts")' \
  'stall 입력은 decide 출력({counts:{...}})이어야 한다 (파이프 배선 오류 의심 — 사람 대기)'
cur="$(jq -c '[(.counts.CRITICAL // 0), (.counts.MAJOR // 0), (.counts.MINOR // 0)]' <<<"$input")"

thr_c="$(loop_param stall_threshold_critical)"
thr_m="$(loop_param stall_threshold_major)"
reg_n="$(loop_param regress_consecutive)"

# 상태 파일도 신뢰할 수 없는 입력이다 — `.loop/run/{ticket}/` 이라 maker 가 쓸 수 있는 자리고,
# 검증은 stdin 에만 걸려 있었다(적대적 시험 13·14). 두 가지가 실제로 났다.
#   - `no_progress` 에 음수를 한 번 심으면 임계에 영영 못 닿아 정체 감지가 죽는다.
#   - 형식이 깨지면(`{}`) jq 산술이 죽고 파일이 그대로 남아 **그 뒤 모든 사이클이 같은 자리에서** 죽는다.
# 형식이 어긋나면 시끄럽게 알리고 INIT 로 회복한다(계속 죽는 것보다 낫다). 카운터는 0 이상으로 조인다.
prev="null"
if [ -f "$state_file" ]; then
  raw="$(cat "$state_file")"
  if printf '%s' "$raw" | jq -e '
        type == "object"
        and ([.floor, .cur, .prev] | all(type == "array" and length == 3 and all(type == "number")))
        and (.no_progress | type == "number") and (.regress_streak | type == "number")' >/dev/null 2>&1; then
    prev="$(printf '%s' "$raw" | jq -c '.no_progress = ([.no_progress, 0] | max)
                                        | .regress_streak = ([.regress_streak, 0] | max)')"
  else
    echo "stall: 상태 파일 형식이 어긋난다($state_file) — INIT 로 회복한다. 누가 덮어썼는지 확인할 것." >&2
  fi
fi

result="$(jq -n \
  --argjson prev "$prev" \
  --argjson cur "$cur" \
  --argjson thrC "$thr_c" \
  --argjson thrM "$thr_m" \
  --argjson regN "$reg_n" '
  # 사전식 비교: <0, 0, >0
  def lexcmp($a; $b):
    if   $a[0] != $b[0] then ($a[0] - $b[0])
    elif $a[1] != $b[1] then ($a[1] - $b[1])
    else                     ($a[2] - $b[2]) end;
  def active($v):
    if   $v[0] > 0 then "CRITICAL"
    elif $v[1] > 0 then "MAJOR"
    elif $v[2] > 0 then "MINOR"
    else                "NONE" end;
  # 악화 = "상위 등급 새로 생김"(rubric). CRITICAL 칸 증가, 또는 CRITICAL 동일+MAJOR 칸 증가.
  # MINOR 만 늘어난 건 악화 아님 — 양성 루프를 불필요하게 사람에게 에스컬레이션하지 않는다.
  def worsened($c; $p): ($c[0] > $p[0]) or ($c[0] == $p[0] and $c[1] > $p[1]);

  if $prev == null then
    { status: "INIT", floor: $cur, cur: $cur, no_progress: 0, regress_streak: 0,
      active_grade: active($cur), threshold: null }
  else
    lexcmp($cur; $prev.floor) as $vsfloor
    | (if $vsfloor < 0 then $cur else $prev.floor end)              as $floor
    | (if $vsfloor < 0 then 0    else ($prev.no_progress + 1) end)  as $np
    | (if worsened($cur; $prev.prev) then ($prev.regress_streak + 1) else 0 end) as $rs
    # 임계 기준은 floor 가 아니라 cur 의 active grade. floor 가 MINOR-only 라도 cur 가 CRITICAL 로
    # 퇴행해 고착되면 STALLED 가 떠야 한다(평탄 퇴행 사각 차단). decide 가 RETRY 내는데 stall 이
    # "정체 아님" 내던 모순도 같이 닫힌다.
    | active($cur) as $ag
    | (if $ag == "CRITICAL" then $thrC elif $ag == "MAJOR" then $thrM else null end) as $thr
    | { floor: $floor, cur: $cur, no_progress: $np, regress_streak: $rs,
        active_grade: $ag, threshold: $thr }
    | .status = (
        if   ($rs >= $regN)                       then "REGRESS_ESCALATE"
        elif ($thr != null and $np >= $thr)       then "STALLED"
        elif ($vsfloor < 0)                       then "PROGRESS"
        elif ($thr == null)                       then "NO_STALL_MINOR"
        else                                           "ONGOING"
        end )
  end
')"

# 다음 사이클을 위해 prev(=이번 cur), floor, no_progress, regress_streak 을 영속.
echo "$result" | jq '{ status, floor, cur, prev: .cur, no_progress, regress_streak, active_grade, threshold }' > "$state_file"
echo "$result"
