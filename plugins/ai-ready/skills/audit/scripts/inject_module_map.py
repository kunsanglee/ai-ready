#!/usr/bin/env python3
"""
루트 CLAUDE.md (또는 AGENTS.md) 에 "## 모듈 맵" 섹션을 idempotent하게 삽입/갱신.

기존 섹션이 있으면 교체, 없으면 파일 끝에 추가합니다.
모듈 요약은 그 모듈의 CLAUDE.md/AGENTS.md 첫 줄에서 가져오며, 없으면 "(설명 없음)".

ROI 액션 매핑: "루트 CLAUDE.md에 모듈 맵 섹션 추가" (Rule 1.2, +4점).

실행:
  python3 inject_module_map.py --target /path/to/repo
  python3 inject_module_map.py --target /path/to/repo --dry-run   # 미리보기
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DOC_NAMES = ("CLAUDE.md", "AGENTS.md")
BUILD_MANIFESTS = {
    "build.gradle.kts", "build.gradle", "pom.xml",
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
}
EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache", ".ai-ready",
}

SECTION_HEADER = "## 모듈 맵"
SECTION_BEGIN = "<!-- module-map:begin (auto-generated) -->"
SECTION_END = "<!-- module-map:end -->"


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
            # _italic_ 메타 라인 (자동 생성·일자 등) 스킵
            import re as _re
            if _re.fullmatch(r"_.+_", cleaned):
                continue
            # ADR 스타일 키-밸류 메타 (`- 상태:`, `- 일자:` 등) 스킵
            if _re.match(r"^[-*]\s*(상태|일자|date|status|관련|related)\s*:", cleaned, _re.IGNORECASE):
                continue
            if len(cleaned) > max_chars:
                cleaned = cleaned[: max_chars - 1].rstrip() + "…"
            return cleaned
    return "(설명 없음)"


def find_root_doc(target: Path) -> Path | None:
    for name in DOC_NAMES:
        p = target / name
        if p.exists():
            return p
    return None


def build_section(target: Path, modules: list[Path]) -> str:
    lines = [SECTION_HEADER, "", SECTION_BEGIN, ""]
    lines.append("> 자동 생성됩니다. 수동 편집은 다음 갱신 시 덮어쓰여집니다.")
    lines.append("> 갱신: Claude Code 에서 `ai-ready:apply` 스킬을 호출하거나 \"모듈 맵 갱신해줘\" 라고 말하세요.")
    lines.append("")
    if not modules:
        lines.append("(빌드 매니페스트로 감지된 모듈 없음)")
    else:
        for m in modules:
            summary = get_module_summary(target, m)
            lines.append(f"- `{m}` — {summary}")
    lines.append("")
    lines.append(SECTION_END)
    return "\n".join(lines)


def inject(text: str, new_section: str) -> str:
    """기존 섹션이 있으면 교체, 없으면 파일 끝에 추가."""
    if SECTION_BEGIN in text and SECTION_END in text:
        # marker 사이를 교체
        before, _, rest = text.partition(SECTION_BEGIN)
        # before은 SECTION_HEADER까지 포함할 수 있음 — 그것까지 정리
        if before.rstrip().endswith(SECTION_HEADER):
            before = before.rstrip()[: -len(SECTION_HEADER)].rstrip() + "\n"
        _, _, after = rest.partition(SECTION_END)
        # before/after를 깨끗이 합치기
        return before.rstrip() + "\n\n" + new_section + after
    # 끝에 추가
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
    section = build_section(target, modules)
    original = root_doc.read_text(encoding="utf-8")
    new_text = inject(original, section)

    if args.dry_run:
        print("=== dry-run 결과 ===")
        print(section)
        print()
        print(f"_변경 여부: {'있음' if new_text != original else '없음'}_")
        return

    if new_text == original:
        print(f"변경 없음: {root_doc}")
        return
    root_doc.write_text(new_text, encoding="utf-8")
    print(f"모듈 맵 갱신: {root_doc}")
    print(f"  모듈 {len(modules)}개")


if __name__ == "__main__":
    main()
