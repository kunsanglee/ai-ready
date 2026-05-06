# ai-ready

Claude Code 마켓플레이스 — 코드베이스의 AI 준비도(AI-readiness) 를 7카테고리 100점 루브릭으로 측정하고, ROI 우선순위로 개선을 적용하는 플러그인.

## 설치

```
/plugin marketplace add kunsanglee/ai-ready
/plugin install ai-ready@ai-ready
```

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
