# Codex 어댑터의 범위

Codex 쪽은 audit(빈틈 보고서), apply(승인한 문서·검증 장치 적용), lessons(교훈 초안)를 지원한다.

- `AGENTS.md` 를 원본 문서로 쓴다. apply 는 옆에 `@AGENTS.md` 한 줄짜리 `CLAUDE.md` 를 둬 Claude Code 도 같은 본문을
  읽게 한다. 이미 있는 `CLAUDE.md` 원본이나 심볼릭 링크 구조는 읽기만 하고, 전환은 audit 이 제안으로만 적는다.
- audit 스크립트는 Claude 트리와 같은 파일을 복사해 쓴다(`build/drift-test.sh` 가 바이트 동일을 검사한다).
  예외는 Stop hook 설치기 하나다. `.claude/settings.json` 을 고치는 Claude Code 전용 도구라 이 번들에 넣지 않는다.
- `scripts/verify.sh` 와 `scripts/check_docs.py` 는 대상 프로젝트에 복사되는 일반 스크립트라 Codex 에서도 쓸 수
  있다. 자동 실행이 필요하면 프로젝트가 소유한 CI 나 pre-commit 에 넣는다.
- 플러그인 캐시·자격 증명·전역 설정·Claude 에이전트 정의를 이 어댑터로 복사하지 않는다.
