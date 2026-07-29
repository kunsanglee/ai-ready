---
name: loop-build
description: 무인 멀티-phase 빌드아웃 루프. 설계 문서를 phase/step 으로 분해해 사람 승인받은 뒤, 각 phase 를 maker 서브에이전트로 개발하고 loop-run 과 같은 판정부(checker→결정론 채점 rubric)로 PASS 까지 수렴시키며 phase 를 순차 전진한다. loop-run 이 "하나의 변경을 수렴"이라면 이 스킬은 "여러 phase 를 무인으로 빌드아웃"이다. maker 는 phase 마다 새 서브에이전트(이전 phase 노이즈 차단), 그 phase 안에서는 SendMessage 로 같은 maker 를 이어가(수렴 맥락 유지). 호출 /loop-build [phase당회차] [설계문서경로]. Use this skill when the user says "/loop-build", "여러 페이즈 무인 개발", "설계대로 쭉 빌드해", "phase 순회 루프", or wants to autonomously build out a multi-phase spec end to end. 단일 변경 수렴은 /loop-run, 1회 점검은 /loop-review.
---

# loop-build — 무인 멀티-phase 빌드아웃 루프

> human-on-the-loop 의 멀티-phase 확장. 호출: `/loop-build [phase당회차] [설계문서경로]`. 사람이 설계를 확정해 넘기고 빠지면, 이 세션이 **오케스트레이터** 가 되어 설계를 phase/step 으로 쪼개고 각 phase 를 서브에이전트 maker 로 개발하며 loop-run 판정부로 수렴시켜 여러 phase 를 순차 전진한다.

## loop-run 과의 관계 (무엇을 공유하고 무엇이 다른가)

이 스킬은 **loop-run 을 감싸는 바깥 층** 이다. loop-run 내부는 건드리지 않고 그 판정부를 재사용한다.

| | loop-run | loop-build (이 스킬) |
|---|---|---|
| 목적 | 하나의 변경을 PASS 까지 수렴 | 설계를 여러 phase 로 나눠 무인 빌드아웃 |
| 오케스트레이터 | 메인 세션(= 순수 오케스트레이터, 코딩 안 함) | **동일** |
| maker | **매 회차 새 `loop-maker` 서브에이전트** | **phase 마다 새 `loop-maker` 서브에이전트**(그 phase 안의 RETRY 는 SendMessage 로 이어감) |
| checker | 매 사이클 새 `loop-checker` 서브에이전트 | **동일** (재사용) |
| 채점 | `_loop-engine` 셸(score/decide/stall) + BASE/LOCAL rubric | **동일** (재사용) |
| 범위 | `origin/main...HEAD + uncommitted` | phase 별 diff, 누적은 워크트리 |

즉 **각 phase 의 안쪽 루프는 loop-run 의 Step 1~6 과 같다**. 다른 건 두 가지뿐이다: (1) maker 의 수명이 회차가 아니라 phase 다, (2) 바깥에 phase 순회가 감싼다. 0.9.5 이전에는 (1)이 "maker 가 메인 세션이 아니라 서브에이전트" 였다. loop-run 이 maker 를 세션에서 떼면서 그 차이가 사라지고 수명 하나만 남았다.

## 🔌 plugin 구조 (loop-run 과 공유)

- `ai-ready` plugin 의 일부. 판정 엔진은 loop-run 과 **같은 번들** 을 쓴다: `$CLAUDE_PLUGIN_ROOT/_loop-engine`(채점 셸 + `lib.sh` 의 `loop_param` + `detect_build.py`), `$CLAUDE_PLUGIN_ROOT/_loop-engine/rubric.base.md`(BASE rubric), `$CLAUDE_PLUGIN_ROOT/agents/loop-checker.md`.
- 프로젝트 사실(빌드·테스트·린트·티켓·베이스 브랜치·컨벤션 docs·지식층)은 loop-run 과 똑같이 `detect_build.py` 가 런타임 감지. 별도 어댑터 파일 없음.
- 프로젝트 LOCAL rubric(`.loop/rubric.md`)·지식층(`docs/ANTIPATTERNS.md`)도 loop-run 과 공유.
- 런타임 상태는 `$CLAUDE_PROJECT_DIR/.loop/run/{ticket}/`(loop-run 과 같은 자리, 티켓 슬러그로 분리). phase 진행 상태(`phases.json`)와 phase 별 history·stall·checker-findings·scored, 재유도 스냅숏 `params.env` 를 여기에 둔다 — 루프 한정 휘발성, `.gitignore` 로 `.loop/run/` 제외.

## 핵심 불변 (loop-run 5개 상속 + 2개 추가)

loop-run 의 핵심 불변 5개를 상속한다: (1) maker/checker 분리 + 둘 다 오케스트레이터가 아님, (2) severity 는 셸이 매김, (3) 게이트가 checker 보다·brake 가 평가보다 먼저, (4) 종료는 점수 합산이 아니라 `BLOCKER 0 AND CRITICAL 0` severity 게이트, (5) 비가역 영역(운영 DB DML/DDL·돈·인가·대량발송·삭제)은 `AWAIT_USER`. 상세는 loop-run SKILL.md 의 "핵심 불변" 절.

**예외 하나.** loop-run 불변 1은 maker 도 checker 도 **매 회차** 새로 띄운다고 못박는데, maker 에 한해 아래 불변 6이 그것을 대체한다. 여기서 수명 단위는 회차가 아니라 phase 다. checker 는 예외 없이 매 사이클 새로 띄운다.

멀티-phase 라서 두 개를 **추가** 한다:

6. **phase 격리 + phase 내 연속성(loop-run 불변 1의 "매 회차" 를 maker 에 한해 대체).** maker 는 phase 마다 **새 서브에이전트** 로 띄운다 — 이전 phase 의 편집 노이즈가 오케스트레이터에도 다음 maker 에도 안 쌓인다(롱런 컨텍스트 보존). 단 **한 phase 안의 RETRY 사이클은 `SendMessage` 로 같은 maker 를 이어간다** — 매 사이클 새 Task 를 띄우면 그 phase 의 수정 맥락("이 파일을 왜 이렇게 고쳤는지")을 잃어 같은 파일 반복 수정에서 역행한다. phase = maker 1명, 사이클 = 그 maker 에게 finding 을 이어 보냄.
7. **분해는 시작 전 사람 승인 1회.** 무인 실행은 phase/step 분해가 확정된 뒤에만 시작한다. 설계가 모호해 자기완결 step 으로 못 쪼개지면 **시작하지 않는다**(loop-run 의 "작업 지시 모호하면 시작 안 함"의 phase 판). 승인 후에는 사람이 빠지고, 오케스트레이터가 PASS·brake·AWAIT_USER 까지 자율 진행한다.

## 좋은 step 의 원칙 (분해 기준)

각 step 은 다음을 만족해야 한다. 못 만족하면 그건 step 이 아니다.

- **자기완결** — 다른 step 에 의존하지 않는다.
- **1 step = 1 레이어(모듈)** — 한 step 이 여러 모듈에 걸치지 않는다.
- **시그니처 수준** — 무엇을 만들지 인터페이스/시그니처로 특정된다.
- **실행 가능한 AC** — 완료를 **실행 가능한 커맨드**(테스트·빌드·린트)로 검증할 수 있다. 검증 커맨드를 못 붙이는 step 은 쪼개기가 덜 된 것이다.

## 입력

1. **설계 문서/spec 경로**: phase/step 분해의 원본. 도메인 설계 문서(예: `docs/design/domain_{name}.md`)나 grill 합의 spec. 형식 무관 — 오케스트레이터가 읽어 phase/step 으로 분해한다. **경로가 없으면**: 직전 대화·세션에 design/spec 이 있으면 그걸 확인해 쓰고, 없으면 "어느 설계 문서를 빌드할지" 요청하고 대기한다 — 분해할 원본 없이 무인 시작하지 않는다(불변 7).
2. **phase 당 회차(선택)**: 위치 인자 중 **정수** = phase 당 `max_iterations`(각 phase 를 몇 사이클까지 수렴 시도). loop-run 의 회차가 "전체 상한"인 것과 달리 여기선 **phase 마다** 적용된다. 명시 없으면 rubric 기본(5, `_loop-engine/rubric.base.md` PARAMS). 전체를 묶는 상한도 loop-build 는 이 `budget_minutes` 를 **phase 당**으로 해석해 전체 시간 상한 = `budget_minutes × phase 수` 로 잡는다 — phase 가 늘수록 자동 확장돼 뒤 phase 가 시간 부족으로 잘리지 않는다(max_iterations 와 같은 phase-당 패턴). rubric `budget_minutes`(기본 120)는 loop-run 에선 전체 상한, loop-build 에선 phase 당 상한이다. **예산·토큰(`budget_usd`/`budget_tokens`)도 같은 phase-당 해석**(전체 = × phase 수)이지만, 핸드오프(케이스3)에선 세션 도중 정밀 못 읽어 **종료 후 참고 백스톱**이다 — 실질 brake 는 회차·시간·정체. 호출은 `/loop-build [회차] [경로]` 순으로 회차를 먼저 둔다(loop-run `/loop-run [회차]` 와 일관). 파싱은 타입으로 가른다 — 정수=회차, 파일경로=spec 이라 순서가 뒤바뀌어도 안전.
3. **비교 베이스**: `$LOOP_BASE_BRANCH`(Step 0 감지, 기본 `origin/main`).

## 작업 흐름

### Step 0. 셋업 (loop-run Step 0 과 동일)

loop-run SKILL.md 의 **Step 0 셋업 블록을 그대로 실행** 한다(`PROJECT_ROOT`·`ENG`·`detect_build.py` 감지·`LOOP_*` 변수·`LOOP_DIR`·`.gitignore` 에 `.loop/run/` 추가·brake 값 읽기·베이스 ref 검증). 두 가지를 더한다: (1) 호출 인자 중 **정수**가 있으면 loop-run Step 0 을 실행하기 **전에** `MAX_ITER=<정수>` 로 export 한다 — loop-run Step 0 이 `MAX_ITER="${MAX_ITER:-$DEFAULT_ITER}"` 로 받으므로 그 값이 그대로 phase 당 상한이 되고(천장 10 클램프도 그대로 상속), 없으면 rubric 기본(5)이 채운다. (2) phase 진행 상태 파일을 준비한다.

```bash
# 호출 인자 중 정수가 있으면 loop-run Step 0 실행 전에 MAX_ITER=<정수> 로 잡아 phase 당 회차로 넘긴다.
# (loop-run Step 0 을 먼저 실행: PROJECT_ROOT/ENG/LOOP_DIR/LOOP_BASE_BRANCH/MAX_ITER/BUDGET_MIN 확보 + params.env 영속)
# 이 블록이 Step 0 과 같은 Bash 호출이 아닐 수 있어 LOOP_DIR 를 포인터에서 재유도한다 — 빈 LOOP_DIR 면
# PHASES 가 '/phases.json' 이 되고 append 가 파일시스템 루트를 향한다(실측: 그 경로는 쓰기 실패).
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "loop-build: params.env 없음 — loop-run Step 0 을 먼저 실행" >&2; exit 65; }
PHASES="$LOOP_DIR/phases.json"   # 분해 결과 + phase 별 status 를 여기 영속(휘발성)
printf 'PHASES=%q\n' "$PHASES" >> "$LOOP_DIR/params.env"   # 재유도용 — 이후 Step 은 프리앰블이 params.env 로 복원
```

> **컨텍스트 위생 — 설계와 오케스트레이션은 세션을 가른다.** 설계 문서를 이 세션에서 방금 작성했다면(스카우트 읽기·설계 초안이 이미 이 창에 쌓임) 그대로 loop-build 를 시작하지 말고, handoff 문서를 만들어 **새 세션에서** `/loop-build` 를 시작하기를 권한다. 오케스트레이터는 여러 phase 롱런을 버텨야 하는 세션이라, 시작 시점의 창이 가벼울수록 완주 확률이 올라간다.

### Step 1. 스펙 분해 → phase/step + 사람 승인 (무인 시작 게이트)

입력 설계 문서를 Read 해서 phase/step 으로 분해한다. 위 "좋은 step 의 원칙"을 따른다. 분해 결과를 `phases.json` 으로 쓰고 **사람에게 승인을 받는다**. 이 승인이 무인 실행의 유일한 시작 게이트다.

```jsonc
// phases.json — 분해 결과 + 진행 상태. phase·step 각각 4-state: pending → in_progress → done | blocked
{
  "phases": [
    { "name": "foundation", "status": "pending",
      "design_ref": "domain_x.md §현재 동작 C5 데이터 모델",   // 이 phase 가 구현하는 설계 문서 구역(정합 점검 + 종료 후 문서 반영 기준)
      "steps": [
        { "id": "types",  "goal": "도메인 타입 정의", "layer": "domain",
          "signature": "data class X(...)", "ac_cmd": "./gradlew :x-domain:compileKotlin",
          "status": "pending" }   // step 별 진행도 — 다음 maker 인계 때 어디까지 됐는지 근거
      ] }
  ]
}
```

- **진행 추적은 phases.json 이 전담한다** — 설계 문서(living)를 개발 중 체크마크로 오염시키지 않는다(코드가 진실, 문서 정합은 종료 후 프로젝트의 문서 정합 스킬 — 예: c8c-api `/finalize`·`/sync-docs`). 각 phase 의 `design_ref` 가 그 phase 를 설계 문서의 어느 구역에 연결해, checker 의 phase 단위 정합 점검과 종료 후 문서 반영의 기준이 된다. phase·step 의 `status` 로 어디까지 구현됐는지 추적하고, 다음 maker 인계 때 그 근거로 쓴다.
- 분해가 애매하면(자기완결 step 으로 안 쪼개지거나 AC 커맨드를 못 붙이면) **여기서 멈추고 사람에게 되돌린다**. 무인 시작 금지(불변 7).
- 승인되면 사람이 빠진다. 이후 Step 2 는 자율 진행한다.

### Step 2. phase 순회 (바깥 루프)

`phases.json` 의 phase 를 순서대로 돈다. 각 phase 를 아래 안쪽 루프로 PASS 시키고 다음으로 넘어간다.

순회 시작 전 두 가지를 한다. 먼저 `phases.json` 이 소비 가능한 형식인지 **fail-loud 로 검증**한다. 무인 시작 후엔 사람이 빠져 조용한 순회 오작동(status 오타로 phase 를 영영 pending 으로 봐 무한 순회하거나 건너뜀)을 잡을 사람이 없으므로, `score.sh` 가 변질된 checker JSON 을 exit 65 로 거부하는 것과 같은 결로 소비 직전에 거른다. 그다음 Step 1 에서 확정된 phase 수 `N` 으로 전체 시간 상한을 phase 수 비례로 재계산한다 — Step 0 이 loop-run 방식으로 잡은 phase 당 `BUDGET_MIN`(rubric `budget_minutes`, 기본 120)에 `N` 을 곱한다:

```bash
# 재유도 프리앰블(loop-run Step 1 과 동일) — 이 블록도 별도 Bash 호출이라 carry-over 를 가정하지 않는다.
# (프리앰블 없이 돌면 BUDGET_MIN 미정의 → 0 이 영속돼 모든 사이클이 즉시 brake 된다.)
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "loop-build: params.env 없음 — Step 0 미실행/폐기됨" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a

# (1) phases.json fail-loud 검증 — 무인 시작·재개 직전. score.sh 의 변질 입력 exit 65 거부와 같은 결.
#     .phases 비배열/빈배열, phase 의 name·steps 누락, step 의 ac_cmd 누락(AC 없으면 step 이 아님),
#     status 가 pending/in_progress/done/blocked 밖 — 하나라도 걸리면 멈추고 사람 호출.
#     name 은 파일명으로도 쓰인다(history-{phase}.jsonl 등) — '/' 가 들어가면 경로로 해석돼 생성이 깨지므로 금지.
jq -e '
  (.phases | type=="array" and length>0) and all(.phases[];
    (.name | type=="string" and length>0 and (contains("/") | not))
    and (.status | IN("pending","in_progress","done","blocked"))
    and (.steps | type=="array" and length>0)
    and all(.steps[];
      (.ac_cmd | type=="string" and length>0)
      and (.status | IN("pending","in_progress","done","blocked"))))
' "$PHASES" >/dev/null || { echo "loop-build: phases.json 스키마 위반 — 무인 시작 중단, 사람 호출" >&2; exit 65; }

# (2) 전체 시간 상한을 phase 수 비례로 재계산 — 재개로 이 블록이 재실행돼도 멱등하도록,
#     phase 당 원값(BUDGET_MIN_PHASE)을 따로 영속하고 늘 그 원값에서 곱한다(이미 곱한 BUDGET_MIN 에 재곱 금지).
NPHASE=$(jq '.phases | length' "$PHASES")
BUDGET_MIN_PHASE="${BUDGET_MIN_PHASE:-$BUDGET_MIN}"
BUDGET_MIN=$(( BUDGET_MIN_PHASE * NPHASE ))
printf 'BUDGET_MIN_PHASE=%q\nBUDGET_MIN=%q\n' "$BUDGET_MIN_PHASE" "$BUDGET_MIN" >> "$LOOP_DIR/params.env"
echo "loop-build 전체 시간 상한: ${BUDGET_MIN}분 (phase 당 ${BUDGET_MIN_PHASE} × ${NPHASE}개)"
```

**phase 진입 — maker 서브에이전트 1명 스핀:**

`Agent` 로 `loop-maker` 를 **하나** 띄운다 — 행동 규칙(배정 범위만·테스트 동반·자기 컴파일 검증·설계 결함 시 보고·커밋 금지·`ok`/`blocked` 종료)은 그 에이전트 정의가 담당하므로 프롬프트에 반복하지 않는다. **`loop-maker` 는 loop-run 과 공유하는 정의라 기본 종료 보고가 한 줄(`ok` 또는 `blocked: <사유>`)** 이다. 그보다 긴 것이 필요하면 이 프롬프트가 명시로 요구해야 온다(계약 상한 5줄). 프롬프트에는 phase 별 가변 정보만:

1. 그 phase 의 step 들(goal·layer·signature·ac_cmd)과 `design_ref`(구현할 설계 구역). **`ac_cmd` 가 곧 규칙 4의 자기 검증 명령이다** — maker 가 보고 전에 그것으로 컴파일을 스스로 확인한다.
2. **이전까지 완료한 phase(status=done)들이 무엇을 구현했는지 1~2줄 요약**(진행 맥락 — 코드는 워크트리에 있지만 요약을 주면 재파악이 빠르다).
3. 프로젝트 컨벤션 문서 경로(`$LOOP_CONVENTION_DOCS` 값 — 환경변수는 서브에이전트에 전달되지 않으니 값 자체를 텍스트로).
4. **phase 를 마칠 때 다음 phase maker 에게 넘길 1~2줄 요약을 달라는 요구.** 위 2번의 입력이 여기서 나온다. 계약 기본이 한 줄이라 이 요구가 없으면 요약이 오지 않는다.

maker 의 `agentId` 를 보관한다(사이클 이어가기용).

> 모델: loop-maker 는 frontmatter 기본값이 `opus` 다(v0.8.5) — 구현은 생산 작업이라 세션 모델보다 아래 급을 기본으로 두고, 검증은 세션 모델을 상속하는 checker 가 맡는 비대칭이 전제다. phase 난도 판단에 따라 이 `Agent` 호출에 `model` 파라미터를 지정해 상향·하향할 수 있다 — 호출 파라미터가 frontmatter 를 이긴다.
>
> effort: loop-maker 는 frontmatter 에 `effort: high` 를 고정한다(v0.9.6) — 모델 축의 강등을 사고 예산 축에서 한 등급 더 잇는 것이다. `medium` 까지 내리지 않는 이유는 maker 가 구현만 하는 게 아니라 checker finding 과 게이트 실패를 고치는데 그건 원인 추적에 가까워 탐색량이 결과를 바꾸기 때문이다. 모델과 달리 `Agent` 호출로 재정의할 수 없다(도구에 `effort` 파라미터가 없다). 계약은 `core/effort-ladder.md`.

**phase 스코프 상태 — history·stall·게이트 카운터를 phase 별로 분리:**

```bash
# 앞 phase 의 회차·정체 잔재가 다음 phase 판정을 오염하지 않게 phase 진입마다 재정의·영속한다.
# (findings 파일 분리와 같은 결. phase 1 이 PASS 로 floor 를 낮춘 stall.json 을 phase 2 가 물려받으면
#  첫 사이클부터 "floor 미갱신"이 쌓여 거짓 STALLED 가 뜬다 — stall 도 반드시 phase 별 파일로.)
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR" 2>/dev/null)" && [ -f "$LOOP_DIR/params.env" ] \
  || { echo "loop-build: params.env 없음 — Step 0 미실행/폐기됨" >&2; exit 65; }
set -a; . "$LOOP_DIR/params.env"; set +a
PHASE="<이 phase 의 name>"
# PHASE 자체도 영속 — 뒤 채점(scored-$PHASE.json)·done 갱신(jq --arg p "$PHASE")이 별도 Bash 호출이라,
# 영속 없이는 프레시 셸에서 PHASE 가 빈 문자열이 되어 scored 파일이 겹쳐 쓰이고 done 갱신이 조용히 no-op 된다.
printf 'PHASE=%q\nHIST=%q\nSTATE=%q\n' "$PHASE" "$LOOP_DIR/history-$PHASE.jsonl" "$LOOP_DIR/stall-$PHASE.json" >> "$LOOP_DIR/params.env"
rm -f "$LOOP_DIR/gate.fail"   # 게이트 실패 카운터도 phase 단위로 리셋
# checker 프롬프트에 넣을 값을 창에 출력(변수 대입만으론 오케스트레이터가 값을 모른다).
echo "phase 진입: $PHASE / checker 프롬프트 값: base=$LOOP_BASE_BRANCH / conv=[${LOOP_CONVENTION_DOCS:-없음}] / knowledge=[${LOOP_KNOWLEDGE_LAYER:-없음}] / base_rubric=$ENG/rubric.base.md / local_rubric=[${LOOP_RUBRIC_LOCAL:-없음}]"
```

loop-run Step 1~3 의 재유도 프리앰블이 `params.env` 를 source 하므로, 이 재정의 이후의 brake 회차(`$HIST` 줄 수)·정체 판정(`$STATE`)·scored 산출물(`$PHASE`)은 자동으로 이 phase 스코프가 된다.

**안쪽 루프 — loop-run Step 1~4 를 이 phase 컨텍스트에서:**

1. **게이트(loop-run Step 1)**: brake 선확인 → 컴파일(`$LOOP_BUILD_CMD`) → 테스트(`$LOOP_TEST_CMD`). 깨지면 checker 안 부르고 **maker 재진입**(아래 5번)으로. loop-run Step 1 을 그대로 상속하므로 **실패 출력은 `gate_parse.py` 로 `$LOOP_DIR/gate-queue.jsonl` 작업 큐가 되고, 매 게이트 실행 시작에 그 파일을 비운다**(앞 회차·앞 phase 의 잔여 항목을 maker 가 쫓지 않게).
   - **게이트를 돌리기 전에 loop-run Step 6-1 의 트리 변경 확인을 함께 상속한다.** `SendMessage` 로 이어간 maker 도 보고가 거짓일 수 있다 — 고쳤다고 하고 아무것도 안 바꿨으면 게이트가 같은 결과를, checker 가 같은 finding 을 내고 회차만 탄다. 변경이 없으면 회차가 아니라 정체 신호이므로 게이트를 돌리지 않고 사람을 부른다. `stall.sh` 도 결국 잡지만 그건 floor 가 몇 회차 제자리인 뒤다.
2. **checker 1회(loop-run Step 2)**: `Agent` 로 `loop-checker` 를 **매 사이클 새로** 띄운다. 스핀 전에 findings 출력 경로를 **phase 별** 결정적 위치로 잡고 비운다 — `F="$LOOP_DIR/checker-findings-{phase}.json"; : > "$F"`. **phase 별 파일이 핵심이다**: 단일 파일을 phase 가 공유하면 앞 phase 의 깨끗-통과 잔여(`{"findings":[]}`)가 남아, 다음 phase 에서 오케스트레이터가 비우기를 빠뜨리고 checker 가 안 쓰면 그 옛 빈 배열이 채점돼 미점검 phase 가 done 으로 둔갑한다. phase 분리(`history-{phase}.jsonl` 와 같은 결)면 다음 phase 의 파일은 없는 상태로 시작해 `[ -s "$F" ]`+score.sh 가 fail-loud 로 멈춘다. checker 는 결과 `{base, findings:[...]}` 를 그 파일에 쓰고, 오케스트레이터는 그 파일을 **열지 않고 경로째** 채점 셸에 넘긴다(백그라운드 세션은 서브에이전트 최종 메시지가 인라인으로 안 와 파일이 정본 회수 경로, loop-run Step 2 개정판). 프롬프트에 원 작업 정의 + 설계 문서 경로 + **이 phase 의 `design_ref` 와 step 목록**(이 phase 가 그 설계대로 구현됐는지 정합을 phase 단위로 점검하게 한다) + 베이스 + 점검 기준 문서(`$LOOP_CONVENTION_DOCS`·`$LOOP_KNOWLEDGE_LAYER`·BASE/LOCAL rubric 경로 — 환경변수는 서브에이전트에 전달되지 않으니 phase 진입 블록이 echo 한 값 자체를 프롬프트 텍스트로, 비었으면 "없음" 명시) + 그 findings 출력 경로. **maker 의 변명·구현 설명을 절대 넣지 않는다**(불변 1). checker 는 diff·컨벤션·ANTIPATTERNS 를 독립적으로 읽고, intent 차원으로 **이 phase 코드 ↔ `design_ref` 정합**을 본다 — 코드가 설계를 벗어나면 finding(채점을 거쳐 PASS 를 막으므로, 이게 곧 "이 phase 를 설계대로 구현했나"라는 phase 통과 조건이다).

> 모델: checker 는 frontmatter 에 모델을 고정하지 않는다(v0.8.4) — 기본은 호출한 세션(오케스트레이터=maker)의 모델을 상속한다. 특정 모델로 돌리려면 이 `Agent` 호출에 `model` 파라미터를 지정한다.
>
> effort: checker 는 frontmatter 에 `effort: xhigh` 를 **고정한다**(v0.9.6) — 모델과 달리 세션을 상속하지 않는다. 세션 등급을 내려도 판정부는 따라 내려가면 안 되기 때문이다. `Agent` 호출로는 재정의할 수 없다. 계약은 `core/effort-ladder.md`.
3. **채점(loop-run Step 3)**: checker 가 쓴 findings 파일(`$F` = `$LOOP_DIR/checker-findings-{phase}.json`)을 `score.sh → decide.sh → stall.sh` 파이프에 흘려 verdict·정체를 낸다. 파일이 비었거나 없으면 checker 실패다 — `[ -s "$F" ] || { echo "checker 미기입" >&2; exit 65; }` 로 멈추고 사람 호출(조용히 PASS 금지). severity 는 셸이 매긴다. 이 phase 의 history 는 `$HIST`(= `$LOOP_DIR/history-{phase}.jsonl`)에, 정체 상태는 `$STATE`(= `$LOOP_DIR/stall-{phase}.json`)에 — 둘 다 phase 진입 때 재정의된 값이다. 채점 결과는 maker 인계용으로 파일에도 남긴다: `printf '%s' "$SCORED" > "$LOOP_DIR/scored-$PHASE.json"`. 오케스트레이터 창에는 counts 와 `등급·종류·위치` 한 줄 목록까지만 남기고 evidence 전문은 읽지 않는다.
4. **분기(loop-run Step 4, 우선순위 순)**:
   - `AWAIT_USER`(비가역/force_await) → **멈춤, 사람 호출.**
   - brake 도달(phase iter + 게이트 실패 ≥ MAX_ITER 또는 전체 경과 ≥ BUDGET_MIN — loop-run Step 1 과 동일 합산) → **멈춤, 사람 호출.**
   - `STALLED`/`REGRESS_ESCALATE` → **멈춤, 사람 호출.**
   - `PASS` → 이 phase `status=done`, **maker 종료 통지**, **다음 phase 로**. maker 는 백그라운드 팀메이트라 통지 없이는 대기 상태로 남는다 — `SendMessage({to: <agentId>})` 로 "phase 완료 — 종료. 새 작업을 시작하지 말고 한 줄 확인으로 턴을 끝내라" 를 보내고 응답을 기다리지 않는다. 이후 이 maker 에는 재진입하지 않으며, 다음 phase 는 새 maker 를 띄운다.
   - `RETRY`/`RETRY_SOFT` → 5번(maker 재진입).
5. **maker 재진입 — `SendMessage` 로 같은 maker 를 이어감(불변 6):** `SendMessage({to: <agentId>})` 에는 **counts 요약 한 줄 + scored 파일 경로(`$LOOP_DIR/scored-{phase}.json`)만** 담아 "이 파일을 읽고 CRITICAL→MAJOR 순으로 고쳐라. 고친 코드에 대응 테스트도" 라고 이어 지시한다. finding 전문(evidence 산문)을 메시지에 붙여넣지 않는다 — SendMessage 도구 결과가 보낸 텍스트를 그대로 에코해 오케스트레이터 창에 같은 내용이 두 벌씩 쌓이고, maker 는 어차피 파일을 직접 읽는 쪽이 정확하다. **새 Task 를 띄우지 않는다** — 그래야 그 phase 의 수정 맥락이 유지된다. 고쳐지면 1번(게이트)부터 이 사이클을 다시 연다.
   - 게이트가 깨진 경우도 같은 maker 에게 `SendMessage` 로 이어 지시하는데, **넘기는 것은 게이트 큐 경로(`$LOOP_DIR/gate-queue.jsonl`) 하나** 다. 항목 본문이나 빌드 출력을 메시지에 붙여넣지 않는다 — 린트 게이트 하나가 수천 항목을 낼 수 있고, 그때 오케스트레이터 창이 먼저 죽는다. 큐가 비어 있지 않으면 그것이 scored 파일보다 우선한다(게이트가 깨진 회차는 checker 가 아예 안 돌아 scored 가 앞 회차 값이다).
   - 못 고치거나 고치면 안 되는 finding(force_await·비가역)은 maker 에게 넘기지 말고 `AWAIT_USER`.

> **설계 drift 는 무인이 판단하지 않는다(사람 게이트).** 실제 구현이 최초 설계(`design_ref`)와 달라져야 한다고 maker 가 보고하거나, checker 가 "코드가 설계와 다른데 코드 쪽이 맞아 보인다(설계 결함 의심)"를 잡으면 — maker 가 코드를 설계에 맞추는 걸로 끝내지 않고 **`AWAIT_USER` 로 멈춰 사람에게 설계 재결정을 맡긴다**. loop-build 는 "설계대로 구현"이 목표이지 "설계를 고쳐 구현"이 아니다. 설계 자체를 바꾸는 결정은 사람이 하고, 승인되면 프로젝트의 설계 문서 스킬(예: c8c-api `/design --decision`)로 설계 문서를 갱신한 뒤 그 phase 를 재개한다.

phase 가 PASS 하면 그 phase 를 `status=done` 으로 갱신하고 다음 phase 로. 갱신은 Read/Edit 가 아니라 Bash 의 jq 로 한다 — Read 는 파일 전문을 오케스트레이터 창에 다시 주입한다:

```bash
# 프리앰블로 PHASE·PHASES 를 params.env 에서 복원(프레시 셸에서 빈 PHASE 면 jq 가 0건 매칭 no-op 된다).
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
LOOP_DIR="$(cat "$PROJECT_ROOT/.loop/run/.active-$BR")"; set -a; . "$LOOP_DIR/params.env"; set +a
jq --arg p "$PHASE" '(.phases[] | select(.name==$p)).status = "done"' "$PHASES" > "$PHASES.tmp" && mv "$PHASES.tmp" "$PHASES"
# 갱신 검증 — jq 는 매칭 0건이어도 exit 0 으로 원본을 그대로 내므로, 실제로 done 이 됐는지 확인해야 fail-loud 다.
jq -e --arg p "$PHASE" '[.phases[] | select(.name==$p) | .status] == ["done"]' "$PHASES" >/dev/null \
  || { echo "loop-build: phase '$PHASE' done 갱신 실패(매칭 0건/중복 이름) — 멈추고 사람 호출" >&2; exit 65; }
```

남은 phase 가 없으면 Step 3.

> **오케스트레이터는 코드를 쓰지 않는다.** 메인 세션은 순환 제어(phase 순회·게이트 실행·checker 스핀·채점·분기·SendMessage)만 한다. 실제 편집은 전부 maker 서브에이전트 안에서 일어나 오케스트레이터 컨텍스트에 안 쌓인다. 이게 여러 phase 롱런을 버티게 하는 핵심이다.

> **오케스트레이터는 내용을 보유하지 않는다(컨텍스트 위생).** 롱런 완주는 오케스트레이터 창이 얼마나 가볍게 유지되느냐에 달려 있다. 규칙 다섯: (1) checker findings·scored JSON 의 evidence 전문을 cat/Read 하지 않는다 — 채점은 경로째 셸에 넘기고, 창에는 counts 와 등급·종류·위치 한 줄 목록만 남긴다. (2) maker 완료 보고는 phase 요약 1~2줄로 받는다 — 공유 계약의 기본은 `ok` 한 줄이고, 이 요약은 스핀 프롬프트가 명시로 요구해서 오는 것이다(상한 5줄). (3) SendMessage 는 짧게 — 도구 결과가 보낸 전문을 에코한다. (4) phases.json·설계 문서를 다시 Read 하지 않는다 — 상태 갱신·조회는 jq 로. (5) git 확인은 `--stat`·`--name-only` 수준까지만.

### Step 3. 전체 완료 처리 (커밋하지 않는다)

모든 phase 가 `done` 이면 사람에게 보고: 완료 phase 목록, phase 별 사이클 수, 남은 MINOR(기록만), 변경 요약.

- **커밋·push 하지 않는다.** 변경은 워크트리에 누적된 채 남긴다. 논리 단위 커밋·PR 은 프로젝트의 커밋·PR 마감 워크플로우(예: c8c-api `/finalize`·`/ship`·`/pr`)에서 사람이 마감한다. 이는 loop-run 의 "PR 인계 보류"와 정합적이다.
- 롱런으로 uncommitted 가 커지면 wrapup 에서 phase 경계를 따라 쪼개 커밋하도록 제안한다.
- 종료 후 `/loop-lessons` 로 이 루프의 `history-*.jsonl` 에서 잡힌 실수를 ANTIPATTERNS 후보로 올릴지 제안한다(선순환). 강제 아님. history 가 phase 별 여러 파일이므로 `lessons.sh` 를 파일마다 반복 호출해 mistake 목록을 합쳐 synthesizer 에 넘긴다(lessons.sh 는 단일 `--history` 입력).
- **종료 후 설계 문서 정합 반영 제안.** phase 도중 큰 drift 는 `AWAIT_USER` 로 사람이 이미 `/design` 을 갱신했지만, 설계 의도 안에서 실제 구현이 문서와 미세하게 달라진 부분은 종료 후 프로젝트의 문서 정합·갱신 스킬(예: c8c-api `/sync-docs`·`/design --behavior`)로 반영하도록 제안한다. 각 phase 의 `design_ref` 가 어느 구역을 대조해야 하는지 짚어줘 사람이 코드↔문서를 처음부터 전수 대조하지 않게 한다. 강제 아님, 반영 주체는 사람.

### Step 3-1. 종료 정리 (loop-run Step 5-1 과 동일)

`$LOOP_DIR`(phases.json·history-*.jsonl·stall)은 루프 한정 휘발성이다. **lesson 종합 다음에만** 폐기한다(종합 전 삭제 시 선순환 입력 소멸). 사람 멈춤(AWAIT_USER/STALLED/brake)으로 재개 여지가 있으면 바로 폐기하지 않는다 — `phases.json`(done/pending)·stall 이 남아야 이어서 돌릴 수 있다.

```bash
# loop-run Step 5-1 과 동일하게 LOOP_DIR 를 포인터에서 재유도한다 — 별도 Bash 호출이라 재유도 없이
# 돌면 빈 LOOP_DIR 로 rm 이 아무것도 못 지우면서 종료코드 0 을 낸다. 그러면 phases.json 이 전 phase
# done 인 채로 남아, 같은 티켓의 다음 loop-build 가 "미완 phase 없음" 으로 읽고 아무것도 안 한다.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
BR="$(git rev-parse --abbrev-ref HEAD | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-')"
PTR="$PROJECT_ROOT/.loop/run/.active-$BR"
LOOP_DIR="$(cat "$PTR" 2>/dev/null)"
# PASS(전 phase done) + lesson 종합(또는 생략 결정) 후에만. 지울 것이 없으면 그렇다고 말하고 끝낸다.
[ -n "$LOOP_DIR" ] || { echo "loop-build: 포인터 없음 — 지울 상태가 없다(이미 폐기됐거나 Step 0 미실행)" >&2; exit 0; }
rm -rf "$LOOP_DIR"
rm -f "$PTR"         # 이 브랜치의 재유도 포인터도 함께(loop-run Step 5-1 과 동일).
echo "loop-build: 런타임 상태 폐기 — $LOOP_DIR"
```

## 재개 (중단된 롱런 이어가기)

사람 멈춤으로 중단됐다 재개할 때는 `phases.json` 을 jq 로 조회해(`jq -r '.phases[] | select(.status != "done") | .name' "$PHASES" | head -1` — 전문 Read 금지) `status=done` phase 를 건너뛰고 첫 `pending`/`blocked` phase 부터 Step 2 를 다시 연다. done phase 는 다시 개발하지 않는다(멱등). 재개 시 loop-run Step 0 의 초기화(history 비우기·stall 삭제·epoch 갱신)는 다시 타지 않는다 — `.loop/run/.active`·`params.env`·phase 별 history·stall 이 남아 있으면 그대로 쓴다.

## 백그라운드 세션 실행

사람이 빠져도 계속 돌게 하려면 이 세션을 백그라운드 잡으로 띄운다. 분해 승인(Step 1)을 받은 그 세션에서 `/loop-build` 를 걸고 자리를 비운다. 페이즈 경계마다 `PushNotification` 으로 "phase X done, 다음 진행" 을 알리게 배선하면 자리를 비운 동안에도 진행이 굴러가고, AWAIT_USER/brake 에서만 사람이 불려온다.

## Non-Goals

- **단일 변경 수렴** — 그건 `/loop-run`. 이 스킬은 여러 phase 를 순차 빌드아웃한다.
- **1회 점검·보고** — `/loop-review`.
- **lesson → ANTIPATTERNS 반영** — 종료 후 `/loop-lessons`(사람 승인 게이트).
- **커밋·push·PR** — 프로젝트의 커밋·PR 마감 워크플로우(예: c8c-api `/finalize`·`/ship`·`/pr`) 소관. 이 스킬은 워크트리 누적까지만.
- **판정부 재구현** — checker·채점 셸·rubric 은 loop-run 과 같은 번들을 재사용한다. 여기서 새로 만들지 않는다.
- **severity 를 LLM 이 매기는 것** — 결정론 셸이 매긴다.
