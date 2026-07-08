# 무인 검증 loop 루브릭 — BASE (프로젝트 무관 골격)

> 이 문서는 **BASE 루브릭 — 프로젝트 무관 골격**입니다. 사람이 읽고 편집합니다.
> 적용 로직(종류 lookup·가중 상향·집계·종료 판정·정체 floor 계산)은 같은 plugin 의 `_loop-engine/` 셸이
> 가지고, 이 표를 파싱해 채점합니다. 스택·도메인 특유 종류(예: DDL 안전성·i18n 키 누락)는 여기 두지 않고
> 대상 프로젝트가 LOCAL rubric(`$CLAUDE_PROJECT_DIR/.loop/rubric.md`)에 추가합니다. BASE 와 LOCAL 은
> 병합돼 채점되며 같은 kind/dimension 은 LOCAL 이 BASE 를 덮습니다.

## 핵심 원칙

- **severity 는 checker(LLM)가 매기지 않는다.** checker 는 finding 을 발견해
  `(종류 kind, 차원 dimension, 가중조건 플래그 weights, 위치 location, 근거 evidence)` 만 태깅한다.
  이 문서의 표를 보고 결정론 셸이 severity 를 매긴다. 같은 코드엔 항상 같은 severity.
- **종료는 점수 합산이 아니라 severity 게이트.** 게이트 모두 통과 + `BLOCKER 0 AND CRITICAL 0` → PASS.
  가중 합산("총점 82라 통과")은 critical 하나를 사소한 감점에 묻으므로 금지.
- **brake 가 평가보다 먼저, 결정론 게이트가 LLM 검증보다 먼저.**

## severity 4단계와 행동 매핑

| severity | 행동 | 뜻 |
|---|---|---|
| BLOCKER | `AWAIT_USER` (사람 대기) | maker 가 못 고치거나 고치면 안 됨. 비가역·자동화 금지 영역 |
| CRITICAL | `RETRY` (maker 재진입) | 진짜 결함이나 maker 가 고칠 수 있음 |
| MAJOR | `RETRY_SOFT` | 고치면 좋으나 통과 가능. 전용 카운터 없이 loop 공통 brake(정체·반복 상한)에 위임. 정체로 멈추면 사람에게 "이 MAJOR 안고 통과?" 승인 옵션 |
| MINOR | `PASS` (기록만) | 통과 |

severity 사다리(낮음→높음): `MINOR(1) < MAJOR(2) < CRITICAL(3) < BLOCKER(4)`.

## 가중 조건 (한 단계 상향)

finding 이 아래 4개 가중 조건 중 **하나라도** 걸리면 기본 severity 를 한 단계 올린다.
`CRITICAL → BLOCKER` 면 사람 대기로 넘어간다. 이 목록 밖의 사유로 임의 상향 금지.

- `hotpath` — 핫패스
- `operational_data` — 운영 데이터 접근
- `money` — 돈·정산 경로
- `authz` — 인가 변경

checker 는 finding 의 `weights` 배열에 위 키를 담아 보낸다. 셸이 아래 허용 표의 키가 하나라도 있으면 한 단계 올린다(표 밖 키는 무시 — 임의 상향 차단). 아래 표가 가중 키의 단일 원천이며, 프로젝트가 LOCAL rubric 의 같은 마커로 키를 더할 수 있다.

<!-- LOOP_RUBRIC:WEIGHTS:BEGIN -->

| weight_key |
|---|
| hotpath |
| operational_data |
| money |
| authz |

<!-- LOOP_RUBRIC:WEIGHTS:END -->

## 자동화 금지 영역 (severity 무관 사람 대기)

비가역성·운영 데이터 영향이 기준. 아래에 닿는 finding 은 점수 만점이어도 `AWAIT_USER`.
표의 `force_await=always` 열, 또는 finding 의 `force_await=true` 플래그로 적용한다.

1. 운영 DB 만지는 DML/DDL (UPDATE/DELETE 마이그레이션, 컬럼 삭제, enum 제거)
2. 돈·포인트·정산·결제 경로
3. 인가 정책 변경
4. 알림·메시지 대량 발송 (회수 불가)
5. 삭제·익명화·탈퇴 처리 (복구 불가)

## 3층 분리

| 층 | 판정 방식 | 비고 |
|---|---|---|
| 게이트 층 | 스크립트/컴파일/테스트 (에이전트 불필요) | severity 매기기 전 단계. 실패하면 checker 안 부르고 maker 재진입(운영 비가역 게이트는 사람 대기) |
| 추론 층 | 에이전트가 코드 의미를 읽어야 판정 | 동시성·트랜잭션·N+1·논리 회귀·멱등성·IDOR·compatibility |
| 정합 층 | 작업 정의(PRD/티켓) ↔ 코드 대조 | 기획 정합 |

> 게이트 층의 *기존 테스트 깨짐* 은 severity 가 아니라 즉시 `RETRY` 를 내므로 아래 종류표에 넣지 않는다
> (오케스트레이터의 게이트 단계가 checker 호출 전에 직접 처리). 반면 *작성·수정한 코드에 대응 테스트가 아예 없는 것*
> (커버리지 누락)은 "어떤 변경에 어떤 테스트가 대응하는지"를 게이트가 결정론으로 못 가리므로, checker 가 코드 의미를 읽어
> 잡아 종류표의 `test-missing`(convention, CRITICAL → RETRY) 으로 채점한다. maker 는 코드를 고치면 그 변경분 테스트도 함께 작성해야 한다.

## 차원 floor (채점의 주 경로)

모든 finding 은 기본적으로 그 차원의 floor severity 로 채점된다. 아래 예외표에 오른 종류만 floor 대신 자기 값을 쓴다.
모르는(표에 없는) 종류도 같은 규칙 — 차원 floor 로 채점된다. fallback 이 아니라 **주 메커니즘**이다.
floor 와 다른 종류가 반복되면 ANTIPATTERNS 승인 단계에서 예외표에 한 줄 등록된다(옛 "lessons 졸업"을 대체).

> floor 값은 "모르는 건 더 보수적으로"가 기준. runtime·intent 를 한 단계씩 올렸다(runtime MAJOR→CRITICAL: 모르는 runtime → RETRY,
> intent MINOR→MAJOR: 모르는 intent → RETRY_SOFT). security 차원은 BASE 에선 넓게 본다(인가·인증·입력 검증·민감정보 —
> checker 본문 security 절과 동일 기준). "security=IDOR 하나로 좁히기"는 특정 프로젝트(c8c-api)의 LOCAL 결정이지 BASE 규칙이
> 아니다 — 좁히려는 프로젝트는 LOCAL rubric·컨벤션 문서에 그 결정을 명시한다.

<!-- LOOP_RUBRIC:DIMFLOOR:BEGIN -->

| dimension | floor |
|---|---|
| security | CRITICAL |
| compatibility | CRITICAL |
| intent | MAJOR |
| runtime | CRITICAL |
| convention | MINOR |

<!-- LOOP_RUBRIC:DIMFLOOR:END -->

## 종류별 severity 예외표 (floor 와 다른 것만)

대부분의 종류는 위 dimension floor 로 채점된다(주 경로). 이 표에는 **자기 dimension floor 와 severity 가 다른 예외만** 적는다.
표에 없는 kind 는 — 모르는 종류든 floor 와 같은 종류든 — dimension floor 로 채점된다.
`base_severity` 는 가중 조건 적용 전 기본값. `force_await=always` 면 가중·severity 무관 사람 대기.
조건부 사람 대기(IDOR+`authz`, 멱등성+`money`)는 별도 열이 아니라 가중 상향(CRITICAL→BLOCKER→AWAIT_USER)으로 자연히 처리된다.
이 표는 ANTIPATTERNS 승인 단계에서만 자란다 — 반복되는 새 종류가 자기 floor 와 다를 때 한 줄 추가, floor 와 같으면 안 늘린다.

> floor 로 처리되어 표에서 빠진 종류(결정 이력): compatibility 3종·security idor·runtime 8종(concurrency-bug, transaction-scope,
> event-before-commit, idempotency-missing, unbounded-findall, logic-regression, timeout-missing, enum-removal-risk)·convention-violation·
> intent-requirement-missing 은 전부 자기 dimension floor 와 같아 floor 가 채점한다. `input-validation-injection`·`sensitive-info-exposure` 를
> 점검 범위에서 뺀 것(C-8: security=IDOR only)은 c8c-api 의 LOCAL 결정이다 — BASE 채점은 지금도 그 kind 슬러그가 오면
> security floor(CRITICAL)로 채점하며, 다른 프로젝트의 checker 는 security 를 넓게 본다.

<!-- LOOP_RUBRIC:KINDS:BEGIN -->

| kind_id | dimension | layer | base_severity | force_await | note |
|---|---|---|---|---|---|
| intent-nongoal-violation | intent | agent | BLOCKER | no | 문서가 금지한 동작 수행. intent floor(MAJOR) 위로 |
| intent-overreach | intent | agent | MINOR | no | scope 초과 구현. intent floor(MAJOR) 아래로 |
| n-plus-1 | runtime | agent | MAJOR | no | runtime floor(CRITICAL) 아래. hotpath 가중 시 CRITICAL |
| test-missing | convention | agent | CRITICAL | no | 작성·수정한 코드에 대응 테스트 누락. 프로젝트 테스트 규약 기준. convention floor(MINOR) 위로 — 코드 변경분 테스트 필수 |

<!-- LOOP_RUBRIC:KINDS:END -->

## 종료 판정 (집계)

scored finding 들을 모아 verdict 하나를 낸다. LLM 의 "괜찮아 보임" 금지, 결정론 집계.

- 하나라도 `await=true`(BLOCKER 또는 force_await) → `AWAIT_USER`
- BLOCKER 0 이고 CRITICAL ≥ 1 → `RETRY` (maker 재진입)
- 위 둘 아니고 MAJOR ≥ 1 → `RETRY_SOFT` (계속 개선하되 정체 시 사람 승인으로 통과 가능)
- 그 외(MINOR 만 또는 깨끗) → `PASS`

## 정체 점수 (사전식 벡터 + best-ever floor)

종료가 아니라 **정체 감지** 에만 쓰는 점수. brake 의 일부.

- **상태 = 등급 개수 벡터 `(CRITICAL 수, MAJOR 수, MINOR 수)`. 사전식 비교.**
  가중 합 버림 — MINOR 대량 정리로 CRITICAL 가리는 게이밍 차단. BLOCKER 는 즉시 사람이라 제외.
- **진전 = loop 시작 이래 최저(best-ever floor)를 갱신했을 때만.** "직전 대비"가 아니라 "역대 최저".
  가짜로 나빴다 되돌리는 토글·decoy 희석을 차단. 헛바퀴는 floor 를 못 깬다.
- **정체 = floor 를 연속 N사이클 미갱신.** 임계 기준은 현재 cur 의 최상위 비0 등급 — CRITICAL 이면
  `stall_threshold_critical`, MAJOR 면 `stall_threshold_major`. cur 가 MINOR 만이면 비활성(게이트가 통과).
  floor 가 한 번 MINOR-only 에 닿았어도 cur 가 CRITICAL 로 퇴행해 고착되면 STALLED 가 떠야 하므로,
  임계 기준은 floor 가 아니라 cur 다(floor 기준이면 그 퇴행을 영영 못 잡는 사각이 생긴다).
- **악화(직전 대비 상위 등급 새로 생김) = `regress_consecutive` 연속이면 즉시 사람.**

<!-- LOOP_RUBRIC:PARAMS:BEGIN -->

| param | value |
|---|---|
| stall_threshold_critical | 2 |
| stall_threshold_major | 2 |
| regress_consecutive | 2 |
| max_iterations | 5 |
| budget_usd | 500 |
| budget_tokens | 5000000 |
| budget_minutes | 120 |

<!-- LOOP_RUBRIC:PARAMS:END -->

> 정체 파라미터와 brake 파라미터를 한 표에 둔다 — 이 표가 loop 설정 전체의 단일 원천이다.
> 정체 파라미터(`stall_threshold_*`, `regress_consecutive`)는 `stall.sh` 가 `loop_param` 으로 읽는다.
> brake 파라미터(`max_iterations`, 예산 `budget_usd`/`budget_tokens`/`budget_minutes`)는 무인 드라이버가
> 같은 `loop_param` 으로 읽는다. 드라이버는 대상 프로젝트 워크트리를 들고 있어 이 읽기가 공짜다.
> 값은 단일 통일(5회 / $500 / 5M 토큰 / 120분) — 무인(케이스2)·핸드오프(케이스3) 같은 상한. 케이스별 프로파일은 두지 않는다.
> 토큰(5M)이 실질 상한이고 $500 은 폭주 안전망(opus 단가상 5M 토큰을 넉넉히 덮어 토큰이 먼저 닿게). 케이스2 는 회차별 정확 집행,
> 케이스3 은 회차·시간·정체 자가 집행 + 종료 후 비용 백스톱. 런별 오버라이드가 필요하면 드라이버 호출 시 env 로 전달해
> 이 기본값을 덮어쓴다 — 별도 `profile.env` 파일은 두지 않는다(`.loop/run/{ticket}/` 는 state·history 전용).
