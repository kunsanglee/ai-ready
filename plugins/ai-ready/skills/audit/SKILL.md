---
name: audit
description: 저장소를 AI 에이전트로 작업하기 좋은 상태인지 점검해 점수 없는 빈틈 보고서를 만든다. 스크립트가 사실(루트·모듈 AGENTS.md·CLAUDE.md 와 그 구조, git 이 무시하는 생성 대상 경로, docs/design 결정 기록, 검증 문서, lint·타입체커·테스트·아키텍처 테스트·pre-commit·CI 설정, CI 가 그 검사를 실제로 돌리는지, 문서 속 규칙 문장)을 모으고, 모델이 규칙 문장마다 이미 강제됨 / 싸게 강제 가능 / 강제 불가 / 코드와 어긋남 으로 나눠 권고를 낸다. Use when the user asks for an ai-ready audit, AI 준비도 점검, 에이전트용 문서 점검, "which of our documented rules are actually enforced", "문서 규칙 중 lint 로 옮길 것", "CI 가 테스트를 돌리나", module CLAUDE.md gaps, or a gap report before running ai-ready:apply.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/*)
---

# ai-ready audit — 빈틈 보고서

에이전트가 이 저장소에서 일할 때 필요한 문서와 강제 수단이 있는지, 문서에 적힌 규칙 중 무엇이 이미 도구로
강제되고 무엇이 문서에만 있는지를 사실로 보여 준다. 점수는 매기지 않는다.

기준은 하나다. **강제할 수 있는 규칙은 lint·타입·테스트·CI·hook 으로 잡고, 문서에는 강제할 수 없는 것(왜·의도·
어디에 무엇이 있나)만 남긴다.** 강제 수단은 강한 것부터 고른다.

1. 잘못된 상태를 타입·구조로 표현할 수 없게 만든다.
2. CI 에서 실패하는 lint·금지 API 규칙.
3. 정석 헬퍼(옳은 길을 하나로 만들어 둔 함수·모듈).
4. 런타임 검사.
5. 테스트.
6. 마지막으로 문서.

## 만드는 것

대상 저장소의 `.ai-ready/` 아래 두 파일만 쓴다. 소스·문서·설정은 건드리지 않는다.

| 파일 | 누가 쓰나 | 내용 |
|---|---|---|
| `.ai-ready/gaps.md` | `scripts/audit.py` | 사실 세 절: 문서 존재 · 강제 수단 · 규칙 문장 목록 |
| `.ai-ready/audit-report.md` | 모델(이 스킬) | 규칙 문장 A/B/C/D 분류 표와 권고. `ai-ready:apply` 가 이 파일을 읽는다 |

## 실행

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/audit.py --target <T> --out <T>/.ai-ready/gaps.md
```

- 스크립트 경로는 이미 절대 경로로 풀려 있으니 그대로 쓴다. `<T>` 는 대상 저장소 절대 경로다.
- 이 꼴 그대로 한 줄로 부른다. 스킬이 미리 허용한 명령은 audit 스크립트 폴더의 `python3 ...` 실행뿐이다. 변수 대입·
  `cd ... &&`·`set -euo pipefail`·`{ ...; exit ...; }` 묶음을 앞에 붙이면 이 허용에 맞지 않아 권한 확인에 걸린다.
- 허용은 이 스킬을 부른 턴에만 있고 하위 에이전트에게 넘어가지 않는다. 스크립트는 메인 에이전트가 같은 턴에 돌린다.
- `echo $?` 를 이어 붙이지 않는다. 스크립트가 실패하면 이유와 `종료 코드 N` 을 stderr 에 출력한다.

- 규칙 문장은 기본 400줄에서 자른다. 잘렸다고 보고서 끝에 적히면 `--max-rules` 로 늘린다. 잘릴 때는 루트·모듈의
  `CLAUDE.md`/`AGENTS.md` → `docs/` → 나머지 → `.claude/` 같은 도구 폴더 순으로 남는다.
- `--json` 을 주면 같은 사실을 JSON 으로 낸다. 표가 너무 길어 읽기 어려울 때 쓴다.

## 스크립트가 보는 것

**1. 문서 존재** — 있음·없음·길이 과다와 문서 구조를 적는다.

- 루트 문서(8,000바이트를 넘으면 길이 과다)와 모듈별 문서(80줄을 넘으면 길이 과다). 모듈은 아래 "모듈을 어떻게
  정하나" 로 정한다. 길이는 본문이 든 파일로 잰다(`@AGENTS.md` 한 줄짜리 `CLAUDE.md` 가 아니라 `AGENTS.md`).
- 문서 구조. 기본값은 `AGENTS.md` 가 원본(일반 파일)이고 옆의 `CLAUDE.md` 가 `@AGENTS.md` 한 줄로 그것을 가져오는
  구조다. Claude Code 는 한 폴더에 둘이 있으면 `CLAUDE.md` 만 읽고, 가져오기 경로는 가져오는 파일 기준으로 푼다.
  옛 구조(`CLAUDE.md` 원본 + `AGENTS.md` 심볼릭 링크)나, 가져오기 없이 두 파일이 따로 있는 구조는 **전환 제안**으로
  적는다. 스크립트도 apply 도 이 전환을 자동으로 하지 않는다.
- git 이 무시하는 생성 대상 경로. apply 가 만들 `AGENTS.md`·`CLAUDE.md`(루트·모듈), `docs/…`, `scripts/verify.sh`
  등을 `git check-ignore` 로 확인한다. 무시되면 만들어도 커밋되지 않고, 커밋된 옆 문서의 가져오기가 깨진다.
- `docs/design/{domain}.md` ↔ `{domain}.decisions.md` 짝, `docs/design/README.md`,
  `.gitattributes` 의 `docs/design/*.decisions.md merge=union`
- 검증 문서(`docs/VERIFICATION.md`), `scripts/verify.sh`, `scripts/check_docs.py`, Stop hook 이 verify.sh 를
  부르는지, 안티패턴 원장(`docs/ANTIPATTERNS.md`)

**2. 강제 수단**

- 설정 파일·매니페스트로 감지한 lint·formatter·타입체커·테스트 러너·아키텍처 테스트(ArchUnit·Konsist·
  dependency-cruiser·eslint-plugin-boundaries·import-linter·go-arch-lint 등)
- 매니페스트에서 추론한 typecheck·lint·test 명령
- **CI 가 그 검사를 실제로 부르는지.** CI 설정 파일(GitHub Actions·GitLab·Bitbucket Pipelines·Jenkinsfile 등) 안에서
  명령 줄을 찾아 `예`·`아니오`·`간접`·`아니오(제외됨)` 으로 적는다. `간접` 은 `./gradlew build` 처럼 그 검사를 포함할
  수 있는 상위 태스크만 보인다는 뜻이라 사람이 확인해야 한다. `test` 같은 맨 태스크 이름은 러너(gradlew·mvn·npm·
  pytest·go·cargo·make 등)를 부르는 줄에서만 찾고, 같은 줄의 `-x test`·`-DskipTests` 가 그 태스크를 빼면
  `아니오(제외됨)` 이다. CI 설정이 저장소에 없으면 `CI 없음` 이다(저장소 밖 Jenkins 등은 스크립트가 볼 수 없다)
- CI·Dockerfile 에서 테스트를 빼거나 실패를 삼키는 줄: `-x test`, `-DskipTests`, `continue-on-error: true`,
  `allow_failure: true`, `|| true`, `--no-verify`
- pre-commit 류(`.pre-commit-config.yaml`·husky·lefthook)와 `.claude/settings.json` 의 hook. hook 이 가리키는
  스크립트가 없으면 따로 표시한다

**3. 규칙 문장** — "금지·반드시·하지 마·must·never·DO NOT" 같은 표현이 든 줄과, 제목에 "규칙·원칙·금지·
안티패턴·rules" 가 든 절 아래의 목록 항목을 `파일:줄` 로 뽑는다. 코드 블록 안은 뺀다. **분류는 하지 않는다.**

### 모듈을 어떻게 정하나 (`scripts/stacks.py`)

루트가 아닌 디렉토리에 빌드 매니페스트(`build.gradle(.kts)`·`pom.xml`·`package.json`·`Cargo.toml`·`go.mod`·
`pyproject.toml`·`setup.py`)가 있으면 그 디렉토리들이 모듈이다. 루트에만 있으면 스택 어댑터가 찾은 소스 기준점의
직속 하위 디렉토리가 모듈이다.

| 스택 | 감지 | 기준점 |
|---|---|---|
| `jvm` | `src/main/kotlin` 또는 `src/main/java` | `*Application.kt`·`*Application.java` 가 있는 패키지. 없으면(라이브러리) 패키지가 갈라지는 곳 |
| `node` | 루트 `package.json` | `src/`·`lib/`·`app/` 중 먼저 있는 것 |
| `python` | `pyproject.toml`·`setup.py`·`setup.cfg` | `src/` 아래 배포 패키지, 또는 `__init__.py` 가 있는 루트 패키지 하나 |
| `go` | `go.mod` | `internal/` 또는 `pkg/`, 없으면 모듈 루트 |
| `rust` | `Cargo.toml` | `src/` |

같은 판단을 `audit.py` 와 `scaffold.py` 가 함께 쓴다. 스택을 늘리려면 `stacks.py` 의 `ADAPTERS` 에 한 줄을 더한다.

## 모델이 할 일 — 규칙 분류와 권고

`gaps.md` 를 읽은 뒤, 3절의 규칙 줄마다 아래 넷 중 하나로 나눈다. **문장만 보고 정하지 않는다.** A 와 D 는 코드·
설정을 `Grep`/`Read` 로 확인한 근거가 있어야 하고, 확인하지 못했으면 "확인 필요" 로 남긴다.

한 줄에 규칙이 여럿 들어 있으면 `R4a`·`R4b` 처럼 나눠 행을 따로 두고, 행마다 A/B/C/D 중 **하나만** 붙인다.
`A/C`·`B+D` 같은 섞인 라벨은 쓰지 않는다. apply 가 행 하나를 승인 단위로 삼기 때문이다.

| 분류 | 뜻 | 근거로 적을 것 | 권고 |
|---|---|---|---|
| **A 이미 강제됨** | lint 규칙·테스트·타입·CI 가 이미 이 규칙을 어기면 실패한다 | 규칙 이름이나 테스트 경로, 그리고 CI 가 그것을 돌리는지(2절) | 문서에서는 본문을 줄이고 "→ <규칙·테스트>" 한 줄만 남긴다. CI 가 안 돌리면 그 사실을 따로 권고 |
| **B 싸게 강제 가능** | 이 스택의 도구로 규칙 하나·테스트 하나를 더하면 강제된다 | 쓸 도구와 규칙 종류(예: eslint `no-restricted-imports`, ArchUnit 의존 규칙, ruff `banned-api`) | 강제 초안 후보. `ai-ready:apply` 가 초안을 만든다 |
| **C 강제 불가** | 의도·트레이드오프·판단이 필요해 도구로 잡을 수 없다 | 왜 도구로 못 잡는지 한 줄 | 문서에 남긴다. 모듈 `AGENTS.md` 의 "강제할 수 없는 규칙" 이나 안티패턴 원장에, 이유와 함께 |
| **D 어긋남·낡음** | 코드가 이미 규칙과 다르게 되어 있거나, 규칙이 가리키는 파일·API 가 없다 | 어긋난 코드 위치(`파일:줄`) | 수정 후보. 문서를 고칠지 코드를 고칠지는 사람이 정한다 |

같은 규칙이 여러 문서에 되풀이되면 한 번만 분류하고 위치를 모두 적는다. 규칙이 아닌 줄(설명·이력·인용)이 섞여
있으면 "규칙 아님" 으로 빼고 넘어간다.

### `audit-report.md` 형식

```markdown
# ai-ready 점검 결과 — <대상>

## 빈틈 요약
- (gaps.md 1·2절에서 중요한 것부터: 없는 문서, git 이 무시하는 생성 대상 경로, CI 가 돌리지 않는 검사,
  테스트 제외 줄, 깨진 hook)

## 규칙 분류
| ID | 위치 | 규칙(요약) | 분류 | 근거 | 권고 |
|---|---|---|---|---|---|
| R3 | `AGENTS.md:12` | ... | B | eslint no-restricted-imports 로 잡힌다 | 강제 초안 |
| R4a | `AGENTS.md:15` | (한 줄의 첫째 규칙) | A | ... | ... |
| R4b | `AGENTS.md:15` | (같은 줄의 둘째 규칙) | C | ... | ... |

## 권고
1. B — 강제 초안 후보 (도구·규칙 이름)
2. D — 수정 후보 (위치)
3. 없는 문서·장치 (apply 가 만들 것)
4. 문서 구조 전환 제안 (옛 구조가 있을 때만. 자동으로 바꾸지 않는다)

## 보류
- (이번 실행에서 확인하지 못한 것: 권한 거부·도구 없음으로 돌리지 못한 명령과 그 이유)
```

보고서를 쓴 뒤 사용자에게는 빈틈 요약과 분류별 개수, B·D 상위 항목만 짧게 알리고, 다음 단계로
`ai-ready:apply` 를 안내한다.

비대화 실행(`claude -p` 처럼 사람이 중간에 답할 수 없는 실행)에서는 사람에게 `!` 로 명령을 대신 돌려 달라고
요청하지 않는다. 돌리지 못한 명령은 이유와 함께 보고서의 "보류" 절에 적고 넘어간다.

## 하지 않는 것

- 점수·등급을 매기지 않는다. 문서 개수로 품질을 말하지 않는다.
- `.ai-ready/` 밖에 쓰지 않는다. hook 설치·CI 수정·문서 수정은 `ai-ready:apply` 에서 사람이 승인한 뒤에 한다.
- 규칙 분류를 스크립트나 정규식에 맡기지 않는다. 스크립트는 후보 줄만 모은다.
