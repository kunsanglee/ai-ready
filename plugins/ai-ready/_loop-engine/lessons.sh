#!/usr/bin/env bash
# 루프 종료 후 history.jsonl 을 diff 해 "출처 1" 실수를 결정론으로 추출한다.
#
# 실수 한 건 = 어느 사이클엔 떴다가 **마지막(통과) 사이클엔 없는** finding.
#   = checker 가 잡았고 maker 가 실제로 고친 것. 새 수집 장치 없이 사이클 로그 diff 로 뽑는다.
# 마지막 사이클에 남은 finding 은 "받아들여진 것"이라 실수로 안 친다(통과 시점 MINOR 등).
#
# Usage:
#   lessons.sh --history .loop/run/{ticket}/history.jsonl
#   lessons.sh .loop/run/{ticket}/history.jsonl
#
# 입력(JSONL): 한 줄 = 한 사이클. 오케스트레이터가 사이클마다 append.
#   { "iteration": N, "verdict": "...", "findings": [ <score.sh 출력 원소>, ... ] }
#   findings 원소는 score.sh 가 채점한 것: 최소 (kind, dimension, location, severity, evidence).
#
# 출력(JSON, stdout): 출처1 실수 목록 (severity 내림차순).
#   { "source": "loop-cycle-diff", "total_cycles": n,
#     "final_verdict": "PASS"|...|null,   # 마지막 사이클 verdict
#     "baseline_passed": true|false,      # 마지막이 PASS 면 기준선이 깨끗(수용). 아니면 미해결 잔존이라
#                                         #   "사라짐=고쳐짐" 추론을 사람이 주의해서 봐야 한다는 신호.
#     "count": n,
#     "mistakes": [ { kind, dimension, location, max_severity,
#                     first_seen_iteration, last_seen_iteration, persisted_cycles,
#                     evidence_sample } ] }
#
# 이 출력은 .loop/run/{ticket}/ 휘발성. loop-lesson-synthesizer 에이전트가
# 출처2(전자=사람 대화 / 후자=PR 코멘트)와 묶어 ANTIPATTERNS 후보 초안을 만든다(사람 승인 필수).
# 영구 중간 레지스트리(옛 docs/loop/lessons/)는 없다 — 영구 지식층은 ANTIPATTERNS 하나.

set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

history_file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --history) history_file="$2"; shift 2;;
    *) history_file="$1"; shift;;
  esac
done
[ -n "$history_file" ] || { echo "lessons: --history <file> 필요" >&2; exit 64; }
[ -f "$history_file" ] || { echo "lessons: history 없음: $history_file" >&2; exit 66; }

# jq -s 로 JSONL 전체를 배열로 슬럽. 마지막 사이클을 기준으로 "고쳐졌나"를 본다.
# (kind+location) 를 키로 묶어, 그 키가 마지막 사이클 키 집합에 없으면 고쳐진 실수.
jq -s '
  def levels: ["_","MINOR","MAJOR","CRITICAL","BLOCKER"];
  def rank($s): {"MINOR":1,"MAJOR":2,"CRITICAL":3,"BLOCKER":4}[$s] // 0;
  # 식별 키는 파일+kind. location 의 끝 라인번호(:88)를 뗀다 — 같은 결함이 무관한 편집으로
  # 라인만 밀려도(:88→:90) "사라짐=고쳐짐"으로 오보되지 않게. (라인까지 키에 넣던 게 버그였다.)
  def fkey: .kind + "@" + ((.location // "") | sub(":[0-9]+$"; ""));

  (length) as $n
  | (if $n == 0 then null else .[$n-1] end) as $last
  | (($last.findings) // []) as $final
  | (($last.verdict) // null) as $final_verdict
  | ([ $final[] | fkey ]) as $finalKeys
  | [ .[] | .iteration as $it | (.findings // [])[]
        | { kind, dimension, location, severity, evidence,
            iteration: $it, key: fkey } ]
  | group_by(.key)
  | map(
      # 키가 마지막 사이클에 없으면(= [key] - finalKeys 가 비지 않으면) 고쳐진 실수.
      select( ([ .[0].key ] - $finalKeys | length) > 0 )
      | ([ .[].severity ] | map(rank(.)) | max) as $maxr
      | {
          kind:                 .[0].kind,
          dimension:            .[0].dimension,
          location:             .[0].location,
          max_severity:         levels[$maxr],
          first_seen_iteration: ([ .[].iteration ] | min),
          last_seen_iteration:  ([ .[].iteration ] | max),
          persisted_cycles:     ([ .[].iteration ] | unique | length),
          evidence_sample:      ([ .[].evidence ] | last)
        }
    )
  | sort_by(rank(.max_severity)) | reverse
  | { source: "loop-cycle-diff", total_cycles: $n,
      final_verdict: $final_verdict,
      baseline_passed: ($final_verdict == "PASS"),
      count: length, mistakes: . }
' "$history_file"
