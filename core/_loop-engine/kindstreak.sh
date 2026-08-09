#!/usr/bin/env bash
# 반복 종류 감지: 같은 **종류**의 finding 이 사이클을 연속으로 지배하고 있는지 본다.
# Usage:
#   kindstreak.sh --history .loop/run/{ticket}/history.jsonl
#   kindstreak.sh .loop/run/{ticket}/history-{phase}.jsonl
#
# 입력(JSONL): lessons.sh 와 같은 사이클 이력. 한 줄 = 한 사이클, 오케스트레이터가 사이클마다 append.
#   { "iteration": N, "verdict": "...", "findings": [ <score.sh 출력 원소>, ... ] }
#   각 finding 에 severity·kind 가 있다(score.sh 가 붙인 값).
#
# 출력(JSON, stdout):
#   { "status": "OK"|"REPEATED_KIND",
#     "kind": <문자열|null>,   # 연속을 이루는 종류. 연속이 0 이면 null
#     "streak": n,             # 마지막 사이클부터 그 종류가 연속으로 지배한 사이클 수
#     "threshold": n,          # rubric PARAMS repeated_kind_cycles
#     "cycles": n }            # 이력의 총 사이클 수
#
# 규칙:
#   - 한 사이클의 **지배 종류** = 그 사이클에 있는 가장 높은 등급(BLOCKER > CRITICAL > MAJOR)의
#     finding 들 중 최빈 kind.
#   - **MINOR 만 있는 사이클은 지배 종류가 없다** — 게이트를 통과시키는 등급이라 세지 않는다.
#     연속을 끊지도 잇지도 않고 건너뛴다.
#   - 최빈이 동점이면 그 사이클도 지배 종류가 없고, 이때는 연속이 **끊긴다**
#     (같은 종류가 계속이라는 근거가 아니므로).
#   - finding 이 하나도 없는 사이클도 지배 종류가 없고 연속이 끊긴다.
#   - 마지막 사이클부터 거슬러 같은 종류가 연속 지배한 횟수를 세고, 임계 이상이면 REPEATED_KIND.
#
# **MINOR 건너뛰기와 severity 가 사다리 밖인 것은 다른 일이다.** 앞은 규칙이고 뒤는 입력이 깨진 것이다.
# 둘을 같은 길로 보내면 등급 오타 하나(`CRITCAL`)에 그 사이클이 통째로 안 보이고, 같은 종류가 네
# 사이클 연속인 이력이 `streak: 0` 으로 나오면서 **감지기가 눈이 먼 채 통과를 낸다**(실측). 그래서
# 사다리(MINOR·MAJOR·CRITICAL·BLOCKER) 밖 값과 누락은 건너뛰지 않고 exit 65 로 거부한다 —
# 확인 못 한 것이 통과 방향으로 떨어지지 않게 하는 것이 이 감지기의 존재 이유와 같은 규율이다.
#
# 왜 stall.sh 와 따로 있나. stall.sh 는 등급 **개수 벡터**만 본다 — finding 의 종류가 안 보인다.
# 그래서 "같은 종류를 매 사이클 다시 잡는다" 가 등급이 오르내리는 동안 PROGRESS 로 읽혔다.
# 이 신호가 뜨면 의심할 곳은 보통 코드가 아니라 **목표** 다: 끝나는 지점이 없는 목표
# ("~하게 만든다")는 하나를 고치면 checker 가 언제나 다음 하나를 더 찾아 수렴하지 않는다.
#
# 종료코드: 0 정상 / 64 인자 오류 / 65 이력 입력·설정 오류(사람 대기).
# 이력을 못 읽을 때 조용히 OK 를 내지 않는 것이 핵심이다 — 그러면 감지기가 영영 안 울리는데
# 그 침묵이 통과처럼 보인다(stall.sh 의 빈 입력 처리와 같은 결).

set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

history_file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --history)
      [ $# -ge 2 ] || { echo "kindstreak: --history 에 <file> 인자 필요" >&2; exit 64; }
      history_file="$2"; shift 2;;
    *) history_file="$1"; shift;;
  esac
done
[ -n "$history_file" ] || { echo "kindstreak: --history <file> 필요" >&2; exit 64; }
[ -f "$history_file" ] && [ -r "$history_file" ] \
  || { echo "kindstreak: history 를 읽을 수 없다: $history_file (사람 대기 — 조용한 OK 금지)" >&2; exit 65; }

threshold="$(loop_param repeated_kind_cycles)"
# 임계가 정수가 아니면 rubric 설정 오류다. 아래 jq 에 그대로 넘기면 파싱 오류가 나는데, 그러면
# "이력이 깨졌다" 는 엉뚱한 메시지로 보고된다 — 원인을 여기서 가른다(score.sh 의 rubric 검증과 같은 결).
case "$threshold" in
  '' | *[!0-9]*)
    echo "kindstreak: rubric PARAMS 의 repeated_kind_cycles 가 정수가 아니다: '$threshold'" >&2; exit 65;;
esac

# 줄 하나라도 JSON 이 아니면 거부한다. 깨진 줄을 건너뛰면 그 사이클이 없던 것이 되어 연속이
# 조용히 끊기고, 감지기가 안 울리는 쪽으로 틀린다. 빈 파일(0줄)은 오류가 아니다 — jq -s 가 [] 를 낸다.
# 이 첫 통과가 파싱과 severity 어휘를 함께 본다. 아래 판정 통과는 검증된 입력만 받는다.
if ! bad_sev="$(jq -s -r '
  ["MINOR","MAJOR","CRITICAL","BLOCKER"] as $ladder
  | [ to_entries[]
      | (.value.iteration // (.key + 1)) as $it
      | (.value.findings // [])[]
      # 누락(null)도 [null] - $ladder 가 비지 않아 함께 걸린다.
      | select(([.severity] - $ladder) | length > 0)
      | "사이클 \($it) kind=\(.kind // "-") severity=\(.severity | tostring)" ]
    | unique | .[0:3] | join(" / ")' "$history_file" 2>/dev/null)"; then
  echo "kindstreak: history 를 사이클 JSON 으로 못 읽는다: $history_file (한 줄 = 한 사이클 — 사람 대기)" >&2
  exit 65
fi
# severity 는 score.sh 가 붙이는 값이라 사다리 밖이면 이력이 깨진 것이다. 건너뛰면 그 사이클이
# 안 보이고 연속이 0 으로 나오는데, 그 침묵이 통과로 읽힌다 — MINOR 건너뛰기(규칙)와는 다른 길로 보낸다.
if [ -n "$bad_sev" ]; then
  echo "kindstreak: finding 의 severity 가 사다리(MINOR·MAJOR·CRITICAL·BLOCKER) 밖이다 — $bad_sev" >&2
  echo "            ($history_file 의 그 줄을 확인할 것. 건너뛰면 감지기가 눈이 먼 채 OK 를 낸다 — 사람 대기)" >&2
  exit 65
fi

if ! result="$(jq -s --argjson thr "$threshold" '
  def rank($s): {"MINOR":1, "MAJOR":2, "CRITICAL":3, "BLOCKER":4}[$s] // 0;

  # 한 사이클 → {v:"kind", k:<종류>} | {v:"skip"}(연속에 영향 없음) | {v:"break"}(연속 끊김)
  def dominant:
    (.findings // []) as $all
    # MAJOR 이상만 센다. MINOR 는 게이트를 통과시키는 등급이라 "지배" 의 근거가 못 된다.
    | [ $all[] | select(rank(.severity) >= 2) ] as $high
    | if ($high | length) == 0 then
        (if ($all | length) == 0 then {v: "break"} else {v: "skip"} end)
      else
        ([ $high[] | rank(.severity) ] | max) as $top
        | ([ $high[] | select(rank(.severity) == $top) | (.kind // "") ]
           | group_by(.) | map({k: .[0], n: length})) as $tally
        | ($tally | map(.n) | max) as $best
        | ($tally | map(select(.n == $best))) as $winners
        | if ($winners | length) == 1 then {v: "kind", k: $winners[0].k} else {v: "break"} end
      end;

  (length) as $cycles
  # 마지막 사이클부터 거슬러 본다.
  | (map(dominant) | reverse) as $seq
  | ([ $seq[] | select(.v != "skip") ] | first // null) as $head
  | (if ($head == null) or ($head.v != "kind") then { kind: null, streak: 0 }
     else
       ($head.k) as $kk
       | (reduce $seq[] as $c ({ stop: false, n: 0 };
            if   .stop                                then .
            elif $c.v == "skip"                       then .
            elif ($c.v == "kind") and ($c.k == $kk)   then (.n += 1)
            else (.stop = true) end)) as $r
       | { kind: $kk, streak: $r.n }
     end)
  | . + { threshold: $thr, cycles: $cycles }
  | .status = (if .streak >= $thr then "REPEATED_KIND" else "OK" end)
  | { status, kind, streak, threshold, cycles }
' "$history_file" 2>/dev/null)"; then
  echo "kindstreak: history 를 사이클 JSON 으로 못 읽는다: $history_file (한 줄 = 한 사이클 — 사람 대기)" >&2
  exit 65
fi

echo "$result"
