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

- **0.4.0** — *사람이 인수한 문서 보호*. 지금까지 생성 스크립트(`gen_index` / `gen_arch_diagram` / `extract_section` / `inject_module_map`)는 대상 파일을 전체 덮어썼다. 사람이 그 문서를 직접 손보며 자동 생성 시그니처를 지우면(예: `NAMING.md` / `TESTING.md` 를 권위 문서로 다듬음) 다음 apply 때 작업이 날아갔다. 신규 `managed_doc` 가드가 출력 대상에 자동 생성 시그니처(신형·구형 모두)가 없으면 덮어쓰기를 거부하고(`중단` + exit 3) `--force` 로만 우회하게 한다. 더해 `apply` 스킬은 mechanical 생성도 *문서별 diff confirm 루프*(임시 출력 → diff → 승인분만 반영)로 바꿔 무조건 덮어쓰지 않는다. 결정론 스크립트는 confirm 하지 않고(헤드리스 안전), 대화형 confirm 은 스킬 레이어가 담당하는 역할 분담. stdlib-only 유지.
- **0.3.0** — `.ai-ready/config.json` 에 `rubric` 섹션 신설 — *채점 로직이 프로젝트 현실을 존중* 하도록 확장 (지금까지 config 는 INDEX/lazy-load 생성에만 작용하고 `audit.py` 채점은 무시했음). ① `rubric.decision_records.dir_hints` 로 ADR/PRD/api-doc 을 흡수한 통합 design 디렉토리(`docs/design/`)를 의사결정 기록(rule 3.2)으로 인정, ② `rubric.api_contracts.build_deps` 로 springdoc/springfox 처럼 코드에서 OpenAPI 를 런타임 생성하는 의존성을 API 계약(rule 4.3)으로 인정. 추가로 config 없이도 — 검증 게이트(rule 5.1)가 프로젝트 레벨 `.claude/settings.json` 의 편집/커밋 시점 lint/test/format hook 을 pre-commit 과 동등한 *기계적 검증 장치* 로 인정 (AI 코딩 harness 자체가 검증 게이트라는 관점, 글로벌 `~/.claude` 는 제외). config 없으면 기존 동작 100% 유지. stdlib-only 정책 유지.
- **0.2.0** — 프로젝트별 `.ai-ready/config.json` 으로 *frontmatter 인지 INDEX 그룹화* 활성화. `gen_index.py` 가 frontmatter 의 `feature` / `aliases` / `tags` / `supersedes` 필드를 스캔해 ① 그룹별 sub-group 분류, ② 한영 자연어 query 의 1차 인덱스가 되는 cross-reference 섹션, ③ ADR 결정 진화 (supersedes/superseded-by) 그래프를 자동 빌드. `inject_lazy_load_index.py` 는 `<!-- lazy-load:user-begin -->` ~ `<!-- lazy-load:user-end -->` 마커로 사용자 수동 추가 행 보존 (v0.1.x 시한폭탄 해소 — 기존 단일 마커 환경에서도 자동 마이그레이션). config 없으면 기존 동작 100% 유지 (backward compat). stdlib-only 정책 유지 — 신규 의존성 0.
- **0.1.2** — manifest schema 오류 수정 (`repository` 가 string URL 이어야 함), 단일 모듈 프로젝트 평가/스캐폴드 분기 추가 (패키지 = 논리 모듈 관점, `docs/PACKAGES.md` 카탈로그 + 표준 레이아웃 일관성 평가), thin-index 인식, sparkline / history archive, ANTIPATTERNS 클러스터링, `.ai-ready/README.md` 자동 생성, iOS 빌드 매니페스트 지원.

### v0.2.0 config 사용법 (선택)

대상 코드베이스의 `<target>/.ai-ready/config.json` 을 만들면 활성. 없으면 v0.1.x 동작 그대로.

```json
{
  "version": 1,
  "frontmatter": {
    "required": ["type", "feature", "module", "status", "created", "updated"],
    "search":   ["aliases", "tags"],
    "evolution": ["supersedes", "superseded-by"]
  },
  "index": {
    "groups": [
      {
        "id": "adr",
        "title": "ADR (`docs/adr/`)",
        "match": { "path_prefix": "docs/adr/" },
        "sub_group_by": "feature"
      }
    ],
    "cross_reference": { "enabled": true, "title": "한영 검색 인덱스" },
    "evolution_graph": { "enabled": true, "title": "ADR 결정 진화", "scope": "adr" }
  },
  "lazy_load_triggers": {
    "detect": [
      { "path": "docs/adr/", "label": "[`docs/adr/`](docs/adr/)", "trigger": "ADR 조회" }
    ],
    "override_hardcoded": ["docs/decisions"]
  }
}
```

전체 스키마는 `plugins/ai-ready/skills/audit/scripts/config_loader.py` 의 모듈 docstring 에 정의되어 있습니다.

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
