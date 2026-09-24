#!/usr/bin/env python3
# ai-ready:apply 자동 생성 — 고치면 이 줄을 남겨 둬도 ai-ready 가 덮어쓰지 않는다. 다시 만들려면 파일을 지우고 apply 를 돌린다.
"""문서 정합 검사. 표준 라이브러리만 쓴다.

검사하는 것:
  - 오류: 깨진 상대 링크 (`[글](경로)`, `![그림](경로)`, `[이름]: 경로`)
  - 오류: 결정 카드 제목 형식 (`docs/design/*.decisions.md` 의 `## ` 줄)
          `## 제목 · (티켓) · [accepted|proposed|rejected|superseded]`  — 티켓이 없으면 `(-)`
  - 오류: 같은 결정 카드가 두 번 (union merge 로 양쪽 줄이 모두 남은 경우. 라벨만 다른 것도 포함)
  - 오류: frontmatter 가 열리고 닫히지 않음, 또는 REQUIRED_FRONTMATTER 가 요구한 키가 없음
  - 경고: `{domain}.decisions.md` 는 있는데 `{domain}.md` 가 없음 (또는 그 반대)

오류가 하나라도 있으면 exit 1, 경고만 있으면 stderr 에 적고 exit 0.

CI 에 넣을 때:  python3 scripts/check_docs.py
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

# 파일 경로 glob(저장소 루트 기준) → 반드시 있어야 하는 frontmatter 키.
# 예: {"docs/design/*.md": ("owner", "status")}. --frontmatter 인자로도 더할 수 있다.
REQUIRED_FRONTMATTER: dict[str, tuple[str, ...]] = {}

EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea", "out", "coverage",
    "__pycache__", ".venv", "venv", "vendor", ".next", ".turbo", ".mypy_cache", ".pytest_cache",
    ".tox", "worktrees", ".ai-ready",
}

CARD_HEADER = re.compile(
    r"^## (?P<title>\S.*?) · \((?P<ticket>[^()]+)\) · \[(?P<status>accepted|proposed|rejected|superseded)\]$")
_INLINE_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_INLINE_CODE = re.compile(r"`+[^`]*`+")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def md_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for f in sorted(filenames):
            if f.endswith(".md"):
                yield Path(dirpath) / f


def _rel(root: Path, p: Path) -> str:
    return str(p.relative_to(root))


def _outside_fences(text: str):
    """(줄 번호, 줄) — 코드 블록 안과 펜스 줄은 뺀다. 여는 펜스와 같은 문자로, 그 길이 이상일 때만 닫힌다
    (`~~~` 블록 안의 ``` 줄은 본문이다)."""
    fence = ""
    for no, line in enumerate(text.splitlines(), 1):
        m = _FENCE.match(line)
        if not fence:
            if m:
                fence = m.group(1)
            else:
                yield no, line
        elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
            fence = ""


def _link_targets(text: str):
    """(줄 번호, 링크 대상). 코드 블록·인라인 코드 안은 뺀다."""
    for no, line in _outside_fences(text):
        m = _REF_DEF.match(line)
        if m:
            yield no, m.group(1)
            continue
        for m in _INLINE_LINK.finditer(_INLINE_CODE.sub("", line)):
            yield no, m.group(1)


def check_links(root: Path, path: Path, text: str) -> list[str]:
    errors = []
    for no, raw in _link_targets(text):
        target = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
        if not target or target.startswith("#") or _SCHEME.match(target) or target.startswith("//"):
            continue
        target = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not target:
            continue
        resolved = (root / target.lstrip("/")) if target.startswith("/") else (path.parent / target)
        if not resolved.exists():
            errors.append(f"{_rel(root, path)}:{no}: 깨진 링크 → {raw}")
    return errors


def check_cards(root: Path, path: Path, text: str) -> list[str]:
    errors = []
    seen_line: dict[str, int] = {}
    seen_card: dict[tuple[str, str], tuple[int, str]] = {}
    for no, line in _outside_fences(text):
        if not line.startswith("## "):
            continue
        where = f"{_rel(root, path)}:{no}"
        line = line.rstrip()
        m = CARD_HEADER.match(line)
        if not m:
            errors.append(f"{where}: 결정 카드 제목 형식이 아니다 — "
                          f"`## 제목 · (티켓) · [accepted|proposed|rejected|superseded]`: {line}")
            continue
        if line in seen_line:
            errors.append(f"{where}: 같은 카드 제목이 {seen_line[line]}번 줄에도 있다 (union merge 중복): {line}")
            continue
        seen_line[line] = no
        key = (m.group("title"), m.group("ticket"))
        if key in seen_card:
            first_no, first_status = seen_card[key]
            errors.append(f"{where}: 같은 카드가 {first_no}번 줄에 [{first_status}] 로도 있다 "
                          f"(라벨만 다르다 — 한 줄만 남긴다): {line}")
            continue
        seen_card[key] = (no, m.group("status"))
    return errors


def _frontmatter(text: str) -> tuple[dict[str, str] | None, bool]:
    """(키 사전, 형식 오류 여부). frontmatter 가 없으면 (None, False)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, False
    keys: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return keys, False
        if line[:1].isspace() or ":" not in line:
            continue
        k, v = line.split(":", 1)
        keys[k.strip()] = v.strip()
    return None, True


def check_frontmatter(root: Path, path: Path, text: str, required: dict[str, tuple[str, ...]]) -> list[str]:
    rel = _rel(root, path)
    keys, broken = _frontmatter(text)
    if broken:
        return [f"{rel}:1: frontmatter 가 `---` 로 닫히지 않는다"]
    need = [k for pattern, ks in required.items() if fnmatch.fnmatch(rel, pattern) for k in ks]
    if not need:
        return []
    if keys is None:
        return [f"{rel}:1: frontmatter 가 없다 — 필요한 키: {', '.join(need)}"]
    missing = [k for k in need if not keys.get(k)]
    return [f"{rel}:1: frontmatter 키 없음: {', '.join(missing)}"] if missing else []


def design_pair_warnings(root: Path) -> list[str]:
    design = root / "docs" / "design"
    if not design.is_dir():
        return []
    names = {p.name for p in design.glob("*.md")}
    warnings = []
    for n in sorted(names):
        if n.endswith(".decisions.md"):
            if n[: -len(".decisions.md")] + ".md" not in names:
                warnings.append(f"docs/design/{n}: 짝이 되는 현재 동작 문서 {n[:-len('.decisions.md')]}.md 가 없다")
        elif n != "README.md" and n[: -len(".md")] + ".decisions.md" not in names:
            warnings.append(f"docs/design/{n}: 결정 카드 파일 {n[:-len('.md')]}.decisions.md 가 없다")
    return warnings


def run(root: Path, required: dict[str, tuple[str, ...]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    for path in md_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"{_rel(root, path)}: 읽지 못했다 ({e})")
            continue
        errors += check_links(root, path, text)
        errors += check_frontmatter(root, path, text, required)
        rel = _rel(root, path)
        if fnmatch.fnmatch(rel, "docs/design/*.decisions.md"):
            errors += check_cards(root, path, text)
    return errors, design_pair_warnings(root)


def _parse_required(items: list[str]) -> dict[str, tuple[str, ...]]:
    out = dict(REQUIRED_FRONTMATTER)
    for item in items:
        pattern, _, keys = item.partition("=")
        if not pattern or not keys:
            raise SystemExit(f"--frontmatter 형식은 GLOB=키1,키2 다: {item}")
        out[pattern] = tuple(k.strip() for k in keys.split(",") if k.strip())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="문서 정합 검사 (링크·결정 카드·frontmatter)")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent),
                    help="저장소 루트 (기본: 이 스크립트의 한 단계 위)")
    ap.add_argument("--frontmatter", action="append", default=[], metavar="GLOB=키1,키2",
                    help="이 glob 에 맞는 문서가 가져야 할 frontmatter 키")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    errors, warnings = run(root, _parse_required(args.frontmatter))
    for w in warnings:
        print(f"경고: {w}", file=sys.stderr)
    for e in errors:
        print(f"오류: {e}", file=sys.stderr)
    if errors:
        print(f"check_docs: 오류 {len(errors)}건", file=sys.stderr)
        return 1
    print(f"check_docs: 통과 (경고 {len(warnings)}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
