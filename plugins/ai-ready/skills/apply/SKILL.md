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
| `single_module_mode: false` | 멀티 모듈 기본 흐름 — 핫 모듈 top-N 의 `CLAUDE.md` 초안 생성. |

매핑 테이블의 일부 룰은 *룰 이름 자체가 모드에 따라 다르다*. apply 는 `rule.name` 의 정확한 문자열로 매핑하므로 audit.json 에 들어온 이름을 그대로 키로 사용하면 된다.

## 적용 흐름

1. **목록화**: `audit.json` 의 `actions` 배열을 ROI 내림차순으로 읽고, 각 항목을 아래 매핑 테이블로 분류한다.
2. **사용자에게 계획 제시**: top-N (기본 5) 액션의 적용 방법 (mechanical / judgment / skip) 을 표로 보여주고 진행 여부 확인.
3. **순서대로 실행**:
   - mechanical → `Bash` 로 스크립트 호출, 결과 stdout 캡처, evidence 보고
   - judgment → Claude 가 대상 파일을 읽고 초안을 작성, 사용자에게 보여주고 승인받은 뒤 적용
   - skip → 이유와 함께 건너뛰기
4. **재평가**: 모두 끝나면 `ai-ready:audit` 의 `scripts/audit.py` 를 다시 돌려 점수 변화를 보고.

## 규칙 → 스크립트 매핑 테이블

각 audit 규칙 이름(`rule.name`)에 대응되는 처리 방법:

| Rule name (audit.json 기준) | 처리 방법 | 명령 |
|----------------------------|----------|------|
| 루트 CLAUDE.md 또는 AGENTS.md 존재 | **judgment** (스크립트 없음) | Claude 가 프로젝트를 훑고 50~150줄 짜리 루트 CLAUDE.md 초안 작성 → 사용자 승인 후 저장 |
| 루트 문서가 3개 이상의 모듈 경로/문서 참조 | **mechanical** | `python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/inject_module_map.py --target <T>` |
| 모듈별 CLAUDE.md 커버리지 | **mechanical** | `python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/scaffold.py --target <T> --out <T>/.ai-ready/scaffolds --top 5` |
| 루트 문서가 패키지 카탈로그 또는 3개 이상의 패키지 경로 참조 *(단일 모듈)* | **judgment** | Claude 가 루트 `CLAUDE.md` 의 '모듈 맵' 섹션에서 `docs/PACKAGES.md` lazy-load 진입 안내를 박는다 |
| 패키지 카탈로그 문서 (PACKAGES.md) 존재 + 3개 이상 패키지 섹션 *(단일 모듈)* | **mechanical+judgment** | `scaffold.py` 가 `scaffolds/PACKAGES.md` 초안 생성 → Claude 가 패키지별 TODO 라인을 패키지 코드 훑어 채움 → `docs/PACKAGES.md` 로 이동 |
| 패키지 카탈로그 문서 적정 길이 (50~300줄) *(단일 모듈)* | **judgment** | Claude 가 카탈로그를 50~300줄 범위로 다이어트하거나 패키지별 항목을 보강 |
| 논리 모듈 맵 + 표준 레이아웃 일관성 (단일 모듈) | **judgment** | (1) 카탈로그 섹션이 부족하면 위 룰 흐름. (2) 도메인 패키지 표준 레이아웃 부족 시 Claude 가 누락 디렉토리 (controller/service/domain/repository) 정렬 제안 — *코드 이동 동반* 이라 사용자 명시 승인 필수 |
| 인덱스 / MOC 파일 (docs/INDEX.md 또는 wiki/index.md) | **mechanical** | `python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/gen_index.py --target <T> --out <T>/docs/INDEX.md` — **v0.2.0+**: 대상에 `.ai-ready/config.json` 이 있으면 frontmatter 기반 그룹화 + 한영 cross-reference + ADR 진화 그래프 자동 활성. **머지 충돌 방지**: 헤더에 생성일자·대상명·문서 개수 같은 휘발성 메타를 넣지 않아(내용 동일 → 재생성 결과 동일) 브랜치 간 충돌을 없애고, `<T>/.gitattributes` 에 `<index> merge=union` 룰을 idempotent 하게 추가해 동시 추가분을 git 이 자동 union 한다 |
| 루트 CLAUDE.md 200줄 이하 | **mechanical+judgment** | thin index 패턴 권장: `python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/inject_lazy_load_index.py --target <T>` 로 lazy-load 트리거 표를 주입한 뒤, Claude 가 인라인된 detail 을 `docs/CONVENTIONS.md` / `docs/API_COMPATIBILITY.md` / `docs/ERROR_HANDLING.md` / `docs/GIT_WORKFLOW.md` / `docs/DDL_DML.md` 등으로 분리 (사용자 승인 후). **v0.2.0+**: `lazy-load:user-begin/user-end` 마커 안 사용자 수동 행은 절대 덮어쓰지 않음 (기존 마커 없는 표는 첫 실행 시 안전 마이그레이션) |
| 모듈 문서 평균 50줄 이하 | **judgment** | Claude 가 가장 긴 모듈 CLAUDE.md 를 추려 다이어트 |
| 명시적 안티패턴 / 절대 금지 가이드 존재 | **judgment** | Claude 가 `.ai-ready/scaffolds/ANTIPATTERNS.md` 와 git 핫스팟을 보고 "DO NOT" 항목 5~10개 초안 작성 |
| '사용 시점' 가이드 존재 | **mechanical+judgment** | `python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/inject_lazy_load_index.py --target <T>` 로 루트 CLAUDE.md 에 lazy-load 트리거 표 주입 (감지된 docs/ 자동 매핑). 추가로 모듈/패턴 문서에 "When to use" bullet 도 함께 추가 권장 |
| ANTIPATTERNS.md (또는 wiki/anti-patterns/) 존재 | **mechanical** | `python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/extract_antipatterns.py --target <T> --out <T>/.ai-ready/scaffolds/ANTIPATTERNS.md --days 180` (그 후 Claude 가 시드 → 실제 항목으로 변환해 `<T>/docs/ANTIPATTERNS.md` 에 채택) |
| 아키텍처 의사결정 기록 (ADR / wiki/decisions) | **judgment** | Claude 가 git history 와 README, blog 등을 훑어 ADR 3~5건 후보 제시 (`<T>/docs/decisions/00NN-*.md`) |
| 네이밍 컨벤션 문서화 | **mechanical** | `python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/extract_section.py --target <T> --out <T>/docs/NAMING.md --kind naming` |
| 모듈 의존성 맵 / 다이어그램 존재 | **mechanical** | `python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/gen_arch_diagram.py --target <T> --out <T>/docs/ARCHITECTURE.md` |
| 빌드 매니페스트로 의존 그래프 추출 가능 | **skip** | 빌드 시스템이 이미 커버 |
| 모듈 간 API 계약 문서화 (OpenAPI/proto/contracts) | **judgment (대) ** | 큰 작업 — 추천만 하고 본격 도입은 별도 세션 |
| 커밋 전 훅 (pre-commit) 존재 | **judgment** | Claude 가 husky/lefthook 중 적절한 도구 설정 제안 |
| CI 설정 존재 + 테스트 참조 | **judgment** | CI provider 에 따라 다름 — Claude 가 추천 |
| 테스트 컨벤션 문서화 (CLAUDE.md 또는 TESTING.md) | **mechanical** | `python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/extract_section.py --target <T> --out <T>/docs/TESTING.md --kind testing` |
| CLAUDE.md / 문서 갱신 훅 또는 스케줄 존재 | **mechanical** | `python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/install_hook.py --target <T>` |
| CLAUDE.md 갱신 프로토콜 문서화 | **judgment** | Claude 가 루트 CLAUDE.md 에 "## 유지보수" 섹션 추가 제안 |
| 매트릭스 문서 / 대시보드 존재 | **judgment (대)** | 측정 인프라 도입 — 별도 작업 |
| PR 리뷰 시간 / AI 사용량 / 토큰 추적 | **judgment (대)** | 추적 셋업 — 별도 작업 |

## 실행 가이드

대상 절대경로 `<T>` 를 받은 뒤:

1. `<T>/.ai-ready/audit.json` 이 없으면 먼저 `ai-ready:audit` 를 안내하고 종료.
2. `audit.json` 의 `actions` 를 읽고 위 매핑으로 (rule, kind, command) 튜플 리스트 만들기.
3. 사용자에게 **계획 표** 출력:

   ```
   다음 액션을 적용합니다 (ROI 순):
   1. [mechanical] 인덱스 / MOC 파일 — gen_index.py 실행
   2. [mechanical] 모듈 의존성 맵 — gen_arch_diagram.py 실행
   3. [judgment]   '사용 시점' 가이드 — Claude 가 초안 작성
   4. [skip]       빌드 매니페스트 — 이미 커버됨
   5. [mechanical] freshness Stop hook — install_hook.py 실행
   ```
4. mechanical 부터 일괄 실행. 각 명령마다:
   - 어떤 명령을 실행하는지 announce
   - Bash 로 호출 (timeout 적절히)
   - stdout 캡처해서 결과 보고
5. judgment 항목들은 한 번에 하나씩:
   - 관련 파일 읽기 (`Read`)
   - 초안 작성 (메시지로 보여주기)
   - 사용자 승인 대기 → 적용 (`Write`/`Edit`)
6. 모든 적용이 끝나면:
   ```
   python3 $CLAUDE_PLUGIN_ROOT/skills/audit/scripts/audit.py --target <T> --out <T>/.ai-ready
   ```
   재실행해 변화한 점수와 카테고리별 변화를 표로 보고.

## 안전 원칙

- **항상 dry-run 우선**: `inject_module_map.py` 와 같이 기존 파일을 수정하는 스크립트는 가능한 경우 `--dry-run` 으로 미리 보여준 뒤 사용자 승인 → 실제 실행.
- **judgment 항목은 항상 사용자 승인**: AI 가 임의로 컨벤션을 결정하지 않도록.
- **백업 권장**: 사용자가 git commit 하지 않은 변경이 있으면 적용 전에 안내.
- **상위 N 만 적용**: 기본 5개. 사용자가 더 많이 원하면 명시적으로 요청.
- **점수 변화 보고**: 적용 후 점수가 오르지 않거나 떨어지면 솔직하게 보고하고 원인 분석 (false negative 인지, 적용이 잘못됐는지).

## 하지 말 것

- audit.json 없이 추측으로 액션 실행
- 한 번에 여러 judgment 항목을 묶어서 처리 (사용자가 검토 못 함)
- 사용자 동의 없이 git commit / push / 외부 시스템 호출
- 적용 결과를 보지 않고 다음 액션으로 넘어가기 (실패해도 계속 가다가 누적 오류)
