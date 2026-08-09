---
name: loop-run
description: 무인 검증 loop 의 사람 핸드오프 자동 루프. 사람이 작업을 맡기고 빠지면 maker(고침)→checker(독립 점검)→결정론 채점(rubric)→정체·brake 판정을 루브릭 통과·예산 소진·사람 대기까지 반복한다. 코드를 고치며 N회 돈다. severity 는 LLM 이 아니라 채점 셸이 매겨 judge 일관성을 보장. 호출 /loop-run [회차]. Use this skill when the user says "/loop-run", "루프 돌려", "핸드오프 루프", "이 작업 루프로 수렴시켜", or wants the verification loop to autonomously fix and converge. 1회 점검만은 /loop-review, 종료 후 교훈 수확은 /loop-lessons.
---

# loop-run — 사람 핸드오프 자동 루프

> 무인 검증 loop 의 사람 핸드오프 입구(human-on-the-loop). 호출: `/loop-run [회차]`. 1회 점검만은 `/loop-review`, 종료 후 교훈 수확은 `/loop-lessons`. 셋은 같은 판정부(loop-checker + 채점 셸 + BASE/LOCAL rubric)를 공유한다.

무인 검증 loop 의 **사람 핸드오프 입구(human-on-the-loop)** 다. 사람이 grill-me 로 작업 지시를 확정한 뒤 이 스킬에 넘기고 빠지면, **이 세션이 오케스트레이터** 가 되어 `maker(고침) → 게이트 → checker(독립 점검) → 채점 → 정체·brake 판정` 을 **루브릭 통과까지 자동 반복** 한다. maker 와 checker 는 둘 다 매 사이클 새로 띄우는 서브에이전트이고, **이 세션은 코드를 쓰지 않는다.** 사람은 작업 지시를 확인하고 빠지고, 결과(수렴 diff)나 사람 호출(AWAIT_USER/brake)을 나중에 받는다.

무인 드라이버가 돌리는 것과 **똑같은 판정부**(단일 `loop-checker` + 결정론 채점 셸 + BASE/LOCAL rubric)를 쓴다. 다른 건 *방아쇠와 실행 호스트* 뿐이다 — 케이스2(Sentry 자동)는 agent 레포의 Node 드라이버가, 케이스3(이 스킬)은 Claude Code 백그라운드 세션이 같은 엔진을 돌린다.

> `/loop-review` 와 혼동 금지. `/loop-review` 는 **1회 점검 + 보고서, 코드 안 고침**(사람이 곧 루프). `/loop-run` 은 **코드를 고치며 N회 도는 루프**(사람이 빠짐). 점검 1회만 원하면 `/loop-review`, 수렴까지 맡기면 `/loop-run`.

## 🔌 plugin / 프로젝트 구조

- 이 스킬은 `ai-ready` plugin 의 일부다(과거 별도 loop-engine plugin 이었으나 v0.6.0 에서 통합). **도구 본체는 유저 레벨**(plugin), **프로젝트별 차이는 런타임 감지**가 채운다 — 별도 어댑터 파일을 만들지 않는다.
- plugin 번들(유저 레벨, `$CLAUDE_PLUGIN_ROOT` 하위): `_loop-engine/`(채점 셸 `score`·`decide`·`stall`·`lessons` + `lib.sh` 의 `loop_param` + `detect_build.py` 감지기 + `gate_parse.py` 게이트 실패 파서), `_loop-engine/rubric.base.md`(BASE 루브릭·brake 단일 원천), `agents/loop-maker.md`·`agents/loop-checker.md`·`agents/loop-spec-checker.md`·`agents/loop-lesson-synthesizer.md`(서브에이전트, `ai-ready:` namespace). `loop-maker` 와 `loop-spec-checker` 는 `loop-build` 와 공유한다 — maker 는 스핀 패턴만 다르고 행동 규칙이 같은 정의고, spec-checker 는 두 스킬의 입구가 같은 물음("이 지시로 사람 없이 돌 수 있나")을 갖기 때문이다.
- 프로젝트 사실(빌드·테스트·린트 명령·티켓 패턴·베이스 브랜치·컨벤션 docs·지식층)은 Step 0 에서 `detect_build.py` 가 매니페스트·브랜치를 *읽어* 감지한다(읽기 전용 — 커밋되는 어댑터 파일은 만들지 않는다. 감지 결과는 루프 한정 휘발 스냅숏 `params.env` 로만 남고 종료 시 폐기된다).
- 프로젝트 델타(레포에 커밋, 선택): `.loop/rubric.md`(LOCAL rubric — 그 스택 특유 kind. BASE 와 병합 채점). 없어도 BASE 만으로 돈다. 스택 특유 종류(예: ddl-safety)는 사람이 `/loop-lessons` 로 덧붙여 키운다 — 자동 생성하지 않는다.
- 지식층은 프로젝트의 `docs/ANTIPATTERNS.md`(ai-ready audit/apply 가 만들고 가꾸는 문서). checker 가 판정 기준으로 읽고, `/loop-lessons` 가 잡힌 실수를 거기에 덧붙인다. loop 은 그 문서를 *읽고 보탤* 뿐 따로 생성하지 않는다 — ai-ready 와 loop 이 같은 지식층을 공동 저작한다.
- 런타임 상태(`$CLAUDE_PROJECT_DIR/.loop/run/{ticket}/` 의 stall·history·started.epoch·params.env·gate.fail·checker-findings·scored·gate-queue·게이트 출력 원문·tree.snapshot·brief·spec-gaps, 그리고 브랜치별 포인터 `.loop/run/.active-{브랜치}`)는 루프 한정 휘발성 — `.gitignore` 로 `.loop/run/` 추적 제외. `.loop/rubric.md`(있으면)는 추적 대상.
- 외부 인증 없음(전부 로컬 git + 셸). brake 런별 오버라이드는 `LOOP_*` env 로(아래).

## 입력

1. **작업 지시(필수, 파일)**: spec·design 문서 경로. "무엇을 만들/고칠지 + 완료 기준". **파일이어야 한다** — maker 가 서브에이전트라 이 세션의 대화 맥락을 물려받지 못하고, 회차마다 요약을 다시 만들면 5회차 지시가 1회차와 달라진다. 파일이면 재개가 지시까지 함께 복원한다(대화 맥락은 세션이 끝나면 사라진다).
   - **파일이 없으면 오케스트레이터가 쓴다.** grill-me 직후처럼 합의가 대화에만 있으면, Step 0 에서 그 맥락을 `$LOOP_DIR/brief.md` 로 한 번 옮기고 **사람에게 보여 확인받은 뒤** 루프를 시작한다. 무인으로 열 회차를 돌릴 작업의 지시를 사람이 한 번도 보지 않고 떠나는 것이 원래 위태로운 자리였다.
   - 이 경로가 checker 의 정합 층 기준이자 maker 의 구현 근거다. 하나의 파일이 둘 다 맡는다.
2. **비교 베이스**: `$LOOP_BASE_BRANCH`(Step 0 감지, 기본 `origin/main`). 점검 범위 = `$LOOP_BASE_BRANCH...HEAD + uncommitted`.
3. ~~작업 정의 문서 경로~~: 입력 1로 합쳤다. 종전에는 선택이었고 없으면 checker 에게 "missing" 을 넘겼는데, maker 가 서브에이전트가 되면서 그 문서가 없으면 maker 도 구현 근거가 없어 필수가 됐다.
4. **시도 횟수 상한(선택)**: 사용자가 `/loop-run` 에 회차를 명시하면(예: "5회로", "--max-iter 5") 그 값을 쓴다. 없으면 rubric `max_iterations`(현재 5). 명시값도 하드 천장 10 으로 깎인다. 횟수를 늘려도 PASS·정체·시간·비가역 조기 종료는 그대로라 상한을 다 안 쓰고 일찍 끝날 수 있다 — 상한이지 목표가 아니다.

작업 지시가 모호하면 루프를 **시작하지 않는다** — checker 의 정합 층이 기준을 못 잡고 maker 도 구현 근거가 없어 헛돈다. 사람이 빠지기 전에 grill-me 로 완료 기준부터 확정하게 한다. **Step 0-1 이 그 확인을 사람 게이트로 만든다.**

## 핵심 불변 (절대 어기지 않는다)

1. **maker / checker 분리, 그리고 둘 다 오케스트레이터가 아니다.** maker = **매 사이클 새로 띄우는 `loop-maker` 서브에이전트**. checker = **매 사이클 새로 띄우는 `loop-checker` 서브에이전트**. **이 세션은 코드를 쓰지 않는다** — 스핀하고 셸을 돌리고 판정을 읽고 분기한다. `loop-build` 와 codex 쪽 두 스킬이 이미 이 구조이고 이 스킬만 달랐다. checker 프롬프트에 **maker 의 구현 변명·합리화를 절대 넣지 않는다** — checker 는 diff·문서·ANTIPATTERNS 만 독립적으로 본다. 자기 코드를 자기가 후하게 보는 걸 막는 게 이 루프의 신뢰 근거다. 이 독립성은 별 컨텍스트 서브에이전트 + checker 의 Edit/Write 부재 + checker 본문의 "쓰기 계열 Bash 금지" 지시로 강제한다 — 도구 목록만으로 완벽히 보장되진 않으니(Bash 로 우회 가능) checker 에 쓰기 금지를 명시로 못박았다.
2. **severity 는 셸이 매긴다.** checker 는 `(종류·차원·가중플래그·위치·근거·force_await)` 만 태깅. 등급·verdict 는 결정론 셸이 낸다. checker 가 "괜찮아 보임" 해도 셸 판정을 따른다.
3. **게이트가 checker 보다 먼저, brake 가 평가보다 먼저.** 컴파일·테스트가 깨지면 checker 를 부르지 않고 즉시 maker 를 다시 스핀한다. 매 사이클 시작에 brake(반복·시간) 부터 확인.
4. **종료는 점수 합산이 아니라 severity 게이트.** `BLOCKER 0 AND CRITICAL 0` 이라야 PASS. 가중 합("총점 높으니 통과") 금지.
5. **비가역 영역은 사람.** 운영 DB DML/DDL·돈·인가·대량발송·삭제에 닿으면(`AWAIT_USER`) 루프가 멈추고 사람을 부른다. 무인이어도 이 영역은 자동 통과 안 한다.

## brake (멈춤 장치) — 값은 rubric, 집행은 이 스킬

brake **값** 은 BASE rubric(`$CLAUDE_PLUGIN_ROOT/_loop-engine/rubric.base.md`)의 PARAMS 표가 단일 원천이다(프로젝트 LOCAL rubric 이 override 할 수 있다). 이 스킬이 `loop_param` 으로 읽어 **집행** 한다(집행은 회차를 가로지르는 주체의 몫 — 1회용 `/loop-review` 는 못 한다).

> **집행 주체 주의(과장 금지)**: 아래 brake 중 *코드로 자가 집행* 되는 것은 `stall.sh`(정체) 한 곳뿐이다. 회차·시간·천장 brake 는 이 스킬을 모는 LLM 오케스트레이터가 **매 사이클 Step 1 의 brake 블록을 실제로 실행** 해야 강제된다 — 지시문이 아니라 실행에 달려 있다. 그래서 Step 1 의 brake 는 주석 의사코드가 아니라 실행 블록으로 둔다.

| brake | 출처 | 이 스킬의 집행 |
|---|---|---|
| `max_iterations` (기본 5, 사용자 명시 시 그 값) | rubric PARAMS 또는 호출 인자 | 매 사이클 `history.jsonl` 줄 수 + 게이트 실패 카운터(`gate.fail`)를 합산해 시도를 세고 도달 시 멈춰 사람 호출. 명시값은 천장 10 으로 클램프 |
| `budget_minutes` (기본 120) | rubric PARAMS | 시작 epoch 영속 → 매 사이클 벽시계 경과 확인, 초과 시 멈춤 |
| `stall_threshold_*` / `regress_consecutive` | rubric PARAMS | `stall.sh` 가 상태 파일로 자가 집행. `STALLED`/`REGRESS_ESCALATE` 면 멈춤 |
| 하드코딩 천장 `ABS_CEIL=10` | 이 스킬 | rubric 오설정(max_iterations 폭주) 대비 백스톱. 무슨 일이 있어도 10회 초과 금지 |
| `budget_usd`(기본 500)·`budget_tokens`(5M) | rubric PARAMS | **케이스3은 종료 후 참고 백스톱**. 세션 도중 누적 비용을 정확히 못 읽어 회차별 정밀 차단 불가(그건 케이스2 agent 드라이버 몫). 실질 brake 는 회차·시간·정체 |

런별 오버라이드가 필요하면 호출 전에 env 로 덮어쓴다(예: `LOOP_PARAM_max_iterations` 대신 rubric 기본을 쓰되, 급하면 `MAX_ITER` 를 셋업에서 직접 지정). 기본값은 단일 통일됐다(5회 / 120분 / 5M 토큰 / $500).

## 작업 흐름

### Step 0. 셋업 (1회)

```bash
# 대상 프로젝트 루트: plugin 은 $CLAUDE_PROJECT_DIR 를 제공. 없으면(직접 실행 등) git 루트로 fallback.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"; cd "$PROJECT_ROOT"
# 채점 엔진: plugin 번들. **$CLAUDE_PLUGIN_ROOT 는 Bash 도구의 셸에 없다** — 스킬 본문을 만들 때
# 치환되는 값이라 자식 셸로 안 내려간다(실측). 그대로 쓰면 ENG=/_loop-engine 이 되어 조용히 없는
# 경로를 가리킨다. 이 스킬 본문 맨 위의 "Base directory for this skill" 값을 그대로 넣는다.
SKILL_DIR="<이 스킬 본문 첫머리의 Base directory 를 그대로 넣는다>"
ENG="$(cd "$SKILL_DIR/../.." && pwd)/_loop-engine"
[ -f "$ENG/lib.sh" ] || { echo "loop: 채점 엔진을 못 찾았다 ($ENG) — base directory 확인" >&2; exit 65; }
# 프로젝트 사실을 런타임 감지(읽기 전용 — 파일 안 만든다). detect_build.py 는 매니페스트·브랜치만 읽어 JSON 을 낸다.
DET="$(python3 "$ENG/detect_build.py" --target "$PROJECT_ROOT")"
LOOP_BUILD_CMD="$(printf '%s' "$DET" | jq -r '.build_cmd // ""')"
LOOP_TEST_CMD="$(printf '%s' "$DET" | jq -r '.test_cmd // ""')"
LOOP_LINT_CMD="$(printf '%s' "$DET" | jq -r '.lint_cmd // ""')"
LOOP_TICKET_REGEX="$(printf '%s' "$DET" | jq -r '.ticket_regex // "[A-Z]+-[0-9]+"')"
LOOP_BASE_BRANCH="$(printf '%s' "$DET" | jq -r '.base_branch // "origin/main"')"
# 베이스 ref 가 실제 존재하는지 확인 — 오감지하면 빈 diff 가 거짓 PASS 로 둔갑한다(checker 가 reviewed 를 채우면 채점은 빈 findings 를 PASS 로 낸다).
if ! git rev-parse --verify --quiet "$LOOP_BASE_BRANCH^{commit}" >/dev/null 2>&1; then
  echo "loop: 베이스 ref '$LOOP_BASE_BRANCH' 확인 불가 — git fetch 후 재확인" >&2
  git fetch --quiet origin 2>/dev/null || true
  if ! git rev-parse --verify --quiet "$LOOP_BASE_BRANCH^{commit}" >/dev/null 2>&1; then
    echo "loop: 베이스 브랜치 미확인 — 멈추고 사람 호출(LOOP_BASE_BRANCH=... 로 지정 필요). PASS 로 넘기지 말 것" >&2
    exit 3
  fi
fi
LOOP_KNOWLEDGE_LAYER="$(printf '%s' "$DET" | jq -r '.knowledge_layer // ""')"
LOOP_CONVENTION_DOCS="$(printf '%s' "$DET" | jq -r '(.convention_docs // []) | join(" ")')"
# 프로젝트 특유 심각도 규칙은 선택적 LOCAL rubric. 있으면 BASE 와 병합 채점, 없으면 BASE 만으로 돈다.
# 스택 특유 종류는 자동 생성하지 않는다 — 사람이 /loop-lessons 로 덧붙여 키운다.
# (ddl-safety 는 0.9.7 부터 BASE 금지행이라 예시에서 뺐다 — LOCAL 에 다시 적으면 등급만 낮아진다.)
if [ -f "$PROJECT_ROOT/.loop/rubric.md" ]; then export LOOP_RUBRIC_LOCAL="$PROJECT_ROOT/.loop/rubric.md"; fi
# 티켓 키가 상태 디렉터리(LOOP_DIR)를 가른다. JIRA 키 없을 때 'loop' 단일 폴백은 동시 실행·다중
# 워크트리에서 같은 LOOP_DIR 를 공유해 정체 상태(stall.json)가 충돌한다 — 브랜치 슬러그로 분리한다.
# 감지기는 티켓 접두어를 대문자로 정규화해 세므로, 소문자 브랜치(feature/cce-123)와 어긋나지 않게
# 브랜치도 대문자로 올려 매칭한다(비대칭이면 소문자 티켓 브랜치가 전부 슬러그 폴백으로 빠진다).
TICKET="$(git rev-parse --abbrev-ref HEAD | tr '[:lower:]' '[:upper:]' | grep -oE "$LOOP_TICKET_REGEX" | head -1 || true)"
[ -n "$TICKET" ] || TICKET="loop-$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$PROJECT_ROOT/.loop/run/$TICKET"; mkdir -p "$LOOP_DIR"
# 런타임 상태는 커밋 대상이 아니다 — .gitignore 에 .loop/run/ 멱등 추가(생성기가 없으니 여기서 보장).
# 기존 파일 끝에 개행이 없으면 >> 가 마지막 줄과 붙여 두 규칙이 다 깨진다 — 개행부터 보정한다.
if ! grep -qxF '.loop/run/' "$PROJECT_ROOT/.gitignore" 2>/dev/null; then
  [ -f "$PROJECT_ROOT/.gitignore" ] && [ -n "$(tail -c1 "$PROJECT_ROOT/.gitignore")" ] && echo >> "$PROJECT_ROOT/.gitignore"
  printf '.loop/run/\n' >> "$PROJECT_ROOT/.gitignore"
fi
STATE="$LOOP_DIR/stall.json"; HIST="$LOOP_DIR/history.jsonl"
# 작업 지시는 파일이어야 한다 — maker 가 서브에이전트라 이 세션의 대화를 물려받지 못한다(입력 1).
# spec 경로를 사용자가 줬으면 그 값으로 아래 LOOP_DESIGN_REF 를 잡는다. 안 줬으면 비워 둔다.
LOOP_DESIGN_REF="${LOOP_DESIGN_REF:-}"
if [ -n "$LOOP_DESIGN_REF" ] && [ ! -f "$LOOP_DESIGN_REF" ]; then
  echo "loop: 지정한 작업 지시 파일 '$LOOP_DESIGN_REF' 가 없다 — 경로 확인. PASS 로 넘기지 말 것" >&2; exit 3
fi
if [ -z "$LOOP_DESIGN_REF" ]; then
  echo "loop: 작업 지시 파일 없음 — 이 대화의 합의를 $LOOP_DIR/brief.md 로 옮기고 사람 확인을 받은 뒤 계속한다" >&2
  LOOP_DESIGN_REF="$LOOP_DIR/brief.md"   # 아래 브리프 절차로 채운다. 채우기 전엔 Step 1 로 넘어가지 않는다.
fi
# 같은 티켓 재실행이면 직전 상태가 남아 정체 감지를 오염시킨다 — 새 루프면 초기화(게이트 실패 카운터 포함).
# **재개**(사람 멈춤 AWAIT_USER/STALLED/brake 후 이어가기)는 이 Step 0 자체를 다시 실행하지 않는다 —
# 아래 초기화와 params.env 재작성이 재개 상태(회차·정체·loop-build 의 phase 오버라이드)를 파괴한다.
# 재개는 브랜치별 포인터(.loop/run/.active-{브랜치})와 params.env 가 살아 있는지 확인하고 곧장 Step 1 로 간다.
: > "$HIST"; rm -f "$STATE" "$LOOP_DIR/gate.fail"
date +%s > "$LOOP_DIR/started.epoch"
# brake 값. Bash 호출마다 새 셸이라 필요할 때 다시 읽는다.
ABS_CEIL=10
DEFAULT_ITER="$(source "$ENG/lib.sh" && loop_param max_iterations)"
# 시도 횟수: 사용자가 회차를 명시했으면 이 줄 위에서 MAX_ITER=N 으로 잡고(예: 5회면 MAX_ITER=5),
# 안 했으면 비워 두면 rubric 디폴트가 채운다. 어느 쪽이든 천장 10 으로 클램프(rubric 오설정·과도 입력 백스톱).
MAX_ITER="${MAX_ITER:-$DEFAULT_ITER}"
if [ "$MAX_ITER" -gt "$ABS_CEIL" ]; then echo "명시 회차 $MAX_ITER → 천장 $ABS_CEIL 로 제한"; MAX_ITER=$ABS_CEIL; fi
BUDGET_MIN="${BUDGET_MIN:-$(source "$ENG/lib.sh" && loop_param budget_minutes)}"
# Bash 호출마다 새 셸이라 위 변수들은 다음 호출에 안 남는다 — 전부 파일로 영속해 매 Step 이 재유도한다.
# (빈 MAX_ITER 로 brake 정수 비교가 실패하면 brake 가 조용히 무력화된다 — 이 파일이 그 구멍을 막는다.)
{
  printf 'ENG=%q\nLOOP_DIR=%q\nSTATE=%q\nHIST=%q\n' "$ENG" "$LOOP_DIR" "$STATE" "$HIST"
  printf 'LOOP_BASE_BRANCH=%q\nLOOP_BUILD_CMD=%q\nLOOP_TEST_CMD=%q\nLOOP_LINT_CMD=%q\n' "$LOOP_BASE_BRANCH" "$LOOP_BUILD_CMD" "$LOOP_TEST_CMD" "$LOOP_LINT_CMD"
  printf 'LOOP_CONVENTION_DOCS=%q\nLOOP_KNOWLEDGE_LAYER=%q\nLOOP_RUBRIC_LOCAL=%q\n' "$LOOP_CONVENTION_DOCS" "$LOOP_KNOWLEDGE_LAYER" "${LOOP_RUBRIC_LOCAL:-}"
  printf 'LOOP_DESIGN_REF=%q\n' "$LOOP_DESIGN_REF"   # maker·checker 가 매 사이클 프롬프트로 받는 작업 지시 파일
  printf 'MAX_ITER=%q\nBUDGET_MIN=%q\nABS_CEIL=%q\nTICKET=%q\n' "$MAX_ITER" "$BUDGET_MIN" "$ABS_CEIL" "$TICKET"
} > "$LOOP_DIR/params.env"
# 재유도 진입점 — 이후 Step 들은 이 포인터로 LOOP_DIR 를 되찾아 params.env 를 source 한다.
# 포인터는 **브랜치별** 파일이다: 한 체크아웃에서 루프 A 를 멈춰 두고(AWAIT_USER) 다른 브랜치의 루프 B 를
# 돌려도 서로의 포인터를 덮어쓰지 않는다(단일 포인터면 A 재개가 B 의 params.env 를 조용히 source 한다).
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
printf '%s\n' "$LOOP_DIR" > "$PROJECT_ROOT/.loop/run/.active-$BR"
echo "loop-run 시작: ticket=$TICKET stack=$(printf '%s' "$DET" | jq -c '.stack') max_iter=$MAX_ITER (디폴트 $DEFAULT_ITER) budget_min=$BUDGET_MIN 천장 $ABS_CEIL"
```

### Step 0-1. 작업 지시 확보 + 스펙 완전성 점검 (사람 게이트)

**(a) 브리프 작성 — 작업 지시 파일이 없을 때만.** Step 0 이 `LOOP_DESIGN_REF` 를 `$LOOP_DIR/brief.md` 로 잡았다면 그 파일이 아직 비어 있다. **채우고 사람 확인을 받기 전에 Step 1 로 넘어가지 않는다.**

1. 이 대화에서 합의된 것을 `brief.md` 에 쓴다. 담을 것은 셋이다. **무엇을 만들/고칠지**, **완료 기준**, **건드리지 않을 범위**. 대화 전체를 옮기지 않는다 — maker 가 매 사이클 읽을 파일이라 짧고 확정적이어야 한다.
2. 그 파일을 사람에게 보여 준다. 경로와 본문을 함께 낸다.
3. 사람이 확인하면 루프를 시작한다. **작업 지시가 모호하다고 판단되면 루프를 시작하지 않는다** — checker 의 정합 층이 기준을 못 잡아 헛돌고, maker 도 구현 근거가 없다. grill-me 로 완료 기준부터 확정하게 한다.

`brief.md` 는 `$LOOP_DIR` 안이라 Step 5-1 폐기에 함께 사라진다. 남길 값이 있는 지시라면 애초에 grill-me B 흐름의 specs 파일로 있어야 하고, 그때는 그 경로를 `LOOP_DESIGN_REF` 로 주면 브리프를 만들지 않는다.

**(b) 스펙 완전성 점검 — 작업 지시가 파일로 왔든 여기서 썼든 항상.** `Agent` 로 `loop-spec-checker` 를 **한 번** 띄워, 그 지시가 답하지 않은 결정을 열거하게 한다. 사람이 아직 있는 마지막 순간이 여기다 — 루프가 돌기 시작하면 안 정해진 것은 maker 가 조용히 추측으로 메우고, checker 가 다른 추측을 기대하며 finding 을 내고, 사이클이 그 사이를 오간다. 등급이 오르내려 정체 감지에도 안 걸린다.

프롬프트에 담는 것: `$LOOP_DESIGN_REF`(점검 대상), 컨벤션 문서 경로·지식층 값(`$LOOP_CONVENTION_DOCS`·`$LOOP_KNOWLEDGE_LAYER` 값 자체 — **환경변수는 서브에이전트에 전달되지 않는다**), 결과 출력 경로 `$LOOP_DIR/spec-gaps.json`.

- **결과는 경고까지고 시작을 막지 않는다.** 무엇이 load-bearing 인지는 프로젝트마다 달라, 기계가 막으면 거짓 양성으로 사람이 게이트 우회법부터 배운다. 판단은 확인하는 사람이 한다.
- **답을 기다리는 자리는 (a)가 돌 때 하나뿐이다.** (a)가 돌았으면 `gaps` 를 그 확인과 **한 화면**에 내고 사람 답을 기다린다. 지시가 파일로 와서 (a)가 건너뛰어졌으면 **`gaps` 를 출력하고 그대로 시작한다** — 기다리지 않는다. 이 스킬은 백그라운드 잡으로 도는 것을 권하는데, 거기서 오지 않을 답을 기다리면 에러 없이 조용히 멈춰 사람이 돌아와서야 안다. 사람이 나중에 그 출력을 보고 답하면 작업 지시 파일에 반영하고 다음 사이클부터 반영된다.
- `gaps` 가 비면 그 사실을 한 줄로 말한다.
- 이 점검은 **모든 `/loop-run` 이 한 번씩 더 무는 비용**이다(에이전트 하나, `effort: high`). 끄는 스위치는 두지 않았다 — 무인으로 다섯 회차를 돌릴 작업에서 한 번의 열거가 더 싸다는 판단이고, 그 판단이 뒤집히면 그때 스위치를 만든다.
- 점검 자체가 실패하면(결과 파일이 안 생김) 그 사실만 알리고 시작은 막지 않는다 — 이 절은 경고 층이지 게이트가 아니다.

> Bash 도구 호출은 호출마다 새 셸이라 env 가 안 남는다. 그래서 회차·시작시각뿐 아니라 **brake 값·감지 명령까지 전부 파일로 영속** 한다(`started.epoch`, `history.jsonl` 줄 수, `params.env`). 이후 모든 Step 의 셸 블록은 맨 위의 재유도 프리앰블(브랜치별 포인터 `.loop/run/.active-{브랜치}` → `set -a` 로 `params.env` source)로 시작한다 — 변수 carry-over 를 가정하지 않는다. `set -a` 가 핵심이다: 그냥 source 하면 값만 복원되고 export 속성이 빠져, 채점 자식 프로세스(score/decide/stall)가 `LOOP_RUBRIC_LOCAL` 을 못 읽어 LOCAL rubric 이 조용히 무시된다.

### Step 1. 사이클 시작 — brake 선확인 + 게이트 층

매 사이클 **맨 먼저** brake 부터 본다. 그 다음 결정론 게이트(컴파일·테스트). 게이트가 깨지면 checker 를 부르지 않는다.

```bash
# 재유도 프리앰블 — 새 셸엔 Step 0 변수가 없다. 브랜치별 포인터→params.env 로 전부 복원한다(없으면 fail-loud).
# set -a: export 속성까지 복원 — 없으면 채점 자식 프로세스가 LOOP_RUBRIC_LOCAL 을 못 읽어 LOCAL rubric 이 조용히 무시된다.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "loop: params.env 없음 — Step 0 미실행/폐기됨. 멈추고 사람 호출" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a
ITER=$(wc -l < "$HIST" 2>/dev/null | tr -d ' '); ITER=${ITER:-0}
GFAIL=$(cat "$LOOP_DIR/gate.fail" 2>/dev/null || echo 0)   # 게이트 실패 재진입 횟수 — checker 없는 공회전도 brake 가 세게
ELAPSED_MIN=$(( ( $(date +%s) - $(cat "$LOOP_DIR/started.epoch") ) / 60 ))
echo "사이클 진입: 완료 $ITER 회 + 게이트 실패 $GFAIL 회 / 경과 ${ELAPSED_MIN}분"
# brake: 반복·시간·천장. 주석 의사코드가 아니라 실행 블록이다 — 매 사이클 실제로 돌아야 강제된다.
if [ $((ITER + GFAIL)) -ge "$MAX_ITER" ] || [ $((ITER + GFAIL)) -ge "$ABS_CEIL" ] || [ "$ELAPSED_MIN" -ge "$BUDGET_MIN" ]; then
  echo "loop: brake 도달 (iter=$ITER + 게이트실패 $GFAIL / $MAX_ITER 천장 $ABS_CEIL, 경과 ${ELAPSED_MIN}/${BUDGET_MIN}분) — 평가 없이 종료, Step 5 사람 호출" >&2
  # 더 진행하지 말고 Step 4 분기 2(brake) → Step 5 로.
fi
# 점검 대상이 실제로 있나 — 베이스 오감지·빈 작업이면 finding 0 이 거짓 PASS 로 둔갑한다. **여기가 결정론 1차 방어**고, 채점의 reviewed 게이트는 checker 가 그 뒤에 반쯤 죽는 경우를 받는다.
CHANGED=$(git diff --name-only "$LOOP_BASE_BRANCH"...HEAD 2>/dev/null | wc -l | tr -d ' ')
DIRTY=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
if [ "${CHANGED:-0}" -eq 0 ] && [ "${DIRTY:-0}" -eq 0 ]; then
  echo "loop: 점검 대상 변경 0건 ($LOOP_BASE_BRANCH...HEAD + uncommitted) — PASS 아님. 베이스 브랜치 확인 필요, 멈추고 사람 호출" >&2
  # 조용히 통과 금지 — Step 5 사람 호출로. **echo 만 하고 흘려보내면 산문과 코드가 어긋난다**:
  # 여기서 안 멈추면 checker 가 빈 diff 를 보고 깨끗하다고 답하고 그게 PASS 가 된다.
  exit 3
fi
# 게이트: 컴파일 먼저(빠름), 통과하면 변경 모듈 테스트(또는 전체).
# 출력은 창이 아니라 파일로 받는다. 실패하면 파서가 항목 큐로 바꾸고, 창에는 한 줄 목록만 낸다.
# (전문을 창에 쏟으면 매 회차 같은 잡음이 컨텍스트를 먹는다 — Step 3 의 findings 위생과 같은 규율.)
GQ="$LOOP_DIR/gate-queue.jsonl"
: > "$GQ"   # 매 사이클 새로 채운다. 앞 회차에 고쳐진 항목이 남으면 maker 가 이미 없는 오류를 쫓는다.
GATE_FAILED=0
run_gate() {   # run_gate <단계라벨> <명령>
  [ -n "$2" ] || { echo "loop: $1 게이트 명령 비어있음 — 스킵(셋업에서 LOOP_${1}_CMD 직접 지정 가능)" >&2; return 0; }
  local out="$LOOP_DIR/gate-$1.out"
  if eval "$2" > "$out" 2>&1; then echo "게이트 $1 통과"; return 0; fi
  python3 "$ENG/gate_parse.py" --stage "$1" "$out" >> "$GQ"   # 아는 형식 0건이면 꼬리를 항목 하나로 — 빈 큐를 내지 않는다
  GATE_FAILED=1
  return 1
}
# 컴파일 먼저. 깨지면 테스트는 돌리지 않는다(깨진 컴파일 위의 테스트 실패는 정보가 없다).
run_gate BUILD "${LOOP_BUILD_CMD:-}" && run_gate TEST "${LOOP_TEST_CMD:-}"
if [ "$GATE_FAILED" -eq 1 ]; then
  TOTAL=$(wc -l < "$GQ" | tr -d ' ')
  echo "게이트 실패 — 항목 $TOTAL 건이 $GQ 에 쌓였다. Step 6 이 여기부터 처리한다."
  jq -r '"\(.stage)\t\(.kind)\t\(.file // "-"):\(.line_number // "-")\t\((.message // .test // "")[0:80])"' "$GQ" | head -20
  [ "$TOTAL" -gt 20 ] && echo "(위 20건만 표시 — 나머지 $((TOTAL - 20)) 건은 $GQ 에 있다. 잘라낸 것을 통과로 읽지 말 것)"
fi
```

- 컴파일·테스트 **실패** = 게이트 층 RETRY. 먼저 아래 자기완결 증가를 실행해 실패 횟수를 영속한다(위 brake 가 회차와 합산해 세는 값 — 게이트만 계속 깨져도 시간 상한까지 공회전하지 않게). 별도 Bash 호출에서 실행되므로 `$GFAIL` 셸 변수에 기대면 안 된다 — 미정의 변수는 산술에서 0 이라 카운터가 항상 1 로 리셋된다. 그 뒤 checker 를 부르지 않고 **Step 6(maker 스핀)** 으로 가서 고친 뒤 이 사이클을 다시 연다. 단, 깨진 게 maker 가 못 고치는 운영 비가역(예: 마이그레이션 충돌)이면 사람 대기.

  ```bash
  # 자기완결 증가 — 파일에서 읽어 +1 해 파일로. 셸 변수 carry-over 불필요.
  PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
  BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
  LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR")"
  G="$LOOP_DIR/gate.fail"; echo $(( $(cat "$G" 2>/dev/null || echo 0) + 1 )) > "$G"; cat "$G"
  ```
- **게이트 실패의 산출물은 버리지 않는다 — `$LOOP_DIR/gate-queue.jsonl` 이 그 사이클 maker 의 입력이다.** 위 블록의 `run_gate` 가 게이트 출력을 파일로 받고 `gate_parse.py` 로 한 줄 하나의 JSON 항목(`kind`·`file`·`line_number`·`message`·`raw`)으로 바꿔 큐에 쌓는다. 채점 경로의 `scored.json` 이 checker finding 을 담는 자리와 같다. 창에는 한 줄 목록만 나가고 원문은 `$LOOP_DIR/gate-<단계>.out` 에 남아, 필요한 항목만 maker 가 열어 본다.
  - **큐는 매 사이클 비우고 새로 채운다.** 게이트를 매 사이클 다시 돌리므로 그 출력이 유일한 정본이다. 앞 회차 항목을 남기면 이미 고쳐진 오류를 maker 가 계속 쫓는다.
  - **아는 형식이 하나도 없어도 큐가 비지 않는다.** 파서가 출력 꼬리를 `gate-output-unparsed` 항목 하나로 남긴다. 조용히 버리면 큐가 비어 게이트가 통과한 것처럼 보이고, 그 오독이 이 큐가 막는 실패다.
  - 형식은 실제 출력에서 뜬 것이다. Kotlin 2.x 는 **열 번호 뒤에 콜론이 없다**(`...:17:31 Unresolved reference`). 형식 회귀는 `_loop-engine/test_gate_parse.py` 가 잡는다.
- 게이트 통과면 Step 2 로.
- 린트 게이트가 필요하면 Step 0 감지가 준 `$LOOP_LINT_CMD`(예: `./gradlew ktlintCheck`·`eslint .`·`ruff check`)를 위 `run_gate LINT "${LOOP_LINT_CMD:-}"` 형태로 게이트 사슬에 덧붙인다(빈 값이면 스킵). 파서는 린트 위반도 `lint-violation` 항목으로 낸다.

### Step 2. checker 1회 호출 (독립·적대 시선)

`Agent` 툴로 `loop-checker` 를 **한 번** 호출한다. **환경변수는 서브에이전트에 전달되지 않는다** — 아래 값 전부를 프롬프트 텍스트로 넘긴다. 프롬프트에 넘기는 것은 이것만:

> 모델: checker 는 frontmatter 에 모델을 고정하지 않는다(v0.8.4) — 기본은 호출한 세션의 모델을 상속한다. 특정 모델로 돌리고 싶으면 이 `Agent` 호출에 `model` 파라미터를 지정한다(세션마다 maker 와 같은 모델로 점검하는 것이 기본 의도).
>
> effort: checker 는 frontmatter 에 `effort: xhigh` 를 **고정한다**(v0.9.6) — 모델과 달리 세션을 상속하지 않는다. 적발률이 곧 탐색량인 자리라, 세션 등급을 내려도 판정부는 따라 내려가면 안 되기 때문이다. `Agent` 호출로는 재정의할 수 없다(도구에 `effort` 파라미터가 없다) — 바꾸려면 에이전트 정의를 고친다. 계약은 `core/effort-ladder.md`.

- **작업 정의 파일 경로**: `$LOOP_DESIGN_REF` 값. maker 에게 준 것과 **같은 파일**이라 둘의 기준이 갈리지 않는다. 이 경로가 checker 의 정합 층 기준이다. 종전처럼 이 세션이 1~3문장으로 요약해 넘기지 않는다 — 요약은 손실이고 maker 와 checker 가 서로 다른 요약을 받으면 정합 판정 자체가 어긋난다.
- 비교 베이스: `$LOOP_BASE_BRANCH`(기본 `origin/main`).
- 점검 기준 문서: `$LOOP_CONVENTION_DOCS` 값(공백 구분 경로 목록)과 지식층 `$LOOP_KNOWLEDGE_LAYER` 값. 비었으면 "없음"이라고 명시해 넘긴다 — checker 가 "컨벤션 문서 없음, 신뢰도 제한" 경로를 정직하게 타게 한다.
- 종류 어휘 rubric 경로 둘 다: BASE(`$ENG/rubric.base.md` 값)와 LOCAL(`$LOOP_RUBRIC_LOCAL`, 있으면) — checker 는 환경변수도 `$CLAUDE_PLUGIN_ROOT` 도 전달받지 못하므로 두 경로 모두 프롬프트 텍스트로 준다.
- findings 출력 경로(아래 `$F` 절대경로).

**maker 가 보고한 것을 checker 프롬프트에 절대 넣지 마라**(핵심 불변 1). maker 가 서브에이전트라 그 산문이 오케스트레이터를 거쳐야만 checker 에 닿을 수 있는데, 그 경유가 곧 이 금지의 대상이다. 한 줄짜리 `ok` 도 옮기지 않는다. checker 는 자기 도구(Read/Grep/Glob/Bash)로 diff·컨벤션 문서·ANTIPATTERNS 를 직접 읽어 독립 판단한다.

**checker 결과는 파일로 회수한다.** checker 를 스핀하기 **전에** findings 출력 경로를 결정적 위치로 잡고 **비운 뒤**, 그 절대경로를 checker 프롬프트에 "findings 출력 경로"로 명시한다. checker 는 `{base, findings:[...]}` 를 그 파일에 쓴다(인라인 ```json 블록도 남기지만 그건 대화형 가독성용 사본 — 백그라운드 세션에선 서브에이전트 최종 메시지가 오케스트레이터에 인라인으로 전달되지 않아, 파일이 정본 회수 경로다).

```bash
# 재유도 프리앰블(Step 1 과 동일) + 결정적 findings 경로.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "loop: params.env 없음 — Step 0 미실행/폐기됨. 멈추고 사람 호출" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a
# 랜덤 mktemp 는 쓰지 않는다 — Bash 호출마다 셸이 새로 떠 그 변수는 다음(채점) 호출에 안 남는다.
# 결정적 경로를 써야 스핀 프롬프트와 Step 3 채점이 같은 경로를 가리킨다. .loop/run/ 하위라 gitignore(추적 소스 아님).
F="$LOOP_DIR/checker-findings.json"
: > "$F"   # 스핀 직전 비우기 — 직전 사이클 잔여가 남으면 checker 미기입을 거짓 통과로 가릴 수 있다.
# 프롬프트에 넣을 값을 창에 출력한다 — 변수 대입만으론 오케스트레이터가 값을 알 수 없다(대입은 stdout 이 없다).
echo "checker 프롬프트 값: base=$LOOP_BASE_BRANCH / conv=[${LOOP_CONVENTION_DOCS:-없음}] / knowledge=[${LOOP_KNOWLEDGE_LAYER:-없음}] / base_rubric=$ENG/rubric.base.md / local_rubric=[${LOOP_RUBRIC_LOCAL:-없음}] / findings=$F"
```

이 `$F` 절대경로를 checker 프롬프트에 넘긴다. checker 가 완료되면(툴 결과/완료 통지) `$F` 를 그대로 Step 3 채점에 넣는다.

### Step 3. 결정론 채점 + history append

checker 가 쓴 findings 파일(`$F`)을 채점 셸 파이프에 흘린다. **severity 는 셸이 매긴다 — checker 등급을 쓰지 않는다.**

```bash
# 재유도 프리앰블 — Step 1 과 동일. 변수 carry-over 를 가정하지 않는다.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "loop: params.env 없음 — Step 0 미실행/폐기됨. 멈추고 사람 호출" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a
# $F 는 Step 2 에서 checker 에 넘긴 findings 출력 파일. 결정적 경로라 이 새 셸에서 같은 값으로 재유도된다.
F="$LOOP_DIR/checker-findings.json"
# checker 가 파일에 못 썼으면(빈/미생성) 조용히 PASS 로 넘기지 말고 멈춘다 — exit 65 로 fail-loud(정상 빈 배열 {"findings":[]} 은 바이트가 있어 -s 통과, 오탐 없음).
[ -s "$F" ] || { echo "loop: checker 가 findings 를 $F 에 안 씀(빈 파일/미생성) — checker 실패. 멈춰 사람 호출" >&2; exit 65; }
SCORED=$(bash "$ENG/score.sh" "$F") || {
  echo "loop: 채점이 입력을 거부했다(exit 65) — checker 출력 계약 위반. 흔한 원인은 깨끗한 결과에 reviewed 를 안 채운 것. 멈춰 사람 호출" >&2
  exit 65
}                                                                # finding 마다 severity·await 부여
VERDICT=$(printf '%s' "$SCORED" | bash "$ENG/decide.sh")         # {verdict, counts, await}
STALL=$(printf '%s' "$VERDICT"  | bash "$ENG/stall.sh" --state "$STATE")   # 정체 판정 + 상태 영속
ITER=$(( $(wc -l < "$HIST" 2>/dev/null | tr -d ' ') + 1 ))
jq -nc --argjson it "$ITER" \
       --argjson v "$VERDICT" \
       --argjson s "$SCORED" \
  '{iteration:$it, verdict:$v.verdict, findings:($s.findings // [])}' >> "$HIST"   # 한 줄 = 한 사이클
# 같은 **종류**가 사이클을 연속 지배하는지. stall.sh 는 등급 개수만 봐서 이걸 못 본다.
# **반드시 위 append 뒤에** 부른다 — 이번 회차가 이력에 들어간 뒤라야 이번 회차가 판정에 포함된다.
KINDST=$(bash "$ENG/kindstreak.sh" --history "$HIST") || {
  echo "loop: 반복 종류 감지가 이력을 거부했다(exit 65) — history 파일 확인. 멈춰 사람 호출" >&2
  exit 65
}
printf '%s' "$SCORED" > "$LOOP_DIR/scored.json"   # maker 단계(Step 6)가 finding 단위로 여는 정본 — 셸 변수 carry-over 대체
# $F 는 지우지 않는다 — 다음 사이클 Step 2 가 스핀 직전 비운다. 남겨두면 이번 사이클 findings 를 디버깅에 쓸 수 있다(gitignore).
V=$(printf  '%s' "$VERDICT" | jq -r .verdict)
ST=$(printf '%s' "$STALL"   | jq -r .status)
KS=$(printf '%s' "$KINDST"  | jq -r .status)
echo "사이클 $ITER → verdict=$V / stall=$ST / counts=$(printf '%s' "$VERDICT" | jq -c .counts)"
# 반복 종류도 창에는 상태 한 줄만. 전문은 안 편다.
echo "반복 종류: $(printf '%s' "$KINDST" | jq -r '"\(.status) kind=\(.kind // "-") streak=\(.streak)/\(.threshold)"')"
# 오케스트레이터 컨텍스트 위생: findings 의 evidence 전문을 cat/Read 로 창에 끌어들이지 않는다.
# 아래 한 줄 목록(등급·종류·위치)까지만 보고, 전문은 maker 단계(Step 6)에서 finding 단위로만 연다.
printf '%s' "$SCORED" | jq -r '.findings[] | "\(.severity)\t\(.dimension)/\(.kind)\t\(.location)"'
```

- 채점 셸이 `exit 65` 로 죽으면(빈/형식오류 입력) checker 가 findings 파일을 못 썼거나 형식이 깨진 것이다(위 `[ -s "$F" ]` 가드가 먼저 잡는 경우 포함) — **조용히 PASS 로 넘기지 말고** 멈춰 사람에게 "checker 출력 파싱 실패"로 보고. fail-loud 가 설계다.

### Step 4. verdict + stall 분기 (우선순위 순서대로)

아래 **위에서부터** 먼저 걸리는 것을 따른다.

1. `V == AWAIT_USER` → **멈춤, 사람 호출.** 비가역·자동화 금지 영역(BLOCKER/force_await). maker 가 손대면 안 된다.
2. brake 도달(`ITER + GFAIL >= MAX_ITER` 또는 `ITER + GFAIL >= ABS_CEIL` 또는 `ELAPSED_MIN >= BUDGET_MIN` — Step 1 과 동일하게 게이트 실패 합산) → **멈춤, 사람 호출.** 현재까지의 best 상태와 남은 finding 을 요약해 넘긴다.
3. `ST == STALLED` 또는 `ST == REGRESS_ESCALATE` → **멈춤, 사람 호출.** 헛바퀴/악화. `RETRY_SOFT`(MAJOR 만)로 정체한 경우 사람에게 "이 MAJOR 안고 통과할까?" 승인 옵션을 같이 제시.
4. `KS == REPEATED_KIND` → **멈춤, 사람 호출.** 다만 3번과 **전할 말이 다르다.** 3번은 "코드가 안 고쳐진다" 이고 이건 **"같은 종류가 N 사이클 연속으로 이 사이클을 지배했다 — 코드가 아니라 작업 목표를 의심하라"** 다. 종류·연속 횟수와 함께 사람에게 물을 것 두 가지를 같이 낸다: 이 목표가 **열거 가능한가**(고칠 대상이 유한한 목록인가, 아니면 checker 가 언제나 다음 하나를 더 찾는 형태인가), **끝나는 지점이 정의됐는가**. 코드를 한 번 더 고치는 것으로는 닫히지 않는다 — 하나를 잠그면 다음 안 잠긴 것이 나온다.
5. `V == PASS` → **종료(수렴).** Step 5 로.
6. `V == RETRY` 또는 `V == RETRY_SOFT` (그리고 위 brake/stall/반복 종류 미도달) → **Step 6(maker 스핀)** 로 가서 finding 을 고치고 Step 1 로 루프.

### Step 5. 종료 처리

- **PASS(수렴)**: 사람에게 결과 보고 — 통과 verdict, 사이클 수, 남은 MINOR(기록만), 변경 요약. **변경 요약은 maker 보고를 모아 쓰지 않고 `git diff "$LOOP_BASE_BRANCH"...HEAD --stat` 과 `git status --short` 에서 뽑는다** — maker 는 회차마다 새로 띄워져 전체를 아는 주체가 없고, 트리가 유일한 정본이다. PR 인계는 **보류 합의 사항**이라 자동으로 올리지 않는다(spec). 프로젝트의 마감 스킬(예: c8c-api `/finalize`) 또는 `/pr` 로 사람이 마감하도록 제안하고, 원하면 그때 진행.
- **AWAIT_USER / STALLED / REGRESS / REPEATED_KIND / brake**: 멈춘 이유 + 현재 남은 finding(등급 내림차순) + 다음 행동 후보(고쳐서 재개 / 이 등급 안고 통과 승인 / 작업 정의 재정렬)를 사람에게 핑. `REPEATED_KIND` 면 후보의 무게가 다르다 — 고쳐서 재개가 아니라 **작업 정의 재정렬**이 기본 후보다. 이 경우 코드는 마지막 maker 시도 상태로 워크트리에 남는다.
- 종료 후(특히 PASS·사람 멈춤 모두) `/loop-lessons` 로 이 루프의 `history.jsonl` 에서 잡힌 실수를 ANTIPATTERNS 후보로 올릴지 사람에게 제안한다(선순환 닫기). 강제 아님.

### Step 5-1. 종료 정리 (런타임 상태 폐기)

`$CLAUDE_PROJECT_DIR/.loop/run/{ticket}/`(history·stall·started.epoch·gate.fail·checker-findings·scored·gate-queue·게이트 출력 원문 `gate-*.out`·트리 스냅숏 `tree.snapshot`·오케스트레이터가 쓴 `brief.md`)는 루프 한정 휘발성이다. **마무리하면 남기지 않는다.** 단 lesson 흐름이 `history.jsonl` 을 입력으로 쓰므로 **폐기는 반드시 lesson 종합 다음**이다 — 종합 전에 지우면 선순환 입력이 사라진다.

```bash
# 이 블록도 별도 Bash 호출이라 LOOP_DIR 를 포인터에서 재유도한다. 재유도 없이 돌면 빈 LOOP_DIR 로
# rm 이 아무것도 못 지우면서 종료코드 0 을 내, 상태가 그대로 남은 채 "정리했다" 로 읽힌다(실측 확인).
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
PTR="$PROJECT_ROOT/.loop/run/.active-$BR"
LOOP_DIR="$(cat "$PTR" 2>/dev/null)"
# 폐기는 lesson 종합(또는 사람이 생략 결정) 후에만. 지울 것이 없으면 그렇다고 말하고 끝낸다(재실행 안전).
[ -n "$LOOP_DIR" ] || { echo "loop: 포인터 없음 — 지울 상태가 없다(이미 폐기됐거나 Step 0 미실행)" >&2; exit 0; }
rm -rf "$LOOP_DIR"   # = $CLAUDE_PROJECT_DIR/.loop/run/{ticket}
rm -f "$PTR"         # 이 브랜치의 재유도 포인터도 함께 — 남으면 다음 루프의 프리앰블이 죽은 경로를 가리킨다.
echo "loop: 런타임 상태 폐기 — $LOOP_DIR"
```

- **PASS(수렴)**: 결과 보고 → (선택) `/loop-lessons` → 그 다음 폐기. 깨끗이 비운다.
- **사람 멈춤(AWAIT_USER/STALLED/brake)으로 재개 여지가 있으면 바로 폐기하지 않는다.** `stall.json`·`started.epoch`·`params.env` 가 남아 있어야 이어서 돌릴 수 있다(없으면 다음 시작이 INIT 로 리셋돼 정체 감지가 무력화). 재개할 때는 Step 0 의 초기화 줄(`: > "$HIST"; rm -f "$STATE"`·epoch 갱신)을 다시 타지 않는다. 사람이 그 작업을 닫기로 하면(고침 완료 또는 포기) 그때 lesson 종합 후 폐기.
- 워크트리째 버리는 경우엔 `.loop/run/` 도 같이 사라지니 별도 폐기가 불필요하지만, **메인 체크아웃이나 워크트리를 남겨 둔 경우엔 이 단계가 정리를 보장**한다. 워크트리 수명에 기대지 않는다.

### Step 6. maker 스핀 (고침)

`Agent` 툴로 `loop-maker` 를 **회차마다 새로 한 번** 띄운다. **이 세션은 코드를 쓰지 않는다**(핵심 불변 1). 같은 maker 를 `SendMessage` 로 이어가지 않는다 — 회차마다 새로 띄우는 이유는 한 maker 가 열 회차를 살면 회차마다 읽은 파일·편집·빌드 출력을 전부 지고 가기 때문이다. **회차 간에 필요한 것은 대화가 아니라 워킹 트리와 반복 표시로 전달된다.**

> 모델·effort: `loop-maker` 는 frontmatter 에 `model: opus`(v0.8.5)와 `effort: high`(v0.9.6)를 기본으로 둔다 — 구현은 생산 작업이라 두 축 모두 세션 아래로 내리고, 판정은 `effort: xhigh` 로 고정된 checker 가 맡는 비대칭이 전제다. 회차 난도에 따라 이 `Agent` 호출의 `model` 파라미터로 상향·하향할 수 있지만 `effort` 는 호출로 못 바꾼다(도구에 파라미터가 없다). 계약은 `core/effort-ladder.md`.

행동 규칙(배정 범위만·테스트 동반·컴파일 자기 검증·설계 결함 시 보고·`ok`/`blocked` 종료·커밋 금지)은 `loop-maker` 정의가 담당하므로 프롬프트에 반복하지 않는다. **환경변수는 서브에이전트에 전달되지 않으니 아래 값 전부를 프롬프트 텍스트로 넘긴다.**

프롬프트에 담는 것은 이것만이다.

1. **작업 지시 파일 경로**: `$LOOP_DESIGN_REF` 값. 루프 전체에 안 바뀐다.
2. **이번 회차 입력 파일 경로 하나**: 아래가 고르는 것. **둘 다 주지 않는다.**
3. **반복 표시**: 아래 명령이 내는 목록. finding 마다 몇 회차째인지.
4. **직전 회차 maker 의 한 줄**: 있으면. 없으면 생략.
5. **컨벤션 문서 경로**: `$LOOP_CONVENTION_DOCS` 값. 비었으면 "없음".
6. **빌드 명령**: `$LOOP_BUILD_CMD` 값. 규칙 4의 자기 검증에 쓴다. 비었으면 "없음".

**입력은 두 갈래이고 게이트 큐가 먼저다.**

```bash
# 재유도 프리앰블(Step 1 과 동일) 뒤에:
GQ="$LOOP_DIR/gate-queue.jsonl"
if [ -s "$GQ" ]; then MAKER_INPUT="$GQ"; echo "maker 입력: 게이트 큐 $(wc -l < "$GQ" | tr -d ' ')건"
else MAKER_INPUT="$LOOP_DIR/scored.json"; echo "maker 입력: 채점 큐 $MAKER_INPUT"; fi
# 반복 표시 — finding 마다 몇 회차째 같은 kind@location 인가. 프롬프트에 이 출력을 그대로 넣는다.
# stall.sh 는 루프 전체의 no_progress 만 내고 finding 단위 반복은 안 낸다. history 에서 뽑는다.
[ -s "$HIST" ] && jq -rs '
  [ .[] | .iteration as $it | (.findings // [])[] | {k: "\(.kind)@\(.location)", it: $it} ]
  | group_by(.k) | map({key: .[0].k, cycles: (map(.it) | unique)})
  | map(select(.cycles | length > 1)) | sort_by(-(.cycles | length))
  | .[] | "\(.cycles | length)회차째  회차=\(.cycles | join(","))  \(.key)"
' "$HIST" || echo "(반복 없음 — 첫 회차이거나 매번 새 finding)"
echo "작업 지시: $LOOP_DESIGN_REF / 빌드: ${LOOP_BUILD_CMD:-없음} / 컨벤션: ${LOOP_CONVENTION_DOCS:-없음}"
```

- **`gate-queue.jsonl` 이 비어 있지 않으면 그것.** 게이트가 깨진 사이클이라는 뜻이고, 이때 `scored.json` 은 **이번 사이클 것이 아니다** — 게이트가 깨지면 checker 를 부르지 않아 Step 3 이 돌지 않았고, 그 파일은 앞 사이클에서 남은 값이다. 그걸 주면 maker 가 없는 문제를 쫓는다. 핵심 불변 3(게이트가 checker 보다 먼저)의 연장이다.
- **`gate-output-unparsed` 항목이 섞여 있으면** 파서가 그 도구의 형식을 모른 것이다. maker 가 꼬리를 읽고 고치되, 같은 형식이 반복되면 `_loop-engine/gate_parse.py` 에 패턴을 더할 후보로 사람에게 보고하라고 프롬프트에 한 줄 덧붙인다.
- **오케스트레이터는 이 파일들의 전문을 창에 끌어오지 않는다.** 경로만 넘기고 maker 가 읽는다. 린트 게이트는 항목이 수천 개가 될 수 있다.
- **테스트 동반 강제는 rubric 이 지탱한다.** KINDS 표의 `test-missing`(convention, CRITICAL)이 BASE 에 등록돼 있어 LOCAL rubric 없이도 작동한다. checker 가 변경분에 대응 테스트 누락을 잡으면 셸이 CRITICAL → RETRY 를 낸다. 테스트 규약이 다른 프로젝트는 LOCAL rubric 의 같은 kind 로 override 하거나 끈다 — 스킬 본문이 아니라 rubric 이 결정한다.
- **`blocked` 로 끝났으면 다음 maker 를 띄우지 않는다.** 사유를 사람에게 넘긴다(`AWAIT_USER`). 고칠 수 없거나 고치면 안 되는 항목을 maker 사이로 돌려보내면 회차만 탄다.
- MINOR 만 남았으면 보통 PASS 라 여기 오지 않는다. RETRY_SOFT(MAJOR)는 고치되, 정체로 멈추면 사람 승인으로 통과 가능.

### Step 6-1. 트리가 실제로 바뀠는지 확인 (게이트 전)

maker 가 `ok` 로 끝냈다고 코드가 바뀐 것은 아니다. **보고는 거짓일 수 있고 트리는 아니다.** 안 바뀐 상태로 Step 1 로 가면 게이트가 같은 결과를, checker 가 같은 finding 을 내고 회차만 탄다.

```bash
# 재유도 프리앰블 뒤에. maker 스핀 직전 스냅숏과 비교한다.
# 상태가 아니라 **내용**을 해싱한다. `git status --porcelain` 만 쓰면 이미 수정된 파일을 또 고쳤을 때
# 출력이 ' M src/Main.kt' 로 동일해 거짓 정체가 뜬다 — 2회차 maker 가 1회차와 같은 파일을 고치는 것이
# 루프의 정상 상황이라 그 오탐이 상시가 된다. 미추적 파일 재수정도 같은 이유로 놓친다. 반대로 내용
# 변화 없는 `git add` 는 porcelain 만 보면 '바뀠다' 가 된다. 여섯 사례 실측으로 확인한 형태다.
NOW="$(git rev-parse HEAD):$( { git diff HEAD; git ls-files --others --exclude-standard -z | xargs -0 shasum 2>/dev/null; } | shasum | cut -d' ' -f1)"
PREV="$(cat "$LOOP_DIR/tree.snapshot" 2>/dev/null || echo none)"
printf '%s\n' "$NOW" > "$LOOP_DIR/tree.snapshot"
if [ "$NOW" = "$PREV" ]; then
  echo "loop: maker 스핀 후 워킹 트리가 그대로다 — 회차가 아니라 정체 신호. 게이트를 돌리지 말고 사람 호출" >&2
  # Step 4 분기 3(정체)과 같이 처리한다. 같은 결과를 N번 내지 않는 것이 이 루프의 전제다.
fi
```

**Step 6 진입 직전에도 같은 명령으로 스냅숏을 갱신한다.** 그러면 비교 대상이 "이번 maker 가 손대기 전" 이 된다. 이 확인이 스킬이 원래 요구했던 "매 회차 코드가 바뀌어야 루프가 의미 있다" 에 처음으로 집행을 붙인다.

통과하면 **Step 1** 로 돌아가 다음 사이클을 연다(게이트부터 다시).

## 백그라운드 세션 실행

사람이 빠져도 루프가 계속 돌게 하려면 이 세션을 **백그라운드 잡**으로 띄운다. grill-me 로 spec 을 확정한 *그 세션에서* `/loop-run` 을 걸고, **Step 0-1 의 작업 지시 파일을 한 번 확인한 뒤** 사용자는 자리를 비운다. 그 한 박자가 이 흐름의 유일한 사람 게이트다. 루프가 PASS·brake·AWAIT_USER 에 닿으면 결과/호출을 남긴다. 케이스3 의 매력은 "이미 Claude 와 대화 중이니 그대로 맡긴다" 는 매끄러움이다 — grill-me → loop-run 이 한 세션에서 이어진다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `loop: base rubric 없음` | plugin 번들 `rubric.base.md` 부재(설치 손상) | plugin 재설치, 또는 `LOOP_RUBRIC_BASE` 로 pin |
| 빌드/테스트 명령이 비어 게이트 스킵 | `detect_build.py` 가 빌드 시스템 미인식(unknown) | 매니페스트(build.gradle/package.json 등) 확인. 비표준이면 셋업에서 `LOOP_BUILD_CMD`/`LOOP_TEST_CMD` 를 직접 지정 |
| `python3` / `detect_build.py` 오류 | python3 미설치 또는 감지기 부재(설치 손상) | python3 설치 확인. plugin 재설치(감지기는 `_loop-engine/detect_build.py`) |
| `score.sh: 입력 형식 오류 — exit 65` | checker 가 findings 파일(`$LOOP_DIR/checker-findings.json`)을 못 썼거나 형식오류 | checker 프롬프트에 findings 출력 경로를 넘겼는지 + 스핀 전 `: > "$F"` 로 비웠는지 확인. `[ -s "$F" ]` 가드가 먼저 잡는다. 멈추고 보고 — PASS 로 넘기지 말 것 |
| `loop: findings 도 reviewed 도 비었다 — exit 65` | checker 가 `{"findings":[]}` 만 내고 `reviewed` 를 안 채움. 흔한 진짜 원인은 **베이스 브랜치 해석이 어긋나 diff 가 통째로 빈 것** — 그러면 점검 없이 통과가 된다 | 베이스 브랜치와 diff 범위를 먼저 확인한다. 정말 깨끗하면 checker 가 검토한 파일을 `reviewed` 에 담아야 한다. PASS 로 넘기지 말 것 |
| 정체 감지가 매번 INIT | 사이클 간 `stall.json` 이 사라짐(셸 종료마다 리셋한 경우) | `--state "$STATE"` 경로가 사이클 간 동일한지 확인. Step 0 에서만 초기화 |
| 회차가 안 늘어남 | `history.jsonl` append 누락 | Step 3 의 append 가 매 사이클 1줄 추가하는지 확인(줄 수 = 회차) |
| 무한 같은 finding | maker 가 안 고치고 재진입 | Step 6-1 트리 확인이 잡는다. 그게 정체로 뜨면 못 고치는 finding 이므로 AWAIT_USER |
| `loop: 작업 지시 파일 없음` | 입력 1을 파일로 안 줬다 | Step 0-1 로 `brief.md` 를 쓰고 사람 확인. 정상 경로다. 사람 확인 없이 Step 1 로 넘어가지 말 것 |
| `loop: 지정한 작업 지시 파일 ... 가 없다` | 경로 오타 또는 워크트리 상대경로 | 절대경로로 다시 준다. `exit 3` 이라 루프가 시작되지 않았다 |
| maker 가 매 회차 같은 접근을 반복 | 반복 표시를 프롬프트에 안 넣었다 | Step 6 의 `jq` 출력을 프롬프트에 그대로 넣는다. 이게 회차 간 유일한 기억이다 |
| maker 스핀 후 트리 그대로 | 규칙 4의 자기 검증에서 컴파일이 깨져 아무것도 못 고쳤거나, `blocked` 인데 스핀을 계속함 | Step 6-1 이 잡는다. maker 의 종료 문자열이 `blocked` 였는지 확인 |
| maker 보고가 길다 | 오케스트레이터가 요약을 요구했다 | `loop-run` 은 `ok`/`blocked` 만 받는다. 요약 요구는 `loop-build` 의 phase 흐름 몫 |
| 게이트 큐가 `gate-output-unparsed` 한 건뿐 | `gate_parse.py` 가 그 도구의 오류 형식을 모름 | 그 항목의 꼬리로 고치되, 같은 형식이 반복되면 파서에 패턴 추가 후보로 보고. **큐가 비는 것보다 이게 낫다** — 빈 큐는 통과로 오독된다 |
| 게이트 큐에 이미 고친 오류가 남음 | Step 1 의 `: > "$GQ"` 초기화를 건너뜀 | 게이트 블록을 통째로 실행한다. 큐는 사이클마다 새로 채우는 것이 정본 |
| 게이트 실패인데 창에 원문이 안 보임 | 설계다 — 출력은 `$LOOP_DIR/gate-<단계>.out` 으로 간다 | 창의 한 줄 목록으로 판단하고, 필요한 항목 주변만 그 파일에서 읽는다 |
| 모든 finding 이 CRITICAL | checker 가 dimension 오타 | score.sh 가 모르는 dimension 을 보수적으로 CRITICAL 처리. checker dimension 값 점검 |

## Non-Goals

- **1회 점검·보고** — 그건 `/loop-review`(사람이 곧 루프). 이 스킬은 코드를 고치며 수렴까지 돈다.
- **lesson → ANTIPATTERNS 반영** — 종료 후 별 스킬 `/loop-lessons`(사람 승인 게이트)가 처리. 이 스킬은 history 만 남긴다.
- **회차별 토큰·달러 정밀 차단** — 케이스2 의 agent 헤드리스 드라이버 몫(세션 밖에서 회차마다 비용 확인). 케이스3 은 회차·시간·정체 + 종료 후 비용 백스톱.
- **Sentry 자동 트리거** — 그건 케이스2. 이 스킬은 사람이 명시적으로 거는 핸드오프 입구(케이스3)다.
- **severity 를 LLM 이 매기는 것** — 결정론 셸이 매긴다(같은 코드 = 같은 등급).
