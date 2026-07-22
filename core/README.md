# core/ — loop 계열 중립 단일원본

ai-ready 의 loop 계열(loop-build·loop-run·loop-lessons·loop-review)을 Claude·codex 두 호스트가 공유하도록, 수정은 여기 `core/` 한 곳에서만 하고 빌드가 각 호스트 설치 트리를 생성한다. 설치본은 호스트별로 유지된다(각자 manifest·root 로 로드하므로 두 호스트가 그대로 읽는 단일 폴더는 불가) — 중립성은 이 소스+빌드 층에 둔다.

## 레이아웃

```
core/                        ← 중립 단일 진실(수정은 여기서만)
  _loop-engine/              결정론 판정 셸(score/decide/stall/lessons/lib + rubric.base + detect_build). 이미 공급자 무관.
  effort-ladder.md           reasoning-effort 중립 사다리 + 호스트 변환표(공유 계약). 역할은 등급만 선언, 어댑터가 토큰으로 해소.
  (호스트별 손작성) skills/·역할 계약  D3′ 로 core 화 안 함 — 각 트리에 손으로 둠(스폰이 호스트별로 달라 자리표시자 이득 작음)
adapters/
  claude/                    (후속) 글루: manifest, 스폰=Agent/SendMessage, 경로=$CLAUDE_PLUGIN_ROOT, 모델맵
  codex/                     (후속) 글루: manifest(.codex-plugin), 스폰=codex 위임(NEW_TASK), 경로=$CODEX_*, 모델맵
build/
  assemble.sh                core → 각 호스트 설치 트리 조립
  drift-test.sh              각 트리 _loop-engine 이 core 와 바이트 동일한지 검사
(생성물, 커밋됨)
  plugins/ai-ready/          Claude 설치 트리
  codex/plugins/ai-ready/    codex 설치 트리
```

## 워크플로

1. loop 엔진/스킬/역할을 고칠 때는 `core/` 에서 고친다. 설치 트리(`plugins/ai-ready`·`codex/plugins/ai-ready`)를 직접 고치지 않는다 — 거긴 생성물이다.
2. `bash build/assemble.sh` 로 각 호스트 트리를 재생성한다.
3. `bash build/drift-test.sh` 로 갈라짐이 없는지 확인한다. 커밋 전 필수.

## 진행 상태 (2026-07-22)

- **완료**: `_loop-engine` 단일원본화 + `build/assemble.sh` + `build/drift-test.sh`. Claude 트리 재생성이 바이트 동일(무회귀), codex 트리에 엔진 조립됨. 엔진은 순수 셸이라 렌더링 없이 그대로 복사된다.
- **후속(설계 결정 남음)**: loop 스킬·역할 스펙의 core 화. 이건 단순 복사가 아니라 스폰 방식(Claude `Agent`/`SendMessage` vs codex 위임 NEW_TASK)·경로 변수·에이전트 참조가 스킬 본문에 얽혀 있어 **자리표시자 + 호스트별 렌더링**이 필요하다. 렌더 깊이(전면 템플릿화 vs 스폰 스니펫만 치환 + 호스트별 오케스트레이션 프롬 분리)는 착수 세션에서 확정한다.

## 범위 (spec `loop-family-codex-neutral-core.md`)

- loop 계열 + 엔진 + maker/checker 역할만 core. audit·apply·freshness 는 각 호스트 트리에 현행 유지(core 대상 아님).
- codex 오케스트레이션은 C(codex 세션이 Claude 처럼 지휘) 방식으로 확정됨(2026-07-22 스파이크). 판정은 어느 호스트든 이 `core/_loop-engine` 셸이 낸다.
- 모델: frontmatter 하드코딩 대신 역할·공급자별 모델맵을 어댑터에 둔다. **codex 실측 주의** — 모델 선택은 되지만(`-m gpt-5.6-sol|terra|luna`), 위임 하위가 자기 에이전트 model 을 따르려면 orchestrator 를 `-m` 로 명시 실행해야 한다(기본 실행이면 계정 기본으로 collapse). 맨 계열명 `-m gpt-5.6` 은 거부.
