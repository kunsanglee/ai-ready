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

# --- Constants -------------------------------------------------------------

BUILD_MANIFESTS = {
    "build.gradle.kts", "build.gradle", "pom.xml",
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
}

CLAUDE_DOC_NAMES = {"CLAUDE.md", "AGENTS.md"}
ANTIPATTERN_NAMES = {"ANTIPATTERNS.md", "ANTI_PATTERNS.md", "anti-patterns.md"}
ARCH_NAMES = {"ARCHITECTURE.md", "DEPENDENCIES.md", "dependencies.md"}
NAMING_NAMES = {"NAMING.md", "naming.md"}

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
)

PRECOMMIT_FILES = (
    ".husky", ".git/hooks/pre-commit", "lefthook.yml", ".pre-commit-config.yaml",
)

EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache",
}

# 명시적 DO-NOT 가이드를 나타내는 표현 (다국어)
DONOT_PATTERNS = [
    r"\bDO NOT\b", r"\bMUST NOT\b", r"\bNEVER\b",
    r"절대\s*하지", r"절대\s*금지", r"금지\b", r"하지\s*마", r"❌", r"⛔",
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


def has_any_path(target: Path, candidates) -> list[str]:
    found = []
    for c in candidates:
        if (target / c).exists():
            found.append(c)
    return found


def regex_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


# --- Single-pass scanner (M-5) -------------------------------------------

def scan_target(target: Path) -> dict:
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
    }
    seen_modules = set()

    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        rel_dir = Path(dirpath).relative_to(target)
        rel_str = str(rel_dir).lower().replace("\\", "/")

        # ADR 디렉토리 감지 (M-1)
        is_adr = False
        for hint in ADR_DIR_HINTS_STRICT:
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

    # 1.1 루트 CLAUDE.md / AGENTS.md 존재
    r = Rule("루트 CLAUDE.md 또는 AGENTS.md 존재", 3)
    root_doc = next((d for d in claude_docs if d.parent == target), None)
    if root_doc:
        r.award(3, [str(root_doc.relative_to(target))])
    rules.append(r)

    # 1.2 루트 문서가 3개 이상의 모듈 경로 참조 (C-1 fix: 모듈 첫 segment 필터)
    r = Rule("루트 문서가 3개 이상의 모듈 경로/문서 참조", 4)
    if root_doc:
        text = doc_text.get(root_doc, "")
        path_hits = re.findall(r"[`\[]([\w\-./]+/[\w\-./]+)[`\]]", text)
        # 실제 모듈의 첫 segment를 가진 경로만 인정
        module_first_segs = {str(m).split("/")[0] for m in modules if m != Path(".")}
        valid_paths = {
            p for p in path_hits
            if "/" in p
            and not p.startswith("http")
            and p.split("/")[0] in module_first_segs
        }
        if len(valid_paths) >= 3:
            r.award(4, sorted(valid_paths)[:5], note=f"유효한 모듈 경로 참조 {len(valid_paths)}건")
        elif len(valid_paths) >= 1:
            r.award(2, sorted(valid_paths), note=f"{len(valid_paths)}건만 발견 (3건 이상 필요)")
        else:
            r.note = "루트 문서에 모듈 경로 참조가 없음"
    rules.append(r)

    # 1.3 모듈별 CLAUDE.md 커버리지
    r = Rule("모듈별 CLAUDE.md 커버리지", 5)
    if modules:
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
    else:
        r.note = "모듈 미감지 (단일 패키지 저장소)"
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

    # 2.2 모듈 문서 평균 50줄 이하
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


def score_tribal_knowledge(target: Path, scan: dict, doc_text: dict) -> dict:
    rules = []

    r = Rule("ANTIPATTERNS.md (또는 wiki/anti-patterns/) 존재", 5)
    if scan["antipattern_docs"]:
        r.award(5, [str(p.relative_to(target)) for p in scan["antipattern_docs"]])
    else:
        wiki_ap = target / "wiki" / "anti-patterns"
        if wiki_ap.is_dir() and any(wiki_ap.iterdir()):
            r.award(5, [str(wiki_ap.relative_to(target))])
    if r.points == 0:
        r.note = "안티패턴 문서 없음 — RUBRIC 권장 사항 참조"
    rules.append(r)

    r = Rule("아키텍처 의사결정 기록 (ADR / wiki/decisions)", 5)
    if scan["adr_dirs"]:
        r.award(5, scan["adr_dirs"][:3])
    rules.append(r)

    r = Rule("네이밍 컨벤션 문서화", 5)
    if scan["naming_docs"]:
        r.award(5, [str(p.relative_to(target)) for p in scan["naming_docs"]])
    else:
        for d in scan["claude_docs"]:
            text = doc_text.get(d, "").lower()
            if "naming" in text or "네이밍" in text or "convention" in text or "컨벤션" in text:
                r.award(3, [str(d.relative_to(target))],
                        note="CLAUDE.md에 네이밍 언급 있음 (NAMING.md로 분리 권장)")
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
        r.award(5, [str(p.relative_to(target)) for p in scan["arch_docs"]])
    rules.append(r)

    r = Rule("빌드 매니페스트로 의존 그래프 추출 가능", 5)
    if len(modules) >= 2:
        r.award(5, [str(m) for m in modules[:6]],
                note=f"빌드 매니페스트 기반 모듈 {len(modules)}개 감지")
    elif len(modules) == 1:
        r.award(2, [str(modules[0])], note="단일 모듈 저장소 — 부분 점수")
    rules.append(r)

    r = Rule("모듈 간 API 계약 문서화 (OpenAPI/proto/contracts)", 5)
    contract_signals = []
    for hint in ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml",
                 "swagger.yml", "swagger.json", "contracts", "proto", "protos"):
        if (target / hint).exists():
            contract_signals.append(hint)
    if scan["proto_files"]:
        contract_signals.append(str(scan["proto_files"][0].relative_to(target)))
    if contract_signals:
        r.award(5, contract_signals[:4])
    rules.append(r)

    return {
        "id": 4, "name": "모듈 간 의존성 추적",
        "rules": [r.to_dict() for r in rules],
        "score": sum(r.points for r in rules),
        "max": sum(r.max for r in rules),
    }


def score_verification(target: Path, scan: dict, doc_text: dict) -> dict:
    rules = []

    r = Rule("커밋 전 훅 (pre-commit) 존재", 3)
    found = has_any_path(target, PRECOMMIT_FILES)
    if found:
        r.award(3, found)
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
    test_doc = (target / "TESTING.md")
    if test_doc.exists():
        r.award(4, ["TESTING.md"])
    else:
        for d in scan["claude_docs"]:
            t = doc_text.get(d, "").lower()
            if "test" in t and ("convention" in t or "naming" in t or "given" in t or "테스트" in t):
                r.award(3, [str(d.relative_to(target))],
                        note="CLAUDE.md에 테스트 언급 있음 (TESTING.md로 분리 권장)")
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


def score_outcomes(target: Path, scan: dict) -> dict:
    rules = []

    # 7.1: metrics 디렉토리 또는 metrics.md
    r = Rule("매트릭스 문서 / 대시보드 존재", 7)
    candidates = ["metrics", "analytics", ".claude/metrics", "dashboards", "metrics.md"]
    found = has_any_path(target, candidates)
    if found:
        r.award(7, found)
    rules.append(r)

    # 7.2 (M-3 fix): 정확 이름 매칭만
    r = Rule("PR 리뷰 시간 / AI 사용량 / 토큰 추적", 8)
    if scan["outcome_paths"]:
        r.award(8, scan["outcome_paths"][:3])
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
        "NAMING.md를 만들거나 CLAUDE.md에 네이밍 컨벤션 섹션을 추가하세요."),
    "모듈 의존성 맵 / 다이어그램 존재": (45, 4,
        "ARCHITECTURE.md 또는 DEPENDENCIES.md를 만들고 Mermaid 다이어그램으로 모듈 의존성을 표현하세요."),
    "빌드 매니페스트로 의존 그래프 추출 가능": (0, 0,
        "이미 빌드 시스템이 커버하고 있습니다."),
    "모듈 간 API 계약 문서화 (OpenAPI/proto/contracts)": (90, 3,
        "OpenAPI 명세나 proto 스키마를 도입해 계약을 기계 판독 가능한 형태로 유지하세요."),
    "커밋 전 훅 (pre-commit) 존재": (20, 4,
        ".husky 또는 lefthook을 추가해 커밋 시점에 lint/format/test를 강제하세요. AI가 만든 PR이 가장 큰 수혜를 봅니다."),
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


def build_action_list(category_results: list[dict]) -> list[dict]:
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
            roi = (impact * missing) / max(effort, 1) * 60
            actions.append({
                "category": cat["name"],
                "rule": rule["name"],
                "missing_points": missing,
                "effort_minutes": effort,
                "impact": impact,
                "roi_score": round(roi, 2),
                "action": message,
                "current_evidence": rule["evidence"],
                "current_note": rule["note"],
            })
    actions.sort(key=lambda a: a["roi_score"], reverse=True)
    return actions


def _sanitize_md_cell(s: str) -> str:
    """L-5: markdown 표 셀 내 파이프 문자 escape."""
    return s.replace("|", "\\|")


def render_report(audit: dict) -> str:
    lines = []
    lines.append(f"# AI 준비도 감사 리포트")
    lines.append("")
    lines.append(f"- **대상**: `{audit['target']}`")
    lines.append(f"- **생성 시각**: {audit['timestamp']}")
    lines.append(f"- **점수**: **{audit['total_score']} / {audit['max_score']}** — _{audit['grade']}_")
    lines.append(f"- **감지된 모듈**: {audit['module_count']}")
    lines.append(f"- **CLAUDE.md 문서 수**: {audit['claude_doc_count']}")
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
        lines.append("| 순위 | ROI | 소요 | 카테고리 | 액션 |")
        lines.append("|------|-----|------|----------|------|")
        for i, a in enumerate(audit["actions"][:15], 1):
            lines.append(
                f"| {i} | {a['roi_score']} | {a['effort_minutes']}분 "
                f"| {_sanitize_md_cell(a['category'])} | {_sanitize_md_cell(a['action'])} |"
            )
    lines.append("")
    lines.append("## 다음 실행")
    lines.append("")
    lines.append("월 1회 재실행하세요. 절대 점수가 아닌 **점수 추이**에 주목합니다.")
    return "\n".join(lines)


# --- Main -----------------------------------------------------------------

def run(target: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    # M-5: 단일 walk
    scan = scan_target(target)
    # M-4: CLAUDE.md 텍스트 1회 읽기 캐시
    doc_text = {p: read_text(p) for p in scan["claude_docs"]}

    categories = [
        score_navigation(target, scan, doc_text),
        score_doc_quality(target, scan, doc_text),
        score_tribal_knowledge(target, scan, doc_text),
        score_dependency_tracking(target, scan),
        score_verification(target, scan, doc_text),
        score_freshness(target, scan, doc_text),
        score_outcomes(target, scan),
    ]
    total = sum(c["score"] for c in categories)
    audit = {
        "schema_version": 2,  # 1 → 2: scan 구조 + scoring 정밀화
        "target": str(target),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "module_count": len(scan["modules"]),
        "claude_doc_count": len(scan["claude_docs"]),
        "modules": [str(m) for m in scan["modules"]],
        "claude_docs": [str(d.relative_to(target)) for d in scan["claude_docs"]],
        "total_score": total,
        "max_score": 100,
        "grade": grade_for(total),
        "categories": categories,
        "actions": build_action_list(categories),
    }
    (out_dir / "audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False))
    (out_dir / "audit-report.md").write_text(render_report(audit), encoding="utf-8")
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


if __name__ == "__main__":
    main()
