#!/usr/bin/env bash
# ai-ready:apply 자동 생성 — 고치면 이 줄을 남겨 둬도 ai-ready 가 덮어쓰지 않는다. 다시 만들려면 파일을 지우고 apply 를 돌린다.
#
# 이 저장소의 확인 명령을 차례로 돌린다. 하나라도 실패하면 그 명령의 출력 마지막 20줄만 보여 주고 멈춘다.
# 작업 트리(HEAD + 커밋 안 한 변경 + 추적 안 하는 파일)가 마지막으로 통과했을 때와 같으면 다시 돌리지 않는다.
# 이 지문에는 gitignore 된 파일(.env 등)·환경변수·도구 버전이 들어가지 않는다. 그것만 바꿨으면 지문을 지우고 돌린다:
#   rm "$(git rev-parse --git-path verify-pass)"
# 실패한 작업 트리의 지문(verify-fail)과 그 지문으로 막은 횟수(verify-blocks)는 세션마다가 아니라 작업 트리에
# 하나라, 같은 작업 트리의 세션들이 함께 센다. 확인 명령이 실패하면 통과 기록(verify-pass)을 지운다 — Stop hook
# 설치기는 이 기록을 "지금 통과하는 상태" 의 근거로 쓴다.
#
#   scripts/verify.sh              사람·CI·에이전트가 직접 부를 때. 늘 확인 명령을 돌리고, 실패하면 exit 1
#   scripts/verify.sh --stop-hook  Claude Code Stop hook 으로 부를 때. 실패하면 exit 2 로 턴을 막는다.
#                                  같은 작업 트리로 3번 막았으면 그 뒤로는 확인 명령을 다시 돌리지 않고 통과시킨다
#                                  (끝없이 막히지 않게). 작업 트리가 바뀌면 다시 센다.
set -uo pipefail

# 확인 명령. 싼 것부터 둔다 — 앞에서 실패하면 뒤는 돌리지 않는다.
CHECKS=(
__CHECKS__
)
MAX_BLOCKS=3
TAIL_LINES=20

mode="${1:-}"
# 루트는 부른 곳이 아니라 이 스크립트가 있는 저장소로 정한다. 다른 저장소 안에서 불러도 엉뚱한 곳을 검사하지 않는다.
root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null)" || root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root" || exit 1

if [ "${#CHECKS[@]}" -eq 0 ]; then
  echo "verify: CHECKS 가 비어 있다 — scripts/verify.sh 에 확인 명령을 적는다" >&2
  exit 1
fi

hash_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi | cut -d' ' -f1
}

# 작업 트리의 지문. git 저장소가 아니거나 커밋이 없으면 비워 둔다(그때는 캐시 없이 매번 돌린다).
tree_key() {
  local head
  head="$(git rev-parse --verify -q HEAD 2>/dev/null)" || return 1
  {
    printf '%s\n' "$head" "${CHECKS[@]}"
    git diff HEAD --binary
    git ls-files --others --exclude-standard -z | while IFS= read -r -d '' f; do
      printf '%s\0' "$f"
      cat -- "$f" 2>/dev/null
      printf '\0'
    done
  } | hash_stdin
}

state_file() {
  # 워크트리에서도 맞는 자리를 쓰도록 --git-path 로 묻는다. git 밖이면 임시 폴더에 둔다.
  git rev-parse --git-path "$1" 2>/dev/null && return 0
  printf '%s/%s-%s\n' "${TMPDIR:-/tmp}" "$1" "$(printf '%s' "$root" | hash_stdin)"
}

run_checks() {
  local out cmd
  out="$(mktemp)"
  for cmd in "${CHECKS[@]}"; do
    if ! bash -c "$cmd" </dev/null >"$out" 2>&1; then
      echo "verify: 실패 — $cmd (출력 마지막 ${TAIL_LINES}줄)"
      tail -n "$TAIL_LINES" "$out"
      rm -f "$out"
      return 1
    fi
  done
  rm -f "$out"
  return 0
}

pass_file="$(state_file verify-pass)"
fail_file="$(state_file verify-fail)"
blocks_file="$(state_file verify-blocks)"
key="$(tree_key 2>/dev/null)" || key=""

read_blocks() {
  local n
  n="$(cat "$blocks_file" 2>/dev/null || echo 0)"
  case "$n" in '' | *[!0-9]*) n=0 ;; esac
  printf '%s\n' "$n"
}

if [ -n "$key" ] && [ "$(cat "$pass_file" 2>/dev/null)" = "$key" ]; then
  rm -f "$fail_file" "$blocks_file"
  [ "$mode" = "--stop-hook" ] || echo "verify: 마지막 통과 이후 바뀐 것이 없다"
  exit 0
fi

if [ "$mode" = "--stop-hook" ] && [ -n "$key" ] && [ "$(cat "$fail_file" 2>/dev/null)" = "$key" ] \
  && [ "$(read_blocks)" -ge "$MAX_BLOCKS" ]; then
  echo "verify: 이 작업 트리로 이미 ${MAX_BLOCKS}번 막았고 그 뒤로 바뀐 것이 없어 다시 돌리지 않는다. 실패는 남아 있다(scripts/verify.sh 로 확인)." >&2
  exit 0
fi

if report="$(run_checks)"; then
  [ -n "$key" ] && printf '%s\n' "$key" >"$pass_file"
  rm -f "$fail_file" "$blocks_file"
  [ "$mode" = "--stop-hook" ] || echo "verify: 통과"
  exit 0
fi

rm -f "$pass_file"
if [ "$mode" != "--stop-hook" ]; then
  printf '%s\n' "$report" >&2
  exit 1
fi

blocks="$(read_blocks)"
if [ -n "$key" ] && [ "$(cat "$fail_file" 2>/dev/null)" != "$key" ]; then
  blocks=0
fi
# 지문을 만들 수 없으면(커밋이 없거나 git 밖) 트리가 같은지 모르므로, 연속으로 센 횟수만 보고 한 번 통과시킨다.
if [ "$blocks" -ge "$MAX_BLOCKS" ]; then
  rm -f "$blocks_file"
  printf '%s\n' "$report" >&2
  echo "verify: 연속 ${MAX_BLOCKS}번 막았으므로 이번에는 통과시킨다. 위 실패는 아직 남아 있다." >&2
  exit 0
fi
[ -n "$key" ] && printf '%s\n' "$key" >"$fail_file"
printf '%s\n' "$((blocks + 1))" >"$blocks_file"
printf '%s\n' "$report" >&2
echo "verify: 확인 명령이 실패했다. 고친 뒤 끝낸다 (이 작업 트리로 막은 횟수 $((blocks + 1))/${MAX_BLOCKS})." >&2
echo "verify: 이번 변경과 무관한 기존 위반은 고치지 말고 멈춰서 사람에게 보고한다." >&2
exit 2
