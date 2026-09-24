---
name: apply
description: ai-ready:audit 의 빈틈 보고서(.ai-ready/gaps.md, audit-report.md)를 읽고, 사람이 승인한 것만 적용한다. 없는 문서의 초안(짧은 루트 AGENTS.md 와 그것을 가져오는 CLAUDE.md, 모듈 AGENTS.md, docs/design 결정 기록 쌍, 안티패턴 원장, 검증 문서), 문서 정합 검사 스크립트, scripts/verify.sh 와 Claude Code Stop hook, 그리고 문서에만 있던 규칙을 lint·아키텍처 테스트로 옮기는 강제 초안(ArchUnit, eslint no-restricted-imports, dependency-cruiser, ruff banned-api, import-linter, detekt 등)을 만든다. Use when the user asks to apply ai-ready audit results, "문서 규칙을 lint 로 옮겨", create verify.sh or a Stop hook that runs checks, set up docs/design decision records, or scaffold module AGENTS.md/CLAUDE.md files.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/*) Bash(python3 scripts/check_docs.py*) Bash(bash scripts/verify.sh*)
---

# ai-ready apply — 승인한 것만 적용

`ai-ready:audit` 결과를 읽어, 없는 문서와 검증 장치를 만들고 문서에만 있던 규칙을 도구로 옮긴다. 파일 하나,
규칙 하나마다 사람이 승인한 뒤에 쓴다.

기준은 audit 과 같다. 강제할 수 있는 규칙은 도구로 옮기고, 문서에는 강제할 수 없는 것(왜·의도·지도)만 남긴다.

## 준비

스크립트는 audit 스킬 폴더(`${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/`)에 있다. 아래 명령의 경로는 이미 절대
경로로 풀려 있으니 그대로 쓴다. `<T>` 는 대상 저장소 절대 경로다.

- 명령은 이 문서에 적힌 꼴 그대로 한 줄로 부른다. 스킬이 미리 허용한 명령은 셋뿐이다: audit 스크립트 폴더의
  `python3 ...` 실행, 대상 저장소를 작업 폴더로 둔 `python3 scripts/check_docs.py`, `bash scripts/verify.sh`.
  변수 대입·`cd ... &&`·`set -euo pipefail`·`{ ...; exit ...; }` 묶음을 앞에 붙이면 이 허용에 맞지 않아 권한 확인에
  걸린다.
- `echo $?` 를 이어 붙이지 않는다. 스크립트가 실패하면 이유와 `종료 코드 N` 을 stderr 에 출력한다.
- 비대화 실행(`claude -p` 처럼 사람이 중간에 답할 수 없는 실행)에서는 사람에게 `!` 로 명령을 대신 돌려 달라고
  요청하지 않는다. 돌리지 못한 명령과 적용하지 못한 항목은 이유와 함께 "보류" 로 마무리 보고에 적는다.

**허용은 이 스킬을 부른 턴에만 있다.** `allowed-tools` 의 허용은 스킬을 부른 턴이 끝나면 사라지고, 이 스킬이 띄운
하위 에이전트에게는 넘어가지 않는다.

- 이 스킬 흐름 안에서 하위 에이전트를 백그라운드로 띄우지 않는다. 결과를 기다리는 동안 턴이 끝나면 뒤의 스크립트
  실행이 권한 확인에 걸린다.
- 스크립트 실행(audit.py·bootstrap.py·scaffold.py·install_verify_hook.py, `check_docs.py`, `verify.sh`, 마무리의
  audit 재실행)은 메인 에이전트가 같은 턴 안에서 끝낸다. 하위 에이전트에 넘기지 않는다.
- 하위 에이전트에 코드 읽기를 맡길 때는 프롬프트에 "Read/Grep/Glob 을 쓰고 셸 명령을 묶어 쓰지 않는다" 를 넣는다.
- 턴이 끝난 뒤에 남은 확인(돌리지 못한 스크립트 등)은 다음 턴에 몰래 이어 하지 않고 보류로 적는다.

1. `<T>/.ai-ready/gaps.md` 와 `audit-report.md` 가 없으면 `ai-ready:audit` 을 먼저 안내하고 멈춘다.
2. 커밋하지 않은 변경이 있으면 알리고, 계속할지 묻는다.
3. `audit-report.md` 에서 할 일을 뽑아 **계획 표**로 보여 준다: 항목 · 만들거나 고칠 파일 · 방법(스크립트 / 모델 초안)
   · 근거(보고서의 어느 줄). 사용자가 고른 것만 진행한다. 보고서에 없던 변경은 추측으로 표에 넣지 않는다.
4. `gaps.md` 의 "git 이 무시하는 생성 대상 경로" 절에 원본 파일(`AGENTS.md`·`docs/…`·`scripts/…`)이 있으면, 무시
   규칙(`.gitignore` 등) 수정을 계획 표의 **독립 항목**으로 둔다. 고치는 방법이 여럿이면(규칙 지우기, `!` 예외 줄
   더하기, 파일을 다른 곳에 두기 등) 선택지를 따로 보여 준다. 선택지가 여럿이면 "전부 진행" 같은 일괄 승인은 그중
   무엇을 골랐는지가 아니므로 선택으로 보지 않고 다시 묻는다. 비대화 실행이면 무시 규칙은 고치지 않고 보류로 적는다.
   다리 파일(`@AGENTS.md` 한 줄짜리 `CLAUDE.md`)만 무시되는 것은 고칠 항목이 아니다(아래 1절).

## 만드는 것

### 1. 없는 문서의 초안 — `bootstrap.py`

| 종류(`--only`) | 만드는 파일 |
|---|---|
| `root` | 루트 `AGENTS.md`(원본) + `@AGENTS.md` 한 줄짜리 `CLAUDE.md`. 확인 명령, 문서 지도(이럴 때 → 이 문서), 강제할 수 없는 규칙 자리만 둔다. 서명 줄은 `AGENTS.md` 첫 줄에 있다 |
| `design` | `docs/design/README.md`(카드 형식·읽는 법), `.gitattributes` 에 `docs/design/*.decisions.md merge=union` 한 줄. `--design-domain <이름>` 을 주면 `<이름>.md`(현재 동작)와 `<이름>.decisions.md`(결정 카드)도 |
| `antipatterns` | `docs/ANTIPATTERNS.md` — 빈 원장과 항목 형식(DO NOT / 이유 / 대신 / 강제 수단 또는 강제 불가 / 출처) |
| `verification` | `docs/VERIFICATION.md`(로컬·CI·에이전트 작업 중에 무엇이 도나) + `scripts/verify.sh` |
| `doc-check` | `scripts/check_docs.py` — 깨진 상대 링크, 결정 카드 제목 형식, union merge 로 생긴 중복 카드, frontmatter 필수 키 |

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/bootstrap.py --target <T> --only root,design --dry-run
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/bootstrap.py --target <T> --only root,design
```

- 먼저 `--dry-run` 결과(무엇을 쓸지)를 보여 주고, 승인을 받은 뒤 두 번째 명령을 돌린다.
- **문서 구조.** `AGENTS.md` 가 원본이고 `CLAUDE.md` 는 `@AGENTS.md` 한 줄로 그것을 가져온다. Claude Code 는 한 폴더에
  둘이 있으면 `CLAUDE.md` 만 읽고, 가져오기 경로는 가져오는 파일 기준으로 푼다. 심볼릭 링크는 만들지 않는다(Windows
  클론에서 한 줄짜리 파일로 풀리고, Edit·Write 도구가 링크를 따라 쓰지 않는다). 이미 `@AGENTS.md` 를 가져오는
  `CLAUDE.md` 는 그대로 둔다. Claude Code 전용 지시는 그 `CLAUDE.md` 의 가져오기 줄 아래에 둔다.
- 만들 파일이 심볼릭 링크면(옛 구조: `CLAUDE.md` 원본 + `AGENTS.md` 링크) 스크립트는 아무것도 쓰지 않고 exit 3 으로
  끝난다. 전환은 audit 보고의 제안을 사람이 보고 정한다. `--force` 로 넘기지 않는다.
- git 이 무시하는 것이 다리 파일(`@AGENTS.md` 한 줄짜리 `CLAUDE.md`)뿐이면 스크립트는 그 파일만 건너뛰고 나머지를
  쓴다. 원본 `AGENTS.md` 는 커밋되고, Claude Code v2.1.277 이상은 작업 폴더와 그 위에 `CLAUDE.md` 가 없으면
  `AGENTS.md` 를 읽는다. 스크립트가 출력한 참고(건너뛴 파일, "로컬에 개인 `CLAUDE.md` 가 있는 사람은 거기에
  `@AGENTS.md` 를 넣어야 `AGENTS.md` 가 로드된다")를 그대로 보고한다.
- `AGENTS.md`·`docs/…`·`scripts/…` 같은 원본이 git 에서 무시되면 아무것도 쓰지 않고 exit 6 으로 끝나며 무시 규칙의
  위치(`.gitignore:43` 꼴)를 출력한다. 무시 규칙 수정은 준비 4단계의 독립 항목으로 사람이 고르고, `--force` 로
  넘기지 않는다.
- 이미 있는 파일에 ai-ready 서명(`<!-- ai-ready:apply 자동 생성 초안 ...`)이 없으면 사람이 관리하는 파일이다. 서명이
  있어도 서명 줄의 본문 해시(`body-sha256:`)가 지금 본문과 다르면 사람이 고친 초안이다. 해시가 없는 옛 초안도 고친
  것으로 본다. 이런 파일이 하나라도 있으면 스크립트는 아무것도 쓰지 않고 exit 3 으로 끝나며, 막는 이유를 모두
  출력한다("초안이 고쳐졌다" 는 따로 적힌다). 그 파일은 `--force` 로 덮지 말고, 아래 "사람이 관리하는 문서 고치기"
  로 처리한다.
- `scripts/verify.sh` 가 고쳐졌으면 stderr 에 지금 `CHECKS` 와 만들 `CHECKS` 가 나온다. 지금 파일을 두려면 `--only`
  에서 `verification` 을 뺀다. 고치지 않은 `verify.sh` 를 다른 `CHECKS` 로 다시 쓰면 출력에 "CHECKS 가 바뀐다" 가
  붙으니 사용자에게 알린다.
- `verification` 은 매니페스트에서 typecheck·lint·test 명령을 추론한다. 추론이 안 되면 exit 4 로 멈춘다. 그때는
  사용자에게 명령을 물어 `--check "<명령>"` 으로 준다(여러 번 줄 수 있다). 명령을 지어내지 않는다.
- CI 한 줄 예시: `python3 scripts/check_docs.py` 를 CI 의 문서 검사 단계에 넣는다. 오류가 있으면 exit 1,
  경고만 있으면 exit 0 이다.

### 2. 모듈 문서 — `scaffold.py`

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/scaffold.py --target <T> --out <T> --top 5 --dry-run
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/scaffold.py --target <T> --out <T> --modules app,core
```

- 두 번째 꼴은 모듈을 직접 고를 때 쓴다. 모듈마다 `AGENTS.md`(초안)와 `@AGENTS.md` 한 줄짜리 `CLAUDE.md` 를 만든다.
  이미 `@AGENTS.md` 를 가져오는 `CLAUDE.md` 는 다른 줄이 더 있어도 그대로 둔다.
- 종료 코드: 사람이 관리하는 문서·고친 초안·심볼릭 링크가 있는 모듈을 직접 고르면 exit 3, 스택의 소스 기준점 아래에
  코드 디렉토리가 없으면 exit 4, 맞는 스택 어댑터가 없으면 exit 5, `AGENTS.md` 가 git 에서 무시되면 exit 6 이다.
  exit 4·5 는 모듈을 정하지 못했다는 뜻이니 `--modules` 로 억지로 넘기지 말고 그 사실을 보고한다. 다리 파일
  `CLAUDE.md` 만 무시되면 그 파일만 건너뛴다(1절과 같다).
- 절: 이 모듈이 하는 일 / 경계(무엇에 의존하고 무엇이 의존하나) / 변경 방법 / 강제할 수 없는 규칙(항목마다 왜) /
  강제되는 규칙("→ <lint 규칙·테스트>" 포인터만).
- 사람이 관리하는 `AGENTS.md`·`CLAUDE.md` 가 이미 있거나, 서명을 남긴 채 고친 초안이거나, 심볼릭 링크인 모듈은
  `--top` 후보에서 뺀다. 모든 모듈에 한꺼번에 만들지 않는다. 최근 변경이 잦은 모듈부터 몇 개만 만들고, 채운 뒤에
  넓힌다.
- 초안이 생기면 모델이 모듈 코드를 읽고 TODO 를 채운 diff 를 보여 준다. 숫자(파일 수·줄 수·호출 수)는 적지 않는다.
  다음 커밋부터 틀린 값이 된다.
- **TODO 를 채울 때는 `Write` 가 아니라 `Edit` 로 TODO 자리만 고친다.** 첫 줄의 서명
  (`<!-- ai-ready:apply 자동 생성 초안 ...`)은 기본으로 남긴다. 서명을 남긴 채 채워도 다음 apply 는 고친 것을
  알아보고 덮지 않는다(서명 줄의 본문 해시가 달라진다). 다시 만들고 싶으면 파일을 지우고 돌린다. 서명 줄을 지울지는
  사람이 정한다.
- TODO 채우기를 하위 에이전트에 넘길 때도 이 두 조건(`Edit` 로 고친다, 서명 줄은 남긴다)과 "Read/Grep/Glob 을 쓰고
  셸 명령을 묶어 쓰지 않는다" 를 프롬프트에 그대로 적는다. 하위 에이전트는 백그라운드로 띄우지 않는다.

### 3. 강제 초안 — audit 의 B 항목

B 항목마다 [`references/enforcement-drafts.md`](references/enforcement-drafts.md) 를 따라 초안을 만든다.

1. 표현할 수 없게 만들기 → lint·금지 API → 정석 헬퍼 → 런타임 검사 → 테스트 순으로 따져 가장 강한 수단을 고른다.
2. 대상 스택의 도구로 규칙·테스트 초안을 쓴다. 오류 메시지에 "대신 X 를 써라" 를 넣는다.
3. 사용자 승인을 받고 적용한다. 적용한 뒤 그 검사를 돌려 기존 위반이 있는지 본다. 있으면 기준 파일(baseline·freeze)
   방식을 제안한다. 검사를 돌릴 수 없었으면(권한 거부·도구 없음) 5단계의 CI 설정 변경을 적용하지 않고, 그 항목을
   돌리지 못한 이유와 함께 보류로 보고한다.
4. 원래 문서 줄은 본문을 지우고 "→ <규칙 이름·테스트 경로>" 한 줄로 바꾸는 diff 를 따로 보여 준다.
5. CI 가 그 검사를 돌리지 않으면(gaps.md 2절) CI 에 넣는 한 줄을 제안한다. CI 설정 수정도 승인 뒤에 한다.

한 번에 규칙 하나씩 처리한다. 여러 규칙을 한 diff 에 묶지 않는다.

### 4. C·D 항목

- **C(강제 불가)**: 해당 모듈 문서(원본인 `AGENTS.md`)의 "강제할 수 없는 규칙" 이나 `docs/ANTIPATTERNS.md` 에 이유와
  함께 옮기는 diff 를 낸다. 루트 문서에는 저장소 전체에 걸린 규칙만 둔다.
- **D(어긋남·낡음)**: 문서를 코드에 맞출지, 코드를 문서에 맞출지 사용자에게 묻는다. 코드 수정은 이 스킬이 하지
  않는다 — 수정 후보와 위치만 보고한다.
- 설계 결정에 해당하는 것은 `docs/design/<도메인>.decisions.md` 맨 위에 새 카드 초안
  (`## 제목 · (티켓) · [proposed]`)으로 낸다. 옛 카드 본문은 고치지 않는다.

### 5. Stop hook — `install_verify_hook.py`

건 전제는 둘이다. `scripts/verify.sh` 가 있고, **이번 세션에서 `bash scripts/verify.sh` 가 한 번 이상 통과했다.**
통과하지 못했으면 hook 을 걸지 않는다. 대신 실패 출력에서 기존 위반 목록을 뽑아 보고하고, 그 검사의 기준선
(baseline·freeze) 방식을 제안한다. 이미 실패하는 검사를 hook 으로 걸면 에이전트가 턴을 끝내려고 이번 작업과 무관한
기존 위반을 고치며 운영 코드를 바꾼다. 두 전제를 채웠고 사용자가 명시적으로 승인하면 건다.

```bash
bash scripts/verify.sh
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/install_verify_hook.py --target <T> --dry-run
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/install_verify_hook.py --target <T>
```

첫 명령은 대상 저장소를 작업 폴더로 두고 돌린다(통과 확인). 통과한 뒤에 `--dry-run` 결과를 보여 주고, 승인을 받아
마지막 명령을 돌린다.

- 스크립트도 같은 전제를 본다. verify.sh 의 통과 기록(`git rev-parse --git-path verify-pass` 파일)이 없거나 Stop hook
  실행의 실패 기록(`verify-fail`)이 있으면 걸지 않고 exit 4 로 끝난다. verify.sh 는 실패하면 통과 기록을 지우므로,
  한 번 통과한 뒤 커밋으로 깨진 저장소도 여기서 걸린다. `--force` 로 넘기지 않는다 — 위 보고로 돌아간다.
- `--dry-run` 은 바뀔 settings.json 을 보여 준다. `.claude/settings.json` 의 다른 설정은 그대로 두고 Stop hook 하나만
  더한다. 이미 걸려 있으면 바꾸지 않는다.
- 에이전트가 턴을 끝내려 할 때 verify.sh 가 돌고, 실패하면 exit 2 로 턴을 막으며 실패 출력의 마지막 20줄과 "이번
  변경과 무관한 기존 위반은 고치지 말고 멈춰서 사람에게 보고한다" 는 줄을 넘긴다.
- 같은 작업 트리로 3번 막았으면(`verify-fail` 에 실패한 트리의 지문을 적어 둔다) 그 뒤로는 확인 명령을 다시 돌리지
  않고 한 줄 안내만 남기고 통과시킨다. 작업 트리가 바뀌면 다시 센다. `scripts/verify.sh` 를 직접 부르면 늘 돈다.
- 작업 트리가 마지막 통과 때와 같으면(`verify-pass` 에 지문을 적어 둔다) 다시 돌리지 않는다.
- 빼려면 `--uninstall`.

## 사람이 관리하는 문서 고치기

서명이 없는 문서는 통째로 다시 만들지 않는다. 문서 전체를 `Read` 로 읽고, 필요한 부분만 고친 diff 를 보여 준 뒤
승인을 받아 `Edit` 한다. 사람이 정한 순서·묶음·산문은 그대로 둔다. `CLAUDE.md` 가 `@AGENTS.md` 를 가져오는 구조면
본문은 `AGENTS.md` 에서 고친다.

## 마무리

적용이 끝나면 audit 스크립트를 다시 돌려 `gaps.md` 가 어떻게 바뀌었는지(생긴 문서, CI 가 새로 돌리는 검사, 줄어든
규칙 줄)를 보고한다. 바뀌지 않은 것이 있으면 그대로 적는다.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/audit.py --target <T> --out <T>/.ai-ready/gaps.md
```

`scripts/check_docs.py` 를 만들었으면 대상 저장소를 작업 폴더로 두고 한 번 돌려 결과를 함께 보고한다.

```bash
python3 scripts/check_docs.py
```

이 재실행은 메인 에이전트가 적용과 같은 턴에서 한다. 턴이 끝나 돌리지 못했으면 보류로 적는다.

보류한 항목(권한 거부·도구 없음·사람 확인이 필요한 것)은 이유와 함께 따로 적는다.

## 하지 않는 것

- 보고서 없이, 또는 보고서에 없던 변경을 추측으로 적용하지 않는다.
- 여러 파일·여러 규칙을 한 번의 승인으로 묶지 않는다.
- 사용자 승인 없이 커밋·push·CI 수정·hook 설치를 하지 않는다.
- 사용자 승인 없이 무시 규칙(`.gitignore` 등)을 고치지 않는다.
- 스킬 흐름 안에서 하위 에이전트를 백그라운드로 띄우거나, 스크립트 실행을 하위 에이전트에 넘기지 않는다.
- 확인 명령이나 lint 규칙 이름을 지어내지 않는다. 확인하지 못한 것은 "확인 필요" 로 적는다.
