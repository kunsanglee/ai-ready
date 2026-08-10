#!/usr/bin/env python3
"""
AI-Ready Codebase Audit — 채점 엔진.

대상 코드베이스를 스캔하고 RUBRIC.md에 정의된 7-카테고리 100점 루브릭을 적용해
다음을 작성합니다.
  - audit.json       (기계 판독용 점수 + 근거)
  - audit-report.md  (사람 판독용 리포트 + ROI 액션 리스트)

stdlib만 사용. 실행:
  python3 audit.py --target /path/to/repo --out /path/to/repo/.ai-ready
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# config_loader (v0.3.0+) — 같은 scripts/ 디렉토리. 절대경로 실행 대비 sys.path 보강.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
from config_loader import (  # noqa: E402
    load_config, decision_record_hints, api_contract_build_deps,
    antipattern_doc_hints, naming_doc_hints,
)
# 논리 모듈 기준점은 스택마다 다르다. 그 답을 이 파일에 두지 않고 어댑터에 묻는다 —
# 종전에는 이 파일과 scaffold.py 가 각자 JVM 으로만 하드코딩해 두 벌로 갈라져 있었다.
import stacks  # noqa: E402

# --- Constants -------------------------------------------------------------

BUILD_MANIFESTS = {
    "build.gradle.kts", "build.gradle", "pom.xml",
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
    # iOS / Apple
    "Package.swift",   # Swift Package Manager
    "Podfile",         # CocoaPods
}

CLAUDE_DOC_NAMES = {"CLAUDE.md", "AGENTS.md"}
ANTIPATTERN_NAMES = {"ANTIPATTERNS.md", "ANTI_PATTERNS.md", "anti-patterns.md"}
ARCH_NAMES = {"ARCHITECTURE.md", "DEPENDENCIES.md", "dependencies.md"}
NAMING_NAMES = {"NAMING.md", "naming.md"}

# 단일 모듈 프로젝트에서 모듈 CLAUDE.md 대체 역할을 하는 카탈로그 문서.
# 패키지(=논리 모듈) 별 진입점·흐름·외부 IO·함정을 한 문서에 모아둔 형태.
PACKAGE_CATALOG_CANDIDATES = (
    "docs/PACKAGES.md", "docs/packages.md",
    "PACKAGES.md", "packages.md",
    "docs/PACKAGE_CATALOG.md", "docs/MODULES.md",
)

# 단일 모듈 프로젝트에서 도메인 패키지가 따라야 하는 표준 레이아웃 디렉토리.
# 4개 중 3개 이상을 가지면 "표준 레이아웃 준수" 로 판정.
STANDARD_LAYOUT_DIRS = ("controller", "service", "domain", "repository")

# 하위 매니페스트 없이 워크스페이스 선언만 있는 모노레포(Nx/Turbo 등) 감지용.
# 이들이 루트에 있으면 하위 빌드 매니페스트가 안 잡혀도 멀티 모듈로 본다.
WORKSPACE_MARKERS = ("pnpm-workspace.yaml", "nx.json", "turbo.json", "go.work")

# 단일 모듈의 논리 모듈 기준점은 stacks.py 의 어댑터가 답한다(JVM·Node·Python·Go·Rust).

# M-1: ADR 디렉토리 — strict는 단독으로도 인정, loose는 .md 파일 ≥2개 필요
ADR_DIR_HINTS_STRICT = ("docs/adr", "doc/adr", "wiki/decisions", "docs/decisions")
ADR_DIR_HINTS_LOOSE = ("adr",)

# M-3: 성과 지표 디렉토리/파일 정확 매칭
OUTCOME_DIR_NAMES = {"token-usage", "ai-usage", "pr-metrics", "pr_review_time"}
OUTCOME_FILE_NAMES = {
    "token-usage.md", "token-usage.csv", "ai-usage.md", "ai-usage.csv",
    "pr-metrics.md", "pr-metrics.csv", "metrics.md",
}

CI_FILES = (
    ".github/workflows", ".gitlab-ci.yml", ".circleci/config.yml",
    "Jenkinsfile", "azure-pipelines.yml", ".buildkite",
    # 추가 CI provider — Bitbucket / Travis / Drone / AppVeyor / Cloud Build
    "bitbucket-pipelines.yml", ".travis.yml", ".drone.yml",
    "appveyor.yml", "cloudbuild.yaml", "cloudbuild.yml",
)

PRECOMMIT_FILES = (
    ".husky", ".git/hooks/pre-commit", "lefthook.yml", ".pre-commit-config.yaml",
)

EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache",
    ".ai-ready",  # 자기 산출물 자기참조 차단 — scaffolds/CLAUDE.md 가 점수에 섞이지 않도록
    "worktrees",  # git worktree(.claude/worktrees) = repo 전체 복사본 — 통째 중복 수집 방지
}

# 명시적 DO-NOT 가이드를 나타내는 표현 (다국어)
# 한국어는 word boundary 가 잘 동작 안 하므로 명령형 종결을 명시해 false positive 줄임
DONOT_PATTERNS = [
    r"\bDO NOT\b", r"\bMUST NOT\b",
    # NEVER / DON'T 는 흔한 단어라 산문 한가운데(예: "would never recommend")서 오탐난다.
    # 줄 시작(텍스트 시작 또는 개행 뒤)·헤더/리스트 마커 뒤의 *가이드 위치* 에서만 인정한다.
    # (regex_any 는 IGNORECASE 만 쓰고 MULTILINE 은 안 써서 ^ 가 텍스트 시작만 잡으므로 \n 을 함께 둔다.)
    r"(?:^|\n)\s*(?:[#*\->]+\s*)?(?:NEVER|DON'?T)\b",
    r"절대\s*(?:하지|금지|하면)", r"(?:^|\s|[#*\-])금지(?:\b|[\s.…!,;:])",
    r"하지\s*마(?:라|세요|십시오|요)", r"하면\s*안\s*(?:됩|돼)",
    r"❌", r"⛔",
]

USAGE_PATTERNS = [
    r"\bWhen to use\b", r"\bUse this\b",
    r"사용\s*시점", r"언제\s*사용", r"적용\s*시점",
]

# M-2: 규칙 "CLAUDE.md / 문서 갱신 훅 또는 스케줄 존재" — 좁은 키워드만 인정
FRESHNESS_KEYWORDS = ("claude.md", "agents.md", "freshness_check", "ai-ready")

# 루트 CLAUDE.md 상주 분량 임계값 (규칙 이름은 아래 ROOT_DOC_SIZE_RULE).
# v0.8.9 이전에는 줄 수로 쟀는데(200줄 이하 만점), 한국어 마크다운에서는 한 줄이 곧 표 한 행이거나
# 문단 하나라 줄 수가 비용의 대리 지표가 되지 못한다. 실측 사례: 46줄인데 12,029바이트인 루트 문서
# (한 불릿이 2,002자) 가 200줄 규칙에서 만점을 받으면서 계속 부풀었다. 바이트는 한글 3 / 영문 1 이라
# 토큰 비중에 더 가까워 always-loaded 비용의 근사로 쓴다.
# 8,000 기준은 정리를 마친 실제 레포(7,058바이트)가 통과하고 그 직전 상태(9,781)는 감점되는 자리다.
# 하한 800 은 v0.9.0 추가 — 상한만 있으면 0바이트짜리 루트 문서가 만점을 받는다. 실측한
# 실제 프로젝트 문서 최소가 887바이트라 그 바로 아래에 두어 스텁만 걸리고 얇은 지도는 통과한다.
ROOT_DOC_MIN_BYTES = 800
ROOT_DOC_MAX_BYTES = 8_000
ROOT_DOC_WARN_BYTES = 12_000
ROOT_DOC_SIZE_RULE = f"루트 CLAUDE.md 상주 분량 ({ROOT_DOC_MIN_BYTES:,}~{ROOT_DOC_MAX_BYTES:,}바이트)"

# 모듈 문서 평균 길이 범위 (v0.9.0). 상한 50 은 종전 규칙 그대로고 하한 10 이 새로 붙었다.
# 종전에는 "평균 50줄 이하" 라 세 줄짜리 스텁 묶음이 가장 좋은 점수를 받았다. 같은 규칙의
# 단일 모듈 버전이 이미 50~300줄 *범위* 를 요구하므로 그 비대칭을 없앤 것이기도 하다.
MODULE_DOC_MIN_LINES = 10
MODULE_DOC_MAX_LINES = 50
MODULE_DOC_LEN_RULE = f"모듈 문서 평균 길이 ({MODULE_DOC_MIN_LINES}~{MODULE_DOC_MAX_LINES}줄)"

# 문서 스텁 판정 하한 (v0.9.0). 실측: 실제 프로젝트 문서 최소가 887바이트 / 비공백 16줄이고
# 껍데기 스텁은 8바이트 / 3줄이었다. 400바이트 + 비공백 8줄은 그 사이를 가르는 자리다.
# 두 조건을 AND 로 요구하는 이유는 어느 한쪽만 보면 우회되기 때문이다 — 바이트만 보면 아주 긴
# 한 줄로, 줄 수만 보면 한 글자짜리 줄 여럿으로 넘길 수 있다. 둘 다 넘기려면 줄당 평균
# 50바이트의 실제 문장이 필요하다.
DOC_MIN_BYTES = 400
DOC_MIN_LINES = 8


# --- Helpers --------------------------------------------------------------

def line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def byte_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _has_min_content(path: Path, min_lines: int = DOC_MIN_LINES,
                     min_bytes: int = DOC_MIN_BYTES) -> bool:
    """파일이 실질 내용을 가졌는지(0바이트·스텁 문서 구분).

    비-공백 줄 수가 min_lines 이상이고 **동시에** 파일 크기가 min_bytes 이상이어야 True.
    존재만으로 만점을 주던 규칙(ANTIPATTERNS/NAMING/ARCHITECTURE/TESTING/ADR/INDEX 등)이
    빈 껍데기 문서에 점수를 주지 않게 하는 최소 품질 게이트다. 임계값 근거는
    DOC_MIN_BYTES 주석 참조. BOM 은 utf-8-sig 로 투명 제거.

    이진 파일은 거른다 — errors="replace" 로 읽으면 무작위 바이너리도 개행 바이트 덕에
    줄 수 조건을 넘어, 스텁 ADR 옆 이미지 하나가 게이트를 통과시켰다(2회차 적대 검토 발견 3).
    앞 8KB 에 NUL 바이트가 있으면 텍스트가 아닌 것으로 본다.
    """
    if byte_size(path) < min_bytes:
        return False
    try:
        with path.open("rb") as f:
            if b"\x00" in f.read(8192):
                return False
        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
            return sum(1 for ln in f if ln.strip()) >= min_lines
    except OSError:
        return False


# 디렉토리 실질 게이트가 문서로 세는 확장자. rglob 전체를 세면 이미지·아카이브 같은
# 이진 파일이 게이트를 대신 통과시키므로 텍스트 문서류로 한정한다(2회차 적대 검토 발견 3).
TEXT_DOC_SUFFIXES = {".md", ".txt", ".rst", ".adoc", ".yaml", ".yml", ".json", ".proto"}


def _has_substantive_content(path: Path) -> bool:
    """파일이면 _has_min_content, 디렉토리면 그 안에 실질 내용을 가진 문서가 하나라도 있는지.

    ADR 디렉토리·contracts 디렉토리처럼 "존재하면 만점" 이던 대상에 같은 스텁 게이트를 걸기 위한 것.
    디렉토리는 TEXT_DOC_SUFFIXES 확장자 파일만 센다.
    """
    if path.is_dir():
        try:
            return any(p.is_file() and p.suffix.lower() in TEXT_DOC_SUFFIXES
                       and _has_min_content(p) for p in path.rglob("*"))
        except OSError:
            return False
    return _has_min_content(path)


def _reference_target_counts(target: Path, ref: str) -> bool:
    """루트 문서가 참조한 경로가 점수 근거로 성립하는지 — 실재해야 하고, 파일이면 스텁이 아니어야 한다.

    존재하지 않는 경로 3개로도 경로 참조 규칙이 만점을 주던 구멍을 막는다(2회차 적대 검토 발견 2).
    앵커(#…)와 끝 슬래시는 떼고 본다. 디렉토리는 존재로 충분하다 — 스텁 우회의 주 벡터가 아니고,
    src/ 같은 큰 트리를 rglob 로 실질 검사하는 비용이 크다. 파일은 _has_min_content 게이트를
    적용해 스텁 문서를 가리키는 링크도 참조 수에서 뺀다.
    """
    p = target / ref.split("#")[0].rstrip("/")
    if p.is_dir():
        return True
    return p.is_file() and _has_min_content(p)


# 의존성 "선언 줄" 판정 키워드 — gradle(kts/groovy)·maven. plugins/dependencies 같은
# 블록 구조 키워드는 넣지 않는다(빈 매니페스트의 구조 줄에 올라타는 우회를 막는 것이 목적).
DEP_DECLARATION_MARKERS = (
    "implementation", "compileonly", "runtimeonly", "testimplementation",
    "api(", "api '", 'api "', "classpath", "kapt", "ksp", "annotationprocessor",
    "id(", "id '", 'id "',
    "<artifactid>", "<groupid>", "<dependency>",
)


def _line_declares_dependency(line: str, dep: str) -> bool:
    """(소문자로 넘어온) 매니페스트 한 줄이 dep 를 *의존성 선언으로* 담고 있는가.

    config rubric.api_contracts.build_deps 는 부분 문자열 매칭이어서, 빈 매니페스트의 구조
    키워드(`plugins {}`)에 "plugins" 를 선언해 올라타는 자기신고 우회가 가능했다(2회차 적대
    검토 발견 1). gradle/maven 선언 키워드가 있는 줄, 또는 `"dep": …` / `dep = …` / `dep: …`
    꼴의 키 선언 줄(package.json·Cargo.toml·pyproject 류)만 인정한다. 애매하면 인정하지 않는
    쪽으로 진다 — 버전 카탈로그(libs.versions.toml) 같은 간접 선언은 못 알아보는 한계를 감수한다.
    """
    if dep not in line:
        return False
    if any(m in line for m in DEP_DECLARATION_MARKERS):
        return True
    pat = re.escape(dep)
    return re.search(rf"""(?:["']{pat}[\w.\-]*["']\s*:|^\s*{pat}[\w.\-]*\s*[=:])""", line) is not None


def count_guide_lines(text: str, patterns: list[str]) -> int:
    """patterns 중 하나라도 걸리는 줄의 개수. 한 줄에 여러 패턴이 걸려도 1로 센다.

    "절대 금지" 처럼 한 표현이 두 패턴에 동시에 매칭되는 경우가 있어 매칭 횟수를 그대로 세면
    부풀려진다. 가이드는 한 줄에 규칙 하나가 권장 형태이므로 줄을 세는 것이 실제 분량에 가깝다.
    """
    return sum(1 for ln in text.splitlines()
               if any(re.search(p, ln, re.IGNORECASE) for p in patterns))


# DO-NOT 줄의 "구체성" 신호 — 백틱 코드 참조, 경로 꼴, CamelCase·snake_case 식별자.
# 금지 줄을 줄 수로만 세면 "금지" 라는 단어를 세 번 적는 것이 최적 전략이 된다(2회차 적대
# 검토 실증). 모델이 따를 수 있는 금지는 무엇을 하지 말라는지 대상을 가리키는 줄이므로,
# 만점은 레포 특정 지시어를 담은 줄로만 센다. 실측(2026-07): agent 92→50줄,
# c8c-api 378→242줄로 두 실레포 모두 만점 기준(3줄)을 크게 웃돌아 점수 무변동이고,
# 탈락분은 섹션 제목("## 불변식 (DO NOT)")과 막연한 문장뿐이다.
SPECIFIC_GUIDE_PATTERNS = [
    r"`[^`]+`",                      # 백틱 코드 참조
    r"\b[\w.\-]+/[\w.\-/]+\b",       # 경로 꼴 (a/b)
    r"\b[A-Z][a-z0-9]+[A-Z]\w*\b",   # CamelCase 식별자
    r"\b\w+_\w+\b",                  # snake_case 식별자
]


def count_specific_guide_lines(text: str, patterns: list[str]) -> int:
    """patterns 에 걸리는 줄 중 SPECIFIC_GUIDE_PATTERNS 구체성 신호도 담은 줄의 개수."""
    return sum(1 for ln in text.splitlines()
               if any(re.search(p, ln, re.IGNORECASE) for p in patterns)
               and any(re.search(sp, ln) for sp in SPECIFIC_GUIDE_PATTERNS))


# 도메인 용어집(glossary) 후보 — 규칙 "네이밍 컨벤션 문서화" 의 자산으로 인정.
GLOSSARY_CANDIDATES = ["docs/glossary.md", "docs/GLOSSARY.md", "GLOSSARY.md", "wiki/glossary.md"]


def has_any_path(target: Path, candidates) -> list[str]:
    """T-6: case-insensitive FS 에서 같은 파일이 두 candidate 모두 매칭되는 경우 dedupe.

    inode + device 비교가 가장 정확 (realpath 는 case 보존이라 macOS APFS 에서 dedupe 실패).
    """
    found = []
    seen_keys = set()
    for c in candidates:
        p = target / c
        if not p.exists():
            continue
        try:
            st = p.stat()
            key = (st.st_dev, st.st_ino)
        except OSError:
            key = os.path.realpath(p).lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        found.append(c)
    return found


def _walk_onerror(_err: OSError) -> None:
    """T-8: os.walk 의 PermissionError 등 fail-soft. 에러 무시하고 다음 디렉토리로."""
    return None


def regex_any(text: str, patterns: list[str]) -> bool:
    """T-8: case-insensitive — Don't / DO NOT / dont / don't 모두 매칭."""
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


# --- Single-module helpers ------------------------------------------------

def find_package_catalog(target: Path) -> Path | None:
    """단일 모듈 프로젝트의 패키지 카탈로그 문서 (PACKAGES.md 등) 를 찾는다."""
    for candidate in PACKAGE_CATALOG_CANDIDATES:
        p = target / candidate
        if p.is_file():
            return p
    return None


def count_package_sections(catalog_text: str) -> int:
    """카탈로그 문서 안의 패키지 섹션 개수.

    헤더 패턴 후보:
      ### `packagename/` ...
      ### packagename — ...
      ### `packagename` ...
      ## packagename/ ...
    """
    # 백틱으로 감싼 코드형 패키지명만 신뢰한다. em-dash 패턴(`## 이름 —`)은
    # `## 개요 —`·`## Architecture —` 같은 산문 헤더까지 패키지 섹션으로 오인해
    # 섹션 수를 부풀렸다(카탈로그 섹션 수를 보는 두 규칙의 점수 인플레) — 제거.
    patterns = [
        r"^#{2,4}\s+`[\w\-]+/`",       # ### `enrollment/`
        r"^#{2,4}\s+`[\w\-]+`",        # ### `enrollment`
    ]
    count = 0
    for line in catalog_text.splitlines():
        if any(re.match(p, line) for p in patterns):
            count += 1
    return count


def is_single_module(modules: list[Path], target: Path | None = None) -> bool:
    """build manifest 가 루트에만 있는 단일 모듈 프로젝트인지.

    하위 매니페스트가 없더라도 워크스페이스 선언(pnpm-workspace.yaml·nx.json·turbo.json·
    go.work)이 루트에 있으면 멀티 모듈로 본다 — Nx/Turbo 는 하위 프로젝트를 package.json
    없이 project.json 등으로 정의해 매니페스트 스캔만으론 단일로 오분류되기 때문. target 을
    안 넘기면 기존 동작(매니페스트 위치만)."""
    non_root = [m for m in modules if str(m) not in (".", "")] if modules else []
    single = len(non_root) == 0
    if single and target is not None and any((target / w).is_file() for w in WORKSPACE_MARKERS):
        return False
    return single


def _rglob_excluded(path: Path, root: Path) -> bool:
    """rglob 결과 path 가 root 기준 EXCLUDE_DIRS(build·target·.gradle 등) 안에 있으면 True.

    scan_target 의 단일 walk 는 EXCLUDE_DIRS 를 거르지만 find_base_package·
    find_domain_packages 는 별도 rglob 을 돌려 그 방어를 우회한다. build/generated 의
    생성물(Q타입·생성 Controller 등)이 섞이면 clean/dirty 상태에 따라 점수가 흔들리므로
    여기서 되거른다.
    """
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(p in EXCLUDE_DIRS for p in parts)


def find_base_package(target: Path) -> Path | None:
    """논리 모듈의 부모 디렉토리를 찾는다. 스택별 판정은 stacks.py 가 한다.

    JVM 이면 Application 클래스가 있는 base package, Node 면 `src/`, Python 이면
    배포 패키지 디렉토리가 나온다. 산출물 제외와 마커 결정성(rglob 순서 미보장 대비)도
    어댑터가 함께 책임진다.
    """
    layout = stacks.detect_layout(target)
    return layout.source_root if layout is not None else None


def find_domain_packages(base: Path) -> list[Path]:
    """base package 의 직속 자식 중 Controller 파일을 *하나라도* 포함하는 도메인 패키지.

    build/generated 등 산출물의 생성 Controller(예: build/gen/*Controller.kt)는 제외해
    도메인 패키지 수가 clean/dirty 상태에 따라 부풀지 않게 한다.
    """
    if not base.is_dir():
        return []
    out = []
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.name.startswith(".") or child.name in EXCLUDE_DIRS:
            continue
        try:
            hits = (f for f in child.rglob("*Controller.*") if not _rglob_excluded(f, child))
            if next(hits, None) is not None:
                out.append(child)
        except OSError:
            continue
    return out


def standard_layout_coverage(domain_packages: list[Path]) -> tuple[int, int]:
    """도메인 패키지 중 표준 레이아웃 4개 중 3개 이상 보유한 패키지의 비율.

    Returns (compliant_count, total_count).
    """
    if not domain_packages:
        return 0, 0
    compliant = 0
    for pkg in domain_packages:
        present = sum(1 for d in STANDARD_LAYOUT_DIRS if (pkg / d).is_dir())
        if present >= 3:
            compliant += 1
    return compliant, len(domain_packages)


# --- Single-pass scanner (M-5) -------------------------------------------

def scan_target(target: Path, cfg: dict | None = None) -> dict:
    """단일 walk로 모든 산출물을 한 번에 수집 (M-5).

    돌려주는 dict:
      - modules: list[Path]  빌드 매니페스트가 있는 디렉토리
      - claude_docs: list[Path]  CLAUDE.md / AGENTS.md
      - antipattern_docs: list[Path]
      - arch_docs: list[Path]
      - naming_docs: list[Path]
      - adr_dirs: list[str]  실제 markdown이 있는 ADR 디렉토리
      - proto_files: list[Path]
      - outcome_paths: list[str]  metrics 등
      - api_build_deps: list[str]  config 선언 API 계약 빌드 의존성 중 실제 감지된 것

    cfg (v0.3.0+): .ai-ready/config.json 의 rubric 섹션. None 이면 기존 동작 (backward compat).
    """
    out = {
        "modules": [],
        "claude_docs": [],
        "antipattern_docs": [],
        "arch_docs": [],
        "naming_docs": [],
        "adr_dirs": [],
        "adr_config_dirs": [],
        "proto_files": [],
        "outcome_paths": [],
        "api_build_deps": [],
    }
    seen_modules = set()

    # config 기반 채점 입력 (v0.3.0+) — cfg=None 이면 빈 리스트라 기존 동작 그대로.
    # config 선언으로 인정된 ADR 디렉토리는 따로 표시한다 — 자기신고 인정분을 리포트에
    # 드러내기 위한 것(2회차 적대 검토 발견 1의 투명성 조치).
    config_adr_hints = set(decision_record_hints(cfg))
    adr_hints_strict = tuple(ADR_DIR_HINTS_STRICT) + tuple(config_adr_hints)
    contract_deps = api_contract_build_deps(cfg)

    for dirpath, dirnames, filenames in os.walk(target, onerror=_walk_onerror):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        rel_dir = Path(dirpath).relative_to(target)
        rel_str = str(rel_dir).lower().replace("\\", "/")

        # ADR 디렉토리 감지 (M-1) — config decision_records.dir_hints (예: docs/design) 포함
        is_adr = False
        for hint in adr_hints_strict:
            if rel_str == hint or rel_str.endswith("/" + hint):
                if any(f.endswith(".md") for f in filenames):
                    out["adr_dirs"].append(str(rel_dir))
                    if hint in config_adr_hints:
                        out["adr_config_dirs"].append(str(rel_dir))
                is_adr = True
                break
        if not is_adr:
            for hint in ADR_DIR_HINTS_LOOSE:
                if rel_str == hint or rel_str.endswith("/" + hint):
                    md_count = sum(1 for f in filenames if f.endswith(".md"))
                    if md_count >= 2:
                        out["adr_dirs"].append(str(rel_dir))
                    break

        # 모듈 감지 (빌드 매니페스트 존재)
        if any(f in BUILD_MANIFESTS for f in filenames):
            if rel_dir not in seen_modules:
                seen_modules.add(rel_dir)
                out["modules"].append(rel_dir)
            # config 선언 API 계약 의존성 (예: springdoc) 을 매니페스트에서 감지 (M-1, v0.3.0+).
            # 파일 전체 부분 문자열이 아니라 *의존성 선언 줄* 에서만 인정한다 —
            # 근거는 _line_declares_dependency docstring (2회차 적대 검토 발견 1).
            if contract_deps:
                for f in filenames:
                    if f in BUILD_MANIFESTS:
                        for line in read_text(Path(dirpath) / f).lower().splitlines():
                            for dep in contract_deps:
                                if dep not in out["api_build_deps"] \
                                        and _line_declares_dependency(line, dep):
                                    out["api_build_deps"].append(dep)

        # 성과 지표 디렉토리 (M-3) — 정확 매칭
        for d in dirnames:
            if d in OUTCOME_DIR_NAMES:
                out["outcome_paths"].append(str(rel_dir / d))

        # 파일 단위 검사
        for f in filenames:
            full = Path(dirpath) / f
            if f in CLAUDE_DOC_NAMES:
                out["claude_docs"].append(full)
            if f in ANTIPATTERN_NAMES:
                out["antipattern_docs"].append(full)
            if f in ARCH_NAMES:
                out["arch_docs"].append(full)
            if f in NAMING_NAMES:
                out["naming_docs"].append(full)
            if f.endswith(".proto"):
                out["proto_files"].append(full)
            if f in OUTCOME_FILE_NAMES:
                out["outcome_paths"].append(str(rel_dir / f))

    out["modules"].sort(key=str)
    return out


# --- Rule helpers ---------------------------------------------------------

class Rule:
    def __init__(self, name: str, max_points: int):
        self.name = name
        self.max = max_points
        self.points = 0
        self.evidence: list[str] = []
        self.note: str = ""

    def award(self, points: int, evidence: list[str] | None = None, note: str = ""):
        self.points = min(self.max, self.points + points)
        if evidence:
            self.evidence.extend(evidence)
        if note:
            self.note = note
        # RUBRIC 불변식: 부여 점수는 재검증 가능한 근거(파일 경로/측정)를 가져야 한다.
        # 근거도 노트도 없이 점수를 주면 다음 실행에서 재검증 불가 → stderr 경고(점수는 유지).
        if points > 0 and not self.evidence and not self.note:
            print(f"경고: 규칙 '{self.name}' 에 근거 없이 {points}점 부여 — 재검증 불가(RUBRIC 불변식 위반)",
                  file=sys.stderr)
        return self

    def to_dict(self):
        return {
            "name": self.name,
            "points": self.points,
            "max": self.max,
            "passed": self.points >= self.max,
            "evidence": self.evidence,
            "note": self.note,
        }


# --- Scoring functions ----------------------------------------------------

def score_navigation(target: Path, scan: dict, doc_text: dict) -> dict:
    rules = []
    modules = scan["modules"]
    claude_docs = scan["claude_docs"]
    single_module = is_single_module(modules, target)
    catalog_doc = find_package_catalog(target) if single_module else None
    catalog_text = read_text(catalog_doc) if catalog_doc else ""
    catalog_sections = count_package_sections(catalog_text) if catalog_text else 0

    # 1.1 루트 CLAUDE.md / AGENTS.md 존재
    r = Rule("루트 CLAUDE.md 또는 AGENTS.md 존재", 3)
    root_doc = next((d for d in claude_docs if d.parent == target), None)
    if root_doc:
        r.award(3, [str(root_doc.relative_to(target))])
    rules.append(r)

    # 1.2 루트 문서가 3개 이상의 모듈/패키지 경로 참조
    # T-7: 한글 모듈명 매칭(가-힣) + thin-index 패턴 인식 (docs/wiki/doc 디렉토리도 가산)
    DOC_DIRS = {"docs", "wiki", "doc", "guides", ".ai-ready"}
    if single_module:
        # 단일 모듈: 루트 문서가 *패키지 카탈로그 문서* 또는 *3개 이상의 패키지 경로* 를 참조하는가
        r = Rule("루트 문서가 패키지 카탈로그 또는 3개 이상의 패키지 경로 참조", 4)
        if root_doc:
            text = doc_text.get(root_doc, "")
            refs_catalog = any(c in text for c in PACKAGE_CATALOG_CANDIDATES)
            path_hits = re.findall(r"[`\[]([\w가-힣\-./]+/[\w가-힣\-./]+)[`\]]", text)
            # 실재하지 않거나 스텁을 가리키는 참조는 세지 않는다 — _reference_target_counts 참조.
            non_http = {p for p in path_hits if not p.startswith("http") and "/" in p
                        and _reference_target_counts(target, p)}
            if refs_catalog:
                r.award(4, [str(catalog_doc.relative_to(target))] if catalog_doc else ["PACKAGES.md 참조"],
                        note="루트 문서가 패키지 카탈로그를 참조")
            elif len(non_http) >= 3:
                r.award(3, sorted(non_http)[:5],
                        note=f"패키지 카탈로그 참조 없이 경로 {len(non_http)}건 직접 참조")
            elif len(non_http) >= 1:
                r.award(1, sorted(non_http), note=f"{len(non_http)}건만 발견")
            else:
                r.note = "루트 문서에 패키지 경로 / 카탈로그 참조가 없음"
    else:
        # 멀티 모듈: 모듈 첫 segment 필터 + thin-index 패턴 인식
        r = Rule("루트 문서가 3개 이상의 모듈 경로/문서 참조", 4)
        if root_doc:
            text = doc_text.get(root_doc, "")
            path_hits = re.findall(r"[`\[]([\w가-힣\-./]+/[\w가-힣\-./]+)[`\]]", text)
            module_first_segs = {str(m).split("/")[0] for m in modules if m != Path(".")}
            valid_paths, dead_refs = set(), set()
            for p in path_hits:
                if "/" not in p or p.startswith("http"):
                    continue
                seg = p.split("/")[0]
                if seg not in module_first_segs and seg not in DOC_DIRS:
                    continue
                # 실재하지 않거나 스텁을 가리키는 참조는 세지 않는다 — _reference_target_counts 참조.
                if _reference_target_counts(target, p):
                    valid_paths.add(p)
                else:
                    dead_refs.add(p)
            dead_note = (f" (실재하지 않거나 스텁인 참조 {len(dead_refs)}건 제외: "
                         f"{', '.join(sorted(dead_refs)[:3])})" if dead_refs else "")
            if len(valid_paths) >= 3:
                r.award(4, sorted(valid_paths)[:5],
                        note=f"유효한 모듈/문서 경로 참조 {len(valid_paths)}건{dead_note}")
            elif len(valid_paths) >= 1:
                r.award(2, sorted(valid_paths),
                        note=f"{len(valid_paths)}건만 발견 (3건 이상 필요){dead_note}")
            else:
                r.note = "루트 문서에 실재하는 모듈/문서 경로 참조가 없음" + dead_note
    rules.append(r)

    # 1.3 모듈별 CLAUDE.md 커버리지 (단일 모듈은 PACKAGES.md 카탈로그로 대체)
    if single_module:
        r = Rule("패키지 카탈로그 문서 (PACKAGES.md) 존재 + 3개 이상 패키지 섹션", 5)
        if catalog_doc:
            if catalog_sections >= 3:
                r.award(5, [str(catalog_doc.relative_to(target))],
                        note=f"카탈로그에 {catalog_sections}개 패키지 섹션")
            elif catalog_sections >= 1:
                r.award(3, [str(catalog_doc.relative_to(target))],
                        note=f"카탈로그에 {catalog_sections}개 섹션 (3개 이상 권장)")
            else:
                r.award(2, [str(catalog_doc.relative_to(target))],
                        note="카탈로그 존재하나 패키지 섹션 헤더가 인식되지 않음")
        else:
            r.note = ("단일 모듈 프로젝트 — 패키지를 논리 모듈로 보고 docs/PACKAGES.md 같은 "
                      "카탈로그 문서를 만들어 각 패키지의 목적·진입점·흐름·함정을 정리하세요.")
    else:
        r = Rule("모듈별 CLAUDE.md 커버리지", 5)
        # 스텁은 커버리지로 세지 않는다 — 세 줄짜리 CLAUDE.md 를 모듈마다 뿌리면 커버리지 100%
        # 가 되던 구멍을 막는다. 스텁 개수는 note 로 따로 알려 무엇을 채우면 되는지 보이게 한다.
        covered, stubs = [], []
        for m in modules:
            if m == Path("."):
                continue
            doc = next((target / m / name for name in sorted(CLAUDE_DOC_NAMES)
                        if (target / m / name).is_file()), None)
            if doc is None:
                continue
            (covered if _has_min_content(doc) else stubs).append(str(m))
        non_root_modules = [m for m in modules if m != Path(".")]
        pct = (len(covered) / len(non_root_modules)) if non_root_modules else 0
        pts = round(pct * 5)
        stub_note = f" · 스텁 {len(stubs)}개는 미집계" if stubs else ""
        if pts > 0:
            r.award(pts, covered[:8],
                    note=f"{len(covered)}/{len(non_root_modules)} 모듈 ({pct*100:.0f}%) 에 실질 CLAUDE.md 존재{stub_note}")
        elif stubs:
            r.evidence.extend(stubs[:8])
            r.note = f"{len(stubs)}개 모듈의 CLAUDE.md 가 스텁 — 진입점·흐름·함정을 채우면 집계됩니다"
        else:
            r.note = f"0/{len(non_root_modules)} 모듈에 CLAUDE.md 없음"
    rules.append(r)

    # 1.4 인덱스 / MOC 파일
    r = Rule("인덱스 / MOC 파일 (docs/INDEX.md 또는 wiki/index.md)", 3)
    candidates = ["docs/INDEX.md", "docs/index.md", "INDEX.md", "wiki/index.md"]
    found = has_any_path(target, candidates)
    if any(_has_min_content(target / c) for c in found):
        r.award(3, found)
    elif found:
        r.award(1, found, note="인덱스가 비어/스텁 — 문서 목록과 1줄 요약을 채우면 만점")
    rules.append(r)

    return {
        "id": 1, "name": "내비게이션",
        "rules": [r.to_dict() for r in rules],
        "score": sum(r.points for r in rules),
        "max": sum(r.max for r in rules),
    }


def score_doc_quality(target: Path, scan: dict, doc_text: dict) -> dict:
    rules = []
    claude_docs = scan["claude_docs"]
    root_doc = next((d for d in claude_docs if d.parent == target), None)
    module_docs = [d for d in claude_docs if d.parent != target]
    single_module = is_single_module(scan["modules"], target)
    catalog_doc = find_package_catalog(target) if single_module else None

    # 2.1 루트 CLAUDE.md 상주 분량 (바이트 — 근거는 ROOT_DOC_MAX_BYTES 주석)
    r = Rule(ROOT_DOC_SIZE_RULE, 5)
    if root_doc:
        size = byte_size(root_doc)
        # 줄 수도 함께 남긴다. 점수 근거는 바이트지만, 줄당 분량을 보면 표 행이 긴 것인지
        # 문단이 많은 것인지 갈려 다이어트 방향이 달라진다.
        ev = [f"{root_doc.relative_to(target)} ({size:,}바이트 / {line_count(root_doc)}줄)"]
        if size < ROOT_DOC_MIN_BYTES:
            r.award(2, ev,
                    note=f"{ROOT_DOC_MIN_BYTES:,}바이트 미만 — 너무 얇아 모듈 문서로의 지도 역할을 못 합니다")
        elif size <= ROOT_DOC_MAX_BYTES:
            r.award(5, ev)
        elif size <= ROOT_DOC_WARN_BYTES:
            r.award(2, ev,
                    note=f"{ROOT_DOC_MAX_BYTES:,}바이트 초과 ~ {ROOT_DOC_WARN_BYTES:,}바이트 이하 — 다이어트 권장")
        else:
            # 0점이어도 근거는 남긴다 — history 에 바이트가 쌓여야 추이가 보인다.
            r.evidence.extend(ev)
            r.note = f"{size:,}바이트 — 너무 길어 매 세션 컨텍스트가 부풉니다"
    else:
        r.note = "루트 CLAUDE.md 없음"
    rules.append(r)

    # 2.2 모듈/패키지 문서 적정 길이
    if single_module:
        # 단일 모듈: 카탈로그 문서가 50~300줄 범위 (너무 짧으면 정보 부족, 너무 길면 lazy-load 비용)
        r = Rule("패키지 카탈로그 문서 적정 길이 (50~300줄)", 5)
        if catalog_doc:
            lc = line_count(catalog_doc)
            if 50 <= lc <= 300:
                r.award(5, [f"{catalog_doc.relative_to(target)} ({lc}줄)"])
            elif lc < 50:
                r.award(2, [f"{catalog_doc.relative_to(target)} ({lc}줄)"],
                        note="너무 짧음 — 패키지별 진입점·흐름·외부 IO·함정을 보강하세요")
            elif lc <= 500:
                r.award(3, [f"{catalog_doc.relative_to(target)} ({lc}줄)"],
                        note="300줄 초과 — 패키지별 별도 문서로 분리 검토")
            else:
                r.note = f"{lc}줄 — 너무 길어 lazy-load 비용이 큼"
        else:
            r.note = "패키지 카탈로그 문서 없음"
    else:
        r = Rule(MODULE_DOC_LEN_RULE, 5)
        if module_docs:
            counts = [line_count(d) for d in module_docs]
            avg = sum(counts) / len(counts)
            ev = [f"모듈 문서 {len(module_docs)}개, 평균 {avg:.0f}줄"]
            if avg < MODULE_DOC_MIN_LINES:
                r.award(2, ev,
                        note=f"평균 {MODULE_DOC_MIN_LINES}줄 미만 — 스텁에 가깝습니다. "
                             "각 모듈의 진입점·흐름·함정을 채우세요")
            elif avg <= MODULE_DOC_MAX_LINES:
                r.award(5, ev)
            elif avg <= 80:
                r.award(3, ev, note="25~35줄 범위로 줄이세요")
            else:
                r.evidence.extend(ev)
                r.note = f"모듈 문서 {len(module_docs)}개 / 평균 {avg:.0f}줄 — 너무 장황"
        else:
            r.note = "모듈 단위 문서 없음"
    rules.append(r)

    # 2.3 명시적 DO NOT / 절대 금지 섹션 존재
    # 스텁 게이트를 통과한 문서만 세고, 가이드 줄 수로 계단화한다 — 종전에는 스텁 문서에
    # "절대 금지: 없음" 한 줄만 있어도 만점이었다. 문서 개수가 아니라 줄 수로 세는 이유는
    # 루트 문서 하나뿐인 단일 모듈 레포가 구조적으로 만점에 닿지 못하는 것을 피하기 위함이다.
    r = Rule("명시적 안티패턴 / 절대 금지 가이드 존재", 5)
    gated = [d for d in claude_docs if _has_min_content(d)]
    hits = [str(d.relative_to(target)) for d in gated
            if regex_any(doc_text.get(d, ""), DONOT_PATTERNS)]
    # 만점은 *구체* 금지 줄 3개 — 줄 수만 세면 "금지" 단어 반복이 최적 전략이 된다(키워드 농사,
    # 2회차 적대 검토 실증). 막연한 금지 줄만 있으면 부분점수는 유지한다 — 식별자 없는 정당한
    # 규칙("main 직접 push 금지" 류)을 0점으로 떨어뜨리지 않기 위해서다.
    specific_lines = sum(count_specific_guide_lines(doc_text.get(d, ""), DONOT_PATTERNS) for d in gated)
    total_lines = sum(count_guide_lines(doc_text.get(d, ""), DONOT_PATTERNS) for d in gated)
    if specific_lines >= 3:
        r.award(5, hits[:5],
                note=f"{len(hits)}개 문서 / 구체 DO-NOT {specific_lines}줄 (전체 {total_lines}줄)")
    elif total_lines >= 1:
        r.award(3, hits[:5],
                note=(f"DO-NOT {total_lines}줄 중 구체 지시를 담은 줄이 {specific_lines}줄 — "
                      "무엇을 하지 말라는지 백틱 코드 참조·경로·식별자로 가리키는 줄 3개 이상이면 만점"))
    elif any(regex_any(doc_text.get(d, ""), DONOT_PATTERNS) for d in claude_docs):
        r.note = "DO-NOT 표현이 스텁 문서에만 있음 — 그 문서를 실질 내용으로 채우면 집계됩니다"
    else:
        r.note = "어떤 CLAUDE.md/AGENTS.md에도 'DO NOT / 절대 / MUST NOT' 표현 없음"
    rules.append(r)

    # 2.4 사용 시점 가이드
    # 2.3 과 달리 줄 수 계단은 두지 않는다 — 사용 시점은 한 문서에 규약 하나로 적는 것이 정상이라
    # 줄 수를 요구하면 같은 표현을 반복해 적게 만드는 잘못된 유인이 생긴다. 스텁 게이트만 건다.
    r = Rule("'사용 시점' 가이드 존재", 5)
    hits = [str(d.relative_to(target)) for d in claude_docs
            if _has_min_content(d) and regex_any(doc_text.get(d, ""), USAGE_PATTERNS)]
    if hits:
        r.award(5, hits[:5])
    elif any(regex_any(doc_text.get(d, ""), USAGE_PATTERNS) for d in claude_docs):
        r.note = "'사용 시점' 표현이 스텁 문서에만 있음 — 그 문서를 실질 내용으로 채우면 집계됩니다"
    else:
        r.note = "'언제 사용/사용 시점' 표현이 발견되지 않음"
    rules.append(r)

    return {
        "id": 2, "name": "컨텍스트 문서 품질",
        "rules": [r.to_dict() for r in rules],
        "score": sum(r.points for r in rules),
        "max": sum(r.max for r in rules),
    }


def score_tribal_knowledge(target: Path, scan: dict, doc_text: dict, cfg: dict | None = None) -> dict:
    rules = []

    r = Rule("ANTIPATTERNS.md (또는 wiki/anti-patterns/) 존재", 5)
    if scan["antipattern_docs"]:
        ev = [str(p.relative_to(target)) for p in scan["antipattern_docs"]]
        if any(_has_min_content(p) for p in scan["antipattern_docs"]):
            r.award(5, ev)
        else:
            r.award(2, ev, note="존재하나 비어/스텁 — DO-NOT 항목을 채우면 만점")
    else:
        wiki_ap = target / "wiki" / "anti-patterns"
        if wiki_ap.is_dir() and any(wiki_ap.iterdir()):
            if _has_substantive_content(wiki_ap):
                r.award(5, [str(wiki_ap.relative_to(target))])
            else:
                r.award(2, [str(wiki_ap.relative_to(target))],
                        note="디렉토리는 있으나 문서가 비어/스텁 — DO-NOT 항목을 채우면 만점")
    # config 선언 통합 문서(예: docs/CONVENTIONS.md)에 안티패턴을 두는 프로젝트 인정 (D1).
    # 파일 존재 + 최소 내용 게이트만 본다 — 섹션 헤더 스캔은 거짓양성이라 안 함.
    # 스텁 ANTIPATTERNS.md 부분점수(2점)가 있어도 힌트가 이긴다 — naming 의 elif 체인과 같은
    # 의미론. 종전 `points == 0` 조건은 낡은 스텁 파일을 지워야만 config 인정을 받는 비대칭을
    # 만들었다(2회차 적대 검토 발견 9).
    if r.points < r.max:
        for hint in antipattern_doc_hints(cfg):
            hp = target / hint
            if hp.is_file() and _has_min_content(hp):
                r.points, r.evidence = 0, []  # 스텁 부분점수를 대체 (award 는 가산이라 리셋 필요)
                r.award(5, [hint], note="config antipatterns.doc_hints 선언 문서 인정")
                break
    if r.points == 0:
        r.note = "안티패턴 문서 없음 — RUBRIC 권장 사항 참조"
    rules.append(r)

    r = Rule("아키텍처 의사결정 기록 (ADR / wiki/decisions)", 5)
    if scan["adr_dirs"]:
        # 디렉토리 존재만으로 만점을 주면 빈 ADR 파일 하나로 통과한다 — 스텁 게이트를 건다.
        substantive = [d for d in scan["adr_dirs"] if _has_substantive_content(target / d)]
        if substantive:
            cfg_dirs = [d for d in substantive if d in scan.get("adr_config_dirs", [])]
            r.award(5, substantive[:3],
                    note="config decision_records.dir_hints 선언 디렉토리 인정" if cfg_dirs else "")
        else:
            r.award(2, scan["adr_dirs"][:3],
                    note="ADR 디렉토리는 있으나 문서가 비어/스텁 — 결정 배경과 거부된 대안을 채우면 만점")
    else:
        r.note = ("ADR/decisions 디렉토리 미발견 — 결정을 docs/adr 또는 docs/decisions 에 두거나, "
                  "docs/design 등 통합 디렉토리에 둔다면 .ai-ready/config.json 의 "
                  "rubric.decision_records.dir_hints 로 선언하세요.")
    rules.append(r)

    r = Rule("네이밍 컨벤션 문서화", 5)
    naming_doc = scan["naming_docs"][0] if scan["naming_docs"] else None
    glossary_doc = next((target / c for c in GLOSSARY_CANDIDATES if (target / c).is_file()), None)
    hint_doc = next((target / h for h in naming_doc_hints(cfg) if (target / h).is_file()), None)
    if naming_doc and _has_min_content(naming_doc):
        ev = [str(p.relative_to(target)) for p in scan["naming_docs"]]
        if glossary_doc:
            ev.append(str(glossary_doc.relative_to(target)))
        r.award(5, ev)
    elif glossary_doc and _has_min_content(glossary_doc):
        # 도메인 용어집(glossary)도 네이밍·도메인 용어를 코드와 매핑한 컨벤션 자산으로 인정.
        r.award(5, [str(glossary_doc.relative_to(target))],
                note="도메인 용어집(glossary) 인정 — 용어·한영 동의어·코드 위치 매핑")
    elif hint_doc and _has_min_content(hint_doc):
        # config 선언 통합 문서(예: docs/CONVENTIONS.md)에 네이밍 규칙을 두는 프로젝트 인정 (D1).
        r.award(5, [str(hint_doc.relative_to(target))], note="config naming.doc_hints 선언 문서 인정")
    elif naming_doc:
        r.award(3, [str(naming_doc.relative_to(target))], note="네이밍 문서가 비어/스텁 — 채우면 만점")
    else:
        for d in scan["claude_docs"]:
            text = doc_text.get(d, "").lower()
            if "naming" in text or "네이밍" in text or "convention" in text or "컨벤션" in text:
                r.award(3, [str(d.relative_to(target))],
                        note="CLAUDE.md에 네이밍 언급 있음 (NAMING.md / docs/glossary.md 로 분리 권장)")
                break
    rules.append(r)

    return {
        "id": 3, "name": "암묵지 & 안티패턴",
        "rules": [r.to_dict() for r in rules],
        "score": sum(r.points for r in rules),
        "max": sum(r.max for r in rules),
    }


def score_dependency_tracking(target: Path, scan: dict) -> dict:
    rules = []
    modules = scan["modules"]

    r = Rule("모듈 의존성 맵 / 다이어그램 존재", 5)
    if scan["arch_docs"]:
        ev = [str(p.relative_to(target)) for p in scan["arch_docs"]]
        if any(_has_min_content(p) for p in scan["arch_docs"]):
            r.award(5, ev)
        else:
            r.award(2, ev, note="존재하나 비어/스텁 — 의존 그래프/다이어그램을 채우면 만점")
    rules.append(r)

    if is_single_module(modules, target):
        # 단일 모듈 — 카탈로그 + 표준 레이아웃 일관성 둘 다 요구.
        # 단일 모듈의 *진짜* 모듈성 신호는 패키지 간 일관된 구조다.
        r = Rule("논리 모듈 맵 + 표준 레이아웃 일관성 (단일 모듈)", 5)
        catalog_doc = find_package_catalog(target)
        sections = count_package_sections(read_text(catalog_doc)) if catalog_doc else 0
        layout = stacks.detect_layout(target)
        base_package = layout.source_root if layout is not None else None
        # 표준 레이아웃(controller/service/repository)은 JVM 웹 스택의 개념이다. 다른 스택에서는
        # 없는 것이 정상이라, 조언 문구가 그것을 요구하면 안 된다.
        stack_name = layout.stack if layout is not None else "미상"
        layout_applies = stack_name == "jvm"
        compliant, layout_total = 0, 0
        if base_package is not None:
            domains = find_domain_packages(base_package)
            compliant, layout_total = standard_layout_coverage(domains)
        ratio = (compliant / layout_total) if layout_total else 0
        evidence = []
        if catalog_doc:
            evidence.append(str(catalog_doc.relative_to(target)))
        if layout_total:
            evidence.append(f"표준 레이아웃 {compliant}/{layout_total} 도메인 ({ratio*100:.0f}%)")
        if catalog_doc and sections >= 3 and ratio >= 0.6:
            r.award(5, evidence,
                    note="카탈로그 + 표준 레이아웃 일관성 모두 만족")
        elif catalog_doc and sections >= 3:
            if layout_total == 0:
                # C4: 레이아웃을 측정하지 못한 것이지 "60% 미만"이 아니다. 0점 침묵 대신
                # 미측정임을 명시하고, 왜 측정이 성립하지 않는지를 스택 이름으로 말한다.
                why = ("JVM 이지만 Controller 를 가진 도메인 패키지가 없음"
                       if layout_applies else f"{stack_name} 스택 — 컨트롤러 레이아웃 개념이 없음")
                r.award(4, evidence,
                        note=f"카탈로그 OK / 표준 레이아웃 미측정 ({why}) — 카탈로그만으로 충분합니다")
            else:
                r.award(4, evidence,
                        note=("카탈로그 OK / 표준 레이아웃 60% 미만 — 도메인 패키지에 "
                              "controller/service/domain/repository 일관성을 보강하세요"))
        elif catalog_doc:
            r.award(3, evidence,
                    note=f"카탈로그 섹션 {sections}개 (3개 이상 권장)")
        elif ratio >= 0.6:
            r.award(2, evidence, note="레이아웃 일관성 OK — 카탈로그 도입 시 만점")
        else:
            if layout_applies:
                r.note = ("단일 모듈(jvm) — 카탈로그(docs/PACKAGES.md) 도입 + 도메인 패키지 표준 레이아웃 "
                          "일관성 (controller/service/domain/repository 4개 중 3개 이상) 확보 시 만점")
            else:
                # 스프링 레이아웃을 안 쓰는 스택에 그것을 권하지 않는다. 그쪽에서 만점의 조건은
                # 카탈로그 하나다(레이아웃 항목은 위 C4 로 미측정 처리된다).
                r.note = (f"단일 모듈({stack_name}) — 카탈로그(docs/PACKAGES.md)에 패키지 섹션 3개 이상을 "
                          "채우면 만점입니다. 표준 레이아웃 항목은 이 스택에서 측정하지 않습니다")
        rules.append(r)
    else:
        r = Rule("빌드 매니페스트로 의존 그래프 추출 가능", 5)
        if len(modules) >= 2:
            r.award(5, [str(m) for m in modules[:6]],
                    note=f"빌드 매니페스트 기반 모듈 {len(modules)}개 감지")
        rules.append(r)

    r = Rule("모듈 간 API 계약 문서화 (OpenAPI/proto/contracts)", 5)
    # 빈 openapi.yaml 이나 빈 contracts/ 디렉토리가 만점을 받지 않도록 스텁 게이트를 건다.
    # 빌드 의존성 신호는 게이트할 파일이 없으므로 종전대로 그대로 인정한다.
    contract_signals, stub_signals = [], []
    for hint in ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml",
                 "swagger.yml", "swagger.json", "contracts", "proto", "protos"):
        p = target / hint
        if not p.exists():
            continue
        (contract_signals if _has_substantive_content(p) else stub_signals).append(hint)
    if scan["proto_files"]:
        pf = scan["proto_files"][0]
        label = str(pf.relative_to(target))
        (contract_signals if _has_min_content(pf) else stub_signals).append(label)
    # config 선언 빌드 의존성 (springdoc 등 코드 기반 OpenAPI 생성) 도 계약 신호로 인정 (v0.3.0+)
    if scan.get("api_build_deps"):
        contract_signals.extend(f"{d} (빌드 의존성)" for d in scan["api_build_deps"])
        r.note = "springdoc 등 코드 기반 OpenAPI 생성 의존성 인정 (config rubric.api_contracts.build_deps)"
    if contract_signals:
        r.award(5, contract_signals[:4])
    elif stub_signals:
        r.award(2, stub_signals[:4], note="계약 파일은 있으나 비어/스텁 — 실제 스키마를 채우면 만점")
    rules.append(r)

    return {
        "id": 4, "name": "모듈 간 의존성 추적",
        "rules": [r.to_dict() for r in rules],
        "score": sum(r.points for r in rules),
        "max": sum(r.max for r in rules),
    }


def _ai_harness_verification_hooks(target: Path) -> list[str]:
    """프로젝트 레벨 .claude/settings.json 의 hooks 중 *코드 검증을 강제* 하는 명령 탐지 (v0.3.0+).

    AI 코딩 harness 에서는 검증 게이트가 pre-commit hook 이 아니라 에이전트 hook 으로
    존재할 수 있다 — 편집 직후 ktlint/format(PostToolUse), 커밋 직전 test/check(PreToolUse).
    repo 에 커밋되는 프로젝트 설정만 본다 — 글로벌(~/.claude)은 다른 개발자/AI 가 clone 해도
    적용되지 않으므로 프로젝트의 ai-readiness 신호가 아니다 (target 내부만 스캔하므로 자동 제외).

    문서 신선도(freshness) / ai-ready 자기 산출물 명령은 *코드 검증이 아니므로* 제외한다.
    """
    settings = target / ".claude" / "settings.json"
    signals, _broken = _classify_settings_hooks(target, settings)
    return signals


def _settings_hook_commands(settings_path: Path) -> list[str]:
    """.claude/settings.json 류 파일의 hooks 트리에서 command 문자열을 전부 수집."""
    try:
        data = json.loads(read_text(settings_path))
    except ValueError:
        return []
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    if not isinstance(hooks, dict):
        return []
    commands = []
    for matchers in hooks.values():
        for matcher in (matchers or []):
            if not isinstance(matcher, dict):
                continue
            for h in (matcher.get("hooks", []) or []):
                if isinstance(h, dict) and h.get("command"):
                    commands.append(str(h["command"]))
    return commands


def _command_missing_scripts(target: Path, cmd: str) -> list[str]:
    """훅 명령 문자열이 가리키는 레포 상대 스크립트 중 실재하지 않는 것 목록.

    훅 문자열 존재만으로 만점을 주면 가리키는 파일이 없는 죽은 설정도 점수를 받는다
    (2회차 적대 검토 발견 6). 판정은 보수적이다 — `./` 로 시작하거나 스크립트 확장자
    (.py/.sh/.js/.ts)로 끝나는 상대 경로 토큰만 본다. PATH 에서 찾는 명령(ktlint 등)과
    `$VAR` 치환이 남은 토큰은 실행 환경을 모르는 채 오탐할 수 있어 판정하지 않는다.
    `$CLAUDE_PROJECT_DIR/` 접두는 target 기준 상대 경로로 치환해 본다.
    """
    missing = []
    for token in cmd.split():
        t = token.strip("'\";&|")
        t = t.replace("$CLAUDE_PROJECT_DIR/", "").replace("${CLAUDE_PROJECT_DIR}/", "")
        if "$" in t or t.startswith(("-", "/")):
            continue
        is_dotslash = t.startswith("./")
        is_script = t.endswith((".py", ".sh", ".js", ".ts"))
        if not (is_dotslash or is_script):
            continue
        rel = t[2:] if is_dotslash else t
        if rel and not (target / rel).exists() and t not in missing:
            missing.append(t)
    return missing


def _classify_settings_hooks(target: Path, settings: Path) -> tuple[list[str], list[str]]:
    """settings 의 코드 검증 훅을 (살아있는 신호, 죽은 신호) 로 분류.

    죽은 신호 = 그 이벤트의 검증 명령이 전부 실재하지 않는 스크립트를 가리키는 경우.
    같은 이벤트에 살아있는 명령이 하나라도 있으면 신호로 인정한다.
    """
    if not settings.is_file():
        return [], []
    try:
        data = json.loads(read_text(settings))
    except (ValueError, OSError):
        return [], []
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    if not isinstance(hooks, dict):
        return [], []
    verify_kw = ("ktlint", "detekt", "lint", "test", "format", "check",
                 "gradlew", "prettier", "eslint", "mypy", "ruff", "tsc",
                 "typecheck", "build")
    exclude_kw = ("freshness", "ai-ready", ".ai-ready")
    signals, broken = [], []
    for event in ("PreToolUse", "PostToolUse", "Stop"):
        alive = dead = False
        for matcher in hooks.get(event, []) or []:
            for h in (matcher.get("hooks", []) or []):
                cmd = (h.get("command", "") or "")
                low = cmd.lower()
                if any(k in low for k in verify_kw) and not any(x in low for x in exclude_kw):
                    if _command_missing_scripts(target, cmd):
                        dead = True
                    else:
                        alive = True
        label = f".claude/settings.json:{event}"
        if alive:
            signals.append(label)
        elif dead:
            broken.append(label)
    return signals, broken


def score_verification(target: Path, scan: dict, doc_text: dict) -> dict:
    rules = []

    r = Rule("기계적 검증 훅 (pre-commit / AI 에이전트 hook)", 3)
    found = has_any_path(target, PRECOMMIT_FILES)
    harness, harness_broken = _classify_settings_hooks(target, target / ".claude" / "settings.json")
    evidence = found + harness
    if evidence:
        note = ""
        if harness and not found:
            note = "AI 에이전트 편집/커밋 시점 검증 hook 인정 (.claude/settings.json)"
        r.award(3, evidence, note=note)
    elif harness_broken:
        r.award(1, harness_broken,
                note="훅 명령이 가리키는 스크립트가 레포에 없음 — 실재하는 명령으로 고치면 만점")
    rules.append(r)

    r = Rule("CI 설정 존재 + 테스트 참조", 3)
    ci_paths = []
    for c in CI_FILES:
        if (target / c).exists():
            ci_paths.append(c)
    references_tests = False
    if ci_paths:
        for c in ci_paths:
            p = target / c
            if p.is_dir():
                for sub in p.rglob("*"):
                    if sub.is_file():
                        text = read_text(sub).lower()
                        if any(k in text for k in ("test", "pytest", "jest", "vitest", "gradle test")):
                            references_tests = True
                            break
            else:
                text = read_text(p).lower()
                if any(k in text for k in ("test", "pytest", "jest", "vitest", "gradle test")):
                    references_tests = True
            if references_tests:
                break
    if ci_paths and references_tests:
        r.award(3, ci_paths)
    elif ci_paths:
        r.award(1, ci_paths, note="CI는 있으나 테스트 참조 없음")
    rules.append(r)

    r = Rule("테스트 컨벤션 문서화 (CLAUDE.md 또는 TESTING.md)", 4)
    # TESTING.md 후보: docs/TESTING.md (권장) → 루트 TESTING.md (구식)
    test_candidates = [
        (target / "docs" / "TESTING.md", "docs/TESTING.md"),
        (target / "TESTING.md", "TESTING.md"),
    ]
    test_doc = next((p for p, _ in test_candidates if p.exists()), None)
    test_label = next((label for p, label in test_candidates if p.exists()), None)
    if test_doc and _has_min_content(test_doc):
        r.award(4, [test_label])
    elif test_doc:
        r.award(2, [test_label], note="TESTING.md 존재하나 비어/스텁 — 위치·네이밍·단언 스타일을 채우면 만점")
    else:
        for d in scan["claude_docs"]:
            t = doc_text.get(d, "").lower()
            if "test" in t and ("convention" in t or "naming" in t or "given" in t or "테스트" in t):
                r.award(3, [str(d.relative_to(target))],
                        note="CLAUDE.md에 테스트 언급 있음 (TESTING.md로 분리 권장)")
                break
    # B2: 재현 명령 문서(COMMANDS.md)는 점수를 바꾸지 않고 note 로만 부기 — 에이전트가
    # 빌드·테스트를 스스로 재현할 수 있는 신호(_has_min_content 로 스텁 제외).
    for cmd_label in ("docs/COMMANDS.md", "COMMANDS.md"):
        if (target / cmd_label).is_file() and _has_min_content(target / cmd_label):
            extra = f"재현 명령 문서({cmd_label}) 발견 — 에이전트가 빌드·테스트를 스스로 재현 가능"
            r.note = f"{r.note} · {extra}" if r.note else extra
            break
    rules.append(r)

    return {
        "id": 5, "name": "검증 게이트",
        "rules": [r.to_dict() for r in rules],
        "score": sum(r.points for r in rules),
        "max": sum(r.max for r in rules),
    }


def score_freshness(target: Path, scan: dict, doc_text: dict) -> dict:
    rules = []

    # 6.1 (M-2 fix): 좁은 키워드 + 파일별 stream 검색 (early break)
    r = Rule("CLAUDE.md / 문서 갱신 훅 또는 스케줄 존재", 5)
    candidates = [
        ".claude/hooks", ".claude/settings.json", ".claude/settings.local.json",
        ".husky", ".github/workflows",
    ]
    found, broken = [], []
    for c in candidates:
        p = target / c
        if not p.exists():
            continue
        if p.is_file():
            text = read_text(p).lower()
            if any(k in text for k in FRESHNESS_KEYWORDS):
                # settings 파일은 키워드만 믿지 않는다 — 신선도 명령이 가리키는 스크립트가
                # 전부 실재하지 않으면 죽은 설정이다(2회차 적대 검토 발견 6). 훅 파일(.claude/hooks
                # 등 디렉토리 갈래)은 그 파일 자체가 실재하는 산출물이라 종전대로 인정한다.
                fresh_cmds = [cmd for cmd in _settings_hook_commands(p)
                              if any(k in cmd.lower() for k in FRESHNESS_KEYWORDS)]
                if fresh_cmds and all(_command_missing_scripts(target, cmd) for cmd in fresh_cmds):
                    broken.append(c)
                else:
                    found.append(c)
        else:
            for sub in p.rglob("*"):
                if sub.is_file():
                    if any(k in read_text(sub).lower() for k in FRESHNESS_KEYWORDS):
                        found.append(c)
                        break
    if found:
        r.award(5, found)
    elif broken:
        r.award(2, broken,
                note="갱신 훅 명령이 가리키는 스크립트가 레포에 없음 — 실재하는 명령으로 고치면 만점")
    rules.append(r)

    # 6.2 — 키워드가 실질 문서에 있어야 한다. 스텁 문서의 "갱신 트리거" 한 줄로 만점을 주면
    # 형제 키워드 규칙(금지·사용 시점)만 게이트한 0.9.0 의 구멍이 여기로 옮겨온다(2회차 발견 4).
    r = Rule("CLAUDE.md 갱신 프로토콜 문서화", 5)
    protocol_keywords = ("갱신 트리거", "Maintenance", "유지보수", "update protocol",
                         "Updating CLAUDE", "갱신 방식")
    stub_only = False
    for d in scan["claude_docs"]:
        text = doc_text.get(d, "")
        if any(k in text for k in protocol_keywords):
            if _has_min_content(d):
                r.award(5, [str(d.relative_to(target))])
                break
            stub_only = True
    if r.points == 0 and stub_only:
        r.note = "갱신 프로토콜 표현이 스텁 문서에만 있음 — 그 문서를 실질 내용으로 채우면 집계됩니다"
    rules.append(r)

    return {
        "id": 6, "name": "신선도 자동 유지",
        "rules": [r.to_dict() for r in rules],
        "score": sum(r.points for r in rules),
        "max": sum(r.max for r in rules),
    }


# T-9: 성과 지표 부분 점수 — 외부 dashboard / 추적 인프라 키워드
EXTERNAL_DASHBOARD_PATTERNS = (
    r"notion\.so/[\w\-/]+", r"atlassian\.net/wiki", r"datadoghq\.com",
    r"grafana[\.\w/]*", r"metabase[\.\w/]*", r"mixpanel[\.\w/]*",
    r"redash[\.\w/]*", r"looker[\.\w/]*", r"tableau[\.\w/]*",
)
EXTERNAL_TRACKING_PATTERNS = (
    r"\bccusage\b", r"token[\s_\-]*usage", r"pr[\s_\-]*review[\s_\-]*time",
    r"ai[\s_\-]*pr[\s_\-]*(?:merge|rate)", r"merge[\s_\-]*rate",
    r"주간\s*보고", r"AI\s*사용량",
)


def _scan_root_docs_for_patterns(target: Path, patterns) -> list[str]:
    """루트 README.md / CLAUDE.md / docs/INDEX.md 에 패턴이 매칭되는지 검사."""
    hits = []
    for doc_name in ("README.md", "CLAUDE.md", "docs/INDEX.md"):
        doc = target / doc_name
        if not doc.exists():
            continue
        text = read_text(doc)
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                hits.append(f"{doc_name} ({p})")
                break  # 한 문서당 한 번만 카운트
    return hits


def score_outcomes(target: Path, scan: dict) -> dict:
    rules = []

    # 7.1: metrics 디렉토리/파일 (정확 매칭) + 외부 dashboard URL 부분점수
    r = Rule("매트릭스 문서 / 대시보드 존재", 7)
    candidates = ["metrics", "analytics", ".claude/metrics", "dashboards", "metrics.md"]
    found = has_any_path(target, candidates)
    # 빈 metrics/ 디렉토리나 스텁 metrics.md 는 외부 대시보드 포인터보다 나을 게 없으므로
    # 같은 3점 부분점수에 둔다 (v0.9.0). 종전에는 존재만으로 만점이었다.
    if any(_has_substantive_content(target / c) for c in found):
        r.award(7, found)
    elif found:
        r.award(3, found, note="metrics 산출물이 비어/스텁 — 실제 추이 수치를 채우면 만점")
    else:
        # T-9: 외부 dashboard URL 발견 시 부분 점수 (3/7)
        ext_hits = _scan_root_docs_for_patterns(target, EXTERNAL_DASHBOARD_PATTERNS)
        if ext_hits:
            r.award(3, ext_hits[:3], note="외부 dashboard URL 발견 — 부분 점수. 운영 대시보드를 metrics/ 로 가져오면 만점")
        else:
            r.note = "metrics/, analytics/, .claude/metrics 등 디렉토리 미발견. 외부 dashboard URL 도 없음"
    rules.append(r)

    # 7.2: 정확 이름 매칭 + 추적 키워드 부분점수
    r = Rule("PR 리뷰 시간 / AI 사용량 / 토큰 추적", 8)
    substantive_outcomes = [p for p in scan["outcome_paths"] if _has_substantive_content(target / p)]
    if substantive_outcomes:
        r.award(8, substantive_outcomes[:3])
    elif scan["outcome_paths"]:
        r.award(3, scan["outcome_paths"][:3],
                note="추적 산출물이 비어/스텁 — 실제 측정치를 채우면 만점")
    else:
        # T-9: 추적 인프라 키워드 발견 시 부분 점수 (3/8)
        tr_hits = _scan_root_docs_for_patterns(target, EXTERNAL_TRACKING_PATTERNS)
        if tr_hits:
            r.award(3, tr_hits[:3], note="추적 키워드 언급 발견 — 부분 점수. 실제 csv/md 산출물로 정착하면 만점")
        else:
            r.note = "PR 리뷰 시간 / 토큰 사용량 등 추적 산출물 미발견"
    rules.append(r)

    return {
        "id": 7, "name": "성과 지표",
        "rules": [r.to_dict() for r in rules],
        "score": sum(r.points for r in rules),
        "max": sum(r.max for r in rules),
    }


# --- Action list / report -------------------------------------------------

GRADE_BANDS = [
    (90, "에이전트 자율 (Agentic-ready)"),
    (80, "AI 맥시멀리스트 (AI-maximalist)"),
    (60, "AI 활용 (AI-enabled)"),
    (40, "AI 인지 (AI-aware)"),
    (0, "AI 미인지 (AI-blind)"),
]


def grade_for(score: int) -> str:
    for threshold, label in GRADE_BANDS:
        if score >= threshold:
            return label
    return "AI 미인지 (AI-blind)"


# 액션 권고 - rule name을 키로 사용. 항목: (소요 분, 임팩트 1-5, 메시지)
ACTION_HINTS = {
    "루트 CLAUDE.md 또는 AGENTS.md 존재": (15, 5,
        f"저장소 루트에 CLAUDE.md를 만드세요. {ROOT_DOC_MAX_BYTES:,}바이트 이하로 유지하고, 백과사전이 아닌 모듈 문서로의 지도 역할로 사용하세요."),
    "루트 문서가 3개 이상의 모듈 경로/문서 참조": (15, 4,
        "루트 CLAUDE.md에 '모듈 맵' 섹션을 추가해 각 모듈의 디렉토리와 1줄 목적을 나열하세요."),
    "모듈별 CLAUDE.md 커버리지": (60, 5,
        "scaffold.py 스크립트로 모듈별 CLAUDE.md 초안을 생성하고, 가장 자주 변경되는 핫 모듈부터 채워 넣으세요."),
    "루트 문서가 패키지 카탈로그 또는 3개 이상의 패키지 경로 참조": (15, 4,
        "단일 모듈 프로젝트는 패키지 = 논리 모듈. 루트 CLAUDE.md 의 '모듈 맵' 섹션에서 docs/PACKAGES.md 같은 카탈로그 문서를 참조하도록 lazy-load 트리거를 박으세요."),
    "패키지 카탈로그 문서 (PACKAGES.md) 존재 + 3개 이상 패키지 섹션": (45, 5,
        "단일 모듈 프로젝트는 패키지를 논리 모듈로 봅니다. docs/PACKAGES.md 를 만들어 각 패키지의 목적 / 진입점 / 흐름 / 외부 IO / 테스트 진입점 / 함정 / 관련 ADR 을 한 곳에 모으세요. AI 가 패키지 진입 시 첫 컨텍스트로 사용합니다."),
    "패키지 카탈로그 문서 적정 길이 (50~300줄)": (20, 3,
        "패키지 카탈로그를 50~300줄 범위로 유지하세요. 너무 짧으면 정보 부족, 너무 길면 lazy-load 비용이 큽니다."),
    "인덱스 / MOC 파일 (docs/INDEX.md 또는 wiki/index.md)": (10, 2,
        "docs/INDEX.md(권장) 또는 wiki/index.md를 만들어 모든 문서를 잇는 단일 진입점을 제공하세요."),
    ROOT_DOC_SIZE_RULE: (30, 4,
        "루트 CLAUDE.md를 다이어트하세요. 컨벤션은 CONVENTIONS.md, 안티패턴은 ANTIPATTERNS.md로 분리하고 루트에는 지도만 남기세요. "
        "줄 수가 적어도 한 줄이 길면 상주 비용은 그대로입니다 — 긴 불릿 하나가 표 열 행보다 무거울 수 있습니다. "
        f"반대로 {ROOT_DOC_MIN_BYTES:,}바이트 미만이면 너무 얇아 지도 역할을 못 하니, 모듈 문서로 가는 트리거를 채우세요."),
    MODULE_DOC_LEN_RULE: (30, 3,
        f"모듈 문서 점검 — {MODULE_DOC_MAX_LINES}줄을 넘는 문서는 DESIGN.md, ANTIPATTERNS.md 등으로 분리하고, "
        f"{MODULE_DOC_MIN_LINES}줄에 못 미치는 스텁은 진입점·흐름·함정으로 채우세요."),
    "명시적 안티패턴 / 절대 금지 가이드 존재": (20, 5,
        "가장 자주 편집되는 CLAUDE.md에 'DO NOT / 절대 금지' 섹션을 추가하세요. 한 줄에 하나의 구체적인 규칙을 적습니다."),
    "'사용 시점' 가이드 존재": (15, 3,
        "각 모듈/패턴 문서 근처에 '사용 시점' bullet을 추가해 AI에게 언제 적용할지 알려주세요."),
    "ANTIPATTERNS.md (또는 wiki/anti-patterns/) 존재": (45, 5,
        "extract_antipatterns.py로 git 히스토리에서 시드를 만들고, 검토·정제한 뒤 채택하세요."),
    "아키텍처 의사결정 기록 (ADR / wiki/decisions)": (60, 3,
        "ADR/ 디렉토리를 시작하세요. 짧은 ADR 3~5개만 있어도 AI가 코드의 'why'를 이해하는 데 큰 도움이 됩니다."),
    "네이밍 컨벤션 문서화": (20, 3,
        "NAMING.md(또는 도메인 용어집 docs/glossary.md)를 만들거나 CLAUDE.md에 네이밍·용어 섹션을 추가하세요. "
        "용어집은 도메인 용어와 한영 동의어·코드 위치 매핑을 담아 AI 의 자연어 query 적중을 돕습니다."),
    "모듈 의존성 맵 / 다이어그램 존재": (45, 4,
        "ARCHITECTURE.md 또는 DEPENDENCIES.md를 만들고 Mermaid 다이어그램으로 모듈 의존성을 표현하세요."),
    "빌드 매니페스트로 의존 그래프 추출 가능": (0, 0,
        "이미 빌드 시스템이 커버하고 있습니다."),
    "논리 모듈 맵 + 표준 레이아웃 일관성 (단일 모듈)": (60, 4,
        "단일 모듈 프로젝트는 패키지 = 논리 모듈. (1) docs/PACKAGES.md 카탈로그에 3개 이상 패키지 섹션을 채우세요. "
        "(2) JVM 웹 스택이면 도메인 패키지가 표준 레이아웃 (controller/service/domain/repository 4개 중 3개 이상) 을 "
        "따르도록 정렬하면 만점입니다. 다른 스택에서는 그 레이아웃 개념이 없어 측정하지 않으며 (1) 만으로 만점입니다 "
        "— 스프링 구조로 바꾸라는 뜻이 아닙니다."),
    "모듈 간 API 계약 문서화 (OpenAPI/proto/contracts)": (90, 3,
        "OpenAPI 명세나 proto 스키마를 도입해 계약을 기계 판독 가능한 형태로 유지하세요."),
    "기계적 검증 훅 (pre-commit / AI 에이전트 hook)": (20, 4,
        "AI 가 만든 코드를 기계가 잡는 검증 게이트를 강제하세요. AI 코딩 환경이면 .claude/settings.json "
        "PostToolUse(편집 후 ktlint/format)·PreToolUse(커밋 전 test/check) hook 이 가장 앞단이고, "
        "lefthook pre-commit·CI 가 안전망입니다. AI 가 만든 PR 이 가장 큰 수혜를 봅니다."),
    "CI 설정 존재 + 테스트 참조": (45, 4,
        "테스트 스위트를 CI에 연결하세요. 없으면 AI 환각이 main에 그대로 흘러들어갑니다."),
    "테스트 컨벤션 문서화 (CLAUDE.md 또는 TESTING.md)": (20, 3,
        "테스트 위치, 네이밍, 단언 스타일을 문서화하세요. AI는 문서화된 것을 모방합니다."),
    "CLAUDE.md / 문서 갱신 훅 또는 스케줄 존재": (30, 4,
        "freshness Stop 훅을 설치하세요 (SKILL.md 참조). 세션 종료 시 CLAUDE.md 신선도를 자동 검증합니다."),
    "CLAUDE.md 갱신 프로토콜 문서화": (15, 3,
        "루트 CLAUDE.md에 '유지보수' / '갱신 트리거' 섹션을 추가해 언제·어떻게 갱신할지 명시하세요."),
    "매트릭스 문서 / 대시보드 존재": (60, 2,
        "AI PR 머지율, 평균 리뷰 시간, 토큰 사용량 추이를 추적하는 metrics.md를 만드세요."),
    "PR 리뷰 시간 / AI 사용량 / 토큰 추적": (60, 3,
        "최소한의 추적 환경을 셋업하세요 — 수동 스프레드시트도 추이 분석에는 충분합니다."),
}


def _validate_action_hints(category_results: list[dict]) -> None:
    """T-8: 모든 rule.name 이 ACTION_HINTS 에 등록됐는지 + 힌트가 가리키는 스크립트가 실재하는지 smoke check.

    의도된 skip rule(빌드 매니페스트)을 제외하고 미등록 룰이 있으면 stderr 경고.
    또한 힌트 메시지가 언급하는 `*.py`(scaffold.py·extract_antipatterns.py 등)가 이 스크립트
    디렉토리에 실제로 존재하는지 검사한다 — 파일명이 바뀌거나 삭제되면 리포트가 없는 명령을
    실행하라고 안내하는 죽은 포인터가 되므로.
    """
    rule_names = {r["name"] for cat in category_results for r in cat["rules"]}
    intentional_skip = {"빌드 매니페스트로 의존 그래프 추출 가능"}
    missing = rule_names - set(ACTION_HINTS.keys()) - intentional_skip
    if missing:
        print(f"경고: ACTION_HINTS 미정의 룰 {len(missing)}건 — {sorted(missing)}", file=sys.stderr)

    referenced = set()
    for _effort, _impact, message in ACTION_HINTS.values():
        referenced.update(re.findall(r"\b[\w\-]+\.py\b", message))
    dead = sorted(s for s in referenced if not (_SCRIPT_DIR / s).is_file())
    if dead:
        print(f"경고: ACTION_HINTS 가 가리키는 스크립트 {len(dead)}건이 {_SCRIPT_DIR} 에 없음 — {dead}",
              file=sys.stderr)


# ROI 스케일 상수 — effort=15분/missing=5점/impact=5 일 때 ROI≈100 으로 정수 직관 범위
_ROI_SCALE = 60


def build_action_list(category_results: list[dict]) -> list[dict]:
    _validate_action_hints(category_results)
    actions = []
    for cat in category_results:
        for rule in cat["rules"]:
            if rule["points"] >= rule["max"]:
                continue
            missing = rule["max"] - rule["points"]
            hint = ACTION_HINTS.get(rule["name"], (60, 3, "RUBRIC.md를 참조하세요."))
            effort, impact, message = hint
            if effort == 0:
                continue
            roi = (impact * missing) / max(effort, 1) * _ROI_SCALE
            actions.append({
                "category": cat["name"],
                "rule": rule["name"],
                "missing_points": missing,
                "current_points": rule["points"],
                "max_points": rule["max"],
                "effort_minutes": effort,
                "impact": impact,
                "roi_score": round(roi, 2),
                "action": message,
                "current_evidence": rule["evidence"],
                "current_note": rule["note"],
            })
    # D5: roi 동점 시 impact 높은 항목 우선 — 정렬식(roi_score) 자체는 불변이라 기존
    # 우선순위 대부분 보존, 동점 구간만 고임팩트로 정리.
    actions.sort(key=lambda a: (a["roi_score"], a["impact"]), reverse=True)
    return actions


def _sanitize_md_cell(s: str) -> str:
    """L-5: markdown 표 셀 내 파이프 문자 escape."""
    return s.replace("|", "\\|")


def render_report(audit: dict) -> str:
    lines = []
    lines.append(f"# AI 준비도 감사 리포트")
    lines.append("")
    # T-5: 로컬 + UTC 병기
    ts_local = audit.get("timestamp_local", "")
    ts_utc = audit["timestamp"]
    lines.append(f"- **생성 시각**: {ts_local} (로컬) · {ts_utc} (UTC)" if ts_local else f"- **생성 시각**: {ts_utc}")
    lines.append(f"- **점수**: **{audit['total_score']} / {audit['max_score']}** — _{audit['grade']}_")
    # config 자기신고 인정분 공개 — 채점당하는 레포가 쓰는 .ai-ready/config.json 이 채점 입력이므로,
    # 그 선언으로 얻은 점수를 검토자가 한눈에 보게 한다(2회차 적대 검토 발견 1의 투명성 조치).
    # 식별 규약: config 로 인정한 규칙의 note 에는 "config" 를 반드시 포함하고, 점수가 있는
    # 다른 규칙의 note 에는 그 단어를 쓰지 않는다.
    config_awarded = [(rule["name"], rule["points"])
                      for cat in audit["categories"] for rule in cat["rules"]
                      if rule["points"] > 0 and "config" in (rule.get("note") or "")]
    if config_awarded:
        config_points = sum(p for _, p in config_awarded)
        lines.append(f"- **config 자기신고 인정**: {len(config_awarded)}개 규칙 {config_points}점 — "
                     f"`.ai-ready/config.json` 선언으로 인정된 점수입니다. "
                     f"선언이 프로젝트 실물과 맞는지는 사람이 확인하세요 (세부는 규칙 비고)")
    if audit.get("single_module_mode"):
        catalog = audit.get("package_catalog") or "없음 — 도입 권장"
        lines.append(f"- **레이아웃**: 단일 모듈 (패키지 = 논리 모듈)")
        lines.append(f"- **패키지 카탈로그 문서**: `{catalog}`")
    else:
        lines.append(f"- **레이아웃**: 멀티 모듈")
        lines.append(f"- **감지된 모듈**: {audit['module_count']}")
    scaffold_note = ""
    if audit.get("claude_doc_count", 0) > audit.get("module_count", 0) + 1:
        scaffold_note = " (루트 + scaffold 포함 가능)"
    lines.append(f"- **CLAUDE.md 문서 수**: {audit['claude_doc_count']}{scaffold_note}")
    lines.append("")

    lines.append("## 카테고리별 점수")
    lines.append("")
    lines.append("| # | 카테고리 | 점수 | 만점 |")
    lines.append("|---|----------|------|------|")
    for cat in audit["categories"]:
        lines.append(f"| {cat['id']} | {cat['name']} | {cat['score']} | {cat['max']} |")
    lines.append("")

    lines.append("## 규칙별 상세 결과")
    for cat in audit["categories"]:
        lines.append(f"\n### {cat['id']}. {cat['name']} — {cat['score']}/{cat['max']}\n")
        for rule in cat["rules"]:
            mark = "✅" if rule["passed"] else ("🟡" if rule["points"] > 0 else "❌")
            lines.append(f"- {mark} **{rule['name']}** — {rule['points']}/{rule['max']}")
            if rule["evidence"]:
                lines.append(f"  - 근거: {', '.join(f'`{e}`' for e in rule['evidence'])}")
            if rule["note"]:
                lines.append(f"  - 비고: {rule['note']}")
    lines.append("")

    lines.append("## ROI 우선순위 액션 리스트")
    lines.append("")
    if not audit["actions"]:
        lines.append("모든 카테고리 만점입니다. 30일 후 재실행해 신선도를 점검하세요.")
    else:
        lines.append("| 순위 | ROI | 현재 | 소요 | 카테고리 | 액션 |")
        lines.append("|------|-----|------|------|----------|------|")
        for i, a in enumerate(audit["actions"][:15], 1):
            cur = f"{a.get('current_points', '?')}/{a.get('max_points', '?')}"
            lines.append(
                f"| {i} | {a['roi_score']} | {cur} | {a['effort_minutes']}분 "
                f"| {_sanitize_md_cell(a['category'])} | {_sanitize_md_cell(a['action'])} |"
            )
    lines.append("")
    lines.append("## 다음 실행")
    lines.append("")
    lines.append("월 1회 재실행하세요. 절대 점수가 아닌 **점수 추이**에 주목합니다.")
    lines.append("")
    lines.append("`/ai-ready:apply` 로 액션을 반영한 변경은 `/build`(수렴까지) 또는 1회 점검 `/review` 로 "
                 "검증하고, 거기서 잡힌 실수는 `/lessons` 로 `docs/ANTIPATTERNS.md` 에 반영해 다음 audit 의 "
                 "입력으로 되돌립니다 — audit→apply→verify→lessons→audit 순환.")
    return "\n".join(lines)


def render_readme(audit: dict, out_dir: Path | None = None) -> str:
    """`.ai-ready/README.md` — 산출물 안내 + 플러그인 설치·사용 가이드.

    팀원·신규 합류자·외부 컨트리뷰터가 `.ai-ready/` 폴더를 처음 봤을 때
    무엇이 들어 있고 어떻게 갱신·활용하는지 자족적으로 알 수 있도록 한다.

    산출물 표는 out_dir 의 실물 기준으로 쓴다 — audit 은 dashboard.html 과 scaffolds/ 를
    만들지 않는데(각각 dashboard.py·apply 의 몫) 종전 README 가 무조건 표에 넣고
    "매 실행 시 갱신"이라 적어, audit 만 재실행한 독자가 낡은 dashboard 점수를 갱신된
    것으로 믿게 했다(2회차 적대 검토 발견 8). out_dir=None 이면 없는 것으로 취급한다.
    """
    def _exists(rel: str) -> bool:
        return out_dir is not None and (out_dir / rel).exists()

    lines = []
    lines.append("# .ai-ready — AI 준비도 감사 산출물")
    lines.append("")
    lines.append("이 디렉토리는 [`kunsanglee/ai-ready`](https://github.com/kunsanglee/ai-ready) Claude Code 플러그인이 생성한 산출물 모음입니다.")
    lines.append("AI 에이전트(Claude/Codex/Gemini)와 신규 합류자가 코드베이스를 빠르게 이해할 수 있도록 컨벤션·암묵지·모듈 경계를 한 곳에 정리합니다.")
    lines.append("")
    lines.append(f"- **현재 점수**: **{audit['total_score']} / {audit['max_score']}** — _{audit['grade']}_")
    lines.append(f"- **감지된 모듈**: {audit['module_count']}개")
    lines.append(f"- **CLAUDE.md 문서 수**: {audit['claude_doc_count']}개")
    lines.append("")
    lines.append("## 산출물")
    lines.append("")
    lines.append("| 파일 | 용도 |")
    lines.append("|---|---|")
    lines.append("| `audit-report.md` | 카테고리별 점수·규칙별 통과 여부·ROI 우선순위 액션. 사람이 먼저 읽는 리포트 |")
    lines.append("| `audit.json` | 동일 결과의 기계 판독용 (스크립트·대시보드 입력) |")
    lines.append("| `history/{ts}.json` | 매 실행마다 archive — dashboard 추이 차트의 입력 |")
    if _exists("dashboard.html"):
        lines.append("| `dashboard.html` | 점수·카테고리 시각화 + 추이 sparkline (브라우저로 직접 열기). "
                     "audit 재실행으로는 갱신되지 않음 — dashboard.py 를 다시 실행 |")
    if _exists("scaffolds"):
        lines.append("| `scaffolds/<module>/CLAUDE.md` | 핫 모듈용 CLAUDE.md 초안. 검토 후 실제 모듈 디렉토리로 이동 |")
        lines.append("| `scaffolds/ANTIPATTERNS.md` | 180일 git 핫스팟 기반 안티패턴 시드. 클러스터링된 후보 — 검토 후 채택 |")
    if _exists("hooks/freshness_check.sh"):
        lines.append("| `hooks/freshness_check.sh` | (선택) Claude Code Stop hook — 소스 변경에 비해 CLAUDE.md가 오래된 경우 경고 |")
    lines.append("")
    if not _exists("dashboard.html"):
        lines.append("`dashboard.html` 은 아직 없습니다 — audit 은 만들지 않으므로 "
                     "`python3 <플러그인>/skills/audit/scripts/dashboard.py --audit audit.json --out dashboard.html` 로 생성하세요.")
        lines.append("")
    if not _exists("scaffolds"):
        lines.append("`scaffolds/` 초안(모듈 CLAUDE.md·ANTIPATTERNS 시드)은 `/ai-ready:apply` 의 해당 액션이 만듭니다.")
        lines.append("")
    lines.append("## 플러그인 설치 (처음 사용)")
    lines.append("")
    lines.append("Claude Code CLI에서:")
    lines.append("")
    lines.append("```")
    lines.append("/plugin marketplace add kunsanglee/ai-ready")
    lines.append("/plugin install ai-ready@ai-ready")
    lines.append("```")
    lines.append("")
    lines.append("## 재실행 (점수 갱신)")
    lines.append("")
    lines.append("월 1회 정도 재실행해 점수 추이를 추적합니다. 절대값보다 **변화 방향**이 중요합니다.")
    lines.append("")
    lines.append("```")
    lines.append("/ai-ready:audit            # 점수 측정 + 리포트 갱신")
    lines.append("/ai-ready:apply top 10     # 상위 ROI 액션 자동 적용")
    lines.append("```")
    lines.append("")
    lines.append("## 점수 해석")
    lines.append("")
    lines.append("| 등급 | 점수 | 의미 |")
    lines.append("|---|---|---|")
    lines.append("| AI-blind | 0-39 | AI 에이전트가 컨벤션·경계 없이 헤맴. 매 PR마다 동일 컨텍스트 재설명 |")
    lines.append("| AI-aware | 40-59 | 일부 가이드 존재. 핫 모듈에만 컨텍스트 도움 |")
    lines.append("| AI-enabled | 60-79 | 모듈 가이드·안티패턴·의존성 그래프 갖춤. AI가 자율 작업 가능 |")
    lines.append("| AI-maximalist | 80-89 | 신선도 자동 갱신 + 측정 인프라 운영 |")
    lines.append("| Agentic-ready | 90-100 | 다중 에이전트가 자율적으로 PR을 만들 수 있는 상태 |")
    lines.append("")
    lines.append("## 7-카테고리 100점 루브릭")
    lines.append("")
    lines.append("| # | 카테고리 | 만점 |")
    lines.append("|---|---|---|")
    lines.append("| 1 | Navigation (root → modules) | 15 |")
    lines.append("| 2 | Context Document Quality | 20 |")
    lines.append("| 3 | Tribal Knowledge & Anti-patterns | 15 |")
    lines.append("| 4 | Cross-module Dependency Tracking | 15 |")
    lines.append("| 5 | Verification Quality Gates | 10 |")
    lines.append("| 6 | Freshness Auto-Maintenance | 10 |")
    lines.append("| 7 | Outcome Metrics | 15 |")
    lines.append("")
    lines.append("## 활용 흐름")
    lines.append("")
    lines.append("1. `audit-report.md` 의 **ROI 우선순위 액션** 표를 위에서부터 본다.")
    lines.append("2. `/ai-ready:apply` 로 mechanical 액션을 일괄 실행한다 (모듈 가이드 scaffold, ARCHITECTURE.md 생성, ANTIPATTERNS 시드 등).")
    lines.append("3. judgment 액션은 Claude Code 세션에서 사용자 검수 후 적용한다.")
    lines.append("4. apply 로 반영한 변경은 `/build`(수렴까지) 또는 `/review`(1회 점검)로 검증하고, "
                 "잡힌 실수는 `/lessons` 로 `docs/ANTIPATTERNS.md` 에 반영한다 (다음 audit 입력으로 환류).")
    lines.append("5. 월 1회 재실행해 점수 추이를 `audit.json` 기반으로 비교한다.")
    lines.append("")
    lines.append("## 주의")
    lines.append("")
    lines.append("- **휴리스틱 점수**: ±5점 노이즈. 절대값이 아니라 추이를 본다.")
    lines.append("- **scaffold/는 초안**: `scaffolds/` 하위 산출물은 그대로 쓰지 말고 검토·이동·정리 후 실제 위치에 둔다.")
    lines.append("  - `scaffolds/<module>/CLAUDE.md` → 검토 후 `<module>/CLAUDE.md` 로 `git mv`")
    lines.append("  - `scaffolds/ANTIPATTERNS.md` → 검토 후 `docs/ANTIPATTERNS.md` 로 채택. 시드와 운영본이 공존할 때는 `docs/` 가 권위")
    lines.append("- **재실행 시 덮어쓰기**: `audit.json` / `audit-report.md` / 본 README는 audit 매 실행 시 갱신된다. 직접 수정한 내용은 사라진다.")
    lines.append("- **dashboard 는 별도 갱신**: `dashboard.html` 은 audit 재실행으로 갱신되지 않는다 — dashboard.py 를 다시 실행해야 최신 점수를 보여준다.")
    lines.append("- **history/ 는 누적**: 이전 실행 결과를 보존하므로 dashboard 가 추이 차트를 그릴 수 있다. 손대지 마세요.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_이 README는 `audit.py` 가 자동 생성합니다. 수동 편집은 다음 audit 실행 시 덮어쓰여집니다._")
    return "\n".join(lines) + "\n"


# --- Main -----------------------------------------------------------------

def _archive_history(out_dir: Path, audit: dict) -> Path | None:
    """T-11: history/{timestamp}.json 으로 audit 결과 archive — dashboard 추이 차트 입력."""
    history_dir = out_dir / "history"
    try:
        history_dir.mkdir(exist_ok=True)
    except OSError:
        return None
    # 파일명에 안전한 timestamp (UTC). 콜론·플러스 문자 제거.
    ts = audit["timestamp"].replace(":", "-").replace("+", "_")
    path = history_dir / f"{ts}.json"
    path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _copy_freshness_hook(out_dir: Path) -> Path | None:
    """Codex adapter: expose freshness as an explicit read-only skill, never a hook."""
    return None


def run(target: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    # config-aware 채점 (v0.3.0+) — 없으면 cfg=None 으로 기존 동작.
    cfg = load_config(target)
    # M-5: 단일 walk
    scan = scan_target(target, cfg)
    # M-4: guidance-document text is read once and reused by scoring.
    doc_text = {p: read_text(p) for p in scan["claude_docs"]}

    categories = [
        score_navigation(target, scan, doc_text),
        score_doc_quality(target, scan, doc_text),
        score_tribal_knowledge(target, scan, doc_text, cfg),
        score_dependency_tracking(target, scan),
        score_verification(target, scan, doc_text),
        score_freshness(target, scan, doc_text),
        score_outcomes(target, scan),
    ]
    total = sum(c["score"] for c in categories)
    now_utc = datetime.now(timezone.utc)
    single_module = is_single_module(scan["modules"], target)
    catalog_doc = find_package_catalog(target) if single_module else None
    audit = {
        "schema_version": 3,  # 2 → 3: timestamp_local, history archive, outcome 부분점수, single-module mode + package catalog
        "target": str(target),
        "timestamp": now_utc.isoformat(timespec="seconds"),
        "timestamp_local": now_utc.astimezone().isoformat(timespec="seconds"),
        "module_count": len(scan["modules"]),
        "claude_doc_count": len(scan["claude_docs"]),
        "modules": [str(m) for m in scan["modules"]],
        "claude_docs": [str(d.relative_to(target)) for d in scan["claude_docs"]],
        "single_module_mode": single_module,
        "package_catalog": str(catalog_doc.relative_to(target)) if catalog_doc else None,
        "total_score": total,
        "max_score": 100,
        "grade": grade_for(total),
        "categories": categories,
        "actions": build_action_list(categories),
    }
    (out_dir / "audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "audit-report.md").write_text(render_report(audit), encoding="utf-8")
    _archive_history(out_dir, audit)
    # README 는 훅 복사 뒤에 쓴다 — 산출물 표가 out_dir 실물 기준이라 순서가 내용을 정한다.
    _copy_freshness_hook(out_dir)
    (out_dir / "README.md").write_text(render_readme(audit, out_dir), encoding="utf-8")
    return audit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="대상 코드베이스 절대 경로")
    ap.add_argument("--out", required=True, help="출력 디렉토리 (자동 생성)")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    out_dir = Path(args.out).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    audit = run(target, out_dir)
    print(f"점수: {audit['total_score']} / 100  ({audit['grade']})")
    print(f"  모듈: {audit['module_count']}개, guidance 문서: {audit['claude_doc_count']}개")
    print(f"  생성: {out_dir / 'audit.json'}")
    print(f"  생성: {out_dir / 'audit-report.md'}")
    print(f"  생성: {out_dir / 'README.md'}")
    print(f"  archive: {out_dir / 'history'}/")


if __name__ == "__main__":
    main()
