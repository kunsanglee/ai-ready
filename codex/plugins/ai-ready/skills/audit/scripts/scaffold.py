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

# 논리 모듈 기준점은 스택마다 다르다. 그 답을 여기 두지 않고 어댑터에 묻는다 — 종전에는
# 이 파일과 audit.py 가 각자 JVM 으로만 하드코딩해 두 벌로 갈라져 있었다.
import stacks

BUILD_MANIFESTS = {
    "build.gradle.kts", "build.gradle", "pom.xml",
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
}

EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache",
    "worktrees",  # git worktree(.claude/worktrees) = repo 전체 복사본 — 통째 중복 수집 방지
    ".ai-ready",  # 자기 산출물 자기참조 차단
}

CODE_EXTS = {
    ".kt", ".java", ".scala", ".groovy",
    ".ts", ".tsx", ".js", ".jsx", ".mjs",
    ".py", ".rs", ".go", ".rb", ".php", ".cs", ".swift",
}

# 단일 모듈 프로젝트의 패키지(=논리 모듈) 탐색 기준점은 stacks.py 의 어댑터가 답한다.

# 종료코드. 0 이 아닌 값을 쓰는 이유는 "안 만들어졌다" 를 호출한 쪽이 셀 수 있게 하기
# 위해서다. 안내문은 사람만 읽고 스크립트는 못 읽는다.
EXIT_OK = 0
EXIT_NO_ADAPTER = 3    # 등록된 스택 어댑터 중 맞는 것이 없다
EXIT_NO_PACKAGES = 4   # 기준점은 찾았는데 그 아래에 코드가 없다


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
    except (OSError, subprocess.SubprocessError):
        # OSError = FileNotFoundError(git 부재) + PermissionError 등, SubprocessError = TimeoutExpired 등.
        # extract_antipatterns / gen_index 의 git 래퍼와 동일 폭(PermissionError 미처리 크래시 차단).
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
    except (OSError, subprocess.SubprocessError):
        # OSError = FileNotFoundError(git 부재) + PermissionError 등, SubprocessError = TimeoutExpired 등.
        # extract_antipatterns / gen_index 의 git 래퍼와 동일 폭(PermissionError 미처리 크래시 차단).
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
    except (OSError, subprocess.SubprocessError):
        # OSError = FileNotFoundError(git 부재) + PermissionError 등, SubprocessError = TimeoutExpired 등.
        # extract_antipatterns / gen_index 의 git 래퍼와 동일 폭(PermissionError 미처리 크래시 차단).
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
{design_pointer_block}
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


def render_design_pointer_block(target: Path, module_path: str) -> str:
    """모듈이 속한 도메인의 living design 문서 (docs/design/domain_{name}.md) 가 있으면 포인터 한 줄.

    도메인명은 모듈 경로의 최상위 세그먼트 (casting/casting-api → casting).
    design 문서가 없으면 빈 문자열 — TODO 자리표시자를 만들지 않는다 (점진 확장 정책:
    design 문서가 생기는 도메인부터 포인터가 따라붙는다).
    """
    domain = Path(module_path).parts[0]
    rel = Path("docs/design") / f"domain_{domain}.md"
    if not (target / rel).exists():
        return ""
    depth = len(Path(module_path).parts)
    href = "../" * depth + str(rel)
    return f"- **도메인 설계 문서**: 비즈니스 룰·결정 이력은 [{rel}]({href}) 참조.\n"


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


# --- Single-module package detection -------------------------------------

def find_base_package(target: Path) -> Path | None:
    """논리 모듈의 부모 디렉토리를 찾는다. 스택별 판정은 stacks.py 가 한다.

    JVM 이면 base package(Application 클래스가 있는 디렉토리), Node 면 `src/`,
    Python 이면 배포 패키지 디렉토리가 나온다.
    """
    layout = stacks.detect_layout(target)
    return layout.source_root if layout is not None else None


def find_packages(base_package: Path) -> list[Path]:
    """base package 의 직속 자식 디렉토리 = 패키지(논리 모듈)."""
    if not base_package.is_dir():
        return []
    out = []
    for child in sorted(base_package.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if child.name in EXCLUDE_DIRS or child.name.startswith("."):
            continue
        # 코드 파일이 1개라도 있는 경우만
        has_code = any(p.suffix in CODE_EXTS for p in child.rglob("*") if p.is_file())
        if has_code:
            out.append(child)
    return out


def detect_package_role(pkg_dir: Path, stack: str = "jvm") -> str:
    """패키지 역할 추정 — Controller/Service/Repository 이름으로 도메인 / 횡단 구분.

    이름 규칙이 잡히면 어느 스택이든 그대로 쓴다. 문제는 **아무것도 안 잡혔을 때**다.
    JVM 웹 스택에서 그 셋이 없으면 실제로 횡단·설정·유틸일 확률이 높지만, 그 이름
    규칙을 애초에 안 쓰는 스택에서는 아무 정보도 없는 것이지 횡단이라는 뜻이 아니다.
    단정하면 사람이 그 라벨을 믿고 넘어가, 채워야 할 자리가 채워진 것처럼 보인다.
    """
    has_controller = next(pkg_dir.rglob("*Controller.*"), None) is not None
    has_service = next(pkg_dir.rglob("*Service.*"), None) is not None
    has_repository = next(pkg_dir.rglob("*Repository.*"), None) is not None
    if has_controller and (has_service or has_repository):
        return "도메인 (Controller + Service/Repository)"
    if has_controller:
        return "도메인 (Controller 만)"
    if has_service or has_repository:
        return "도메인 (Service/Repository — Controller 없음)"
    if stack == "jvm":
        return "횡단 / 설정 / 유틸"
    return "TODO — 이 패키지의 역할을 적으세요"


def collect_endpoints(pkg_dir: Path) -> list[str]:
    """패키지의 Controller 파일에서 @RequestMapping / @GetMapping / @PostMapping 등 추출."""
    endpoints: list[str] = []
    pattern = re.compile(r'@(?:RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\(\s*"([^"]+)"')
    try:
        for ctrl in pkg_dir.rglob("*Controller.*"):
            text = ctrl.read_text(encoding="utf-8", errors="replace")
            for m in pattern.finditer(text):
                endpoints.append(m.group(1))
    except OSError:
        pass
    return endpoints


PACKAGE_CATALOG_TEMPLATE = """# PACKAGES.md — 패키지 카탈로그

> **읽기 트리거**: 패키지 진입 / 새 도메인 추가 / 책임 경계 확인 / 트랜잭션·이벤트 흐름 파악.
>
> 단일 모듈 프로젝트의 *패키지가 곧 논리 모듈* 이다. 본 문서는 패키지 단위 CLAUDE.md 를 분산 배치하는 대신 한 곳에 모은 카탈로그.
>
> **TODO** 로 시작하는 줄은 사람이 채워야 하는 자리표시자입니다. ai-ready scaffold 가 자동 감지한 단서로 1차 채워뒀습니다.

베이스 패키지: `{base_package}` ({total} 개 패키지 감지)

---

{sections}

---

## 새 도메인 패키지 추가 시 체크리스트

1. 새 패키지 디렉토리 생성 + 표준 레이아웃 (`controller/`, `service/`, `domain/`, `repository/`).
2. 본 문서에 새 도메인 섹션 추가 + 루트 `CLAUDE.md` 의 모듈 맵 갱신.
3. TODO: 프로젝트 별 추가 체크리스트를 적으세요 (ADR / 테스트 패턴 / DDL 등).
"""

PACKAGE_SECTION_TEMPLATE = """### `{name}/` — {role}

- **목적**: TODO — 이 패키지의 책임을 1~2줄로 적으세요.
- **엔드포인트**: {endpoints}
- **흐름**: TODO — 이 패키지를 지나는 호출·이벤트의 경계를 적으세요 (어디서 들어와 어디로 나가나).
- **외부 IO**: TODO — 이 패키지가 건드리는 바깥 자원을 적으세요 (데이터베이스 / 큐 / 외부 API / 파일).
- **테스트 진입점**: TODO — 이 패키지를 검증할 때 무엇부터 보나.
- **함정**: TODO — 이 패키지 특유의 주의사항 3개 이내.
- **관련 설계 문서 / 결정 기록**: TODO.
"""


def render_package_catalog(target: Path, base_package: Path, packages: list[Path],
                           stack: str = "jvm") -> str:
    sections = []
    for pkg in packages:
        role = detect_package_role(pkg, stack)
        endpoints = collect_endpoints(pkg)
        endpoints_str = ", ".join(f"`{e}`" for e in endpoints) if endpoints else "TODO — 패키지의 외부 노출 endpoint 를 적으세요."
        sections.append(PACKAGE_SECTION_TEMPLATE.format(
            name=pkg.name,
            role=role,
            endpoints=endpoints_str,
        ))
    base_rel = base_package.relative_to(target)
    return PACKAGE_CATALOG_TEMPLATE.format(
        base_package=base_rel,
        total=len(packages),
        sections="\n".join(sections),
    )


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
    # 단일 모듈 분기 — 빌드 매니페스트가 루트에만 있는 경우 패키지 카탈로그 스캐폴드 생성
    non_root = [m for m in modules if m != Path(".")]
    if not non_root:
        layout = stacks.detect_layout(target)
        if layout is None:
            # 안내문만 찍고 0으로 끝내지 않는다. 그러면 산출물 0개인 실행과 성공한 실행이
            # 호출한 쪽에서 똑같아 보인다.
            print(stacks.unsupported_message(target), file=sys.stderr)
            return EXIT_NO_ADAPTER
        base_package = layout.source_root
        packages = find_packages(base_package)
        if not packages:
            print(f"단일 모듈({layout.stack}) — 기준점 {base_package.relative_to(target)} 아래 "
                  f"코드가 든 디렉토리가 없다. 근거: {layout.evidence}", file=sys.stderr)
            return EXIT_NO_PACKAGES
        catalog_path = out_dir / "PACKAGES.md"
        catalog_path.write_text(
            render_package_catalog(target, base_package, packages, layout.stack), encoding="utf-8")
        print(f"단일 모듈({layout.stack}) — 패키지 카탈로그 스캐폴드 생성: {catalog_path}")
        print(f"  기준점: {base_package.relative_to(target)} (근거: {layout.evidence})")
        print(f"  감지된 패키지 {len(packages)}개: {', '.join(p.name for p in packages)}")
        print(f"  → 검토 후 docs/PACKAGES.md 로 복사하세요.")
        return EXIT_OK
    selected = select_top_modules(target, modules, top_n)
    # datetime.now() 는 비멱등 — 같은 입력을 재생성할 때마다 '최종 검토일' 이 바뀌어 무의미한
    # diff 가 난다. 스캐폴드는 '초안' 이라 검토일은 사람이 검토 후 채우는 placeholder 로 둔다.
    today = "TODO: 검토일 기입"
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
            design_pointer_block=render_design_pointer_block(target, str(m)),
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
    return EXIT_OK


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
    sys.exit(run(target, out_dir, args.top))


if __name__ == "__main__":
    main()
