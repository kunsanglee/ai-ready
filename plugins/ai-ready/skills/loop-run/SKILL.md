---
name: loop-run
description: 무인 검증 loop 의 사람 핸드오프 자동 루프. 사람이 작업을 맡기고 빠지면 maker(고침)→checker(독립 점검)→결정론 채점(rubric)→정체·brake 판정을 루브릭 통과·예산 소진·사람 대기까지 반복한다. 코드를 고치며 N회 돈다. severity 는 LLM 이 아니라 채점 셸이 매겨 judge 일관성을 보장. 호출 /loop-run [회차]. Use this skill when the user says "/loop-run", "루프 돌려", "핸드오프 루프", "이 작업 루프로 수렴시켜", or wants the verification loop to autonomously fix and converge. 1회 점검만은 /loop-review, 종료 후 교훈 수확은 /loop-lessons.
---

# loop-run — 사람 핸드오프 자동 루프

> 무인 검증 loop 의 사람 핸드오프 입구(human-on-the-loop). 호출: `/loop-run [회차]`. 1회 점검만은 `/loop-review`, 종료 후 교훈 수확은 `/loop-lessons`. 셋은 같은 판정부(loop-checker + 채점 셸 + BASE/LOCAL rubric)를 공유한다.

무인 검증 loop 의 **사람 핸드오프 입구(human-on-the-loop)** 다. 사람이 grill-me 로 작업 지시를 확정한 뒤 이 스킬에 넘기고 빠지면, **이 세션이 곧 maker** 가 되어 `maker(고침) → checker(독립 점검) → 채점 → 정체·brake 판정` 을 **루브릭 통과까지 자동 반복** 한다. 사람은 셋업하고 빠지고, 결과(수렴 diff)나 사람 호출(AWAIT_USER/brake)을 나중에 받는다.

무인 드라이버가 돌리는 것과 **똑같은 판정부**(단일 `loop-checker` + 결정론 채점 셸 + BASE/LOCAL rubric)를 쓴다. 다른 건 *방아쇠와 실행 호스트* 뿐이다 — 케이스2(Sentry 자동)는 agent 레포의 Node 드라이버가, 케이스3(이 스킬)은 Claude Code 백그라운드 세션이 같은 엔진을 돌린다.

> `/loop-review` 와 혼동 금지. `/loop-review` 는 **1회 점검 + 보고서, 코드 안 고침**(사람이 곧 루프). `/loop-run` 은 **코드를 고치며 N회 도는 루프**(사람이 빠짐). 점검 1회만 원하면 `/loop-review`, 수렴까지 맡기면 `/loop-run`.

## 🔌 plugin / 프로젝트 구조

- 이 스킬은 `ai-ready` plugin 의 일부다(과거 별도 loop-engine plugin 이었으나 v0.6.0 에서 통합). **도구 본체는 유저 레벨**(plugin), **프로젝트별 차이는 런타임 감지**가 채운다 — 별도 어댑터 파일을 만들지 않는다.
- plugin 번들(유저 레벨, `$CLAUDE_PLUGIN_ROOT` 하위): `_loop-engine/`(채점 셸 `score`·`decide`·`stall`·`lessons` + `lib.sh` 의 `loop_param` + `detect_build.py` 감지기), `_loop-engine/rubric.base.md`(BASE 루브릭·brake 단일 원천), `agents/loop-checker.md`·`agents/loop-lesson-synthesizer.md`(서브에이전트, `ai-ready:` namespace).
- 프로젝트 사실(빌드·테스트·린트 명령·티켓 패턴·베이스 브랜치·컨벤션 docs·지식층)은 Step 0 에서 `detect_build.py` 가 매니페스트·브랜치를 *읽어* 감지한다(읽기 전용, 파일로 굳히지 않음).
- 프로젝트 델타(레포에 커밋, 선택): `.loop/rubric.md`(LOCAL rubric — 그 스택 특유 kind. BASE 와 병합 채점). 없어도 BASE 만으로 돈다. 스택 특유 종류(예: ddl-safety)는 사람이 `/loop-lessons` 로 덧붙여 키운다 — 자동 생성하지 않는다.
- 지식층은 프로젝트의 `docs/ANTIPATTERNS.md`(ai-ready audit/apply 가 만들고 가꾸는 문서). checker 가 판정 기준으로 읽고, `/loop-lessons` 가 잡힌 실수를 거기에 덧붙인다. loop 은 그 문서를 *읽고 보탤* 뿐 따로 생성하지 않는다 — ai-ready 와 loop 이 같은 지식층을 공동 저작한다.
- 런타임 상태(`$CLAUDE_PROJECT_DIR/.loop/run/{ticket}/` 의 stall·history·started.epoch)는 루프 한정 휘발성 — `.gitignore` 로 `.loop/run/` 추적 제외. `.loop/rubric.md`(있으면)는 추적 대상.
- 외부 인증 없음(전부 로컬 git + 셸). brake 런별 오버라이드는 `LOOP_*` env 로(아래).

## 입력

1. **작업 지시(필수)**: grill-me 합의 요약 또는 spec 경로. "무엇을 만들/고칠지 + 완료 기준". 같은 세션 컨텍스트로 들어온다.
2. **비교 베이스**: `$LOOP_BASE_BRANCH`(Step 0 감지, 기본 `origin/main`). 점검 범위 = `$LOOP_BASE_BRANCH...HEAD + uncommitted`.
3. **작업 정의 문서 경로**(있으면): design/티켓 문서. checker 가 정합 층 점검에 쓴다. 없으면 "missing".
4. **시도 횟수 상한(선택)**: 사용자가 `/loop-run` 에 회차를 명시하면(예: "5회로", "--max-iter 5") 그 값을 쓴다. 없으면 rubric `max_iterations`(현재 10). 명시값도 하드 천장 10 으로 깎인다. 횟수를 늘려도 PASS·정체·시간·비가역 조기 종료는 그대로라 상한을 다 안 쓰고 일찍 끝날 수 있다 — 상한이지 목표가 아니다.

작업 지시가 모호하면 루프를 **시작하지 않는다** — checker 의 정합 층이 기준을 못 잡아 헛돈다. 사람이 빠지기 전에 grill-me 로 완료 기준부터 확정하게 한다.

## 핵심 불변 (절대 어기지 않는다)

1. **maker / checker 분리.** maker = 이 세션(오케스트레이터). checker = **매 사이클 새로 띄우는 `loop-checker` 서브에이전트**. checker 프롬프트에 **maker 의 구현 변명·합리화를 절대 넣지 않는다** — checker 는 diff·문서·ANTIPATTERNS 만 독립적으로 본다. 자기 코드를 자기가 후하게 보는 걸 구조로 막는 게 이 루프의 신뢰 근거다.
2. **severity 는 셸이 매긴다.** checker 는 `(종류·차원·가중플래그·위치·근거·force_await)` 만 태깅. 등급·verdict 는 결정론 셸이 낸다. checker 가 "괜찮아 보임" 해도 셸 판정을 따른다.
3. **게이트가 checker 보다 먼저, brake 가 평가보다 먼저.** 컴파일·테스트가 깨지면 checker 를 부르지 않고 즉시 maker 재진입. 매 사이클 시작에 brake(반복·시간) 부터 확인.
4. **종료는 점수 합산이 아니라 severity 게이트.** `BLOCKER 0 AND CRITICAL 0` 이라야 PASS. 가중 합("총점 높으니 통과") 금지.
5. **비가역 영역은 사람.** 운영 DB DML/DDL·돈·인가·대량발송·삭제에 닿으면(`AWAIT_USER`) 루프가 멈추고 사람을 부른다. 무인이어도 이 영역은 자동 통과 안 한다.

## brake (멈춤 장치) — 값은 rubric, 집행은 이 스킬

brake **값** 은 BASE rubric(`$CLAUDE_PLUGIN_ROOT/_loop-engine/rubric.base.md`)의 PARAMS 표가 단일 원천이다(프로젝트 LOCAL rubric 이 override 할 수 있다). 이 스킬이 `loop_param` 으로 읽어 **집행** 한다(집행은 회차를 가로지르는 주체의 몫 — 1회용 `/loop-review` 는 못 한다).

| brake | 출처 | 이 스킬의 집행 |
|---|---|---|
| `max_iterations` (기본 10, 사용자 명시 시 그 값) | rubric PARAMS 또는 호출 인자 | 매 사이클 후 `history.jsonl` 줄 수로 회차 세고 도달 시 멈춰 사람 호출. 명시값은 천장 10 으로 클램프 |
| `budget_minutes` (기본 60) | rubric PARAMS | 시작 epoch 영속 → 매 사이클 벽시계 경과 확인, 초과 시 멈춤 |
| `stall_threshold_*` / `regress_consecutive` | rubric PARAMS | `stall.sh` 가 상태 파일로 자가 집행. `STALLED`/`REGRESS_ESCALATE` 면 멈춤 |
| 하드코딩 천장 `ABS_CEIL=10` | 이 스킬 | rubric 오설정(max_iterations 폭주) 대비 백스톱. 무슨 일이 있어도 10회 초과 금지 |
| `budget_usd`(기본 100)·`budget_tokens`(1M) | rubric PARAMS | **케이스3은 종료 후 참고 백스톱**. 세션 도중 누적 비용을 정확히 못 읽어 회차별 정밀 차단 불가(그건 케이스2 agent 드라이버 몫). 실질 brake 는 회차·시간·정체 |

런별 오버라이드가 필요하면 호출 전에 env 로 덮어쓴다(예: `LOOP_PARAM_max_iterations` 대신 rubric 기본을 쓰되, 급하면 `MAX_ITER` 를 셋업에서 직접 지정). 기본값은 단일 통일됐다(10회 / 60분 / 1M 토큰 / $100).

## 작업 흐름

### Step 0. 셋업 (1회)

```bash
# 대상 프로젝트 루트: plugin 은 $CLAUDE_PROJECT_DIR 를 제공. 없으면(직접 실행 등) git 루트로 fallback.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"; cd "$PROJECT_ROOT"
# 채점 엔진: plugin 번들. $CLAUDE_PLUGIN_ROOT 는 ai-ready plugin 설치 위치.
ENG="$CLAUDE_PLUGIN_ROOT/_loop-engine"
# 프로젝트 사실을 런타임 감지(읽기 전용 — 파일 안 만든다). detect_build.py 는 매니페스트·브랜치만 읽어 JSON 을 낸다.
DET="$(python3 "$ENG/detect_build.py" --target "$PROJECT_ROOT")"
LOOP_BUILD_CMD="$(printf '%s' "$DET" | jq -r '.build_cmd // ""')"
LOOP_TEST_CMD="$(printf '%s' "$DET" | jq -r '.test_cmd // ""')"
LOOP_LINT_CMD="$(printf '%s' "$DET" | jq -r '.lint_cmd // ""')"
LOOP_TICKET_REGEX="$(printf '%s' "$DET" | jq -r '.ticket_regex // "[A-Z]+-[0-9]+"')"
LOOP_BASE_BRANCH="$(printf '%s' "$DET" | jq -r '.base_branch // "origin/main"')"
LOOP_KNOWLEDGE_LAYER="$(printf '%s' "$DET" | jq -r '.knowledge_layer // ""')"
LOOP_CONVENTION_DOCS="$(printf '%s' "$DET" | jq -r '(.convention_docs // []) | join(" ")')"
# 프로젝트 특유 심각도 규칙은 선택적 LOCAL rubric. 있으면 BASE 와 병합 채점, 없으면 BASE 만으로 돈다.
# 스택 특유 종류(예: postgres→ddl-safety)는 자동 생성하지 않는다 — 사람이 /loop-lessons 로 덧붙여 키운다.
if [ -f "$PROJECT_ROOT/.loop/rubric.md" ]; then export LOOP_RUBRIC_LOCAL="$PROJECT_ROOT/.loop/rubric.md"; fi
TICKET="$(git rev-parse --abbrev-ref HEAD | grep -oE "$LOOP_TICKET_REGEX" || echo loop)"
LOOP_DIR="$PROJECT_ROOT/.loop/run/$TICKET"; mkdir -p "$LOOP_DIR"
# 런타임 상태는 커밋 대상이 아니다 — .gitignore 에 .loop/run/ 멱등 추가(생성기가 없으니 여기서 보장).
grep -qxF '.loop/run/' "$PROJECT_ROOT/.gitignore" 2>/dev/null || printf '.loop/run/\n' >> "$PROJECT_ROOT/.gitignore"
STATE="$LOOP_DIR/stall.json"; HIST="$LOOP_DIR/history.jsonl"
# 같은 티켓 재실행이면 직전 상태가 남아 정체 감지를 오염시킨다 — 새 루프면 초기화.
: > "$HIST"; rm -f "$STATE"
date +%s > "$LOOP_DIR/started.epoch"
# brake 값. Bash 호출마다 새 셸이라 필요할 때 다시 읽는다.
ABS_CEIL=10
DEFAULT_ITER="$(source "$ENG/lib.sh" && loop_param max_iterations)"
# 시도 횟수: 사용자가 회차를 명시했으면 이 줄 위에서 MAX_ITER=N 으로 잡고(예: 5회면 MAX_ITER=5),
# 안 했으면 비워 두면 rubric 디폴트가 채운다. 어느 쪽이든 천장 10 으로 클램프(rubric 오설정·과도 입력 백스톱).
MAX_ITER="${MAX_ITER:-$DEFAULT_ITER}"
if [ "$MAX_ITER" -gt "$ABS_CEIL" ]; then echo "명시 회차 $MAX_ITER → 천장 $ABS_CEIL 로 제한"; MAX_ITER=$ABS_CEIL; fi
BUDGET_MIN="${BUDGET_MIN:-$(source "$ENG/lib.sh" && loop_param budget_minutes)}"
echo "loop-run 시작: ticket=$TICKET stack=$(printf '%s' "$DET" | jq -c '.stack') max_iter=$MAX_ITER (디폴트 $DEFAULT_ITER) budget_min=$BUDGET_MIN 천장 $ABS_CEIL"
```

> Bash 도구 호출은 호출마다 새 셸이라 env 가 안 남는다. 그래서 회차·시작시각을 **파일로 영속** 한다(`started.epoch`, `history.jsonl` 줄 수). 변수에 의존하지 말고 매 사이클 파일에서 다시 읽는다.

### Step 1. 사이클 시작 — brake 선확인 + 게이트 층

매 사이클 **맨 먼저** brake 부터 본다. 그 다음 결정론 게이트(컴파일·테스트). 게이트가 깨지면 checker 를 부르지 않는다.

```bash
ITER=$(wc -l < "$HIST" 2>/dev/null | tr -d ' '); ITER=${ITER:-0}
ELAPSED_MIN=$(( ( $(date +%s) - $(cat "$LOOP_DIR/started.epoch") ) / 60 ))
echo "사이클 진입: 완료 $ITER 회 / 경과 ${ELAPSED_MIN}분"
# brake: 반복·시간·천장. 도달했으면 평가 없이 종료(Step 5 의 '사람 호출'로).
#   if [ "$ITER" -ge "$MAX_ITER" ] || [ "$ITER" -ge "$ABS_CEIL" ] || [ "$ELAPSED_MIN" -ge "$BUDGET_MIN" ]; then → 종료
# 게이트: 컴파일 먼저(빠름), 통과하면 변경 모듈 테스트(또는 전체).
# 컴파일 게이트(빠름). 명령은 Step 0 감지가 준다. 빈 값이면 스킵하되 시끄럽게 알린다(silent skip 금지).
if [ -n "${LOOP_BUILD_CMD:-}" ]; then eval "$LOOP_BUILD_CMD"   # 실패 → 즉시 maker 재진입, checker 안 부름
else echo "loop: LOOP_BUILD_CMD 비어있음 — 빌드 시스템 미인식. 컴파일 게이트 스킵(셋업에서 LOOP_BUILD_CMD 직접 지정 가능)" >&2; fi
# 테스트 게이트. 감지 명령이 변경 모듈 한정이면 그게 게이트를 좁힌다.
if [ -n "${LOOP_TEST_CMD:-}" ]; then eval "$LOOP_TEST_CMD"
else echo "loop: LOOP_TEST_CMD 비어있음 — 테스트 게이트 스킵(셋업에서 LOOP_TEST_CMD 직접 지정 가능)" >&2; fi
```

- 컴파일·테스트 **실패** = 게이트 층 RETRY. checker 를 부르지 않고 **Step 6(maker 재진입)** 으로 가서 고친 뒤 이 사이클을 다시 연다. 단, 깨진 게 maker 가 못 고치는 운영 비가역(예: 마이그레이션 충돌)이면 사람 대기.
- 게이트 통과면 Step 2 로.
- 린트 게이트가 필요하면 Step 0 감지가 준 `$LOOP_LINT_CMD`(예: `./gradlew ktlintCheck`·`eslint .`·`ruff check`)를 게이트에 추가한다(빈 값이면 스킵).

### Step 2. checker 1회 호출 (독립·적대 시선)

`Agent` 툴로 `loop-checker` 를 **한 번** 호출한다. 프롬프트에 넘기는 것은 이것만:

- 원래 작업 정의(입력 1 요약, 1~3문장).
- 작업 정의 문서 경로(있으면, 없으면 "missing").
- 비교 베이스: `$LOOP_BASE_BRANCH`(기본 `origin/main`).

**maker(이 세션)의 합리화·구현 변명을 checker 프롬프트에 절대 넣지 마라**(핵심 불변 1). checker 는 자기 도구(Read/Grep/Glob/Bash)로 diff·컨벤션 문서·ANTIPATTERNS 를 직접 읽어 독립 판단한다. checker 는 마지막에 정확히 하나의 ```json 펜스 블록으로 `{base, findings:[...]}` 를 낸다. 그 블록만 추출한다.

### Step 3. 결정론 채점 + history append

추출한 checker JSON 을 임시 파일에 저장하고 채점 셸 파이프에 흘린다. **severity 는 셸이 매긴다 — checker 등급을 쓰지 않는다.**

```bash
F=$(mktemp)   # 추출한 {base, findings:[...]} 를 $F 에 기록
SCORED=$(bash "$ENG/score.sh" "$F")                              # finding 마다 severity·await 부여
VERDICT=$(printf '%s' "$SCORED" | bash "$ENG/decide.sh")         # {verdict, counts, await}
STALL=$(printf '%s' "$VERDICT"  | bash "$ENG/stall.sh" --state "$STATE")   # 정체 판정 + 상태 영속
ITER=$(( $(wc -l < "$HIST" 2>/dev/null | tr -d ' ') + 1 ))
jq -nc --argjson it "$ITER" \
       --argjson v "$VERDICT" \
       --argjson s "$SCORED" \
  '{iteration:$it, verdict:$v.verdict, findings:($s.findings // [])}' >> "$HIST"   # 한 줄 = 한 사이클
rm -f "$F"
V=$(printf  '%s' "$VERDICT" | jq -r .verdict)
ST=$(printf '%s' "$STALL"   | jq -r .status)
echo "사이클 $ITER → verdict=$V / stall=$ST / counts=$(printf '%s' "$VERDICT" | jq -c .counts)"
```

- 채점 셸이 `exit 65` 로 죽으면(빈/형식오류 입력) checker JSON 추출이 실패한 것이다 — **조용히 PASS 로 넘기지 말고** 멈춰 사람에게 "checker 출력 파싱 실패"로 보고. fail-loud 가 설계다.

### Step 4. verdict + stall 분기 (우선순위 순서대로)

아래 **위에서부터** 먼저 걸리는 것을 따른다.

1. `V == AWAIT_USER` → **멈춤, 사람 호출.** 비가역·자동화 금지 영역(BLOCKER/force_await). maker 가 손대면 안 된다.
2. brake 도달(`ITER >= MAX_ITER` 또는 `ITER >= ABS_CEIL` 또는 `ELAPSED_MIN >= BUDGET_MIN`) → **멈춤, 사람 호출.** 현재까지의 best 상태와 남은 finding 을 요약해 넘긴다.
3. `ST == STALLED` 또는 `ST == REGRESS_ESCALATE` → **멈춤, 사람 호출.** 헛바퀴/악화. `RETRY_SOFT`(MAJOR 만)로 정체한 경우 사람에게 "이 MAJOR 안고 통과할까?" 승인 옵션을 같이 제시.
4. `V == PASS` → **종료(수렴).** Step 5 로.
5. `V == RETRY` 또는 `V == RETRY_SOFT` (그리고 위 brake/stall 미도달) → **Step 6(maker 재진입)** 로 가서 finding 을 고치고 Step 1 로 루프.

### Step 5. 종료 처리

- **PASS(수렴)**: 사람에게 결과 보고 — 통과 verdict, 사이클 수, 남은 MINOR(기록만), 변경 요약. PR 인계는 **보류 합의 사항**이라 자동으로 올리지 않는다(spec). feature-wrapup 또는 `/pr` 로 사람이 마감하도록 제안하고, 원하면 그때 진행.
- **AWAIT_USER / STALLED / REGRESS / brake**: 멈춘 이유 + 현재 남은 finding(등급 내림차순) + 다음 행동 후보(고쳐서 재개 / 이 등급 안고 통과 승인 / 작업 정의 재정렬)를 사람에게 핑. 이 경우 코드는 마지막 maker 시도 상태로 워크트리에 남는다.
- 종료 후(특히 PASS·사람 멈춤 모두) `/loop-lessons` 로 이 루프의 `history.jsonl` 에서 잡힌 실수를 ANTIPATTERNS 후보로 올릴지 사람에게 제안한다(선순환 닫기). 강제 아님.

### Step 5-1. 종료 정리 (런타임 상태 폐기)

`$CLAUDE_PROJECT_DIR/.loop/run/{ticket}/`(history·stall·started.epoch)는 루프 한정 휘발성이다. **마무리하면 남기지 않는다.** 단 lesson 흐름이 `history.jsonl` 을 입력으로 쓰므로 **폐기는 반드시 lesson 종합 다음**이다 — 종합 전에 지우면 선순환 입력이 사라진다.

```bash
rm -rf "$LOOP_DIR"   # = $CLAUDE_PROJECT_DIR/.loop/run/{ticket}. lesson 종합(또는 사람이 생략 결정) 후에만.
```

- **PASS(수렴)**: 결과 보고 → (선택) `/loop-lessons` → 그 다음 폐기. 깨끗이 비운다.
- **사람 멈춤(AWAIT_USER/STALLED/brake)으로 재개 여지가 있으면 바로 폐기하지 않는다.** `stall.json`·`started.epoch` 가 남아 있어야 이어서 돌릴 수 있다(없으면 다음 시작이 INIT 로 리셋돼 정체 감지가 무력화). 사람이 그 작업을 닫기로 하면(고침 완료 또는 포기) 그때 lesson 종합 후 폐기.
- 워크트리째 버리는 경우엔 `.loop/run/` 도 같이 사라지니 별도 폐기가 불필요하지만, **메인 체크아웃이나 워크트리를 남겨 둔 경우엔 이 단계가 정리를 보장**한다. 워크트리 수명에 기대지 않는다.

### Step 6. maker 재진입 (고침)

이 세션이 maker 다. Step 3 의 `$SCORED` finding(등급 내림차순)을 보고 **CRITICAL → MAJOR 순으로 실제 코드를 고친다**. 고치고 나면 **Step 1** 로 돌아가 다음 사이클을 연다(게이트부터 다시). 매 회차 코드가 바뀌어야 루프가 의미 있다 — 같은 결과를 N번 내지 않는다.

- **코드를 작성·수정하면 그 변경분에 대응하는 테스트도 함께 작성한다.** 단 이 강제는 LOCAL rubric 의 KINDS 표가 그 프로젝트에 `test-missing`(convention, CRITICAL) 을 등록한 경우에만 작동한다 — 테스트 문화·도구는 프로젝트마다 다르니 스킬 본문이 아니라 rubric 이 결정한다. 작성 직전에 Step 0 감지가 준 `$LOOP_CONVENTION_DOCS`(공백 구분 경로 목록 — 테스트 규약·네이밍·에러 처리 등 ai-ready 가 만든 문서) 중 변경 표면에 닿는 문서를 **그 시점에 lazy 하게 Read** 해 컨벤션을 따른다. 목록이 비었거나 파일이 없으면 그 단계를 건너뛴다. 작성한 테스트는 Step 1 의 테스트 게이트(`$LOOP_TEST_CMD`)에 포함돼 실제로 실행·검증된다.
- MINOR 만 남았으면 보통 PASS 라 여기 오지 않는다. RETRY_SOFT(MAJOR)는 고치되, 정체로 멈추면 사람 승인으로 통과 가능.
- 고칠 수 없거나 고치면 안 되는 finding(force_await·비가역)은 maker 가 만지지 말고 AWAIT_USER 로 사람에게.

## 백그라운드 세션 실행

사람이 빠져도 루프가 계속 돌게 하려면 이 세션을 **백그라운드 잡**으로 띄운다. grill-me 로 spec 을 확정한 *그 세션에서* `/loop-run` 을 걸고 사용자는 자리를 비운다. 루프가 PASS·brake·AWAIT_USER 에 닿으면 결과/호출을 남긴다. 케이스3 의 매력은 "이미 Claude 와 대화 중이니 그대로 맡긴다" 는 매끄러움이다 — grill-me → loop-run 이 한 세션에서 이어진다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `loop: base rubric 없음` | plugin 번들 `rubric.base.md` 부재(설치 손상) | plugin 재설치, 또는 `LOOP_RUBRIC_BASE` 로 pin |
| 빌드/테스트 명령이 비어 게이트 스킵 | `detect_build.py` 가 빌드 시스템 미인식(unknown) | 매니페스트(build.gradle/package.json 등) 확인. 비표준이면 셋업에서 `LOOP_BUILD_CMD`/`LOOP_TEST_CMD` 를 직접 지정 |
| `python3` / `detect_build.py` 오류 | python3 미설치 또는 감지기 부재(설치 손상) | python3 설치 확인. plugin 재설치(감지기는 `_loop-engine/detect_build.py`) |
| `score.sh: 입력 형식 오류 — exit 65` | checker JSON 추출 실패(빈/null/형식오류) | 마지막 ```json 블록만 정확히 추출했는지 확인. 멈추고 보고 — PASS 로 넘기지 말 것 |
| 정체 감지가 매번 INIT | 사이클 간 `stall.json` 이 사라짐(셸 종료마다 리셋한 경우) | `--state "$STATE"` 경로가 사이클 간 동일한지 확인. Step 0 에서만 초기화 |
| 회차가 안 늘어남 | `history.jsonl` append 누락 | Step 3 의 append 가 매 사이클 1줄 추가하는지 확인(줄 수 = 회차) |
| 무한 같은 finding | maker 가 안 고치고 재진입 | Step 6 에서 실제 코드를 바꿨는지 확인. 못 고치는 finding 은 AWAIT_USER |
| 모든 finding 이 CRITICAL | checker 가 dimension 오타 | score.sh 가 모르는 dimension 을 보수적으로 CRITICAL 처리. checker dimension 값 점검 |

## Non-Goals

- **1회 점검·보고** — 그건 `/loop-review`(사람이 곧 루프). 이 스킬은 코드를 고치며 수렴까지 돈다.
- **lesson → ANTIPATTERNS 반영** — 종료 후 별 스킬 `/loop-lessons`(사람 승인 게이트)가 처리. 이 스킬은 history 만 남긴다.
- **회차별 토큰·달러 정밀 차단** — 케이스2 의 agent 헤드리스 드라이버 몫(세션 밖에서 회차마다 비용 확인). 케이스3 은 회차·시간·정체 + 종료 후 비용 백스톱.
- **Sentry 자동 트리거** — 그건 케이스2. 이 스킬은 사람이 명시적으로 거는 핸드오프 입구(케이스3)다.
- **severity 를 LLM 이 매기는 것** — 결정론 셸이 매긴다(같은 코드 = 같은 등급).
