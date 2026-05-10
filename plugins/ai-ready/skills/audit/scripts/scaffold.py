#!/usr/bin/env python3
"""
Generate module-level CLAUDE.md scaffolds for the top N hot modules.

A "hot module" is one with the most recent activity (git commits in the last
90 days), with file count as a fallback. Each generated draft uses the
5-question template:
  1) What — what this module does
  2) How — typical change patterns
  3) Anti-patterns — what NEVER to do
  4) Dependencies — what this module touches
  5) Tribal knowledge — non-obvious facts

The script writes drafts to <out>/<module-path>/CLAUDE.md. You then review,
edit, and copy them into the actual module directories.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

BUILD_MANIFESTS = {
    "build.gradle.kts", "build.gradle", "pom.xml",
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
}

EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache",
}

CODE_EXTS = {
    ".kt", ".java", ".scala", ".groovy",
    ".ts", ".tsx", ".js", ".jsx", ".mjs",
    ".py", ".rs", ".go", ".rb", ".php", ".cs", ".swift",
}


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
                if rel not in seen:
                    seen.add(rel)
                    out.append(rel)
                break
    return sorted(out, key=str)


def git_changed_paths(target: Path, days: int = 90) -> list[str]:
    """최근 N일의 fix류·일반 commit에서 변경된 파일 경로 목록 반환 (raw, 미분배)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "log", f"--since={days}.days.ago", "--name-only", "--pretty=format:"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def attribute_to_modules(paths: list[str], modules: list[Path]) -> dict[str, int]:
    """H-1 fix: 각 파일을 가장 긴 일치 prefix를 갖는 모듈에 정확히 1번 귀속.

    형제 모듈끼리 commit count를 나눠 갖지 않도록 longest-prefix 매칭.
    """
    counter: dict[str, int] = {}
    # 긴 경로 먼저 매칭하도록 정렬
    sorted_modules = sorted((str(m) for m in modules if m != Path(".")),
                            key=len, reverse=True)
    for p in paths:
        for m in sorted_modules:
            if p == m or p.startswith(m + "/"):
                counter[m] = counter.get(m, 0) + 1
                break
    return counter


def file_counts_attributed(target: Path, modules: list[Path]) -> dict[str, int]:
    """H-2 fix: 각 소스 파일을 가장 긴 일치 모듈 prefix에 누적.

    `foo` 모듈의 코드가 `foo/src/main/kotlin/...` 에 있어도 `foo`로 카운트되도록.
    """
    counter: dict[str, int] = {}
    sorted_modules = sorted((str(m) for m in modules if m != Path(".")),
                            key=len, reverse=True)
    if not sorted_modules:
        return counter
    for dirpath, _, filenames in walk(target):
        rel_dir = str(dirpath.relative_to(target))
        if rel_dir == ".":
            continue
        # 이 디렉토리가 속한 모듈 찾기
        owning_module = None
        for m in sorted_modules:
            if rel_dir == m or rel_dir.startswith(m + "/"):
                owning_module = m
                break
        if not owning_module:
            continue
        n = sum(1 for f in filenames if Path(f).suffix in CODE_EXTS)
        if n:
            counter[owning_module] = counter.get(owning_module, 0) + n
    return counter


def detect_stack_hint(module_dir: Path) -> str:
    """Return a short label describing the language/framework for this module."""
    files = list(module_dir.iterdir()) if module_dir.is_dir() else []
    names = {f.name for f in files}
    if "build.gradle.kts" in names or "build.gradle" in names:
        # Spring Boot? check for application.yml or src/main/kotlin
        if (module_dir / "src" / "main" / "kotlin").is_dir():
            return "Kotlin / Gradle"
        if (module_dir / "src" / "main" / "java").is_dir():
            return "Java / Gradle"
        return "JVM / Gradle"
    if "pom.xml" in names:
        return "Java / Maven"
    if "package.json" in names:
        # Detect framework
        try:
            pkg = (module_dir / "package.json").read_text(encoding="utf-8", errors="replace")
            if "next" in pkg:
                return "Next.js"
            if "react" in pkg:
                return "React"
            if "express" in pkg or "fastify" in pkg:
                return "Node.js (server)"
            return "Node.js"
        except OSError:
            return "Node.js"
    if "Cargo.toml" in names:
        return "Rust"
    if "go.mod" in names:
        return "Go"
    if "pyproject.toml" in names or "setup.py" in names:
        return "Python"
    return "unknown"


def detect_layered_pattern(module_dir: Path) -> list[str]:
    """H-3 fix: 와일드카드 매칭으로 일반적인 아키텍처 패턴 마커 탐지.

    `Controller.kt`(정확 매칭)이 아닌 `*Controller.kt`(suffix 매칭) 사용.
    """
    hints = []
    # (rglob 패턴, 라벨)
    file_patterns = [
        ("*Controller.kt", "Controller (Kotlin)"),
        ("*Controller.java", "Controller (Java)"),
        ("*Service.kt", "Service (Kotlin)"),
        ("*Service.java", "Service (Java)"),
        ("*Repository.kt", "Repository (Kotlin)"),
        ("*UseCase.kt", "UseCase / Executor"),
        ("*Executor.kt", "Executor (오케스트레이션)"),
        ("*Entity.kt", "JPA Entity"),
    ]
    for pattern, label in file_patterns:
        try:
            if next(module_dir.rglob(pattern), None) is not None:
                if label not in hints:
                    hints.append(label)
        except OSError:
            continue

    # 디렉토리 마커 — `module_dir/api`, `module_dir/domain` 처럼 직속 자식만
    dir_markers = [
        ("api", "api/ 서브 모듈"),
        ("domain", "domain/ 서브 모듈"),
        ("infrastructure", "infrastructure/ 서브 모듈"),
        ("controller", "controller/ 디렉토리"),
    ]
    for marker, label in dir_markers:
        if (module_dir / marker).is_dir() or (module_dir / "src" / "main" / "kotlin" / marker).is_dir():
            if label not in hints:
                hints.append(label)
    return hints


def list_dependencies(module_dir: Path) -> list[str]:
    """Best-effort extraction of dependencies from build files."""
    deps = []
    gradle = module_dir / "build.gradle.kts"
    if not gradle.exists():
        gradle = module_dir / "build.gradle"
    if gradle.exists():
        try:
            text = gradle.read_text(encoding="utf-8", errors="replace")
            # Match project(":foo") references for inter-module dependencies
            for m in re.finditer(r'project\(["\']:([\w\-:]+)["\']\)', text):
                dep = m.group(1).replace(":", "/")
                if dep not in deps:
                    deps.append(dep)
        except OSError:
            pass
    pkg = module_dir / "package.json"
    if pkg.exists():
        try:
            import json
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            for key in ("dependencies", "devDependencies"):
                for dep_name in (data.get(key) or {}):
                    if dep_name.startswith("@") and "/" in dep_name:
                        # likely internal scope
                        if dep_name not in deps:
                            deps.append(dep_name)
        except (ValueError, OSError):
            pass
    return deps


# --- Auto-fill helpers (T-10) ---------------------------------------------

def module_summary_from_root_claude_md(target: Path, module_path: str) -> str | None:
    """루트 CLAUDE.md 의 module map 줄에서 모듈 1줄 설명을 cherry-pick.

    매칭: `[`mod`](path)` 또는 `` `mod` `` 다음에 ' — ', ' - ', ': ' 로 이어지는 줄.
    """
    root = target / "CLAUDE.md"
    if not root.exists():
        return None
    try:
        text = root.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    escaped = re.escape(module_path)
    # 형태: `[`module`](path)` — 설명  /  `[module](path)` — 설명  /  `module` — 설명
    patterns = [
        rf"\[`{escaped}`\]\([^)]*\)\s*[—\-:]\s*(.+?)(?:\n|$)",
        rf"\[{escaped}\]\([^)]*\)\s*[—\-:]\s*(.+?)(?:\n|$)",
        rf"`{escaped}`\s*[—\-:]\s*(.+?)(?:\n|$)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            summary = m.group(1).strip()
            # trailing 마크다운 강조/링크 제거
            summary = re.sub(r"\s*\(\[?[^\)]*\)\s*$", "", summary)
            return summary[:200]
    return None


def git_hot_files(target: Path, module_path: str, days: int = 90, top: int = 5) -> list[tuple[str, int]]:
    """모듈 내 최근 N일 변경 빈도 Top K 파일."""
    if module_path == ".":
        return []
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "log", f"--since={days}.days.ago",
             "--name-only", "--pretty=format:", "--", module_path],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    counts = Counter(line.strip() for line in result.stdout.splitlines() if line.strip())
    return counts.most_common(top)


_FIX_RE = re.compile(
    r"^(fix|hotfix|revert|bugfix|chore\(fix\)|버그|핫픽스|롤백|되돌림)[\(\s:]",
    re.IGNORECASE,
)


def git_fix_subjects(target: Path, module_path: str, days: int = 180, top: int = 5) -> list[str]:
    """모듈 내 최근 fix/hotfix/revert 커밋 subject Top K — 안티패턴 후보 시드."""
    if module_path == ".":
        return []
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "log", f"--since={days}.days.ago",
             "--pretty=format:%s", "--", module_path],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    subjects = []
    for s in result.stdout.splitlines():
        s = s.strip()
        if s and _FIX_RE.match(s):
            subjects.append(s)
        if len(subjects) >= top:
            break
    return subjects


# --- Template -------------------------------------------------------------

TEMPLATE = """# CLAUDE.md — `{module_path}`

> AI 에이전트를 위한 모듈 가이드. 50줄 이내로 유지하세요.
> **TODO**로 표시된 곳은 사람이 채워야 하는 자리표시자입니다.

## 스택
- {stack_hint}

## 이 모듈이 하는 일
{what_block}

## 일반적인 변경 방법
{how_block}

## 절대 금지 (이 모듈 고유 안티패턴)
{antipattern_block}

## 의존성
{deps_block}

## 핫 파일 (최근 90일 변경 빈도 Top 5)
{hot_files_block}

## 암묵지 (코드에 드러나지 않는 것)
- TODO: 팀이 암묵적으로 따르지만 코드엔 없는 규칙 하나.
- TODO: AI가 자주 놓치는 필드/값 네이밍 불일치.
- TODO: 알아둘 가치가 있는 과거 의사결정 (ADR이 있으면 링크).

## 최종 검토일
- {today} (자동 생성 초안 — 사람 검토 필요)
"""


def render_what_block(module_path: str, stack_hint: str, file_count: int, summary: str | None) -> str:
    """T-10: 루트 CLAUDE.md 의 module map 1줄 설명을 자동으로 cherry-pick."""
    head = f"- {summary}" if summary else f"- TODO: `{module_path}` 의 책임을 한 문장으로 적으세요."
    return f"{head}\n- {stack_hint} 소스 파일 {file_count}개."


def render_how_block(layer_hints: list[str]) -> str:
    if not layer_hints:
        return "- TODO: 이 모듈에 새 기능을 추가할 때의 일반적인 흐름을 적으세요.\n- TODO: 요청이 어디로 들어와서 어디로 나가는지 적으세요."
    out = ["- 감지된 레이어 / 패턴:"]
    for h in layer_hints:
        out.append(f"  - {h}")
    out.append("- TODO: 진입 → 서비스 → 출구의 일반적인 end-to-end 흐름을 적으세요.")
    return "\n".join(out)


def render_deps_block(deps: list[str]) -> str:
    if not deps:
        return "- TODO: 이 모듈이 의존하는 내부 모듈을 적으세요 (또는 'leaf 모듈 — 의존 없음')."
    out = []
    for d in deps[:8]:
        out.append(f"- `{d}`")
    if len(deps) > 8:
        out.append(f"- … 외 {len(deps) - 8}개 (빌드 파일 참조)")
    return "\n".join(out)


def render_antipattern_block(fix_subjects: list[str]) -> str:
    """T-10: 모듈 내 fix 커밋 subject 를 안티패턴 후보로 시드."""
    if not fix_subjects:
        return ("- TODO: 합리적으로 보이지만 이 모듈을 깨뜨리는 것 3~5개를 적으세요.\n"
                "- TODO: AI가 가장 최근에 했던 실수와 그것이 왜 잘못인지 한 줄로 적으세요.")
    out = ["> 최근 fix/revert 커밋 (안티패턴 후보 — 검토 후 절대 금지 항목으로 승격):"]
    for s in fix_subjects[:5]:
        # 길이 제한
        snippet = s[:140].replace("\n", " ").replace("|", "│")
        out.append(f"- `{snippet}`")
    out.append("- TODO: 위 fix 커밋 패턴을 보고 '절대 금지 — X. 이유 — Y. 대신 — Z' 형식으로 정리하세요.")
    return "\n".join(out)


def render_hot_files_block(hot_files: list[tuple[str, int]]) -> str:
    """T-10: git log 기반 핫 파일 Top 5."""
    if not hot_files:
        return "- _최근 90일간 git 변경 없음 (또는 git 미사용 모듈)._"
    out = []
    for path, n in hot_files:
        out.append(f"- `{path}` — {n}회 변경")
    return "\n".join(out)


# --- Main -----------------------------------------------------------------

def select_top_modules(target: Path, modules: list[Path], top_n: int) -> list[Path]:
    """H-1/H-2 fix: longest-prefix 매칭으로 commit·file count를 정확히 모듈에 귀속."""
    paths = git_changed_paths(target)
    commit_counts = attribute_to_modules(paths, modules)
    file_counts = file_counts_attributed(target, modules)
    scored = []
    for m in modules:
        if m == Path("."):
            continue
        key = str(m)
        commit_score = commit_counts.get(key, 0)
        file_score = file_counts.get(key, 0)
        # composite: 핫 모듈을 보상하기 위해 commit 가중치 3배
        scored.append((commit_score * 3 + file_score, commit_score, file_score, m))
    scored.sort(reverse=True)
    return [m for _, _, _, m in scored[:top_n]]


def run(target: Path, out_dir: Path, top_n: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    modules = find_modules(target)
    if not modules:
        print("모듈 미감지 (빌드 매니페스트 없음)", file=sys.stderr)
        return
    selected = select_top_modules(target, modules, top_n)
    today = datetime.now().strftime("%Y-%m-%d")
    written = []
    for m in selected:
        module_dir = target / m
        # 실제 모듈 디렉토리에 CLAUDE.md가 이미 있으면 스킵 (큐레이션된 내용을 덮어쓰지 않음)
        existing = module_dir / "CLAUDE.md"
        if existing.exists():
            print(f"스킵: {m} (CLAUDE.md가 이미 존재)", file=sys.stderr)
            continue
        stack = detect_stack_hint(module_dir)
        layers = detect_layered_pattern(module_dir)
        deps = list_dependencies(module_dir)
        file_count = sum(1 for p in module_dir.rglob("*")
                         if p.is_file() and p.suffix in CODE_EXTS
                         and not any(part in EXCLUDE_DIRS for part in p.parts))
        # T-10: 루트 CLAUDE.md / git history 에서 자동 채움
        summary = module_summary_from_root_claude_md(target, str(m))
        hot_files = git_hot_files(target, str(m))
        fix_subjects = git_fix_subjects(target, str(m))
        content = TEMPLATE.format(
            module_path=str(m),
            stack_hint=stack,
            what_block=render_what_block(str(m), stack, file_count, summary),
            how_block=render_how_block(layers),
            antipattern_block=render_antipattern_block(fix_subjects),
            deps_block=render_deps_block(deps),
            hot_files_block=render_hot_files_block(hot_files),
            today=today,
        )
        out_path = out_dir / m / "CLAUDE.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        written.append(out_path)
    print(f"모듈 CLAUDE.md 초안 {len(written)}개 생성: {out_dir}")
    for p in written:
        print(f"  - {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--out", required=True, help="초안 출력 디렉토리 (예: .ai-ready/scaffolds)")
    ap.add_argument("--top", type=int, default=5, help="스캐폴드할 핫 모듈 개수")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    out_dir = Path(args.out).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    run(target, out_dir, args.top)


if __name__ == "__main__":
    main()
