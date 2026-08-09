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

# --- 설명문 길이: 변경 이력을 여기 쌓지 않는다 ---
# 이 필드는 플러그인 목록 화면에서 사람이 읽는 한 문단이다. 그런데 릴리스마다 문단을 하나씩 덧붙여
# 19,805자까지 갔고, 목록이 읽을 수 없게 됐다. 0.9.7 에서 전부 README 변경 이력으로 옮겼고,
# 그 이력이 README 안에서 다시 자라 0.9.13 에서 CHANGELOG.md 로 한 번 더 옮겼다.
#
# **직전 판의 "이 릴리스를 언급하나" 검사가 바로 그 부풀림의 유인이었다** — 통과하는 가장 쉬운 길이
# 문단을 하나 더 붙이는 것이었다. 그래서 그 검사를 길이 상한으로 바꾼다. 릴리스 이력의 단일 출처는
# CHANGELOG.md 이고, 아래 changelog 검사가 그쪽을 지킨다.
DESC_MAX=1200
desc_long=""
for f in .claude-plugin/marketplace.json plugins/ai-ready/.claude-plugin/plugin.json codex/plugins/ai-ready/.codex-plugin/plugin.json; do
  longest="$(jq -r '[.metadata?.description, (.plugins? // [] | .[].description), .description] | map(select(. != null) | length) | max // 0' "$f")"
  [ "$longest" -gt "$DESC_MAX" ] && desc_long="$desc_long $f($longest자)"
done
if [ -n "$desc_long" ]; then
  echo "[description] 너무 길다(상한 ${DESC_MAX}자) —$desc_long" >&2
  echo "              플러그인 목록에서 사람이 읽는 자리다. 릴리스 이력은 CHANGELOG.md 에 쓴다." >&2
  exit 1
fi
echo "[description] OK — 매니페스트 셋 모두 ${DESC_MAX}자 이하"

# --- 설명문이 가리키는 이력 위치가 실재하나 ---
# 설명문 넷이 "Release history lives in <파일>" 로 독자를 이력으로 보낸다. 0.9.13 에서 이력이
# README.md 에서 CHANGELOG.md 로 옮겨졌는데 그 문장 넷은 그대로 남아 있었다 — 길이 상한만 보는
# 위 검사가 그 거짓말에 초록을 줬다. 문구는 자유롭게 두고 가리키는 대상만 본다.
desc_bad=""
for f in .claude-plugin/marketplace.json plugins/ai-ready/.claude-plugin/plugin.json codex/plugins/ai-ready/.codex-plugin/plugin.json; do
  while IFS= read -r target; do
    [ -z "$target" ] && continue
    [ -f "$target" ] || desc_bad="$desc_bad $f→$target"
  done < <(jq -r '[.metadata?.description, (.plugins? // [] | .[].description), .description]
                  | map(select(. != null)) | .[]' "$f" \
           | grep -oE 'Release history lives in [A-Za-z0-9._/-]+' \
           | sed 's/^Release history lives in //; s/\.$//')
done
if [ -n "$desc_bad" ]; then
  echo "[description] 설명문이 없는 파일을 이력으로 가리킨다 —$desc_bad" >&2
  exit 1
fi
echo "[description] OK — 설명문이 가리키는 이력 파일이 실재"

# --- 변경 이력 드리프트: 사용자 대면 릴리스 노트가 이 버전을 담고 있나 ---
# 0.9.6 은 매니페스트도 릴리스 노트도 안 올라갔다. 계약이 바뀌는 릴리스에서 설치자가 그 사실을 알
# 경로가 없다는 뜻이고, 위 버전 검사가 숫자만 보면 그 상태에 초록 도장을 찍는다.
#
# 0.9.13 에서 이력을 README 에서 CHANGELOG.md 로 옮겼다 — README 의 57%가 이력이라 이 플러그인이
# 무엇인지 알려는 사람이 그것부터 스크롤했다. 파일이 없으면 그 사실을 먼저 말한다. `grep` 은 없는
# 파일에도 비0 을 내므로, 없는 파일과 항목 누락이 같은 메시지로 뭉뚱그려지면 원인을 못 읽는다.
CHANGELOG_FILE="CHANGELOG.md"
if [ ! -f "$CHANGELOG_FILE" ]; then
  echo "[changelog] $CHANGELOG_FILE 이 없다 — 릴리스 이력의 단일 출처다." >&2
  exit 1
fi
if grep -q "^- \*\*$ver_claude\*\*" "$CHANGELOG_FILE"; then
  echo "[changelog] OK — $CHANGELOG_FILE 에 $ver_claude 항목 있음"
else
  echo "[changelog] 누락 — $CHANGELOG_FILE 에 '- **$ver_claude**' 항목이 없다." >&2
  echo "            버전만 올리고 사용자 대면 기록을 안 남기면 설치자가 계약 변경을 알 길이 없다." >&2
  exit 1
fi

echo "드리프트 테스트 통과."
