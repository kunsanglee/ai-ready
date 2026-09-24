---
name: lessons
description: "Collect the mistakes a human corrected during a work session and in PR review comments, and draft candidates that stop them from recurring, for human review. For each candidate, first ask whether a tool can enforce it: if yes, draft a lint rule or architecture test; if not, draft an anti-pattern ledger entry with the reason; if it is a design decision, draft a docs/design decision card. Use for AI-ready lessons, 교훈 정리, or turning review feedback into lint rules."
---

# AI-Ready Lessons — 교훈을 강제 수단이나 문서로

작업 중 사람이 바로잡은 실수를 모아, 다음 작업에서 같은 실수가 나지 않게 할 후보를 초안으로 만든다. 초안만 만들고,
반영 여부는 사람이 후보마다 정한다.

## 흐름

1. 입력을 모은다.
   - 이 세션에서 사람이 바로잡은 말과 그 맥락(어느 파일·어떤 변경).
   - PR 번호를 받았고 GitHub 이며 `gh` 가 있으면 `gh pr view <번호> --comments` 로 리뷰 코멘트를 읽는다. 아니면
     사용자에게 붙여 달라고 한다. 토큰을 찾아 쓰지 않는다.
   - 강제 초안을 돌려 볼 확인 명령은 추정하지 않는다. `docs/VERIFICATION.md`·`scripts/verify.sh` 의 `CHECKS` 나 패키지
     매니페스트(`package.json` scripts, `build.gradle(.kts)`, `pyproject.toml`, `Makefile` 등)에서 읽고, 없으면 묻는다.
   - 입력이 없으면 "바로잡은 실수가 없다" 고 알리고 끝낸다.
2. 같은 원인끼리 묶고, 묶음마다 먼저 **도구로 강제할 수 있는지** 따진다(표현 불가 → lint·금지 API → 정석 헬퍼 →
   런타임 검사 → 테스트 → 문서 순). 넷 중 하나로 초안을 쓴다.
   - **강제 초안**: 도구·위치, 설정 조각이나 테스트 코드, "대신 X 를 써라" 가 든 오류 메시지, 기존 위반(있으면
     기준 파일 방식), CI 가 돌리는지. 형식은 `apply` 스킬의 `references/enforcement-drafts.md` 를 따른다.
   - **안티패턴 원장 항목**: DO NOT / 이유 / 대신 / 강제 불가: <왜> / 출처.
   - **결정 카드**: `## 제목 · (티켓 또는 -) · [proposed]` 와 날짜·맥락·결정·버린 대안·결과.
   - **버림**: 일회성이거나 이미 있는 규칙과 중복.
3. 후보를 하나씩 보여 주고 추가·수정·버림을 묻는다. 승인한 것만 반영한다. 안티패턴은 `docs/ANTIPATTERNS.md` 의
   "항목" 절 끝에, 결정 카드는 `docs/design/<도메인>.decisions.md` 맨 위에 더한다. 옛 카드 본문은 고치지 않는다.

## 하지 않는 것

- 사람 승인 없이 문서·설정·CI 를 고치지 않는다. 커밋하지 않는다.
- 확인하지 않은 코드 위치나 도구 규칙 이름을 적지 않는다.
- 일회성 실수를 억지로 규칙으로 만들지 않는다.
