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
# 단 0.9.7 부터 "무엇을 봤나"(reviewed)를 함께 받아야 깨끗함으로 인정한다.
clean='{"findings":[],"reviewed":["src/A.kt"]}'
assert_eq "깨끗+reviewed 통과 rc0"  "$(score_rc "$clean")" "0"
assert_eq "깨끗+reviewed → PASS"    "$(printf '%s' "$clean" | bash "$DIR/score.sh" | bash "$DIR/decide.sh" | jq -r .verdict)" "PASS"

# 깨끗함과 안 봄을 가른다. `{"findings":[]}` 는 정상 형식이라 "파일이 비었나" 가드를 지나므로,
# 베이스 브랜치 해석이 어긋나 diff 가 통째로 빈 경우가 점검 없이 PASS 로 둔갑하던 자리다.
assert_eq "findings·reviewed 둘 다 빔 → exit65"  "$(score_rc '{"findings":[]}')"              "65"
assert_eq "reviewed 빈 배열도 exit65"            "$(score_rc '{"findings":[],"reviewed":[]}')" "65"
# finding 이 있으면 reviewed 없이도 통과 — 뭔가 찾았다는 것 자체가 봤다는 증거다(구 checker 호환).
assert_eq "finding 있으면 reviewed 없어도 rc0"   "$(score_rc '{"findings":[{"id":"x","dimension":"convention"}]}')" "0"

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
| i18n-key-missing | convention | gate | BLOCKER | always | LOCAL 전용 — BASE 엔 없는 스택 특유 종류 |
LOCALEOF
printf '<!-- LOOP_RUBRIC:KINDS:END -->\n' >> "$locrub"
loc_in='{"findings":[{"id":"d","kind":"i18n-key-missing","dimension":"convention"}]}'
assert_eq "BASE 만: LOCAL 전용 kind 모름 → convention floor MINOR" "$(sev "$(printf '%s' "$loc_in" | bash "$DIR/score.sh")" d)" "MINOR"
assert_eq "BASE+LOCAL: override → BLOCKER"       "$(sev "$(printf '%s' "$loc_in" | LOOP_RUBRIC_LOCAL="$locrub" bash "$DIR/score.sh")" d)" "BLOCKER"
assert_eq "BASE+LOCAL: force_await → AWAIT_USER" "$(printf '%s' "$loc_in" | LOOP_RUBRIC_LOCAL="$locrub" bash "$DIR/score.sh" | bash "$DIR/decide.sh" | jq -r .verdict)" "AWAIT_USER"
rm -rf "$loctmp"

# ── 7-1. 자동화 금지 영역 다섯이 BASE 표에 실제로 있다 ────────────
# 오래 산문으로만 있었고 force_await=always 를 쓰는 행이 0개였다 — 사람 대기가 checker 의
# 프롬프트 준수에만 걸려 있었다. 이제 종류 이름만 맞으면 표가 사람을 부른다.
for k in ddl-safety money-path-change authz-policy-change mass-dispatch destructive-data-op; do
  v="$(printf '{"findings":[{"id":"a","kind":"%s","dimension":"runtime"}]}' "$k" \
       | bash "$DIR/score.sh" | bash "$DIR/decide.sh" | jq -r .verdict)"
  assert_eq "자동화 금지 kind $k → AWAIT_USER" "$v" "AWAIT_USER"
done

# 산문의 다섯 항목과 표의 다섯 행을 **묶는다.** 이 둘이 갈라진 것이 애초의 결함이었다 —
# 산문은 "표의 force_await=always 로 적용한다" 고 적었고 그런 행은 0개였다.
# 위 verdict 검사는 base_severity 가 BLOCKER 인 것만으로도 통과하므로 열 값을 직접 본다.
# shellcheck disable=SC1091
kinds_json="$(. "$DIR/lib.sh" >/dev/null 2>&1; loop_kinds_json)"
for k in ddl-safety money-path-change authz-policy-change mass-dispatch destructive-data-op; do
  assert_eq "산문↔표: $k 행이 always" "$(jq -r --arg k "$k" '.[$k].force_await // "행없음"' <<<"$kinds_json")" "always"
done
prose_n="$(grep -cE '^[0-9]+\. .* — `[a-z-]+`$' "$DIR/rubric.base.md")"
assert_eq "산문 금지 항목 다섯이 전부 kind 를 달고 있다" "$prose_n" "5"
# 가중을 하나도 안 달아도 사람 대기여야 한다 — 그게 이 행들의 존재 이유다.
assert_eq "금지 kind 는 weights 없이도 await" \
  "$(printf '{"findings":[{"id":"a","kind":"ddl-safety","dimension":"runtime","weights":[]}]}' | bash "$DIR/score.sh" | jq -r '.findings[0].await')" "true"

# force_await=always 를 등급과 **독립으로** 잠근다.
# 위 다섯 행은 base_severity 가 BLOCKER 라 그것만으로 await 이 서고, always 를 no 로 바꿔도
# 테스트가 안 깨진다(변이로 확인). 그래서 always 자체는 등급이 낮은 행으로 따로 확인한다 —
# 이 확인이 없으면 "다섯 행에 always 를 달았다" 는 아무것도 잠그지 않는 문장이 된다.
awtmp="$(mktemp -d)"; awrub="$awtmp/local.md"
cat > "$awrub" <<'AWEOF'
<!-- LOOP_RUBRIC:KINDS:BEGIN -->
| kind_id | dimension | layer | base_severity | force_await | note |
|---|---|---|---|---|---|
| minor-but-irreversible | convention | agent | MINOR | always | 등급은 최하인데 비가역 |
AWEOF
printf '<!-- LOOP_RUBRIC:KINDS:END -->\n' >> "$awrub"
aw_in='{"findings":[{"id":"w","kind":"minor-but-irreversible","dimension":"convention"}]}'
aw_out="$(printf '%s' "$aw_in" | LOOP_RUBRIC_LOCAL="$awrub" bash "$DIR/score.sh")"
assert_eq "always: 등급은 MINOR 그대로"        "$(sev "$aw_out" w)" "MINOR"
assert_eq "always: MINOR 인데도 await=true"    "$(jq -r '.findings[0].await' <<<"$aw_out")" "true"
assert_eq "always: MINOR 인데도 AWAIT_USER"    "$(bash "$DIR/decide.sh" <<<"$aw_out" | jq -r .verdict)" "AWAIT_USER"
rm -rf "$awtmp"

# ── 7-2. test-vacuous: 되돌려도 초록인 테스트 ─────────────────────
# test-missing 은 테스트가 *없는* 것만 잡는다. 있는데 아무것도 안 잠그는 것은 이름이 없어
# convention floor(MINOR)로 떨어져 통과했다.
tv='{"findings":[{"id":"t","kind":"test-vacuous","dimension":"convention"}]}'
assert_eq "test-vacuous → CRITICAL" "$(sev "$(printf '%s' "$tv" | bash "$DIR/score.sh")" t)" "CRITICAL"
assert_eq "test-vacuous 단독 → RETRY" "$(printf '%s' "$tv" | bash "$DIR/score.sh" | bash "$DIR/decide.sh" | jq -r .verdict)" "RETRY"

# ── 7-3. 경로 유도 가중 (checker 가 안 달아도 선다) ────────────────
# 같은 finding 이 가중 표시 유무로 RETRY 와 AWAIT_USER 로 갈리던 자리. 경로로 유도되는 것만이라도
# 모델 밖에서 세운다.
pw_mig='{"findings":[{"id":"p","kind":"logic-regression","dimension":"runtime","location":"src/main/resources/db/migration/V9__x.sql:3"}]}'
pw_other='{"findings":[{"id":"p","kind":"logic-regression","dimension":"runtime","location":"README.md:3"}]}'
assert_eq "마이그레이션 경로 → operational_data 유도" \
  "$(printf '%s' "$pw_mig" | bash "$DIR/score.sh" | jq -c '.findings[0].weights_derived')" '["operational_data"]'
assert_eq "마이그레이션 경로 → 상향돼 AWAIT_USER" \
  "$(printf '%s' "$pw_mig" | bash "$DIR/score.sh" | bash "$DIR/decide.sh" | jq -r .verdict)" "AWAIT_USER"
assert_eq "무관 경로는 유도 없음(오탐 확인)" \
  "$(printf '%s' "$pw_other" | bash "$DIR/score.sh" | jq -c '.findings[0].weights_derived')" '[]'
assert_eq "무관 경로는 등급 그대로 RETRY" \
  "$(printf '%s' "$pw_other" | bash "$DIR/score.sh" | bash "$DIR/decide.sh" | jq -r .verdict)" "RETRY"
assert_eq "location 없으면 유도 없음(크래시 없이)" \
  "$(printf '{"findings":[{"id":"p","dimension":"runtime"}]}' | bash "$DIR/score.sh" | jq -c '.findings[0].weights_derived')" '[]'

# LOCAL 이 자기 경로 규칙을 더한다(덮어쓰기가 아니라 누적). 그리고 잘못된 정규식 행 하나가
# 배치 전체를 죽이지 않는다 — 그 행만 아무것도 못 붙인다.
pwtmp="$(mktemp -d)"; pwrub="$pwtmp/local.md"
cat > "$pwrub" <<'PWEOF'
<!-- LOOP_RUBRIC:PATHWEIGHTS:BEGIN -->
| path_pattern | weight_keys |
|---|---|
| src/billing/ | money |
| [broken(regex | hotpath |
| src/perm/ | authz, not_in_allowlist |
PWEOF
printf '<!-- LOOP_RUBRIC:PATHWEIGHTS:END -->\n' >> "$pwrub"
bill='{"findings":[{"id":"b","kind":"logic-regression","dimension":"runtime","location":"src/billing/Calc.kt:1"}]}'
perm='{"findings":[{"id":"b","kind":"n-plus-1","dimension":"runtime","location":"src/perm/Check.kt:1"}]}'
assert_eq "LOCAL 경로 규칙 누적 → money 유도" \
  "$(printf '%s' "$bill" | LOOP_RUBRIC_LOCAL="$pwrub" bash "$DIR/score.sh" | jq -c '.findings[0].weights_derived')" '["money"]'
assert_eq "깨진 정규식 행이 배치를 안 죽인다(rc0)" \
  "$(printf '%s' "$bill" | LOOP_RUBRIC_LOCAL="$pwrub" bash "$DIR/score.sh" >/dev/null 2>&1; echo $?)" "0"
assert_eq "유도 가중도 WEIGHTS 허용표를 지난다(표 밖 키 무시)" \
  "$(printf '%s' "$perm" | LOOP_RUBRIC_LOCAL="$pwrub" bash "$DIR/score.sh" | jq -c '.findings[0].weights_ignored')" '["not_in_allowlist"]'
assert_eq "유도 가중 상향은 한 단계뿐(n-plus-1 MAJOR→CRITICAL)" \
  "$(sev "$(printf '%s' "$perm" | LOOP_RUBRIC_LOCAL="$pwrub" bash "$DIR/score.sh")" b)" "CRITICAL"
rm -rf "$pwtmp"

# 패턴 열은 정규식이라 역슬래시·큰따옴표가 들어온다. JSON 을 손으로 짜면 `\.` 이 잘못된 이스케이프가
# 되어 jq 파서가 죽는다(실제로 죽었다). 이 두 줄이 그 회귀를 막는다.
estmp="$(mktemp -d)"; esrub="$estmp/local.md"
cat > "$esrub" <<'ESEOF'
<!-- LOOP_RUBRIC:PATHWEIGHTS:BEGIN -->
| path_pattern | weight_keys |
|---|---|
| \.sql$ | operational_data |
| a"b | hotpath |
ESEOF
printf '<!-- LOOP_RUBRIC:PATHWEIGHTS:END -->\n' >> "$esrub"
sqlf='{"findings":[{"id":"s","kind":"logic-regression","dimension":"runtime","location":"db/x/V1__a.sql"}]}'
assert_eq "역슬래시 정규식이 파서를 안 죽인다" \
  "$(printf '%s' "$sqlf" | LOOP_RUBRIC_LOCAL="$esrub" bash "$DIR/score.sh" >/dev/null 2>&1; echo $?)" "0"
assert_eq "역슬래시 정규식이 실제로 매칭한다" \
  "$(printf '%s' "$sqlf" | LOOP_RUBRIC_LOCAL="$esrub" bash "$DIR/score.sh" | jq -c '.findings[0].weights_derived')" '["operational_data"]'
# 입력은 printf 의 형식 문자열이 아니라 인자로 넘긴다 — 형식 문자열이면 printf 가 `\"` 를 먹어
# JSON 이 깨진다(그 오류를 실제로 봤다).
qjson='{"findings":[{"id":"q","dimension":"runtime","location":"a\"b/c"}]}'
assert_eq "큰따옴표 든 패턴도 파서를 안 죽인다" \
  "$(printf '%s' "$qjson" | LOOP_RUBRIC_LOCAL="$esrub" bash "$DIR/score.sh" | jq -c '.findings[0].weights_derived')" '["hotpath"]'
rm -rf "$estmp"

# ── 7-4. layer 열이 살아 있다 (표에서 읽어 출력까지 간다) ──────────
assert_eq "layer 노출 (죽은 열 아님)" \
  "$(printf '{"findings":[{"id":"l","kind":"ddl-safety","dimension":"runtime"}]}' | bash "$DIR/score.sh" | jq -r '.findings[0].layer')" "gate"

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
