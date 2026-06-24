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

확장 동작 (v0.2.0+):
  대상에 `.ai-ready/config.json` 이 존재하면 *config-driven 그룹화* 활성화 —
  frontmatter 의 `feature` / `aliases` / `tags` / `supersedes` 같은 필드를 스캔해
  feature 그룹 / 한영 cross-reference / 결정 진화 그래프 섹션을 추가로 빌드합니다.
  config 가 없으면 기존 동작 (claude / guides / docs-decisions / docs-other 카테고리) 그대로.

실행:
  python3 gen_index.py --target /path/to/repo --out /path/to/repo/docs/INDEX.md
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 동일 디렉토리의 두 모듈 import — ai-ready 의 standard layout
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from frontmatter_parser import parse_frontmatter  # noqa: E402
from managed_doc import guard_overwrite, add_force_arg  # noqa: E402
from config_loader import (  # noqa: E402
    load_config,
    index_groups,
    cross_reference_config,
    evolution_graph_config,
    frontmatter_section,
)

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
    # git worktree 체크아웃 — repo 전체 복사본이라 docs/모듈 문서가 통째로 중복 수집돼
    # INDEX 를 폭발시킨다 (Claude Code 는 .claude/worktrees/ 에 워크트리를 만든다).
    # basename 매칭이라 worktree 표준 위치를 안전하게 제외한다.
    "worktrees",
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
        # 마크다운 링크는 표시 텍스트만 남긴다 — 요약 줄에 들어간 `[NAMING.md](NAMING.md)`
        # 같은 상대 링크가 INDEX 에 그대로 박히면 (INDEX 위치 기준으로 해석돼) 깨진 링크가 된다.
        cleaned = _re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cleaned).strip()
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
    """카테고리별로 문서를 수집해 dict 로 반환 (legacy — config 없을 때 사용).

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


def collect_with_meta(target: Path) -> list[dict]:
    """모든 .md 파일을 frontmatter + summary + 경로와 함께 수집 (config-driven 동작용)."""
    docs: list[dict] = []
    for dirpath, _, filenames in walk(target):
        for f in filenames:
            if not f.endswith(".md"):
                continue
            full = dirpath / f
            try:
                rel = full.relative_to(target)
            except ValueError:
                continue
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = parse_frontmatter(text)
            summary = extract_summary(full)
            docs.append({
                "path": rel,
                "frontmatter": fm,
                "summary": summary,
            })
    return sorted(docs, key=lambda d: str(d["path"]))


def _matches_group(rel_path: Path, group: dict) -> bool:
    """문서 경로가 group.match 룰에 매치되는지 검사."""
    match = group.get("match", {}) or {}
    rel_str = str(rel_path).replace(os.sep, "/")
    prefix = match.get("path_prefix")
    if prefix:
        prefix_norm = prefix.rstrip("/") + "/"
        if not rel_str.startswith(prefix_norm):
            return False
    excluding = match.get("excluding", []) or []
    for exc in excluding:
        exc_norm = exc.rstrip("/") + "/"
        if rel_str.startswith(exc_norm):
            return False
    return True


def render(target: Path, collected: dict[str, list[tuple[Path, str]]]) -> str:
    """Legacy 렌더링 — config 없을 때."""
    claude = collected["claude"]
    guides = collected["guides"]
    docs_dir = collected["docs"]
    total = len(claude) + len(guides) + len(docs_dir)

    lines = []
    lines.append("# 문서 인덱스")
    lines.append("")
    # 휘발성 메타(생성일자 · 대상 워크트리명 · 문서 개수)를 헤더에 넣지 않는다 — 브랜치마다
    # 달라져 머지 충돌을 보장하던 줄. 내용이 같으면 재생성 결과도 동일하도록 안정 헤더만 둔다.
    lines.append("_자동 생성 (`ai-ready:apply`) — 재생성 시 전체를 덮어씁니다._")
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


def render_with_config(target: Path, cfg: dict, all_docs: list[dict]) -> str:
    """Config-driven 렌더링 — frontmatter 기반 그룹화 + 한영 cross-reference + 결정 진화 그래프."""
    total = len(all_docs)

    lines: list[str] = []
    lines.append("# 문서 인덱스")
    lines.append("")
    # 휘발성 메타(생성일자 · 대상 워크트리명 · 문서 개수)를 헤더에 넣지 않는다 — 브랜치마다
    # 달라져 머지 충돌을 보장하던 줄. 내용이 같으면 재생성 결과도 동일하도록 안정 헤더만 둔다.
    lines.append("_자동 생성 (`ai-ready:apply`, config v1) — 재생성 시 전체를 덮어씁니다._")
    lines.append("")

    if total == 0:
        lines.append("스캔된 문서가 없습니다.")
        return "\n".join(lines)

    # 1. config groups 룰로 분류
    grouped_paths: set[str] = set()
    for group in index_groups(cfg):
        matched = [d for d in all_docs if _matches_group(d["path"], group)]
        if not matched:
            continue
        title = group.get("title") or group.get("id") or "(이름 없음)"
        lines.append(f"## {title}")
        lines.append("")
        sub_key = group.get("sub_group_by")
        if sub_key:
            sub_groups: dict[str, list[dict]] = {}
            for d in matched:
                sub_value = d["frontmatter"].get(sub_key)
                if isinstance(sub_value, list):
                    # list 값이면 각 원소를 별도 그룹에 등장시킴
                    if not sub_value:
                        sub_groups.setdefault("(미분류)", []).append(d)
                    else:
                        for v in sub_value:
                            sub_groups.setdefault(str(v), []).append(d)
                elif isinstance(sub_value, str) and "," in sub_value:
                    # 콤마 구분 스칼라("feed, inspiration, member")도 YAML 리스트처럼 분리해
                    # 각 값을 별도 sub-group 에 등장시킨다. 안 그러면 통째로 한 섹션명이 돼
                    # `### feed, inspiration, member` 같은 깨진 그룹이 생긴다.
                    for v in (x.strip() for x in sub_value.split(",")):
                        if v:
                            sub_groups.setdefault(v, []).append(d)
                else:
                    sub_groups.setdefault(str(sub_value) if sub_value else "(미분류)", []).append(d)
            for sub_name in sorted(sub_groups.keys()):
                lines.append(f"### {sub_name}")
                lines.append("")
                for d in sorted(sub_groups[sub_name], key=lambda x: str(x["path"])):
                    lines.append(f"- [`{d['path']}`]({d['path']}) — {d['summary']}")
                    grouped_paths.add(str(d["path"]))
                lines.append("")
        else:
            for d in sorted(matched, key=lambda x: str(x["path"])):
                lines.append(f"- [`{d['path']}`]({d['path']}) — {d['summary']}")
                grouped_paths.add(str(d["path"]))
            lines.append("")

    # 2. config groups 에 매치 안 된 나머지 — 기존 카테고리 보존
    remaining = [d for d in all_docs if str(d["path"]) not in grouped_paths]
    if remaining:
        # 루트/모듈 CLAUDE.md
        claude_docs = [d for d in remaining if d["path"].name in DOC_NAMES]
        guide_docs = [
            d for d in remaining
            if d["path"].parent == Path(".") and d["path"].name in ROOT_GUIDE_NAMES
        ]
        other_docs = [
            d for d in remaining
            if d not in claude_docs and d not in guide_docs
        ]
        root_claude = [d for d in claude_docs if d["path"].parent == Path(".")]
        module_claude = [d for d in claude_docs if d["path"].parent != Path(".")]

        if root_claude or guide_docs:
            lines.append("## 루트 가이드")
            lines.append("")
            for d in sorted(root_claude, key=lambda x: str(x["path"])):
                lines.append(f"- [`{d['path']}`]({d['path']}) — {d['summary']}")
            for d in sorted(guide_docs, key=lambda x: str(x["path"])):
                lines.append(f"- [`{d['path']}`]({d['path']}) — {d['summary']}")
            lines.append("")
        if module_claude:
            lines.append("## 모듈 CLAUDE.md")
            lines.append("")
            for d in sorted(module_claude, key=lambda x: str(x["path"])):
                lines.append(f"- [`{d['path']}`]({d['path']}) — {d['summary']}")
            lines.append("")
        if other_docs:
            lines.append("## 기타 문서")
            lines.append("")
            for d in sorted(other_docs, key=lambda x: str(x["path"])):
                lines.append(f"- [`{d['path']}`]({d['path']}) — {d['summary']}")
            lines.append("")

    # 3. cross_reference 섹션 (frontmatter 의 aliases / tags 등 search 필드 역 인덱스)
    cr = cross_reference_config(cfg)
    if cr.get("enabled"):
        search_fields = frontmatter_section(cfg).get("search", ["aliases", "tags"])
        index_map: dict[str, list[Path]] = {}
        for d in all_docs:
            fm = d["frontmatter"]
            for field in search_fields:
                values = fm.get(field, [])
                if isinstance(values, str):
                    # 콤마 구분 스칼라("북마크, bookmark")도 다중 검색어로 분리 — frontmatter_parser
                    # 가 리스트로 보지 않은 경우에도 한영 인덱스에서 통째 누락되지 않도록.
                    values = [x.strip() for x in values.split(",") if x.strip()]
                if not isinstance(values, list):
                    continue
                for term in values:
                    if term is None or term == "":
                        continue
                    index_map.setdefault(str(term), []).append(d["path"])
        if index_map:
            title = cr.get("title", "한영 검색 인덱스")
            lines.append(f"## {title}")
            lines.append("")
            lines.append("_frontmatter 의 aliases / tags 역 인덱스 — 한국어 / 영어 자연어 query 매칭_")
            lines.append("")
            for term in sorted(index_map.keys()):
                paths = sorted(set(str(p) for p in index_map[term]))
                links = " · ".join(f"[`{p}`]({p})" for p in paths)
                lines.append(f"- **{term}** → {links}")
            lines.append("")

    # 4. evolution_graph 섹션 (supersedes / superseded-by)
    eg = evolution_graph_config(cfg)
    if eg.get("enabled"):
        evolution_fields = frontmatter_section(cfg).get("evolution", ["supersedes", "superseded-by"])
        scope_type = eg.get("scope")
        scope_docs = (
            [d for d in all_docs if d["frontmatter"].get("type") == scope_type]
            if scope_type
            else all_docs
        )
        edges: list[tuple[Path, int]] = []
        for d in scope_docs:
            sup = d["frontmatter"].get("supersedes", [])
            if not isinstance(sup, list):
                continue
            for old in sup:
                if isinstance(old, int):
                    edges.append((d["path"], old))
        if edges:
            title = eg.get("title", "결정 진화")
            lines.append(f"## {title}")
            lines.append("")
            lines.append("_ADR 의 `supersedes` / `superseded-by` 추적 — 옛 결정 → 새 결정의 영향 관계_")
            lines.append("")
            for new_path, old_num in sorted(edges, key=lambda x: (str(x[0]), x[1])):
                lines.append(f"- [`{new_path}`]({new_path}) → ADR-{old_num:04d}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_재생성: Claude Code 에서 `ai-ready:apply` 스킬을 호출하거나 \"INDEX 재생성해줘\" 라고 말하세요._")
    return "\n".join(lines)


def ensure_gitattributes_union(target: Path, out_path: Path) -> bool:
    """`<target>/.gitattributes` 에 INDEX 파일의 `merge=union` 룰을 idempotent 하게 보장.

    INDEX.md 는 전체 재생성되는 집계 산출물이라 브랜치마다 항목이 추가되면 같은 영역에서
    머지 충돌이 난다. union 머지 드라이버를 걸면 git 이 양쪽 추가분을 자동 합쳐 충돌을 없앤다
    (드물게 생기는 중복 항목은 다음 재생성이 정리). 헤더의 휘발성 메타 제거와 한 쌍으로 동작.

    target 이 git 저장소가 아니어도 .gitattributes 자체는 무해하므로 항상 보장한다.
    이미 룰이 있으면 건드리지 않는다. 추가했으면 True 반환.
    """
    try:
        rel = out_path.relative_to(target)
    except ValueError:
        rel = Path(out_path.name)
    rel_str = str(rel).replace(os.sep, "/")
    rule = f"{rel_str} merge=union"
    ga = target / ".gitattributes"
    existing = ""
    if ga.exists():
        try:
            existing = ga.read_text(encoding="utf-8")
        except OSError:
            return False
    # 이미 해당 경로에 대한 룰이 있으면 추가하지 않음 (룰 종류 무관 — 사용자 설정 존중)
    for line in existing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.split()[0] == rel_str:
            return False
    block = "" if existing == "" or existing.endswith("\n") else "\n"
    block += (
        "# ai-ready: 집계 산출물 — 브랜치 간 머지 충돌 방지 (양쪽 추가분 자동 union)\n"
        f"{rule}\n"
    )
    try:
        with ga.open("a", encoding="utf-8") as fh:
            fh.write(block)
    except OSError:
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="대상 코드베이스 경로")
    ap.add_argument("--out", required=True, help="INDEX.md 출력 경로")
    add_force_arg(ap)
    args = ap.parse_args()
    target = Path(args.target).resolve()
    out_path = Path(args.out).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    if not guard_overwrite(out_path, args.force):
        sys.exit(3)

    cfg = load_config(target)

    if cfg is None:
        # Legacy path — config 없으면 기존 동작 유지
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
        added_ga = ensure_gitattributes_union(target, out_path)
        total = sum(len(v) for v in collected.values())
        print(f"인덱스 생성: {out_path}")
        print(f"  대상 문서: claude={len(collected['claude'])}, guides={len(collected['guides'])}, docs={len(collected['docs'])} (총 {total}개)")
        if added_ga:
            print("  .gitattributes: docs INDEX merge=union 룰 추가 (머지 충돌 방지)")
    else:
        # Config-driven path — frontmatter 기반 그룹화
        all_docs = collect_with_meta(target)
        # 자기 자신은 인덱스에서 제외
        try:
            out_rel = out_path.relative_to(target)
            all_docs = [d for d in all_docs if d["path"] != out_rel]
        except ValueError:
            pass
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_with_config(target, cfg, all_docs), encoding="utf-8")
        added_ga = ensure_gitattributes_union(target, out_path)
        n_groups = len(index_groups(cfg))
        print(f"인덱스 생성: {out_path} (config v1, {n_groups}개 그룹 룰 적용)")
        print(f"  대상 문서: {len(all_docs)}개")
        if added_ga:
            print("  .gitattributes: docs INDEX merge=union 룰 추가 (머지 충돌 방지)")


if __name__ == "__main__":
    main()
