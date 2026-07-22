#!/usr/bin/env bash
# assemble.sh — core/ 단일원본을 각 호스트 설치 트리로 조립한다.
#
# ai-ready 는 호스트(Claude·codex)마다 설치 트리가 따로다(각자 manifest·root 로 로드).
# 중립성은 소스+빌드 층에 둔다: core/ 가 단일 진실, 이 스크립트가 각 트리로 복사·렌더한다.
# 설치본은 커밋된다(설치 시 빌드 불필요) — 그래서 core 와 트리 사본의 갈라짐을 drift-test.sh 가 막는다.
#
# 현재 범위: _loop-engine(순수 중립 셸)만 core→양 트리로 조립한다. loop 스킬·에이전트 렌더는 후속 phase.
#
# Usage: build/assemble.sh              # 모든 호스트
#        build/assemble.sh claude       # 특정 호스트만
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 호스트별 엔진 설치 위치. (스폰 문법·모델맵 등 나머지 어댑터 글루는 adapters/<host>/ 로 후속 확장.)
declare -a HOSTS=("claude" "codex")
engine_dest() {
  case "$1" in
    claude) echo "plugins/ai-ready/_loop-engine" ;;
    codex)  echo "codex/plugins/ai-ready/_loop-engine" ;;
    *) echo "assemble: 모르는 호스트 '$1'" >&2; return 2 ;;
  esac
}

targets=("${HOSTS[@]}")
[ $# -gt 0 ] && targets=("$@")

for host in "${targets[@]}"; do
  dest="$(engine_dest "$host")"
  echo "[$host] core/_loop-engine → $dest"
  mkdir -p "$dest"
  # -a 정확 복사, --delete 로 stale 제거, pycache 는 제외(gitignore 대상, 산출물 아님).
  rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' core/_loop-engine/ "$dest/"
done
echo "assemble 완료."
