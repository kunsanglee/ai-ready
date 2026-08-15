# 무인 검증 loop 루브릭 — BASE (프로젝트 무관 골격)

> 이 문서는 **BASE 루브릭 — 프로젝트 무관 골격**입니다. 사람이 읽고 편집합니다.
> 적용 로직(종류 lookup·가중 상향·집계·종료 판정·정체 floor 계산)은 같은 plugin 의 `_loop-engine/` 셸이
> 가지고, 이 표를 파싱해 채점합니다. 스택·도메인 특유 종류(예: DDL 안전성·i18n 키 누락)는 여기 두지 않고
> 대상 프로젝트가 LOCAL rubric(`$CLAUDE_PROJECT_DIR/.loop/rubric.md`)에 추가합니다. BASE 와 LOCAL 은
> 병합돼 채점되며 같은 kind/dimension 은 LOCAL 이 BASE 를 덮습니다.

## 핵심 원칙

- **severity 는 checker(LLM)가 매기지 않는다.** checker 는 finding 을 발견해
  `(종류 kind, 차원 dimension, 가중조건 플래그 weights, 위치 location, 근거 evidence, 사람 대기 force_await)`
  를 태깅하고, phase 가 안 볼 표면(`non_goals`)을 프롬프트로 받았으면 범위 표시 `in_scope` 를 더한다
  (계약 전문은 이 루프의 checker 역할 계약 문서 — 호스트마다 그 문서가 놓인 자리가 다르다).
  이 문서의 표를 보고 결정론 셸이 severity 를 매긴다.
  같은 코드엔 항상 같은 severity.
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

## 경로에서 유도하는 가중 (모델이 안 달아도 서게 한다)

위 가중은 **checker 가 달아 준다.** 그래서 안 달면 조용히 한 단계 낮게 채점된다 — 결함은 제대로
보고됐고 등급도 표대로 매겨졌는데 결과만 낮은, **신호가 아무 데도 안 남는 강등**이다.
같은 운영 DB 마이그레이션 finding 이 표시 유무로 `RETRY` 와 `AWAIT_USER` 로 갈린다.

그래서 finding 의 `location` 경로가 아래 패턴에 걸리면 **셸이 가중을 직접 붙인다.** checker 가 준
가중과 합집합이고, 합친 뒤 위 WEIGHTS 허용 표를 다시 지난다(허용 표가 여전히 단일 원천이다).
붙인 것은 출력의 `weights_derived` 로 드러나 어디서 왔는지 감사할 수 있다.

**패턴은 한 행에 하나만 쓴다.** 표 구분자가 `|` 라 정규식 안의 `|` 교대(alternation)는 열을 쪼갠다.
여러 경로를 덮으려면 행을 늘린다. `weight_keys` 는 쉼표로 여럿 쓸 수 있다.
패턴은 `location` 문자열에 대한 **대소문자 무시** 부분 일치이고, 잘못된 정규식은 그 행만 건너뛴다
(한 줄 오타가 배치 전체를 죽이지 않게 — 대신 그 행은 아무것도 못 붙인다).
**`weight_keys` 가 위 WEIGHTS 허용 표 밖이면 설정 오류로 거부한다**(exit 65). 조용히 무시하면
사람은 그 경로를 덮었다고 믿는데 실제로는 아무 가중도 안 서고, `|` 로 열이 밀린 행이 그 모양이 된다.

> **BASE 목록은 2026-08-09 적대적 시험으로 채웠다.** 처음엔 다섯 줄이었는데 흔한 배치를 놓쳤다 —
> `/migrations/` 가 앞 슬래시를 요구해 레포 루트 `migrations/`(golang-migrate·sqlx)를 놓쳤고,
> Rails 의 `db/migrate/` 는 `db/migration` 과 한 글자 차이로 빗나갔고, Liquibase 의 실제 관례
> 디렉터리는 `db/changelog` 인데 패턴은 리터럴 `liquibase` 라 보통 경로에 안 나왔다.
> 대소문자를 가려 `DB/Migration` 도 빠졌다. **운영 DB 를 드롭하는 finding 이 사람 없이 돌 수 있었다.**

**BASE 에는 어느 스택에서나 같은 뜻인 것만 둔다.** DB 마이그레이션 디렉터리가 그렇다.
돈·인가 경로는 저장소마다 이름이 달라 BASE 가 못 정한다 — LOCAL rubric 에 자기 경로를 적는다.

<!-- LOOP_RUBRIC:PATHWEIGHTS:BEGIN -->

| path_pattern | weight_keys |
|---|---|
| db/migration | operational_data |
| migrations/ | operational_data |
| db/migrate/ | operational_data |
| db/changelog | operational_data |
| flyway | operational_data |
| liquibase | operational_data |
| alembic/versions | operational_data |
| changeset | operational_data |

<!-- LOOP_RUBRIC:PATHWEIGHTS:END -->

### 유도에서 빼는 경로

위 패턴은 부분 일치라 마이그레이션을 **설명하는** 문서, 테스트 픽스처, 의존성 트리까지 걸린다.
그러면 마이그레이션 정책 문서에 테스트가 없다는 지적 하나가 `AWAIT_USER` 를 내고
**밤새 도는 무인 루프가 거기서 선다**(2026-08-09 실측: `docs/db/migration-policy.md`,
`src/test/fixtures/migrations/seed.sql`, `node_modules/p/migrations/x.js` 셋 다 사람 대기였다).

아래 패턴에 걸리는 `location` 은 유도를 아예 안 받는다(checker 가 직접 단 가중은 그대로 남는다).
이 표는 **LOCAL 이 BASE 경로 규칙을 끄는 유일한 길**이기도 하다 — KINDS·DIMFLOOR 는 같은 키를
LOCAL 이 덮지만 PATHWEIGHTS 는 누적이라, 마이그레이션 디렉터리가 통째로 픽스처인 저장소는
여기에 자기 경로를 적어 뺀다.

<!-- LOOP_RUBRIC:PATHEXCLUDE:BEGIN -->

| exclude_pattern |
|---|
| node_modules/ |
| vendor/ |
| \.md$ |
| /fixtures/ |
| /testdata/ |
| src/test/ |
| /__tests__/ |

<!-- LOOP_RUBRIC:PATHEXCLUDE:END -->

## 자동화 금지 영역 (severity 무관 사람 대기)

비가역성·운영 데이터 영향이 기준. 아래에 닿는 finding 은 점수 만점이어도 `AWAIT_USER`.
표의 `force_await=always` 열, 또는 finding 의 `force_await=true` 플래그로 적용한다.

1. 운영 DB 만지는 DML/DDL (UPDATE/DELETE 마이그레이션, 컬럼 삭제, enum 제거) — `ddl-safety`
2. 돈·포인트·정산·결제 경로 — `money-path-change`
3. 인가 정책 변경 — `authz-policy-change`
4. 알림·메시지 대량 발송 (회수 불가) — `mass-dispatch`
5. 삭제·익명화·탈퇴 처리 (복구 불가) — `destructive-data-op`

> **다섯에 `kind_id` 를 준 이유(2026-08-09).** 이 목록은 오래 산문으로만 있었고, 종류표에
> `force_await=always` 를 쓰는 행이 **하나도 없었다.** "표의 열, 또는 finding 의 플래그" 두 경로 중
> 앞쪽이 비어 있었다는 뜻이고, 실제로 도는 것은 checker 가 자기 판단으로 다는 플래그뿐이었다.
> 그건 사람 대기 여부를 **프롬프트 준수**에 맡긴 것이다. 이제 checker 가 종류 이름만 맞게 부르면
> 사람 대기가 표에서 선다. 종류를 잘못 부르면 여전히 새지만, 모델이 맞춰야 할 것이
> **둘(종류 + 가중 플래그)에서 하나(종류)로** 줄었다. 이름은 스택 무관하게 골랐다 — 프로젝트가
> 자기 용어를 쓰고 싶으면 LOCAL 에서 같은 `kind_id` 로 덮거나 별칭 행을 더한다.
>
> **`force_await=always` 는 LOCAL 이 끄지 못한다(2026-08-09).** 다른 열은 LOCAL 이 덮지만 이 열만
> 병합이 합집합이다 — 어느 쪽이든 `always` 면 `always` 다. 그러지 않으면 LOCAL 한 줄로 다섯 게이트가
> 통째로 사라지는데, 그 파일은 `.loop/rubric.md` 라 **채점받는 쪽(maker)이 쓸 수 있는 자리**다.
> 등급은 여전히 LOCAL 이 조절할 수 있고, 사람 대기만 남는다.
>
> **다섯 행의 `always` 는 등급과 겹친다.** `base_severity` 가 BLOCKER 라 그것만으로 이미 사람 대기다.
> 그래도 `always` 를 함께 적는 이유는, 나중에 누가 등급을 내려도 사람 대기가 남게 하기 위해서다
> (이 목록의 뜻이 "등급 무관 사람 대기" 라서다). 겹친다는 것은 **변이로 확인했다** — 다섯 행의
> `always` 를 `no` 로 바꿔도 테스트가 하나도 안 깨졌다. 그래서 `always` 자체는 등급이 낮은 행으로
> 따로 잠갔다(`test.sh` 의 `minor-but-irreversible`).

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
>
> **simplicity 가 MAJOR 인 이유는 두 실패를 동시에 피하려는 것이다.** MINOR 로 두면 잡아도 PASS 를 막지 않아
> 과잉 설계가 기록만 되고 그대로 남는다 — 무인 루프가 수렴시킨 코드가 단순성 검사를 사실상 안 받는 셈이다.
> CRITICAL 로 두면 반대로 "더 단순한 형태가 있다" 는 판단이 갈리는 지적이 PASS 를 완전히 막아, 루프가 취향
> 논쟁으로 회차를 더 쓴다. MAJOR 는 `RETRY_SOFT` 를 내서 고치려 시도하되 정체하면 사람이 그 등급을 안고
> 통과시킬 수 있는 자리다. 이 차원은 "더 적은 코드로 같은 일이 되는가" 만 보고, 등가 대안을 제시할 수 없는
> 지적은 checker 본문이 금지한다.

<!-- LOOP_RUBRIC:DIMFLOOR:BEGIN -->

| dimension | floor |
|---|---|
| security | CRITICAL |
| compatibility | CRITICAL |
| intent | MAJOR |
| runtime | CRITICAL |
| convention | MINOR |
| simplicity | MAJOR |

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
| doc-lags-code | intent | agent | MINOR | no | 문서가 코드를 못 따라간 것(새 결정·필드·DDL 이 문서에 아직 없음, 문서가 적은 개수·목록이 낡음). intent floor(MAJOR) 아래로 — 코드는 정상이고 문서만 고치면 되는 자리라 회차를 더 쓰지 않는다. **코드가 문서를 어기는 반대 방향(`intent-requirement-missing`·`intent-nongoal-violation`)은 등급 그대로다** |
| n-plus-1 | runtime | agent | MAJOR | no | runtime floor(CRITICAL) 아래. hotpath 가중 시 CRITICAL |
| test-missing | convention | agent | CRITICAL | no | 작성·수정한 코드에 대응 테스트 누락. 프로젝트 테스트 규약 기준. convention floor(MINOR) 위로 — 코드 변경분 테스트 필수 |
| test-vacuous | convention | agent | CRITICAL | no | 테스트가 있으나 변경을 되돌려도 통과한다(되돌림을 아무것도 잡아내지 못한다). 없는 것보다 나쁘다 — 덮인 것처럼 보인다 |
| comment-noise | simplicity | agent | MINOR | no | 코드를 그대로 다시 말하는 주석. simplicity floor(MAJOR) 아래로 — 잡되 통과를 막지 않는다(주석 문구로 회차를 더 쓰지 않게) |
| comment-rot | convention | agent | MINOR | no | 주석이 **그 파일이 안 바뀌어도 틀려질 수 있는 것**을 말한다 — 다른 컴포넌트의 동작, 근거가 다른 파일에 있는 개수·주기. 그 값이 바뀔 때 이 파일은 안 열리므로 아무도 모르고, 주석만 틀려져도 컴파일·테스트는 통과한다. convention floor(MINOR) 와 같다 — `comment-noise` 와 같은 이유로 통과를 막지 않는다. **셋은 대상이 아니다**: 그 문장 안에서 다 세어지는 개수, 날짜를 붙인 실측 기록(기록은 낡아도 거짓이 아니다), 검사가 지키고 있는 사실(테스트·빌드 게이트가 확인하면 조용히 안 틀려지고 검사가 먼저 실패한다 — 프로젝트가 주석 속 경로 실재를 검사한다면 경로가 그 경우다). `comment-noise`(중복)·`doc-lags-code`(문서가 코드에 뒤처짐)와 다른 축이다: 여기는 코드 옆 주석이 **바깥 사실**을 말하는 것 |
| ddl-safety | runtime | gate | BLOCKER | always | 자동화 금지 1 — 운영 DB DML/DDL. 비가역이라 등급 무관 사람 대기 |
| money-path-change | runtime | agent | BLOCKER | always | 자동화 금지 2 — 돈·포인트·정산·결제 경로 |
| authz-policy-change | security | agent | BLOCKER | always | 자동화 금지 3 — 인가 정책 변경 |
| mass-dispatch | runtime | agent | BLOCKER | always | 자동화 금지 4 — 알림·메시지 대량 발송(회수 불가) |
| destructive-data-op | runtime | agent | BLOCKER | always | 자동화 금지 5 — 삭제·익명화·탈퇴(복구 불가) |

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
| repeated_kind_cycles | 3 |
| max_iterations | 5 |
| budget_usd | 500 |
| budget_tokens | 5000000 |
| budget_minutes | 120 |

<!-- LOOP_RUBRIC:PARAMS:END -->

> 정체 파라미터와 brake 파라미터를 한 표에 둔다 — 이 표가 loop 설정 전체의 단일 원천이다.
> 정체 파라미터(`stall_threshold_*`, `regress_consecutive`)는 `stall.sh` 가 `loop_param` 으로 읽는다.
> `repeated_kind_cycles` 는 `kindstreak.sh` 가 같은 방식으로 읽는다 — 같은 **종류**의 finding 이 몇 사이클
> 연속으로 그 사이클을 지배하면 사람을 부를지다. 3인 이유는 두 번은 우연일 수 있고 세 번이면 코드가 아니라
> 목표를 의심할 근거이기 때문이다(끝나는 지점이 없는 목표는 하나를 고칠 때마다 checker 가 다음 하나를 찾는다).
> brake 파라미터(`max_iterations`, 예산 `budget_usd`/`budget_tokens`/`budget_minutes`)는 무인 드라이버가
> 같은 `loop_param` 으로 읽는다. 드라이버는 대상 프로젝트 워크트리를 들고 있어 이 읽기가 공짜다.
> 값은 단일 통일(5회 / $500 / 5M 토큰 / 120분) — 무인(케이스2)·핸드오프(케이스3) 같은 상한. 케이스별 프로파일은 두지 않는다.
> 토큰(5M)이 실질 상한이고 $500 은 폭주 안전망(opus 단가상 5M 토큰을 넉넉히 덮어 토큰이 먼저 닿게). 케이스2 는 회차별 정확 집행,
> 케이스3 은 회차·시간·정체 자가 집행 + 종료 후 비용 백스톱. 런별 오버라이드가 필요하면 드라이버 호출 시 env 로 전달해
> 이 기본값을 덮어쓴다 — 커밋되는 별도 프로파일 파일은 두지 않는다(`.loop/run/{ticket}/` 에는 루프 한정 휘발 상태만 —
> state·history 와 Bash 호출 간 재유도 스냅숏 `params.env` — 남고 종료 시 폐기된다).
