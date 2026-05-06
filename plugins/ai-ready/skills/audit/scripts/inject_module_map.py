#!/usr/bin/env python3
"""
모듈 맵을 두 위치에 idempotent 하게 갱신:

1. `docs/MODULE_MAP.md` — 전체 모듈 목록 (52+ 엔트리). 단일 출처.
2. 루트 CLAUDE.md / AGENTS.md 의 `## 모듈 맵` 섹션 — 짧은 stub:
   - 전체 목록 링크
   - 자체 `CLAUDE.md` 가 있는 "documented" 모듈만 (audit 의 모듈 경로 참조 검사 통과 + skim 용도)
   - 모듈 N 개 통계

이렇게 분리하면 매 세션 자동 로드되는 루트 분량을 ~50줄 이상 절감하면서도
모듈 검색·진입은 여전히 1-홉 (루트 → MODULE_MAP.md) 으로 가능.

모듈 요약은 그 모듈의 CLAUDE.md/AGENTS.md 첫 줄에서 가져오며, 없으면 "(설명 없음)".

ROI 액션 매핑: "루트 CLAUDE.md에 모듈 맵 섹션 추가" + "루트 CLAUDE.md 200줄 이하"
(Rule 1.2 + 2.1).

실행:
  python3 inject_module_map.py --target /path/to/repo
  python3 inject_module_map.py --target /path/to/repo --dry-run   # 미리보기
"""
from __future__ import annotations

import argparse
import os
import re as _re
import sys
from pathlib import Path

DOC_NAMES = ("CLAUDE.md", "AGENTS.md")
BUILD_MANIFESTS = {
    "build.gradle.kts", "build.gradle", "pom.xml",
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
    # iOS / Apple
    "Package.swift",   # Swift Package Manager
    "Podfile",         # CocoaPods
}
EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache", ".ai-ready",
}

SECTION_HEADER = "## 모듈 맵"
SECTION_BEGIN = "<!-- module-map:begin (auto-generated) -->"
SECTION_END = "<!-- module-map:end -->"

MODULE_MAP_FILE = "docs/MODULE_MAP.md"

STUB_DOCUMENTED_LIMIT = 10  # 루트 stub 에 노출할 documented 모듈 최대 수


def walk(target: Path):
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        yield Path(dirpath), dirnames, filenames


def find_modules(target: Path) -> list[Path]:
    seen = set()
    out = []
    for dirpath, _, filenames in walk(target):
        for f in filenames:
            if f in BUILD_MANIFESTS:
                rel = dirpath.relative_to(target)
                if rel == Path("."):
                    break
                if rel not in seen:
                    seen.add(rel)
                    out.append(rel)
                break
    return sorted(out, key=str)


def get_module_summary(target: Path, module: Path, max_chars: int = 100) -> str:
    """모듈 디렉토리의 CLAUDE.md/AGENTS.md에서 첫 의미있는 줄 추출."""
    for name in DOC_NAMES:
        p = target / module / name
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
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
            if not s or s.startswith("#"):
                continue
            cleaned = s.lstrip("> ").rstrip()
            if not cleaned:
                continue
            if _re.fullmatch(r"_.+_", cleaned):
                continue
            if _re.match(r"^[-*]\s*(상태|일자|date|status|관련|related)\s*:", cleaned, _re.IGNORECASE):
                continue
            if len(cleaned) > max_chars:
                cleaned = cleaned[: max_chars - 1].rstrip() + "…"
            return cleaned
    return "(설명 없음)"


def has_module_doc(target: Path, module: Path) -> bool:
    return any((target / module / name).exists() for name in DOC_NAMES)


def find_root_doc(target: Path) -> Path | None:
    for name in DOC_NAMES:
        p = target / name
        if p.exists():
            return p
    return None


def build_full_map_doc(target: Path, modules: list[Path]) -> str:
    """docs/MODULE_MAP.md 전체 본문."""
    today_iso = ""  # 일자 추가 안 함 (자주 변경)
    lines = ["# 모듈 맵", ""]
    lines.append("> 빌드 매니페스트(`build.gradle.kts` 등) 로 자동 감지된 모듈 카탈로그.")
    lines.append("> 모듈별 1줄 요약은 그 모듈의 `CLAUDE.md` 첫 줄에서 추출. (설명 없음) 표시는 모듈 가이드를 추가하면 자동 채워짐.")
    lines.append("> 갱신: Claude Code 에서 `ai-ready:apply` 스킬을 호출하거나 \"모듈 맵 갱신해줘\" 라고 말하세요.")
    lines.append("")
    lines.append(SECTION_BEGIN)
    lines.append("")
    if not modules:
        lines.append("(빌드 매니페스트로 감지된 모듈 없음)")
    else:
        for m in modules:
            summary = get_module_summary(target, m)
            lines.append(f"- `{m}` — {summary}")
    lines.append("")
    lines.append(SECTION_END)
    lines.append("")
    return "\n".join(lines)


def build_root_stub(target: Path, modules: list[Path]) -> str:
    """루트 CLAUDE.md 의 `## 모듈 맵` stub.

    audit 의 모듈 경로 참조 검사를 통과하기 위해 documented 모듈을 일부 노출.
    """
    documented = [m for m in modules if has_module_doc(target, m)]
    documented_count = len(documented)
    total = len(modules)
    sample = documented[:STUB_DOCUMENTED_LIMIT]

    lines = [SECTION_HEADER, "", SECTION_BEGIN, ""]
    lines.append("> 자동 생성됩니다. 수동 편집은 다음 갱신 시 덮어쓰여집니다.")
    lines.append("> 갱신: Claude Code 에서 `ai-ready:apply` 스킬을 호출하거나 \"모듈 맵 갱신해줘\" 라고 말하세요.")
    lines.append("")
    lines.append(f"전체 모듈 카탈로그 ({total}개): [`{MODULE_MAP_FILE}`]({MODULE_MAP_FILE})")
    if documented_count:
        lines.append("")
        lines.append(f"가이드가 작성된 핵심 모듈 ({documented_count}개 중 상위 {len(sample)}개):")
        lines.append("")
        for m in sample:
            summary = get_module_summary(target, m)
            lines.append(f"- [`{m}`]({m}/CLAUDE.md) — {summary}")
        if documented_count > len(sample):
            lines.append(f"- … 외 {documented_count - len(sample)}개 (전체 목록은 위 카탈로그 링크 참조)")
    lines.append("")
    lines.append(SECTION_END)
    return "\n".join(lines)


def inject(text: str, new_section: str) -> str:
    """기존 섹션이 있으면 교체, 없으면 파일 끝에 추가."""
    if SECTION_BEGIN in text and SECTION_END in text:
        before, _, rest = text.partition(SECTION_BEGIN)
        if before.rstrip().endswith(SECTION_HEADER):
            before = before.rstrip()[: -len(SECTION_HEADER)].rstrip() + "\n"
        _, _, after = rest.partition(SECTION_END)
        return before.rstrip() + "\n\n" + new_section + after
    sep = "\n\n" if not text.endswith("\n\n") else ""
    if not text.endswith("\n"):
        text += "\n"
    return text + sep + new_section + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="대상 코드베이스 경로")
    ap.add_argument("--dry-run", action="store_true", help="실제 파일은 수정하지 않고 결과만 출력")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    root_doc = find_root_doc(target)
    if root_doc is None:
        print(f"오류: 루트 CLAUDE.md / AGENTS.md를 찾을 수 없음. 먼저 생성하세요.", file=sys.stderr)
        sys.exit(3)

    modules = find_modules(target)
    full_doc_text = build_full_map_doc(target, modules)
    stub = build_root_stub(target, modules)
    full_path = target / MODULE_MAP_FILE
    original_root = root_doc.read_text(encoding="utf-8")
    new_root = inject(original_root, stub)
    original_full = full_path.read_text(encoding="utf-8") if full_path.exists() else ""

    if args.dry_run:
        print("=== dry-run: docs/MODULE_MAP.md ===")
        print(full_doc_text)
        print()
        print("=== dry-run: 루트 CLAUDE.md 의 ## 모듈 맵 stub ===")
        print(stub)
        print()
        print(f"_변경 여부: docs/MODULE_MAP.md = {'있음' if full_doc_text != original_full else '없음'}, 루트 = {'있음' if new_root != original_root else '없음'}_")
        return

    full_path.parent.mkdir(parents=True, exist_ok=True)
    if full_doc_text != original_full:
        full_path.write_text(full_doc_text, encoding="utf-8")
        print(f"전체 모듈 맵 갱신: {full_path}")
    else:
        print(f"변경 없음: {full_path}")
    if new_root != original_root:
        root_doc.write_text(new_root, encoding="utf-8")
        print(f"루트 stub 갱신: {root_doc}")
    else:
        print(f"변경 없음: {root_doc}")
    documented_count = sum(1 for m in modules if has_module_doc(target, m))
    print(f"  모듈 {len(modules)}개 (가이드 작성된 모듈 {documented_count}개)")


if __name__ == "__main__":
    main()
