#!/usr/bin/env python3
"""
CLAUDE.md / AGENTS.md의 헤딩 섹션 중 키워드 매칭되는 것을 별도 파일로 추출.

testing / naming 등 흩어진 컨벤션을 전용 파일로 분리하는 데 사용합니다.
원본 CLAUDE.md는 수정하지 않습니다 — 사용자가 직접 정리하세요.

ROI 규칙 (audit 의 규칙 이름 그대로 — 번호가 아니라 이름으로 가리킨다):
  - "테스트 컨벤션 문서화 (CLAUDE.md 또는 TESTING.md)" (+4점)
  - "네이밍 컨벤션 문서화" (+5점)

실행:
  python3 extract_section.py --target /path --out TESTING.md --kind testing
  python3 extract_section.py --target /path --out NAMING.md --kind naming
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
from managed_doc import guard_overwrite, add_force_arg  # noqa: E402

DOC_NAMES = {"CLAUDE.md", "AGENTS.md"}
EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache", ".ai-ready",
    "worktrees",  # git worktree(.claude/worktrees) = repo 전체 복사본 — 통째 중복 수집 방지
}

KEYWORD_SETS = {
    "testing": ("test", "테스트", "테스팅", "spec", "given", "assert"),
    "naming": ("naming", "네이밍", "convention", "컨벤션", "이름"),
}

TITLE_FOR_KIND = {
    "testing": "테스트 컨벤션",
    "naming": "네이밍 컨벤션",
}


def walk(target: Path):
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        yield Path(dirpath), dirnames, filenames


def find_docs(target: Path) -> list[Path]:
    out = []
    for dirpath, _, filenames in walk(target):
        for f in sorted(filenames):
            if f in DOC_NAMES:
                out.append(dirpath / f)
    return sorted(out, key=str)  # 출처 섹션 순서를 walk 순서에 의존하지 않게 — 멱등


def extract_matching_sections(text: str, keywords: tuple[str, ...]) -> list[str]:
    """`## ` 헤딩 라인에 keyword가 포함된 섹션을 추출."""
    sections: list[str] = []
    lines = text.splitlines()
    current_lines: list[str] = []
    in_section = False

    def heading_matches(line: str) -> bool:
        s = line.strip().lower()
        return any(k in s for k in keywords)

    for line in lines:
        is_h2 = line.startswith("## ") and not line.startswith("###")
        is_h1 = line.startswith("# ") and not line.startswith("##")
        if is_h2:
            # 이전 섹션 마감
            if in_section and current_lines:
                sections.append("\n".join(current_lines).rstrip())
            in_section = heading_matches(line)
            current_lines = [line] if in_section else []
        elif is_h1:
            if in_section and current_lines:
                sections.append("\n".join(current_lines).rstrip())
            in_section = False
            current_lines = []
        else:
            if in_section:
                current_lines.append(line)
    if in_section and current_lines:
        sections.append("\n".join(current_lines).rstrip())
    return sections


def render(kind: str, source_target: Path, results: list[tuple[Path, list[str]]]) -> str:
    title = TITLE_FOR_KIND.get(kind, kind.title())
    lines = [f"# {title}", ""]
    # 휘발성 메타(추출일자 · 대상 워크트리명) 제거 — 브랜치마다 달라져 머지 충돌을 내던 줄.
    # 머리의 자동 추출 서명이 덮어쓰기 가드의 앵커이자 "초안" 이라는 표시다 — 같은 말을
    # 인용구로 한 번 더 쓰지 않는다.
    lines.append("_자동 추출 (`ai-ready:apply`) — 재추출 시 전체를 덮어씁니다._")
    lines.append("")
    lines.append("> 검토·정제 후 원본 문서에서 해당 섹션을 제거하고 이 파일을 참조하도록 하세요.")
    lines.append("")
    total = sum(len(s) for _, s in results)
    if total == 0:
        lines.append(f"매칭되는 섹션을 찾지 못했습니다 (키워드: {', '.join(KEYWORD_SETS[kind])}).")
        return "\n".join(lines)

    for src, sections in results:
        if not sections:
            continue
        rel = src.relative_to(source_target)
        lines.append(f"## 출처: `{rel}`")
        lines.append("")
        for s in sections:
            lines.append(s)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def collect_facts(target: Path, kind: str) -> dict:
    """문서를 쓰지 않고 매칭 섹션 사실(소스 문서·헤딩·본문)만 모아 반환.

    AI 가 이 섹션들을 보고 NAMING.md/TESTING.md 를 외과적으로 유지보수한다.
    """
    keywords = KEYWORD_SETS[kind]
    docs = find_docs(target)
    sections_out = []
    for d in docs:
        try:
            text = d.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            source = str(d.relative_to(target))
        except ValueError:
            source = str(d)
        for section in extract_matching_sections(text, keywords):
            sec_lines = section.splitlines()
            heading = sec_lines[0] if sec_lines else ""
            body = "\n".join(sec_lines[1:]).strip()
            sections_out.append({"source": source, "heading": heading, "body": body})
    return {"target": str(target), "kind": kind, "sections": sections_out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--out", help="출력 파일 경로 (--json 일 땐 불필요)")
    ap.add_argument("--kind", required=True, choices=sorted(KEYWORD_SETS.keys()))
    ap.add_argument("--json", action="store_true", dest="json_mode",
                    help="문서를 쓰지 않고 매칭 섹션 사실만 JSON 으로 출력(읽기 전용). apply 의 AI 외과 유지보수용")
    add_force_arg(ap)
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    if args.json_mode:
        print(json.dumps(collect_facts(target, args.kind), ensure_ascii=False, indent=2))
        return
    if not args.out:
        print("오류: --out 이 필요합니다 (--json 모드가 아니면).", file=sys.stderr)
        sys.exit(2)
    out_path = Path(args.out).resolve()
    if not guard_overwrite(out_path, args.force):
        sys.exit(3)
    keywords = KEYWORD_SETS[args.kind]
    docs = find_docs(target)
    results = []
    total_sections = 0
    for d in docs:
        try:
            text = d.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sections = extract_matching_sections(text, keywords)
        if sections:
            results.append((d, sections))
            total_sections += len(sections)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(args.kind, target, results), encoding="utf-8")
    print(f"{args.kind} 섹션 추출 완료: {out_path}")
    print(f"  소스 문서 {len(docs)}개에서 매칭 섹션 {total_sections}개")


if __name__ == "__main__":
    main()
