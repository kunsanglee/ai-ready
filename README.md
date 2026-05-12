# ai-ready

Claude Code 마켓플레이스 — 코드베이스의 AI 준비도(AI-readiness) 를 7카테고리 100점 루브릭으로 측정하고, ROI 우선순위로 개선을 적용하는 플러그인.

## 설치

```
/plugin marketplace add kunsanglee/ai-ready
/plugin install ai-ready@ai-ready
```

## 업데이트

이미 설치한 사용자가 최신 버전으로 갱신하려면 세 명령을 *각각 한 줄씩* 입력 (slash command 는 한 줄에 한 명령만 받아서 주석을 같은 줄에 붙이면 marketplace 이름으로 오해석됩니다):

마켓플레이스의 최신 `plugin.json` 정보 fetch:

```
/plugin marketplace update ai-ready
```

plugin 자체를 새 version 으로 갱신:

```
/plugin update ai-ready@ai-ready
```

설치된 version 확인:

```
/plugin list
```

> Claude Code 는 `plugin.json` 의 `version` 필드가 바뀐 경우에만 새 버전으로 인지합니다. 이 repo 는 매 릴리즈에 version 을 bump 합니다.

### 최근 주요 변경

- **0.1.2** — manifest schema 오류 수정 (`repository` 가 string URL 이어야 함), 단일 모듈 프로젝트 평가/스캐폴드 분기 추가 (패키지 = 논리 모듈 관점, `docs/PACKAGES.md` 카탈로그 + 표준 레이아웃 일관성 평가), thin-index 인식, sparkline / history archive, ANTIPATTERNS 클러스터링, `.ai-ready/README.md` 자동 생성, iOS 빌드 매니페스트 지원.

## 사용

```
/ai-ready:audit   # 점수·리포트·대시보드 생성 + 핫 모듈 CLAUDE.md 초안 + 안티패턴 시드
/ai-ready:apply   # 감사 결과의 ROI 상위 액션 자동 적용
```

자세한 내용은 [`plugins/ai-ready/skills/audit/SKILL.md`](plugins/ai-ready/skills/audit/SKILL.md) 와 [`plugins/ai-ready/skills/apply/SKILL.md`](plugins/ai-ready/skills/apply/SKILL.md) 참고.

## 구조

```
.
├── .claude-plugin/marketplace.json   # 마켓플레이스 manifest
└── plugins/
    └── ai-ready/
        ├── .claude-plugin/plugin.json
        └── skills/
            ├── audit/    # 감사 + 리포트 + 대시보드 + 시드 생성
            └── apply/    # ROI 액션 자동 적용
```

## 라이선스

MIT
