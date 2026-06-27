#!/usr/bin/env python3
"""빌드 시스템·스택·컨벤션 문서 런타임 감지기 (ai-ready plugin 의 loop 엔진용, v0.5.0+).

대상 코드베이스를 훑어 무인 검증 loop(`/loop-run`·`/loop-review`·`/loop-lessons`)이
그 프로젝트에서 돌 때 필요한 사실을 추론한다:

  1. 빌드 시스템 (gradle / maven / npm / cargo / go / python) → 빌드·테스트·린트 명령
  2. 스택 (Spring / JPA / PostgreSQL) → LOCAL rubric 에 심을 종류(kind) 후보
  3. 컨벤션 문서 (ANTIPATTERNS / CONVENTIONS / NAMING …) → 점검 기준 문서 목록 + 영구 지식층
  4. 티켓 패턴 (브랜치·커밋에서 JIRA 키 추론) + 베이스 브랜치

이 모듈은 *감지만* 한다 — 파일을 쓰지 않는다. loop 스킬이 Step 0 에서 이걸 호출해 JSON 을
받아 `$LOOP_*` 환경변수를 채운다(어댑터 파일을 만들지 않는다 — 파생 가능한 값을 굳히지
않는 단일 원본 원칙). 같은 감지 로직을 audit 채점이나 진단에서도 재사용한다.

stdlib-only — json / subprocess / pathlib / re 만 사용.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

__all__ = ["detect", "detect_build_system", "detect_stack", "detect_convention_docs",
           "local_kinds_for_stack", "infer_ticket_regex", "detect_base_branch"]

# 빌드 매니페스트 → 빌드 시스템 키. audit.py 의 BUILD_MANIFESTS 와 같은 신호를 쓰되,
# 여기선 *루트* 매니페스트로 빌드 시스템 한 종을 고른다(모듈 열거가 아니라 명령 추론이 목적).
_GRADLE_FILES = ("build.gradle.kts", "build.gradle", "settings.gradle.kts", "settings.gradle")

# 컨벤션 문서 후보 — 대소문자 무시 basename 매칭. knowledge_layer 는 ANTIPATTERNS 우선.
_CONVENTION_DOC_NAMES = (
    "ANTIPATTERNS.md", "ANTI_PATTERNS.md",
    "CONVENTIONS.md", "NAMING.md",
    "API_COMPATIBILITY.md", "ERROR_HANDLING.md",
    "DDL_DML.md", "TESTING.md", "ARCHITECTURE.md",
)
_CONVENTION_DOC_DIRS = ("docs", ".")  # docs/ 우선, 루트도 본다

# 트리 walk 시 가지치기할 디렉토리 — audit.py 와 같은 집합. 특히 worktrees/.claude 는
# repo 전체 복사본이라 중복 매칭·비용을 막으려 반드시 제외한다.
_EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "dist", "target", ".gradle", ".idea",
    "out", "bin", "vendor", ".venv", "venv", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".mypy_cache", ".ai-ready", "worktrees", ".claude",
}


def _iter_files(target: Path, match, max_dirs: int = 4000):
    """target 하위를 가지치기하며 walk, match(filename)→True 인 파일 Path 를 yield.

    멀티모듈(서브모듈 src/) 대응 — 루트 src/ 만 보던 한계를 없앤다. worktrees/build 등은
    가지치기하고, 디렉토리 수 상한으로 거대 repo 폭주를 막는다(상한 도달 시 조용히 멈춤).
    """
    seen = 0
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS and not d.startswith(".")]
        seen += 1
        if seen > max_dirs:
            return
        for f in filenames:
            if match(f):
                yield Path(dirpath) / f


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _git(target: Path, *args: str) -> str:
    """대상 repo 에서 git 실행 — 실패·미설치·비-git 이면 빈 문자열(절대 예외 전파 안 함)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(target), *args],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


# --- 빌드 시스템 ----------------------------------------------------------

def _gradle_lint_cmd(target: Path, gradle: str) -> str:
    """루트 gradle 파일 텍스트에서 린트 플러그인을 감지해 대응 task 를 고른다."""
    text = "".join(_read(target / f) for f in _GRADLE_FILES).lower()
    if "ktlint" in text:
        return f"{gradle} ktlintCheck"
    if "spotless" in text:
        return f"{gradle} spotlessCheck"
    if "detekt" in text:
        return f"{gradle} detekt"
    return ""


def _npm_scripts(target: Path) -> dict[str, str]:
    try:
        pkg = json.loads(_read(target / "package.json") or "{}")
    except json.JSONDecodeError:
        return {}
    scripts = pkg.get("scripts")
    return scripts if isinstance(scripts, dict) else {}


def _npm_pm(target: Path) -> str:
    if (target / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (target / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _python_test_cmd(target: Path) -> str:
    pyproject = _read(target / "pyproject.toml").lower()
    if "pytest" in pyproject or (target / "pytest.ini").is_file() or (target / "tox.ini").is_file():
        return "pytest"
    return "python -m unittest"


def _python_lint_cmd(target: Path) -> str:
    pyproject = _read(target / "pyproject.toml").lower()
    if "[tool.ruff" in pyproject or (target / "ruff.toml").is_file() or (target / ".ruff.toml").is_file():
        return "ruff check ."
    if (target / ".flake8").is_file() or "[flake8]" in _read(target / "setup.cfg").lower():
        return "flake8"
    return ""


def detect_build_system(target: Path) -> dict[str, str]:
    """루트 매니페스트로 빌드 시스템을 고르고 빌드·테스트·린트 명령을 추론한다.

    Returns dict(build_system, build_cmd, test_cmd, lint_cmd). 감지 실패 시 unknown + 빈 명령.
    빌드 명령은 *테스트 제외 컴파일* 을 기본으로 한다(게이트 단계가 빠르게 컴파일만 확인하도록).
    """
    has = lambda f: (target / f).is_file()  # noqa: E731

    # Gradle — gradlew 있으면 래퍼 우선(프로젝트 고정 버전).
    if any(has(f) for f in _GRADLE_FILES):
        gradle = "./gradlew" if has("gradlew") else "gradle"
        return {
            "build_system": "gradle",
            "build_cmd": f"{gradle} assemble -x test",
            "test_cmd": f"{gradle} test",
            "lint_cmd": _gradle_lint_cmd(target, gradle),
        }

    # Maven
    if has("pom.xml"):
        mvn = "./mvnw" if has("mvnw") else "mvn"
        pom = _read(target / "pom.xml").lower()
        lint = ""
        if "spotless-maven-plugin" in pom:
            lint = f"{mvn} spotless:check"
        elif "maven-checkstyle-plugin" in pom or "checkstyle" in pom:
            lint = f"{mvn} checkstyle:check"
        return {
            "build_system": "maven",
            "build_cmd": f"{mvn} -q -DskipTests compile",
            "test_cmd": f"{mvn} test",
            "lint_cmd": lint,
        }

    # npm / pnpm / yarn — package.json 의 scripts 에 있는 것만 명령으로 채택.
    if has("package.json"):
        pm = _npm_pm(target)
        scripts = _npm_scripts(target)
        run = lambda s: f"{pm} run {s}"  # noqa: E731
        build_cmd = run("build") if "build" in scripts else ""
        # npm/yarn/pnpm 은 test 가 최상위 명령(`npm test`)이라 run 없이.
        test_cmd = f"{pm} test" if "test" in scripts else ""
        lint_cmd = run("lint") if "lint" in scripts else ""
        return {
            "build_system": pm,
            "build_cmd": build_cmd,
            "test_cmd": test_cmd,
            "lint_cmd": lint_cmd,
        }

    # Cargo
    if has("Cargo.toml"):
        return {
            "build_system": "cargo",
            "build_cmd": "cargo build",
            "test_cmd": "cargo test",
            "lint_cmd": "cargo clippy",
        }

    # Go
    if has("go.mod"):
        return {
            "build_system": "go",
            "build_cmd": "go build ./...",
            "test_cmd": "go test ./...",
            "lint_cmd": "go vet ./...",
        }

    # Python
    if has("pyproject.toml") or has("setup.py"):
        return {
            "build_system": "python",
            "build_cmd": "",  # 라이브러리는 별도 빌드 단계가 없는 경우가 흔함 — 게이트는 테스트로 충분
            "test_cmd": _python_test_cmd(target),
            "lint_cmd": _python_lint_cmd(target),
        }

    return {"build_system": "unknown", "build_cmd": "", "test_cmd": "", "lint_cmd": ""}


# --- 스택 ----------------------------------------------------------------

def _all_manifest_text(target: Path) -> str:
    """루트 빌드 매니페스트 + 흔한 설정 파일 텍스트를 모아 소문자로 반환(스택 신호 grep 용)."""
    names = list(_GRADLE_FILES) + [
        "pom.xml", "package.json", "Cargo.toml", "go.mod", "pyproject.toml",
        "gradle/libs.versions.toml",  # gradle version catalog
    ]
    text = "".join(_read(target / n) for n in names)
    # application 설정·compose 도 본다(특히 postgres 신호). 멀티모듈이라 서브모듈의
    # application*.* 까지 가지치기 walk 로 모은다(상한 내). 신호 grep 이라 일부만 봐도 충분.
    for cfg in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        text += _read(target / cfg)
    grabbed = 0
    for p in _iter_files(target, lambda f: f.startswith("application") and f.endswith(
            (".yml", ".yaml", ".properties"))):
        text += _read(p)
        grabbed += 1
        if grabbed >= 30:  # 신호 감지엔 충분 — 거대 repo 에서 무한 누적 방지
            break
    return text.lower()


def detect_stack(target: Path) -> list[str]:
    """Spring / JPA / PostgreSQL 등 스택 신호를 감지(소문자 키 리스트)."""
    text = _all_manifest_text(target)
    stack: list[str] = []
    if "org.springframework.boot" in text or "spring-boot" in text or "springframework" in text:
        stack.append("spring")
    if ("data-jpa" in text or "jakarta.persistence" in text
            or "javax.persistence" in text or "hibernate" in text):
        stack.append("jpa")
    if "postgresql" in text or "jdbc:postgresql" in text or "org.postgresql" in text:
        stack.append("postgres")
    return stack


def _has_i18n_error_code(target: Path) -> bool:
    """i18n 키 누락 종류를 심을 근거 — ErrorCode 소스 또는 message(s).properties 존재.

    멀티모듈(core-common/src/...)까지 가지치기 walk 로 본다. 첫 매치에서 멈춘다.
    """
    def _match(f: str) -> bool:
        return (f in ("ErrorCode.kt", "ErrorCode.java")
                or (f.startswith(("message", "messages")) and f.endswith(".properties")))
    return next(_iter_files(target, _match), None) is not None


def local_kinds_for_stack(target: Path, stack: list[str]) -> list[dict[str, str]]:
    """감지된 스택에 대응하는 LOCAL rubric 종류(kind) 후보를 만든다.

    각 종류는 BASE 와 병합돼 채점된다(같은 kind/dimension 은 LOCAL override). 전부 *후보* 다 —
    rubric.md 는 사람이 검토하는 문서이고, 맞지 않으면 지우면 된다.
    1차 범위는 c8c 스택(Spring/JPA/PostgreSQL)만. 점진 확장.
    """
    kinds: list[dict[str, str]] = []
    if "spring" in stack and _has_i18n_error_code(target):
        kinds.append({
            "kind_id": "i18n-key-missing", "dimension": "convention", "layer": "gate",
            "base_severity": "MAJOR", "force_await": "no",
            "note": "새 ErrorCode 에 대응하는 i18n 메시지 키 누락 (Spring ErrorCode 감지)",
        })
    if "postgres" in stack:
        kinds.append({
            "kind_id": "ddl-safety", "dimension": "runtime", "layer": "gate",
            "base_severity": "BLOCKER", "force_await": "always",
            "note": "NOT NULL 추가·컬럼 DROP·ALTER TYPE·비CONCURRENTLY 인덱스 (PostgreSQL 감지)",
        })
    return kinds


# --- 컨벤션 문서 ----------------------------------------------------------

def detect_convention_docs(target: Path) -> tuple[list[str], str]:
    """존재하는 컨벤션 문서 경로 목록 + 영구 지식층(ANTIPATTERNS 우선) 을 반환.

    Returns (convention_docs[rel paths], knowledge_layer rel path or "").
    """
    found: list[str] = []
    knowledge = ""
    seen = set()
    for d in _CONVENTION_DOC_DIRS:
        base = target / d if d != "." else target
        if not base.is_dir():
            continue
        # 대소문자 무시 매칭 — 실제 파일명을 한 번만 훑는다.
        try:
            actual = {p.name.lower(): p for p in base.iterdir() if p.is_file()}
        except OSError:
            continue
        for name in _CONVENTION_DOC_NAMES:
            p = actual.get(name.lower())
            if p is None:
                continue
            rel = str(p.relative_to(target))
            key = rel.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(rel)
            if name.upper().startswith("ANTIPATTERN") and not knowledge:
                knowledge = rel
    return found, knowledge


# --- 티켓 패턴 / 베이스 브랜치 --------------------------------------------

_JIRA_KEY = re.compile(r"\b([A-Z][A-Z0-9]+)-\d+\b")


def infer_ticket_regex(target: Path) -> str:
    """브랜치명·최근 커밋 제목에서 JIRA 키 접두어를 추론해 정규식을 만든다.

    가장 많이 등장한 접두어로 `PREFIX-[0-9]+` 를 만든다. 신호가 없으면 generic 기본값.
    """
    sources = []
    cur = _git(target, "rev-parse", "--abbrev-ref", "HEAD")
    if cur:
        sources.append(cur)
    branches = _git(target, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    if branches:
        sources.extend(branches.splitlines())
    log = _git(target, "log", "--oneline", "-50", "--format=%s")
    if log:
        sources.extend(log.splitlines())

    counts: dict[str, int] = {}
    for s in sources:
        for m in _JIRA_KEY.finditer(s.upper()):
            prefix = m.group(1)
            counts[prefix] = counts.get(prefix, 0) + 1
    if not counts:
        return "[A-Z]+-[0-9]+"  # generic — 사람이 좁히도록
    best = max(counts, key=lambda k: counts[k])
    return f"{best}-[0-9]+"


def detect_base_branch(target: Path) -> str:
    """원격 기본 브랜치를 감지(origin/main 또는 origin/master). 실패 시 origin/main."""
    head = _git(target, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if head:
        # refs/remotes/origin/main → origin/main
        return head.replace("refs/remotes/", "", 1)
    for cand in ("origin/main", "origin/master"):
        if _git(target, "rev-parse", "--verify", "--quiet", cand):
            return cand
    return "origin/main"


# --- 종합 ----------------------------------------------------------------

def detect(target: Path) -> dict[str, Any]:
    """대상 코드베이스의 loop 어댑터 입력을 한 번에 감지해 descriptor dict 로 반환."""
    target = Path(target).resolve()
    build = detect_build_system(target)
    stack = detect_stack(target)
    convention_docs, knowledge_layer = detect_convention_docs(target)
    return {
        "target": str(target),
        "build_system": build["build_system"],
        "build_cmd": build["build_cmd"],
        "test_cmd": build["test_cmd"],
        "lint_cmd": build["lint_cmd"],
        "stack": stack,
        "convention_docs": convention_docs,
        "knowledge_layer": knowledge_layer,
        "ticket_regex": infer_ticket_regex(target),
        "base_branch": detect_base_branch(target),
        "local_kinds": local_kinds_for_stack(target, stack),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="loop 어댑터용 빌드/스택/문서 감지기")
    ap.add_argument("--target", required=True, help="대상 코드베이스 경로")
    ap.add_argument("--out", help="감지 결과 JSON 출력 경로 (생략 시 stdout)")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"오류: 대상이 디렉토리가 아님: {target}", file=sys.stderr)
        sys.exit(2)
    result = detect(target)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
        print(f"감지 결과: {out}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
