#!/usr/bin/env bash
# .claude/skills/_loop-engine/ 결정론 채점 회귀 테스트.
# "같은 코드엔 항상 같은 severity" 를 고정한다 — 채점 로직·rubric 표를 바꾸면 여기서 깨진다.
# 입력 픽스처만 있고 기대 출력을 박는 짝이 없으면 그 결정론은 자동으로 지켜지지 않는다.
# Usage: bash .claude/skills/_loop-engine/test.sh   (exit 0 = 전부 통과, 비0 = 실패 있음)
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FIX="$DIR/fixtures"
pass=0; fail=0

assert_eq() { # $1 이름  $2 실제  $3 기대
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL  %s\n  기대: [%s]\n  실제: [%s]\n' "$1" "$3" "$2"
  fi
}

sev() { jq -r --arg id "$2" '.findings[] | select(.id==$id) | .severity' <<<"$1"; }
score_rc() { printf '%s' "$1" | bash "$DIR/score.sh" >/dev/null 2>&1; echo $?; }

# ── 1. 정상 픽스처 채점 결정론 ───────────────────────────────────
scored="$(bash "$DIR/score.sh" "$FIX/findings.example.json")"
assert_eq "f1 n-plus-1 +hotpath → CRITICAL"         "$(sev "$scored" f1)" "CRITICAL"
assert_eq "f2 convention floor → MINOR"             "$(sev "$scored" f2)" "MINOR"
assert_eq "f3 idor +authz → BLOCKER"                "$(sev "$scored" f3)" "BLOCKER"
assert_eq "f4 모르는 runtime kind → floor CRITICAL"  "$(sev "$scored" f4)" "CRITICAL"
assert_eq "fixture verdict → AWAIT_USER"            "$(bash "$DIR/decide.sh" <<<"$scored" | jq -r .verdict)" "AWAIT_USER"

# 깨끗 입력은 정상 통과 — 가드가 정상 경로(빈 findings = 발견 없음)를 막으면 안 된다.
assert_eq "{\"findings\":[]} 통과 rc0"  "$(score_rc '{"findings":[]}')" "0"
assert_eq "빈 findings → PASS"          "$(printf '{"findings":[]}' | bash "$DIR/score.sh" | bash "$DIR/decide.sh" | jq -r .verdict)" "PASS"

# test-missing: convention floor(MINOR) 가 아니라 KINDS 예외표 CRITICAL (코드 변경분 테스트 필수 → RETRY)
tmiss_in='{"findings":[{"id":"x","kind":"test-missing","dimension":"convention"}]}'
assert_eq "test-missing → CRITICAL (convention floor 위로)" "$(sev "$(printf '%s' "$tmiss_in" | bash "$DIR/score.sh")" x)" "CRITICAL"
assert_eq "test-missing 단독 → RETRY"  "$(printf '%s' "$tmiss_in" | bash "$DIR/score.sh" | bash "$DIR/decide.sh" | jq -r .verdict)" "RETRY"

# ── 2. 변질 입력 fail-loud (BLOCKER 1·2) ────────────────────────
# checker JSON 추출 실패(빈/null/{}·findings 비배열)를 PASS 로 둔갑시키지 않고 exit 65 로 거부.
assert_eq "{} 거부 exit65"             "$(score_rc '{}')"                 "65"
assert_eq "null 거부 exit65"           "$(score_rc 'null')"               "65"
assert_eq "빈 입력 거부 exit65"         "$(score_rc '')"                   "65"
assert_eq "findings 비배열 거부 exit65" "$(score_rc '{"findings":"oops"}')" "65"

# 파이프 마스킹 차단: score 가 죽으면 decide 도 빈 입력으로 fail-loud (PASS 둔갑 금지).
printf '{}' | bash "$DIR/score.sh" 2>/dev/null | bash "$DIR/decide.sh" >/dev/null 2>&1; rc=$?
assert_eq "변질 입력 파이프 fail-loud(비0)" "$([ "$rc" -ne 0 ] && echo loud || echo silent)" "loud"

# decide/stall 계약 검증: findings/counts 없는 JSON 을 // 폴백으로 PASS·[0,0,0] 오독하지 않는다.
printf '{"nothing":1}' | bash "$DIR/decide.sh" >/dev/null 2>&1; rc=$?
assert_eq "decide: findings 없는 입력 거부 exit65" "$rc" "65"
sttmp="$(mktemp -d)"; stf="$sttmp/s.json"
printf '{"findings":[]}' | bash "$DIR/stall.sh" --state "$stf" >/dev/null 2>&1; rc=$?
assert_eq "stall: counts 없는 입력 거부 exit65" "$rc" "65"
assert_eq "stall: 거부 시 state 미기록(floor 오염 방지)" "$([ -f "$stf" ] && echo written || echo none)" "none"
rm -rf "$sttmp"

# ── 3. 필드 누락이 크래시 대신 보수 채점 (BLOCKER 2 + HIGH 3) ──────
miss_kind="$(printf '%s' '{"findings":[{"id":"x","dimension":"runtime"}]}' | bash "$DIR/score.sh" 2>/dev/null)"
assert_eq "kind 누락 → 크래시 없이 dimension floor CRITICAL" "$(sev "$miss_kind" x)" "CRITICAL"

typo_dim="$(printf '%s' '{"findings":[{"id":"x","kind":"concurrency-bug","dimension":"runtim"}]}' | bash "$DIR/score.sh" 2>/dev/null)"
assert_eq "dimension 오타 → 관대 MINOR 아닌 보수 CRITICAL" "$(sev "$typo_dim" x)" "CRITICAL"

no_dim="$(printf '%s' '{"findings":[{"id":"x","kind":"concurrency-bug"}]}' | bash "$DIR/score.sh" 2>/dev/null)"
assert_eq "dimension 누락 → 보수 CRITICAL" "$(sev "$no_dim" x)" "CRITICAL"

# ── 4. lessons.sh 출처1 추출 결정론 ──────────────────────────────
les="$(bash "$DIR/lessons.sh" "$FIX/history.example.jsonl")"
assert_eq "lessons 고쳐진 실수 수"        "$(jq -r .count <<<"$les")" "3"
assert_eq "lessons 최다 severity → BLOCKER" "$(jq -r '.mistakes[0].max_severity' <<<"$les")" "BLOCKER"
assert_eq "최종 잔존 convention 은 실수 제외" "$(jq -r '([.mistakes[].kind] | index("convention-violation")) // "none"' <<<"$les")" "none"

# ── 5. stall 정체/악화 판정 (평탄 퇴행 사각 + regress 정의) ───────
tmpd="$(mktemp -d)"
st="$tmpd/stall.json"; rm -f "$st"
stall_feed() { # $1 C  $2 M  $3 Mn  → status
  printf '{"counts":{"CRITICAL":%s,"MAJOR":%s,"MINOR":%s}}' "$1" "$2" "$3" \
    | bash "$DIR/stall.sh" --state "$st" | jq -r .status
}
stall_feed 0 0 1 >/dev/null   # INIT, floor = MINOR-only
stall_feed 1 0 0 >/dev/null   # CRITICAL 로 퇴행
stall_feed 1 0 0 >/dev/null   # 고착(ONGOING)
assert_eq "MINOR floor 후 CRITICAL 고착 → STALLED(평탄 퇴행 사각 차단)" "$(stall_feed 1 0 0)" "STALLED"

st2="$tmpd/stall2.json"; rm -f "$st2"
stall_minor() { printf '{"counts":{"CRITICAL":0,"MAJOR":0,"MINOR":%s}}' "$1" | bash "$DIR/stall.sh" --state "$st2" | jq -r .status; }
stall_minor 2 >/dev/null
stall_minor 3 >/dev/null
assert_eq "MINOR 만 증가 → REGRESS_ESCALATE 아님" "$([ "$(stall_minor 4)" = "REGRESS_ESCALATE" ] && echo escalate || echo ok)" "ok"

# ── 6. lessons.sh 키 라인-스트립 + verdict 노출 ──────────────────
hist="$tmpd/h.jsonl"
printf '%s\n' \
 '{"iteration":1,"verdict":"RETRY","findings":[{"kind":"n-plus-1","dimension":"runtime","location":"A.kt:88","severity":"CRITICAL","evidence":"e"}]}' \
 '{"iteration":2,"verdict":"PASS","findings":[{"kind":"n-plus-1","dimension":"runtime","location":"A.kt:90","severity":"CRITICAL","evidence":"e"}]}' \
 > "$hist"
les2="$(bash "$DIR/lessons.sh" "$hist")"
assert_eq "라인만 밀린 동일 결함은 고쳐진 실수 아님(파일키 dedup)" "$(jq -r .count <<<"$les2")" "0"
assert_eq "final_verdict 노출"   "$(jq -r .final_verdict <<<"$les2")"   "PASS"
assert_eq "baseline_passed 노출" "$(jq -r .baseline_passed <<<"$les2")" "true"
rm -rf "$tmpd"

# ── 7. BASE+LOCAL rubric 병합 override (plugin 핵심: 프로젝트가 자기 kind 를 LOCAL 로 더함) ──
loctmp="$(mktemp -d)"; locrub="$loctmp/local.md"
cat > "$locrub" <<'LOCALEOF'
<!-- LOOP_RUBRIC:KINDS:BEGIN -->
| kind_id | dimension | layer | base_severity | force_await | note |
|---|---|---|---|---|---|
| ddl-safety | runtime | gate | BLOCKER | always | LOCAL 전용 — BASE 엔 없음 |
LOCALEOF
printf '<!-- LOOP_RUBRIC:KINDS:END -->\n' >> "$locrub"
ddl_in='{"findings":[{"id":"d","kind":"ddl-safety","dimension":"runtime"}]}'
assert_eq "BASE 만: ddl-safety 모름 → runtime floor CRITICAL" "$(sev "$(printf '%s' "$ddl_in" | bash "$DIR/score.sh")" d)" "CRITICAL"
assert_eq "BASE+LOCAL: ddl-safety override → BLOCKER"          "$(sev "$(printf '%s' "$ddl_in" | LOOP_RUBRIC_LOCAL="$locrub" bash "$DIR/score.sh")" d)" "BLOCKER"
assert_eq "BASE+LOCAL: ddl-safety force_await → AWAIT_USER"    "$(printf '%s' "$ddl_in" | LOOP_RUBRIC_LOCAL="$locrub" bash "$DIR/score.sh" | bash "$DIR/decide.sh" | jq -r .verdict)" "AWAIT_USER"
rm -rf "$loctmp"

# ── 8. detect_build.py 감지기 (런타임 어댑터 대체 — 빌드/스택/문서/티켓 감지) ──
# 셸 채점과 별개의 Python unittest. 통과면 1 assert 가산, 실패면 출력 그대로 노출.
if command -v python3 >/dev/null 2>&1; then
  if det_out="$(python3 "$DIR/test_detect_build.py" 2>&1)"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1)); printf 'FAIL  detect_build 감지기 테스트\n%s\n' "$det_out"
  fi
else
  echo "SKIP  detect_build 테스트 — python3 미설치"
fi

# ── 9. gate_parse.py 파서 (게이트 실패 출력 → 항목 큐) ──
# 형식 회귀가 조용히 나면 큐가 빈 채로 통과처럼 보인다 — 그래서 이 테스트가 게이트에 붙는다.
if command -v python3 >/dev/null 2>&1; then
  if gp_out="$(python3 "$DIR/test_gate_parse.py" 2>&1)"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1)); printf 'FAIL  gate_parse 파서 테스트\n%s\n' "$gp_out"
  fi
else
  echo "SKIP  gate_parse 테스트 — python3 미설치"
fi

# ── 결과 ─────────────────────────────────────────────────────────
echo "────────────────────────"
echo "통과 $pass / 실패 $fail"
[ "$fail" -eq 0 ]
