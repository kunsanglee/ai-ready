#!/usr/bin/env bash
# ai-ready codex loop 헤드리스 런처 (참고 구현).
#
# loop-profile.env 의 model·effort 로 codex 세션을 띄운다. 모델·effort 를 바꾸려면
# loop-profile.env 한 곳만 고친다 — 스킬도 이 스크립트도 손대지 않는다(균일 프로필).
# 세션 model·effort 는 위임된 maker/checker 하위 에이전트로 상속된다(2026-07-22 실측).
#
# 대화형으로 쓸 땐 이 런처가 필요 없다 — codex 세션에서 고른 model·effort 가 그대로 loop 에 쓰인다.
# 이 런처는 봇·자동화가 loop 를 헤드리스로 돌릴 때의 진입점이다.
#
# Usage:
#   loop-launch.sh "use the ai-ready build skill to build @<spec>"  [extra codex exec args...]
#   loop-launch.sh "use the ai-ready build skill to converge this change to PASS"  -C /path/to/repo
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$DIR/loop-profile.env"

: "${LOOP_MODEL:?loop-profile.env 에 LOOP_MODEL 이 없다}"
: "${LOOP_EFFORT:?loop-profile.env 에 LOOP_EFFORT 이 없다}"

[ $# -ge 1 ] || { echo "loop-launch: 프롬프트 인자가 필요하다 (예: 'use build to build @spec')" >&2; exit 2; }

# codex 는 중립 사다리 등급을 그대로 받는다(core/effort-ladder.md). 첫 인자는 프롬프트, 나머지는 codex exec 로 전달.
prompt="$1"; shift
exec codex exec -m "$LOOP_MODEL" -c "model_reasoning_effort=$LOOP_EFFORT" "$@" "$prompt"
