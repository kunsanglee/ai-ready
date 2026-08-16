---
name: build
description: 설계·작업 지시를 사람 없이 구현해 수렴시키는 실행층. 일을 phase/step 으로 쪼개 사람 승인을 한 번 받은 뒤, phase 마다 maker 서브에이전트가 고치고 축이 갈린 checker 렌즈 셋(contract·safety·quality)이 서로를 모른 채 병렬로 점검하고 결정론 채점(rubric)이 등급을 매겨 PASS 까지 반복한다. severity 는 LLM 이 아니라 셸이 매겨 판정 일관성을 보장하고, 렌즈 결과는 개수를 세어 합치므로 축 하나가 죽으면 멈춘다. 착수 전 스펙 검사(exit_criteria·irreversible·non_goals·tiebreaks)를 통과해야 시작하고, 순회는 서브에이전트 오케스트레이터에 내려 사이클 잡음이 사람 창에 안 쌓이게 한다. 변경 하나만 수렴시키는 경우는 phase 가 하나인 특수한 경우다(종전 /loop-run). 호출 /build [phase당회차] [설계문서경로]. Use this skill when the user says "/build", "루프 돌려", "설계대로 쭉 빌드해", "이 작업 루프로 수렴시켜", "여러 페이즈 무인 개발", or wants the verification loop to autonomously implement and converge. 1회 점검만은 /review, 종료 후 교훈 수확은 /lessons.
---

# build — 설계를 사람 없이 구현해 수렴시킨다

> 실행층의 유일한 입구. 호출: `/build [phase당회차] [설계문서경로]`. 1회 점검만은 `/review`, 종료 후 교훈 수확은 `/lessons`. 셋은 같은 판정부(checker 렌즈 + 채점 셸 + BASE/LOCAL rubric)를 공유한다.

사람이 무엇을 만들지 확정해 넘기고 빠지면, 이 스킬이 그것을 phase/step 으로 쪼개 승인을 한 번 받고, 그 뒤 `maker(고침) → 게이트 → checker 렌즈 셋(병렬 점검) → 병합·채점 → 정체·brake 판정` 을 phase 마다 PASS 까지 돌린 다음 다음 phase 로 전진한다. **사람은 승인 한 번에만 필요하다.**

**변경 하나를 수렴시키는 것도 이 스킬이다** — phase 가 하나인 경우일 뿐이다. 종전에 `/loop-run` 이 하던 일이고, 그 스킬은 여기로 흡수됐다(아래 "loop-run 이 흡수된 이유").

> `/review` 와 혼동 금지. `/review` 는 **1회 점검 + 보고서, 코드 안 고침**(사람이 곧 루프). `/build` 는 **코드를 고치며 도는 루프**(사람이 빠짐). 점검 1회만 원하면 `/review`, 수렴까지 맡기면 `/build`.

## loop-run 이 흡수된 이유 (이관 안내)

종전에는 `/loop-run`(변경 하나 수렴)과 `/loop-build`(여러 phase 빌드아웃)가 따로 있었다. 실질 차이는 **maker 수명 하나**였는데, 그 차이가 없어졌다.

- `loop-run` 은 maker 를 **매 회차** 새로 띄웠다. 회차 사이에 필요한 것은 대화가 아니라 **워킹 트리와 반복 표시**로 넘어간다 — 앞 회차가 무엇을 했는지는 `git diff` 에 있고, 같은 결함이 몇 회차째인지는 이력에서 뽑는다.
- `loop-build` 는 phase 안에서 같은 maker 를 이어갔다. 명분은 "이 파일을 왜 이렇게 고쳤는지" 였는데 그것도 워킹 트리와 `phases.json` 의 step status 로 대체된다. 반면 **컨텍스트 부풀림은 대체 수단이 없고, 한 phase 가 여러 step 을 담고 최대 회차를 도는 이쪽이 더 심했다.**

그래서 **매 회차 새 maker 로 통일**했고, 두 스킬의 차이가 0이 되어 하나로 합쳤다.

**합친 것이 더 중요한 이유가 하나 더 있다.** 아래 "착수 전 스펙 검사"는 무인 완주를 가르는 게이트인데 `loop-build` 에만 있었다. 스킬이 둘이면 `/loop-run` 이 그 게이트를 통째로 우회하는 경로가 된다 — **검사 옆에 우회로가 있으면 그 검사는 검사가 아니라 권고다.** 합치면서 그 우회로가 닫혔다.

`/loop-run` 을 쓰던 자리는 `/build` 로 바꾸면 된다. 달라지는 것은 작업 지시를 자유 산문 파일이 아니라 **phase 하나짜리 `phases.json`** 으로 적는다는 것뿐이고, 그 파일은 이 스킬이 대화 합의에서 써서 사람에게 확인받는다(Step 1).

## 🔌 plugin / 프로젝트 구조

- 이 스킬은 `ai-ready` plugin 의 일부다. **도구 본체는 유저 레벨**(plugin), **프로젝트별 차이는 런타임 감지**가 채운다 — 별도 어댑터 파일을 만들지 않는다.
- plugin 번들(`$CLAUDE_PLUGIN_ROOT` 하위): `_loop-engine/`(채점 셸 `score`·`decide`·`stall`·`kindstreak`·`lessons`, 렌즈 결과 병합 `merge_findings`, `lib.sh` 의 `loop_param`, `detect_build.py` 감지기, `gate_parse.py` 게이트 실패 파서), `_loop-engine/rubric.base.md`(BASE 루브릭·brake 단일 원천), `agents/loop-maker.md`·`agents/loop-checker.md`·`agents/loop-spec-checker.md`·`agents/loop-lesson-synthesizer.md`(서브에이전트, `ai-ready:` namespace). **에이전트 이름은 `loop-` 접두를 유지한다** — 스킬 이름과 달리 에이전트는 사람이 타이핑하지 않고, `maker`·`checker` 같은 일반명은 다른 플러그인과 부딪히기 쉽다.
- 프로젝트 사실(빌드·테스트·린트 명령·티켓 패턴·베이스 브랜치·컨벤션 docs·지식층)은 Step 0 에서 `detect_build.py` 가 매니페스트·브랜치를 *읽어* 감지한다(읽기 전용 — 커밋되는 어댑터 파일은 만들지 않는다).
- 프로젝트 델타(레포에 커밋, 선택): `.loop/rubric.md`(LOCAL rubric — 그 스택 특유 kind. BASE 와 병합 채점). 없어도 BASE 만으로 돈다. 스택 특유 종류는 사람이 `/lessons` 로 덧붙여 키운다 — 자동 생성하지 않는다.
- 지식층은 프로젝트의 `docs/ANTIPATTERNS.md`(ai-ready audit/apply 가 만들고 가꾸는 문서). checker 가 판정 기준으로 읽고, `/lessons` 가 잡힌 실수를 거기에 덧붙인다.
- 런타임 상태는 `$CLAUDE_PROJECT_DIR/.loop/run/{ticket}/`(phases.json·phase 별 history·stall·렌즈별 checker 결과·scored·gate-queue·게이트 출력 원문·tree.snapshot·spec-gaps, 그리고 브랜치별 포인터 `.loop/run/.active-{브랜치}`) — 루프 한정 휘발성, `.gitignore` 로 `.loop/run/` 추적 제외. `.loop/rubric.md`(있으면)는 추적 대상.
- 외부 인증 없음(전부 로컬 git + 셸). brake 런별 오버라이드는 `LOOP_*` env 로.

## 입력

1. **설계 문서 / 작업 지시 경로**: phase/step 분해의 원본. 도메인 설계 문서나 grill 합의 spec. 형식 무관 — 이 세션이 읽어 분해한다. **경로가 없으면**: 직전 대화에 합의가 있으면 그것으로 분해안을 만들어 사람에게 확인받고, 없으면 "무엇을 빌드할지" 요청하고 대기한다 — 분해할 원본 없이 무인 시작하지 않는다(불변 7).
2. **phase 당 회차(선택)**: 위치 인자 중 **정수** = phase 당 `max_iterations`. 명시 없으면 rubric 기본(5). 명시값도 하드 천장 10 으로 깎인다. 전체 시간 상한도 `budget_minutes`(기본 120)를 **phase 당**으로 해석해 `× phase 수` 로 잡는다 — phase 가 늘수록 자동 확장돼 뒤 phase 가 시간 부족으로 잘리지 않는다. 파싱은 타입으로 가른다 — 정수=회차, 파일경로=spec 이라 순서가 뒤바뀌어도 안전.
3. **비교 베이스**: `$LOOP_BASE_BRANCH`(Step 0 감지, 기본 `origin/main`). 점검 범위 = `$LOOP_BASE_BRANCH...HEAD + uncommitted`.

작업 지시가 모호하면 루프를 **시작하지 않는다** — checker 의 정합 렌즈가 기준을 못 잡고 maker 도 구현 근거가 없어 헛돈다. Step 1 의 착수 전 검사가 그 확인을 게이트로 만든다.

## 핵심 불변 (절대 어기지 않는다)

1. **maker / checker 분리, 그리고 둘 다 오케스트레이터가 아니다.** maker = **매 회차 새로 띄우는 `loop-maker` 서브에이전트**. checker = **매 사이클 새로 띄우는 `loop-checker` 서브에이전트 렌즈 셋**. **오케스트레이터는 코드를 쓰지 않는다** — 스핀하고 셸을 돌리고 판정을 읽고 분기한다. checker 프롬프트에 **maker 의 구현 변명·합리화를 절대 넣지 않는다** — checker 는 diff·문서·ANTIPATTERNS 만 독립적으로 본다. 자기 코드를 자기가 후하게 보는 걸 막는 게 이 루프의 신뢰 근거다.
2. **checker 는 축이 갈린 여럿이고 서로를 모른다.** 한 명이 여섯 차원을 순회하면 각 차원에 쓸 탐색량이 나뉘고, 먼저 선 판단에 나머지가 끌려간다. 렌즈는 자기 축만 보고 자기 파일에만 쓴다. **결과는 개수를 세어 합친다** — 렌즈 하나가 죽어도 남은 것의 형식은 멀쩡해서, 세지 않으면 그 축이 한 번도 점검되지 않은 채 통과한다.
3. **severity 는 셸이 매긴다.** checker 는 `(종류·차원·가중플래그·위치·근거·force_await)` 만 태깅. 등급·verdict 는 결정론 셸이 낸다. checker 가 "괜찮아 보임" 해도 셸 판정을 따른다.
4. **게이트가 checker 보다 먼저, brake 가 평가보다 먼저.** 컴파일·테스트가 깨지면 checker 를 부르지 않고 즉시 maker 를 다시 스핀한다. 매 사이클 시작에 brake(반복·시간)부터 확인.
5. **종료는 점수 합산이 아니라 severity 게이트.** `BLOCKER 0 AND CRITICAL 0` 이라야 PASS. 가중 합("총점 높으니 통과") 금지.
6. **비가역 영역은 사람.** 운영 DB DML/DDL·돈·인가·대량발송·삭제에 닿으면(`AWAIT_USER`) 루프가 멈추고 사람을 부른다. 무인이어도 이 영역은 자동 통과 안 한다.
7. **분해는 시작 전 사람 승인 1회.** 무인 실행은 phase/step 분해가 확정된 뒤에만 시작한다. 설계가 모호해 자기완결 step 으로 못 쪼개지면 **시작하지 않는다**. 승인 후에는 사람이 빠지고, 오케스트레이터가 PASS·brake·AWAIT_USER 까지 자율 진행한다.

## 좋은 step 의 원칙 (분해 기준)

각 step 은 다음을 만족해야 한다. 못 만족하면 그건 step 이 아니다.

- **자기완결** — 다른 step 에 의존하지 않는다.
- **1 step = 1 레이어(모듈)** — 한 step 이 여러 모듈에 걸치지 않는다.
- **시그니처 수준** — 무엇을 만들지 인터페이스/시그니처로 특정된다.
- **실행 가능한 AC** — 완료를 **실행 가능한 커맨드**(테스트·빌드·린트)로 검증할 수 있다. 검증 커맨드를 못 붙이는 step 은 쪼개기가 덜 된 것이다.

**step 이 넷을 다 만족해도 phase 목표가 열거 불가능하면 그 phase 는 수렴하지 않는다.** 목표는 유한한 목록이어야 한다 — "이 다섯 파일의 이 결함들" 처럼 무엇을 다 하면 끝인지 셀 수 있어야 한다. "~하게 만든다"(예: "세웠다고 적은 장치가 실제로 잠기게 한다")는 끝나는 지점이 없는 목표다. 하나를 잠그면 checker 가 다음 안 잠긴 것을 찾고, 그것을 잠그면 또 다음을 찾는다. 사이클이 도는 동안 등급은 오르내리므로 정체 감지도 안 뜬다.

그 실수를 **사후에** 잡는 것이 `kindstreak.sh` 다(Step 2-4 의 `REPEATED_KIND`). 사전 규율이 먼저고, 감지기는 그것이 새어 나갔을 때의 그물이다.

## brake (멈춤 장치) — 값은 rubric, 집행은 이 스킬

brake **값** 은 BASE rubric(`$CLAUDE_PLUGIN_ROOT/_loop-engine/rubric.base.md`)의 PARAMS 표가 단일 원천이다(프로젝트 LOCAL rubric 이 override 할 수 있다). 이 스킬이 `loop_param` 으로 읽어 **집행** 한다.

> **집행 주체 주의(과장 금지)**: 아래 brake 중 *코드로 자가 집행* 되는 것은 `stall.sh`(정체) 한 곳뿐이다. 회차·시간·천장 brake 는 이 스킬을 모는 LLM 오케스트레이터가 **매 사이클 Step 2-1 의 brake 블록을 실제로 실행** 해야 강제된다 — 지시문이 아니라 실행에 달려 있다. 그래서 그 brake 는 주석 의사코드가 아니라 실행 블록으로 둔다.

| brake | 출처 | 이 스킬의 집행 |
|---|---|---|
| `max_iterations` (기본 5, 사용자 명시 시 그 값) | rubric PARAMS 또는 호출 인자 | 매 사이클 phase 별 `history-{phase}.jsonl` 줄 수 + 게이트 실패 카운터(`gate.fail`)를 합산해 시도를 세고 도달 시 멈춰 사람 호출. 명시값은 천장 10 으로 클램프 |
| `budget_minutes` (기본 120, **phase 당**) | rubric PARAMS | 시작 epoch 영속 → 매 사이클 벽시계 경과 확인. 전체 상한 = `budget_minutes × phase 수` |
| `stall_threshold_*` / `regress_consecutive` | rubric PARAMS | `stall.sh` 가 상태 파일로 자가 집행. `STALLED`/`REGRESS_ESCALATE` 면 멈춤 |
| 하드코딩 천장 `ABS_CEIL=10` | 이 스킬 | rubric 오설정(max_iterations 폭주) 대비 백스톱. 무슨 일이 있어도 10회 초과 금지 |
| `budget_usd`(기본 500)·`budget_tokens`(5M) | rubric PARAMS | **종료 후 참고 백스톱**. 세션 도중 누적 비용을 정확히 못 읽어 회차별 정밀 차단 불가. 실질 brake 는 회차·시간·정체 |

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
PHASES="$LOOP_DIR/phases.json"   # 분해 결과 + phase/step status 를 여기 영속(휘발성)
# 설계 문서 경로를 줬으면 실재해야 한다 — 오타나 워크트리 상대경로면 checker 가 정합 판정의 기준을
# 잃는데 그 실패는 조용하다(없는 파일을 못 읽었다고 아무도 말하지 않는다). 안 준 경우는 정상이다:
# 그때는 phases.json 의 step 과 exit_criteria 가 유일한 근거고, design_ref 는 비워 둔다.
LOOP_DESIGN_REF="${LOOP_DESIGN_REF:-}"
if [ -n "$LOOP_DESIGN_REF" ] && [ ! -f "$LOOP_DESIGN_REF" ]; then
  echo "build: 지정한 설계 문서 '$LOOP_DESIGN_REF' 가 없다 — 절대경로로 다시 준다. PASS 로 넘기지 말 것" >&2
  exit 3
fi
# 같은 티켓 재실행이면 직전 상태가 남아 정체 감지를 오염시킨다 — 새 루프면 초기화(게이트 실패 카운터 포함).
# **재개**(사람 멈춤 AWAIT_USER/STALLED/brake 후 이어가기)는 이 Step 0 자체를 다시 실행하지 않는다 —
# 아래 초기화와 params.env 재작성이 재개 상태(회차·정체·phase 진행도)를 파괴한다.
# 재개는 브랜치별 포인터(.loop/run/.active-{브랜치})와 params.env 가 살아 있는지 확인하고 곧장 Step 2 로 간다.
# 글롭에 하이픈을 넣지 않는다 — `history*.jsonl` 이 phase 별 파일과 **접미 없는 옛 판**
# (`history.jsonl`·`stall.json`)을 함께 잡는다. 0.9.x 루프가 완주 전에 멈췄으면 같은 티켓
# 디렉터리에 그 파일이 남아 있고, `history-*` 만 지우면 살아남아 종료 후 lesson 수확이
# 글롭으로 그것까지 읽어 옛 루프의 실수가 이번 교훈 후보에 섞인다.
rm -f "$LOOP_DIR/gate.fail" "$LOOP_DIR"/history*.jsonl "$LOOP_DIR"/stall*.json
date +%s > "$LOOP_DIR/started.epoch"
# brake 값. Bash 호출마다 새 셸이라 필요할 때 다시 읽는다.
ABS_CEIL=10
DEFAULT_ITER="$(source "$ENG/lib.sh" && loop_param max_iterations)"
# 시도 횟수: 호출 인자에 정수가 있으면 이 줄 위에서 MAX_ITER=N 으로 잡고(예: 5회면 MAX_ITER=5),
# 안 했으면 비워 두면 rubric 디폴트가 채운다. 어느 쪽이든 천장 10 으로 클램프.
MAX_ITER="${MAX_ITER:-$DEFAULT_ITER}"
if [ "$MAX_ITER" -gt "$ABS_CEIL" ]; then echo "명시 회차 $MAX_ITER → 천장 $ABS_CEIL 로 제한"; MAX_ITER=$ABS_CEIL; fi
BUDGET_MIN="${BUDGET_MIN:-$(source "$ENG/lib.sh" && loop_param budget_minutes)}"
# Bash 호출마다 새 셸이라 위 변수들은 다음 호출에 안 남는다 — 전부 파일로 영속해 매 Step 이 재유도한다.
# (빈 MAX_ITER 로 brake 정수 비교가 실패하면 brake 가 조용히 무력화된다 — 이 파일이 그 구멍을 막는다.)
{
  printf 'ENG=%q\nLOOP_DIR=%q\nPHASES=%q\n' "$ENG" "$LOOP_DIR" "$PHASES"
  printf 'LOOP_BASE_BRANCH=%q\nLOOP_BUILD_CMD=%q\nLOOP_TEST_CMD=%q\nLOOP_LINT_CMD=%q\n' "$LOOP_BASE_BRANCH" "$LOOP_BUILD_CMD" "$LOOP_TEST_CMD" "$LOOP_LINT_CMD"
  printf 'LOOP_CONVENTION_DOCS=%q\nLOOP_KNOWLEDGE_LAYER=%q\nLOOP_RUBRIC_LOCAL=%q\n' "$LOOP_CONVENTION_DOCS" "$LOOP_KNOWLEDGE_LAYER" "${LOOP_RUBRIC_LOCAL:-}"
  printf 'LOOP_DESIGN_REF=%q\n' "${LOOP_DESIGN_REF:-}"   # 설계 문서 경로(있으면). phases.json 의 design_ref 가 구역을 가리킨다
  printf 'MAX_ITER=%q\nBUDGET_MIN=%q\nABS_CEIL=%q\nTICKET=%q\n' "$MAX_ITER" "$BUDGET_MIN" "$ABS_CEIL" "$TICKET"
} > "$LOOP_DIR/params.env"
# 재유도 진입점 — 이후 Step 들은 이 포인터로 LOOP_DIR 를 되찾아 params.env 를 source 한다.
# 포인터는 **브랜치별** 파일이다: 한 체크아웃에서 루프 A 를 멈춰 두고(AWAIT_USER) 다른 브랜치의 루프 B 를
# 돌려도 서로의 포인터를 덮어쓰지 않는다(단일 포인터면 A 재개가 B 의 params.env 를 조용히 source 한다).
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
printf '%s\n' "$LOOP_DIR" > "$PROJECT_ROOT/.loop/run/.active-$BR"
echo "build 시작: ticket=$TICKET stack=$(printf '%s' "$DET" | jq -c '.stack') max_iter=$MAX_ITER (디폴트 $DEFAULT_ITER) budget_min=$BUDGET_MIN 천장 $ABS_CEIL"
```

> **컨텍스트 위생 — 설계와 오케스트레이션은 세션을 가른다.** 설계 문서를 이 세션에서 방금 작성했다면(스카우트 읽기·설계 초안이 이미 이 창에 쌓임) 그대로 `/build` 를 시작하지 말고, handoff 문서를 만들어 **새 세션에서** 시작하기를 권한다. 시작 시점의 창이 가벼울수록 완주 확률이 올라간다.

### Step 1. 분해 → phases.json + 착수 전 검사 + 사람 승인 (무인 시작 게이트)

입력을 Read 해서 phase/step 으로 분해한다. 위 "좋은 step 의 원칙"을 따른다. 분해 결과를 `phases.json` 으로 쓰고, **기계 검사와 스펙 완전성 점검을 거친 뒤 사람에게 승인을 받는다.** 이 승인이 무인 실행의 유일한 시작 게이트다.

**변경 하나만 수렴시키는 경우도 여기를 지난다** — phase 가 하나인 `phases.json` 을 쓴다. 사람이 JSON 을 직접 쓸 필요는 없다. 대화의 합의를 이 세션이 옮겨 적고 사람은 그것을 보고 승인한다. 그 한 번이 종전 `/loop-run` 의 브리프 확인 자리를 대신한다.

```jsonc
// phases.json — 분해 결과 + 진행 상태. phase·step 각각 4-state: pending → in_progress → done | blocked
// tiebreaks·exit_criteria·irreversible·non_goals 는 선택이 아니라 필수다(아래 "착수 전 스펙 검사").
{
  "tiebreaks": ["잠그는 것이 원본과 호출 규약을 맞추는 것보다 앞선다"],
  "phases": [
    { "name": "foundation", "status": "pending",
      "design_ref": "x.md §현재 동작 C5 데이터 모델",   // 이 phase 가 구현하는 설계 문서 구역(정합 점검 + 종료 후 문서 반영 기준)
      "exit_criteria": ["관성 분기를 지우면 그 검사가 실패한다", "빈 입력으로 부르면 exit 65 로 죽는다"],
      "irreversible": false,          // 닿으면 "운영 DB 마이그레이션" 처럼 영역을 문자열로
      "non_goals": ["수신 층", "성능 튜닝"],   // 이번에 안 볼 표면. 안 좁히면 false
      "review_scope": "phase",        // 선택. 기본 "phase"(이 phase 가 만든 파일만 렌즈에 넘긴다).
                                      // "full" 이면 안 좁힌다. **마지막 phase 는 적든 안 적든 full 이다** —
                                      // phase 끼리 부딪히는 결함을 보는 자리가 순회에 하나는 있어야 한다.
      "steps": [
        { "id": "types",  "goal": "도메인 타입 정의", "layer": "domain",
          "signature": "data class X(...)", "ac_cmd": "./gradlew :x-domain:compileKotlin",
          "status": "pending" }   // step 별 진행도 — 다음 maker 인계 때 어디까지 됐는지 근거
      ] }
  ]
}
```

- **진행 추적은 phases.json 이 전담한다** — 설계 문서(living)를 개발 중 체크마크로 오염시키지 않는다(코드가 진실, 문서 정합은 종료 후 프로젝트의 문서 정합 스킬). 각 phase 의 `design_ref` 가 그 phase 를 설계 문서의 어느 구역에 연결해, checker 의 phase 단위 정합 점검과 종료 후 문서 반영의 기준이 된다.
- 분해가 애매하면(자기완결 step 으로 안 쪼개지거나 AC 커맨드를 못 붙이면) **여기서 멈추고 사람에게 되돌린다.** 무인 시작 금지(불변 7).
- 승인되면 사람이 빠진다. 이후 Step 2 는 자율 진행한다.

#### 착수 전 스펙 검사 (통과해야 시작한다)

**무엇이 무인 완주를 가르나 — 사람 게이트가 아니라 스펙의 질이다.** 같은 날 같은 저장소에서 돌린 두 phase 가 근거다. 한 phase 는 목표를 "세웠다고 적은 장치가 실제로 잠기게 한다" 로 줬고 **여섯 사이클, 사람이 한 번 끼어들어야 닫혔다** — 목표를 항목으로 나열할 수 없어 하나를 닫으면 checker 가 다음을 찾았다. 다른 phase 는 목표를 **변이 여섯으로 미리 적어** 줬고("관성 분기를 지우면 빨개진다" 같은 것) **네 사이클, 사람이 한 번도 필요 없었다.** 차이는 스펙 하나뿐이었다. 그래서 이 스킬은 사람이 필요한지를 **실행 중에 판정하지 않고 착수 전에 검사한다.**

아래 항목은 전부 **선택이 아니다.** 하나라도 없으면 `phases.json` 을 고쳐 다시 온다 — 다른 방식으로 도는 우회로는 없다. 검사 옆에 우회로가 있으면 그 검사는 검사가 아니라 권고가 되고, 이것들이 막으려던 사고는 바로 그 우회로 쪽에서 일어났다.

1. **완료 조건을 항목으로 나열할 수 있나.** phase 마다 `exit_criteria` 를 배열로 적는다. 각 항목은 **되돌렸을 때 무엇이 빨개지는지** 를 말해야 한다("관성 분기를 지우면 그 검사가 실패한다" 처럼). "~하게 만든다" 같은 서술은 항목이 아니다 — 끝나는 지점이 없어 그 phase 가 수렴하지 않는다.
2. **되돌릴 수 없는 영역에 닿나.** phase 마다 `irreversible` 에 그 답을 적는다. 닿으면 어느 영역인지 문자열로(그 자리만 사람에게 올린다는 뜻), 안 닿으면 `false`(그 이유로 멈출 일이 없다는 뜻). 무엇이 그 목록인지는 BASE rubric 의 `force_await=always` 종류다.
3. **부딪힐 판단에 우선순위를 적었나.** 최상위 `tiebreaks` 에 측정으로 안 갈리는 트레이드오프를 미리 순서 지어 둔다. 안 적으면 오케스트레이터가 그 자리에서 멈춰 결국 사람을 부른다.
4. **이번에 안 볼 표면을 적었나.** phase 마다 `non_goals` 에 답한다. 좁히면 그 표면들을 문자열 배열로(`["수신 층", "성능 튜닝"]`), 안 좁히면 `false`. **모든 phase 에 같은 값을 복사하면 아무것도 안 좁혀진다** — 설계 문서의 "안 만드는 것" 은 작업 **전체**가 안 만드는 것이라 공통으로 깔리고, 거기에 **그 phase 만 안 보는 표면**(다음 phase 가 볼 것)을 더해야 이 칸이 일을 한다. 그 "다음 phase 가 본다" 는 문서에 없는 정보라 여기 분해에서 정해진다. 이 칸이 여는 것이 둘이다. **하나는 바로 선다** — 문서가 "안 한다" 고 적은 것을 구현하면 checker 가 `intent-nongoal-violation` 으로 내고 그 종류는 BLOCKER 라 사람을 부른다. 종류는 계약에 원래 있었는데 **적을 칸이 없어 아무도 그 기준을 받은 적이 없다.** 다른 하나는 계측이다 — 렌즈가 finding 마다 범위 안팎을 표시하고 회차 끝의 `out_of_scope` 가 그 수를 센다. **그 수는 등급을 안 바꾼다.** 회차를 다 쓰고 멈춘 자리에서 사람이 묻는 것이 "이 지적이 이번 목표 안인가" 인데 그 답이 지금까지 아무 데도 안 남았고, 이 칸이 그것을 파일로 남긴다.

기계가 보는 것은 **있는지 없는지**뿐이고, 그 검사가 아래 블록이다. 각 항목이 **정말** 되돌림과 빨개짐을 말하는지는 다음 절의 `loop-spec-checker` 와 사람이 본다.

```bash
# 착수 전 스펙 검사 — 통과해야 순회를 시작한다. 자리마다 따로 세는 이유는 사람에게 무엇을 더 적어야
# 하는지 이름으로 알려주기 위해서다(jq -e 한 방이면 "뭔가 빠졌다" 까지만 나온다). 판정은 세 jq 모두
# 결정론이고, 하나라도 없으면 exit 65 로 멈춘다 — 무인으로 길게 돌 때 사람이 없어서, 이 셋이 없으면
# 오케스트레이터가 결국 그 자리에서 멈춘다. 착수 전에 거르는 편이 싸다.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "build: params.env 없음 — Step 0 미실행/폐기됨" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a

# 공백만 든 문자열("  ")은 답이 아니다 — length 는 문자 수라 그것을 통과시킨다. test("\\S") 로 본다.
MISSING=""
# (1) 완료 조건이 항목인가 — phase 마다 비지 않은 문자열 배열.
jq -e '(.phases | type=="array" and length>0) and all(.phases[];
        .exit_criteria | type=="array" and length>0 and all(.[]; type=="string" and test("\\S")))' \
  "$PHASES" >/dev/null 2>&1 || MISSING="$MISSING exit_criteria"
# (2) 비가역 영역에 닿나 — 안 닿으면 false, 닿으면 어느 영역인지 적은 문자열. 답은 그 둘뿐이다.
#     `true` 는 "닿는데 어딘지 안 적음" 이라 거부한다 — 통과시키면 위임 오케스트레이터가 사람에게
#     올려야 할 영역 이름 없이 그 자리에 선다(위 규칙 2가 문자열을 요구하는 이유가 그것이다).
jq -e 'all(.phases[]; (.irreversible | type) as $t
        | ($t=="boolean" and .irreversible==false) or ($t=="string" and (.irreversible | test("\\S"))))' \
  "$PHASES" >/dev/null 2>&1 || MISSING="$MISSING irreversible"
# (3) 부딪힐 판단의 우선순위 — 최상위 tiebreaks, 비지 않은 문자열 배열.
jq -e '.tiebreaks | type=="array" and length>0 and all(.[]; type=="string" and test("\\S"))' \
  "$PHASES" >/dev/null 2>&1 || MISSING="$MISSING tiebreaks"
# (4) 이번에 안 볼 표면 — 안 좁히면 false, 좁히면 어느 표면인지 적은 문자열 배열. (2)와 같은 모양이다.
#     `true` 는 "좁히는데 어딘지 안 적음" 이라 거부한다 — 통과시키면 checker 가 기준으로 쓸 것이 없고,
#     `intent-nongoal-violation` 도 범위 표시도 그 phase 에서 아무것도 안 한다.
jq -e 'all(.phases[]; (.non_goals | type) as $t
        | ($t=="boolean" and .non_goals==false)
          or ($t=="array" and (.non_goals|length)>0 and all(.non_goals[]; type=="string" and test("\\S"))))' \
  "$PHASES" >/dev/null 2>&1 || MISSING="$MISSING non_goals"

[ -z "$MISSING" ] || { echo "build: 착수 전 스펙 검사 실패 —$MISSING 없음/빈값. phases.json 의 그 자리를 채우고 다시 시작한다(우회 경로 없음)." >&2; exit 65; }
echo "build: 착수 전 스펙 검사 통과"
```

#### 스펙 완전성 점검 (loop-spec-checker) — 승인 화면 앞

위 기계 검사가 통과하면 `Agent` 로 `loop-spec-checker` 를 **한 번** 띄운다. 기계가 그 자리들이 **있는지**를 봤으니 이 에이전트는 그것이 **쓸모 있는지**를 본다 — `exit_criteria` 항목이 되돌림을 말하는지, 그 phase 의 완료를 대표하는지, `irreversible` 이 실제 범위와 맞는지, 그리고 `non_goals` 가 이 phase 의 목표와 **실제로 갈리는지**. 마지막 것은 양쪽으로 어긋날 수 있다. 넓게 적으면 정상 구현이 `intent-nongoal-violation` 으로 잡혀 사람을 부르고, 좁게 적으면 아무것도 안 걸러 그 칸이 있으나 마나가 된다.

프롬프트에 담는 것: 설계 문서 경로와 `$PHASES` 경로(점검 대상), 컨벤션 문서 경로·지식층 값(`$LOOP_CONVENTION_DOCS`·`$LOOP_KNOWLEDGE_LAYER` 값 자체 — **환경변수는 서브에이전트에 전달되지 않는다**), 결과 출력 경로 `$LOOP_DIR/spec-gaps.json`.

- **결과는 경고까지고 시작을 막지 않는다.** 무엇이 load-bearing 인지는 프로젝트마다 달라, 기계가 막으면 거짓 양성으로 사람이 게이트 우회법부터 배운다. 판단은 승인하는 사람이 한다.
- **`gaps` 는 분해 승인 요청과 한 화면에 낸다.** 사람이 어차피 승인하려고 그 화면을 보고 있고, 답을 기다리는 자리를 둘로 나누면 백그라운드 잡에서 오지 않을 답을 기다리게 된다.
- 답을 반영할 곳은 설계 문서 또는 `phases.json` 이다. 반영했으면 분해가 달라졌을 수 있으므로 **이 절이 아니라 기계 검사부터** 다시 돈다.
- `gaps` 가 비면 그 사실을 한 줄로 말한다. 점검 자체가 실패하면(결과 파일이 안 생김) 그 사실만 알리고 시작은 막지 않는다 — 이 절은 경고 층이지 게이트가 아니다.

> Bash 도구 호출은 호출마다 새 셸이라 env 가 안 남는다. 그래서 회차·시작시각뿐 아니라 **brake 값·감지 명령까지 전부 파일로 영속** 한다. 이후 모든 Step 의 셸 블록은 맨 위의 재유도 프리앰블(브랜치별 포인터 `.loop/run/.active-{브랜치}` → `set -a` 로 `params.env` source)로 시작한다 — 변수 carry-over 를 가정하지 않는다. `set -a` 가 핵심이다: 그냥 source 하면 값만 복원되고 export 속성이 빠져, 채점 자식 프로세스가 `LOOP_RUBRIC_LOCAL` 을 못 읽어 LOCAL rubric 이 조용히 무시된다.

### Step 1-1. 순회를 서브에이전트에 내린다 (위임 계약)

**왜 내리나.** 순회를 이 세션이 돌면 사이클마다 오가는 것(채점 결과, maker 지시, 게이트 출력)이 전부 사람이 보고 있는 그 대화에 쌓인다. 한 phase 를 여섯 사이클 돌리면 그만큼 무거워진다. 순환 제어를 한 층 아래로 내리면 그 잡음이 위로 안 올라온다 — **아래층 출력은 띄운 쪽에게 가기 때문이다**(실측: 3,900자 출력을 내는 하위 에이전트를 그 깊이에서 돌렸더니 중간 에이전트만 전문을 받았고 최상위에는 네 줄 요약만 왔다).

**위임 오케스트레이터의 계약.** `Agent` 로 **이름 붙인 백그라운드** 오케스트레이터를 하나 띄우고, Step 2 의 phase 순회를 통째로 그 안에서 돌린다. 프롬프트에 담는 것은 그 층이 스스로 재유도할 수 없는 것뿐이다: 이 스킬 문서의 경로와 "Step 2 를 네가 돈다" 는 지시, 프로젝트 루트, 설계 문서 경로, 그리고 `phases.json` 의 `tiebreaks` 값(그 층이 판단에 쓸 순서). **담지 않는 것**: checker findings 전문, maker 보고, 게이트 출력, 설계 문서 본문 — 전부 그 층이 파일로 직접 읽는 것들이고, 프롬프트에 실으면 메인 창에 먼저 쌓여 위임의 목적이 사라진다.

**그 오케스트레이터가 정하는 것**: 어느 지적을 먼저 고칠지, 근거가 맞는지, maker 에게 다시 보낼지, 회차 안에서의 진행.

**메인이 하는 것 — 중계와 관측 안내 둘.** 순회를 내린 뒤 메인에 남는 일은 위로 올라온 것을 사람에게 전하고 답을 되돌리는 중계, 그리고 **시작할 때 진행을 볼 자리를 한 줄로 알리는 것**이다. 순회가 아래층에서 도니 화면에 아무것도 안 뜨는데, 그것이 안 돈다는 뜻이 아님을 사람이 알 길이 없다. 띄운 직후 이렇게 낸다:

```
build 시작 — phase N개, 진행은 .loop/run/{ticket}/phases.json 에서 볼 수 있다
(phase 가 하나 닫힐 때마다 여기에 한 줄로 보고된다)
```

**멈추고 위로 올리는 것 셋**:

- **되돌릴 수 없는 영역**(`force_await`·`irreversible`) — 협상 대상이 아니다.
- **범위가 바뀌는 것** — phase 목표를 좁히거나 넓히거나, `exit_criteria` 에 없는 것을 하려 할 때. 위 두 phase 실측에서 사람에게 올라간 것이 이 종류 하나였다.
- **설계가 미완이 아니라 틀렸을 때.** 단 **근거가 측정이면 올리지 않는다** — 재서 갈리는 것은 오케스트레이터가 재고 정한다. 올리는 것은 재도 안 갈리는 것뿐이고, 그중에서도 `tiebreaks` 에 답이 있으면 그것도 안 올린다.

**올리는 방법**: 자기 턴을 끝내고 메인에 짧게 보고한다 — 무엇이 왜 멈췄나, 사람에게 물을 것 한 줄. 메인이 그것을 사람에게 전달하고 답을 받아 `SendMessage` 로 재개시킨다. **위임 오케스트레이터는 사람에게 직접 말할 수 없다.** 그 층의 출력은 띄운 쪽(메인)에게만 가므로, 사람을 부르는 유일한 길이 메인을 거치는 것이다. 이 사실을 그 프롬프트에 못박는다 — 모르면 창에 대고 질문한 뒤 오지 않을 답을 기다린다.

**컨텍스트 위생은 그 층에도 그대로 걸린다**(아래 "오케스트레이터는 내용을 보유하지 않는다"). 그리고 **메인에 올리는 보고는 phase 단위 요약** 이지 사이클 잡음이 아니다 — 사이클마다 보고하면 잡음이 한 층만 늦게 같은 창에 쌓인다.

**아래층 스폰의 제약.** 위임 오케스트레이터가 maker·checker 를 띄울 때는 `run_in_background` 와 `name` 을 쓸 수 없다 — 그 깊이에서는 동기 서브에이전트만 뜬다. **checker 렌즈 셋은 한 메시지에 `Agent` 호출 셋을 담아 함께 띄우면 동기여도 병렬로 돈다.** 그 층은 팀 명부에도 화면에도 안 보이므로, 진행을 사람이 보려면 `.loop/run/{ticket}/` 의 이력 파일을 읽는다 — 화면에 안 뜬다는 것이 안 돈다는 뜻이 아니다.

**호스트가 이름 붙인 백그라운드 서브에이전트를 못 띄우면 이 세션이 Step 2 를 돈다.** 위임은 잡음이 어느 창에 쌓이는가의 문제라, 그 수단이 없는 호스트에서 스킬 자체를 못 쓰게 만들 이유가 없다. **다만 착수 전 스펙 검사는 그대로 통과해야 한다** — 그 검사는 위임 여부와 무관한 시작 조건이고, 없앤 것은 "검사에 걸렸을 때 다른 모드로 도는 길" 이지 "직접 도는 것" 자체가 아니었다. 이 퇴로로 들어왔으면 사이클 잡음이 사람 창에 쌓이므로, 한 phase 가 길어지면 세션을 나눌지 사람에게 묻는다.

### Step 2. phase 순회 (바깥 루프)

> **이 Step 을 도는 것은 Step 1-1 이 띄운 오케스트레이터다.** 아래 블록·분기·불변은 그 층이 그대로 실행한다.

`phases.json` 의 phase 를 순서대로 돈다. 각 phase 를 아래 안쪽 루프로 PASS 시키고 다음으로 넘어간다.

순회 시작 전 두 가지를 한다. 먼저 `phases.json` 이 소비 가능한 형식인지 **fail-loud 로 검증**한다. **Step 1 이 요구한 자리들도 여기서 다시 요구한다** — Step 1 의 검사는 사람 승인 앞에서 한 번 돌지만, 순회는 **재개로도 진입**하고 그 사이에 `phases.json` 이 손으로 편집될 수 있다. 소비 직전에 한 번 더 보는 것이 그 창을 닫는다. 그다음 phase 수 `N` 으로 전체 시간 상한을 재계산한다.

```bash
# 재유도 프리앰블 — 이 블록도 별도 Bash 호출이라 carry-over 를 가정하지 않는다.
# (프리앰블 없이 돌면 BUDGET_MIN 미정의 → 0 이 영속돼 모든 사이클이 즉시 brake 된다.)
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "build: params.env 없음 — Step 0 미실행/폐기됨" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a

# (1a) 착수 전 스펙 검사 재확인 — Step 1 과 같은 판정, 같은 이름 지목.
#      이 자리에 오는 파일은 정의상 Step 1 을 **안 거친** 것이다: 진행 중이던 옛 phases.json 이거나,
#      Step 1 뒤에 손으로 편집된 것. 그래서 "스키마 위반" 한 줄로 끝내면 사람이 status 오타부터
#      찾게 된다. 아래 (1b)와 나눠 두는 이유가 그 진단이다.
# `.phases` 배열 조건을 Step 1 과 **똑같이** 건다. 빼면 빈 배열에서 `all()` 이 공허하게 참이 되어
# 이 검사를 통과하고, 아래 (1b)가 대신 걸려 "스키마 위반" 한 줄로 끝난다 — 무엇이 빠졌는지
# 이름으로 알려주려고 (1a)와 (1b)를 나눈 목적이 그 경우에만 죽는다.
MISSING=""
jq -e '(.phases | type=="array" and length>0) and all(.phases[];
        .exit_criteria | type=="array" and length>0 and all(.[]; type=="string" and test("\\S")))' \
  "$PHASES" >/dev/null 2>&1 || MISSING="$MISSING exit_criteria"
jq -e 'all(.phases[]; (.irreversible | type) as $t
        | ($t=="boolean" and .irreversible==false) or ($t=="string" and (.irreversible | test("\\S"))))' \
  "$PHASES" >/dev/null 2>&1 || MISSING="$MISSING irreversible"
jq -e '.tiebreaks | type=="array" and length>0 and all(.[]; type=="string" and test("\\S"))' \
  "$PHASES" >/dev/null 2>&1 || MISSING="$MISSING tiebreaks"
jq -e 'all(.phases[]; (.non_goals | type) as $t
        | ($t=="boolean" and .non_goals==false)
          or ($t=="array" and (.non_goals|length)>0 and all(.non_goals[]; type=="string" and test("\\S"))))' \
  "$PHASES" >/dev/null 2>&1 || MISSING="$MISSING non_goals"
# 여기 걸리는 흔한 경우는 **옛 버전이 만든 진행 중 분해**다(자리가 늘면 그 전에 만든 파일이 전부
# 걸린다). **채우는 것은 사람이다** — `non_goals` 를 적는 것이 phase 목표를 좁히는 일이라, 위
# "멈추고 위로 올리는 것 셋" 이 오케스트레이터에게 직접 하지 말라고 적은 바로 그 종류다.
[ -z "$MISSING" ] || { echo "build: phases.json 에 착수 전 스펙 검사 자리가 없다 —$MISSING 없음/빈값. 사람이 그 자리만 채우고 재개한다(안 좁혔으면 false) — 분해를 새로 쓰지 않는다(done 진행도가 날아간다). 우회 경로 없음." >&2; exit 65; }

# (1b) 순회가 소비하는 자리 검증 — score.sh 의 변질 입력 exit 65 거부와 같은 결.
#      .phases 비배열/빈배열, phase 의 name·steps 누락, step 의 ac_cmd 누락(AC 없으면 step 이 아님),
#      status 가 pending/in_progress/done/blocked 밖 — 하나라도 걸리면 멈추고 사람 호출.
#      name 은 파일명으로도 쓰인다(history-{phase}.jsonl 등) — '/' 가 들어가면 경로로 해석돼 생성이 깨지므로 금지.
jq -e '
  (.phases | type=="array" and length>0)
  and all(.phases[];
    (.name | type=="string" and length>0 and (contains("/") | not))
    and (.status | IN("pending","in_progress","done","blocked"))
    and (.steps | type=="array" and length>0)
    and all(.steps[];
      (.ac_cmd | type=="string" and length>0)
      and (.status | IN("pending","in_progress","done","blocked"))))
' "$PHASES" >/dev/null || { echo "build: phases.json 스키마 위반 — 무인 시작 중단, 사람 호출" >&2; exit 65; }

# (2) 전체 시간 상한을 phase 수 비례로 재계산 — 재개로 이 블록이 재실행돼도 멱등하도록,
#     phase 당 원값(BUDGET_MIN_PHASE)을 따로 영속하고 늘 그 원값에서 곱한다(이미 곱한 BUDGET_MIN 에 재곱 금지).
NPHASE=$(jq '.phases | length' "$PHASES")
BUDGET_MIN_PHASE="${BUDGET_MIN_PHASE:-$BUDGET_MIN}"
BUDGET_MIN=$(( BUDGET_MIN_PHASE * NPHASE ))
printf 'BUDGET_MIN_PHASE=%q\nBUDGET_MIN=%q\n' "$BUDGET_MIN_PHASE" "$BUDGET_MIN" >> "$LOOP_DIR/params.env"
echo "build 전체 시간 상한: ${BUDGET_MIN}분 (phase 당 ${BUDGET_MIN_PHASE} × ${NPHASE}개)"
```

**phase 진입 — 상태를 phase 스코프로 가른다:**

```bash
# 앞 phase 의 회차·정체 잔재가 다음 phase 판정을 오염하지 않게 phase 진입마다 재정의·영속한다.
# (phase 1 이 PASS 로 floor 를 낮춘 stall.json 을 phase 2 가 물려받으면 첫 사이클부터 "floor 미갱신"이
#  쌓여 거짓 STALLED 가 뜬다 — stall 도 반드시 phase 별 파일로.)
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "build: params.env 없음 — Step 0 미실행/폐기됨" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a
PHASE="<이 phase 의 name>"
# PHASE 자체도 영속 — 뒤 채점(scored-$PHASE.json)·done 갱신(jq --arg p "$PHASE")이 별도 Bash 호출이라,
# 영속 없이는 프레시 셸에서 PHASE 가 빈 문자열이 되어 scored 파일이 겹쳐 쓰이고 done 갱신이 조용히 no-op 된다.
printf 'PHASE=%q\nHIST=%q\nSTATE=%q\n' "$PHASE" "$LOOP_DIR/history-$PHASE.jsonl" "$LOOP_DIR/stall-$PHASE.json" >> "$LOOP_DIR/params.env"
rm -f "$LOOP_DIR/gate.fail"   # 게이트 실패 카운터도 phase 단위로 리셋
touch "$LOOP_DIR/history-$PHASE.jsonl"
# 들어오는 순간의 변경 상태를 파일별 해시로 적어 둔다. Step 2-2 가 이것과 비교해 **이 phase 가
# 실제로 만든 것**만 렌즈에 넘긴다. 스냅숏이 없으면 그 단계가 좁히기를 건너뛰고 전 범위를
# 넘기므로, 이 줄이 빠져도 점검이 헐거워지지 않고 느려지기만 한다(안전한 쪽으로 떨어진다).
python3 "$ENG/review_scope.py" snapshot --base "$LOOP_BASE_BRANCH" \
  --out "$LOOP_DIR/scope-open-$PHASE.txt" --root "$PROJECT_ROOT"
echo "phase 진입: $PHASE"
```

#### Step 2-1. 사이클 시작 — brake 선확인 + 게이트 층

매 사이클 **맨 먼저** brake 부터 본다. 그 다음 결정론 게이트(컴파일·테스트). 게이트가 깨지면 checker 를 부르지 않는다.

```bash
# 재유도 프리앰블 — 새 셸엔 앞 Step 의 변수가 없다. 브랜치별 포인터→params.env 로 전부 복원한다(없으면 fail-loud).
# set -a: export 속성까지 복원 — 없으면 채점 자식 프로세스가 LOOP_RUBRIC_LOCAL 을 못 읽어 LOCAL rubric 이 조용히 무시된다.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "build: params.env 없음 — Step 0 미실행/폐기됨. 멈추고 사람 호출" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a
ITER=$(wc -l < "$HIST" 2>/dev/null | tr -d ' '); ITER=${ITER:-0}
GFAIL=$(cat "$LOOP_DIR/gate.fail" 2>/dev/null || echo 0)   # 게이트 실패 재진입 횟수 — checker 없는 공회전도 brake 가 세게
ELAPSED_MIN=$(( ( $(date +%s) - $(cat "$LOOP_DIR/started.epoch") ) / 60 ))
echo "사이클 진입: phase=$PHASE 완료 $ITER 회 + 게이트 실패 $GFAIL 회 / 경과 ${ELAPSED_MIN}분"
# brake: 반복·시간·천장. 주석 의사코드가 아니라 실행 블록이다 — 매 사이클 실제로 돌아야 강제된다.
if [ $((ITER + GFAIL)) -ge "$MAX_ITER" ] || [ $((ITER + GFAIL)) -ge "$ABS_CEIL" ] || [ "$ELAPSED_MIN" -ge "$BUDGET_MIN" ]; then
  echo "build: brake 도달 (iter=$ITER + 게이트실패 $GFAIL / $MAX_ITER 천장 $ABS_CEIL, 경과 ${ELAPSED_MIN}/${BUDGET_MIN}분) — 평가 없이 종료, 사람 호출" >&2
  # 더 진행하지 말고 Step 2-4 분기 2(brake) → Step 3 으로.
fi
# 점검 대상이 실제로 있나 — 베이스 오감지·빈 작업이면 finding 0 이 거짓 PASS 로 둔갑한다. **여기가 결정론 1차 방어**고, 채점의 reviewed 게이트는 checker 가 그 뒤에 반쯤 죽는 경우를 받는다.
CHANGED=$(git diff --name-only "$LOOP_BASE_BRANCH"...HEAD 2>/dev/null | wc -l | tr -d ' ')
DIRTY=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
if [ "${CHANGED:-0}" -eq 0 ] && [ "${DIRTY:-0}" -eq 0 ]; then
  echo "build: 점검 대상 변경 0건 ($LOOP_BASE_BRANCH...HEAD + uncommitted) — PASS 아님. 베이스 브랜치 확인 필요, 멈추고 사람 호출" >&2
  # 조용히 통과 금지. **echo 만 하고 흘려보내면 산문과 코드가 어긋난다**:
  # 여기서 안 멈추면 checker 가 빈 diff 를 보고 깨끗하다고 답하고 그게 PASS 가 된다.
  exit 3
fi
# 게이트: 컴파일 먼저(빠름), 통과하면 변경 모듈 테스트(또는 전체).
# 출력은 창이 아니라 파일로 받는다. 실패하면 파서가 항목 큐로 바꾸고, 창에는 한 줄 목록만 낸다.
GQ="$LOOP_DIR/gate-queue.jsonl"
: > "$GQ"   # 매 사이클 새로 채운다. 앞 회차에 고쳐진 항목이 남으면 maker 가 이미 없는 오류를 쫓는다.
GATE_FAILED=0
run_gate() {   # run_gate <단계라벨> <명령>
  [ -n "$2" ] || { echo "build: $1 게이트 명령 비어있음 — 스킵(셋업에서 LOOP_${1}_CMD 직접 지정 가능)" >&2; return 0; }
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
  echo "게이트 실패 — 항목 $TOTAL 건이 $GQ 에 쌓였다. Step 2-5 가 여기부터 처리한다."
  jq -r '"\(.stage)\t\(.kind)\t\(.file // "-"):\(.line_number // "-")\t\((.message // .test // "")[0:80])"' "$GQ" | head -20
  [ "$TOTAL" -gt 20 ] && echo "(위 20건만 표시 — 나머지 $((TOTAL - 20)) 건은 $GQ 에 있다. 잘라낸 것을 통과로 읽지 말 것)"
fi
```

- 컴파일·테스트 **실패** = 게이트 층 RETRY. 먼저 아래 자기완결 증가를 실행해 실패 횟수를 영속한다(위 brake 가 회차와 합산해 세는 값). 별도 Bash 호출에서 실행되므로 `$GFAIL` 셸 변수에 기대면 안 된다 — 미정의 변수는 산술에서 0 이라 카운터가 항상 1 로 리셋된다. 그 뒤 checker 를 부르지 않고 **Step 2-5(maker 스핀)** 로 가서 고친 뒤 이 사이클을 다시 연다. 단, 깨진 게 maker 가 못 고치는 운영 비가역이면 사람 대기.

  ```bash
  # 자기완결 증가 — 파일에서 읽어 +1 해 파일로. 셸 변수 carry-over 불필요.
  PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
  BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
  LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR")"
  G="$LOOP_DIR/gate.fail"; echo $(( $(cat "$G" 2>/dev/null || echo 0) + 1 )) > "$G"; cat "$G"
  ```
- **게이트 실패의 산출물은 버리지 않는다 — `gate-queue.jsonl` 이 그 사이클 maker 의 입력이다.** 창에는 한 줄 목록만 나가고 원문은 `$LOOP_DIR/gate-<단계>.out` 에 남아, 필요한 항목만 maker 가 열어 본다.
  - **아는 형식이 하나도 없어도 큐가 비지 않는다.** 파서가 출력 꼬리를 `gate-output-unparsed` 항목 하나로 남긴다. 조용히 버리면 큐가 비어 게이트가 통과한 것처럼 보이고, 그 오독이 이 큐가 막는 실패다.
  - 형식은 실제 출력에서 뜬 것이다. Kotlin 2.x 는 **열 번호 뒤에 콜론이 없다**. 형식 회귀는 `_loop-engine/test_gate_parse.py` 가 잡는다.
- 린트 게이트가 필요하면 `run_gate LINT "${LOOP_LINT_CMD:-}"` 를 게이트 사슬에 덧붙인다(빈 값이면 스킵).
- 게이트 통과면 Step 2-2 로.

#### Step 2-2. checker 렌즈 셋을 병렬로 (독립·적대 시선)

**`Agent` 호출 셋을 한 메시지에 담아 함께 띄운다.** 렌즈마다 담당 차원이 다르고 서로를 모른다(불변 2).

| 렌즈 | 담당 차원 | 무엇을 의심하나 |
|---|---|---|
| `contract` | compatibility · intent | 약속한 것과 다른가 |
| `safety` | security · runtime | 돌 때 터지거나 새는가 |
| `quality` | convention · simplicity | 더 나은 형태가 있는가 |

**환경변수는 서브에이전트에 전달되지 않는다** — 아래 값 전부를 프롬프트 텍스트로 넘긴다. 세 프롬프트가 공유하는 것과 렌즈마다 다른 것을 가른다.

- 공통: 설계 문서 경로와 이 phase 의 `design_ref`·step 목록, **이 phase 의 `exit_criteria` 항목 전부**, **이 phase 의 `non_goals`**, 비교 베이스 `$LOOP_BASE_BRANCH`, 컨벤션 문서 `$LOOP_CONVENTION_DOCS`·지식층 `$LOOP_KNOWLEDGE_LAYER`(비었으면 "없음" 명시 — checker 가 "컨벤션 문서 없음, 신뢰도 제한" 경로를 정직하게 타게), 종류 어휘 rubric 두 경로(BASE `$ENG/rubric.base.md`, LOCAL `$LOOP_RUBRIC_LOCAL` 있으면).
- 렌즈마다: **렌즈 이름과 담당 차원**, 그리고 **그 렌즈 전용 출력 경로**.
- 그리고 **점검 범위** — 아래 블록이 낸 값을 그대로 옮긴다. 파일 목록이 나왔으면 "지적은 이 파일들 안에서 낸다, 나머지는 배경으로만 읽는다" 를 함께 적고, "전 범위" 가 나왔으면 그대로 적는다.

**점검 범위를 왜 좁히나 — 안 좁히면 마지막 phase 의 렌즈가 첫 phase 를 처음부터 다시 읽는다.** 비교 베이스는 Step 0 에서 한 번 정해지고 순회 내내 그대로라, 렌즈가 보는 양은 phase 가 진행될수록 자라기만 한다. 실측에서 회차 하나가 76분이었고 게이트는 그중 14초였다 — 나머지는 렌즈가 **누적된** 변경을 읽는 시간이다. 여덟째 회차의 렌즈도 첫 회차와 같은 2,600줄을 여덟 번째로 읽었다. `review_scope.py` 가 phase 진입 스냅숏과 지금을 견줘 **이 phase 가 실제로 만든 파일**만 뽑는다. 경로 목록이 아니라 내용 해시로 재는 것이 요점이다 — 목록으로 재면 **앞 phase 가 만든 파일을 이번 phase 가 고친 경우**가 빠지고, 빠져도 아무 검사가 실패하지 않는다(`_loop-engine/test_review_scope.py` 가 그 성질을 든다).

**좁히기가 공짜가 아니라서 전 범위를 보는 자리를 하나 남긴다.** 좁히면 phase 끼리 부딪히는 결함이 안 보인다 — 첫 phase 의 코드와 다섯째 phase 의 코드가 맞물려 깨지는 자리가 그렇다. 그래서 **마지막 phase 는 자동으로 안 좁히고**, 중간 phase 도 필요하면 `review_scope: "full"` 로 그렇게 만든다. 되돌림 확인처럼 전 범위를 다시 도는 phase 가 그 자리로 적당하다.

**`exit_criteria` 를 왜 checker 에 넘기나 — 안 넘기면 아무도 안 재기 때문이다.** 착수 전 검사는 그 항목이 *있는지* 만 보고, PASS 판정은 `BLOCKER 0 AND CRITICAL 0` 이라 그 phase 의 완료 조건과 무관하다. 그 사이에 "관성 분기를 지우면 그 검사가 실패한다" 를 적어 두고 실제로 그런지 재는 자리가 없었다. 항목을 프롬프트에 실으면 점검자가 그것을 **정합 판정의 기준**으로 삼아, 조건이 성립하지 않으면 `intent-requirement-missing` 으로 낸다(그 dimension floor 가 MAJOR 라 `RETRY_SOFT` 가 되어 다음 회차로 돌아간다). 평가 *계산기* 는 고정이고 **평가 대상 기준을 phase 가 가져오는 것**이 이 구조가 작업마다 달라지는 방식이다 — 계산기까지 매번 새로 지으면 같은 코드가 회차마다 다른 등급을 받아 정체 감지가 무너지고, 루프가 코드 대신 기준을 낮춰 통과할 수 있다.

**그리고 성립 여부를 파일로 받는다.** `exit_criteria` 를 받은 checker 는 출력에 `exit_criteria_probes` 를 함께 낸다(계약은 `agents/loop-checker.md`) — 조건마다 무엇을 되돌려 무엇이 빨개졌는지, 어떤 명령으로 쟀는지가 들어간다. **이 필드는 채점에 안 들어가고 병합본에도 안 실린다. 렌즈별 결과 파일이 정본이다.** 그런데도 표준으로 두는 이유는 아래 분기에서 사람이 phase 를 닫을지 정할 때 **그것이 유일한 근거**이기 때문이다. 요구해야 생기는 것은 계약이 아니다.

**`non_goals` 도 같은 이유로 넘긴다 — 안 넘기면 그 칸이 아무 일도 안 한다.** 넘기면 렌즈가 그것을 두 가지로 쓴다. 첫째, 그 표면을 실제로 구현한 것이 보이면 `intent-nongoal-violation`(BLOCKER)으로 낸다. 둘째, finding 마다 `in_scope` 로 이번 목표 안팎을 표시한다. **표시는 등급을 안 바꾼다** — `decide.sh` 가 `out_of_scope` 로 세기만 하고 verdict 는 등급만으로 정해진다(계약은 `_loop-engine/decide.sh` 헤더). 세는 이유는 아래 "완료 조건이 전부 성립했는데" 분기에서 사람이 답해야 하는 물음이 정확히 그것이고, 지금까지 그 답이 파일에 없었기 때문이다. 확신이 안 서는 finding 은 범위 **안**으로 기울이는 것이 계약이다 — 안 쟀거나 애매한 것이 통과 방향으로 떨어지지 않게 하는 이 엔진의 규율과 같은 방향이다.

**maker 가 보고한 것을 checker 프롬프트에 절대 넣지 마라**(불변 1). 한 줄짜리 `ok` 도 옮기지 않는다.

```bash
# 재유도 프리앰블(Step 2-1 과 동일) 뒤에: 렌즈별 결과 경로를 잡고 **비운다.**
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "build: params.env 없음 — Step 0 미실행/폐기됨. 멈추고 사람 호출" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a
# 랜덤 mktemp 는 쓰지 않는다 — Bash 호출마다 셸이 새로 떠 그 변수는 다음(병합) 호출에 안 남는다.
# 결정적 경로라야 스핀 프롬프트와 Step 2-3 병합이 같은 곳을 가리킨다. .loop/run/ 하위라 gitignore.
# **phase 별로도 가른다**: 단일 파일을 phase 가 공유하면 앞 phase 의 잔여가 남아, 다음 phase 에서
# 비우기를 빠뜨리고 checker 가 안 쓰면 그 옛 결과가 채점돼 미점검 phase 가 done 으로 둔갑한다.
LENSES="contract safety quality"
for L in $LENSES; do : > "$LOOP_DIR/checker-$PHASE-$L.json"; done
# 프롬프트에 넣을 값을 창에 출력한다 — 변수 대입만으론 오케스트레이터가 값을 알 수 없다(대입은 stdout 이 없다).
echo "checker 렌즈: $LENSES"
echo "checker 공통 값: base=$LOOP_BASE_BRANCH / conv=[${LOOP_CONVENTION_DOCS:-없음}] / knowledge=[${LOOP_KNOWLEDGE_LAYER:-없음}] / base_rubric=$ENG/rubric.base.md / local_rubric=[${LOOP_RUBRIC_LOCAL:-없음}]"
# 이번 phase 가 안 볼 표면. `false` 면 안 좁힌 것이라 렌즈는 모든 finding 을 범위 안으로 표시한다.
# 값을 창에 내야 프롬프트에 그대로 옮길 수 있다 — 변수 대입만으론 오케스트레이터가 값을 모른다.
# **phase 를 하나로 못 집으면 값을 내지 않고 멈춘다.** 이 줄의 출력은 렌즈 프롬프트에 그대로
# 옮겨지는 값이라, 여기에 진단 문구를 실으면 렌즈가 그것을 "안 볼 표면" 의 이름으로 받는다.
# 빈 `PHASE` 도 이 경로로 떨어지고(위 "영속 없이" 주석이 적는 실패 모드), 이름이 둘 이상이면
# 뒤엣것의 답이 조용히 사라진다 — (1b) 스키마 검사에 이름 유일성 조건이 없어 통과하는 입력이다.
NON_GOALS=$(jq -er --arg p "$PHASE" '[.phases[] | select(.name==$p) | .non_goals]
  | if   length != 1              then empty
    elif (.[0] | type) == "array" then (.[0] | join(" / "))
    else "없음(표면을 안 좁힘 — 전부 범위 안)" end' "$PHASES") || {
  echo "build: phases.json 에서 phase '$PHASE' 를 하나로 못 집었다(없거나 같은 이름이 둘 이상) — PHASE 값과 phase 이름을 확인한다. 멈춤" >&2; exit 65; }
echo "이번 phase 의 non_goals: $NON_GOALS"
# 점검 범위 — 이 phase 가 실제로 만든 것. phase 진입 스냅숏과 지금을 견줘 뽑는다.
# **마지막 phase 는 안 좁힌다.** 좁히면 phase 끼리 부딪히는 결함을 아무도 안 보게 되므로,
# 전 범위를 보는 자리가 순회 안에 반드시 하나는 있어야 한다. 중간 phase 도 필요하면
# `review_scope: "full"` 로 그렇게 만들 수 있다.
LAST_PHASE="$(jq -r '.phases[-1].name' "$PHASES")"
WANT="$(jq -r --arg p "$PHASE" '[.phases[] | select(.name==$p) | .review_scope // "phase"] | .[0]' "$PHASES")"
if [ "$PHASE" = "$LAST_PHASE" ] || [ "$WANT" = "full" ]; then
  echo "점검 범위: 전 범위 — $LOOP_BASE_BRANCH...HEAD 전부 (이유: $([ "$PHASE" = "$LAST_PHASE" ] && echo '마지막 phase' || echo 'review_scope=full'))"
else
  # **줄을 세지 않고 빈 문자열인지 본다.** `grep -c ''` 는 빈 입력에서 `0` 을 찍고 종료코드 1 로
  # 끝나 `|| echo 0` 이 한 번 더 찍는다. 그러면 값이 `0\n0` 이 되어 정수 비교가 죽고, 하필
  # **아래 안전 분기를 건너뛰어 빈 목록이 렌즈로 넘어간다**(실측). 세는 값이 안내 문구에만
  # 쓰이는데 그것 때문에 판정이 갈리는 자리라, 세기를 없애는 것이 그 갈래를 통째로 지운다.
  SCOPE="$(python3 "$ENG/review_scope.py" since --base "$LOOP_BASE_BRANCH" \
    --snapshot "$LOOP_DIR/scope-open-$PHASE.txt" --root "$PROJECT_ROOT")"
  if [ -z "$SCOPE" ]; then
    # 빈 목록을 넘기면 렌즈가 볼 것이 없다고 읽는다 — 좁히기 실패와 "아무것도 안 고쳤다" 가
    # 같은 값이라, 여기서는 안전한 쪽인 전 범위로 떨어진다. Step 2-6 이 트리 미변경을 따로 잡는다.
    echo "점검 범위: 이 phase 가 바꾼 파일 0건 — 좁히지 않고 전 범위를 넘긴다"
  else
    echo "점검 범위: 아래 파일들 — 지적은 이 안에서 내고 나머지는 배경으로만 읽는다"
    printf '%s\n' "$SCOPE" | sed 's/^/  /'
  fi
fi
for L in $LENSES; do echo "  렌즈 $L 출력 경로: $LOOP_DIR/checker-$PHASE-$L.json"; done
```

> 모델: checker 는 frontmatter 에 모델을 고정하지 않는다 — 기본은 호출한 세션의 모델을 상속한다. 특정 모델로 돌리려면 `Agent` 호출에 `model` 파라미터를 지정한다.
>
> effort: checker 는 frontmatter 에 `effort: xhigh` 를 **고정한다** — 모델과 달리 세션을 상속하지 않는다. 적발률이 곧 탐색량인 자리라, 세션 등급을 내려도 판정부는 따라 내려가면 안 되기 때문이다. `Agent` 호출로는 재정의할 수 없다. 계약은 `core/effort-ladder.md`.

#### Step 2-3. 렌즈 결과 병합 + 결정론 채점

렌즈 셋이 끝나면 결과를 **개수를 세어** 합치고 채점 파이프에 흘린다. **severity 는 셸이 매긴다 — checker 등급을 쓰지 않는다.**

```bash
# 재유도 프리앰블 — Step 2-1 과 동일. 변수 carry-over 를 가정하지 않는다.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "build: params.env 없음 — Step 0 미실행/폐기됨. 멈추고 사람 호출" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a
F="$LOOP_DIR/checker-findings-$PHASE.json"
# 병합이 곧 검사다. --expect 로 렌즈 수를 못박아, 한 축이 조용히 죽었을 때 남은 둘만으로 채점하지
# 않는다 — 안 돈 축은 점검된 적이 없고 그걸 통과로 읽으면 그 차원의 결함이 영영 안 잡힌다.
# 빈 파일·형식 위반·렌즈 간 base 불일치도 여기서 exit 65 로 걸린다(어느 렌즈인지 이름으로 알려준다).
bash "$ENG/merge_findings.sh" --expect 3 \
  "contract=$LOOP_DIR/checker-$PHASE-contract.json" \
  "safety=$LOOP_DIR/checker-$PHASE-safety.json" \
  "quality=$LOOP_DIR/checker-$PHASE-quality.json" > "$F" || {
  echo "build: 렌즈 결과 병합 실패 — 위 메시지가 어느 축인지 말한다. 그 축만 다시 띄우거나 멈춰 사람 호출" >&2
  exit 65
}
SCORED=$(bash "$ENG/score.sh" "$F") || {
  echo "build: 채점이 입력을 거부했다(exit 65) — checker 출력 계약 위반. 흔한 원인은 깨끗한 결과에 reviewed 를 안 채운 것. 멈춰 사람 호출" >&2
  exit 65
}                                                                # finding 마다 severity·await 부여
VERDICT=$(printf '%s' "$SCORED" | bash "$ENG/decide.sh")         # {verdict, counts, out_of_scope, await}
STALL=$(printf '%s' "$VERDICT"  | bash "$ENG/stall.sh" --state "$STATE")   # 정체 판정 + 상태 영속
ITER=$(( $(wc -l < "$HIST" 2>/dev/null | tr -d ' ') + 1 ))
jq -nc --argjson it "$ITER" \
       --argjson v "$VERDICT" \
       --argjson s "$SCORED" \
  '{iteration:$it, verdict:$v.verdict, findings:($s.findings // [])}' >> "$HIST"   # 한 줄 = 한 사이클
# 같은 **종류**가 사이클을 연속 지배하는지. stall.sh 는 등급 개수만 봐서 이걸 못 본다.
# **반드시 위 append 뒤에** 부른다 — 이번 회차가 이력에 들어간 뒤라야 이번 회차가 판정에 포함된다.
KINDST=$(bash "$ENG/kindstreak.sh" --history "$HIST") || {
  echo "build: 반복 종류 감지가 이력을 거부했다(exit 65) — history 파일 확인. 멈춰 사람 호출" >&2
  exit 65
}
printf '%s' "$SCORED" > "$LOOP_DIR/scored-$PHASE.json"   # maker 단계(Step 2-5)가 finding 단위로 여는 정본
V=$(printf  '%s' "$VERDICT" | jq -r .verdict)
ST=$(printf '%s' "$STALL"   | jq -r .status)
KS=$(printf '%s' "$KINDST"  | jq -r .status)
echo "사이클 $ITER → verdict=$V / stall=$ST / counts=$(printf '%s' "$VERDICT" | jq -c .counts)"
# 범위 계측 — **판정에 안 들어간다.** verdict 는 위 등급만으로 정해지고 이 줄은 세기만 한다.
# `미표시` 가 총 finding 수와 같으면 렌즈가 표시를 통째로 빠뜨린 것이다. 그 회차의 범위 수치는
# 근거로 쓰지 않는다 — 0 이 "범위 밖이 없다" 가 아니라 "아무도 안 쟀다" 이기 때문이다.
printf '%s' "$VERDICT" | jq -r '.out_of_scope
  | "범위 밖(계측, 판정 무관): BLOCKER=\(.BLOCKER) CRITICAL=\(.CRITICAL) MAJOR=\(.MAJOR) MINOR=\(.MINOR) / 미표시=\(.unmarked)"'
echo "반복 종류: $(printf '%s' "$KINDST" | jq -r '"\(.status) kind=\(.kind // "-") streak=\(.streak)/\(.threshold)"')"
# 렌즈별 적발 수 — 한 축이 매번 0건이면 그 렌즈 프롬프트를 의심할 근거가 된다(빈 결과는 증거가 아니다).
printf '%s' "$SCORED" | jq -r '[.findings[] | .lens // "?"] | group_by(.) | map("\(.[0])=\(length)") | "렌즈별 적발: " + join(" ")'
# 오케스트레이터 컨텍스트 위생: findings 의 evidence 전문을 cat/Read 로 창에 끌어들이지 않는다.
# 아래 한 줄 목록(등급·종류·위치)까지만 보고, 전문은 maker 단계에서 finding 단위로만 연다.
printf '%s' "$SCORED" | jq -r '.findings[] | "\(.severity)\t\(.dimension)/\(.kind)\t\(.location)"'
```

- 채점 셸이 `exit 65` 로 죽으면 checker 가 findings 를 못 썼거나 형식이 깨진 것이다 — **조용히 PASS 로 넘기지 말고** 멈춰 사람에게 보고. fail-loud 가 설계다.

#### Step 2-4. verdict + stall 분기 (우선순위 순서대로)

아래 **위에서부터** 먼저 걸리는 것을 따른다.

1. `V == AWAIT_USER` → **멈춤, 사람 호출.** 비가역·자동화 금지 영역(BLOCKER/force_await). maker 가 손대면 안 된다.
2. brake 도달(`ITER + GFAIL >= MAX_ITER` 또는 `>= ABS_CEIL` 또는 `ELAPSED_MIN >= BUDGET_MIN`) → **멈춤, 사람 호출.** 현재까지의 best 상태와 남은 finding 을 요약해 넘긴다. **`exit_criteria_probes` 가 있으면 조건별 성립 여부를 함께 넘긴다** — 사람이 "한 회차 더" 와 "여기서 닫는다" 를 가르는 재료가 그것이다(아래 블록). **회차 요약의 범위 계측(`out_of_scope`)도 함께 넘긴다** — 조건이 성립했나와 남은 지적이 이번 목표 안인가는 같은 판단의 두 반쪽이다.
3. `ST == STALLED` 또는 `ST == REGRESS_ESCALATE` → **멈춤, 사람 호출.** 헛바퀴/악화. `RETRY_SOFT`(MAJOR 만)로 정체한 경우 사람에게 "이 MAJOR 안고 통과할까?" 승인 옵션을 같이 제시한다 — **simplicity 지적이 이 자리에 자주 온다**(더 단순한 형태가 있다는 판단은 갈릴 수 있고, floor 가 MAJOR 인 것이 그 뜻이다).
4. `KS == REPEATED_KIND` → **멈춤, 사람 호출.** 다만 3번과 **전할 말이 다르다.** 3번은 "코드가 안 고쳐진다" 이고 이건 **"같은 종류가 N 사이클 연속으로 이 phase 를 지배했다 — 코드가 아니라 phase 목표를 의심하라"** 다. 사람에게 물을 것 둘: 이 목표가 **열거 가능한가**, **끝나는 지점이 정의됐는가**. 코드를 한 번 더 고치는 것으로는 닫히지 않는다.
5. `V == PASS` → 이 phase `status=done`, **메인에 한 줄 보고**, 다음 phase 로. 남은 phase 가 없으면 Step 3.
6. `V == RETRY` 또는 `V == RETRY_SOFT` (그리고 위 brake/stall/반복 종류 미도달) → **Step 2-5(maker 스핀)** 로.

> **완료 조건이 전부 성립했는데 조건 밖 지적만 남았으면 — 사람이 그 phase 를 닫을 수 있다.** PASS 는 `BLOCKER 0 AND CRITICAL 0` 이고 **그 phase 의 완료 조건을 안 본다.** 그래서 조건을 다 만족하고도 조건 **밖** CRITICAL 때문에 안 닫히는 상태가 성립한다. 사람이 고를 것은 셋이다. (a) 회차 상한을 올려 한 번 더 돈다. (b) **여기서 닫고 남은 지적을 다음 phase 로 세운다** — `phases.json` 에 phase 를 하나 더하면 회차가 새로 시작된다. 회차 상한은 "한 목표에 몇 번까지 매달릴 것인가" 라, 목표가 바뀌면 새로 세는 것이 맞다(편법이 아니다). (c) 목표가 애초에 열거 불가능했다고 보고 `exit_criteria` 를 다시 적는다. **이 판단은 자동으로 못 한다** — 조건 성립은 checker 가 되돌림으로 재지만 "이 지적이 조건 밖인가" 는 사람이 정한다. 2026-08-11 `agent-ts` 의 저장 계층 첫 phase 가 완료 조건 열한 개를 전부 만족하고도 조건 밖 CRITICAL 때문에 회차 상한 여덟을 다 썼고, (b) 로 닫았다.
>
> **판단은 여전히 사람이 하되, 재료는 이제 파일에 있다.** phase 가 `non_goals` 에 안 볼 표면을 적었으면 렌즈가 finding 마다 안팎을 표시하고 회차 요약의 `out_of_scope` 가 그 수를 센다. **그 수는 등급을 안 내린다.** 세는 것과 판정하는 것을 갈라 둔 이유는 근거가 아직 한 저장소 한 루프뿐이어서다 — 재는 장치를 먼저 두고, 수치가 쌓인 뒤에 강등을 얹을지 정한다. 읽을 때 조건이 하나 있다: **`미표시` 가 총 건수와 같은 회차의 수치는 근거가 아니다.** 그건 범위 밖이 없다는 뜻이 아니라 렌즈가 표시를 안 달았다는 뜻이다.
>
> **설계 drift 는 무인이 판단하지 않는다(사람 게이트).** 실제 구현이 최초 설계(`design_ref`)와 달라져야 한다고 maker 가 보고하거나, checker 가 "코드가 설계와 다른데 코드 쪽이 맞아 보인다"를 잡으면 — 코드를 설계에 맞추는 걸로 끝내지 않고 **`AWAIT_USER` 로 멈춰 사람에게 설계 재결정을 맡긴다.** 이 스킬은 "설계대로 구현"이 목표이지 "설계를 고쳐 구현"이 아니다.

phase 가 PASS 하면 `status=done` 으로 갱신한다. 갱신은 Read/Edit 가 아니라 Bash 의 jq 로 한다 — Read 는 파일 전문을 오케스트레이터 창에 다시 주입한다:

```bash
# 프리앰블로 PHASE·PHASES 를 params.env 에서 복원(프레시 셸에서 빈 PHASE 면 jq 가 0건 매칭 no-op 된다).
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR")"; set -a; . "$LOOP_DIR/params.env"; set +a
jq --arg p "$PHASE" '(.phases[] | select(.name==$p)).status = "done"' "$PHASES" > "$PHASES.tmp" && mv "$PHASES.tmp" "$PHASES"
# 갱신 검증 — jq 는 매칭 0건이어도 exit 0 으로 원본을 그대로 내므로, 실제로 done 이 됐는지 확인해야 fail-loud 다.
jq -e --arg p "$PHASE" '[.phases[] | select(.name==$p) | .status] == ["done"]' "$PHASES" >/dev/null \
  || { echo "build: phase '$PHASE' done 갱신 실패(매칭 0건/중복 이름) — 멈추고 사람 호출" >&2; exit 65; }
```

#### Step 2-5. maker 스핀 (고침)

`Agent` 툴로 `loop-maker` 를 **회차마다 새로 한 번** 띄운다. **오케스트레이터는 코드를 쓰지 않는다**(불변 1). 같은 maker 를 `SendMessage` 로 이어가지 않는다 — 한 maker 가 열 회차를 살면 회차마다 읽은 파일·편집·빌드 출력을 전부 지고 간다. **회차 간에 필요한 것은 대화가 아니라 워킹 트리와 반복 표시로 전달된다.**

행동 규칙(배정 범위만·테스트 동반·컴파일 자기 검증·설계 결함 시 보고·`ok`/`blocked` 종료·커밋 금지)은 `loop-maker` 정의가 담당하므로 프롬프트에 반복하지 않는다. **환경변수는 서브에이전트에 전달되지 않으니 아래 값 전부를 프롬프트 텍스트로 넘긴다.**

1. **이 phase 의 step 들**(goal·layer·signature·ac_cmd)과 `design_ref`. **`ac_cmd` 가 곧 자기 검증 명령이다.**
2. **이번 회차 입력 파일 경로 하나**: 아래가 고르는 것. **둘 다 주지 않는다.**
3. **반복 표시**: 아래 명령이 내는 목록. finding 마다 몇 회차째인지.
4. **이전까지 완료한 phase(status=done)들이 무엇을 구현했는지 1~2줄**(진행 맥락).
5. **컨벤션 문서 경로**: `$LOOP_CONVENTION_DOCS` 값. 비었으면 "없음".
6. **빌드 명령**: `$LOOP_BUILD_CMD` 값. 비었으면 "없음".

**입력은 두 갈래이고 게이트 큐가 먼저다.**

```bash
# 재유도 프리앰블(Step 2-1 과 동일) 뒤에:
GQ="$LOOP_DIR/gate-queue.jsonl"
if [ -s "$GQ" ]; then MAKER_INPUT="$GQ"; echo "maker 입력: 게이트 큐 $(wc -l < "$GQ" | tr -d ' ')건"
else MAKER_INPUT="$LOOP_DIR/scored-$PHASE.json"; echo "maker 입력: 채점 큐 $MAKER_INPUT"; fi
# 반복 표시 — finding 마다 몇 회차째 같은 kind@location 인가. 프롬프트에 이 출력을 그대로 넣는다.
# stall.sh 는 루프 전체의 no_progress 만 내고 finding 단위 반복은 안 낸다. history 에서 뽑는다.
# $HIST 가 phase 별 파일이라 이 집계도 phase 안에서만 센다 — 앞 phase 의 finding 이 섞이지 않는다.
[ -s "$HIST" ] && jq -rs '
  [ .[] | .iteration as $it | (.findings // [])[] | {k: "\(.kind)@\(.location)", it: $it} ]
  | group_by(.k) | map({key: .[0].k, cycles: (map(.it) | unique)})
  | map(select(.cycles | length > 1)) | sort_by(-(.cycles | length))
  | .[] | "\(.cycles | length)회차째  회차=\(.cycles | join(","))  \(.key)"
' "$HIST" || echo "(반복 없음 — 첫 회차이거나 매번 새 finding)"
echo "빌드: ${LOOP_BUILD_CMD:-없음} / 컨벤션: ${LOOP_CONVENTION_DOCS:-없음}"
```

- **`gate-queue.jsonl` 이 비어 있지 않으면 그것.** 게이트가 깨진 사이클이라는 뜻이고, 이때 `scored-{phase}.json` 은 **이번 사이클 것이 아니다** — 게이트가 깨지면 checker 를 부르지 않아 Step 2-3 이 돌지 않았고, 그 파일은 앞 사이클에서 남은 값이다. 그걸 주면 maker 가 없는 문제를 쫓는다. 불변 4의 연장이다.
- **`gate-output-unparsed` 항목이 섞여 있으면** 파서가 그 도구의 형식을 모른 것이다. maker 가 꼬리를 읽고 고치되, 같은 형식이 반복되면 `gate_parse.py` 에 패턴을 더할 후보로 사람에게 보고하라고 한 줄 덧붙인다.
- **오케스트레이터는 이 파일들의 전문을 창에 끌어오지 않는다.** 경로만 넘기고 maker 가 읽는다. 린트 게이트는 항목이 수천 개가 될 수 있다.
- **테스트 동반 강제는 rubric 이 지탱한다.** KINDS 표의 `test-missing`(convention, CRITICAL)이 BASE 에 등록돼 있어 LOCAL rubric 없이도 작동한다.
- **`blocked` 로 끝났으면 다음 maker 를 띄우지 않는다.** 사유를 사람에게 넘긴다(`AWAIT_USER`).

> 모델·effort: `loop-maker` 는 frontmatter 에 `model: opus`·`effort: high` 를 기본으로 둔다 — 구현은 생산 작업이라 두 축 모두 세션 아래로 내리고, 판정은 `effort: xhigh` 로 고정된 checker 가 맡는 비대칭이 전제다. 회차 난도에 따라 `Agent` 호출의 `model` 파라미터로 상향·하향할 수 있지만 `effort` 는 호출로 못 바꾼다. 계약은 `core/effort-ladder.md`.

#### Step 2-6. 트리가 실제로 바뀠는지 확인 (게이트 전)

maker 가 `ok` 로 끝냈다고 코드가 바뀐 것은 아니다. **보고는 거짓일 수 있고 트리는 아니다.** 안 바뀐 상태로 Step 2-1 로 가면 게이트가 같은 결과를, checker 가 같은 finding 을 내고 회차만 탄다.

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
  echo "build: maker 스핀 후 워킹 트리가 그대로다 — 회차가 아니라 정체 신호. 게이트를 돌리지 말고 사람 호출" >&2
  # Step 2-4 분기 3(정체)과 같이 처리한다. 같은 결과를 N번 내지 않는 것이 이 루프의 전제다.
fi
```

**Step 2-5 진입 직전에도 같은 명령으로 스냅숏을 갱신한다.** 그러면 비교 대상이 "이번 maker 가 손대기 전" 이 된다.

통과하면 **Step 2-1** 로 돌아가 다음 사이클을 연다(게이트부터 다시).

> **오케스트레이터는 코드를 쓰지 않는다.** 순환 제어(phase 순회·게이트 실행·checker 스핀·병합·채점·분기)만 한다. 실제 편집은 전부 maker 서브에이전트 안에서 일어나 오케스트레이터 컨텍스트에 안 쌓인다. 이게 여러 phase 롱런을 버티게 하는 핵심이다.

> **오케스트레이터는 내용을 보유하지 않는다(컨텍스트 위생).** 롱런 완주는 오케스트레이터 창이 얼마나 가볍게 유지되느냐에 달려 있다. 규칙 다섯: (1) checker findings·scored JSON 의 evidence 전문을 cat/Read 하지 않는다 — 채점은 경로째 셸에 넘기고, 창에는 counts 와 등급·종류·위치 한 줄 목록만 남긴다. (2) maker 완료 보고는 `ok` 한 줄로 받는다(요약이 필요하면 명시로 요구하되 상한 5줄). (3) SendMessage 는 짧게 — 도구 결과가 보낸 전문을 에코한다. (4) phases.json·설계 문서를 다시 Read 하지 않는다 — 상태 갱신·조회는 jq 로. (5) git 확인은 `--stat`·`--name-only` 수준까지만.

### Step 3. 전체 완료 처리 (커밋하지 않는다)

모든 phase 가 `done` 이면 사람에게 보고: 완료 phase 목록, phase 별 사이클 수, 남은 MINOR(기록만), 변경 요약.

- **변경 요약은 maker 보고를 모아 쓰지 않고 `git diff "$LOOP_BASE_BRANCH"...HEAD --stat` 과 `git status --short` 에서 뽑는다** — maker 는 회차마다 새로 띄워져 전체를 아는 주체가 없고, 트리가 유일한 정본이다.
- **커밋·push 하지 않는다.** 변경은 워크트리에 누적된 채 남긴다. 논리 단위 커밋·PR 은 프로젝트의 마감 워크플로우에서 사람이 마감한다.
- 롱런으로 uncommitted 가 커지면 phase 경계를 따라 쪼개 커밋하도록 제안한다.
- 종료 후 `/lessons` 로 이 루프의 `history-*.jsonl` 에서 잡힌 실수를 ANTIPATTERNS 후보로 올릴지 제안한다(선순환). 강제 아님. history 가 phase 별 여러 파일이므로 `lessons.sh` 를 파일마다 반복 호출해 mistake 목록을 합쳐 synthesizer 에 넘긴다.
- **종료 후 설계 문서 정합 반영 제안.** 각 phase 의 `design_ref` 가 어느 구역을 대조해야 하는지 짚어줘 사람이 코드↔문서를 처음부터 전수 대조하지 않게 한다. 강제 아님, 반영 주체는 사람.

### Step 3-1. 종료 정리 (런타임 상태 폐기)

`$LOOP_DIR`(phases.json·history-*.jsonl·stall·렌즈별 결과·게이트 출력·tree.snapshot)는 루프 한정 휘발성이다. **lesson 종합 다음에만** 폐기한다(종합 전 삭제 시 선순환 입력 소멸).

```bash
# 이 블록도 별도 Bash 호출이라 LOOP_DIR 를 포인터에서 재유도한다. 재유도 없이 돌면 빈 LOOP_DIR 로
# rm 이 아무것도 못 지우면서 종료코드 0 을 내, 상태가 그대로 남은 채 "정리했다" 로 읽힌다(실측 확인).
# 그러면 phases.json 이 전 phase done 인 채 남아, 같은 티켓의 다음 build 가 "미완 phase 없음"으로 읽는다.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
PTR="$PROJECT_ROOT/.loop/run/.active-$BR"
LOOP_DIR="$(cat "$PTR" 2>/dev/null)"
# 폐기는 lesson 종합(또는 사람이 생략 결정) 후에만. 지울 것이 없으면 그렇다고 말하고 끝낸다(재실행 안전).
[ -n "$LOOP_DIR" ] || { echo "build: 포인터 없음 — 지울 상태가 없다(이미 폐기됐거나 Step 0 미실행)" >&2; exit 0; }
rm -rf "$LOOP_DIR"
rm -f "$PTR"         # 이 브랜치의 재유도 포인터도 함께 — 남으면 다음 루프의 프리앰블이 죽은 경로를 가리킨다.
echo "build: 런타임 상태 폐기 — $LOOP_DIR"
```

- **사람 멈춤(AWAIT_USER/STALLED/brake)으로 재개 여지가 있으면 바로 폐기하지 않는다.** `phases.json`·`stall-*.json`·`started.epoch`·`params.env` 가 남아 있어야 이어서 돌릴 수 있다(없으면 다음 시작이 리셋돼 정체 감지가 무력화). 사람이 그 작업을 닫기로 하면 그때 lesson 종합 후 폐기.
- 워크트리째 버리는 경우엔 `.loop/run/` 도 같이 사라지니 별도 폐기가 불필요하지만, **메인 체크아웃이나 워크트리를 남겨 둔 경우엔 이 단계가 정리를 보장**한다.

## 재개 (중단된 롱런 이어가기)

사람 멈춤으로 중단됐다 재개할 때는 `phases.json` 을 jq 로 조회해(`jq -r '.phases[] | select(.status != "done") | .name' "$PHASES" | head -1` — 전문 Read 금지) `status=done` phase 를 건너뛰고 첫 `pending`/`blocked` phase 부터 Step 2 를 다시 연다. done phase 는 다시 개발하지 않는다(멱등). 재개 시 Step 0 의 초기화(history 비우기·stall 삭제·epoch 갱신)는 다시 타지 않는다.

**재개도 순회를 직접 돌지 않는다.** Step 1(분해·승인)은 건너뛰지만 **Step 1-1 은 건너뛰지 않는다** — 오케스트레이터를 새로 띄우고 그 안에서 Step 2 를 연다. 이 세션이 이어서 도는 것은 없앤 직접 모드가 재개라는 문으로 돌아오는 것이고, 중단된 롱런일수록 남은 사이클이 많아 잡음이 가장 크게 쌓이는 자리다.

## 백그라운드 세션 실행

사람이 빠져도 계속 돌게 하려면 이 세션을 백그라운드 잡으로 띄운다. 분해 승인(Step 1)을 받은 그 세션에서 `/build` 를 걸고 자리를 비운다. 페이즈 경계마다 `PushNotification` 으로 알리게 배선하면 자리를 비운 동안에도 진행이 굴러가고, AWAIT_USER/brake 에서만 사람이 불려온다.

이것은 순회 위임(Step 1-1)과 **다른 축**이고 함께 쓴다 — 백그라운드 잡은 **세션이 사람 없이 도는** 것이고, 위임은 **사이클 잡음이 어느 창에 쌓이는가** 다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `loop: base rubric 없음` | plugin 번들 `rubric.base.md` 부재(설치 손상) | plugin 재설치, 또는 `LOOP_RUBRIC_BASE` 로 pin |
| 빌드/테스트 명령이 비어 게이트 스킵 | `detect_build.py` 가 빌드 시스템 미인식 | 매니페스트 확인. 비표준이면 셋업에서 `LOOP_BUILD_CMD`/`LOOP_TEST_CMD` 를 직접 지정 |
| `merge_findings: 렌즈 결과가 3 개여야 하는데 2 개 왔다` | 렌즈 하나가 안 떴거나 죽었다 | 그 축만 다시 띄운다. **남은 둘로 채점하지 않는다** — 안 돈 축은 점검된 적이 없다 |
| `merge_findings: 렌즈 '<이름>' 의 결과 파일이 비었거나 없다` | 그 축 checker 가 출력 경로에 못 씀 | 그 렌즈 프롬프트에 출력 경로를 넘겼는지 확인. 경로는 스핀 전 블록이 echo 한 값 |
| `merge_findings: 렌즈마다 비교 베이스가 다르다` | 렌즈들에게 다른 base 를 넘겼다 | 공통 값은 세 프롬프트에 같은 문자열로. 서로 다른 diff 를 본 결과는 합칠 수 없다 |
| `score.sh: 입력 형식 오류 — exit 65` | 병합 결과가 계약 위반 | 병합 전 렌즈 파일들을 본다. `[ -s ]`·형식 검사는 merge 가 먼저 잡는다 |
| `loop: findings 도 reviewed 도 비었다 — exit 65` | 렌즈 전부가 빈 결과 + `reviewed` 미기입. 흔한 진짜 원인은 **베이스 브랜치 해석이 어긋나 diff 가 통째로 빈 것** | 베이스 브랜치와 diff 범위를 먼저 확인한다. PASS 로 넘기지 말 것 |
| 한 렌즈만 매번 0건 | 그 축 프롬프트가 잘못됐거나 담당 차원이 안 넘어감 | Step 2-3 의 "렌즈별 적발" 줄로 확인. **빈 결과를 깨끗함의 증거로 읽지 않는다** |
| 회차가 갈수록 느려진다 | 비교 베이스가 순회 내내 고정이라 렌즈가 읽는 양이 자란다 | Step 2-2 의 "점검 범위" 줄을 본다. 매번 "전 범위" 로 나오면 phase 진입 스냅숏이 안 만들어진 것이다 |
| 점검 범위가 매번 전 범위로 나온다 | phase 진입 블록의 `review_scope.py snapshot` 이 안 돌았거나, 그 phase 가 마지막이거나 `review_scope: "full"` 이다 | 진입 줄의 출력과 `phases.json` 의 그 필드를 본다. **좁히기 실패는 느려질 뿐 헐거워지지 않는다** — 급하지 않다 |
| 좁혔더니 앞 phase 코드와 맞물린 결함을 놓쳤다 | 전 범위를 보는 phase 가 실질적으로 없었다 | 마지막 phase 는 자동으로 안 좁힌다. 그 phase 가 전 범위를 실제로 도는 내용인지 본다(되돌림 확인 같은 것) |
| 정체 감지가 매번 INIT | 사이클 간 `stall-{phase}.json` 이 사라짐 | `--state "$STATE"` 경로가 사이클 간 동일한지 확인. Step 0 에서만 초기화 |
| 회차가 안 늘어남 | `history-{phase}.jsonl` append 누락 | Step 2-3 의 append 가 매 사이클 1줄 추가하는지 확인(줄 수 = 회차) |
| 무한 같은 finding | maker 가 안 고치고 재진입 | Step 2-6 트리 확인이 잡는다. 그게 정체로 뜨면 못 고치는 finding 이므로 AWAIT_USER |
| `build: 착수 전 스펙 검사 실패` | Step 1 에서 `phases.json` 에 필수 자리 하나가 없다(메시지가 이름을 지목한다) | 그 자리를 채우고 다시 시작한다. **우회 경로는 없다** |
| `build: phases.json 에 착수 전 스펙 검사 자리가 없다` | 같은 판정이 **순회 입구(1a)** 에서 났다. 흔한 원인은 옛 버전이 만든 진행 중 분해 | **사람이** 그 자리만 채우고 재개한다(안 좁혔으면 `false`). **Step 1 로 돌아가지 않는다** — 거기는 분해를 새로 쓰는 단계라 `status=done` 진행도가 날아간다 |
| `build: phases.json 에서 phase '<이름>' 를 하나로 못 집었다` | `PHASE` 가 비었거나 오타이거나, 같은 이름의 phase 가 둘 이상 | 재개가 `PHASE` 를 물려받았는지 먼저 본다(빈 값이면 그쪽이다). 이름이 겹치면 하나로 만든다 — 이력·결과 파일이 이름으로 갈린다 |
| `build: phases.json 스키마 위반` | name·steps·ac_cmd·status 중 하나가 계약 밖 | 위 (1b) 조건을 보고 고친다. 필수 자리 누락은 (1a)가 따로 이름을 지목한다 |
| maker 가 매 회차 같은 접근을 반복 | 반복 표시를 프롬프트에 안 넣었다 | Step 2-5 의 `jq` 출력을 프롬프트에 그대로 넣는다. 이게 회차 간 유일한 기억이다 |
| maker 스핀 후 트리 그대로 | 자기 검증에서 컴파일이 깨져 아무것도 못 고쳤거나, `blocked` 인데 스핀을 계속함 | Step 2-6 이 잡는다. maker 의 종료 문자열이 `blocked` 였는지 확인 |
| 게이트 큐가 `gate-output-unparsed` 한 건뿐 | `gate_parse.py` 가 그 도구의 오류 형식을 모름 | 그 항목의 꼬리로 고치되, 반복되면 파서에 패턴 추가 후보로 보고. **큐가 비는 것보다 이게 낫다** |
| 모든 finding 이 CRITICAL | checker 가 dimension 오타 | `score.sh` 가 모르는 dimension 을 보수적으로 CRITICAL 처리. 렌즈가 담당 차원을 정확히 받았는지 확인 |
| simplicity 지적으로 회차만 탄다 | 등가 대안 없는 지적이 반복 | 그 렌즈 프롬프트가 quality 렌즈 규율(등가 대안 필수·diff 증분만)을 담았는지 확인. 정체하면 사람 승인으로 통과 |

## Non-Goals

- **1회 점검·보고** — 그건 `/review`(사람이 곧 루프). 이 스킬은 코드를 고치며 수렴까지 돈다.
- **lesson → ANTIPATTERNS 반영** — 종료 후 `/lessons`(사람 승인 게이트)가 처리. 이 스킬은 history 만 남긴다.
- **커밋·push·PR** — 프로젝트의 마감 워크플로우 소관. 이 스킬은 워크트리 누적까지만.
- **회차별 토큰·달러 정밀 차단** — 세션 밖 드라이버 몫. 여기선 회차·시간·정체 + 종료 후 비용 백스톱.
- **severity 를 LLM 이 매기는 것** — 결정론 셸이 매긴다(같은 코드 = 같은 등급).
- **무엇을 만들지 도출하는 것** — 이 스킬은 실행층이다. 결정이 안 된 자리는 착수 전 검사가 되돌린다.
