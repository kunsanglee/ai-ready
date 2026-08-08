#!/usr/bin/env bash
# drift-test.sh — 각 호스트 설치 트리의 _loop-engine 이 core/_loop-engine 과 바이트 동일한지 검사한다.
#
# core 가 단일 진실이고 설치 트리는 커밋된 사본이므로, 사본이 손으로 갈라지면(한쪽만 고침)
# 결정론 판정이 호스트마다 달라진다. 이 테스트가 그 갈라짐을 CI/커밋 전에 fail-loud 로 막는다.
# (D5 "엔진 공유: core 원본 + 빌드 복사 + 드리프트 테스트".)
#
# exit 0 = 동일, exit 1 = 드리프트 발견(어느 호스트·어느 파일인지 출력).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

declare -a CHECKS=(
  "claude:plugins/ai-ready/_loop-engine"
  "codex:codex/plugins/ai-ready/_loop-engine"
)

fail=0
for entry in "${CHECKS[@]}"; do
  host="${entry%%:*}"; dest="${entry#*:}"
  if [ ! -d "$dest" ]; then
    echo "[$host] 스킵 — 설치 트리 없음($dest). (아직 조립 안 됨)"
    continue
  fi
  if diff -rq --exclude='__pycache__' --exclude='*.pyc' core/_loop-engine "$dest" >/tmp/drift.$$.txt 2>&1; then
    echo "[$host] OK — core 와 바이트 동일"
  else
    echo "[$host] DRIFT 발견 — core/_loop-engine 과 $dest 가 다르다:"
    sed 's/^/    /' /tmp/drift.$$.txt
    fail=1
  fi
  rm -f /tmp/drift.$$.txt
done

[ "$fail" -eq 0 ] || { echo "드리프트 테스트 실패 — core 에서 고치고 build/assemble.sh 로 재조립하라." >&2; exit 1; }

# --- 버전 드리프트: 매니페스트 셋이 같은 릴리스를 가리키나 ---
# 릴리스마다 손으로 세 곳을 올려야 해서 실제로 갈라졌다 — 0.9.6 은 claude plugin.json 만 올라가고
# marketplace.json(둘) 과 codex plugin.json 은 0.9.5 에 남았다. 설치본이 어느 버전인지 읽는 곳이
# 서로 다른 답을 하면 "무엇이 깔려 있나" 를 아무도 결정론으로 답할 수 없다.
# codex 는 `<버전>+codex.N` 형태라 빌드 메타(+ 뒤)를 떼고 비교한다.
ver_claude="$(jq -r '.version' plugins/ai-ready/.claude-plugin/plugin.json)"
ver_codex="$(jq -r '.version' codex/plugins/ai-ready/.codex-plugin/plugin.json | sed 's/+.*//')"
ver_mkt_meta="$(jq -r '.metadata.version' .claude-plugin/marketplace.json)"
ver_mkt_plugin="$(jq -r '.plugins[0].version' .claude-plugin/marketplace.json)"
if [ "$ver_claude" = "$ver_codex" ] && [ "$ver_claude" = "$ver_mkt_meta" ] && [ "$ver_claude" = "$ver_mkt_plugin" ]; then
  echo "[version] OK — 매니페스트 넷 모두 $ver_claude"
else
  echo "[version] DRIFT 발견 — 릴리스 하나를 올리며 일부만 바꿨다:" >&2
  printf '    %-34s %s\n' \
    "plugins/.../plugin.json"        "$ver_claude" \
    "codex/.../plugin.json (+메타 뗌)" "$ver_codex" \
    "marketplace.json .metadata"     "$ver_mkt_meta" \
    "marketplace.json .plugins[0]"   "$ver_mkt_plugin" >&2
  exit 1
fi

echo "드리프트 테스트 통과."
