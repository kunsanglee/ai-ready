# looping review — 1회 점검 보고서 (서브커맨드)

> 우산 스킬 `looping` 의 `review` 동작. 호출: `/looping review [--html]`. 디스패처는 같은 폴더 [`SKILL.md`](SKILL.md).

무인 검증 loop 의 **사람 입구**다. 무인 드라이버가 돌리는 것과 **똑같은 단일 checker(`loop-checker`) + 결정론 채점 셸**을 사람이 한 번 돌려, 등급순 보고서를 받는다. 루프가 아니다 — checker 1회 → 채점 → 보고서로 끝난다. 무엇을 고칠지는 사람이 정한다.

## 🤝 팀 공유 버전 안내

- 이 스킬은 `.claude/skills/` 의 팀 공유 자산(projectSettings, 최우선)이다.
- 의존: `.claude/agents/loop-checker.md`(점검), `.claude/skills/_loop-engine/`(채점 셸 `score.sh`·`decide.sh`), `docs/loop/rubric.md`(루브릭 데이터). 셋 다 같은 레포에 커밋돼 있어 별도 셋업 불필요.
- 환경변수·외부 인증 없음(전부 로컬 git + 셸).

## `/code-review` 와 차이

| | `/looping review` | `/code-review` |
|---|---|---|
| 점검자 | 단일 `loop-checker` 1회 | 5개 전문 에이전트 병렬 |
| severity | 결정론 셸(rubric) — 같은 코드 = 같은 등급 | 각 에이전트가 매김 |
| 쓰임 | 무인 loop 와 동일 판정을 사람이 미리 봄 | 폭넓은 다관점 진단 |

둘은 보완재다. 무인 loop 에 올릴 코드를 그 loop 의 판정 기준으로 미리 보고 싶으면 `/looping review`, 다관점 깊이 진단이면 `/code-review`.

## 호출 예시

```
/looping review              # 현재 브랜치 origin/main..HEAD + uncommitted 점검 → markdown 보고서
/looping review --html       # 같은 보고서를 자체완결 HTML 파일로
```

## 작업 흐름

### Step 1. 스코프·작업 정의 파악

```bash
git fetch origin main --quiet
git diff origin/main...HEAD --stat   # 브랜치에서 커밋된 전체 변경
git diff --stat                      # uncommitted (unstaged)
git diff --staged --stat             # uncommitted (staged)
```

세 diff 의 파일 합집합이 점검 범위다. 대화/티켓에서 원래 작업 정의를 1~3문장으로 요약한다(없으면 "작업 정의 없음" — checker 가 동작 보존+범위 일탈로 좁혀 본다).

### Step 2. loop-checker 1회 호출 (독립 시선)

`Agent` 툴로 `loop-checker` 를 **한 번** 호출한다. 프롬프트에 넘기는 것은 이것만:

- 원래 작업 정의(Step 1 요약, 1~3문장).
- 작업 정의 문서 경로(있으면 design/티켓 경로, 없으면 "missing").
- 비교 베이스: `origin/main`.

**maker(이 세션)의 합리화·구현 변명을 checker 프롬프트에 넣지 마라.** checker 는 diff·문서·ANTIPATTERNS 만 보고 독립적으로 판단한다(분리 강제). checker 는 자기 도구(Read/Grep/Glob/Bash)로 diff 와 컨벤션 문서를 직접 읽는다.

checker 는 마지막에 정확히 하나의 ```json 펜스 블록으로 `{base, findings:[...]}` 를 낸다. 그 블록만 추출한다.

### Step 3. 결정론 채점 (score → decide)

추출한 JSON 을 임시 파일에 저장하고 채점 셸에 흘린다. **severity 는 셸이 매긴다 — checker 가 낸 등급을 쓰지 않는다(애초에 checker 는 등급을 안 낸다).**

```bash
F=$(mktemp)                                  # checker JSON 저장
# (위에서 추출한 {base,findings:[...]} 를 $F 에 기록)
SCORED=$(bash .claude/skills/_loop-engine/score.sh "$F")    # finding 마다 severity·await·base·kind_known 추가
VERDICT=$(printf '%s' "$SCORED" | bash .claude/skills/_loop-engine/decide.sh)   # verdict·counts·await 집계
rm -f "$F"
```

- `$SCORED` = `{base, findings:[{..., severity, await, base, kind_known}]}`.
- `$VERDICT` = `{verdict, counts:{BLOCKER,CRITICAL,MAJOR,MINOR}, await}`.
- 셸이 `exit 65` 로 죽으면(빈/형식오류 입력) checker JSON 추출이 실패한 것이다 — 조용히 PASS 로 넘기지 말고 사용자에게 "checker 출력 파싱 실패"로 보고하고 멈춘다.

verdict 의미(rubric): `AWAIT_USER`(BLOCKER 또는 force_await — 사람만 처리), `RETRY`(CRITICAL≥1 — 무인 loop 면 maker 재진입감), `RETRY_SOFT`(MAJOR≥1 — 정체 시 사람 승인으로 통과 가능), `PASS`(MINOR 만/깨끗).

### Step 4. 보고서 조립 (등급 내림차순)

`$SCORED` 의 findings 를 severity 내림차순(BLOCKER>CRITICAL>MAJOR>MINOR)으로 정렬해 보고서를 만든다. 기본은 markdown.

```
## looping review 결과

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

`/code-review` 의 HTML 모드 규약을 그대로 따른다: 외부 의존성 없는 자체완결 단일 HTML 1개(CDN✗, inline `<style>`+`<script>`만), 경로 `/tmp/looping-review-{branch-slug}-{HHMMSS}.html`, 상단 verdict·counts 요약 카드, finding 카드(severity 색상 바 BLOCKER=red·CRITICAL=red·MAJOR=orange·MINOR=yellow, 파일경로 monospace, 복사 버튼), 인용 라인 외 코드 본문 복사 금지(라인+경로만). 산출 후 절대경로 + `file://` 안내.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `loop: rubric 없음` | `docs/loop/rubric.md` 부재(워크트리 누락) | 레포 루트에서 호출, 또는 `LOOP_RUBRIC_MD` 로 pin |
| `score.sh: 입력 형식 오류 — ... exit 65` | checker JSON 추출 실패(빈/null/형식오류) | checker 출력의 마지막 ```json 블록만 정확히 추출했는지 확인. 멈추고 보고 — PASS 로 넘기지 말 것 |
| `loop: 'jq' 필요` | jq 미설치 | `brew install jq` |
| 모든 finding 이 CRITICAL 로 뜸 | checker 가 dimension 을 5값 밖으로 오타 | score.sh 가 모르는 dimension 을 보수적으로 CRITICAL 처리. checker 출력의 dimension 값 점검 |

## Non-Goals

- 루프·재시도·코드 수정 — 이 입구는 1회 점검+보고. 무인 자동 반복은 agent 프로젝트의 드라이버(human-on-the-loop).
- lesson → ANTIPATTERNS 반영 — 별 스킬(`/looping lessons`)이 사람 승인 게이트로 처리.
- severity 를 LLM 이 매기는 것 — 결정론 셸이 매긴다(같은 코드 = 같은 등급).
