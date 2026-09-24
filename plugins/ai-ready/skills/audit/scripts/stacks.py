#!/usr/bin/env python3
"""stacks.py — 단일 모듈 저장소에서 '논리 모듈' 이 어디서부터 시작하는지를 스택별로 답한다.

이 질문의 답은 언어마다 다르다. 그런데 그 답이 audit.py 와 scaffold.py 에 각각 JVM 으로만
하드코딩돼 두 벌로 복사돼 있었다(`JVM_SOURCE_ROOTS` · `APPLICATION_MARKERS`). 스택을 하나
늘리려면 두 곳을 고쳐야 했고, 한쪽만 고치면 채점과 생성이 서로 다른 자리를 본다. 어댑터를
여기 한 곳에 모아 둘이 같이 쓴다.

**새 스택을 더하는 법**: 아래 `ADAPTERS` 에 `(이름, 함수)` 한 줄을 더한다. 함수는
`SourceLayout` 또는 `None` 을 낸다. 호출부는 이 목록을 훑으므로 등록 말고 고칠 곳이 없다.

**어댑터가 없는 스택은 조용히 넘어가지 않는다.** 호출부가 `unsupported_message()` 를 찍고
0이 아닌 값으로 끝낸다. 종전에는 JVM 이 아니면 안내문 한 줄을 찍고 종료코드 0으로 끝나서,
산출물 0개인 실행과 성공한 실행이 호출한 쪽에서 구분되지 않았다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# 소스가 아닌 디렉토리. 패키지 후보를 셀 때와 마커를 찾을 때 둘 다 걸러야 산출물 안의
# 생성 코드가 논리 모듈로 둔갑하지 않는다.
EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "__pycache__", ".venv", "venv", "vendor", ".next", "out", "coverage",
    ".mypy_cache", ".pytest_cache", ".tox", "bin", "obj",
    ".turbo", "worktrees", ".ai-ready",
}

# 모듈 경계를 알리는 빌드 매니페스트. 루트가 아닌 디렉토리에 하나라도 있으면 멀티 모듈로 본다.
MODULE_MANIFESTS = {
    "build.gradle.kts", "build.gradle", "pom.xml",
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml", "setup.py",
}

CODE_EXTS = {
    ".kt", ".java", ".scala", ".groovy",
    ".ts", ".tsx", ".js", ".jsx", ".mjs",
    ".py", ".rs", ".go", ".rb", ".php", ".cs", ".swift",
}

# 루트 매니페스트 — 어댑터가 못 맞췄을 때 무엇을 봤는지 사람에게 말해 주기 위한 목록.
ROOT_MANIFESTS = (
    "build.gradle.kts", "build.gradle", "pom.xml", "package.json",
    "pyproject.toml", "setup.py", "setup.cfg", "go.mod", "Cargo.toml",
    "Package.swift", "Gemfile", "composer.json",
)


@dataclass(frozen=True)
class SourceLayout:
    """단일 모듈 저장소의 논리 모듈 기준점.

    `source_root` 의 **직속 자식 디렉토리**가 논리 모듈이다. JVM 이면 base package,
    Node 면 `src/`, Python 이면 배포 패키지 디렉토리가 거기 온다.
    """

    stack: str
    source_root: Path
    evidence: str  # 무엇을 보고 그렇게 판정했나 (보고·근거용)


def _excluded(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(p in EXCLUDE_DIRS for p in parts)


def _first_dir(target: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = target / name
        if candidate.is_dir():
            return candidate
    return None


def _descend_package_chain(root: Path) -> Path:
    """`com/example/app` 처럼 한 갈래로만 이어지는 패키지 사슬을 끝까지 내려간다.

    자식 디렉토리가 둘 이상이거나 그 디렉토리에 소스 파일이 있으면 거기가 base package다.
    Application 클래스가 없는 라이브러리 모듈에도 통한다.
    """
    current = root
    while True:
        try:
            children = [c for c in sorted(current.iterdir())
                        if c.is_dir() and c.name not in EXCLUDE_DIRS and not c.name.startswith(".")]
            has_source = any(f.is_file() and f.suffix in (".kt", ".java", ".scala", ".groovy")
                             for f in current.iterdir())
        except OSError:
            return current
        if len(children) != 1 or has_source:
            return current
        current = children[0]


def _jvm(target: Path) -> SourceLayout | None:
    """JVM: 소스 루트 아래 base package(패키지 사슬이 갈라지는 첫 디렉토리)를 찾는다.

    Application 클래스가 있으면 그것이 가장 정확한 신호라 먼저 본다. 마커는 `*Application.kt`
    처럼 접두를 허용한다 — 스프링 관례가 `FooApplication.kt` 라서 정확히 `Application.kt` 로만
    보면 실제 프로젝트 대부분을 놓친다. 마커가 여럿이면 경로가 가장 짧은 것을 택한다. `rglob`
    은 순서를 보장하지 않아 첫 매칭을 그냥 쓰면 실행·머신마다 base package 가 달라진다.

    마커가 없으면(라이브러리 모듈) 패키지 사슬을 내려가 base package 를 잡는다.
    """
    for rel in ("src/main/kotlin", "src/main/java"):
        root = target / rel
        if not root.is_dir():
            continue
        hits: list[Path] = []
        for marker in ("*Application.kt", "*Application.java"):
            try:
                hits.extend(h for h in root.rglob(marker) if not _excluded(h, root))
            except OSError:
                continue
        if hits:
            best = min(hits, key=lambda p: (len(p.parts), str(p)))
            return SourceLayout("jvm", best.parent, f"{rel} 아래 {best.name}")
        base = _descend_package_chain(root)
        if base != root:
            return SourceLayout("jvm", base, f"{rel} 의 패키지 사슬 (Application 클래스 없음)")
    return None


def _node(target: Path) -> SourceLayout | None:
    """Node/TypeScript: 루트 package.json + 소스 디렉토리."""
    if not (target / "package.json").is_file():
        return None
    root = _first_dir(target, ("src", "lib", "app"))
    if root is None:
        return None
    return SourceLayout("node", root, f"package.json + {root.name}/")


def _python(target: Path) -> SourceLayout | None:
    """Python: src 레이아웃이면 배포 패키지 디렉토리, 평면 레이아웃이면 루트의 패키지."""
    if not any((target / m).is_file() for m in ("pyproject.toml", "setup.py", "setup.cfg")):
        return None
    src = target / "src"
    if src.is_dir():
        pkgs = [d for d in sorted(src.iterdir())
                if d.is_dir() and (d / "__init__.py").is_file()]
        if len(pkgs) == 1:
            return SourceLayout("python", pkgs[0], f"src/{pkgs[0].name}/__init__.py")
        if pkgs:
            # 배포 패키지가 여럿이면 그것들 자체가 논리 모듈이다.
            return SourceLayout("python", src, f"src/ 아래 배포 패키지 {len(pkgs)}개")
    pkgs = [d for d in sorted(target.iterdir())
            if d.is_dir() and not d.name.startswith(".") and d.name not in EXCLUDE_DIRS
            and (d / "__init__.py").is_file()]
    if len(pkgs) == 1:
        return SourceLayout("python", pkgs[0], f"{pkgs[0].name}/__init__.py")
    return None


def _go(target: Path) -> SourceLayout | None:
    """Go: internal/ 또는 pkg/ 가 있으면 그것이 기준점, 없으면 모듈 루트."""
    if not (target / "go.mod").is_file():
        return None
    root = _first_dir(target, ("internal", "pkg"))
    if root is not None:
        return SourceLayout("go", root, f"go.mod + {root.name}/")
    return SourceLayout("go", target, "go.mod (모듈 루트가 곧 패키지 루트)")


def _rust(target: Path) -> SourceLayout | None:
    """Rust: Cargo.toml + src/."""
    if not (target / "Cargo.toml").is_file():
        return None
    src = target / "src"
    if not src.is_dir():
        return None
    return SourceLayout("rust", src, "Cargo.toml + src/")


# 등록만으로 스택이 늘어난다. 순서는 매니페스트가 겹칠 때의 우선순위다
# (예: Gradle 프로젝트에 프론트엔드용 package.json 이 함께 있으면 JVM 을 먼저 본다).
ADAPTERS: tuple[tuple[str, Callable[[Path], "SourceLayout | None"]], ...] = (
    ("jvm", _jvm),
    ("node", _node),
    ("python", _python),
    ("go", _go),
    ("rust", _rust),
)


def known_stacks() -> tuple[str, ...]:
    return tuple(name for name, _ in ADAPTERS)


def detect_layout(target: Path) -> SourceLayout | None:
    """등록된 어댑터를 순서대로 훑어 첫 번째로 맞는 레이아웃을 낸다."""
    for _, adapter in ADAPTERS:
        layout = adapter(target)
        if layout is not None:
            return layout
    return None


def unsupported_message(target: Path) -> str:
    """어댑터가 하나도 안 맞았을 때 사람이 다음 행동을 정할 수 있는 문장.

    "수동으로 작성하세요" 로 끝내지 않는다 — 무엇을 봤고 무엇이 없어서 못 했는지,
    그리고 어디에 어댑터를 더하면 되는지까지 말한다.
    """
    found = [m for m in ROOT_MANIFESTS if (target / m).is_file()]
    seen = ", ".join(found) if found else "없음"
    return (
        f"논리 모듈 기준점을 못 찾았다 — 등록된 스택 어댑터({', '.join(known_stacks())}) 중 "
        f"맞는 것이 없다.\n"
        f"  루트 매니페스트: {seen}\n"
        f"  대상: {target}\n"
        f"  이 스택을 지원하려면 skills/audit/scripts/stacks.py 의 ADAPTERS 에 어댑터를 더한다. "
        f"어댑터는 '논리 모듈의 부모 디렉토리가 어디인가' 하나만 답하면 된다."
    )


# --- 모듈 목록 ---------------------------------------------------------------

@dataclass(frozen=True)
class ModuleLayout:
    """모듈 CLAUDE.md 를 둘 자리 목록.

    mode:
      - "multi": 루트가 아닌 디렉토리에 빌드 매니페스트가 있다. 그 디렉토리들이 모듈이다.
      - "single": 매니페스트가 루트에만 있고, 스택 어댑터가 찾은 기준점의 직속 하위가 모듈이다.
      - "no-adapter": 매니페스트가 루트에만 있는데 맞는 스택 어댑터가 없다.
      - "no-code": 어댑터는 맞았는데 기준점 아래에 코드가 든 디렉토리가 없다.
    """

    mode: str
    modules: tuple[Path, ...] = ()  # target 기준 상대 경로
    layout: SourceLayout | None = None


def _walk(target: Path):
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        yield Path(dirpath), dirnames, filenames


def find_manifest_modules(target: Path) -> list[Path]:
    """빌드 매니페스트가 있는 디렉토리(루트 포함, target 기준 상대 경로)."""
    out = []
    for dirpath, _, filenames in _walk(target):
        if any(f in MODULE_MANIFESTS for f in filenames):
            out.append(dirpath.relative_to(target))
    return sorted(out, key=str)


def _has_code(directory: Path) -> bool:
    for dirpath, _, filenames in _walk(directory):
        if any(Path(f).suffix in CODE_EXTS for f in filenames):
            return True
    return False


def find_packages(source_root: Path) -> list[Path]:
    """기준점의 직속 하위 디렉토리 중 코드 파일이 하나라도 있는 것 = 논리 모듈."""
    if not source_root.is_dir():
        return []
    out = []
    for child in sorted(source_root.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.name in EXCLUDE_DIRS or child.name.startswith("."):
            continue
        if _has_code(child):
            out.append(child)
    return out


def logical_modules(target: Path) -> ModuleLayout:
    """모듈 CLAUDE.md 를 둘 자리를 정한다. audit 과 scaffold 가 같은 답을 쓰도록 여기 한 곳에 둔다."""
    non_root = [m for m in find_manifest_modules(target) if m != Path(".")]
    if non_root:
        return ModuleLayout("multi", tuple(non_root))
    layout = detect_layout(target)
    if layout is None:
        return ModuleLayout("no-adapter")
    packages = find_packages(layout.source_root)
    if not packages:
        return ModuleLayout("no-code", (), layout)
    return ModuleLayout("single", tuple(p.relative_to(target) for p in packages), layout)


# --- 확인 명령 ---------------------------------------------------------------
#
# verify.sh 와 루트 CLAUDE.md 의 "확인 명령" 이 쓰는 명령을 루트 매니페스트에서 고른다.
# 못 고른 역할은 빈 채로 둔다 — 지어낸 명령은 매번 실패하는 검사가 되어 사람이 그 검사를 끄게 만든다.

_GRADLE_FILES = ("build.gradle.kts", "build.gradle", "settings.gradle.kts", "settings.gradle")


@dataclass(frozen=True)
class Commands:
    build_system: str
    typecheck: str = ""
    lint: str = ""
    test: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def checks(self) -> list[tuple[str, str]]:
        """(역할, 명령) — 빈 역할은 뺀다. 순서는 싼 것부터."""
        return [(role, cmd) for role, cmd in
                (("typecheck", self.typecheck), ("lint", self.lint), ("test", self.test)) if cmd]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def npm_scripts(target: Path) -> dict[str, str]:
    try:
        pkg = json.loads(_read(target / "package.json") or "{}")
    except json.JSONDecodeError:
        return {}
    scripts = pkg.get("scripts") if isinstance(pkg, dict) else None
    return {str(k): str(v) for k, v in scripts.items()} if isinstance(scripts, dict) else {}


def npm_runner(target: Path) -> str:
    if (target / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (target / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _is_npm_test_stub(body: str) -> bool:
    # `npm init` 이 넣는 자리표시("no test specified" && exit 1)는 테스트가 아니다.
    low = body.lower()
    return "no test specified" in low and "exit 1" in low


def _node_commands(target: Path) -> Commands:
    pm = npm_runner(target)
    scripts = npm_scripts(target)
    run = (lambda s: f"{pm} run {s}")
    typecheck = next((run(n) for n in ("typecheck", "type-check", "tsc", "check-types") if n in scripts), "")
    notes = []
    if not typecheck and (target / "tsconfig.json").is_file():
        typecheck = "npx tsc --noEmit"
        notes.append("typecheck: package.json 에 타입 검사 스크립트가 없어 tsconfig.json 으로 tsc 를 골랐다")
    lint = run("lint") if "lint" in scripts else ""
    test = f"{pm} test" if "test" in scripts and not _is_npm_test_stub(scripts["test"]) else ""
    return Commands(pm, typecheck, lint, test, tuple(notes))


def _python_commands(target: Path) -> Commands:
    pyproject = _read(target / "pyproject.toml").lower()
    setup_cfg = _read(target / "setup.cfg").lower()
    typecheck = ""
    if ("[tool.mypy" in pyproject or "[mypy" in setup_cfg
            or (target / "mypy.ini").is_file() or (target / ".mypy.ini").is_file()):
        typecheck = "mypy ."
    elif "[tool.pyright" in pyproject or (target / "pyrightconfig.json").is_file():
        typecheck = "pyright"
    lint = ""
    if "[tool.ruff" in pyproject or (target / "ruff.toml").is_file() or (target / ".ruff.toml").is_file():
        lint = "ruff check ."
    elif (target / ".flake8").is_file() or "[flake8]" in setup_cfg:
        lint = "flake8"
    if ("pytest" in pyproject or (target / "pytest.ini").is_file()
            or (target / "conftest.py").is_file() or (target / "tests" / "conftest.py").is_file()):
        test = "pytest"
    else:
        test = "python3 -m unittest"
    return Commands("python", typecheck, lint, test)


def detect_commands(target: Path) -> Commands:
    """루트 매니페스트로 빌드 시스템을 고르고 typecheck·lint·test 명령을 추론한다."""
    has = (lambda f: (target / f).is_file())
    if any(has(f) for f in _GRADLE_FILES):
        g = "./gradlew" if has("gradlew") else "gradle"
        text = "".join(_read(target / f) for f in _GRADLE_FILES).lower()
        lint = ""
        if "ktlint" in text:
            lint = f"{g} ktlintCheck"
        elif "spotless" in text:
            lint = f"{g} spotlessCheck"
        elif "detekt" in text:
            lint = f"{g} detekt"
        return Commands("gradle", f"{g} testClasses", lint, f"{g} test")
    if has("pom.xml"):
        mvn = "./mvnw" if has("mvnw") else "mvn"
        pom = _read(target / "pom.xml").lower()
        lint = ""
        if "spotless-maven-plugin" in pom:
            lint = f"{mvn} spotless:check"
        elif "checkstyle" in pom:
            lint = f"{mvn} checkstyle:check"
        return Commands("maven", f"{mvn} -q test-compile", lint, f"{mvn} test")
    if has("package.json"):
        return _node_commands(target)
    if has("Cargo.toml"):
        return Commands("cargo", "cargo check --all-targets", "cargo clippy --all-targets", "cargo test")
    if has("go.mod"):
        lint = "golangci-lint run" if any(
            has(f) for f in (".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json")) \
            else "go vet ./..."
        return Commands("go", "go build ./...", lint, "go test ./...")
    if has("pyproject.toml") or has("setup.py") or has("setup.cfg"):
        return _python_commands(target)
    return Commands("unknown")
