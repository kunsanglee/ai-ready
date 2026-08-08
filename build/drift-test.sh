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
command -v jq >/dev/null 2>&1 || { echo "drift-test: 'jq' 필요 (PATH 확인)" >&2; exit 127; }
ver_claude="$(jq -r '.version' plugins/ai-ready/.claude-plugin/plugin.json)"
ver_codex="$(jq -r '.version' codex/plugins/ai-ready/.codex-plugin/plugin.json | sed 's/+.*//')"
ver_mkt_meta="$(jq -r '.metadata.version' .claude-plugin/marketplace.json)"
# 인덱스 고정(.plugins[0])이 아니라 이름으로 찾는다 — 마켓플레이스에 플러그인이 하나 더 붙으면
# 엉뚱한 항목을 검사하게 된다.
ver_mkt_plugin="$(jq -r '.plugins[] | select(.name == "ai-ready") | .version' .claude-plugin/marketplace.json)"
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

# --- 설명문 드리프트: 매니페스트 셋이 이 릴리스를 언급하나 ---
# 버전 검사는 `version` 숫자만 본다. 그 옆의 `description` 은 마켓플레이스 UI 에서 설치자가 읽는 자리인데
# 실제로 세 파일이 세 가지 답을 하고 있었다(marketplace 는 0.9.6 을 건너뛰고, claude 는 0.9.7 이 없고,
# codex 는 0.9.5 에서 멈췄다). 전문을 강제로 같게 만들지는 않는다 — 길이가 8,957자와 19,679자로 달라
# 목적이 다른 글이다. **이 릴리스를 언급은 하는가**까지만 잠근다.
desc_missing=""
for f in .claude-plugin/marketplace.json plugins/ai-ready/.claude-plugin/plugin.json codex/plugins/ai-ready/.codex-plugin/plugin.json; do
  if ! jq -r '[.metadata?.description, (.plugins? // [] | .[].description), .description] | map(select(. != null)) | join(" ")' "$f" \
       | grep -q "v${ver_claude}+"; then
    desc_missing="$desc_missing $f"
  fi
done
if [ -n "$desc_missing" ]; then
  echo "[description] 누락 — 이 매니페스트의 설명문이 v${ver_claude} 를 언급하지 않는다:$desc_missing" >&2
  echo "              설치자가 마켓플레이스에서 읽는 자리라, 셋이 다른 릴리스를 말하면 무엇이 깔리는지 알 수 없다." >&2
  exit 1
fi
echo "[description] OK — 매니페스트 셋 모두 v$ver_claude 언급"

# --- 변경 이력 드리프트: 사용자 대면 릴리스 노트가 이 버전을 담고 있나 ---
# 0.9.6 은 매니페스트도 README 도 안 올라갔다. 계약이 바뀌는 릴리스에서 설치자가 그 사실을 알 경로가
# 없다는 뜻이고, 위 버전 검사가 숫자만 보면 그 상태에 초록 도장을 찍는다.
if grep -q "^- \*\*$ver_claude\*\*" README.md; then
  echo "[changelog] OK — README 변경 이력에 $ver_claude 항목 있음"
else
  echo "[changelog] 누락 — README.md 변경 이력에 '- **$ver_claude**' 항목이 없다." >&2
  echo "            버전만 올리고 사용자 대면 기록을 안 남기면 설치자가 계약 변경을 알 길이 없다." >&2
  exit 1
fi

echo "드리프트 테스트 통과."
