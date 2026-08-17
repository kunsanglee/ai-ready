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

# --- audit 스킬 스크립트: 두 호스트 트리의 사본이 갈라졌나 ---
# 위 블록과 달리 이쪽은 core 원본이 없다. claude 트리가 원본이고 codex 트리가 손으로 맞춰 온
# 사본이라, 한쪽만 고치면 같은 저장소를 두 호스트가 다르게 채점하게 된다.
#
# freshness_check.py 와 install_hook.py 는 codex audit 번들에 일부러 없다
# (codex/tests 의 test_audit_bundle_has_no_hook_installer 가 install_hook.py 부재를 단언한다).
# 이 둘을 빼지 않으면 의도한 차이를 드리프트로 잘못 잡는다.
#
# audit.py 는 파일째로 빼지 않는다. 호스트마다 다른 곳은 훅 복사와 그 산출물 안내 두 자리뿐인데
# 파일을 통째로 빼면 채점 로직 전체가 검사 밖이 된다 — 실측: 한쪽 트리에서만 점수 밴드를
# 뒤집어도 모든 검사가 통과했다. 아래 audit.py 블록이 그 자리를 마커 단위로 좁혀 잠근다.
AUDIT_SRC="plugins/ai-ready/skills/audit/scripts"
AUDIT_DEST="codex/plugins/ai-ready/skills/audit/scripts"
if diff -rq --exclude='__pycache__' --exclude='*.pyc' \
     --exclude='audit.py' --exclude='freshness_check.py' --exclude='install_hook.py' \
     "$AUDIT_SRC" "$AUDIT_DEST" >/tmp/drift.$$.txt 2>&1; then
  echo "[audit-scripts] OK — 두 트리 사본이 바이트 동일"
else
  echo "[audit-scripts] DRIFT 발견 — $AUDIT_SRC 와 $AUDIT_DEST 가 다르다:" >&2
  sed 's/^/    /' /tmp/drift.$$.txt >&2
  rm -f /tmp/drift.$$.txt
  echo "                claude 트리가 원본이다. 거기서 고치고 codex 사본에 옮겨라." >&2
  exit 1
fi
rm -f /tmp/drift.$$.txt

# audit.py: 호스트별로 갈리는 구간만 `HOST-ADAPTER:BEGIN`~`:END` 로 표시돼 있다. 양쪽에서 그
# 구간을 지운 나머지를 비교하므로, 마커 밖의 한 글자 변이는 잡히고 마커 안의 차이는 허용된다.
# 마커가 한쪽에만 있거나 짝이 안 맞으면 지워지는 범위가 서로 달라져 여기서 드러난다.
AUDIT_PY_SRC="$AUDIT_SRC/audit.py"
AUDIT_PY_DEST="$AUDIT_DEST/audit.py"
strip_adapter() { sed '/HOST-ADAPTER:BEGIN/,/HOST-ADAPTER:END/d' "$1"; }
for f in "$AUDIT_PY_SRC" "$AUDIT_PY_DEST"; do
  begins="$(grep -c 'HOST-ADAPTER:BEGIN' "$f" || true)"
  ends="$(grep -c 'HOST-ADAPTER:END' "$f" || true)"
  if [ "$begins" != "$ends" ] || [ "$begins" = "0" ]; then
    echo "[audit-py] 마커가 짝이 안 맞는다($f: BEGIN ${begins}개 / END ${ends}개) —" >&2
    echo "           마커가 없으면 지우는 범위가 어긋나 비교가 뜻을 잃는다." >&2
    exit 1
  fi
done
if diff <(strip_adapter "$AUDIT_PY_SRC") <(strip_adapter "$AUDIT_PY_DEST") >/tmp/drift.$$.txt 2>&1; then
  echo "[audit-py] OK — 어댑터 구간을 뺀 나머지가 두 트리 동일"
else
  echo "[audit-py] DRIFT 발견 — 어댑터 구간 밖에서 $AUDIT_PY_SRC 와 $AUDIT_PY_DEST 가 다르다:" >&2
  sed 's/^/    /' /tmp/drift.$$.txt >&2
  rm -f /tmp/drift.$$.txt
  echo "           claude 트리가 원본이다. 호스트마다 달라야 하는 코드면 마커로 감싸라." >&2
  exit 1
fi
rm -f /tmp/drift.$$.txt

# freshness_check.py 는 codex 에서 audit 번들이 아니라 freshness 스킬에 산다. 위 디렉토리
# 비교에서 뺐으니 여기서 따로 잠근다 — 안 그러면 이 파일만 검사 밖에 남는다.
FRESHNESS_SRC="plugins/ai-ready/skills/audit/scripts/freshness_check.py"
FRESHNESS_DEST="codex/plugins/ai-ready/skills/freshness/scripts/freshness_check.py"
if diff -q "$FRESHNESS_SRC" "$FRESHNESS_DEST" >/dev/null 2>&1; then
  echo "[audit-scripts] OK — freshness_check.py 두 트리 바이트 동일"
else
  echo "[audit-scripts] DRIFT 발견 — $FRESHNESS_SRC 와 $FRESHNESS_DEST 가 다르다:" >&2
  diff "$FRESHNESS_SRC" "$FRESHNESS_DEST" | sed 's/^/    /' >&2
  exit 1
fi

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
  # `${longest}` 의 중괄호는 장식이 아니다. 변수 바로 뒤에 한글이 붙으면 셸이 그 한글까지 변수
  # 이름으로 읽어, zsh 는 빈 문자열을 내고 bash 는 깨진 바이트를 낸다(실측). 실패 경로의 메시지라
  # 평소에 안 보이고, 정작 사람이 이 줄을 읽는 순간은 이미 뭔가 잘못됐을 때다.
  [ "$longest" -gt "$DESC_MAX" ] && desc_long="$desc_long $f(${longest}자)"
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

# --- 변수 확장 바로 뒤에 한글이 붙었나 ---
# 변수 확장 바로 뒤에 한글 음절이 붙으면 셸이 그 한글까지 변수 이름으로 읽는다. zsh 는 빈 문자열을
# 내고 bash 는 깨진 바이트를 낸다(실측: TOTAL=19 일 때 `결정 ` 과 `결정 ??`). 아래가 그 예다.
#
#   나쁨:  echo "결정 $TOTAL개"      # brace-check-example
#   좋음:  echo "결정 ${TOTAL}개"
#
# 이 저장소는 셸 블록도 메시지도 한국어라 이 조합이 자연스럽게 만들어지고, 대부분 실패 경로의
# 메시지라 평소에 안 보인다 — 사람이 그 줄을 읽는 순간은 이미 뭔가 잘못됐을 때고, 그때 숫자가
# 비어 있으면 원인을 한 번 더 헤맨다.
#
# SKILL.md 의 셸 블록도 함께 본다. 그 블록은 오케스트레이터가 그대로 Bash 에 넣어 도는 코드라
# 문서가 아니라 실행물이다. 검사 자신이 예시를 쓸 수 있어야 왜 있는지 설명이 되므로, 줄 끝에
# `brace-check-example` 이 있으면 건너뛴다 — 예외는 이 한 줄짜리 명시적 표시뿐이다.
brace_bad="$(grep -rnE '\$[A-Za-z_][A-Za-z0-9_]*[가-힣]' \
  --include='*.sh' --include='*.md' --include='*.py' \
  build core plugins codex README.md CHANGELOG.md 2>/dev/null \
  | grep -v 'brace-check-example' || true)"
if [ -n "$brace_bad" ]; then
  echo "[brace] 변수 뒤에 한글이 바로 붙었다 — 셸이 그 한글까지 변수 이름으로 읽는다:" >&2
  printf '%s\n' "$brace_bad" | cut -c1-160 | sed 's/^/          /' >&2
  echo "        중괄호를 씌운다. 예외가 필요하면 그 줄 끝에 brace-check-example 을 단다." >&2
  exit 1
fi
echo "[brace] OK — 변수 뒤에 한글이 바로 붙은 자리 없음"

# --- `grep -c` 의 종료코드를 `|| echo` 로 덮었나 ---   # grepc-check-example
# grep 은 일치가 하나도 없으면 **`0` 을 찍고 종료코드 1 로** 끝난다. 그래서 `$(grep -c … || echo 0)`   # grepc-check-example
# 는 0 을 두 번 찍어 값이 `0\n0` 이 되고, 그 값으로 정수 비교를 하면 셸이 "integer expression
# expected" 로 죽으면서 조건이 **거짓**이 된다. 하필 그 조건이 "비었으면 안전한 쪽으로 간다" 인
# 경우가 있어, 문서가 약속한 안전 분기가 통째로 도달 불가가 된다(2026-08-16 실측 — 점검 범위
# 좁히기에서 빈 목록이 그대로 렌즈로 넘어갔다).
#
#   나쁨:  N="$(grep -c '' "$f" || echo 0)"; [ "$N" -eq 0 ] && …   # grepc-check-example
#   좋음:  V="$(cmd)"; [ -z "$V" ] && …
#
# 세는 값이 안내 문구에만 쓰이는데 그것 때문에 판정이 갈리는 것이 이 버그의 모양이라, 세기를
# 없애는 쪽이 갈래를 통째로 지운다. 예외가 정말 필요하면 줄 끝에 grepc-check-example 을 단다.
grepc_bad="$(grep -rn 'grep -c' --include='*.sh' --include='*.md' --include='*.py' \
  build core plugins codex 2>/dev/null \
  | grep '|| echo' | grep -v 'grepc-check-example' || true)"
if [ -n "$grepc_bad" ]; then
  echo "[grep-c] 일치 0건이면 값이 두 줄이 된다 — 정수 비교가 죽고 그 조건이 거짓이 된다:" >&2
  printf '%s\n' "$grepc_bad" | cut -c1-160 | sed 's/^/          /' >&2
  echo "         세지 말고 값을 변수로 받아 [ -z \"\$VAR\" ] 로 본다." >&2
  exit 1
fi
echo "[grep-c] OK — grep -c 종료코드를 덮는 자리 없음"

echo "드리프트 테스트 통과."
