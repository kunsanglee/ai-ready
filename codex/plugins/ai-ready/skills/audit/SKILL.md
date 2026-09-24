---
name: audit
description: "Produce a score-free gap report on whether a repository is set up for AI-agent work: which guidance documents exist (root and module AGENTS.md/CLAUDE.md and their layout, generated paths that git ignores, docs/design decision records, verification doc), which lint/typecheck/test/architecture checks exist and whether CI actually runs them, and which documented rules are already enforced, cheaply enforceable, not enforceable, or out of date. Use for an AI-ready audit, AI 준비도 점검, 문서 규칙 중 lint 로 옮길 것 찾기, or before running the apply skill."
---

# AI-Ready Audit — 빈틈 보고서

에이전트가 이 저장소에서 일할 때 필요한 문서와 강제 수단이 있는지, 문서의 규칙 중 무엇이 도구로 강제되고 무엇이
문서에만 있는지를 사실로 보여 준다. 점수는 없다.

기준: 강제할 수 있는 규칙은 lint·타입·테스트·CI 로 잡고, 문서에는 강제할 수 없는 것(왜·의도·어디에 무엇이
있나)만 남긴다.

## 준비

1. 사용자가 준 경로나 현재 Git 루트를 대상으로 정한다. 둘 다 없으면 추측하지 말고 묻는다.
2. 쓰는 곳은 `<target>/.ai-ready/` 뿐이라고 알린다. 소스·문서·설정은 건드리지 않는다.
3. 루트의 `AGENTS.md` 또는 `CLAUDE.md` 를 먼저 읽는다. 사람이 쓴 `AGENTS.md` 가 있으면 그것이 원본이다.

## 사실 모으기

이 스킬 폴더(이 `SKILL.md` 가 있는 `audit/` 폴더) 안 `scripts/audit.py` 를 돌린다. 작업 폴더는 보통 대상 저장소라
`scripts/audit.py` 를 상대 경로로 부르면 대상 저장소의 파일을 찾는다. `<audit 스킬 폴더>` 자리에 이 `SKILL.md` 가
있는 폴더의 절대 경로를 넣는다.

```text
python3 <audit 스킬 폴더>/scripts/audit.py --target <target> --out <target>/.ai-ready/gaps.md
```

한 줄로 부른다. 변수 대입·`{ ...; exit ...; }` 묶음을 앞에 붙이지 않고, `echo $?` 를 이어 붙이지 않는다 — 스크립트가
실패하면 이유와 `종료 코드 N` 을 출력한다.

`gaps.md` 는 세 절이다.

1. 문서 존재 — 루트·모듈 문서, `docs/design/` 결정 기록 쌍과 union merge 설정, 검증 문서·`scripts/verify.sh`·
   `scripts/check_docs.py`, 안티패턴 원장. 있음·없음·길이 과다와 문서 구조를 적는다. 기본 구조는 `AGENTS.md` 원본 +
   `@AGENTS.md` 한 줄짜리 `CLAUDE.md` 다. 옛 구조(`CLAUDE.md` 원본 + `AGENTS.md` 심볼릭 링크)나 가져오기 없이 따로 있는
   두 파일은 전환 제안으로 적고 바꾸지 않는다. apply 가 만들 문서 경로가 `git check-ignore` 에 걸리면 따로 적는다.
   무시되는 것이 `@AGENTS.md` 한 줄짜리 `CLAUDE.md`(다리 파일)뿐이면 참고로만 적는다(원본 `AGENTS.md` 는 커밋된다).
2. 강제 수단 — 감지된 lint·formatter·타입체커·테스트 러너·아키텍처 테스트, 매니페스트에서 추론한 확인 명령,
   CI 설정 파일 안에서 그 검사를 부르는 줄(`예`·`아니오`·`간접`·`아니오(제외됨)` — 같은 줄의 `-x test`·`-DskipTests`
   가 그 태스크를 빼면 제외됨), CI·Dockerfile 의 테스트 제외·실패 무시 줄,
   pre-commit 설정.
3. 규칙 문장 — "금지·반드시·must·never·DO NOT" 류 줄과 규칙 제목 아래 항목을 `파일:줄` 로. 분류는 없다.

## 분류와 권고 (모델이 한다)

3절의 규칙 줄마다 넷 중 하나로 나눈다. A 와 D 는 코드·설정을 읽어 확인한 근거가 있어야 하고, 확인하지 못했으면
"확인 필요" 로 남긴다. 한 줄에 규칙이 여럿이면 `R4a`·`R4b` 처럼 행을 나눠 행마다 A/B/C/D 중 하나만 붙인다.
`A/C` 같은 섞인 라벨은 쓰지 않는다.

| 분류 | 뜻 | 권고 |
|---|---|---|
| A 이미 강제됨 | lint 규칙·테스트·타입·CI 가 어기면 실패한다 | 문서 본문을 줄이고 "→ <규칙·테스트>" 한 줄만. CI 가 안 돌리면 따로 권고 |
| B 싸게 강제 가능 | 이 스택 도구로 규칙·테스트 하나를 더하면 강제된다 | 강제 초안 후보 (apply 가 만든다) |
| C 강제 불가 | 의도·트레이드오프라 도구로 못 잡는다 | 문서에 이유와 함께 남긴다 |
| D 어긋남·낡음 | 코드가 규칙과 다르거나 가리키는 대상이 없다 | 수정 후보 (문서·코드 중 어느 쪽을 고칠지는 사람이 정한다) |

결과를 `<target>/.ai-ready/audit-report.md` 에 쓴다: 빈틈 요약 → 규칙 분류 표(ID·위치·요약·분류·근거·권고) →
권고 목록(B 강제 초안 후보, D 수정 후보, 없는 문서·장치, 무시되는 생성 대상 경로, 문서 구조 전환 제안) → 보류
(돌리지 못한 명령과 이유). 사용자에게는 요약과 분류별 개수, B·D 상위 항목만
알리고 다음 단계로 `apply` 를 안내한다.

## 하지 않는 것

- 점수·등급을 매기지 않는다.
- `.ai-ready/` 밖에 쓰지 않는다. 문서 수정·CI 수정은 `apply` 에서 사람이 승인한 뒤에 한다.
- 규칙 분류를 정규식에 맡기지 않는다.
- 사람이 쓴 `AGENTS.md`·`CLAUDE.md`·문서를 덮어쓰지 않는다. 원격 호출·자격 증명 사용은 하지 않는다.
- 사람이 중간에 답할 수 없는 비대화 실행에서는 사람에게 명령을 대신 돌려 달라고 요청하지 않고 보류로 적는다.
