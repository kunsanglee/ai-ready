#!/usr/bin/env python3
"""
INDEX.md 자동 생성기.

대상 코드베이스를 스캔해 다음 문서들을 단일 인덱스로 묶습니다:
  - 루트 / 모듈의 CLAUDE.md, AGENTS.md
  - 루트의 ARCHITECTURE.md / ANTIPATTERNS.md / NAMING.md / TESTING.md / GLOSSARY.md / CONTRIBUTING.md / README.md
  - docs/**/*.md (ADR, setup 가이드 등)

각 항목은 wikilink + 1줄 요약 형태이며, 요약은 문서의 첫 비-블랭크·비-헤딩·비-frontmatter
라인에서 추출합니다.

ROI 액션 매핑: "docs/INDEX.md (권장) 또는 wiki/index.md 생성" (Rule 1.4, +3점).

실행:
  python3 gen_index.py --target /path/to/repo --out /path/to/repo/docs/INDEX.md
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

DOC_NAMES = {"CLAUDE.md", "AGENTS.md"}
ROOT_GUIDE_NAMES = {
    "ARCHITECTURE.md", "ANTIPATTERNS.md", "NAMING.md", "TESTING.md",
    "GLOSSARY.md", "CONTRIBUTING.md", "README.md", "SECURITY.md",
}
DOCS_DIR = "docs"
EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache", ".ai-ready",
}


def walk(target: Path):
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        yield Path(dirpath), dirnames, filenames


def extract_summary(path: Path, max_chars: int = 120) -> str:
    """첫 비-블랭크, 비-헤딩, 비-frontmatter, 비-메타 라인을 한 줄 요약으로 반환."""
    import re as _re
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(읽기 실패)"
    lines = text.splitlines()
    in_fm = False
    for i, line in enumerate(lines):
        s = line.strip()
        if i == 0 and s == "---":
            in_fm = True
            continue
        if in_fm:
            if s == "---":
                in_fm = False
            continue
        if not s:
            continue
        if s.startswith("#"):
            continue
        # blockquote 마커 제거
        cleaned = s.lstrip("> ").rstrip()
        if not cleaned:
            continue
        # _italic_ 만으로 구성된 메타 라인 (자동 생성·일자 등) 무시
        if _re.fullmatch(r"_.+_", cleaned):
            continue
        # ADR / front-matter-like 키-밸류 (`- 상태:`, `- 일자:`, `- 관련:` 등) 무시
        if _re.match(r"^[-*]\s*(상태|일자|date|status|관련|related)\s*:", cleaned, _re.IGNORECASE):
            continue
        if len(cleaned) > max_chars:
            cleaned = cleaned[: max_chars - 1].rstrip() + "…"
        return cleaned
    return "(요약 없음)"


def collect_docs(target: Path) -> dict[str, list[tuple[Path, str]]]:
    """카테고리별로 문서를 수집해 dict 로 반환.

    카테고리:
      - 'claude'   : 루트/모듈 CLAUDE.md / AGENTS.md
      - 'guides'   : 루트의 ARCHITECTURE/ANTIPATTERNS/NAMING/TESTING/... 가이드
      - 'docs'     : docs/**/*.md (ADR, setup 등)
    """
    claude_docs: list[tuple[Path, str]] = []
    guide_docs: list[tuple[Path, str]] = []
    docs_dir_docs: list[tuple[Path, str]] = []
    for dirpath, _, filenames in walk(target):
        rel_dir = dirpath.relative_to(target)
        for f in filenames:
            full = dirpath / f
            rel = full.relative_to(target)
            summary = None
            if f in DOC_NAMES:
                summary = extract_summary(full)
                claude_docs.append((rel, summary))
            elif rel_dir == Path(".") and f in ROOT_GUIDE_NAMES:
                summary = extract_summary(full)
                guide_docs.append((rel, summary))
            elif str(rel_dir).split("/", 1)[0] == DOCS_DIR and f.endswith(".md"):
                summary = extract_summary(full)
                docs_dir_docs.append((rel, summary))
    return {
        "claude": sorted(claude_docs, key=lambda x: str(x[0])),
        "guides": sorted(guide_docs, key=lambda x: str(x[0])),
        "docs": sorted(docs_dir_docs, key=lambda x: str(x[0])),
    }


def render(target: Path, collected: dict[str, list[tuple[Path, str]]]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    claude = collected["claude"]
    guides = collected["guides"]
    docs_dir = collected["docs"]
    total = len(claude) + len(guides) + len(docs_dir)

    lines = []
    lines.append("# 문서 인덱스")
    lines.append("")
    lines.append(f"_자동 생성: {today} · 대상: `{target.name}` · 문서 {total}개_")
    lines.append("")

    if total == 0:
        lines.append("스캔된 문서가 없습니다.")
        return "\n".join(lines)

    # 루트 CLAUDE.md
    root_claude = [d for d in claude if d[0].parent == Path(".")]
    module_claude = [d for d in claude if d[0].parent != Path(".")]

    if root_claude or guides:
        lines.append("## 루트 가이드")
        lines.append("")
        for path, summary in root_claude:
            lines.append(f"- [`{path}`]({path}) — {summary}")
        for path, summary in guides:
            lines.append(f"- [`{path}`]({path}) — {summary}")
        lines.append("")

    if module_claude:
        lines.append("## 모듈 CLAUDE.md")
        lines.append("")
        for path, summary in module_claude:
            lines.append(f"- [`{path}`]({path}) — {summary}")
        lines.append("")

    if docs_dir:
        # docs/decisions/ 와 그 외 docs/ 문서 분리
        adrs = [d for d in docs_dir if d[0].parts[:2] == ("docs", "decisions")]
        others = [d for d in docs_dir if d[0].parts[:2] != ("docs", "decisions")]
        if adrs:
            lines.append("## ADR (`docs/decisions/`)")
            lines.append("")
            for path, summary in adrs:
                lines.append(f"- [`{path}`]({path}) — {summary}")
            lines.append("")
        if others:
            lines.append("## 기타 문서 (`docs/`)")
            lines.append("")
            for path, summary in others:
                lines.append(f"- [`{path}`]({path}) — {summary}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_재생성: Claude Code 에서 `ai-ready:apply` 스킬을 호출하거나 \"INDEX 재생성해줘\" 라고 말하세요._")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="대상 코드베이스 경로")
    ap.add_argument("--out", required=True, help="INDEX.md 출력 경로")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    out_path = Path(args.out).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    collected = collect_docs(target)
    # 자기 자신은 인덱스에서 제외
    try:
        out_rel = out_path.relative_to(target)
        for k in collected:
            collected[k] = [(p, s) for (p, s) in collected[k] if p != out_rel]
    except ValueError:
        pass
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(target, collected), encoding="utf-8")
    total = sum(len(v) for v in collected.values())
    print(f"인덱스 생성: {out_path}")
    print(f"  대상 문서: claude={len(collected['claude'])}, guides={len(collected['guides'])}, docs={len(collected['docs'])} (총 {total}개)")


if __name__ == "__main__":
    main()
