#!/usr/bin/env bash
# ai-ready:apply 자동 생성 — 고치면 이 줄을 남겨 둬도 ai-ready 가 덮어쓰지 않는다. 다시 만들려면 파일을 지우고 apply 를 돌린다.
#
# 이 저장소의 확인 명령을 차례로 돌린다. 하나라도 실패하면 그 명령의 출력 마지막 20줄만 보여 주고 exit 1 로 멈춘다.
# 작업 트리(HEAD + 커밋 안 한 변경 + 추적 안 하는 파일)가 마지막으로 통과했을 때와 같으면 다시 돌리지 않는다.
# 이 지문에는 gitignore 된 파일(.env 등)·환경변수·도구 버전이 들어가지 않는다. 그것만 바꿨으면 지문을 지우고 돌린다:
#   rm "$(git rev-parse --git-path verify-pass)"
# 확인 명령이 실패하면 통과 기록(verify-pass)을 지운다. pre-push hook 설치기는 이 기록을 "지금 통과하는 상태" 의
# 근거로 쓴다.
#
# 인자를 받지 않는다. 사람·CI·에이전트·git hook 모두 scripts/verify.sh 로 부른다.
set -uo pipefail

# 확인 명령. 싼 것부터 둔다 — 앞에서 실패하면 뒤는 돌리지 않는다.
CHECKS=(
__CHECKS__
)
TAIL_LINES=20

if [ "$#" -gt 0 ]; then
  echo "verify: 인자를 받지 않는다. 쓰는 법: scripts/verify.sh" >&2
  echo 'verify: Claude Code Stop hook 이 --stop-hook 으로 부른 것이면, ai-ready 의 install_verify_hook.py 를 다시 돌려 git pre-push hook 으로 옮긴다(옛 Stop hook 은 그때 지운다).' >&2
  exit 1
fi

# git hook 안에서 불리면 GIT_DIR 이 잡혀 있을 수 있다(연결 워크트리의 pre-push 가 그렇다). 그대로 두면 아래
# `git -C` 가 scripts 폴더를 작업 트리 최상위로 읽는다.
unset GIT_DIR GIT_WORK_TREE
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
key="$(tree_key 2>/dev/null)" || key=""

if [ -n "$key" ] && [ "$(cat "$pass_file" 2>/dev/null)" = "$key" ]; then
  echo "verify: 마지막 통과 이후 바뀐 것이 없다"
  exit 0
fi

if report="$(run_checks)"; then
  [ -n "$key" ] && printf '%s\n' "$key" >"$pass_file"
  echo "verify: 통과"
  exit 0
fi

rm -f "$pass_file"
printf '%s\n' "$report" >&2
exit 1
