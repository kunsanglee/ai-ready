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
# **배열로 모은다.** 공백으로 이어 붙인 뒤 단어 분할로 되돌리면 경로에 공백이 있을 때 한 인자가
# 둘로 쪼개져 개수 검사가 엉뚱하게 어긋난다(macOS 에서 `~/My Projects/repo` 는 흔하다 — 실측으로
# exit 65 를 냈다). bash 3.2 가 막는 것은 **연관** 배열(declare -A)이고 일반 배열은 쓴다.
lenses=()
paths=()

while [ $# -gt 0 ]; do
  case "$1" in
    --expect) expect="${2:-}"; shift 2 ;;
    --expect=*) expect="${1#--expect=}"; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *)
      case "$1" in
        *=*) : ;;
        *) echo "merge_findings: 인자는 '렌즈이름=경로' 형식이어야 한다: $1" >&2; exit 64 ;;
      esac
      # 경로 쪽에 `=` 가 더 있어도 안전하다 — 이름은 첫 `=` 앞까지, 경로는 첫 `=` 뒤 전부.
      lens_name="${1%%=*}"; lens_path="${1#*=}"
      if [ -z "$lens_name" ] || [ -z "$lens_path" ]; then
        echo "merge_findings: 렌즈 이름과 경로가 모두 필요하다: $1" >&2; exit 64
      fi
      lenses+=("$lens_name"); paths+=("$lens_path")
      shift ;;
  esac
done

given=${#paths[@]}

if [ -z "$expect" ]; then
  echo "merge_findings: --expect N 이 필요하다 (몇 개의 렌즈가 쓸 예정이었나)." >&2
  echo "                이 값이 없으면 렌즈가 죽어도 남은 결과가 멀쩡해 보여 점검 없이 통과한다." >&2
  exit 64
fi
case "$expect" in
  ''|*[!0-9]*) echo "merge_findings: --expect 는 정수여야 한다: $expect" >&2; exit 64 ;;
esac
# 0 개를 기대하는 병합은 없다. 통과시키면 jq 가 파일 인자 없이 떠 stdin 을 기다리며 멈춘다.
if [ "$expect" -eq 0 ]; then
  echo "merge_findings: --expect 0 은 받지 않는다 — 합칠 렌즈가 없으면 채점할 것도 없다." >&2; exit 64
fi

# 기대한 만큼의 렌즈 결과가 실제로 왔나 — 이 셸의 핵심 게이트.
if [ "$given" -ne "$expect" ]; then
  echo "merge_findings: 렌즈 결과가 $expect 개여야 하는데 $given 개 왔다 — 축 하나가 죽었을 수 있다." >&2
  echo "                남은 결과만으로 채점하지 않는다. 못 돈 축은 점검된 적이 없고, 그걸 통과로 읽으면" >&2
  echo "                그 차원의 결함이 영영 안 잡힌다. 멈추고 사람 호출." >&2
  exit 65
fi

# 렌즈 이름과 경로는 각각 서로 달라야 한다. 개수 게이트는 **명령줄 인자 수**만 세므로, 두 렌즈
# 프롬프트에 같은 출력 경로가 들어가 나중 렌즈가 앞 파일을 덮어써도 3개로 세어 통과한다(실측).
# 그때 병합은 group_by 로 접어 멀쩡한 payload 를 내고, 흔적은 evidence 뒤 중복 문구뿐이다.
dupe_path="$(printf '%s\n' "${paths[@]}" | sort | uniq -d | head -1)"
if [ -n "$dupe_path" ]; then
  echo "merge_findings: 둘 이상의 렌즈가 같은 결과 파일을 가리킨다 ($dupe_path)." >&2
  echo "                나중 렌즈가 앞의 것을 덮어써 한 축이 통째로 사라져도 개수는 맞는다. 경로를 렌즈마다 따로 준다." >&2
  exit 65
fi
dupe_lens="$(printf '%s\n' "${lenses[@]}" | sort | uniq -d | head -1)"
if [ -n "$dupe_lens" ]; then
  echo "merge_findings: 렌즈 이름이 겹친다 ($dupe_lens) — id 접두가 겹쳐 전역 고유성이 깨진다." >&2
  exit 65
fi

# 파일마다 존재·비어있지 않음·형식을 따로 본다. 어느 렌즈가 문제인지 이름으로 말해야
# 사람이 그 축만 다시 돌릴 수 있다 — "입력 오류" 한 줄이면 셋을 다 뒤지게 된다.
i=0
while [ "$i" -lt "$given" ]; do
  lens="${lenses[$i]}"; p="${paths[$i]}"
  i=$((i + 1))
  if [ ! -s "$p" ]; then
    echo "merge_findings: 렌즈 '$lens' 의 결과 파일이 비었거나 없다 ($p) — 그 축 checker 실패. 멈추고 사람 호출." >&2
    exit 65
  fi
  payload="$(cat "$p")"
  # `base` 를 함께 요구한다. 아래 병합의 베이스 불일치 검사는 `.base // empty` 로 값을 모으므로,
  # 키를 아예 빼면 그 렌즈가 비교에서 조용히 빠진다 — 다른 ref 를 본 렌즈가 base 를 안 적기만
  # 하면 그 검사가 정확히 그 경우에만 무력해진다(실측).
  loop_validate_json "$payload" \
    'type=="object" and has("base") and has("findings") and (.findings|type=="array")' \
    "merge_findings: 렌즈 '$lens' 의 결과가 {\"base\":..., \"findings\":[...]} 객체가 아니다 ($p) — 그 축 checker 출력 계약 위반"
  # **눈먼 렌즈를 여기서 잡는다.** `score.sh` 의 "findings 도 reviewed 도 비면 거부" 가드는
  # 병합된 payload 하나를 보는데, 병합이 reviewed 를 합집합으로 접으므로 **한 렌즈만 채우면**
  # 그 가드가 만족된다. 그러면 나머지 축은 한 번도 안 봤는데 PASS 가 난다(실측: 단일 checker
  # 계약으로 같은 payload 를 직결하면 exit 65 인데 병렬 경로만 통과했다). 축마다 따로 물어야
  # 그 구멍이 닫힌다 — 병렬화가 만든 구멍이라 병렬 쪽에서 막는다.
  loop_validate_json "$payload" \
    '((.findings|length) > 0) or ((.reviewed|type=="array") and ((.reviewed|length) > 0))' \
    "merge_findings: 렌즈 '$lens' 가 아무것도 못 찾았는데 무엇을 봤는지도 안 적었다 ($p) — 깨끗함과 안 봄이 구분되지 않는다. 그 축 checker 가 reviewed 에 검토한 파일을 담아야 한다"
done

jq -s --argjson lenses "$(printf '%s\n' "${lenses[@]}" | jq -R . | jq -s .)" '
  def norm: if type=="array" then . else [] end;
  # score.sh 와 같은 판정을 쓴다 — 거짓이라고 분명히 말한 값만 거짓. 오타는 사람을 부르는 쪽으로.
  def truthy: . != false and . != null and . != "false" and . != "no" and . != "";

  ([ .[] | .base // empty ] | map(select(. != "")) | unique) as $bases
  # 렌즈들이 서로 다른 비교 베이스를 봤으면 판정이 어긋난다 — 한 축은 origin/main, 다른 축은
  # 엉뚱한 ref 를 본 diff 를 합쳐 놓고 하나의 verdict 를 내면 그 판정이 무엇에 대한 것인지 없다.
  # `error` 가 아니라 `halt_error(65)` 다 — 전자는 종료코드 5 라 오케스트레이터가 사람 대기
  # 신호로 아는 65 와 달라져 "입력 오류" 분기가 안 탄다.
  | (if ($bases | length) > 1
     then ("merge_findings: 렌즈마다 비교 베이스가 다르다 (\($bases | join(", "))) — 같은 base 를 프롬프트로 넘겼는지 확인.\n                서로 다른 diff 를 본 결과를 합쳐 하나의 verdict 를 내면 그 판정이 무엇에 대한 것인지 없다.\n" | halt_error(65))
     else . end)
  # id 는 렌즈 안에서만 고유하다("c1" 을 두 렌즈가 낼 수 있다). 접두를 붙여 전역 고유로 만든다 —
  # 안 붙이면 반복 표시(kind@location 집계)와 maker 지시가 서로 다른 finding 을 같은 이름으로 가리킨다.
  | [ to_entries[] | .key as $i | ($lenses[$i]) as $lens
      | (.value.findings | norm)[]
      | . + { id: ($lens + "-" + ((.id // "x") | tostring)), lens: $lens } ] as $all

  | ([ .[] | (.reviewed | norm) ] | add // [] | unique) as $reviewed

  # 같은 (차원·종류·위치)를 두 렌즈가 냈으면 하나로 접는다. 축이 갈려 있어 드물지만, 렌즈가 자기
  # 축 밖 차원을 내면 생긴다. 접을 때 가중은 합집합, 사람 대기는 OR — 어느 방향으로도 조용히
  # 약해지지 않게 보수적으로 합친다. 차원이 다르면 접지 않는다(checker 계약이 차원별 별도 finding 이다).
  #
  # `in_scope` 는 세 상태를 그대로 유지한다: true(이번 phase 가 보기로 한 표면) / false(안 보기로
  # 한 표면) / null(렌즈가 표시를 안 달았음). **`truthy` 로 접으면 안 된다** — 그러면 안 단 것이
  # false 로 떨어져 "아무도 안 쟀다" 가 "범위 밖이다" 로 둔갑하고, 이 필드를 넣은 목적인 계측이
  # 거짓 수치를 낸다. 접는 방향은 true 우선이다: 한 렌즈가 범위 안이라 보면 범위 안으로 남긴다.
  # 지금 이 값은 등급을 바꾸지 않지만(집계 전용), 나중에 강등을 얹더라도 false 쪽이 내리는
  # 방향이라 true 우선이 보수적이다.
  | ($all | group_by([.dimension // "", .kind // "", .location // ""])
          | map(.[0] + {
              weights: ([ .[] | (.weights | norm) ] | add // [] | unique),
              force_await: ([ .[] | .force_await | truthy ] | any),
              in_scope: (if   any(.[]; .in_scope == true)  then true
                         elif any(.[]; .in_scope == false) then false
                         else null end),
              evidence: (if (length > 1)
                         then ((.[0].evidence // "") + " [같은 자리를 렌즈 " + ([.[].lens] | unique | join("+")) + " 가 중복 보고 — 병합]")
                         else (.[0].evidence // "") end)
            })) as $findings

  | { base: ($bases[0] // "unknown"), reviewed: $reviewed, findings: $findings }
' "${paths[@]}"
