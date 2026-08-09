# `_loop-engine/` — 무인 검증 loop 결정론 루브릭 적용 셸 (ai-ready 플러그인 번들)

checker(LLM)가 발견한 finding 에 **결정론으로 severity 를 매기고, 종료 verdict 와 정체 여부를 판정**한다.
severity 는 checker 가 매기지 않는다 — 이 셸이 [`rubric.base.md`](./rubric.base.md)(BASE, 엔진 번들) + 프로젝트 LOCAL `.loop/rubric.md`(있으면 병합)의 표를 보고 매긴다.
같은 코드엔 항상 같은 severity (judge 일관성).

## 데이터 흐름

```
checker 렌즈 셋(축마다 자기 JSON findings 파일)
   │  { findings: [ {kind, dimension, weights[], force_await?, location, evidence}, ... ] }
   ▼
merge_findings.sh  렌즈 결과를 **개수를 세어** 하나로 합침 (--expect N 미달이면 exit 65)
   ▼
score.sh    종류 lookup + 가중 상향 + force_await  → finding 마다 severity/await 부여
   ▼
decide.sh   집계 → verdict: AWAIT_USER | RETRY | RETRY_SOFT | PASS  (+ counts)
   ▼
stall.sh    등급 개수 벡터 사전식 + best-ever floor → 정체/악화 판정 (사이클 간 상태 파일)
```

checker 를 한 명만 띄우는 호출(`/review`)은 그 결과 파일을 `score.sh` 에 바로 흘린다 — 합칠 것이 하나면 병합 단계가 없다.

루프가 끝나면(PASS 또는 사람 대기) 사이클 로그를 종합해 선순환을 닫는다:

```
history-{phase}.jsonl  (오케스트레이터가 사이클마다 append: { iteration, verdict, findings:[scored...] })
   ▼
lessons.sh     마지막 사이클 대비 diff → "출처1" 실수(떴다가 고쳐진 finding) 추출
   ▼
loop-lesson-synthesizer (agents/, ai-ready: namespace)  출처1 + 출처2(전자=대화 / 후자=PR 코멘트) → ANTIPATTERNS 후보 초안
   ▼
사람 게이트     추가/수정/버림 → 승인분만 docs/ANTIPATTERNS.md(+ 필요 시 rubric 예외표 한 줄) 반영
```

`rubric.base.md`(데이터, 사람 편집) 와 이 셸(로직)의 분리가 핵심. 표 한 줄 추가로 검증이 두꺼워진다.
영구 지식층은 ANTIPATTERNS 하나 — 옛 `docs/loop/lessons/` 중간 레지스트리는 폐기됐다.

## 스크립트

| 파일 | 책임 | 입력 → 출력 |
|---|---|---|
| `lib.sh` | 공용 부트스트랩: repo root·rubric 경로, severity 사다리, rubric 표 추출(awk/jq) | (source 전용) |
| `merge_findings.sh` | 축별 checker 렌즈가 각자 쓴 findings 파일 N 개를 채점 입력 하나로 합침. **`--expect N` 개수 검사가 존재 이유** — 렌즈가 죽어도 남은 결과는 형식이 멀쩡해 세지 않으면 그 축이 점검 없이 통과한다. 빈 파일·형식 위반·렌즈 간 base 불일치도 exit 65 | `--expect N 렌즈=경로 ...` → 합쳐진 findings JSON |
| `score.sh` | 깨끗함↔안 봄 게이트(findings·reviewed 둘 다 비면 exit 65), 종류 lookup → base severity, 경로 유도 + checker 가중 합집합으로 한 단계 상향, force_await 판정 | findings JSON → severity 부여된 findings |
| `decide.sh` | severity 집계 → 종료 verdict | scored JSON → `{verdict, counts, await}` |
| `stall.sh` | 사전식 벡터 + best-ever floor 정체 판정 | decide JSON + `--state <file>` → 갱신된 상태 |
| `lessons.sh` | 루프 종료 후 history-{phase}.jsonl diff → 출처1 실수(고쳐진 finding) 추출 | `--history <file>` → mistakes JSON |
| `test.sh` | 결정론 채점 회귀 테스트: 정상 채점 고정 + 변질 입력 fail-loud + lessons 결정론 | (인자 없음) → 통과/실패, exit 0=전부 통과 |

## 사용 예

```bash
# 한 사이클 전체 (렌즈 셋 → 병합 → 채점 → 판정 → 정체)
./merge_findings.sh --expect 3 \
    contract=.loop/run/CCE-1234/checker-p1-contract.json \
    safety=.loop/run/CCE-1234/checker-p1-safety.json \
    quality=.loop/run/CCE-1234/checker-p1-quality.json \
  | ./score.sh \
  | ./decide.sh \
  | tee verdict.json \
  | ./stall.sh --state .loop/run/CCE-1234/stall-p1.json

# checker 한 명이면 병합 없이 바로 채점
./score.sh checker-output.json | ./decide.sh

# 픽스처로 스모크 테스트
./score.sh fixtures/findings.example.json | ./decide.sh
```

## verdict 의미

- `AWAIT_USER` — BLOCKER 또는 자동화 금지 영역(force_await). 사람 대기.
- `RETRY` — CRITICAL 있음. maker 재진입해 고친다.
- `RETRY_SOFT` — MAJOR 만 있음. 통과 가능하나 개선 권장. 정체 시 사람 승인으로 PASS.
- `PASS` — MINOR 만 또는 깨끗.

## stall status 의미

- `INIT` — 첫 사이클. floor 초기화.
- `PROGRESS` — best-ever floor 갱신(역대 최저 경신).
- `ONGOING` — floor 미갱신이나 아직 임계 미만.
- `STALLED` — floor 연속 미갱신이 임계 이상. 임계는 cur 의 active grade 기준(floor 아님 — floor 가
  MINOR-only 라도 cur 가 CRITICAL 로 고착되면 STALLED). 사람 호출.
- `REGRESS_ESCALATE` — 직전 대비 "상위 등급 새로 생김"(CRITICAL/MAJOR 칸 증가)이 `regress_consecutive`
  연속. MINOR 만 늘어난 건 악화로 안 침. 즉시 사람.
- `NO_STALL_MINOR` — cur 가 MINOR 만 → 정체 비활성(게이트가 통과시킴).

## history 계약 (lesson 흐름 입력)

오케스트레이터가 사이클마다 한 줄(JSON)을 `.loop/run/{ticket}/history-{phase}.jsonl` 에 append 한다.
파일은 phase 별로 갈린다 — 회차·정체 판정이 phase 스코프라 앞 phase 의 이력이 다음 phase 판정에 섞이면 안 된다.
한 줄 = 한 사이클. `findings` 는 그 사이클 `score.sh` 출력(severity 부여됨), `verdict` 는 `decide.sh` 결과.

```
{ "iteration": N, "verdict": "RETRY", "findings": [ { kind, dimension, location, severity, evidence, ... }, ... ] }
```

`lessons.sh` 가 이걸 받아 **마지막 사이클에 없는 finding**(= 도중에 고쳐진 것)을 출처1 실수로 추출한다.
마지막 사이클에 남은 finding 은 "받아들여진 것"이라 실수로 안 친다.

```bash
# 루프 종료 후 출처1 실수 추출 → 휘발성 수집 파일. `--history` 는 파일 하나만 받으므로
# phase 가 여럿이면 파일마다 돌려 mistake 목록을 합친다(`/lessons` 가 그렇게 부른다).
./lessons.sh --history .loop/run/CCE-1234/history-foundation.jsonl > .loop/run/CCE-1234/lessons-source1.json

# 픽스처로 스모크 테스트
./lessons.sh fixtures/history.example.jsonl
```

`.loop/run/{ticket}/` 는 그 루프 한정 휘발성(gitignore). 종합 후 폐기 — 영구 보존은 사람이 승인한 ANTIPATTERNS 만.

## 설계 제약

- **macOS 기본 bash 3.2 호환.** 연관 배열(`declare -A`)·`${var^^}`·`mapfile` 미사용.
  데이터 가공은 awk/jq 로 위임. `jq`, `awk` 필수.
- **severity 는 셸이 매긴다.** checker 는 `(종류·차원·가중플래그·위치·근거)` 만 태깅.
- **변질 입력은 fail-loud.** 채점 셸은 신뢰하는 변환기가 아니라 안전 게이트다. 입력 생산자가 LLM checker 라
  빈/null/`{}`/형식오류 JSON 이 흔하다. 그걸 조용히 PASS 로 통과(fail-open)시키지 않고 `exit 65` 로 거부한다
  (오케스트레이터는 사람 대기 신호로 본다). 깨끗한 결과는 `{"findings":[],"reviewed":[...]}` 여야 통과다 — `reviewed` 가 비면 "안 본 것" 과 구분이 안 돼 거부한다. kind·dimension 누락은 jq
  크래시 없이 보수 채점하며, 모르는/누락 dimension 은 가장 관대한 MINOR 가 아니라 CRITICAL 로 떨어뜨린다.
  `decide.sh`·`stall.sh` 도 빈 입력과 계약 밖 입력(`findings`/`counts` 누락 — 배선 오류로 다른 단계 출력이 직결된 경우)을 거부해 파이프(`score|decide|stall`)가 앞단 실패를 통과로 둔갑시키지 못하게 한다.
- **종료는 점수 합산이 아니라 severity 게이트.** BLOCKER 0 AND CRITICAL 0 → PASS.
- 정체 점수는 **가중 합 버리고** 등급 개수 벡터 사전식 + best-ever floor("직전 대비" 아님)라
  MINOR 희석·토글 왕복 게이밍을 코어만으로 차단.

## 오케스트레이션 (ai-ready 0.6.0+ 구현 완료)

위 부품(채점 셸 score/decide/stall·병합 merge_findings·lesson 추출기 lessons·에이전트 loop-checker/loop-lesson-synthesizer)을 묶는 오케스트레이션은 ai-ready 플러그인의 **스킬**이 한다. 별도 `/loop` 스킬·`profile.env`·외부 게이트 스크립트(enum-converter-guard 등)는 두지 않는다 — 부품을 묶는 정책이 곧 스킬 본문이고, 게이트는 런타임 감지한 빌드·테스트 명령으로 스킬이 직접 돌린다.

- **`/build`** — 무인 자동 루프(사람 핸드오프, 케이스3). 일을 phase/step 으로 쪼개 승인을 한 번 받고, phase 마다 PASS 까지 순회한다. Step 0 에서 `detect_build.py` 로 빌드·테스트·린트 명령·티켓·베이스를 런타임 감지(어댑터 파일 없음), 매 사이클 brake(반복·시간) 선확인 → 컴파일·테스트 게이트 → checker 렌즈 셋(contract·safety·quality) 병렬 → `merge_findings|score|decide|stall` → verdict 분기 → maker 재스핀. 변경 하나만 수렴시키는 것은 phase 가 하나인 경우다. brake 값은 `rubric.base.md` PARAMS(`max_iterations` 5·`budget_minutes` 120 등) 단일 원천.
- **`/review`** — 1회 점검(사람이 곧 루프). checker 1회(렌즈 지정 없이 여섯 차원 전부) + 채점 → 보고서. 코드 안 고침.
- **`/lessons`** — 종료 후 lesson 수확. `lessons.sh` 출력 + 사람·PR 지적을 loop-lesson-synthesizer 가 ANTIPATTERNS 후보 초안으로 만들고, 사람 승인분만 반영.
- **케이스2(Sentry 무인)** — agent 봇이 `runLoopFix` 로 수정 worktree 에서 헤드리스로 `/build` 를 띄워 같은 엔진을 돈다(케이스2 = 케이스3, 헤드리스 위임). brake 집행도 그 스킬이 한다.

런타임 상태(`history-{phase}.jsonl` producer·`stall-{phase}.json` state·`started.epoch`·재유도 스냅숏 `params.env`·게이트 실패 카운터 `gate.fail`·렌즈별 checker findings/병합본/scored + 브랜치별 포인터 `.active-{브랜치}`)는 `/build` 스킬이 `$CLAUDE_PROJECT_DIR/.loop/run/{ticket}/` 에 사이클마다 append·갱신하고, 종료 시(lesson 종합 후) 폐기한다. `.loop/run/` 은 gitignore.
