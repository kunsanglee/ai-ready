---
name: lessons
description: 무인 검증 loop 종료 후 lesson 승인 게이트. 루프가 잡은 실수(history diff)와 사람·PR 지적을 loop-lesson-synthesizer 가 영구 지식층 후보 초안으로 만들면, 한 번에 하나씩 추가/수정/버림을 사람에게 묻고 승인분만 반영한다. 호출 /lessons [--history <경로>]. Use this skill when the user says "/lessons", "lesson 종합", "교훈 반영", "안티패턴 후보", or wants to harvest a finished loop's mistakes into the knowledge layer. 자동 반영 없음 — 사람 승인이 의무.
---

# lessons — lesson 승인 게이트

> 무인 검증 loop 의 선순환을 닫는 사람 승인 게이트. 호출: `/lessons [--history <경로>]`. 보통 `/build` 종료 후 그 history 로 부른다.

무인 검증 loop 의 **선순환을 닫는 사람 승인 게이트**다. loop 가 잡은 실수(+ 사람·PR 이 더한 지적)를 `loop-lesson-synthesizer` 가 ANTIPATTERNS 후보 초안으로 만들면, 이 스킬이 **한 번에 하나씩** 추가/수정/버림을 사람에게 묻고 승인분만 영구 지식층에 반영한다.

선순환: loop 가 잡은 실수 → 사람 검증(여기) → 프로젝트 영구 지식층(`$LOOP_KNOWLEDGE_LAYER`, 예: `docs/ANTIPATTERNS.md`) → 다음 loop·세션이 그 자산을 읽고 같은 실수를 안 함.

## 🔌 plugin / 프로젝트 구조

- 이 스킬은 `ai-ready` plugin 의 일부다(과거 별도 loop-engine plugin 이었으나 v0.6.0 에서 통합).
- 의존(plugin 번들): `agents/loop-lesson-synthesizer.md`(후보 초안 작성, `ai-ready:` namespace), `_loop-engine/lessons.sh`(출처1 추출), `_loop-engine/detect_build.py`(지식층·문서 경로 감지), `_loop-engine/test.sh`(rubric 변경 시 채점 회귀).
- 반영 대상(프로젝트 델타, Step 1 감지가 경로를 줌): `$LOOP_KNOWLEDGE_LAYER`(영구 지식층 — ai-ready 가 만든 `docs/ANTIPATTERNS.md`), `$LOOP_RUBRIC_LOCAL`(LOCAL rubric `.loop/rubric.md` — 새 kind 예외표, 없으면 새로 만들 대상). 어댑터 파일은 없다 — 경로는 런타임 감지가 준다.
- 환경변수 없음. 반영은 사람이 승인한 것만 그 프로젝트 파일에 기록. 지식층은 ai-ready 와 공동 저작하는 append-only 문서라 통째로 덮어쓰지 않고 항목을 덧붙인다.

## 절대 원칙

1. **사람 승인 없이는 반영 금지.** synthesizer 도 이 스킬도 초안·제시까지다. 추가/수정/버림은 사람이 정한다. 무인 loop 여도 이 한 단계는 반드시 사람.
2. **수록 문턱을 지킨다.** 영구 지식층(`$LOOP_KNOWLEDGE_LAYER`) 헤더 기준이 권위: 동일 위치 fix 3회+ 또는 revert. 못 넘으면 모듈 `CLAUDE.md` "절대 금지" 로만, 또는 보류. 한 loop 1회 발생은 대개 문턱 미달 — 과거 git fix 핫스팟과 합산해야 넘는다.
3. **rubric 예외표는 ANTIPATTERNS 승인 때만 자란다.** 승인된 후보가 반복되는 새 종류이고 그 severity 가 자기 dimension floor 와 **다를 때만** KINDS 표에 한 줄 추가. floor 와 같으면 안 늘린다.

## 호출 예시

```
/lessons                                   # 직전 loop 의 history 에서 출처1 자동 추출 → 후보 검토
/lessons --history .loop/run/{ticket}/history-{phase}.jsonl    # history 경로 명시
```

## 작업 흐름

### Step 1. 입력 수집 (출처1 + 출처2)

- **출처1 (loop 가 잡고 maker 가 고친 실수)**: `loop-lesson-synthesizer` 가 받을 JSON. 없으면 history 경로로 직접 만든다.
  ```bash
  # 엔진: plugin 번들. **$CLAUDE_PLUGIN_ROOT 는 Bash 도구의 셸에 없다** — 스킬 본문을 만들 때
  # 치환되는 값이라 자식 셸로 안 내려간다(실측). 그대로 쓰면 ENG=/_loop-engine 이 되어 조용히 없는
  # 경로를 가리킨다. 이 스킬 본문 맨 위의 "Base directory for this skill" 값을 그대로 넣는다.
  SKILL_DIR="<이 스킬 본문 첫머리의 Base directory 를 그대로 넣는다>"
  ENG="$(cd "$SKILL_DIR/../.." && pwd)/_loop-engine"
  [ -f "$ENG/lib.sh" ] || { echo "loop: 엔진을 못 찾았다 ($ENG) — base directory 확인" >&2; exit 65; }
  PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
  # 반영 대상 경로를 런타임 감지(읽기 전용, 어댑터 파일 없음).
  DET="$(python3 "$ENG/detect_build.py" --target "$PROJECT_ROOT")"
  LOOP_KNOWLEDGE_LAYER="$(printf '%s' "$DET" | jq -r '.knowledge_layer // ""')"   # ai-ready 가 만든 docs/ANTIPATTERNS.md
  LOOP_RUBRIC_LOCAL="$PROJECT_ROOT/.loop/rubric.md"                                # 있으면 병합 대상, 없으면 새 kind 추가 시 생성
  # 감지 값을 창에 출력 — 변수 대입만으론 Step 2 프롬프트에 넣을 값이 오케스트레이터에게 존재하지 않는다.
  echo "lessons 값: knowledge=[${LOOP_KNOWLEDGE_LAYER:-없음}] / local_rubric=$LOOP_RUBRIC_LOCAL / engine=$ENG"
  bash "$ENG/lessons.sh" --history <history-{phase}.jsonl>
  ```
  (kind+위치)로 중복 제거한 mistake 목록 + 통과 시점 verdict 을 낸다. 통과 시 남은 MINOR 는 받아들여진 것이라 실수로 안 친다. `/build` 는 history 를 phase 별로 가르므로(`history-{phase}.jsonl`) `lessons.sh` 를 파일마다 반복 호출해 mistake 목록을 합친다(`--history` 는 파일 하나만 받는다).
- **출처2 (checker 가 놓친 것, 선택)**: 사람이 결과 검토 중 "checker 가 여기 놓쳤다/과하게 잡았다" 한 지적(세션 안이면 대화에서), 또는 무인 드라이버면 PR 코멘트 추출 결과. 텍스트로 모은다.
- 티켓/작업 요약 1~3문장(없으면 "작업 정의 없음").

### Step 2. synthesizer 호출 (후보 초안 작성)

`Agent` 툴로 `loop-lesson-synthesizer` 를 호출한다. 프롬프트에 출처1 경로(또는 내용)·출처2 지적·티켓 요약, 그리고 **지식층 경로·LOCAL rubric 경로·엔진 경로**(Step 1 이 echo 한 "lessons 값:" 줄의 값들)를 넘긴다 — 환경변수는 서브에이전트에 전달되지 않으므로 값 자체를 프롬프트 텍스트로 넘긴다. 지식층·LOCAL rubric 은 synthesizer 의 중복 차단·예외표 동반 제안이 읽고, 엔진 경로는 출처1 이 없을 때 synthesizer 가 `lessons.sh` 를 직접 돌리는 폴백에 쓴다. synthesizer 는:

- 출처1+출처2 를 같은 근본원인끼리 클러스터링.
- 각 클러스터를 일반 규칙인지/일회성인지 가르고 목적지 분류(ANTIPATTERNS / 모듈 CLAUDE.md / 버림·관찰).
- 후보마다 `DO NOT / 이유 / 대신` 초안 + (해당 시) rubric KINDS 예외표 한 줄을 낸다.
- 기존 ANTIPATTERNS·모듈 CLAUDE.md 와 중복이면 "기존 항목 N 보강" 으로 표시.

synthesizer 는 Edit/Write 가 없어 **절대 문서를 직접 안 고친다** — 출력은 후보 목록뿐이다.

### Step 3. 사람 게이트 (한 번에 하나씩)

synthesizer 후보를 **하나씩** 사용자에게 제시하고 추가/수정/버림을 묻는다. 각 후보에 synthesizer 의 추천(수록 문턱 충족 여부 + 목적지)을 같이 보여준다.

후보당 묻는 형식:

```
### 후보 {i} — {제목}
- 목적지(추천): {ANTIPATTERNS.md | {module}/CLAUDE.md | 버림/관찰}
- 수록 문턱: {충족 | 미충족(이유) | 과거 핫스팟 합산 시 충족}
- 초안:
  - DO NOT: ...
  - 이유: ... (이 loop: `파일:라인`, {severity}, {persisted_cycles}사이클 / 과거: {커밋·revert} / 출처2: {지적})
  - 대신: ...
- (해당 시) rubric KINDS 한 줄: `| {kind} | {dimension} | {layer} | {base_severity} | {force_await} | {note} |`

→ 추가 / 수정 / 버림 ?
```

한 번에 한 후보만 묻는다(grill-me 결). 사용자가 "수정" 이면 그 자리에서 문구를 고쳐 다시 확인받는다.

### Step 4. 승인분만 반영

사용자가 **추가**(또는 수정 후 승인)한 후보만 반영한다. 버림·보류는 아무 데도 안 쓴다.

- **영구 지식층 추가**: `$LOOP_KNOWLEDGE_LAYER`(ai-ready 가 만든 `docs/ANTIPATTERNS.md`) 끝의 다음 번호로 `## {N}. {제목}` 섹션을 *덧붙인다*(append, 통째 덮어쓰기 금지 — ai-ready 와 공동 저작하는 문서). 형식은 기존 항목과 동일하게 `**DO NOT**` / `**이유**` / `**대신**` 세 bullet. 이유에는 근거(이 loop `파일:라인`·severity·사이클 수 / 과거 커밋·revert / 출처2)를 남긴다. 감지된 지식층 경로가 비어 있으면(프로젝트에 `docs/ANTIPATTERNS.md` 부재) 사용자에게 어디에 둘지 묻는다 — 임의 생성 금지.
- **모듈 CLAUDE.md 추가**(문턱 미달·모듈 고유): 해당 `{module}/CLAUDE.md` "절대 금지" 섹션에 짧게.
- **LOCAL rubric KINDS 예외표**(해당 시만): 승인 후보가 반복되는 새 종류이고 severity 가 자기 dimension floor 와 다르면 프로젝트의 LOCAL rubric(`$LOOP_RUBRIC_LOCAL` = `.loop/rubric.md`)의 `LOOP_RUBRIC:KINDS` 마커 안 표에 한 줄 추가(BASE rubric 은 건드리지 않는다 — 프로젝트 특유 kind 는 LOCAL 로). **파일이 아직 없으면** KINDS 마커(`<!-- LOOP_RUBRIC:KINDS:BEGIN -->` ~ `:END`)와 6열 헤더(`kind_id|dimension|layer|base_severity|force_await|note`)만 갖춘 최소 골격으로 새로 만들고 그 한 줄을 넣는다(이것이 스택 특유 종류가 자라는 유일한 경로 — 별도 생성기 없음). floor 와 같으면 추가하지 않는다(원칙 3). 추가했으면 `bash "<엔진 경로>/test.sh"` 로 BASE 채점 회귀 0 확인 — 엔진 경로는 Step 1 이 창에 낸 "lessons 값:" 줄의 `engine=` 값이다(`$CLAUDE_PLUGIN_ROOT` 는 Bash 도구의 셸에 없고, 셸 변수도 호출을 건너 남지 않는다).
- 반영 후 변경 파일·추가 항목을 사용자에게 1줄로 보고한다. 커밋은 사용자/별도 절차가 한다(이 스킬은 파일 기록까지).

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| lessons.sh 출력이 비어있음 | history 파일에 "떴다가 사라진 finding" 없음(고친 실수 0) | 정상 — 후보 없음. 억지로 만들지 않는다 |
| 후보가 전부 "버림/관찰" | 전부 일회성·중복 | 정상. ANTIPATTERNS 는 반복·일반 규칙만. 그대로 종료 |
| rubric KINDS 추가 후 test 실패 | 표 형식 깨짐(열 수 불일치) | 6열(kind_id\|dimension\|layer\|base_severity\|force_await\|note) 맞췄는지 확인 |

## Non-Goals

- 자동 반영 — 사람 승인 게이트가 품질 차단선. 절대 자동화하지 않는다.
- severity 재산정 — synthesizer 가 들고 온 값을 인용만. 채점은 결정론 셸.
- loop 실행·재시도 — 이 스킬은 loop 종료 후 회고 단계.
