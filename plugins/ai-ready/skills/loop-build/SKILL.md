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
| 오케스트레이터 | 메인 세션(= maker 겸임) | 메인 세션(= 순수 오케스트레이터, 코딩 안 함) |
| maker | 메인 세션 자신 | **phase 마다 새 서브에이전트**(SendMessage 로 사이클 이어감) |
| checker | 매 사이클 새 `loop-checker` 서브에이전트 | **동일** (재사용) |
| 채점 | `_loop-engine` 셸(score/decide/stall) + BASE/LOCAL rubric | **동일** (재사용) |
| 범위 | `origin/main...HEAD + uncommitted` | phase 별 diff, 누적은 워크트리 |

즉 **각 phase 의 안쪽 루프는 loop-run 의 Step 1~6 과 같다**. 다른 건 두 가지뿐이다: (1) maker 가 메인 세션이 아니라 서브에이전트, (2) 바깥에 phase 순회가 감싼다.

## 🔌 plugin 구조 (loop-run 과 공유)

- `ai-ready` plugin 의 일부. 판정 엔진은 loop-run 과 **같은 번들** 을 쓴다: `$CLAUDE_PLUGIN_ROOT/_loop-engine`(채점 셸 + `lib.sh` 의 `loop_param` + `detect_build.py`), `$CLAUDE_PLUGIN_ROOT/_loop-engine/rubric.base.md`(BASE rubric), `$CLAUDE_PLUGIN_ROOT/agents/loop-checker.md`.
- 프로젝트 사실(빌드·테스트·린트·티켓·베이스 브랜치·컨벤션 docs·지식층)은 loop-run 과 똑같이 `detect_build.py` 가 런타임 감지. 별도 어댑터 파일 없음.
- 프로젝트 LOCAL rubric(`.loop/rubric.md`)·지식층(`docs/ANTIPATTERNS.md`)도 loop-run 과 공유.
- 런타임 상태는 `$CLAUDE_PROJECT_DIR/.loop/run/{ticket}/`(loop-run 과 같은 자리, 티켓 슬러그로 분리). phase 진행 상태(`phases.json`)를 여기에 추가로 둔다 — 루프 한정 휘발성, `.gitignore` 로 `.loop/run/` 제외.

## 핵심 불변 (loop-run 5개 상속 + 2개 추가)

loop-run 의 핵심 불변 5개를 **그대로 상속** 한다: (1) maker/checker 분리, (2) severity 는 셸이 매김, (3) 게이트가 checker 보다·brake 가 평가보다 먼저, (4) 종료는 점수 합산이 아니라 `BLOCKER 0 AND CRITICAL 0` severity 게이트, (5) 비가역 영역(운영 DB DML/DDL·돈·인가·대량발송·삭제)은 `AWAIT_USER`. 상세는 loop-run SKILL.md 의 "핵심 불변" 절.

멀티-phase 라서 두 개를 **추가** 한다:

6. **phase 격리 + phase 내 연속성.** maker 는 phase 마다 **새 서브에이전트** 로 띄운다 — 이전 phase 의 편집 노이즈가 오케스트레이터에도 다음 maker 에도 안 쌓인다(롱런 컨텍스트 보존). 단 **한 phase 안의 RETRY 사이클은 `SendMessage` 로 같은 maker 를 이어간다** — 매 사이클 새 Task 를 띄우면 그 phase 의 수정 맥락("이 파일을 왜 이렇게 고쳤는지")을 잃어 같은 파일 반복 수정에서 역행한다. phase = maker 1명, 사이클 = 그 maker 에게 finding 을 이어 보냄.
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
# (loop-run Step 0 을 먼저 실행: PROJECT_ROOT/ENG/LOOP_DIR/LOOP_BASE_BRANCH/MAX_ITER/BUDGET_MIN 확보)
PHASES="$LOOP_DIR/phases.json"   # 분해 결과 + phase 별 status 를 여기 영속(휘발성)
```

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
# (1) phases.json fail-loud 검증 — 무인 시작·재개 직전. score.sh 의 변질 입력 exit 65 거부와 같은 결.
#     .phases 비배열/빈배열, phase 의 name·steps 누락, step 의 ac_cmd 누락(AC 없으면 step 이 아님),
#     status 가 pending/in_progress/done/blocked 밖 — 하나라도 걸리면 멈추고 사람 호출.
jq -e '
  (.phases | type=="array" and length>0) and all(.phases[];
    (.name | type=="string" and length>0)
    and (.status | IN("pending","in_progress","done","blocked"))
    and (.steps | type=="array" and length>0)
    and all(.steps[];
      (.ac_cmd | type=="string" and length>0)
      and (.status | IN("pending","in_progress","done","blocked"))))
' "$PHASES" >/dev/null || { echo "loop-build: phases.json 스키마 위반 — 무인 시작 중단, 사람 호출" >&2; exit 65; }

# (2) 전체 시간 상한을 phase 수 비례로 재계산.
NPHASE=$(jq '.phases | length' "$PHASES")
BUDGET_MIN=$(( BUDGET_MIN * NPHASE ))   # phase 당 120분 × phase 수 = 전체 상한. 뒤 phase 가 시간에 안 잘리게.
echo "loop-build 전체 시간 상한: ${BUDGET_MIN}분 (phase 당 120 × ${NPHASE}개)"
```

**phase 진입 — maker 서브에이전트 1명 스핀:**

`Agent`(general-purpose) 로 maker 를 **하나** 띄운다. 프롬프트에 (1) 그 phase 의 step 들(goal·layer·signature·ac_cmd)과 `design_ref`(구현할 설계 구역), (2) **이전까지 완료한 phase(status=done)들이 무엇을 구현했는지 1~2줄 요약**(진행 맥락 — 코드는 워크트리에 있지만 요약을 주면 재파악이 빠르다), (3) 프로젝트 컨벤션 문서 경로(`$LOOP_CONVENTION_DOCS`)를 준다. "이 phase 의 step 만, `design_ref` 의 설계대로 구현하라. 다른 phase 에 의존하지 마라. 코드를 고치면 대응 테스트도 함께 작성하라. **설계대로 구현이 불가능하거나 설계에 결함이 보이면 임의로 바꾸지 말고 그 사실을 보고하라**(→ 사람 판단)." maker 의 `agentId` 를 보관한다(사이클 이어가기용).

**안쪽 루프 — loop-run Step 1~4 를 이 phase 컨텍스트에서:**

1. **게이트(loop-run Step 1)**: brake 선확인 → 컴파일(`$LOOP_BUILD_CMD`) → 테스트(`$LOOP_TEST_CMD`). 깨지면 checker 안 부르고 **maker 재진입**(아래 5번)으로.
2. **checker 1회(loop-run Step 2)**: `Agent` 로 `loop-checker` 를 **매 사이클 새로** 띄운다. 스핀 전에 findings 출력 경로를 **phase 별** 결정적 위치로 잡고 비운다 — `F="$LOOP_DIR/checker-findings-{phase}.json"; : > "$F"`. **phase 별 파일이 핵심이다**: 단일 파일을 phase 가 공유하면 앞 phase 의 깨끗-통과 잔여(`{"findings":[]}`)가 남아, 다음 phase 에서 오케스트레이터가 비우기를 빠뜨리고 checker 가 안 쓰면 그 옛 빈 배열이 채점돼 미점검 phase 가 done 으로 둔갑한다. phase 분리(`history-{phase}.jsonl` 와 같은 결)면 다음 phase 의 파일은 없는 상태로 시작해 `[ -s "$F" ]`+score.sh 가 fail-loud 로 멈춘다. checker 는 결과 `{base, findings:[...]}` 를 그 파일에 쓰고, 오케스트레이터는 그 파일을 읽어 채점한다(백그라운드 세션은 서브에이전트 최종 메시지가 인라인으로 안 와 파일이 정본 회수 경로, loop-run Step 2 개정판). 프롬프트에 원 작업 정의 + 설계 문서 경로 + **이 phase 의 `design_ref` 와 step 목록**(이 phase 가 그 설계대로 구현됐는지 정합을 phase 단위로 점검하게 한다) + 베이스 + 그 findings 출력 경로. **maker 의 변명·구현 설명을 절대 넣지 않는다**(불변 1). checker 는 diff·컨벤션·ANTIPATTERNS 를 독립적으로 읽고, intent 차원으로 **이 phase 코드 ↔ `design_ref` 정합**을 본다 — 코드가 설계를 벗어나면 finding(채점을 거쳐 PASS 를 막으므로, 이게 곧 "이 phase 를 설계대로 구현했나"라는 phase 통과 조건이다).
3. **채점(loop-run Step 3)**: checker 가 쓴 findings 파일(`$F` = `$LOOP_DIR/checker-findings-{phase}.json`)을 `score.sh → decide.sh → stall.sh` 파이프에 흘려 verdict·정체를 낸다. 파일이 비었거나 없으면 checker 실패다 — `[ -s "$F" ] || { echo "checker 미기입" >&2; exit 65; }` 로 멈추고 사람 호출(조용히 PASS 금지). severity 는 셸이 매긴다. 이 phase 의 history 는 `$LOOP_DIR/history-{phase}.jsonl` 에 append(phase 별 정체 감지 분리).
4. **분기(loop-run Step 4, 우선순위 순)**:
   - `AWAIT_USER`(비가역/force_await) → **멈춤, 사람 호출.**
   - brake 도달(phase iter ≥ MAX_ITER 또는 전체 경과 ≥ BUDGET_MIN) → **멈춤, 사람 호출.**
   - `STALLED`/`REGRESS_ESCALATE` → **멈춤, 사람 호출.**
   - `PASS` → 이 phase `status=done`, maker 서브에이전트 종료, **다음 phase 로**.
   - `RETRY`/`RETRY_SOFT` → 5번(maker 재진입).
5. **maker 재진입 — `SendMessage` 로 같은 maker 를 이어감(불변 6):** `SendMessage({to: <agentId>})` 로 Step 3 의 scored finding(등급 내림차순, CRITICAL→MAJOR)을 넘겨 "이걸 고쳐라. 고친 코드에 대응 테스트도" 라고 이어 지시한다. **새 Task 를 띄우지 않는다** — 그래야 그 phase 의 수정 맥락이 유지된다. 고쳐지면 1번(게이트)부터 이 사이클을 다시 연다.
   - 게이트가 깨진 경우도 같은 maker 에게 `SendMessage` 로 "빌드/테스트가 깨졌다. 고쳐라"를 넘긴다.
   - 못 고치거나 고치면 안 되는 finding(force_await·비가역)은 maker 에게 넘기지 말고 `AWAIT_USER`.

> **설계 drift 는 무인이 판단하지 않는다(사람 게이트).** 실제 구현이 최초 설계(`design_ref`)와 달라져야 한다고 maker 가 보고하거나, checker 가 "코드가 설계와 다른데 코드 쪽이 맞아 보인다(설계 결함 의심)"를 잡으면 — maker 가 코드를 설계에 맞추는 걸로 끝내지 않고 **`AWAIT_USER` 로 멈춰 사람에게 설계 재결정을 맡긴다**. loop-build 는 "설계대로 구현"이 목표이지 "설계를 고쳐 구현"이 아니다. 설계 자체를 바꾸는 결정은 사람이 하고, 승인되면 프로젝트의 설계 문서 스킬(예: c8c-api `/design --decision`)로 설계 문서를 갱신한 뒤 그 phase 를 재개한다.

phase 가 PASS 하면 `phases.json` 의 그 phase `status=done` 으로 갱신하고 다음 phase 로. 남은 phase 가 없으면 Step 3.

> **오케스트레이터는 코드를 쓰지 않는다.** 메인 세션은 순환 제어(phase 순회·게이트 실행·checker 스핀·채점·분기·SendMessage)만 한다. 실제 편집은 전부 maker 서브에이전트 안에서 일어나 오케스트레이터 컨텍스트에 안 쌓인다. 이게 여러 phase 롱런을 버티게 하는 핵심이다.

### Step 3. 전체 완료 처리 (커밋하지 않는다)

모든 phase 가 `done` 이면 사람에게 보고: 완료 phase 목록, phase 별 사이클 수, 남은 MINOR(기록만), 변경 요약.

- **커밋·push 하지 않는다.** 변경은 워크트리에 누적된 채 남긴다. 논리 단위 커밋·PR 은 프로젝트의 커밋·PR 마감 워크플로우(예: c8c-api `/feature-wrapup`·`/ship`·`/pr`)에서 사람이 마감한다. 이는 loop-run 의 "PR 인계 보류"와 정합적이다.
- 롱런으로 uncommitted 가 커지면 wrapup 에서 phase 경계를 따라 쪼개 커밋하도록 제안한다.
- 종료 후 `/loop-lessons` 로 이 루프의 `history-*.jsonl` 에서 잡힌 실수를 ANTIPATTERNS 후보로 올릴지 제안한다(선순환). 강제 아님.
- **종료 후 설계 문서 정합 반영 제안.** phase 도중 큰 drift 는 `AWAIT_USER` 로 사람이 이미 `/design` 을 갱신했지만, 설계 의도 안에서 실제 구현이 문서와 미세하게 달라진 부분은 종료 후 프로젝트의 문서 정합·갱신 스킬(예: c8c-api `/sync-docs`·`/design --behavior`)로 반영하도록 제안한다. 각 phase 의 `design_ref` 가 어느 구역을 대조해야 하는지 짚어줘 사람이 코드↔문서를 처음부터 전수 대조하지 않게 한다. 강제 아님, 반영 주체는 사람.

### Step 3-1. 종료 정리 (loop-run Step 5-1 과 동일)

`$LOOP_DIR`(phases.json·history-*.jsonl·stall)은 루프 한정 휘발성이다. **lesson 종합 다음에만** 폐기한다(종합 전 삭제 시 선순환 입력 소멸). 사람 멈춤(AWAIT_USER/STALLED/brake)으로 재개 여지가 있으면 바로 폐기하지 않는다 — `phases.json`(done/pending)·stall 이 남아야 이어서 돌릴 수 있다.

```bash
rm -rf "$LOOP_DIR"   # PASS(전 phase done) + lesson 종합(또는 생략 결정) 후에만.
```

## 재개 (중단된 롱런 이어가기)

사람 멈춤으로 중단됐다 재개할 때는 `phases.json` 을 읽어 `status=done` phase 를 건너뛰고 첫 `pending`/`blocked` phase 부터 Step 2 를 다시 연다. done phase 는 다시 개발하지 않는다(멱등).

## 백그라운드 세션 실행

사람이 빠져도 계속 돌게 하려면 이 세션을 백그라운드 잡으로 띄운다. 분해 승인(Step 1)을 받은 그 세션에서 `/loop-build` 를 걸고 자리를 비운다. 페이즈 경계마다 `PushNotification` 으로 "phase X done, 다음 진행" 을 알리게 배선하면 자리를 비운 동안에도 진행이 굴러가고, AWAIT_USER/brake 에서만 사람이 불려온다.

## Non-Goals

- **단일 변경 수렴** — 그건 `/loop-run`. 이 스킬은 여러 phase 를 순차 빌드아웃한다.
- **1회 점검·보고** — `/loop-review`.
- **lesson → ANTIPATTERNS 반영** — 종료 후 `/loop-lessons`(사람 승인 게이트).
- **커밋·push·PR** — 프로젝트의 커밋·PR 마감 워크플로우(예: c8c-api `/feature-wrapup`·`/ship`·`/pr`) 소관. 이 스킬은 워크트리 누적까지만.
- **판정부 재구현** — checker·채점 셸·rubric 은 loop-run 과 같은 번들을 재사용한다. 여기서 새로 만들지 않는다.
- **severity 를 LLM 이 매기는 것** — 결정론 셸이 매긴다.
