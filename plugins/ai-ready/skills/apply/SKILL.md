---
name: apply
description: Apply ROI-prioritized actions from an ai-ready:audit run. Read `<target>/.ai-ready/audit.json` + `audit-report.md`, then for each top-N action either run a mechanical script (CLAUDE.md scaffolds, ANTIPATTERNS seed, INDEX.md, ARCHITECTURE.md Mermaid diagrams, freshness Stop hook install, naming/testing extraction) or apply a judgment-based change via Claude (anti-pattern entries, ADRs, "DO NOT" sections, "When to use" guides). Use this skill after the user has run ai-ready:audit and now wants to actually execute the recommended improvements rather than just read the report — invoke it whenever they say "apply the audit", "audit 적용", "ROI 액션 실행", "우선순위 액션 적용", "AI 준비도 개선 실행", "audit fix", or refer to running through the action list, even casually.
---

# AI-Ready Apply — ROI 액션 자동 실행기

`ai-ready:audit` 결과(`audit.json` + `audit-report.md`)를 읽어 ROI 상위 액션들을 차례로 적용하는 오케스트레이터입니다.

## 입력 가정

- 대상 디렉토리에 `.ai-ready/audit.json` 이 이미 존재 (`ai-ready:audit` 선행 실행)
- 절대 경로로 받은 `<target>` (사용자가 지정)

## 레이아웃 감지 (단일 vs 멀티 모듈)

`audit.json` 의 `single_module_mode` (bool) + `package_catalog` (path|null) 를 먼저 확인한다.

| 모드 | 동작 차이 |
|---|---|
| `single_module_mode: true` | (a) `scaffold.py` 가 `scaffolds/PACKAGES.md` 한 파일을 생성 → 사용자 검토 후 `docs/PACKAGES.md` 로 이동. 패키지별 `CLAUDE.md` 분산 생성하지 않는다. (b) 도메인 패키지의 표준 레이아웃 (`controller/ service/ domain/ repository/` 4개 중 3개 이상) 일관성도 평가됨 — 부족 시 `audit-report.md` 의 권고대로 정렬 권장. |
| `single_module_mode: false` | 멀티 모듈 기본 흐름 — 핫 모듈 top-N 의 `CLAUDE.md` 초안 생성. **점진 확장 정책**: 전 모듈 일괄 생성 금지 — 저빈도 모듈의 빈 스캐폴드 양산은 채움 비용과 검토일 안 갱신되는 썩는 문서만 늘린다. 대상은 핫 모듈 top-N + (대상 repo 가 living design 체계를 쓰면) `docs/design/{name}.md` 가 있는 도메인의 연관 모듈. scaffold 는 모듈의 도메인 design 문서가 존재하면 "도메인 설계 문서" 포인터 한 줄을 자동 포함한다. |

매핑 테이블의 일부 룰은 *룰 이름 자체가 모드에 따라 다르다*. apply 는 `rule.name` 의 정확한 문자열로 매핑하므로 audit.json 에 들어온 이름을 그대로 키로 사용하면 된다. 아래 표의 첫 칸은 그 문자열 그대로이고, 모드 표시 같은 부기는 둘째 칸에 둔다.

## 적용 흐름

> **핵심 원칙 — 문서는 AI 가 외과적으로 유지보수한다 (v0.5.0+).** 기계적 스크립트가 문서를 통째 재생성·덮어쓰지 않는다. 스크립트는 `--json` 으로 *사실만* 모으고(읽기 전용, 문서 안 씀), AI 가 그 사실과 *현재 문서*를 대조해 **새 항목만 더하고 바뀐 것만 고치며 사람이 정리한 그룹·순서·메모·산문은 그대로 둔다.** 변경은 사람 승인 후 `Edit`. 문서가 아예 없을 때만 사실로 초안을 통째 생성한다(보존할 게 없으므로). 의존 그래프처럼 AI 가 직접 쓰기 까다로운 것도, 스크립트가 *정확한 사실*(엣지 목록)을 주면 AI 가 그걸로 안전하게 쓴다.

1. **목록화**: `audit.json` 의 `actions` 배열을 ROI 내림차순으로 읽고, 각 항목을 아래 매핑 테이블로 분류한다.
2. **사용자에게 계획 제시**: top-N (기본 5) 액션의 적용 방법 (maintain / judgment / mechanical / skip) 을 표로 보여주고 진행 여부 확인.
3. **순서대로 실행**:
   - **maintain** (문서 외과 유지보수) → 스크립트 `--json` 으로 사실 수집(문서 안 씀) → AI 가 현재 문서 `Read` → 새 항목 추가/변경분 수정(나머지 보존) 제안 → 사용자 승인 → `Edit`. 문서 부재면 사실로 초안 생성.
   - **judgment** → AI 가 대상을 읽고 초안 작성(스크립트 없음), 사용자에게 보여주고 승인받은 뒤 적용.
   - **mechanical** (부수효과 없는 멱등 작업, 예: `install_hook.py`) → announce 후 실행, evidence 보고.
   - **skip** → 이유와 함께 건너뛰기.
4. **재평가**: 모두 끝나면 `ai-ready:audit` 의 `scripts/audit.py` 를 다시 돌려 점수 변화를 보고.

## 규칙 → 스크립트 매핑 테이블

각 audit 규칙 이름(`rule.name`)에 대응되는 처리 방법:

아래 표의 mechanical 명령은 `ai-ready:audit` 스킬 폴더의 스크립트를 부른다. **`$CLAUDE_PLUGIN_ROOT` 는 Bash 도구의 셸에 없어서**(실측) 그대로 쓰면 `/skills/audit/...` 이라는 없는 경로를 가리키므로, 그 폴더는 아래 두 줄로 유도한다. Bash 호출마다 새 셸이라 이 두 줄을 **명령과 같은 호출에 함께** 넣는다.

```bash
# 이 스킬 본문 맨 위의 "Base directory for this skill" 값을 그대로 넣는다(= .../skills/apply).
SKILL_DIR="<이 스킬 본문 첫머리의 Base directory 를 그대로 넣는다>"
AUDIT="$(cd "$SKILL_DIR/../audit" && pwd)"
[ -f "$AUDIT/scripts/audit.py" ] || { echo "apply: audit 스크립트를 못 찾았다 ($AUDIT) — base directory 확인" >&2; exit 65; }
```

| Rule name (audit.json 기준) | 처리 방법 | 명령 |
|----------------------------|----------|------|
| 루트 CLAUDE.md 또는 AGENTS.md 존재 | **judgment** (스크립트 없음) | Claude 가 프로젝트를 훑고 루트 CLAUDE.md 초안 작성 → 사용자 승인 후 저장. 분량 목표는 "루트 CLAUDE.md 상주 분량 (800~8,000바이트)" 규칙과 같은 **바이트 기준 800~8,000** — 채점이 0.8.9 부터 바이트라, 줄 수로 짓으면 한국어 문서는 줄이 적어도 초과할 수 있다 |
| 루트 문서가 3개 이상의 모듈 경로/문서 참조 | **maintain** | `inject_module_map.py --target <T> --json` → 루트 CLAUDE.md 의 '모듈 맵'·MODULE_MAP.md. 마커(`<!-- module-map -->`) 안 자동 영역만 손대고 사용자 영역은 보존 |
| 모듈별 CLAUDE.md 커버리지 | **mechanical** | `python3 "$AUDIT/scripts/scaffold.py" --target <T> --out <T>/.ai-ready/scaffolds --top 5` |
| 루트 문서가 패키지 카탈로그 또는 3개 이상의 패키지 경로 참조 | **judgment** *(단일 모듈)* | Claude 가 루트 `CLAUDE.md` 의 '모듈 맵' 섹션에서 `docs/PACKAGES.md` lazy-load 진입 안내를 박는다 |
| 패키지 카탈로그 문서 (PACKAGES.md) 존재 + 3개 이상 패키지 섹션 | **mechanical+judgment** *(단일 모듈)* | `scaffold.py` 가 `scaffolds/PACKAGES.md` 초안 생성 → Claude 가 패키지별 TODO 라인을 패키지 코드 훑어 채움 → `docs/PACKAGES.md` 로 이동 |
| 패키지 카탈로그 문서 적정 길이 (50~300줄) | **judgment** *(단일 모듈)* | Claude 가 카탈로그를 50~300줄 범위로 다이어트하거나 패키지별 항목을 보강 |
| 논리 모듈 맵 + 표준 레이아웃 일관성 (단일 모듈) | **judgment** | (1) 카탈로그 섹션이 부족하면 위 룰 흐름. (2) 도메인 패키지 표준 레이아웃 부족 시 Claude 가 누락 디렉토리 (controller/service/domain/repository) 정렬 제안 — *코드 이동 동반* 이라 사용자 명시 승인 필수 |
| 인덱스 / MOC 파일 (docs/INDEX.md 또는 wiki/index.md) | **maintain** | `gen_index.py --target <T> --json` → docs/INDEX.md. **v0.2.0+**: `.ai-ready/config.json` 있으면 사실에 frontmatter 가 포함돼 그룹화 판단에 쓴다 |
| 루트 CLAUDE.md 상주 분량 (800~8,000바이트) | **maintain+judgment** | thin index 패턴: `inject_lazy_load_index.py --target <T> --json` → 루트 CLAUDE.md 의 lazy-load 표. 자동 마커 안에만 새 트리거를 넣고 `lazy-load:user-begin/user-end` 사용자 행은 절대 안 건드린다. 사용자 영역이 이미 가리키는 문서는 auto 표에 넣지 않는다 — 루트 문서는 always-loaded 라 같은 문서를 두 표가 각각 가리키면 그 중복분을 매 세션 낸다(스크립트 쓰기 모드는 자동으로 뺀다). 사실 JSON 의 `self_evident: true` 항목은 파일명이 곧 트리거라 표 행 대신 링크 한 줄로 묶는다. 판정이 바이트 기준이라 **줄 수를 줄여도 한 줄이 길면 통과하지 못한다** — 긴 불릿은 쪼개지 말고 `docs/CONVENTIONS.md` 등으로 내보낸다(사용자 승인 후). 하한 800바이트가 있어 과하게 줄여 루트가 지도 역할을 잃으면 감점이므로, 내보낸 문서로 가는 트리거는 루트에 남긴다. (v0.8.7·v0.8.9·v0.9.0 에서 차례로 들어온 규칙) |
| 모듈 문서 평균 길이 (10~50줄) | **judgment** | Claude 가 가장 긴 모듈 CLAUDE.md 를 추려 다이어트하고, 평균이 10줄 미만이면 반대로 스텁을 채운다 (**v0.9.0+** 하한). **보존 가드**: "도메인 설계 문서" 포인터 줄 (`docs/design/{name}.md` 참조) 은 다이어트 대상에서 제외 — design 문서가 있는 도메인의 모듈엔 반드시 포인터가 남아야 한다 (불변식) |
| 명시적 안티패턴 / 절대 금지 가이드 존재 | **judgment** | Claude 가 `.ai-ready/scaffolds/ANTIPATTERNS.md` 와 git 핫스팟을 보고 "DO NOT" 항목 5~10개 초안 작성 |
| '사용 시점' 가이드 존재 | **maintain+judgment** | `inject_lazy_load_index.py --target <T> --json` → 루트 CLAUDE.md 의 lazy-load 표(자동 마커 안, 사용자 행은 보존). 추가로 모듈/패턴 문서에 "When to use" bullet 도 함께 넣기를 권장 |
| ANTIPATTERNS.md (또는 wiki/anti-patterns/) 존재 | **mechanical** | `python3 "$AUDIT/scripts/extract_antipatterns.py" --target <T> --out <T>/.ai-ready/scaffolds/ANTIPATTERNS.md --days 180` (그 후 Claude 가 시드 → 실제 항목으로 변환해 `<T>/docs/ANTIPATTERNS.md` 에 채택) |
| 아키텍처 의사결정 기록 (ADR / wiki/decisions) | **judgment** | Claude 가 git history 와 README, blog 등을 훑어 ADR 3~5건 후보 제시 (`<T>/docs/decisions/00NN-*.md`). *이미 design 통합 문서 등으로 결정을 기록 중이면* `.ai-ready/config.json` 의 `rubric.decision_records.dir_hints` 에 그 디렉토리를 선언해 인정시키는 게 우선 |
| 네이밍 컨벤션 문서화 | **maintain** | `extract_section.py --target <T> --kind naming --json` → docs/NAMING.md |
| 모듈 의존성 맵 / 다이어그램 존재 | **maintain** | `gen_arch_diagram.py --target <T> --json` → docs/ARCHITECTURE.md 의 Mermaid. 엣지는 스크립트가 준 것만 쓰고 지어내지 않는다 |
| 빌드 매니페스트로 의존 그래프 추출 가능 | **skip** | 빌드 시스템이 이미 커버 |
| 모듈 간 API 계약 문서화 (OpenAPI/proto/contracts) | **judgment (대)** | 큰 작업 — 추천만 하고 본격 도입은 별도 세션. *springdoc/springfox 처럼 코드에서 OpenAPI 를 런타임 생성 중이면* `.ai-ready/config.json` 의 `rubric.api_contracts.build_deps` 에 선언해 인정시키는 게 우선 |
| 기계적 검증 훅 (pre-commit / AI 에이전트 hook) | **judgment** | AI 코딩 환경이면 `.claude/settings.json` PostToolUse(편집 후 ktlint/format)·PreToolUse(커밋 전 test/check) hook 을 먼저 제안. 추가 안전망으로 lefthook pre-commit / CI. 글로벌(~/.claude) 말고 *프로젝트* 설정에 둘 것 |
| CI 설정 존재 + 테스트 참조 | **judgment** | CI provider 에 따라 다름 — Claude 가 추천 |
| 테스트 컨벤션 문서화 (CLAUDE.md 또는 TESTING.md) | **maintain** | `extract_section.py --target <T> --kind testing --json` → docs/TESTING.md |
| CLAUDE.md / 문서 갱신 훅 또는 스케줄 존재 | **mechanical** | `python3 "$AUDIT/scripts/install_hook.py" --target <T>` |
| CLAUDE.md 갱신 프로토콜 문서화 | **judgment** | Claude 가 루트 CLAUDE.md 에 "## 유지보수" 섹션 추가 제안 |
| 매트릭스 문서 / 대시보드 존재 | **judgment (대)** | 측정 인프라 도입 — 별도 작업 |
| PR 리뷰 시간 / AI 사용량 / 토큰 추적 | **judgment (대)** | 추적 셋업 — 별도 작업 |

## 실행 가이드

대상 절대경로 `<T>` 를 받은 뒤:

1. `<T>/.ai-ready/audit.json` 이 없으면 먼저 `ai-ready:audit` 를 안내하고 종료.
2. `audit.json` 의 `actions` 를 읽고 위 매핑으로 (rule, kind, command) 튜플 리스트 만들기.
3. 액션별 적용 방법(maintain / judgment / mechanical / skip)을 **계획 표**로 보여주고 진행 여부를 확인한다.
4. **maintain** 액션(`gen_index` / `gen_arch_diagram` / `extract_section` / `inject_module_map` / `inject_lazy_load_index`)은 일괄 실행하지 말고 **문서별로 한 번에 하나씩** 처리한다. 절차는 위 "적용 흐름" 3번의 maintain 과 같다.
5. judgment 항목들은 한 번에 하나씩:
   - 관련 파일 읽기 (`Read`)
   - 초안 작성 (메시지로 보여주기)
   - 사용자 승인 대기 → 적용 (`Write`/`Edit`)
6. 모든 적용이 끝나면 (`$AUDIT` 유도 두 줄을 같은 Bash 호출에 함께 넣는다 — 호출마다 새 셸이라 앞 호출의 값이 안 남는다):
   ```
   python3 "$AUDIT/scripts/audit.py" --target <T> --out <T>/.ai-ready
   ```
   재실행해 변화한 점수와 카테고리별 변화를 표로 보고.

## 안전 원칙

- **문서 유지보수는 AI 외과적 (v0.5.0+)**: maintain 액션은 스크립트 `--json` 이 모은 사실(의존 엣지·문서 요약·섹션)만 받아 AI 가 현재 문서를 *부분 수정*한다. 새 항목 추가와 바뀐 값 수정만 하고 사람이 정리한 그룹·순서·메모·산문은 보존한다. 통째 `Write` 는 대상 문서가 없을 때뿐이고, 있으면 항상 `Edit`. AI 가 엣지·요약을 지어내지 않는다.
- **레거시 쓰기 모드 가드 (v0.4.0)**: 스크립트의 `--out` 직접 쓰기 모드는 부재 문서 부트스트랩용으로 남아 있고, 여전히 `managed_doc` 가드로 사람 인수 문서(서명 없는)는 거부(exit 3)한다. apply 의 maintain 흐름은 이 쓰기 모드를 쓰지 않으니 보통 마주칠 일이 없다 — 마주치면 `--force` 우회 전에 사용자 확인.
- **git 을 못 읽으면 exit 4**: `extract_antipatterns.py` 는 대상이 git 저장소가 아니거나 `git` 실행에 실패하면 exit 4 로 끝내고 문서를 쓰지 않는다. "이력을 읽었는데 뽑을 것이 없었다" 와 다른 결과이므로 빈 결과로 삼키지 말고 그대로 보고한다(사람 인수 문서 거부는 exit 3).
- **judgment 항목은 항상 사용자 승인**: AI 가 임의로 컨벤션을 결정하지 않도록.
- **백업 권장**: 사용자가 git commit 하지 않은 변경이 있으면 적용 전에 안내.
- **상위 N 만 적용**: 기본 5개. 사용자가 더 많이 원하면 명시적으로 요청.
- **점수 변화 보고**: 적용 후 점수가 오르지 않거나 떨어지면 솔직하게 보고하고 원인 분석 (false negative 인지, 적용이 잘못됐는지).

## 하지 말 것

- audit.json 없이 추측으로 액션 실행
- 한 번에 여러 judgment 항목을 묶어서 처리 (사용자가 검토 못 함)
- 사용자 동의 없이 git commit / push / 외부 시스템 호출
- 적용 결과를 보지 않고 다음 액션으로 넘어가기 (실패해도 계속 가다가 누적 오류)
