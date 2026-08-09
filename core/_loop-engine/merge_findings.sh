#!/usr/bin/env bash
# 축별 checker 가 각자 쓴 findings 파일 여러 개를 채점 입력 하나로 합친다.
#
# Usage:
#   merge_findings.sh --expect 3 contract=/path/a.json safety=/path/b.json quality=/path/c.json
#   (stdout 으로 {base, reviewed, findings} 하나를 낸다 — 그대로 score.sh 에 흘린다)
#
# 왜 있나: checker 를 축으로 갈라 병렬로 띄우면 결과가 파일 여러 개로 나온다. `score.sh` 는
# `{findings:[...]}` 하나를 받으므로 그 사이를 잇는 자리가 필요하다.
#
# **개수 검사가 이 셸의 존재 이유다.** 렌즈 하나가 조용히 죽어도 남은 둘의 결과는 형식이 멀쩡해서,
# 세지 않으면 그 축은 한 번도 점검되지 않은 채 PASS 로 간다. 단일 checker 시절의 `[ -s "$F" ]` 가드가
# 병렬에서 대응하는 자리가 여기고, 가드 하나가 파일 하나만 보던 것을 N 개로 넓힌 것이다.
# "확인 못 한 것이 통과 방향으로 떨어지지 않게 한다" 는 이 엔진의 규율을 병렬로 옮긴 것.
#
# exit 65 = 입력 데이터 오류(EX_DATAERR). 오케스트레이터는 이걸 사람 대기 신호로 본다.

set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

expect=""
lenses=""   # 공백 구분 렌즈 이름 (bash 3.2 라 연관 배열을 안 쓴다 — lib.sh 호환 규약)
paths=""

while [ $# -gt 0 ]; do
  case "$1" in
    --expect) expect="${2:-}"; shift 2 ;;
    --expect=*) expect="${1#--expect=}"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *)
      case "$1" in
        *=*) : ;;
        *) echo "merge_findings: 인자는 '렌즈이름=경로' 형식이어야 한다: $1" >&2; exit 64 ;;
      esac
      lens_name="${1%%=*}"; lens_path="${1#*=}"
      if [ -z "$lens_name" ] || [ -z "$lens_path" ]; then
        echo "merge_findings: 렌즈 이름과 경로가 모두 필요하다: $1" >&2; exit 64
      fi
      lenses="$lenses $lens_name"; paths="$paths $lens_path"
      shift ;;
  esac
done

# shellcheck disable=SC2086
set -- $paths
given=$#

if [ -z "$expect" ]; then
  echo "merge_findings: --expect N 이 필요하다 (몇 개의 렌즈가 쓸 예정이었나)." >&2
  echo "                이 값이 없으면 렌즈가 죽어도 남은 결과가 멀쩡해 보여 점검 없이 통과한다." >&2
  exit 64
fi
case "$expect" in
  ''|*[!0-9]*) echo "merge_findings: --expect 는 정수여야 한다: $expect" >&2; exit 64 ;;
esac

# 기대한 만큼의 렌즈 결과가 실제로 왔나 — 이 셸의 핵심 게이트.
if [ "$given" -ne "$expect" ]; then
  echo "merge_findings: 렌즈 결과가 $expect 개여야 하는데 $given 개 왔다 — 축 하나가 죽었을 수 있다." >&2
  echo "                남은 결과만으로 채점하지 않는다. 못 돈 축은 점검된 적이 없고, 그걸 통과로 읽으면" >&2
  echo "                그 차원의 결함이 영영 안 잡힌다. 멈추고 사람 호출." >&2
  exit 65
fi

# 파일마다 존재·비어있지 않음·형식을 따로 본다. 어느 렌즈가 문제인지 이름으로 말해야
# 사람이 그 축만 다시 돌릴 수 있다 — "입력 오류" 한 줄이면 셋을 다 뒤지게 된다.
i=0
for lens in $lenses; do
  i=$((i + 1))
  p="$(eval "echo \${$i}")"
  if [ ! -s "$p" ]; then
    echo "merge_findings: 렌즈 '$lens' 의 결과 파일이 비었거나 없다 ($p) — 그 축 checker 실패. 멈추고 사람 호출." >&2
    exit 65
  fi
  loop_validate_json "$(cat "$p")" \
    'type=="object" and has("findings") and (.findings|type=="array")' \
    "merge_findings: 렌즈 '$lens' 의 결과가 {\"findings\":[...]} 객체가 아니다 ($p) — 그 축 checker 출력 계약 위반"
done

# 렌즈들이 서로 다른 비교 베이스를 봤으면 판정이 어긋난다 — 한 축은 origin/main, 다른 축은
# 엉뚱한 ref 를 본 diff 를 합쳐 놓고 하나의 verdict 를 내면 그 verdict 가 무엇에 대한 것인지 없다.
# **판정은 jq 로, 종료는 셸로 한다.** jq 의 `error` 로 죽이면 종료코드가 5 라, 오케스트레이터가
# 사람 대기 신호로 아는 65 와 달라져 "입력 오류" 분기가 안 탄다(실측).
# shellcheck disable=SC2086
bases="$(jq -s -r '[ .[] | .base // empty ] | map(select(. != "")) | unique | join(", ")' "$@")"
case "$bases" in
  *", "*)
    echo "merge_findings: 렌즈마다 비교 베이스가 다르다 ($bases) — 같은 base 를 프롬프트로 넘겼는지 확인." >&2
    echo "                서로 다른 diff 를 본 결과를 합쳐 하나의 verdict 를 내면 그 판정이 무엇에 대한 것인지 없다." >&2
    exit 65 ;;
esac

# shellcheck disable=SC2086
jq -s --argjson lenses "$(printf '%s\n' $lenses | jq -R . | jq -s .)" '
  def norm: if type=="array" then . else [] end;
  # score.sh 와 같은 판정을 쓴다 — 거짓이라고 분명히 말한 값만 거짓. 오타는 사람을 부르는 쪽으로.
  def truthy: . != false and . != null and . != "false" and . != "no" and . != "";

  ([ .[] | .base // empty ] | map(select(. != "")) | unique) as $bases
  # id 는 렌즈 안에서만 고유하다("c1" 을 두 렌즈가 낼 수 있다). 접두를 붙여 전역 고유로 만든다 —
  # 안 붙이면 반복 표시(kind@location 집계)와 maker 지시가 서로 다른 finding 을 같은 이름으로 가리킨다.
  | [ to_entries[] | .key as $i | ($lenses[$i]) as $lens
      | (.value.findings | norm)[]
      | . + { id: ($lens + "-" + ((.id // "x") | tostring)), lens: $lens } ] as $all

  | ([ .[] | (.reviewed | norm) ] | add // [] | unique) as $reviewed

  # 같은 (차원·종류·위치)를 두 렌즈가 냈으면 하나로 접는다. 축이 갈려 있어 드물지만, 렌즈가 자기
  # 축 밖 차원을 내면 생긴다. 접을 때 가중은 합집합, 사람 대기는 OR — 어느 방향으로도 조용히
  # 약해지지 않게 보수적으로 합친다. 차원이 다르면 접지 않는다(checker 계약이 차원별 별도 finding 이다).
  | ($all | group_by([.dimension // "", .kind // "", .location // ""])
          | map(.[0] + {
              weights: ([ .[] | (.weights | norm) ] | add // [] | unique),
              force_await: ([ .[] | .force_await | truthy ] | any),
              evidence: (if (length > 1)
                         then ((.[0].evidence // "") + " [같은 자리를 렌즈 " + ([.[].lens] | unique | join("+")) + " 가 중복 보고 — 병합]")
                         else (.[0].evidence // "") end)
            })) as $findings

  | { base: ($bases[0] // "unknown"), reviewed: $reviewed, findings: $findings }
' "$@"
