---
name: apply
description: ai-ready:audit 의 빈틈 보고서(.ai-ready/gaps.md, audit-report.md)를 읽고, 사람이 승인한 것만 적용한다. 없는 문서의 초안(짧은 루트 CLAUDE.md, 모듈 CLAUDE.md, docs/design 결정 기록 쌍, 안티패턴 원장, 검증 문서), 문서 정합 검사 스크립트, scripts/verify.sh 와 Claude Code Stop hook, 그리고 문서에만 있던 규칙을 lint·아키텍처 테스트로 옮기는 강제 초안(ArchUnit, eslint no-restricted-imports, dependency-cruiser, ruff banned-api, import-linter, detekt 등)을 만든다. Use when the user asks to apply ai-ready audit results, "문서 규칙을 lint 로 옮겨", create verify.sh or a Stop hook that runs checks, set up docs/design decision records, or scaffold module CLAUDE.md files.
---

# ai-ready apply — 승인한 것만 적용

`ai-ready:audit` 결과를 읽어, 없는 문서와 검증 장치를 만들고 문서에만 있던 규칙을 도구로 옮긴다. 파일 하나,
규칙 하나마다 사람이 승인한 뒤에 쓴다.

기준은 audit 과 같다. 강제할 수 있는 규칙은 도구로 옮기고, 문서에는 강제할 수 없는 것(왜·의도·지도)만 남긴다.

## 준비

```bash
# Bash 도구의 셸에는 $CLAUDE_PLUGIN_ROOT 가 없다. 이 스킬 본문 맨 위의 "Base directory for this skill" 값을 넣는다.
# Bash 호출마다 셸이 새로 뜨므로 아래 두 줄을 스크립트를 부르는 호출마다 같이 넣는다.
SKILL_DIR="<이 스킬 본문 첫머리의 Base directory>"
AUDIT="$(cd "$SKILL_DIR/../audit" && pwd)"
[ -f "$AUDIT/scripts/bootstrap.py" ] || { echo "apply: audit 스크립트를 못 찾았다 ($AUDIT)" >&2; exit 65; }
```

1. `<T>/.ai-ready/gaps.md` 와 `audit-report.md` 가 없으면 `ai-ready:audit` 을 먼저 안내하고 멈춘다.
2. 커밋하지 않은 변경이 있으면 알리고, 계속할지 묻는다.
3. `audit-report.md` 에서 할 일을 뽑아 **계획 표**로 보여 준다: 항목 · 만들거나 고칠 파일 · 방법(스크립트 / 모델 초안)
   · 근거(보고서의 어느 줄). 사용자가 고른 것만 진행한다.

## 만드는 것

### 1. 없는 문서의 초안 — `bootstrap.py`

| 종류(`--only`) | 만드는 파일 |
|---|---|
| `root` | 루트 `CLAUDE.md` + `AGENTS.md` 심링크. 확인 명령, 문서 지도(이럴 때 → 이 문서), 강제할 수 없는 규칙 자리만 둔다 |
| `design` | `docs/design/README.md`(카드 형식·읽는 법), `.gitattributes` 에 `docs/design/*.decisions.md merge=union` 한 줄. `--design-domain <이름>` 을 주면 `<이름>.md`(현재 동작)와 `<이름>.decisions.md`(결정 카드)도 |
| `antipatterns` | `docs/ANTIPATTERNS.md` — 빈 원장과 항목 형식(DO NOT / 이유 / 대신 / 강제 수단 또는 강제 불가 / 출처) |
| `verification` | `docs/VERIFICATION.md`(로컬·CI·에이전트 작업 중에 무엇이 도나) + `scripts/verify.sh` |
| `doc-check` | `scripts/check_docs.py` — 깨진 상대 링크, 결정 카드 제목 형식, union merge 로 생긴 중복 카드, frontmatter 필수 키 |

```bash
python3 "$AUDIT/scripts/bootstrap.py" --target <T> --only root,design --dry-run   # 무엇을 쓸지 먼저 보여 준다
python3 "$AUDIT/scripts/bootstrap.py" --target <T> --only root,design             # 승인 뒤
```

- 먼저 `--dry-run` 결과를 보여 주고 승인을 받는다.
- 이미 있는 파일에 ai-ready 서명(`<!-- ai-ready:apply 자동 생성 초안 ...`)이 없으면 사람이 관리하는 파일이다. 그런
  파일이 하나라도 있으면 스크립트는 아무것도 쓰지 않고 exit 3 으로 끝난다. 그 파일은 `--force` 로 덮지 말고, 아래
  "사람이 관리하는 문서 고치기" 로 처리한다.
- `verification` 은 매니페스트에서 typecheck·lint·test 명령을 추론한다. 추론이 안 되면 exit 4 로 멈춘다. 그때는
  사용자에게 명령을 물어 `--check "<명령>"` 으로 준다(여러 번 줄 수 있다). 명령을 지어내지 않는다.
- CI 한 줄 예시: `python3 scripts/check_docs.py` 를 CI 의 문서 검사 단계에 넣는다. 오류가 있으면 exit 1,
  경고만 있으면 exit 0 이다.

### 2. 모듈 CLAUDE.md — `scaffold.py`

```bash
python3 "$AUDIT/scripts/scaffold.py" --target <T> --out <T> --top 5 --dry-run
python3 "$AUDIT/scripts/scaffold.py" --target <T> --out <T> --modules app,core   # 모듈을 직접 고를 때
```

- 절: 이 모듈이 하는 일 / 경계(무엇에 의존하고 무엇이 의존하나) / 변경 방법 / 강제할 수 없는 규칙(항목마다 왜) /
  강제되는 규칙("→ <lint 규칙·테스트>" 포인터만).
- 사람이 관리하는 `CLAUDE.md` 가 이미 있는 모듈은 후보에서 뺀다. 모든 모듈에 한꺼번에 만들지 않는다. 최근 변경이
  잦은 모듈부터 몇 개만 만들고, 채운 뒤에 넓힌다.
- 초안이 생기면 모델이 모듈 코드를 읽고 TODO 를 채운 diff 를 보여 준다. 숫자(파일 수·줄 수·호출 수)는 적지 않는다.
  다음 커밋부터 틀린 값이 된다.

### 3. 강제 초안 — audit 의 B 항목

B 항목마다 [`references/enforcement-drafts.md`](references/enforcement-drafts.md) 를 따라 초안을 만든다.

1. 표현할 수 없게 만들기 → lint·금지 API → 정석 헬퍼 → 런타임 검사 → 테스트 순으로 따져 가장 강한 수단을 고른다.
2. 대상 스택의 도구로 규칙·테스트 초안을 쓴다. 오류 메시지에 "대신 X 를 써라" 를 넣는다.
3. 사용자 승인을 받고 적용한다. 적용한 뒤 그 검사를 돌려 기존 위반이 있는지 본다. 있으면 기준 파일(baseline·freeze)
   방식을 제안한다.
4. 원래 문서 줄은 본문을 지우고 "→ <규칙 이름·테스트 경로>" 한 줄로 바꾸는 diff 를 따로 보여 준다.
5. CI 가 그 검사를 돌리지 않으면(gaps.md 2절) CI 에 넣는 한 줄을 제안한다. CI 설정 수정도 승인 뒤에 한다.

한 번에 규칙 하나씩 처리한다. 여러 규칙을 한 diff 에 묶지 않는다.

### 4. C·D 항목

- **C(강제 불가)**: 해당 모듈 `CLAUDE.md` 의 "강제할 수 없는 규칙" 이나 `docs/ANTIPATTERNS.md` 에 이유와 함께
  옮기는 diff 를 낸다. 루트 `CLAUDE.md` 에는 저장소 전체에 걸린 규칙만 둔다.
- **D(어긋남·낡음)**: 문서를 코드에 맞출지, 코드를 문서에 맞출지 사용자에게 묻는다. 코드 수정은 이 스킬이 하지
  않는다 — 수정 후보와 위치만 보고한다.
- 설계 결정에 해당하는 것은 `docs/design/<도메인>.decisions.md` 맨 위에 새 카드 초안
  (`## 제목 · (티켓) · [proposed]`)으로 낸다. 옛 카드 본문은 고치지 않는다.

### 5. Stop hook — `install_verify_hook.py`

`scripts/verify.sh` 가 생긴 뒤, 사용자가 명시적으로 승인하면 건다.

```bash
python3 "$AUDIT/scripts/install_verify_hook.py" --target <T> --dry-run   # 바뀔 settings.json 을 보여 준다
python3 "$AUDIT/scripts/install_verify_hook.py" --target <T>
```

- `.claude/settings.json` 의 다른 설정은 그대로 두고 Stop hook 하나만 더한다. 이미 걸려 있으면 바꾸지 않는다.
- 에이전트가 턴을 끝내려 할 때 verify.sh 가 돌고, 실패하면 exit 2 로 턴을 막으며 실패 출력의 마지막 20줄을 넘긴다.
  연속 3번 막았으면 다음 실패는 경고만 남기고 통과시킨다(끝없이 막히지 않게).
- 작업 트리가 마지막 통과 때와 같으면(`.git/verify-pass` 에 지문을 적어 둔다) 다시 돌리지 않는다.
- 빼려면 `--uninstall`.

## 사람이 관리하는 문서 고치기

서명이 없는 문서는 통째로 다시 만들지 않는다. 문서 전체를 `Read` 로 읽고, 필요한 부분만 고친 diff 를 보여 준 뒤
승인을 받아 `Edit` 한다. 사람이 정한 순서·묶음·산문은 그대로 둔다.

## 마무리

적용이 끝나면 audit 스크립트를 다시 돌려 `gaps.md` 가 어떻게 바뀌었는지(생긴 문서, CI 가 새로 돌리는 검사, 줄어든
규칙 줄)를 보고한다. 바뀌지 않은 것이 있으면 그대로 적는다.

```bash
python3 "$AUDIT/scripts/audit.py" --target <T> --out <T>/.ai-ready/gaps.md
```

## 하지 않는 것

- 보고서 없이 추측으로 적용하지 않는다.
- 여러 파일·여러 규칙을 한 번의 승인으로 묶지 않는다.
- 사용자 승인 없이 커밋·push·CI 수정·hook 설치를 하지 않는다.
- 확인 명령이나 lint 규칙 이름을 지어내지 않는다. 확인하지 못한 것은 "확인 필요" 로 적는다.
