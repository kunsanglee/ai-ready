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

# 단일 모듈 base package 자동 감지를 위한 JVM 소스 루트와 Application 마커.
JVM_SOURCE_ROOTS = ("src/main/kotlin", "src/main/java")
APPLICATION_MARKERS = ("Application.kt", "Application.java")

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

# M-2: freshness rule 6.1 — 좁은 키워드만 인정
FRESHNESS_KEYWORDS = ("claude.md", "agents.md", "freshness_check", "ai-ready")


# --- Helpers --------------------------------------------------------------

def line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _has_min_content(path: Path, min_lines: int = 3) -> bool:
    """파일이 실질 내용을 가졌는지(0바이트·스텁 문서 구분). 비-공백 줄 수가 min_lines 이상이면 True.

    존재만으로 만점을 주던 규칙(ANTIPATTERNS/NAMING/ARCHITECTURE/TESTING)이 빈 껍데기 문서에
    점수를 주지 않게 하는 최소 품질 게이트. BOM 은 utf-8-sig 로 투명 제거.
    """
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
            return sum(1 for ln in f if ln.strip()) >= min_lines
    except OSError:
        return False


# 도메인 용어집(glossary) 후보 — 네이밍/용어 컨벤션 자산으로 인정(rule 3.3).
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
    # 섹션 수를 부풀렸다(rule 1.3·4.2 점수 인플레) — 제거.
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
    """JVM 소스 루트에서 Application 클래스가 위치한 base package 를 찾는다.

    build/generated 등 산출물은 제외하고, 마커가 여럿이면 경로가 가장 짧은(소스 루트에
    가장 가까운) 것을 택해 결정성을 보장한다 — rglob 은 순서 미보장이라 첫 매칭을 그냥
    쓰면 실행·머신마다 base package 가 달라진다.
    """
    for src in JVM_SOURCE_ROOTS:
        root = target / src
        if not root.is_dir():
            continue
        for marker in APPLICATION_MARKERS:
            try:
                hits = [h for h in root.rglob(marker) if not _rglob_excluded(h, root)]
            except OSError:
                continue
            if hits:
                return min(hits, key=lambda p: (len(p.parts), str(p))).parent
    return None


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
        "proto_files": [],
        "outcome_paths": [],
        "api_build_deps": [],
    }
    seen_modules = set()

    # config 기반 채점 입력 (v0.3.0+) — cfg=None 이면 빈 리스트라 기존 동작 그대로.
    adr_hints_strict = tuple(ADR_DIR_HINTS_STRICT) + tuple(decision_record_hints(cfg))
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
            # config 선언 API 계약 의존성 (예: springdoc) 을 매니페스트 텍스트에서 감지 (M-1, v0.3.0+)
            if contract_deps:
                for f in filenames:
                    if f in BUILD_MANIFESTS:
                        txt = read_text(Path(dirpath) / f).lower()
                        for dep in contract_deps:
                            if dep in txt and dep not in out["api_build_deps"]:
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
            non_http = {p for p in path_hits if not p.startswith("http") and "/" in p}
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
            valid_paths = set()
            for p in path_hits:
                if "/" not in p or p.startswith("http"):
                    continue
                seg = p.split("/")[0]
                if seg in module_first_segs or seg in DOC_DIRS:
                    valid_paths.add(p)
            if len(valid_paths) >= 3:
                r.award(4, sorted(valid_paths)[:5], note=f"유효한 모듈/문서 경로 참조 {len(valid_paths)}건")
            elif len(valid_paths) >= 1:
                r.award(2, sorted(valid_paths), note=f"{len(valid_paths)}건만 발견 (3건 이상 필요)")
            else:
                r.note = "루트 문서에 모듈/문서 경로 참조가 없음"
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
        covered = []
        for m in modules:
            if m == Path("."):
                continue
            if any((target / m / name).exists() for name in CLAUDE_DOC_NAMES):
                covered.append(str(m))
        non_root_modules = [m for m in modules if m != Path(".")]
        pct = (len(covered) / len(non_root_modules)) if non_root_modules else 0
        pts = round(pct * 5)
        if pts > 0:
            r.award(pts, covered[:8],
                    note=f"{len(covered)}/{len(non_root_modules)} 모듈 ({pct*100:.0f}%) 에 CLAUDE.md 존재")
        else:
            r.note = f"0/{len(non_root_modules)} 모듈에 CLAUDE.md 없음"
    rules.append(r)

    # 1.4 인덱스 / MOC 파일
    r = Rule("인덱스 / MOC 파일 (docs/INDEX.md 또는 wiki/index.md)", 3)
    candidates = ["docs/INDEX.md", "docs/index.md", "INDEX.md", "wiki/index.md"]
    found = has_any_path(target, candidates)
    if found:
        r.award(3, found)
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

    # 2.1 루트 CLAUDE.md 200줄 이하
    r = Rule("루트 CLAUDE.md 200줄 이하", 5)
    if root_doc:
        lc = line_count(root_doc)
        if lc <= 200:
            r.award(5, [f"{root_doc.relative_to(target)} ({lc}줄)"])
        elif lc <= 300:
            r.award(2, [f"{root_doc.relative_to(target)} ({lc}줄)"],
                    note="200줄 초과 ~ 300줄 이하 — 다이어트 권장")
        else:
            r.note = f"{lc}줄 — 너무 길어 매 세션 컨텍스트가 부풉니다"
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
        r = Rule("모듈 문서 평균 50줄 이하", 5)
        if module_docs:
            counts = [line_count(d) for d in module_docs]
            avg = sum(counts) / len(counts)
            if avg <= 50:
                r.award(5, [f"모듈 문서 {len(module_docs)}개, 평균 {avg:.0f}줄"])
            elif avg <= 80:
                r.award(3, [f"모듈 문서 {len(module_docs)}개, 평균 {avg:.0f}줄"],
                        note="25~35줄 범위로 줄이세요")
            else:
                r.note = f"모듈 문서 {len(module_docs)}개 / 평균 {avg:.0f}줄 — 너무 장황"
        else:
            r.note = "모듈 단위 문서 없음"
    rules.append(r)

    # 2.3 명시적 DO NOT / 절대 금지 섹션 존재
    r = Rule("명시적 안티패턴 / 절대 금지 가이드 존재", 5)
    hits = [str(d.relative_to(target)) for d in claude_docs
            if regex_any(doc_text.get(d, ""), DONOT_PATTERNS)]
    if hits:
        r.award(5, hits[:5], note=f"{len(hits)}개 문서에 명시적 DO-NOT 표현 포함")
    else:
        r.note = "어떤 CLAUDE.md/AGENTS.md에도 'DO NOT / 절대 / MUST NOT' 표현 없음"
    rules.append(r)

    # 2.4 사용 시점 가이드
    r = Rule("'사용 시점' 가이드 존재", 5)
    hits = [str(d.relative_to(target)) for d in claude_docs
            if regex_any(doc_text.get(d, ""), USAGE_PATTERNS)]
    if hits:
        r.award(5, hits[:5])
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
            r.award(5, [str(wiki_ap.relative_to(target))])
    # config 선언 통합 문서(예: docs/CONVENTIONS.md)에 안티패턴을 두는 프로젝트 인정 (D1).
    # 파일 존재 + 최소 내용 게이트만 본다 — 섹션 헤더 스캔은 거짓양성이라 안 함.
    if r.points == 0:
        for hint in antipattern_doc_hints(cfg):
            hp = target / hint
            if hp.is_file() and _has_min_content(hp):
                r.award(5, [hint], note="config antipatterns.doc_hints 선언 문서 인정")
                break
    if r.points == 0:
        r.note = "안티패턴 문서 없음 — RUBRIC 권장 사항 참조"
    rules.append(r)

    r = Rule("아키텍처 의사결정 기록 (ADR / wiki/decisions)", 5)
    if scan["adr_dirs"]:
        r.award(5, scan["adr_dirs"][:3])
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
        base_package = find_base_package(target)
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
                # C4: 비-JVM 또는 Application 마커 부재 — 레이아웃을 측정하지 못한 것이지
                # "60% 미만"이 아니다. 0점 침묵 대신 미측정임을 명시.
                r.award(4, evidence,
                        note=("카탈로그 OK / 표준 레이아웃 미측정 — JVM-Spring 웹 레이아웃"
                              "(controller/service/domain/repository)이 아니면 카탈로그만으로 충분합니다"))
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
            r.note = ("단일 모듈 — 카탈로그(docs/PACKAGES.md) 도입 + 도메인 패키지 표준 레이아웃 일관성 "
                      "(controller/service/domain/repository 4개 중 3개 이상) 확보 시 만점")
        rules.append(r)
    else:
        r = Rule("빌드 매니페스트로 의존 그래프 추출 가능", 5)
        if len(modules) >= 2:
            r.award(5, [str(m) for m in modules[:6]],
                    note=f"빌드 매니페스트 기반 모듈 {len(modules)}개 감지")
        rules.append(r)

    r = Rule("모듈 간 API 계약 문서화 (OpenAPI/proto/contracts)", 5)
    contract_signals = []
    for hint in ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml",
                 "swagger.yml", "swagger.json", "contracts", "proto", "protos"):
        if (target / hint).exists():
            contract_signals.append(hint)
    if scan["proto_files"]:
        contract_signals.append(str(scan["proto_files"][0].relative_to(target)))
    # config 선언 빌드 의존성 (springdoc 등 코드 기반 OpenAPI 생성) 도 계약 신호로 인정 (v0.3.0+)
    if scan.get("api_build_deps"):
        contract_signals.extend(f"{d} (빌드 의존성)" for d in scan["api_build_deps"])
        r.note = "springdoc 등 코드 기반 OpenAPI 생성 의존성 인정 (config rubric.api_contracts.build_deps)"
    if contract_signals:
        r.award(5, contract_signals[:4])
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
    if not settings.is_file():
        return []
    try:
        data = json.loads(read_text(settings))
    except (ValueError, OSError):
        return []
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    if not isinstance(hooks, dict):
        return []
    verify_kw = ("ktlint", "detekt", "lint", "test", "format", "check",
                 "gradlew", "prettier", "eslint", "mypy", "ruff", "tsc",
                 "typecheck", "build")
    exclude_kw = ("freshness", "ai-ready", ".ai-ready")
    signals = []
    for event in ("PreToolUse", "PostToolUse", "Stop"):
        for matcher in hooks.get(event, []) or []:
            for h in (matcher.get("hooks", []) or []):
                cmd = (h.get("command", "") or "").lower()
                if any(k in cmd for k in verify_kw) and not any(x in cmd for x in exclude_kw):
                    signals.append(f".claude/settings.json:{event}")
                    break
    return signals


def score_verification(target: Path, scan: dict, doc_text: dict) -> dict:
    rules = []

    r = Rule("기계적 검증 훅 (pre-commit / AI 에이전트 hook)", 3)
    found = has_any_path(target, PRECOMMIT_FILES)
    harness = _ai_harness_verification_hooks(target)
    evidence = found + harness
    if evidence:
        note = ""
        if harness and not found:
            note = "AI 에이전트 편집/커밋 시점 검증 hook 인정 (.claude/settings.json)"
        r.award(3, evidence, note=note)
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
    found = []
    for c in candidates:
        p = target / c
        if not p.exists():
            continue
        if p.is_file():
            text = read_text(p).lower()
            if any(k in text for k in FRESHNESS_KEYWORDS):
                found.append(c)
        else:
            for sub in p.rglob("*"):
                if sub.is_file():
                    if any(k in read_text(sub).lower() for k in FRESHNESS_KEYWORDS):
                        found.append(c)
                        break
    if found:
        r.award(5, found)
    rules.append(r)

    # 6.2
    r = Rule("CLAUDE.md 갱신 프로토콜 문서화", 5)
    for d in scan["claude_docs"]:
        text = doc_text.get(d, "")
        if any(k in text for k in ("갱신 트리거", "Maintenance", "유지보수", "update protocol",
                                   "Updating CLAUDE", "갱신 방식")):
            r.award(5, [str(d.relative_to(target))])
            break
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
    if found:
        r.award(7, found)
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
    if scan["outcome_paths"]:
        r.award(8, scan["outcome_paths"][:3])
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
        "저장소 루트에 CLAUDE.md를 만드세요. 200줄 이하로 유지하고, 백과사전이 아닌 모듈 문서로의 지도 역할로 사용하세요."),
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
    "루트 CLAUDE.md 200줄 이하": (30, 4,
        "루트 CLAUDE.md를 다이어트하세요. 컨벤션은 CONVENTIONS.md, 안티패턴은 ANTIPATTERNS.md로 분리하고 루트에는 지도만 남기세요."),
    "모듈 문서 평균 50줄 이하": (30, 3,
        "모듈 문서 점검 — 60줄을 넘는 문서는 DESIGN.md, ANTIPATTERNS.md 등으로 분리하세요."),
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
        "단일 모듈 프로젝트는 패키지 = 논리 모듈. (1) docs/PACKAGES.md 카탈로그에 3개 이상 패키지 섹션을 채우고, "
        "(2) 도메인 패키지들이 일관된 표준 레이아웃 (controller/service/domain/repository 4개 중 3개 이상) 을 따르도록 "
        "정렬하세요. 둘 다 만족하면 만점."),
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
    lines.append("`/ai-ready:apply` 로 액션을 반영한 변경은 `/loop-run`(수렴까지) 또는 1회 점검 `/loop-review` 로 "
                 "검증하고, 거기서 잡힌 실수는 `/loop-lessons` 로 `docs/ANTIPATTERNS.md` 에 반영해 다음 audit 의 "
                 "입력으로 되돌립니다 — audit→apply→verify→lessons→audit 순환.")
    return "\n".join(lines)


def render_readme(audit: dict) -> str:
    """`.ai-ready/README.md` — 산출물 안내 + 플러그인 설치·사용 가이드.

    팀원·신규 합류자·외부 컨트리뷰터가 `.ai-ready/` 폴더를 처음 봤을 때
    무엇이 들어 있고 어떻게 갱신·활용하는지 자족적으로 알 수 있도록 한다.
    """
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
    lines.append("| `dashboard.html` | 점수·카테고리 시각화 + 추이 sparkline (브라우저로 직접 열기) |")
    lines.append("| `history/{ts}.json` | 매 실행마다 archive — dashboard 추이 차트의 입력 |")
    lines.append("| `scaffolds/<module>/CLAUDE.md` | 핫 모듈용 CLAUDE.md 초안. 검토 후 실제 모듈 디렉토리로 이동 |")
    lines.append("| `scaffolds/ANTIPATTERNS.md` | 180일 git 핫스팟 기반 안티패턴 시드. 클러스터링된 후보 — 검토 후 채택 |")
    lines.append("| `hooks/freshness_check.sh` | (선택) Claude Code Stop hook — 소스 변경에 비해 CLAUDE.md가 오래된 경우 경고 |")
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
    lines.append("4. apply 로 반영한 변경은 `/loop-run`(수렴까지) 또는 `/loop-review`(1회 점검)로 검증하고, "
                 "잡힌 실수는 `/loop-lessons` 로 `docs/ANTIPATTERNS.md` 에 반영한다 (다음 audit 입력으로 환류).")
    lines.append("5. 월 1회 재실행해 점수 추이를 `audit.json` 기반으로 비교한다.")
    lines.append("")
    lines.append("## 주의")
    lines.append("")
    lines.append("- **휴리스틱 점수**: ±5점 노이즈. 절대값이 아니라 추이를 본다.")
    lines.append("- **scaffold/는 초안**: `scaffolds/` 하위 산출물은 그대로 쓰지 말고 검토·이동·정리 후 실제 위치에 둔다.")
    lines.append("  - `scaffolds/<module>/CLAUDE.md` → 검토 후 `<module>/CLAUDE.md` 로 `git mv`")
    lines.append("  - `scaffolds/ANTIPATTERNS.md` → 검토 후 `docs/ANTIPATTERNS.md` 로 채택. 시드와 운영본이 공존할 때는 `docs/` 가 권위")
    lines.append("- **재실행 시 덮어쓰기**: `audit.json` / `audit-report.md` / `dashboard.html` / 본 README는 매 실행 시 갱신된다. 직접 수정한 내용은 사라진다.")
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
    """T-4: 플러그인의 freshness_check.sh 를 .ai-ready/hooks/ 에 실제 복사.

    install_hook.py 가 등록할 때 `$CLAUDE_PROJECT_DIR/.ai-ready/hooks/freshness_check.sh`
    경로를 가리키므로 파일이 실제로 존재해야 한다 (이전엔 SKILL.md 만 광고하고 안 만들었음).
    """
    src = Path(__file__).resolve().parent.parent / "hooks" / "freshness_check.sh"
    if not src.is_file():
        return None
    dst_dir = out_dir / "hooks"
    try:
        dst_dir.mkdir(exist_ok=True)
        dst = dst_dir / "freshness_check.sh"
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        os.chmod(dst, 0o755)
        return dst
    except OSError:
        return None


def run(target: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    # config-aware 채점 (v0.3.0+) — 없으면 cfg=None 으로 기존 동작.
    cfg = load_config(target)
    # M-5: 단일 walk
    scan = scan_target(target, cfg)
    # M-4: CLAUDE.md 텍스트 1회 읽기 캐시
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
    (out_dir / "README.md").write_text(render_readme(audit), encoding="utf-8")
    _archive_history(out_dir, audit)
    _copy_freshness_hook(out_dir)
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
    print(f"  모듈: {audit['module_count']}개, CLAUDE.md 문서: {audit['claude_doc_count']}개")
    print(f"  생성: {out_dir / 'audit.json'}")
    print(f"  생성: {out_dir / 'audit-report.md'}")
    print(f"  생성: {out_dir / 'README.md'}")
    print(f"  archive: {out_dir / 'history'}/")
    if (out_dir / 'hooks' / 'freshness_check.sh').exists():
        print(f"  생성: {out_dir / 'hooks' / 'freshness_check.sh'}")


if __name__ == "__main__":
    main()
