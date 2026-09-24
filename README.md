# ai-ready

AI 에이전트가 일하기 좋은 저장소를 만들고 유지하는 Claude Code 플러그인입니다.

기준은 하나입니다. **강제할 수 있는 규칙은 lint·타입·테스트·CI·hook 으로 잡고, 문서에는 강제할 수 없는 것(왜·의도·
어디에 무엇이 있나)만 남깁니다.** 에이전트는 문서를 읽고도 규칙을 놓칠 수 있지만, CI 에서 실패하는 lint 규칙은
놓칠 수 없습니다. 그래서 규칙이 문서에만 있으면 먼저 도구로 옮길 수 있는지 따지고, 옮길 수 없는 것만 이유와 함께
문서에 둡니다.

| 스킬 | 하는 일 |
|---|---|
| `ai-ready:audit` | 점수 없는 빈틈 보고서. 문서가 있나, 검사 도구가 있고 CI 가 실제로 돌리나, 문서 속 규칙이 이미 강제되나 |
| `ai-ready:apply` | 보고서에서 사람이 고른 것만 만든다. 짧은 루트 `AGENTS.md`(원본)와 그것을 `@AGENTS.md` 한 줄로 가져오는 `CLAUDE.md`, 모듈 `AGENTS.md`·`CLAUDE.md`, 결정 기록, 안티패턴 원장, 검증 문서와 `verify.sh`, Stop hook, 문서 정합 검사, lint·아키텍처 테스트 초안 |
| `ai-ready:lessons` | 작업 중 사람이 바로잡은 실수와 PR 리뷰 코멘트를 강제 초안이나 문서 항목 초안으로 만들고, 하나씩 승인받아 반영한다 |

---

## 설치

### 1. 마켓플레이스 등록

```
/plugin marketplace add kunsanglee/ai-ready
```

### 2. 플러그인 설치

```
/plugin install ai-ready@ai-ready
```

### 3. 업데이트

```
/plugin marketplace update ai-ready
```

### 설치 확인

```
/plugin list
```

> Claude Code 는 `plugin.json` 의 `version` 필드가 바뀐 경우에만 새 버전으로 인지합니다. 이 저장소는 매 릴리스에
> 버전을 올립니다. 설치된 버전은 `/plugin list` 로, 최신 버전은 [CHANGELOG.md](CHANGELOG.md) 첫 항목으로 확인합니다.

### 1.x 에서 올라올 때

2.0.0 은 무인 검증 loop(`spec`·`build`·`review`)와 7개 영역 점수를 없앴습니다. 1.x 가 대상 저장소에 깔아 둔
freshness hook 과 `.ai-ready/` 설정이 남아 있으면 없는 스크립트를 가리키게 됩니다. 옮기는 순서는
[CHANGELOG.md](CHANGELOG.md) 의 2.0.0 항목에 있습니다.

## 요구사항

로컬 셸, git, python3 만 있으면 됩니다. 스크립트는 표준 라이브러리만 씁니다. 외부 서비스 인증은 필요 없습니다.
PR 코멘트를 읽을 때만 GitHub CLI(`gh`)를 쓰고, 없으면 코멘트를 붙여 넣으면 됩니다.

---

## 쓰는 순서

```
ai-ready:audit  →  (보고서 읽기)  →  ai-ready:apply  →  (작업)  →  ai-ready:lessons
```

### `ai-ready:audit` — 빈틈 보고서

스크립트가 사실을 모으고, 모델이 규칙을 나눕니다. 대상 저장소의 `.ai-ready/` 아래 두 파일만 씁니다.

- `.ai-ready/gaps.md` (스크립트)
  1. **문서 존재** — 루트·모듈별 `AGENTS.md`·`CLAUDE.md`(길이 과다 표시)와 둘의 구조, git 이 무시하는 생성 대상
     경로(`git check-ignore`), `docs/design` 의 결정 기록 쌍과 union merge 설정, 검증 문서, `verify.sh`, Stop hook,
     안티패턴 원장. 옛 구조(`CLAUDE.md` 원본 + `AGENTS.md` 심볼릭 링크)는 전환 제안으로만 적고 바꾸지 않습니다
  2. **강제 수단** — 감지된 lint·formatter·타입체커·테스트 러너·아키텍처 테스트·pre-commit·CI 설정, 그리고 CI
     설정 안에서 그 검사를 실제로 부르는 줄. CI·Dockerfile 에서 테스트를 빼거나(`-x test`, `-DskipTests`) 실패를
     삼키는(`|| true`, `continue-on-error`) 줄
  3. **규칙 문장** — 문서에서 "금지·반드시·must·never" 같은 줄을 `파일:줄` 로
- `.ai-ready/audit-report.md` (모델) — 규칙 줄마다 넷 중 하나로 나누고 코드·설정에서 근거를 찾아 적습니다.

| 분류 | 뜻 | 권고 |
|---|---|---|
| A 이미 강제됨 | 어기면 lint·테스트·CI 가 실패한다 | 문서는 "→ <규칙>" 한 줄로 줄인다 |
| B 싸게 강제 가능 | 규칙·테스트 하나를 더하면 된다 | apply 가 강제 초안을 만든다 |
| C 강제 불가 | 의도·판단이 필요하다 | 이유와 함께 문서에 남긴다 |
| D 어긋남·낡음 | 코드가 이미 다르거나 가리키는 것이 없다 | 수정 후보 |

점수는 매기지 않습니다. 문서 개수로 준비 상태를 말하면, 강제되지 않는 문서를 더 쓰는 쪽으로 기울기 때문입니다.

### `ai-ready:apply` — 승인한 것만

| 만드는 것 | 내용 |
|---|---|
| 루트 `AGENTS.md` + `CLAUDE.md` | `AGENTS.md` 가 원본이다: 확인 명령, 문서 지도(이럴 때 → 이 문서), 강제할 수 없는 규칙. 짧게 둔다. `CLAUDE.md` 는 `@AGENTS.md` 한 줄로 그것을 가져온다 |
| 모듈 `AGENTS.md` + `CLAUDE.md` | 이 모듈이 하는 일 / 경계 / 변경 방법 / 강제할 수 없는 규칙(왜) / 강제되는 규칙(포인터만). 최근 변경이 잦은 모듈부터 몇 개만 |
| `docs/design/{domain}.md` + `{domain}.decisions.md` | 지금 동작은 고쳐 쓰고, 결정은 카드를 맨 위에 더한다. 카드 제목은 `## 제목 · (티켓) · [accepted\|proposed\|rejected\|superseded]`, 읽을 때는 `grep -n '^## '`. `.gitattributes` 의 `merge=union` 으로 병합 충돌을 피한다 |
| `docs/ANTIPATTERNS.md` | 빈 원장과 항목 형식(DO NOT / 이유 / 대신 / 강제 수단 또는 강제 불가 / 출처) |
| `docs/VERIFICATION.md` + `scripts/verify.sh` | 매니페스트에서 추론한 typecheck·lint·test 를 차례로 돌린다. 실패하면 마지막 20줄만 보여 준다. 작업 트리가 마지막 통과 때와 같으면 다시 돌리지 않는다 |
| Stop hook | `verify.sh` 가 통과한 기록이 남아 있을 때만(실패하면 기록을 지운다) `.claude/settings.json` 에 `verify.sh --stop-hook` 을 병합한다. 실패하면 에이전트가 턴을 끝내지 못한다. 같은 작업 트리로 3번 막은 뒤에는 검사를 다시 돌리지 않고 통과시키고, 트리가 바뀌면 다시 센다 |
| `scripts/check_docs.py` | 깨진 상대 링크, 결정 카드 제목 형식, union merge 로 생긴 중복 카드, frontmatter 필수 키. CI 에 한 줄로 넣는다 |
| 강제 초안 | audit 의 B 항목을 ArchUnit·detekt·eslint(`no-restricted-imports`)·dependency-cruiser·ruff(`banned-api`)·import-linter·clippy 규칙이나 테스트로. 오류 메시지에 "대신 X" 를 넣고, 기존 위반은 기준 파일로 묶는다 |

서명이 없는(사람이 관리하는) 파일과, 서명을 남긴 채 고친 초안은 덮어쓰지 않습니다. 초안의 서명 줄에는 본문 해시가
들어 있어 고쳤는지 알 수 있습니다. 그런 파일이 있으면 스크립트가 아무것도 쓰지 않고 멈추고, 그 파일은 필요한 부분만
고친 diff 로 제안합니다. 초안을 다시 만들고 싶으면 파일을 지우고 돌립니다. 만들 원본 파일(`AGENTS.md`·`docs/`·
`scripts/`)이 git 에서 무시되거나 심볼릭 링크일 때도 아무것도 쓰지 않고 멈춥니다. 무시되는 것이 `@AGENTS.md` 한
줄짜리 `CLAUDE.md` 뿐이면 그 파일만 건너뜁니다.

`AGENTS.md` 를 원본으로 두고 `CLAUDE.md` 에서 가져오는 까닭은 [Claude Code 문서](https://code.claude.com/docs/en/memory)에
있습니다. 한 폴더에 둘이 있으면 Claude Code 는 `CLAUDE.md` 만 읽고, `@AGENTS.md` 가져오기를 권하며, 가져오기 경로는
가져오는 파일 기준으로 풉니다. 심볼릭 링크는 Windows 클론과 Edit·Write 도구에서 제약이 있어 쓰지 않습니다.

### `ai-ready:lessons` — 교훈을 강제 수단이나 문서로

```
/lessons           # 이 세션에서 사람이 바로잡은 것으로
/lessons 123       # PR #123 의 리뷰 코멘트도 함께
```

`lesson-synthesizer` 에이전트(읽기 전용)가 후보마다 먼저 도구로 막을 수 있는지 따져 강제 초안을 내고, 안 되면
이유를 붙인 안티패턴 원장 항목을, 설계 결정이면 결정 카드를 냅니다. 스킬이 후보를 하나씩 보여 주고 승인받은 것만
반영합니다.

---

## 강제 수단을 고르는 순서

1. 잘못된 상태를 타입·구조로 표현할 수 없게 만든다.
2. CI 에서 실패하는 lint·금지 API 규칙.
3. 정석 헬퍼(옳은 길을 함수 하나로 만들고, 다른 길은 2번으로 막는다).
4. 런타임 검사.
5. 테스트.
6. 마지막으로 문서.

## 모듈을 어떻게 정하나

루트가 아닌 디렉토리에 빌드 매니페스트(`build.gradle(.kts)`·`pom.xml`·`package.json`·`Cargo.toml`·`go.mod`·
`pyproject.toml`·`setup.py`)가 있으면 그 디렉토리들이 모듈입니다. 루트에만 있으면 스택 어댑터가 찾은 소스 기준점의
직속 하위 디렉토리가 모듈입니다.

| 스택 | 기준점 |
|---|---|
| JVM (Kotlin·Java) | `*Application.kt\|java` 가 있는 패키지. 없으면 패키지가 갈라지는 곳 |
| Node | `src/`·`lib/`·`app/` |
| Python | `src/` 아래 배포 패키지, 또는 `__init__.py` 가 있는 루트 패키지 |
| Go | `internal/` 또는 `pkg/` |
| Rust | `src/` |

---

## 저장소 구조

```
.
├── .claude-plugin/marketplace.json
├── plugins/ai-ready/                     # Claude Code 플러그인
│   ├── .claude-plugin/plugin.json
│   ├── skills/
│   │   ├── audit/                        # 빈틈 보고서 + 공용 스크립트
│   │   │   └── scripts/
│   │   │       ├── audit.py              # gaps.md
│   │   │       ├── stacks.py             # 모듈 기준점 · 확인 명령 추론
│   │   │       ├── scaffold.py           # 모듈 AGENTS.md 초안 + 가져오는 CLAUDE.md
│   │   │       ├── bootstrap.py          # 루트 문서 · 결정 기록 · 원장 · 검증 문서 초안
│   │   │       ├── install_verify_hook.py
│   │   │       ├── managed_doc.py        # 사람이 관리하는 파일을 덮지 않는 규칙
│   │   │       └── project/              # 대상 저장소로 복사되는 verify.sh · check_docs.py
│   │   ├── apply/                        # + references/enforcement-drafts.md
│   │   └── lessons/
│   ├── agents/lesson-synthesizer.md
│   └── tests/                            # stdlib unittest
└── build/drift-test.sh                   # 매니페스트 버전·변경 이력·셸 함정 검사
```

시험은 `plugins/ai-ready` 에서 `python3 -m unittest discover -s tests -t .`, 그리고 저장소 루트에서
`bash build/drift-test.sh` 입니다.

실제 세션으로 확인할 때는 대상 저장소를 `~/.claude` 밖 경로(예: `/tmp/ai-ready-e2e/`)에 복사해 두고
`claude -p --plugin-dir <이 저장소>/plugins/ai-ready ...` 로 돌립니다. `~/.claude` 아래에서 돌리면 권한 검사가 그
경로의 쓰기를 따로 막아 결과가 실제 사용과 달라집니다.

---

릴리스마다 무엇이 왜 바뀌었는지는 [CHANGELOG.md](CHANGELOG.md) 에 있습니다.

## 라이선스

MIT
