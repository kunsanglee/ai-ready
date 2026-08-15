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
# **이름을 산문에서 뽑아 쓴다.** 하드코딩하면 "줄 수 5" 만 세게 되어, 산문의 이름이 바뀌어도
# 안 깨진다 — 애초 결함이 "산문과 표가 갈라진 것" 인데 그 갈라짐을 못 잡으면 이 검사는 무의미하다.
prose_kinds="$(grep -oE '^[0-9]+\. .* — `[a-z-]+`$' "$DIR/rubric.base.md" | sed 's/.*`\(.*\)`$/\1/' | sort)"
assert_eq "산문 금지 항목이 다섯이다" "$(printf '%s\n' "$prose_kinds" | grep -c .)" "5"
for k in $prose_kinds; do
  assert_eq "산문↔표: $k 행이 always" "$(jq -r --arg k "$k" '.[$k].force_await // "행없음"' <<<"$kinds_json")" "always"
done
# 표에 always 인 행의 집합과 산문 목록이 **같은지** 본다(한쪽에만 있는 것을 잡는다).
table_kinds="$(jq -r 'to_entries | map(select(.value.force_await == "always")) | .[].key' <<<"$kinds_json" | sort)"
assert_eq "산문 목록과 표의 always 집합이 일치" "$(printf '%s' "$table_kinds")" "$(printf '%s' "$prose_kinds")"
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
| src/perm/ | authz |
PWEOF
printf '<!-- LOOP_RUBRIC:PATHWEIGHTS:END -->\n' >> "$pwrub"
bill='{"findings":[{"id":"b","kind":"logic-regression","dimension":"runtime","location":"src/billing/Calc.kt:1"}]}'
perm='{"findings":[{"id":"b","kind":"n-plus-1","dimension":"runtime","location":"src/perm/Check.kt:1"}]}'
assert_eq "LOCAL 경로 규칙 누적 → money 유도" \
  "$(printf '%s' "$bill" | LOOP_RUBRIC_LOCAL="$pwrub" bash "$DIR/score.sh" | jq -c '.findings[0].weights_derived')" '["money"]'
assert_eq "깨진 정규식 행이 배치를 안 죽인다(rc0)" \
  "$(printf '%s' "$bill" | LOOP_RUBRIC_LOCAL="$pwrub" bash "$DIR/score.sh" >/dev/null 2>&1; echo $?)" "0"
assert_eq "유도 가중 상향은 한 단계뿐(n-plus-1 MAJOR→CRITICAL)" \
  "$(sev "$(printf '%s' "$perm" | LOOP_RUBRIC_LOCAL="$pwrub" bash "$DIR/score.sh")" b)" "CRITICAL"
rm -rf "$pwtmp"

# 허용 표 밖 키를 유도하는 PATHWEIGHTS 는 **설정 오류**다. 조용히 무시하면 사람은 그 경로를 덮었다고
# 믿는데 실제로는 아무 가중도 안 선다 — 실패 방향이 나쁜 쪽이라 fail-loud 로 바꿨다(적대적 시험 11).
badtmp="$(mktemp -d)"; badrub="$badtmp/local.md"
cat > "$badrub" <<'BADEOF'
<!-- LOOP_RUBRIC:PATHWEIGHTS:BEGIN -->
| path_pattern | weight_keys |
|---|---|
| src/perm/ | authz, not_in_allowlist |
BADEOF
printf '<!-- LOOP_RUBRIC:PATHWEIGHTS:END -->\n' >> "$badrub"
assert_eq "허용 표 밖 유도 키 → exit65" \
  "$(printf '{"findings":[{"id":"b","dimension":"runtime","location":"x"}]}' | LOOP_RUBRIC_LOCAL="$badrub" bash "$DIR/score.sh" >/dev/null 2>&1; echo $?)" "65"

# alternation 을 쓰면 표 열이 밀려 **경로가 가중 키 자리**에 온다. 전에는 그 행이 조용히 무효가 됐다 —
# 사람은 두 경로를 덮었다고 믿고 실제로는 둘 다 못 받는다. 이제 위 검사가 같이 잡는다.
alttmp="$(mktemp -d)"; altrub="$alttmp/local.md"
{ printf '<!-- LOOP_RUBRIC:PATHWEIGHTS:BEGIN -->\n| path_pattern | weight_keys |\n|---|---|\n'
  printf '| db/migrate|db/changelog | operational_data |\n'
  printf '<!-- LOOP_RUBRIC:PATHWEIGHTS:END -->\n'; } > "$altrub"
# 후행 파이프 오타로 가중 열이 비는 행도 조용히 무효였다.
emptytmp="$(mktemp -d)"; emptyrub="$emptytmp/local.md"
{ printf '<!-- LOOP_RUBRIC:PATHWEIGHTS:BEGIN -->\n| path_pattern | weight_keys |\n|---|---|\n'
  printf '| db/migrate| | operational_data |\n'
  printf '<!-- LOOP_RUBRIC:PATHWEIGHTS:END -->\n'; } > "$emptyrub"
assert_eq "가중 키 없는 PATHWEIGHTS 행 → exit65" \
  "$(printf '{"findings":[{"id":"b","dimension":"runtime","location":"x"}]}' | LOOP_RUBRIC_LOCAL="$emptyrub" bash "$DIR/score.sh" >/dev/null 2>&1; echo $?)" "65"
rm -rf "$emptytmp"

assert_eq "alternation 이 밀어낸 열 → exit65 (조용한 무효 아님)" \
  "$(printf '{"findings":[{"id":"b","dimension":"runtime","location":"x"}]}' | LOOP_RUBRIC_LOCAL="$altrub" bash "$DIR/score.sh" >/dev/null 2>&1; echo $?)" "65"
rm -rf "$badtmp" "$alttmp"

# ── 7-5. 적대적 시험이 찾은 fail-open 넷 ──────────────────────────
# 넷 다 "조용히 낮아지는" 방향이라 실패해도 아무 신호가 안 남던 자리다.

# (1) reviewed 가 배열이 아니면 게이트가 통째로 열렸다. `true|length` 가 jq 에러를 내고
#     그 실패가 빈 문자열이 되어 if 조건이 거짓이 됐다 — 이번 커밋의 새 방어가 스스로 fail-open.
for bad in 'true' '"x"' '5' '{}'; do
  assert_eq "reviewed 가 배열 아님($bad) → exit65" \
    "$(printf '{"findings":[],"reviewed":%s}' "$bad" | bash "$DIR/score.sh" >/dev/null 2>&1; echo $?)" "65"
done

# (2) force_await 를 표의 어휘 그대로 "always" 로 쓰면 엄격 비교(== true)가 조용히 무시했다.
#     하필 KINDS 표의 그 열 값이 always 라, 표를 베낀 checker 가 사람 대기를 통째로 없앨 수 있었다.
for v in 'true' '"true"' '"always"' '"yes"' '1'; do
  assert_eq "force_await=$v → await 참" \
    "$(printf '{"findings":[{"id":"f","dimension":"convention","force_await":%s}]}' "$v" | bash "$DIR/score.sh" | jq -r '.findings[0].await')" "true"
done
for v in 'false' '"false"' 'null'; do
  assert_eq "force_await=$v → await 거짓" \
    "$(printf '{"findings":[{"id":"f","dimension":"convention","force_await":%s}]}' "$v" | bash "$DIR/score.sh" | jq -r '.findings[0].await')" "false"
done

# (3) 알려진 관대한 kind 가 dimension floor 를 완전히 이겼다. security 를 정직하게 적어도
#     kind 하나로 MINOR 가 됐다. 어긋나면 둘 중 높은 쪽 — 어느 방향으로도 조용히 안 낮아진다.
assert_eq "kind(MINOR)↔dimension(security) 어긋남 → floor 승" \
  "$(sev "$(printf '{"findings":[{"id":"m","kind":"intent-overreach","dimension":"security"}]}' | bash "$DIR/score.sh")" m)" "CRITICAL"
assert_eq "kind(BLOCKER)↔dimension(convention) 어긋남 → kind 승(내려가지 않는다)" \
  "$(sev "$(printf '{"findings":[{"id":"m","kind":"ddl-safety","dimension":"convention"}]}' | bash "$DIR/score.sh")" m)" "BLOCKER"
assert_eq "일치하면 표값 그대로(n-plus-1 은 runtime floor 아래가 의도)" \
  "$(sev "$(printf '{"findings":[{"id":"m","kind":"n-plus-1","dimension":"runtime"}]}' | bash "$DIR/score.sh")" m)" "MAJOR"

# (4) weights 가 배열이 아니면 jq 가 죽어 **같은 배치의 진짜 BLOCKER 까지** 사라졌다.
mixed='{"findings":[{"id":"real","kind":"authz-policy-change","dimension":"security"},{"id":"bad","dimension":"convention","weights":"oops"}]}'
assert_eq "weights 타입 오류가 배치를 안 죽인다(rc0)" \
  "$(printf '%s' "$mixed" | bash "$DIR/score.sh" >/dev/null 2>&1; echo $?)" "0"
assert_eq "그 배치의 진짜 BLOCKER 가 살아남는다" \
  "$(printf '%s' "$mixed" | bash "$DIR/score.sh" | bash "$DIR/decide.sh" | jq -r .verdict)" "AWAIT_USER"
assert_eq "잘못된 weights 는 눈에 보이게 남는다" \
  "$(printf '%s' "$mixed" | bash "$DIR/score.sh" | jq -c '.findings[1].weights_ignored')" '["oops"]'

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


# ── 7-6. 마이그레이션 경로 커버리지 (적대적 시험 7) ────────────────
# 처음 다섯 패턴이 흔한 배치를 놓쳤다. 운영 DB 를 드롭하는 finding 이 사람 없이 돌 수 있었다.
mig_await() {
  printf '{"findings":[{"id":"d","kind":"ddl","dimension":"runtime","location":"%s"}],"reviewed":["x"]}' "$1" \
    | bash "$DIR/score.sh" | jq -r '.findings[0].await'
}
# BASE 의 여덟 행을 **전부** 건다. 전에는 `db/migration` 하나만 걸려서, 나머지 넷을 지워도
# 테스트가 84/0 그대로였다(계약 리뷰 실측).
for loc in 'migrations/001_drop.sql' 'db/migrate/20260809_drop.rb' \
           'src/main/resources/db/changelog/changes/001-drop.sql' 'DB/Migration/V9.sql' \
           'src/main/resources/db/migration/V9__x.sql' 'alembic/versions/ab_x.py' \
           'infra/flyway/conf/V2__x.sql' 'ops/liquibase/master.xml' 'db/changeset/003.sql'; do
  assert_eq "마이그레이션 경로 잡힘: $loc" "$(mig_await "$loc")" "true"
done
# 오탐 확인 — 무관한 경로가 덩달아 올라가면 루프가 사람 대기로 멈춘다.
for loc in 'src/UserService.kt' 'README.md' 'docs/migration-guide.md.bak'; do
  assert_eq "무관 경로는 안 올라간다: $loc" "$(mig_await "$loc")" "false"
done

# ── 7-6b. 유도에서 빼는 경로 (계약 리뷰 1·2) ──────────────────────
# 부분 일치라 마이그레이션을 *설명하는* 문서·픽스처·의존성 트리까지 걸렸다. 그 한 건이 AWAIT_USER 를
# 내면 밤새 도는 무인 루프가 거기서 선다 — 오탐 비용이 실재하는 자리다.
for loc in 'docs/db/migration-policy.md:12' 'docs/guide/liquibase-vs-flyway.md:4' \
           'src/test/fixtures/migrations/seed.sql:1' 'node_modules/p/migrations/x.js:2' \
           'vendor/x/db/migrate/1.rb'; do
  assert_eq "제외 경로는 유도 안 받음: $loc" "$(mig_await "$loc")" "false"
done
# 줄 번호가 붙은 채로 맞추면 `\.md$` 같은 끝 앵커가 영영 안 맞는다 — 실제로 그래서 안 들었다.
assert_eq "location 의 :줄 을 떼고 맞춘다" "$(mig_await 'docs/a.md:12')" "false"
assert_eq "제외 없는 경로는 그대로 유도"   "$(mig_await 'src/main/resources/db/migration/V1__x.sql:9')" "true"

# LOCAL 이 BASE 경로 규칙을 끄는 유일한 길이 이 표다(PATHWEIGHTS 는 누적이라 덮을 수 없다).
extmp="$(mktemp -d)"; exrub="$extmp/local.md"
{ printf '<!-- LOOP_RUBRIC:PATHEXCLUDE:BEGIN -->\n| exclude_pattern |\n|---|\n'
  printf '| db/migration |\n'
  printf '<!-- LOOP_RUBRIC:PATHEXCLUDE:END -->\n'; } > "$exrub"
assert_eq "LOCAL 제외로 BASE 경로행을 끌 수 있다" \
  "$(printf '{"findings":[{"id":"d","kind":"ddl","dimension":"runtime","location":"src/db/migration/V1.sql"}],"reviewed":["x"]}' \
     | LOOP_RUBRIC_LOCAL="$exrub" bash "$DIR/score.sh" | jq -c '.findings[0].weights_derived')" '[]'
rm -rf "$extmp"

# ── 7-6c. force_await=always 는 LOCAL 이 못 끈다 (적대적 시험 9) ────
# 그 파일은 `.loop/rubric.md` 라 **채점받는 쪽(maker)이 쓸 수 있는 자리**다. 한 줄로 다섯 게이트가
# 사라지면 안 된다. 등급은 여전히 LOCAL 이 조절할 수 있고, 사람 대기만 남는다.
kltmp="$(mktemp -d)"; klrub="$kltmp/local.md"
{ printf '<!-- LOOP_RUBRIC:KINDS:BEGIN -->\n| kind_id | dimension | layer | base_severity | force_await | note |\n|---|---|---|---|---|---|\n'
  printf '| ddl-safety | runtime | agent | MINOR | no | 무력화 시도 |\n'
  printf '<!-- LOOP_RUBRIC:KINDS:END -->\n'; } > "$klrub"
kl_out="$(printf '{"findings":[{"id":"k","kind":"ddl-safety","dimension":"runtime"}]}' | LOOP_RUBRIC_LOCAL="$klrub" bash "$DIR/score.sh")"
assert_eq "LOCAL 이 등급은 낮출 수 있다"        "$(sev "$kl_out" k)" "MINOR"
assert_eq "그래도 사람 대기는 안 없어진다"      "$(jq -r '.findings[0].await' <<<"$kl_out")" "true"
assert_eq "verdict 도 AWAIT_USER 그대로"        "$(bash "$DIR/decide.sh" <<<"$kl_out" | jq -r .verdict)" "AWAIT_USER"
rm -rf "$kltmp"

# ── 7-7. LOCAL KINDS 행의 열이 모자라면 조용히 버리지 않는다 (적대적 시험 9) ──
# 전에는 그 kind 가 등록 안 된 채 dimension floor 로 떨어져 통과했다. 사람은 등록했다고 믿는다.
shorttmp="$(mktemp -d)"; shortrub="$shorttmp/local.md"
{ printf '<!-- LOOP_RUBRIC:KINDS:BEGIN -->\n| kind_id | dimension | layer | base_severity | force_await | note |\n|---|---|---|---|---|---|\n'
  printf '| tenant-leak | security | BLOCKER | always |\n'
  printf '<!-- LOOP_RUBRIC:KINDS:END -->\n'; } > "$shortrub"
assert_eq "KINDS 열 부족 행 → exit65 (조용한 누락 아님)" \
  "$(printf '{"findings":[{"id":"x","kind":"tenant-leak","dimension":"security"}]}' | LOOP_RUBRIC_LOCAL="$shortrub" bash "$DIR/score.sh" >/dev/null 2>&1; echo $?)" "65"
rm -rf "$shorttmp"

# ── 7-8. stall 상태 파일도 신뢰할 수 없는 입력이다 (적대적 시험 13·14) ──
# 그 파일은 `.loop/run/{ticket}/` 이라 maker 가 쓸 수 있는 자리다. 검증이 stdin 에만 걸려 있었다.
sttmp2="$(mktemp -d)"; stf2="$sttmp2/s.json"
feed2() { printf '{"counts":{"CRITICAL":3,"MAJOR":0,"MINOR":0}}' | bash "$DIR/stall.sh" --state "$stf2" 2>/dev/null | jq -r "$1"; }
printf '{"floor":[3,0,0],"cur":[3,0,0],"prev":[3,0,0],"no_progress":-999,"regress_streak":0}' > "$stf2"
feed2 .status >/dev/null
assert_eq "음수 no_progress 를 심어도 정체 감지가 산다" "$(feed2 .status)" "STALLED"
printf '{}' > "$stf2"
printf '{"counts":{"CRITICAL":1,"MAJOR":0,"MINOR":0}}' | bash "$DIR/stall.sh" --state "$stf2" >/dev/null 2>&1
assert_eq "깨진 상태 파일 → 죽지 않고 INIT 로 회복" \
  "$(printf '{"counts":{"CRITICAL":1,"MAJOR":0,"MINOR":0}}' | bash "$DIR/stall.sh" --state "$stf2" 2>/dev/null | jq -r .status)" "ONGOING"
rm -rf "$sttmp2"

# ── 7-9. kindstreak.sh 반복 종류 감지 ────────────────────────────
# stall.sh 는 등급 개수 벡터만 봐서 finding 의 **종류** 가 안 보인다. 한 phase 가 여섯 사이클을
# 돌았고 그중 넷이 같은 kind(test-vacuous)였는데 판정부는 그걸 신호로 내지 않았다 — 등급이
# 오르내리는 동안 PROGRESS 까지 떴다. 그 자리를 이 감지기가 메운다.
kstmp="$(mktemp -d)"
# 사이클 이력 픽스처 생성기. 인자 하나 = 한 사이클, "kind:등급,kind:등급" 형식(빈 문자열 = finding 0건).
ks_hist() {
  local f="$1"; shift
  local it=0 spec item kind sev
  : > "$f"
  for spec in "$@"; do
    it=$((it + 1))
    printf '{"iteration":%d,"verdict":"RETRY","findings":[' "$it" >> "$f"
    local first=1
    local IFS=,
    for item in $spec; do
      [ -n "$item" ] || continue
      kind="${item%%:*}"; sev="${item##*:}"
      [ "$first" -eq 1 ] || printf ',' >> "$f"
      first=0
      printf '{"kind":"%s","dimension":"convention","location":"A.kt:1","severity":"%s"}' "$kind" "$sev" >> "$f"
    done
    printf ']}\n' >> "$f"
  done
}
ks() { bash "$DIR/kindstreak.sh" --history "$1"; }               # JSON 전문
ks_f() { ks "$1" | jq -r "$2"; }                                  # 필드 하나
ks_rc() { bash "$DIR/kindstreak.sh" --history "$1" >/dev/null 2>&1; echo $?; }

# 임계만큼 연속 → 감지. 종류와 연속 횟수가 맞는지까지 본다("떴다" 만 보면 아무 종류나 통과한다).
ks_thr="$(. "$DIR/lib.sh" >/dev/null 2>&1; loop_param repeated_kind_cycles)"
ks_hist "$kstmp/streak.jsonl" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL"
assert_eq "같은 종류 3연속 → REPEATED_KIND" "$(ks_f "$kstmp/streak.jsonl" .status)" "REPEATED_KIND"
assert_eq "그 종류를 지목한다"               "$(ks_f "$kstmp/streak.jsonl" .kind)"   "test-vacuous"
assert_eq "연속 횟수 3"                      "$(ks_f "$kstmp/streak.jsonl" .streak)" "3"
assert_eq "threshold 는 rubric 값 그대로"    "$(ks_f "$kstmp/streak.jsonl" .threshold)" "$ks_thr"
assert_eq "cycles 는 이력 줄 수"             "$(ks_f "$kstmp/streak.jsonl" .cycles)" "3"

# 대조군 넷 — 임계에 못 미치거나 연속이 아닌 것은 울리지 않는다. 이게 없으면 "늘 울리는 감지기" 와
# 구분이 안 된다.
ks_hist "$kstmp/short.jsonl" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL"
assert_eq "임계보다 하나 적으면 → OK" "$(ks_f "$kstmp/short.jsonl" .status)" "OK"
assert_eq "그래도 연속 수는 센다"      "$(ks_f "$kstmp/short.jsonl" .streak)" "2"

ks_hist "$kstmp/vary.jsonl" "n-plus-1:CRITICAL" "test-missing:CRITICAL" "idor:CRITICAL"
assert_eq "종류가 매번 다르면 → OK"   "$(ks_f "$kstmp/vary.jsonl" .status)" "OK"
assert_eq "그때 연속은 1"             "$(ks_f "$kstmp/vary.jsonl" .streak)" "1"

ks_hist "$kstmp/interrupt.jsonl" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL" \
                                 "n-plus-1:CRITICAL" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL"
assert_eq "다른 종류가 끼면 연속이 끊긴다 → OK" "$(ks_f "$kstmp/interrupt.jsonl" .status)" "OK"
assert_eq "끊긴 뒤부터 다시 센다(2)"            "$(ks_f "$kstmp/interrupt.jsonl" .streak)" "2"

ks_hist "$kstmp/empty-cycle.jsonl" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL" "" "test-vacuous:CRITICAL"
assert_eq "finding 0건 사이클도 연속을 끊는다" "$(ks_f "$kstmp/empty-cycle.jsonl" .streak)" "1"

# MINOR 만 있는 사이클은 게이트를 통과시키는 등급이라 세지 않는다 — 연속을 끊지도 잇지도 않는다.
# 이걸 안 건너뛰면 MINOR 하나가 낀 것만으로 감지기가 영영 안 울린다.
ks_hist "$kstmp/minor-gap.jsonl" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL" \
                                 "convention-violation:MINOR" "test-vacuous:CRITICAL"
assert_eq "MINOR 만 있는 사이클은 건너뛴다 → 연속 유지" "$(ks_f "$kstmp/minor-gap.jsonl" .status)" "REPEATED_KIND"
assert_eq "그 연속은 3(MINOR 사이클은 안 셈)"           "$(ks_f "$kstmp/minor-gap.jsonl" .streak)" "3"
assert_eq "cycles 는 MINOR 사이클도 포함한 4"           "$(ks_f "$kstmp/minor-gap.jsonl" .cycles)" "4"

# 동점이면 그 사이클엔 지배 종류가 없다 — "같은 종류가 계속" 이라는 근거가 아니므로 연속이 끊긴다.
ks_hist "$kstmp/tie.jsonl" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL,n-plus-1:CRITICAL"
assert_eq "최빈 동점 → 연속 끊김(OK)" "$(ks_f "$kstmp/tie.jsonl" .status)" "OK"
assert_eq "동점 사이클은 지배 종류 없음(kind null)" "$(ks_f "$kstmp/tie.jsonl" .kind)" "null"
assert_eq "동점 사이클은 streak 0"                  "$(ks_f "$kstmp/tie.jsonl" .streak)" "0"
# 같은 동점을 **연속 종류가 사전순으로 앞서는** 배치로 한 번 더 본다. 동점 처리를 지우고 아무거나
# 고르게 하면 여기서는 status 까지 뒤집힌다(위 배치만으로는 고른 쪽이 우연히 달라 status 가 안 뒤집혔다).
ks_hist "$kstmp/tie2.jsonl" "aaa-kind:CRITICAL" "aaa-kind:CRITICAL" "aaa-kind:CRITICAL,zzz-kind:CRITICAL"
assert_eq "동점이면 앞선 종류를 집어 잇지 않는다" "$(ks_f "$kstmp/tie2.jsonl" .status)" "OK"
assert_eq "그 배치도 streak 0"                    "$(ks_f "$kstmp/tie2.jsonl" .streak)" "0"
# 대조군 — 같은 사이클에서 한쪽이 하나 더 많으면 동점이 아니라 그쪽이 지배한다.
ks_hist "$kstmp/notie.jsonl" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL" \
                             "test-vacuous:CRITICAL,test-vacuous:CRITICAL,n-plus-1:CRITICAL"
assert_eq "동점이 아니면 최빈이 지배한다" "$(ks_f "$kstmp/notie.jsonl" .status)" "REPEATED_KIND"
assert_eq "그 종류는 최빈 쪽"             "$(ks_f "$kstmp/notie.jsonl" .kind)"   "test-vacuous"

# 등급이 섞이면 **가장 높은 등급** 쪽만 본다. 개수로만 세면 아래 이력의 지배 종류가 n-plus-1 이 된다.
ks_hist "$kstmp/mixed.jsonl" "ddl-safety:BLOCKER,n-plus-1:CRITICAL,n-plus-1:CRITICAL" \
                             "ddl-safety:BLOCKER,n-plus-1:CRITICAL,n-plus-1:CRITICAL" \
                             "ddl-safety:BLOCKER,n-plus-1:CRITICAL,n-plus-1:CRITICAL"
assert_eq "BLOCKER 와 CRITICAL 이 섞이면 BLOCKER 쪽" "$(ks_f "$kstmp/mixed.jsonl" .kind)"   "ddl-safety"
assert_eq "그 연속이 감지된다"                        "$(ks_f "$kstmp/mixed.jsonl" .status)" "REPEATED_KIND"

# 빈 이력(0줄)은 오류가 아니다 — 첫 사이클 전에 부를 수 있어야 한다.
: > "$kstmp/empty.jsonl"
assert_eq "빈 이력 → OK"        "$(ks_f "$kstmp/empty.jsonl" .status)" "OK"
assert_eq "빈 이력 → cycles 0"  "$(ks_f "$kstmp/empty.jsonl" .cycles)" "0"
assert_eq "빈 이력 → streak 0"  "$(ks_f "$kstmp/empty.jsonl" .streak)" "0"

# 못 읽는 입력에 조용히 OK 를 내면 감지기가 영영 안 울리는데 그 침묵이 통과로 보인다 — fail-loud.
assert_eq "이력 파일 없음 → exit65" "$(ks_rc "$kstmp/nosuch.jsonl")" "65"
printf '{"iteration":1,"findings":[]}\n너 이건 JSON 이 아니다\n' > "$kstmp/broken.jsonl"
assert_eq "깨진 줄 → exit65"        "$(ks_rc "$kstmp/broken.jsonl")" "65"
assert_eq "인자 없음 → exit64"      "$(bash "$DIR/kindstreak.sh" >/dev/null 2>&1; echo $?)" "64"

# severity 가 사다리 밖이면 그 finding 을 건너뛰던 자리(실측). 같은 종류가 네 사이클 연속인데
# 등급 오타 하나로 streak 0 / status OK 가 나왔다 — **감지기가 눈이 먼 채 통과를 낸다.**
# 이건 이 감지기를 만들게 한 병과 같은 종류라(확인 못 한 것이 통과 방향으로 떨어진다) 65 로 거부한다.
ks_hist "$kstmp/sev-typo.jsonl" "test-vacuous:CRITCAL" "test-vacuous:CRITCAL" \
                                "test-vacuous:CRITCAL" "test-vacuous:CRITCAL"
ks_err() { bash "$DIR/kindstreak.sh" --history "$1" 2>&1 >/dev/null; }
assert_eq "미지 등급(오타) → exit65" "$(ks_rc "$kstmp/sev-typo.jsonl")" "65"
assert_eq "메시지가 어느 사이클·어떤 값인지 짚는다" \
  "$(ks_err "$kstmp/sev-typo.jsonl" | grep -c 'CRITCAL')" "1"
# 등급 누락도 같다 — 필드가 없는 것과 오타는 같은 실패다(둘 다 score.sh 가 붙였어야 할 값이 없다).
printf '{"iteration":1,"verdict":"RETRY","findings":[{"kind":"test-vacuous","dimension":"convention"}]}\n' \
  > "$kstmp/sev-missing.jsonl"
assert_eq "등급 누락 → exit65" "$(ks_rc "$kstmp/sev-missing.jsonl")" "65"
# **종료코드만으로는 이 둘이 안 잠긴다.** 등급 누락은 거부를 지워도 65 가 나온다 — 판정 jq 의
# `rank(null)` 이 죽어서다. 65 는 같고 사람에게 가는 말은 "이력을 못 읽는다" 라 어디를 볼지 못 짚는다.
# 그래서 **원인을 짚는 메시지**를 함께 단언한다. 종료코드가 맞다고 진단이 맞은 것은 아니다.
for ksf in sev-typo sev-missing; do
  assert_eq "$ksf: 원인을 severity 로 짚는다(파싱 실패로 뭉뚱그리지 않는다)" \
    "$(ks_err "$kstmp/$ksf.jsonl" | grep -c '사다리')" "1"
done
# 대조군 — 그 이력의 등급만 제대로 적으면 감지가 산다. 죽는 이유가 "늘 죽어서" 가 아니라 등급 때문이다.
ks_hist "$kstmp/sev-fixed.jsonl" "test-vacuous:CRITICAL" "test-vacuous:CRITICAL" \
                                 "test-vacuous:CRITICAL" "test-vacuous:CRITICAL"
assert_eq "등급만 고치면 감지된다"   "$(ks_f "$kstmp/sev-fixed.jsonl" .status)" "REPEATED_KIND"
assert_eq "그 연속은 4"              "$(ks_f "$kstmp/sev-fixed.jsonl" .streak)" "4"
# 그리고 **MINOR 는 여전히 오류가 아니다.** 규칙(건너뛰기)과 입력 오류(거부)를 가른 증거가 이 대조다.
assert_eq "MINOR 만 있는 사이클은 거부가 아니라 정상 rc0" "$(ks_rc "$kstmp/minor-gap.jsonl")" "0"
rm -rf "$kstmp"

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

# ── 10. merge_findings.sh 축별 병렬 checker 결과 병합 ─────────────
# checker 를 축으로 갈라 병렬로 띄우면 결과가 파일 여러 개로 나온다. 그 사이를 잇는 셸이고,
# **개수 검사가 존재 이유다** — 렌즈 하나가 죽어도 남은 둘의 결과는 형식이 멀쩡해서, 세지 않으면
# 그 축이 한 번도 점검되지 않은 채 PASS 로 간다. 단일 checker 의 `[ -s "$F" ]` 가드를 N 개로 넓힌 자리.
mgtmp="$(mktemp -d)"
cat > "$mgtmp/contract.json" <<'J'
{"base":"origin/main","reviewed":["src/A.kt"],"findings":[{"id":"c1","kind":"compat-response-break","dimension":"compatibility","location":"src/A.kt:10","evidence":"필드 삭제","weights":[],"force_await":false}]}
J
cat > "$mgtmp/safety.json" <<'J'
{"base":"origin/main","reviewed":["src/A.kt","src/B.kt"],"findings":[{"id":"c1","kind":"n-plus-1","dimension":"runtime","location":"src/B.kt:88","evidence":"루프 안 조회","weights":["hotpath"],"force_await":false}]}
J
cat > "$mgtmp/quality.json" <<'J'
{"base":"origin/main","reviewed":["src/B.kt"],"findings":[{"id":"s1","kind":"speculative-abstraction","dimension":"simplicity","location":"src/B.kt:12","evidence":"구현 하나뿐인 인터페이스","weights":[],"force_await":false}]}
J
merge3() { bash "$DIR/merge_findings.sh" --expect 3 \
  "contract=$mgtmp/contract.json" "safety=$mgtmp/safety.json" "quality=$mgtmp/$1"; }
merge_rc() { bash "$DIR/merge_findings.sh" "$@" >/dev/null 2>&1; echo $?; }

merged="$(merge3 quality.json)"
# id 는 렌즈 안에서만 고유하다 — 두 렌즈가 "c1" 을 냈고 접두가 없으면 반복 표시와 maker 지시가
# 서로 다른 finding 을 같은 이름으로 가리킨다.
assert_eq "merge: id 에 렌즈 접두" \
  "$(jq -r '[.findings[].id] | sort | join(",")' <<<"$merged")" "contract-c1,quality-s1,safety-c1"
assert_eq "merge: reviewed 합집합" \
  "$(jq -r '.reviewed | sort | join(",")' <<<"$merged")" "src/A.kt,src/B.kt"
# 병합 결과가 score.sh 의 입력 계약을 만족하고, 새 simplicity 차원이 rubric DIMFLOOR 에 실제로
# 연결돼 있나. floor 가 MAJOR 라야 RETRY_SOFT 가 되어 "고치려 시도하되 정체하면 사람 승인" 이 된다.
assert_eq "merge→score: simplicity floor = MAJOR" \
  "$(printf '%s' "$merged" | bash "$DIR/score.sh" | jq -r '.findings[] | select(.dimension=="simplicity") | .severity')" "MAJOR"

# 렌즈가 모자라면 남은 것만으로 채점하지 않는다. 이 한 줄이 병렬화가 만든 가장 큰 구멍을 막는다.
assert_eq "merge: 렌즈 2/3 이면 exit 65" \
  "$(merge_rc --expect 3 "contract=$mgtmp/contract.json" "safety=$mgtmp/safety.json")" "65"
# 렌즈마다 다른 diff 를 봤으면 합친 verdict 가 무엇에 대한 것인지 없다.
sed 's|origin/main|origin/develop|' "$mgtmp/quality.json" > "$mgtmp/badbase.json"
assert_eq "merge: base 불일치면 exit 65" "$(merge_rc --expect 3 \
  "contract=$mgtmp/contract.json" "safety=$mgtmp/safety.json" "quality=$mgtmp/badbase.json")" "65"
# 빈 파일·형식 위반은 그 축 checker 가 실패한 것이다. 어느 렌즈인지 이름으로 말해야 그 축만 다시 돈다.
: > "$mgtmp/empty.json"
assert_eq "merge: 빈 결과 파일이면 exit 65" "$(merge_rc --expect 3 \
  "contract=$mgtmp/contract.json" "safety=$mgtmp/safety.json" "quality=$mgtmp/empty.json")" "65"
echo '{"findings":"nope"}' > "$mgtmp/bad.json"
assert_eq "merge: findings 비배열이면 exit 65" "$(merge_rc --expect 3 \
  "contract=$mgtmp/contract.json" "safety=$mgtmp/safety.json" "quality=$mgtmp/bad.json")" "65"
# --expect 를 안 주면 개수 검사가 통째로 사라진다 — 그 호출 자체를 거부한다(사용법 오류 64).
assert_eq "merge: --expect 없으면 거부" "$(merge_rc "contract=$mgtmp/contract.json")" "64"
# 0 개를 기대하는 병합은 없다. 통과시키면 jq 가 파일 인자 없이 떠 stdin 을 기다리며 멈춘다.
assert_eq "merge: --expect 0 거부" "$(merge_rc --expect 0)" "64"

# **경로에 공백이 있어도 돌아야 한다.** 인자를 공백으로 이어 붙였다가 단어 분할로 되돌리면
# `~/My Projects/repo` 같은 경로가 두 인자로 쪼개져 개수 검사가 엉뚱하게 어긋난다(실측 exit 65).
# macOS 에서 흔한 경로라 이 시험이 그 회귀를 잠근다. `=` 가 경로 쪽에 더 있는 경우도 함께 본다 —
# 이름은 첫 `=` 앞까지, 경로는 첫 `=` 뒤 전부여야 한다.
mkdir -p "$mgtmp/sp ace" "$mgtmp/a=b"
cp "$mgtmp/contract.json" "$mgtmp/sp ace/f.json"
cp "$mgtmp/contract.json" "$mgtmp/a=b/f.json"
assert_eq "merge: 경로에 공백이 있어도 돈다" "$(merge_rc --expect 1 "lens=$mgtmp/sp ace/f.json")" "0"
assert_eq "merge: 경로에 = 가 있어도 돈다" "$(merge_rc --expect 1 "lens=$mgtmp/a=b/f.json")" "0"

# **눈먼 렌즈** — 병렬화가 만든 가장 조용한 구멍이다. `score.sh` 의 "findings 도 reviewed 도
# 비면 거부" 가드는 병합된 payload **하나**를 보는데, 병합이 reviewed 를 합집합으로 접으므로
# 한 렌즈만 채우면 그 가드가 만족된다. 그러면 나머지 축은 한 번도 안 봤는데 PASS 가 난다.
# 실측 대조: 같은 blind payload 를 단일 checker 계약으로 score.sh 에 직결하면 exit 65 인데,
# 병렬 경로만 통과했다. 그래서 축마다 따로 묻는다.
echo '{"base":"origin/main","reviewed":["src/Main.kt"],"findings":[]}' > "$mgtmp/seen.json"
echo '{"base":"origin/main","reviewed":[],"findings":[]}'              > "$mgtmp/blind.json"
cp "$mgtmp/seen.json" "$mgtmp/seen2.json"
assert_eq "merge: 눈먼 렌즈가 섞이면 exit 65" "$(merge_rc --expect 3 \
  "contract=$mgtmp/seen.json" "safety=$mgtmp/contract.json" "quality=$mgtmp/blind.json")" "65"
# 대조군 — 셋 다 깨끗하되 무엇을 봤는지 적었으면 통과해야 한다. 이 줄이 없으면 위 가드가
# 정상 "발견 없음" 까지 막는 쪽으로 조여져도 아무도 모른다.
assert_eq "merge: 셋 다 깨끗+reviewed 는 통과" "$(merge_rc --expect 3 \
  "contract=$mgtmp/seen.json" "safety=$mgtmp/seen2.json" "quality=$mgtmp/quality.json")" "0"

# `base` 키를 빼면 그 렌즈가 베이스 불일치 비교에서 조용히 빠진다(`.base // empty`) —
# 다른 ref 를 본 렌즈가 base 를 안 적기만 하면 그 검사가 정확히 그 경우에만 무력해진다.
echo '{"reviewed":["src/Main.kt"],"findings":[]}' > "$mgtmp/nobase.json"
assert_eq "merge: base 키 누락이면 exit 65" "$(merge_rc --expect 3 \
  "contract=$mgtmp/contract.json" "safety=$mgtmp/safety.json" "quality=$mgtmp/nobase.json")" "65"

# 개수 게이트는 **명령줄 인자 수**만 센다. 두 렌즈 프롬프트에 같은 출력 경로가 들어가면
# 나중 렌즈가 앞 파일을 덮어써 한 축이 통째로 사라져도 3개로 세어 통과한다.
assert_eq "merge: 같은 파일을 두 렌즈가 가리키면 exit 65" "$(merge_rc --expect 3 \
  "contract=$mgtmp/contract.json" "safety=$mgtmp/contract.json" "quality=$mgtmp/quality.json")" "65"
assert_eq "merge: 렌즈 이름이 겹치면 exit 65" "$(merge_rc --expect 2 \
  "x=$mgtmp/contract.json" "x=$mgtmp/safety.json")" "65"

# 같은 (차원·종류·위치)를 두 렌즈가 냈으면 하나로 접되, 가중은 합집합·사람 대기는 OR 로 보수적으로.
cat > "$mgtmp/dup.json" <<'J'
{"base":"origin/main","reviewed":["src/B.kt"],"findings":[{"id":"x9","kind":"n-plus-1","dimension":"runtime","location":"src/B.kt:88","evidence":"나도 봤다","weights":["money"],"force_await":true}]}
J
dup_merged="$(merge3 dup.json)"
assert_eq "merge: 중복 접기 — 건수" "$(jq '.findings | length' <<<"$dup_merged")" "2"
assert_eq "merge: 중복 접기 — weights 합집합" \
  "$(jq -r '.findings[] | select(.kind=="n-plus-1") | .weights | sort | join(",")' <<<"$dup_merged")" "hotpath,money"
assert_eq "merge: 중복 접기 — force_await OR" \
  "$(jq -r '.findings[] | select(.kind=="n-plus-1") | .force_await' <<<"$dup_merged")" "true"
rm -rf "$mgtmp"

# ── 11. 범위 계측(in_scope) — 세기만 하고 판정은 안 건드린다 ──────
# phase 가 "이번에 안 볼 표면"(`phases.json` 의 `non_goals`)을 미리 적고 렌즈가 finding 마다
# 안팎을 표시하면, "이 지적이 이번 목표 안인가" 라는 물음의 답이 사람 머릿속이 아니라 파일에 남는다.
# **지금은 등급을 안 내린다** — 근거가 한 저장소 한 루프뿐이라 재는 장치를 먼저 두는 단계다.
# 그래서 이 절의 핵심 단언은 마지막 둘(verdict 불변)이다. 그것이 깨지면 계측이 아니라 판정 변경이다.
sctmp="$(mktemp -d)"
sc_in='{"reviewed":["src/A.kt"],"findings":[
  {"id":"a","kind":"n-plus-1","dimension":"runtime","location":"src/A.kt:1","in_scope":true},
  {"id":"b","kind":"dead-code","dimension":"simplicity","location":"src/B.kt:2","in_scope":false},
  {"id":"c","kind":"convention-violation","dimension":"convention","location":"src/C.kt:3"},
  {"id":"d","kind":"unknown-thing","dimension":"security","location":"src/D.kt:4","in_scope":"false"}
]}'
sc_out="$(printf '%s' "$sc_in" | bash "$DIR/score.sh" | bash "$DIR/decide.sh")"
scf() { jq -r "$1" <<<"$sc_out"; }

assert_eq "범위: 명시 false 만 범위 밖으로 센다"   "$(scf '.out_of_scope.MAJOR')"    "1"
# 필드를 안 단 것과 오타 값(`"false"`)은 둘 다 unmarked 다. 오타를 범위 밖으로 읽으면 수치가
# 부풀고, 나중에 강등을 얹었을 때 그 오타 하나가 등급을 내린다.
assert_eq "범위: 필드 누락+오타 값 → unmarked 2"   "$(scf '.out_of_scope.unmarked')" "2"
assert_eq "범위: 오타 값은 범위 밖이 아니다"       "$(scf '.out_of_scope.CRITICAL')" "0"
# 세 갈래(안·밖·미표시)의 합이 총수와 같아야, unmarked 가 총수와 같은 회차를 "렌즈가 표시를
# 통째로 빠뜨렸다" 로 읽을 수 있다. 안 맞으면 0 이 "범위 밖 없음" 인지 "안 쟀음" 인지 갈리지 않는다.
assert_eq "범위: 안+밖+미표시 = 총 finding 수" \
  "$(jq -r '[.counts[]] | add' <<<"$sc_out")" \
  "$(jq -r '(1) + ([.out_of_scope.BLOCKER,.out_of_scope.CRITICAL,.out_of_scope.MAJOR,.out_of_scope.MINOR,.out_of_scope.unmarked] | add)' <<<"$sc_out")"

# **판정 불변 — 이 절의 계약이다.** 범위 표시가 있든 없든 verdict 는 등급만으로 정해진다.
assert_eq "범위: verdict 는 등급대로(RETRY)" "$(scf .verdict)" "RETRY"
# 대조군. 같은 입력에서 표시를 전부 지워도 판정이 같아야 한다 — 다르면 계측이 판정에 샌 것이다.
sc_bare="$(printf '%s' "$sc_in" | jq -c 'del(.findings[].in_scope)' | bash "$DIR/score.sh" | bash "$DIR/decide.sh")"
assert_eq "범위: 표시를 다 지워도 같은 verdict" "$(jq -r .verdict <<<"$sc_bare")" "$(scf .verdict)"
assert_eq "범위: 표시를 다 지워도 같은 counts"  "$(jq -c .counts <<<"$sc_bare")"  "$(jq -c .counts <<<"$sc_out")"
# 반대 대조군. 전부 범위 밖이라 표시해도 verdict 는 안 내려간다(강등이 없다는 뜻).
sc_all_out="$(printf '%s' "$sc_in" | jq -c '.findings |= map(.in_scope = false)' | bash "$DIR/score.sh" | bash "$DIR/decide.sh")"
assert_eq "범위: 전부 범위 밖이어도 verdict 그대로" "$(jq -r .verdict <<<"$sc_all_out")" "RETRY"

# 병합 쪽 3상태. `truthy` 로 접으면 안 단 것이 false 로 떨어져 계측이 거짓 수치를 낸다.
cat > "$sctmp/l1.json" <<'J'
{"base":"origin/main","reviewed":["src/A.kt"],"findings":[
 {"id":"1","kind":"k","dimension":"runtime","location":"src/A.kt:1","in_scope":false},
 {"id":"2","kind":"k2","dimension":"runtime","location":"src/B.kt:2","in_scope":false}]}
J
cat > "$sctmp/l2.json" <<'J'
{"base":"origin/main","reviewed":["src/A.kt"],"findings":[
 {"id":"1","kind":"k","dimension":"runtime","location":"src/A.kt:1","in_scope":true},
 {"id":"9","kind":"k9","dimension":"runtime","location":"src/Z.kt:9"}]}
J
sc_merged="$(bash "$DIR/merge_findings.sh" --expect 2 "contract=$sctmp/l1.json" "safety=$sctmp/l2.json")"
scm() { jq -r --arg id "$1" '.findings[] | select(.id==$id) | .in_scope | tostring' <<<"$sc_merged"; }
assert_eq "merge: 렌즈가 갈리면 범위 안이 이긴다" "$(scm contract-1)" "true"
assert_eq "merge: 단독 범위 밖은 그대로"          "$(scm contract-2)" "false"
assert_eq "merge: 안 단 것은 null 로 남는다"      "$(scm safety-9)"   "null"
rm -rf "$sctmp"

# ── 결과 ─────────────────────────────────────────────────────────
echo "────────────────────────"
echo "통과 $pass / 실패 $fail"
[ "$fail" -eq 0 ]
