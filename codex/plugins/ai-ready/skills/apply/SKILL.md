---
name: apply
description: "Apply only the user-approved items from an AI-Ready audit gap report (.ai-ready/gaps.md and audit-report.md): draft missing guidance (a short root AGENTS.md/CLAUDE.md, module docs, docs/design decision records, an anti-pattern ledger, a verification doc), add scripts/verify.sh and a docs consistency check, and turn documented rules into lint or architecture-test drafts. Use when the user asks to apply AI-ready audit results, move documented rules into lint, or set up decision records or verify.sh."
---

# AI-Ready Apply — 승인한 것만 적용

audit 결과를 읽어 없는 문서와 검증 장치를 만들고, 문서에만 있던 규칙을 도구로 옮긴다. 파일 하나·규칙 하나마다
사람이 승인한 뒤에 쓴다. 강제할 수 있는 규칙은 도구로 옮기고, 문서에는 강제할 수 없는 것만 남긴다.

## 준비

1. `<target>/.ai-ready/gaps.md` 와 `audit-report.md` 를 읽는다. 없으면 `audit` 을 먼저 안내하고 멈춘다.
2. 루트와 모듈의 `AGENTS.md`/`CLAUDE.md` 중 어느 것이 원본인지 정한다. 한쪽이 심링크면 원본만 고친다.
3. 할 일을 표로 보여 준다: 항목 · 파일 · 방법(스크립트 / 모델 초안) · 근거. 사용자가 고른 것만 진행한다.

## 만드는 것

audit 스킬 폴더의 스크립트를 쓴다(`../audit/scripts/`).

- `bootstrap.py --target <target> --only <종류> --dry-run` 으로 먼저 보여 주고, 승인 뒤 `--dry-run` 없이 돌린다.
  종류: `root`(짧은 루트 문서 + AGENTS.md 심링크), `design`(`docs/design/README.md` + `.gitattributes` 의
  union merge 한 줄, `--design-domain` 으로 도메인 문서 쌍), `antipatterns`(빈 원장과 형식), `verification`
  (`docs/VERIFICATION.md` + `scripts/verify.sh`), `doc-check`(`scripts/check_docs.py`).
- 사람이 관리하는 파일(ai-ready 서명이 없는 파일)이 있으면 스크립트는 아무것도 쓰지 않고 exit 3 이다. 덮어쓰지
  말고 diff 를 보여 준 뒤 필요한 부분만 고친다.
- 확인 명령을 추론하지 못하면 exit 4 다. 사용자에게 물어 `--check "<명령>"` 으로 준다. 명령을 지어내지 않는다.
- `scaffold.py --target <target> --out <target> --dry-run` 으로 모듈 문서 초안을 만든다. 절은 하는 일 / 경계 /
  변경 방법 / 강제할 수 없는 규칙 / 강제되는 규칙(포인터만)이고, 숫자는 적지 않는다.
- audit 의 B 항목은 `references/enforcement-drafts.md` 를 따라 강제 초안을 만든다. 오류 메시지에 "대신 X" 를 넣고,
  기존 위반이 있으면 기준 파일(baseline·freeze) 방식을 제안한다. 적용 뒤 문서 줄은 "→ <규칙·테스트>" 로 줄인다.
- C 항목은 이유와 함께 모듈 문서나 안티패턴 원장으로, 설계 결정은 `docs/design/<도메인>.decisions.md` 맨 위의 새
  카드(`## 제목 · (티켓) · [proposed]`)로 낸다. D 항목은 수정 후보로 보고만 한다.

## Codex 에서의 범위

- `.claude/settings.json` 을 고치거나 Claude Stop hook 을 흉내 내지 않는다. `scripts/verify.sh` 를 자동으로 돌리고
  싶으면 프로젝트의 CI 나 pre-commit 에 넣는 방법을 설명하고, 사용자가 승인하면 그 설정 diff 를 낸다.
- 전역 Codex 설정·플러그인 설치·원격 호출·자격 증명은 건드리지 않는다.
- 끝나면 `audit.py` 를 다시 돌려 `gaps.md` 가 어떻게 바뀌었는지 보고한다.
