---
name: apply
description: "Apply only the user-approved items from an AI-Ready audit gap report (.ai-ready/gaps.md and audit-report.md): draft missing guidance (a short root AGENTS.md plus a one-line CLAUDE.md that imports it, module docs, docs/design decision records, an anti-pattern ledger, a verification doc), add scripts/verify.sh and a docs consistency check, and turn documented rules into lint or architecture-test drafts. Use when the user asks to apply AI-ready audit results, move documented rules into lint, or set up decision records or verify.sh."
---

# AI-Ready Apply — 승인한 것만 적용

audit 결과를 읽어 없는 문서와 검증 장치를 만들고, 문서에만 있던 규칙을 도구로 옮긴다. 파일 하나·규칙 하나마다
사람이 승인한 뒤에 쓴다. 강제할 수 있는 규칙은 도구로 옮기고, 문서에는 강제할 수 없는 것만 남긴다.

## 준비

1. `<target>/.ai-ready/gaps.md` 와 `audit-report.md` 를 읽는다. 없으면 `audit` 을 먼저 안내하고 멈춘다.
2. 커밋하지 않은 변경이 있으면(`git status --short`) 알리고, 계속할지 묻는다.
3. 루트와 모듈의 `AGENTS.md`/`CLAUDE.md` 중 어느 것이 원본인지 정한다. 기본 구조는 `AGENTS.md` 가 원본이고
   `CLAUDE.md` 가 `@AGENTS.md` 한 줄로 그것을 가져오는 것이다. 한쪽이 심볼릭 링크면 원본만 고친다.
4. 할 일을 표로 보여 준다: 항목 · 파일 · 방법(스크립트 / 모델 초안) · 근거. 사용자가 고른 것만 진행한다. 보고서에
   없던 변경은 추측으로 표에 넣지 않는다.
5. `gaps.md` 의 "git 이 무시하는 생성 대상 경로" 에 원본 파일(`AGENTS.md`·`docs/…`·`scripts/…`)이 있으면 무시
   규칙(`.gitignore` 등) 수정을 표의 독립 항목으로 둔다. 고치는 방법이 여럿이면 선택지를 따로 보여 준다. 선택지가
   여럿이면 "전부 진행" 같은 일괄 승인은 선택으로 보지 않고 다시 묻는다. 비대화 실행이면 고치지 않고 보류로 적는다.
   다리 파일(`@AGENTS.md` 한 줄짜리 `CLAUDE.md`)만 무시되는 것은 고칠 항목이 아니다.

## 만드는 것

스크립트는 이 `SKILL.md` 가 있는 `apply/` 폴더의 형제인 `audit/` 스킬 폴더 안 `scripts/` 에 있다. 작업 폴더(대상
저장소) 기준 상대 경로가 아니므로, `<audit 스킬 폴더>` 자리에 이 `SKILL.md` 의 절대 경로에서 `apply/SKILL.md` 를
`audit` 으로 바꾼 폴더를 넣는다. 명령은 `python3 <audit 스킬 폴더>/scripts/<스크립트> ...` 한 줄로 부른다. 변수 대입·`{ ...; exit ...; }` 묶음을 앞에 붙이지 않고, 있는지 보려면 `test -f ... && python3 ...`
꼴까지만 쓴다. `echo $?` 를 이어 붙이지 않는다 — 스크립트가 실패하면 이유와 `종료 코드 N` 을 출력한다.

- `bootstrap.py --target <target> --only <종류> --dry-run` 으로 먼저 보여 주고, 승인 뒤 `--dry-run` 없이 돌린다.
  종류: `root`(짧은 루트 `AGENTS.md` + 그것을 `@AGENTS.md` 한 줄로 가져오는 `CLAUDE.md`. 심볼릭 링크는 만들지
  않는다), `design`(`docs/design/README.md` + `.gitattributes` 의
  union merge 한 줄, `--design-domain` 으로 도메인 문서 쌍), `antipatterns`(빈 원장과 형식), `verification`
  (`docs/VERIFICATION.md` + `scripts/verify.sh`), `doc-check`(`scripts/check_docs.py`).
- 사람이 관리하는 파일(ai-ready 서명이 없는 파일)이나 사람이 고친 초안(서명 줄의 `body-sha256:` 해시가 지금 본문과
  다르거나, 해시가 없는 옛 초안)이 있으면 스크립트는 아무것도 쓰지 않고 exit 3 이다. 막는 이유는 모두 출력한다.
  덮어쓰지 말고 diff 를 보여 준 뒤 필요한 부분만 고친다. `scripts/verify.sh` 가 고쳐졌으면 지금 `CHECKS` 도 함께
  나온다. 지금 파일을 두려면 `verification` 을 뺀다.
- 만들 파일이 심볼릭 링크면(옛 구조: `CLAUDE.md` 원본 + `AGENTS.md` 링크) exit 3 이다. `AGENTS.md`·`docs/…`·
  `scripts/…` 같은 원본이 git 에서 무시되면 exit 6 이다. 둘 다 아무것도 쓰지 않는다. 전환이나 무시 규칙 수정은
  사람이 정하고, `--force` 로 넘기지 않는다.
- 무시되는 것이 다리 파일(`@AGENTS.md` 한 줄짜리 `CLAUDE.md`)뿐이면 그 파일만 건너뛰고 나머지를 쓴다. 스크립트가
  출력한 참고("로컬에 개인 `CLAUDE.md` 가 있는 사람은 거기에 `@AGENTS.md` 를 넣어야 `AGENTS.md` 가 로드된다")를
  그대로 보고한다.
- 확인 명령을 추론하지 못하면 exit 4 다. 사용자에게 물어 `--check "<명령>"` 으로 준다. 명령을 지어내지 않는다.
- 모듈 문서 초안(`AGENTS.md` + 가져오는 `CLAUDE.md`)은 `scaffold.py` 로 만든다. 먼저
  `scaffold.py --target <target> --out <target> --top 5 --dry-run` 으로 무엇을 쓸지 보여 준다(`--dry-run` 은 아무것도
  쓰지 않는다). 승인 뒤 `--dry-run` 없이 같은 명령을 돌리거나, 모듈을 직접 고를 때는
  `scaffold.py --target <target> --out <target> --modules app,core` 로 쓴다. 절은 하는 일 / 경계 / 변경 방법 / 강제할
  수 없는 규칙 / 강제되는 규칙(포인터만)이고, 숫자는 적지 않는다. 사람 문서·고친 초안·심볼릭 링크가 있는 모듈은
  `--top` 후보에서 빠지고, `--modules` 로 고르면 exit 3 이다. 기준점 아래 코드가 없으면 exit 4, 맞는 스택 어댑터가
  없으면 exit 5, `AGENTS.md` 가 무시되면 exit 6 이다.
- TODO 를 채울 때는 파일을 통째로 다시 쓰지 않고 TODO 자리만 고친다. 첫 줄의 서명(`<!-- ai-ready:apply 자동 생성
  초안 ...`)은 기본으로 남긴다. 서명을 남긴 채 채워도 다음 apply 는 고친 것을 알아보고 덮지 않는다. 다시 만들고
  싶으면 파일을 지우고 돌린다. 하위 에이전트에 넘길 때도 이 두 조건을 그대로 전달한다.
- audit 의 B 항목은 `references/enforcement-drafts.md` 를 따라 강제 초안을 만든다. 오류 메시지에 "대신 X" 를 넣고,
  기존 위반이 있으면 기준 파일(baseline·freeze) 방식을 제안한다. 적용 뒤 문서 줄은 "→ <규칙·테스트>" 로 줄인다.
  검사를 돌릴 수 없었으면(권한 거부·도구 없음) CI 설정 변경은 적용하지 않고 보류 항목으로 보고한다.
- C 항목은 이유와 함께 모듈 문서나 안티패턴 원장으로, 설계 결정은 `docs/design/<도메인>.decisions.md` 맨 위의 새
  카드(`## 제목 · (티켓) · [proposed]`)로 낸다. D 항목은 수정 후보로 보고만 한다.

## Codex 에서의 범위

- `.claude/settings.json` 을 고치거나 Claude Stop hook 을 흉내 내지 않는다. `scripts/verify.sh` 를 자동으로 돌리고
  싶으면 프로젝트의 CI 나 pre-commit 에 넣는 방법을 설명하고, 사용자가 승인하면 그 설정 diff 를 낸다.
- 전역 Codex 설정·플러그인 설치·원격 호출·자격 증명은 건드리지 않는다.
- 사용자 승인 없이 커밋·push·CI 수정·무시 규칙(`.gitignore` 등) 수정을 하지 않는다.
- 사람이 중간에 답할 수 없는 비대화 실행에서는 사람에게 명령을 대신 돌려 달라고 요청하지 않는다. 돌리지 못한 것은
  이유와 함께 보류 항목으로 보고한다.
- 끝나면 `audit.py` 를 다시 돌려 `gaps.md` 가 어떻게 바뀌었는지 보고한다.
