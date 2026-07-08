---
name: loop-review
description: 무인 검증 loop 의 1회 점검 입구. 현재 브랜치 변경(기본 origin/main..HEAD)을 단일 loop-checker 로 한 번 적대적 점검해 등급 내림차순 보고서를 낸다. 코드를 고치지 않는다(사람이 곧 루프). 채점은 결정론 셸(BASE/LOCAL rubric) — 무인 루프와 같은 판정 기준을 사람이 미리 본다. 호출 /loop-review [--html]. Use this skill when the user says "/loop-review", "loop 리뷰", "검수 한 번", "이 변경 점검", or wants a one-shot adversarial review with the loop's rubric. 수렴까지 맡기면 /loop-run.
---

# loop-review — 1회 점검 보고서

> 무인 검증 loop 의 사람 입구(human-in-the-loop). 호출: `/loop-review [--html]`. 코드를 고치며 수렴까지 맡기면 `/loop-run`, 종료 후 교훈 수확은 `/loop-lessons`.

무인 검증 loop 의 **사람 입구**다. 무인 드라이버가 돌리는 것과 **똑같은 단일 checker(`loop-checker`) + 결정론 채점 셸**을 사람이 한 번 돌려, 등급순 보고서를 받는다. 루프가 아니다 — checker 1회 → 채점 → 보고서로 끝난다. 무엇을 고칠지는 사람이 정한다.

## 🔌 plugin / 프로젝트 구조

- 이 스킬은 `ai-ready` plugin 의 일부다(과거 별도 loop-engine plugin 이었으나 v0.6.0 에서 통합). checker·채점 셸·BASE rubric 은 plugin 번들(`$CLAUDE_PLUGIN_ROOT` 하위), 프로젝트 특유 LOCAL rubric 은 `$CLAUDE_PROJECT_DIR/.loop/rubric.md`(있으면 병합).
- 의존: `agents/loop-checker.md`(점검, `ai-ready:` namespace), `_loop-engine/`(채점 셸 `score.sh`·`decide.sh` + `detect_build.py` 감지기), `_loop-engine/rubric.base.md`(BASE 루브릭). 전부 plugin 번들이라 별도 셋업 불필요. review 는 게이트를 안 돌려 빌드 명령이 불필요하고, 베이스 브랜치·컨벤션 문서·지식층을 런타임 감지한다. 프로젝트에 `.loop/rubric.md` 가 있으면 LOCAL 로 병합해 점검 기준을 그 스택에 맞춘다(없으면 BASE 만).
- 환경변수·외부 인증 없음(전부 로컬 git + 셸).

## `/code-review` 와 차이

| | `/loop-review` | `/code-review` |
|---|---|---|
| 점검자 | 단일 `loop-checker` 1회 | 5개 전문 에이전트 병렬 |
| severity | 결정론 셸(rubric) — 같은 코드 = 같은 등급 | 각 에이전트가 매김 |
| 쓰임 | 무인 loop 와 동일 판정을 사람이 미리 봄 | 폭넓은 다관점 진단 |

둘은 보완재다. 무인 loop 에 올릴 코드를 그 loop 의 판정 기준으로 미리 보고 싶으면 `/loop-review`, 다관점 깊이 진단이면 `/code-review`.

## 호출 예시

```
/loop-review              # 현재 브랜치 origin/main..HEAD + uncommitted 점검 → markdown 보고서
/loop-review --html       # 같은 보고서를 자체완결 HTML 파일로
```

## 작업 흐름

### Step 1. 스코프·작업 정의 파악

```bash
ENG="$CLAUDE_PLUGIN_ROOT/_loop-engine"
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
# 베이스·컨벤션 문서·지식층을 diff 보다 먼저 감지한다 — 기본 브랜치가 master 인 레포에서
# origin/main 하드코딩이 깨지고, checker 프롬프트(Step 2)가 이 값들을 쓴다.
DET="$(python3 "$ENG/detect_build.py" --target "$PROJECT_ROOT")"
LOOP_BASE_BRANCH="$(printf '%s' "$DET" | jq -r '.base_branch // "origin/main"')"
LOOP_CONVENTION_DOCS="$(printf '%s' "$DET" | jq -r '(.convention_docs // []) | join(" ")')"
LOOP_KNOWLEDGE_LAYER="$(printf '%s' "$DET" | jq -r '.knowledge_layer // ""')"
git fetch origin --quiet 2>/dev/null || true
git diff "$LOOP_BASE_BRANCH"...HEAD --stat   # 브랜치에서 커밋된 전체 변경
git diff --stat                      # uncommitted (unstaged)
git diff --staged --stat             # uncommitted (staged)
# 감지 값을 창에 출력한다 — 변수 대입은 stdout 이 없어, 출력 없이는 Step 2 프롬프트에 넣을 값이 존재하지 않는다.
echo "review 값: base=$LOOP_BASE_BRANCH / conv=[${LOOP_CONVENTION_DOCS:-없음}] / knowledge=[${LOOP_KNOWLEDGE_LAYER:-없음}] / base_rubric=$ENG/rubric.base.md / local_rubric=[$([ -f "$PROJECT_ROOT/.loop/rubric.md" ] && echo "$PROJECT_ROOT/.loop/rubric.md" || echo 없음)]"
```

세 diff 의 파일 합집합이 점검 범위다. 대화/티켓에서 원래 작업 정의를 1~3문장으로 요약한다(없으면 "작업 정의 없음" — checker 가 동작 보존+범위 일탈로 좁혀 본다).

### Step 2. loop-checker 1회 호출 (독립 시선)

`Agent` 툴로 `loop-checker` 를 **한 번** 호출한다. **환경변수는 서브에이전트에 전달되지 않는다** — 아래 값 전부를 프롬프트 텍스트로 넘긴다. 프롬프트에 넘기는 것은 이것만:

- 원래 작업 정의(Step 1 요약, 1~3문장).
- 작업 정의 문서 경로(있으면 design/티켓 경로, 없으면 "missing").
- 비교 베이스: `$LOOP_BASE_BRANCH`(Step 1 감지, 기본 `origin/main`).
- 점검 기준 문서: 컨벤션 문서 목록과 지식층 경로 — Step 1 이 echo 한 "review 값:" 줄에서 가져온다(셸 변수는 이 시점에 이미 소멸). 비었으면 "없음"이라고 명시해 넘긴다.
- 종류 어휘 rubric 경로 둘 다: BASE 와 LOCAL(있으면) — 같은 "review 값:" 줄에 있다.
- findings 출력 경로(아래 `$F`).

**maker(이 세션)의 합리화·구현 변명을 checker 프롬프트에 넣지 마라.** checker 는 diff·문서·ANTIPATTERNS 만 보고 독립적으로 판단한다(분리 강제). checker 는 자기 도구(Read/Grep/Glob/Bash)로 diff 와 컨벤션 문서를 직접 읽는다.

**checker 결과는 파일로 회수한다.** 스핀 전에 findings 출력 경로를 결정적 위치로 잡고 `: > "$F"` 로 비운 뒤, 그 절대경로를 checker 프롬프트에 "findings 출력 경로"로 넘긴다:

```bash
# 레포 이름 + 브랜치 체크섬으로 격리 — 고정 단일 경로면 동시에 도는 두 review 가 서로 덮어쓴다.
# 슬러그 대신 체크섬인 이유: 한글 브랜치는 ASCII 슬러그에서 전부 지워져 서로 충돌하고, 체크섬은 어떤
# 브랜치명에도 결정적이다. 레포 이름을 붙여 다른 레포의 같은 브랜치명과도 갈라둔다(TMPDIR 는 사용자 공유).
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
F="${TMPDIR:-/tmp}/loop-review-findings-$(basename "$PROJECT_ROOT")-$(git rev-parse --abbrev-ref HEAD | cksum | tr ' ' '-').json"
: > "$F"
```

checker 는 `{base, findings:[...]}` 를 그 파일에 쓴다(인라인 ```json 블록도 남기지만 그건 가독성용 사본 — 백그라운드 세션은 최종 메시지 인라인 회수가 안 돼 파일이 정본). 랜덤 `mktemp` 는 쓰지 않는다(Bash 호출마다 셸이 새로 떠 변수가 Step 3 채점에 안 남는다) — 위 경로는 브랜치에서 결정적으로 재유도된다. 완료되면 그 파일을 Step 3 채점에 넣는다.

### Step 3. 결정론 채점 (score → decide)

checker 가 쓴 findings 파일(`$F`)을 채점 셸에 흘린다. **severity 는 셸이 매긴다 — checker 가 낸 등급을 쓰지 않는다(애초에 checker 는 등급을 안 낸다).**

```bash
ENG="$CLAUDE_PLUGIN_ROOT/_loop-engine"
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
# 프로젝트에 LOCAL rubric 이 있으면 BASE 와 병합(없으면 BASE 만으로 점검).
[ -f "$PROJECT_ROOT/.loop/rubric.md" ] && export LOOP_RUBRIC_LOCAL="$PROJECT_ROOT/.loop/rubric.md"
# F 는 Step 2 에서 잡아 checker 에 넘긴 findings 출력 파일(= checker 가 쓴 정본). 레포+브랜치 체크섬 경로라
# 여기서 같은 값으로 재유도된다 — 단 Step 2 와 Step 3 사이에 브랜치를 바꾸면 경로가 어긋나 거짓 "checker 실패"가 난다.
F="${TMPDIR:-/tmp}/loop-review-findings-$(basename "$PROJECT_ROOT")-$(git rev-parse --abbrev-ref HEAD | cksum | tr ' ' '-').json"
# checker 가 파일에 못 썼으면(빈/미생성) exit 65 로 fail-loud — 조용히 PASS 금지(정상 빈 배열은 -s 통과라 오탐 없음).
[ -s "$F" ] || { echo "loop: checker 가 findings 를 $F 에 안 씀(빈 파일/미생성) — checker 실패. 멈춰 보고" >&2; exit 65; }
SCORED=$(bash "$ENG/score.sh" "$F")          # finding 마다 severity·await·base·kind_known 추가
VERDICT=$(printf '%s' "$SCORED" | bash "$ENG/decide.sh")   # verdict·counts·await 집계
rm -f "$F"
```

- `$SCORED` = `{base, findings:[{..., severity, await, base, kind_known}]}`.
- `$VERDICT` = `{verdict, counts:{BLOCKER,CRITICAL,MAJOR,MINOR}, await}`.
- 셸이 `exit 65` 로 죽으면(빈/형식오류 입력) checker 가 findings 파일을 못 썼거나 형식이 깨진 것이다(위 `[ -s "$F" ]` 가드가 먼저 잡는 경우 포함) — 조용히 PASS 로 넘기지 말고 사용자에게 "checker 출력 파싱 실패"로 보고하고 멈춘다.

verdict 의미(rubric): `AWAIT_USER`(BLOCKER 또는 force_await — 사람만 처리), `RETRY`(CRITICAL≥1 — 무인 loop 면 maker 재진입감), `RETRY_SOFT`(MAJOR≥1 — 정체 시 사람 승인으로 통과 가능), `PASS`(MINOR 만/깨끗).

### Step 4. 보고서 조립 (등급 내림차순)

`$SCORED` 의 findings 를 severity 내림차순(BLOCKER>CRITICAL>MAJOR>MINOR)으로 정렬해 보고서를 만든다. 기본은 markdown.

```
## loop-review 결과

### Verdict: {verdict}   (BLOCKER {n} / CRITICAL {n} / MAJOR {n} / MINOR {n})

{checker 가 낸 차원별 한 줄 요약을 헤더로}

### {SEVERITY} — {kind} ({dimension})
- **위치**: {location}
- **근거**: {evidence}
- **가중**: {weights}   ·   **사람대기**: {await}
- **종류표 등록**: {kind_known ? "예" : "예외표 미등록 — 차원 floor 채점"}

... (등급 내림차순 반복) ...

### 다음 행동
- verdict 가 PASS 면: 무인 loop 기준으론 통과. 남은 MINOR 는 기록만.
- RETRY/RETRY_SOFT 면: CRITICAL/MAJOR finding 을 사람이 보고 고칠지 결정.
- AWAIT_USER 면: 자동화 금지 영역(운영 DB·돈·인가·대량발송·삭제)에 닿음 — 반드시 사람 판단.
```

이 스킬은 **지적만 한다 — 코드를 고치지 않는다.** 사용자가 보고서를 보고 무엇을 고칠지 정한다.

### Step 4-Alt. HTML 출력 (`--html` 일 때만)

`/code-review` 의 HTML 모드 규약을 그대로 따른다: 외부 의존성 없는 자체완결 단일 HTML 1개(CDN✗, inline `<style>`+`<script>`만), 경로 `/tmp/loop-review-{branch-slug}-{HHMMSS}.html`, 상단 verdict·counts 요약 카드, finding 카드(severity 색상 바 BLOCKER=red·CRITICAL=red·MAJOR=orange·MINOR=yellow, 파일경로 monospace, 복사 버튼), 인용 라인 외 코드 본문 복사 금지(라인+경로만). 산출 후 절대경로 + `file://` 안내.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `loop: base rubric 없음` | plugin 번들 `rubric.base.md` 부재(설치 손상) | plugin 재설치, 또는 `LOOP_RUBRIC_BASE` 로 pin |
| `score.sh: 입력 형식 오류 — ... exit 65` | checker 가 findings 파일(`${TMPDIR:-/tmp}/loop-review-findings-{repo}-{branch-cksum}.json`)을 못 썼거나 형식오류 | checker 프롬프트에 findings 출력 경로를 넘겼는지 + 스핀 전 `: > "$F"` 로 비웠는지 확인. `[ -s "$F" ]` 가드가 먼저 잡는다. 멈추고 보고 — PASS 로 넘기지 말 것 |
| `[ -s "$F" ]` 가 거짓 "checker 실패" | Step 2 와 Step 3 사이에 브랜치를 바꿔 F 재유도가 어긋남 | 리뷰가 도는 동안 그 체크아웃의 브랜치를 바꾸지 않는다 |
| `loop: 'jq' 필요` | jq 미설치 | `brew install jq` |
| 모든 finding 이 CRITICAL 로 뜸 | checker 가 dimension 을 5값 밖으로 오타 | score.sh 가 모르는 dimension 을 보수적으로 CRITICAL 처리. checker 출력의 dimension 값 점검 |

## Non-Goals

- 루프·재시도·코드 수정 — 이 입구는 1회 점검+보고. 무인 자동 반복은 agent 프로젝트의 드라이버(human-on-the-loop).
- lesson → ANTIPATTERNS 반영 — 별 스킬(`/loop-lessons`)이 사람 승인 게이트로 처리.
- severity 를 LLM 이 매기는 것 — 결정론 셸이 매긴다(같은 코드 = 같은 등급).
