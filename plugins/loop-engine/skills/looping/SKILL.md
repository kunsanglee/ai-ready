---
name: looping
description: 무인 검증 loop 우산 스킬. 첫 인자로 세 서브커맨드를 분기한다 — `run`(사람 핸드오프 자동 루프: maker→checker→결정론 채점→정체·brake 를 루브릭 통과·예산 소진·사람 대기까지 반복, 코드를 고치며 돈다), `review`(현재 브랜치 변경을 1회 적대적 점검해 등급 내림차순 보고서, 코드 수정 없음), `lessons`(루프 종료 후 잡힌 실수를 사람 승인 게이트로 docs/ANTIPATTERNS.md 에 승격). 셋 다 같은 판정부(loop-checker 에이전트 + .claude/skills/_loop-engine 채점 셸 + docs/loop/rubric.md)를 써서 같은 코드엔 항상 같은 severity. Use when the user says "/looping", "/looping run|review|lessons", "루프 돌려", "핸드오프 루프", "loop 리뷰", "검수 한 번", "lesson 종합", "교훈 반영", "이 작업 루프로 수렴시켜", or runs / reviews / harvests-lessons-from the verification loop. run 은 점검·수정 반복 → 종료 → 사람 검토 → lessons 로 이어지는 주 흐름이고, review·lessons 는 단독으로도 부를 수 있다.
disable-model-invocation: true
---

# looping — 무인 검증 loop 우산

`run` / `review` / `lessons` 세 동작을 **첫 인자로 분기** 하는 우산 스킬이다. 호출은 `/looping <서브커맨드> [옵션]`. 셋은 같은 판정부를 공유하는 한 가족이고, 다른 건 사람 개입 양식뿐이다.

## 공통 코어 (세 동작이 공유)

- **`loop-checker`** 에이전트: 변경 코드를 5차원(compatibility·security·runtime·intent·convention)으로 적대적 점검해 finding 을 `(종류·차원·가중플래그·위치·근거·force_await)` 로 태깅만 한다. severity 는 안 매긴다.
- **`.claude/skills/_loop-engine/`** 채점 셸: `docs/loop/rubric.md` 표를 보고 결정론으로 severity·종료 verdict·정체를 판정한다. score → decide → stall.
- 그래서 **같은 코드엔 항상 같은 등급**(judge 일관성). 셋 다 이 코어를 호출 — 점검 로직 복제 없음.

## 서브커맨드 분기

첫 인자를 보고 해당 동작의 **절차 파일을 Read 해서 그대로 따른다**. 각 파일은 frontmatter 없는 순수 절차다.

| 인자 | 동작 | 절차 파일 | 한 줄 |
|---|---|---|---|
| `run` | 사람 핸드오프 자동 루프 | [`run.md`](run.md) | 맡기고 빠지면 루브릭 통과까지 고치며 돈다 (human-on-the-loop) |
| `review` | 1회 점검 보고서 | [`review.md`](review.md) | 코드 안 고치고 한 번 점검 → 등급순 보고서 (human-in-the-loop) |
| `lessons` | lesson 승인 게이트 | [`lessons.md`](lessons.md) | 끝난 루프의 실수를 사람 승인으로 ANTIPATTERNS 승격 |
| (없음/기타) | 사용법 안내 | — | 아래 "인자 없이 호출" |

```bash
SUB="$1"   # 첫 인자 (예: /looping run 5 → SUB=run, 둘째 토큰 5)
case "$SUB" in
  run)     : ;;  # → run.md 를 Read. 둘째 토큰이 회차면 run.md 셋업의 MAX_ITER 로 넘긴다(예: /looping run 5 → MAX_ITER=5)
  review)  : ;;  # → review.md 를 Read. 둘째 토큰이 --html 이면 HTML 모드
  lessons) : ;;  # → lessons.md 를 Read. --history <경로> 옵션 가능
  *)       : ;;  # → 아래 사용법 출력
esac
```

분기 규칙:
- `run` → `.claude/skills/looping/run.md` 를 Read 하고 그 Step 0~ 절차를 수행한다. 사용자가 회차를 같이 주면(`/looping run 5`) 둘째 토큰을 run.md 셋업의 `MAX_ITER` 로 넣는다(천장 10 클램프는 run.md 가 한다).
- `review` → `review.md` 를 Read 하고 그 절차를 수행한다. `--html` 이면 HTML 보고서 모드.
- `lessons` → `lessons.md` 를 Read 하고 그 절차를 수행한다. `--history <경로>` 로 history 명시 가능.
- 그 외/빈 인자 → 아래 사용법을 출력하고 멈춘다.

## 주 흐름과 단독 사용

- **주 흐름(run)**: `run` 은 내부에서 점검(checker)과 수정을 반복하다 종료하고, 종료하면 사람이 결과를 검토한 뒤 `lessons` 로 교훈을 수확하는 한 흐름이다. run 의 종료 처리가 이 검토·lessons 연결을 안내한다. run 한 번이 "점검 반복 → 종료 → 사람 검토 → lessons" 를 이어준다.
- **단독 사용**: `review` 는 run 을 안 돌리고 지금 코드를 한 번만 점검받고 싶을 때(사람이 직접 고침). `lessons` 는 루프가 끝난 뒤, 또는 과거 history 로 교훈만 정리할 때. 둘 다 주 흐름의 단계이면서 따로 부를 수 있다.

## 인자 없이 호출 (`/looping`)

서브커맨드 없이 부르면 아래를 출력하고 멈춘다(어느 동작도 자동 실행하지 않는다):

```
looping — 무인 검증 loop 우산. 서브커맨드를 주세요.

  /looping run [회차]      사람 핸드오프 자동 루프. 맡기고 빠지면 루브릭 통과까지 고치며 돈다.
                           회차 생략 시 rubric 기본(10), 명시 시 그 값(천장 10).
  /looping review [--html] 현재 변경을 1회 점검 → 등급순 보고서. 코드 안 고침.
  /looping lessons         끝난 루프의 실수를 사람 승인 게이트로 ANTIPATTERNS 승격.

주 흐름: run 이 점검·수정 반복 → 종료 → 사람 검토 → lessons 로 이어집니다.
review·lessons 는 단독으로도 부를 수 있습니다.
```

## 팀 공유 / 의존

- `.claude/skills/` 의 팀 공유 자산(projectSettings, 최우선). 자동 트리거 없음(`disable-model-invocation`) — 사용자가 명시 호출.
- 의존: `.claude/agents/loop-checker.md`, `.claude/agents/loop-lesson-synthesizer.md`(lessons), `.claude/skills/_loop-engine/`(채점 셸), `docs/loop/rubric.md`(루브릭·brake 단일 원천). 전부 같은 레포에 커밋돼 별도 셋업 불필요.
- 런타임 상태(`.claude/loop/{ticket}/`)는 `.gitignore` 로 추적 제외 — 루프 한정 휘발성, run 종료 시 폐기(lessons 종합 후).
